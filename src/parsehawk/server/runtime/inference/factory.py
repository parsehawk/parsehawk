"""Resolve and cache an extraction engine per extractor.

Each extractor names a provider and a model; the factory looks up the provider's
connection config, decrypts its API key, and builds an ``OpenAIExtractionEngine``
for that (provider, key, model) combination. Engines are cached per config so a
provider edit or key rotation transparently yields a fresh client. One factory
lives per process (the API and worker each have their own), reading providers
and secrets from the shared SQLite database.
"""

from __future__ import annotations

from typing import Any

from parsehawk.config import Settings
from parsehawk.core.application.ports import ProviderRepository, SecretStore
from parsehawk.core.application.services import DEFAULT_PROVIDER_NAME
from parsehawk.core.domain.models import Extractor
from parsehawk.server.runtime.inference.openai_engine import (
    OpenAIEngineConfig,
    OpenAIExtractionEngine,
)


class EngineFactory:
    def __init__(
        self, providers: ProviderRepository, secrets: SecretStore, settings: Settings
    ) -> None:
        self._providers = providers
        self._secrets = secrets
        self._settings = settings
        self._cache: dict[tuple[Any, ...], OpenAIExtractionEngine] = {}

    def for_extractor(self, extractor: Extractor) -> OpenAIExtractionEngine:
        provider_name = extractor.provider_name or DEFAULT_PROVIDER_NAME
        model = extractor.model or self._settings.vllm_model
        provider = self._providers.get(provider_name)
        base_url = provider.base_url if provider else None
        api_version = provider.api_version if provider else None
        api_key = self._secrets.get(provider_name) or "EMPTY"

        cache_key = (provider_name.value, base_url, api_version, api_key, model)
        engine = self._cache.get(cache_key)
        if engine is None:
            engine = OpenAIExtractionEngine(
                OpenAIEngineConfig(
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    api_version=api_version,
                    max_tokens=self._settings.vllm_max_tokens,
                    temperature=self._settings.vllm_temperature,
                    timeout_seconds=self._settings.vllm_timeout_seconds,
                    log_model_io=self._settings.log_model_io,
                )
            )
            self._cache[cache_key] = engine
        return engine
