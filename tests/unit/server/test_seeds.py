from __future__ import annotations

from parsehawk.config import Settings
from parsehawk.core.domain.models import ProviderName
from parsehawk.server.bootstrap.seeds import (
    OPENAI_BASE_URL,
    RECEIPT_EXTRACTOR_SEED_KEY,
    seed_prebuilt_data,
)
from parsehawk.server.container import build_container


def _settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, database_path=tmp_path / "parsehawk.db")


def test_seed_prebuilt_data_is_idempotent(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "parsehawk.db",
    )

    seed_prebuilt_data(settings)
    seed_prebuilt_data(settings)

    container = build_container(settings)
    try:
        extractors = container.extractor_service.list()
    finally:
        container.close()

    prebuilt = [
        extractor for extractor in extractors if extractor.seed_key == RECEIPT_EXTRACTOR_SEED_KEY
    ]
    assert len(prebuilt) == 1
    assert prebuilt[0].is_prebuilt is True
    assert prebuilt[0].seed_version == 1
    assert prebuilt[0].schema["properties"]["receipt_id"]["x-parsehawk"] == {
        "semantic": "verbatim-string"
    }
    assert "nuextract_template" not in prebuilt[0].model_dump()


def test_seed_creates_the_three_fixed_providers(tmp_path) -> None:
    settings = _settings(tmp_path)

    seed_prebuilt_data(settings)

    container = build_container(settings)
    try:
        providers = {provider.name: provider for provider in container.provider_service.list()}
    finally:
        container.close()
    assert set(providers) == {
        ProviderName.OPENAI,
        ProviderName.AZURE_OPENAI,
        ProviderName.OPENAI_COMPATIBLE,
    }
    assert providers[ProviderName.OPENAI].base_url == OPENAI_BASE_URL
    assert providers[ProviderName.OPENAI_COMPATIBLE].base_url == settings.vllm_base_url
    assert providers[ProviderName.AZURE_OPENAI].base_url is None


def test_reseeding_does_not_clobber_configured_provider(tmp_path) -> None:
    settings = _settings(tmp_path)
    seed_prebuilt_data(settings)

    container = build_container(settings)
    try:
        container.provider_service.configure(
            ProviderName.OPENAI, base_url="https://custom.example/v1", api_key="sk-x"
        )
    finally:
        container.close()

    seed_prebuilt_data(settings)  # a restart re-runs seeding

    container = build_container(settings)
    try:
        provider = container.provider_service.get(ProviderName.OPENAI)
        assert provider.base_url == "https://custom.example/v1"
        assert container.provider_service.has_api_key(ProviderName.OPENAI) is True
    finally:
        container.close()


def test_seeded_prebuilt_extractor_uses_default_provider_and_model(tmp_path) -> None:
    settings = _settings(tmp_path)

    seed_prebuilt_data(settings)

    container = build_container(settings)
    try:
        prebuilt = next(
            extractor
            for extractor in container.extractor_service.list()
            if extractor.seed_key == RECEIPT_EXTRACTOR_SEED_KEY
        )
    finally:
        container.close()
    assert prebuilt.provider_name == ProviderName.OPENAI_COMPATIBLE
    assert prebuilt.model == settings.vllm_model
