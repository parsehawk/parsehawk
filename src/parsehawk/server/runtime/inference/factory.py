"""Resolve and cache an extraction engine per extractor.

Each extractor names a provider and model. The application service loads the
provider configuration and key inside a short Unit of Work, then passes those
immutable values here after the transaction closes. Engines are cached per
configuration, so a provider edit or key rotation yields a fresh client without
giving runtime code a database dependency.
"""

from __future__ import annotations

from typing import Any

from parsehawk.config import Settings
from parsehawk.core.application.ports import ResolvedExecutionConfig
from parsehawk.core.application.services import DEFAULT_PROVIDER_NAME
from parsehawk.core.domain.models import Extractor, Provider
from parsehawk.server.runtime.inference.openai_engine import (
    OpenAIEngineConfig,
    OpenAIExtractionEngine,
)


class EngineFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict[tuple[Any, ...], OpenAIExtractionEngine] = {}

    def resolve_extractor_config(self, extractor: Extractor) -> ResolvedExecutionConfig:
        provider_name = extractor.provider_name or DEFAULT_PROVIDER_NAME
        model = extractor.model or self._settings.vllm_model
        return ResolvedExecutionConfig(provider_name=provider_name, model=model)

    def for_extractor(
        self,
        extractor: Extractor,
        *,
        provider: Provider | None = None,
        api_key: str | None = None,
    ) -> OpenAIExtractionEngine:
        resolved = self.resolve_extractor_config(extractor)
        provider_name = resolved.provider_name
        model = resolved.model
        base_url = provider.base_url if provider else None
        resolved_api_key = api_key or "EMPTY"

        cache_key = (provider_name.value, base_url, resolved_api_key, model)
        engine = self._cache.get(cache_key)
        if engine is None:
            engine = OpenAIExtractionEngine(
                OpenAIEngineConfig(
                    model=model,
                    base_url=base_url,
                    api_key=resolved_api_key,
                    max_tokens=self._settings.vllm_max_tokens,
                    temperature=self._settings.vllm_temperature,
                    timeout_seconds=self._settings.vllm_timeout_seconds,
                    log_model_io=self._settings.log_model_io,
                )
            )
            self._cache[cache_key] = engine
        return engine
