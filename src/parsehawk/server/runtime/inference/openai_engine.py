"""OpenAI-compatible extraction engine driving every provider through one client.

The same ``openai.OpenAI`` client talks to OpenAI, Microsoft Foundry's
OpenAI-compatible endpoint, and any OpenAI-compatible server (the bundled vLLM,
Ollama, …). The payload adapter is chosen by model: NuExtract3 variants keep
their fine-tuned chat-template kwargs (sent via ``extra_body``), everything else
uses the generic template + TYPES.md prompt.
"""

from __future__ import annotations

import json
import logging
from contextlib import nullcontext
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

import httpx
from openai import APIConnectionError, APIStatusError, OpenAI

from parsehawk import tracing
from parsehawk.core.application.ports import ExtractionRequest, ExtractionResponse
from parsehawk.core.domain.errors import ExtractionCancelled, ProviderRequestError
from parsehawk.core.domain.models import NUEXTRACT3_MODELS
from parsehawk.server.runtime.inference._response import (
    message_content_with_source,
    redact_model_io,
)
from parsehawk.server.runtime.inference.generic import (
    REASONING_NONE,
    RESPONSE_FORMAT_JSON_SCHEMA,
    build_generic_chat_payload,
)
from parsehawk.server.runtime.inference.nuextract import (
    build_chat_completion_payload,
    extract_json_object,
    strip_generation_control_tokens,
    strip_hidden_thinking,
)

logger = logging.getLogger("parsehawk.runtime")

ADAPTER_NUEXTRACT = "nuextract"
ADAPTER_GENERIC = "generic"
CANCELLATION_CHECK_INTERVAL_SECONDS = 1.0
FOUNDRY_DEPLOYMENTS_API_VERSION = "v1"

# OpenAI's /models payload does not expose endpoint capability metadata. Keep
# this filter specific to the first-party OpenAI provider so compatible servers
# can still advertise their own non-OpenAI model names.
_OPENAI_NON_CHAT_MODEL_MARKERS = (
    "whisper",
    "tts",
    "transcribe",
    "embedding",
    "moderation",
    "dall-e",
    "gpt-image",
    "image-",
    "realtime",
)

# Top-level OpenAI chat-completion params; everything else rides in extra_body.
_STANDARD_KEYS = frozenset(
    {
        "model",
        "messages",
        "temperature",
        "max_tokens",
        "max_completion_tokens",
        "response_format",
        "reasoning_effort",
    }
)


def select_adapter(model: str) -> str:
    """Pick the payload adapter for a model by exact NuExtract3 membership."""
    return ADAPTER_NUEXTRACT if model in NUEXTRACT3_MODELS else ADAPTER_GENERIC


def _requires_legacy_max_tokens(exc: ProviderRequestError) -> bool:
    """Whether a 400 means the server rejects `max_completion_tokens` (legacy server)."""
    return exc.status_code == 400 and "max_completion_tokens" in str(exc)


@dataclass(frozen=True)
class OpenAIEngineConfig:
    model: str
    base_url: str | None = None
    api_key: str = "EMPTY"
    max_tokens: int = 2048
    temperature: float = 0.2
    timeout_seconds: int = 600
    include_response_format: bool = True
    response_format_mode: str = RESPONSE_FORMAT_JSON_SCHEMA
    reasoning_mode: str = REASONING_NONE
    reasoning_effort: str = "medium"
    log_model_io: bool = False


class OpenAIExtractionEngine:
    """Extraction engine backed by the OpenAI SDK for one provider + model."""

    def __init__(self, config: OpenAIEngineConfig, client: OpenAI | None = None) -> None:
        self._config = config
        self._adapter = select_adapter(config.model)
        self._client = client if client is not None else _build_client(config)
        # The generic adapter sends `max_completion_tokens` (the go-forward param,
        # required by gpt-5/o-series). Some legacy OpenAI-compatible servers only
        # know `max_tokens`; we learn that from the first API error and convert for
        # the life of this engine so the common (modern) case never pays a retry.
        self._legacy_max_tokens = False

    def extract(
        self,
        request: ExtractionRequest,
        cancellation_check: Callable[[], bool] | None = None,
    ) -> ExtractionResponse:
        def raise_if_cancelled() -> None:
            if cancellation_check is not None and cancellation_check():
                raise ExtractionCancelled("extraction cancelled")

        standard, extra_body = self._build_payload(request)
        try:
            raise_if_cancelled()
            raw = self._post_chat(standard, extra_body, cancellation_check=raise_if_cancelled)
        except ProviderRequestError as exc:
            if self._legacy_max_tokens or not _requires_legacy_max_tokens(exc):
                raise
            raise_if_cancelled()
            self._legacy_max_tokens = True
            raw = self._post_chat(standard, extra_body, cancellation_check=raise_if_cancelled)

        raise_if_cancelled()
        self._debug_model_io("model runtime response: %s", raw)
        content = strip_generation_control_tokens(message_content_with_source(raw).text)
        if request.enable_thinking:
            content = strip_hidden_thinking(content)
        return ExtractionResponse(data=extract_json_object(content))

    def _post_chat(
        self,
        standard: dict[str, Any],
        extra_body: dict[str, Any],
        *,
        cancellation_check: Callable[[], None],
    ) -> dict[str, Any]:
        call_kwargs = dict(standard)
        if self._legacy_max_tokens and "max_completion_tokens" in call_kwargs:
            call_kwargs["max_tokens"] = call_kwargs.pop("max_completion_tokens")
        if extra_body:
            call_kwargs["extra_body"] = extra_body
        call_kwargs["stream"] = True
        self._debug_model_io("model runtime request: %s", call_kwargs)
        try:
            extra_body_context = (
                tracing.openai_extra_body_context(extra_body) if extra_body else nullcontext()
            )
            with extra_body_context:
                stream = self._client.chat.completions.create(**call_kwargs)
                content_parts: list[str] = []
                reasoning_parts: list[str] = []
                next_cancellation_check_at = monotonic()
                try:
                    for chunk in stream:
                        now = monotonic()
                        if now >= next_cancellation_check_at:
                            cancellation_check()
                            next_cancellation_check_at = now + CANCELLATION_CHECK_INTERVAL_SECONDS
                        chunk_data = chunk.model_dump()
                        choice = (chunk_data.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if isinstance(content, str):
                            content_parts.append(content)
                        for field in ("reasoning", "reasoning_content"):
                            reasoning = delta.get(field)
                            if isinstance(reasoning, str):
                                reasoning_parts.append(reasoning)
                finally:
                    close = getattr(stream, "close", None)
                    if close is not None:
                        close()
        except APIStatusError as exc:
            message = getattr(exc, "message", str(exc))
            raise ProviderRequestError(
                f"model provider returned HTTP {exc.status_code}: {message}",
                status_code=exc.status_code,
            ) from exc
        except APIConnectionError as exc:
            raise ProviderRequestError(f"model provider is unreachable: {exc}") from exc
        message: dict[str, str] = {}
        if content_parts:
            message["content"] = "".join(content_parts)
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        return {"choices": [{"message": message}]}

    def _build_payload(self, request: ExtractionRequest) -> tuple[dict[str, Any], dict[str, Any]]:
        if self._adapter == ADAPTER_NUEXTRACT:
            payload = build_chat_completion_payload(
                request,
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                enable_thinking=request.enable_thinking,
                include_response_format=self._config.include_response_format,
                include_enable_thinking_field=False,
            )
            return _split_payload(payload)
        return build_generic_chat_payload(
            request,
            model=self._config.model,
            max_completion_tokens=self._config.max_tokens,
            response_format_mode=self._config.response_format_mode,
            reasoning_mode=self._config.reasoning_mode,
            reasoning_effort=self._config.reasoning_effort,
        )

    def _debug_model_io(self, message: str, payload: dict[str, Any]) -> None:
        if not self._config.log_model_io or not logger.isEnabledFor(logging.DEBUG):
            return
        logger.debug(message, json.dumps(redact_model_io(payload), ensure_ascii=False))


def _split_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    standard = {key: value for key, value in payload.items() if key in _STANDARD_KEYS}
    extra_body = {key: value for key, value in payload.items() if key not in _STANDARD_KEYS}
    return standard, extra_body


def build_openai_client(*, base_url: str | None, api_key: str, timeout_seconds: int) -> OpenAI:
    kwargs: dict[str, Any] = {"api_key": api_key or "EMPTY", "timeout": timeout_seconds}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _build_client(config: OpenAIEngineConfig) -> OpenAI:
    return build_openai_client(
        base_url=config.base_url,
        api_key=config.api_key,
        timeout_seconds=config.timeout_seconds,
    )


def list_models(
    *,
    base_url: str | None,
    api_key: str,
    timeout_seconds: int = 30,
) -> list[str]:
    """List the model ids a provider offers (for the Web UI's model dropdown)."""
    client = build_openai_client(
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    try:
        page = client.models.list()
    except APIStatusError as exc:
        message = getattr(exc, "message", str(exc))
        raise ProviderRequestError(
            f"model provider returned HTTP {exc.status_code}: {message}",
            status_code=exc.status_code,
        ) from exc
    except APIConnectionError as exc:
        raise ProviderRequestError(f"model provider is unreachable: {exc}") from exc
    return [model.id for model in page.data]


def list_openai_chat_models(
    *,
    base_url: str | None,
    api_key: str,
    timeout_seconds: int = 30,
) -> list[str]:
    """List first-party OpenAI model ids that are plausible chat-completion models."""
    return [
        model
        for model in list_models(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        if _is_openai_chat_completion_model(model)
    ]


def _is_openai_chat_completion_model(model_id: str) -> bool:
    normalized = model_id.lower()
    if any(marker in normalized for marker in _OPENAI_NON_CHAT_MODEL_MARKERS):
        return False
    if normalized.startswith(("gpt-", "chatgpt-", "ft:gpt-", "ft:chatgpt-")):
        return True
    if len(normalized) >= 2 and normalized[0] == "o" and normalized[1].isdigit():
        return True
    return normalized.startswith("ft:o") and len(normalized) >= 5 and normalized[4].isdigit()


def list_foundry_chat_deployments(
    *,
    project_url: str | None,
    api_key: str,
    timeout_seconds: int = 30,
) -> list[str]:
    """List Microsoft Foundry deployment names usable by chat completions."""
    if not project_url:
        raise ProviderRequestError(
            "configure Microsoft Foundry project URL to list deployment names"
        )
    try:
        response = httpx.get(
            f"{project_url.rstrip('/')}/deployments",
            headers={"api-key": api_key},
            params={"api-version": FOUNDRY_DEPLOYMENTS_API_VERSION},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        message = _http_error_message(exc.response)
        raise ProviderRequestError(
            f"Microsoft Foundry deployments returned HTTP {exc.response.status_code}: {message}",
            status_code=exc.response.status_code,
        ) from exc
    except httpx.RequestError as exc:
        raise ProviderRequestError(
            f"Microsoft Foundry project endpoint is unreachable: {exc}"
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderRequestError("Microsoft Foundry deployments returned invalid JSON") from exc
    values = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        raise ProviderRequestError("Microsoft Foundry deployments response is missing value[]")
    return [
        name
        for deployment in values
        if isinstance(deployment, dict)
        if _deployment_supports_chat_completions(deployment)
        if isinstance(name := deployment.get("name"), str) and name
    ]


def _deployment_supports_chat_completions(deployment: dict[str, Any]) -> bool:
    capabilities = deployment.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    value = capabilities.get("chat_completion")
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _http_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(payload.get("message"), str):
            return payload["message"]
    return response.text
