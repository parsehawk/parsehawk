"""OpenAI-compatible extraction engine driving every provider through one client.

The same ``openai.OpenAI`` client talks to OpenAI, Azure OpenAI (via its v1
endpoint), and any OpenAI-compatible server (the bundled vLLM, Ollama, …); only
``base_url``/``api_key``/``api_version`` differ. The payload adapter is chosen by
model: NuExtract3 variants keep their fine-tuned chat-template kwargs (sent via
``extra_body``), everything else uses the generic template + TYPES.md prompt.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from openai import APIConnectionError, APIStatusError, OpenAI

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
    api_version: str | None = None
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
            raw = self._post_chat(standard, extra_body)
        except ProviderRequestError as exc:
            if self._legacy_max_tokens or not _requires_legacy_max_tokens(exc):
                raise
            raise_if_cancelled()
            self._legacy_max_tokens = True
            raw = self._post_chat(standard, extra_body)

        raise_if_cancelled()
        self._debug_model_io("model runtime response: %s", raw)
        content = strip_generation_control_tokens(message_content_with_source(raw).text)
        if request.enable_thinking:
            content = strip_hidden_thinking(content)
        return ExtractionResponse(data=extract_json_object(content))

    def _post_chat(self, standard: dict[str, Any], extra_body: dict[str, Any]) -> dict[str, Any]:
        call_kwargs = dict(standard)
        if self._legacy_max_tokens and "max_completion_tokens" in call_kwargs:
            call_kwargs["max_tokens"] = call_kwargs.pop("max_completion_tokens")
        if extra_body:
            call_kwargs["extra_body"] = extra_body
        self._debug_model_io("model runtime request: %s", call_kwargs)
        try:
            completion = self._client.chat.completions.create(**call_kwargs)
        except APIStatusError as exc:
            message = getattr(exc, "message", str(exc))
            raise ProviderRequestError(
                f"model provider returned HTTP {exc.status_code}: {message}",
                status_code=exc.status_code,
            ) from exc
        except APIConnectionError as exc:
            raise ProviderRequestError(f"model provider is unreachable: {exc}") from exc
        return completion.model_dump()

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


def build_openai_client(
    *, base_url: str | None, api_key: str, api_version: str | None, timeout_seconds: int
) -> OpenAI:
    kwargs: dict[str, Any] = {"api_key": api_key or "EMPTY", "timeout": timeout_seconds}
    if base_url:
        kwargs["base_url"] = base_url
    if api_version:
        kwargs["default_query"] = {"api-version": api_version}
    return OpenAI(**kwargs)


def _build_client(config: OpenAIEngineConfig) -> OpenAI:
    return build_openai_client(
        base_url=config.base_url,
        api_key=config.api_key,
        api_version=config.api_version,
        timeout_seconds=config.timeout_seconds,
    )


def list_models(
    *,
    base_url: str | None,
    api_key: str,
    api_version: str | None = None,
    timeout_seconds: int = 30,
) -> list[str]:
    """List the model ids a provider offers (for the Web UI's model dropdown)."""
    client = build_openai_client(
        base_url=base_url,
        api_key=api_key,
        api_version=api_version,
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
