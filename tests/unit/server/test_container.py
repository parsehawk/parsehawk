from __future__ import annotations

from pathlib import Path
from typing import List

from parsehawk.config import Settings
from parsehawk.core.domain.models import Extractor, Provider, ProviderName
from parsehawk.server.container import Container
from parsehawk.server.runtime.inference.factory import EngineFactory
from parsehawk.server.runtime.inference.openai_engine import OpenAIExtractionEngine


class _Providers:
    def __init__(self, providers: List[Provider]) -> None:
        self._by_name = {provider.name: provider for provider in providers}

    def get(self, name: ProviderName) -> Provider | None:
        return self._by_name.get(name)

    def list(self) -> List[Provider]:
        return list(self._by_name.values())

    def save(self, provider: Provider) -> None:
        self._by_name[provider.name] = provider


class _Secrets:
    def __init__(self, keys: dict[ProviderName, str] | None = None) -> None:
        self._keys = dict(keys or {})

    def get(self, provider_name: ProviderName) -> str | None:
        return self._keys.get(provider_name)

    def put(self, provider_name: ProviderName, api_key: str) -> None:
        self._keys[provider_name] = api_key

    def delete(self, provider_name: ProviderName) -> None:
        self._keys.pop(provider_name, None)

    def has(self, provider_name: ProviderName) -> bool:
        return provider_name in self._keys


def _extractor(provider_name: ProviderName | None = None, model: str | None = None) -> Extractor:
    return Extractor(
        id="e1",
        name="e",
        instructions="i",
        schema={"type": "object"},
        provider_name=provider_name,
        model=model,
    )


def test_factory_builds_engine_from_provider_config_and_key() -> None:
    providers = _Providers(
        [Provider(name=ProviderName.OPENAI, base_url="https://api.openai.com/v1")]
    )
    secrets = _Secrets({ProviderName.OPENAI: "sk-x"})
    factory = EngineFactory(providers, secrets, Settings())

    engine = factory.for_extractor(_extractor(ProviderName.OPENAI, "gpt-4o-mini"))

    assert isinstance(engine, OpenAIExtractionEngine)
    assert engine._config.base_url == "https://api.openai.com/v1"
    assert engine._config.api_key == "sk-x"
    assert engine._config.model == "gpt-4o-mini"
    assert engine._adapter == "generic"


def test_factory_defaults_provider_and_uses_empty_key_for_local_runtime() -> None:
    providers = _Providers(
        [Provider(name=ProviderName.OPENAI_COMPATIBLE, base_url="http://127.0.0.1:8080/v1")]
    )
    settings = Settings()
    factory = EngineFactory(providers, _Secrets(), settings)

    engine = factory.for_extractor(_extractor())  # no provider/model -> defaults

    assert engine._config.base_url == "http://127.0.0.1:8080/v1"
    assert engine._config.api_key == "EMPTY"
    assert engine._config.model == settings.vllm_model
    assert engine._adapter == "nuextract"


def test_factory_caches_by_config_and_refreshes_on_key_change() -> None:
    providers = _Providers(
        [Provider(name=ProviderName.OPENAI, base_url="https://api.openai.com/v1")]
    )
    secrets = _Secrets({ProviderName.OPENAI: "sk-1"})
    factory = EngineFactory(providers, secrets, Settings())
    extractor = _extractor(ProviderName.OPENAI, "gpt-4o-mini")

    first = factory.for_extractor(extractor)
    assert factory.for_extractor(extractor) is first

    secrets.put(ProviderName.OPENAI, "sk-2")
    assert factory.for_extractor(extractor) is not first


def test_container_wires_services_and_leaves_local_model_inherited(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, database_path=tmp_path / "db.sqlite")
    container = Container(settings)
    try:
        assert isinstance(container.engine_factory, EngineFactory)
        extractor = container.extractor_service.create(
            name="e", instructions="i", schema={"type": "object", "properties": {}}
        )
        assert extractor.provider_name == ProviderName.OPENAI_COMPATIBLE
        assert extractor.model is None
    finally:
        container.close()
