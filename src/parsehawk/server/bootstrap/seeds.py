from __future__ import annotations

from parsehawk.config import Settings
from parsehawk.core.domain.models import ExtractorSource, Provider, ProviderName, utc_now
from parsehawk.server.container import Container, build_container

RECEIPT_EXTRACTOR_SEED_KEY = "prebuilt:receipt:v1"
RECEIPT_EXTRACTOR_SEED_VERSION = 1

OPENAI_BASE_URL = "https://api.openai.com/v1"
KNOWN_BUNDLED_RUNTIME_BASE_URLS = frozenset(
    {
        "http://127.0.0.1:8080/v1",
        "http://localhost:8080/v1",
        "http://host.docker.internal:8080/v1",
        "http://runtime:8080/v1",
    }
)

RECEIPT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "merchant_name": {
            "type": ["string", "null"],
            "description": "Merchant or store name exactly as written on the receipt.",
            "x-parsehawk": {"semantic": "verbatim-string"},
        },
        "receipt_id": {
            "type": ["string", "null"],
            "description": "Receipt, transaction, or invoice identifier exactly as written.",
            "x-parsehawk": {"semantic": "verbatim-string"},
        },
        "date": {
            "type": ["string", "null"],
            "description": "Receipt date.",
            "x-parsehawk": {"semantic": "date"},
        },
        "total": {
            "type": ["number", "null"],
            "description": "Final amount paid after taxes, discounts, and fees.",
        },
        "currency": {
            "type": ["string", "null"],
            "enum": ["EUR", "USD", "GBP", None],
            "description": "Currency of the final total.",
        },
    },
    "required": ["merchant_name", "receipt_id", "date", "total", "currency"],
}


def seed_prebuilt_data(settings: Settings) -> None:
    container = build_container(settings)
    try:
        seed_prebuilt_data_in_container(container)
    finally:
        container.close()


def seed_providers_in_container(container: Container) -> None:
    """Ensure fixed providers exist and bundled defaults match this runtime.

    Operator-configured provider URLs survive restarts. The local bundled runtime
    URL is the exception: older ParseHawk versions could seed a host-local URL
    before Docker mode knew the container-facing URL, so known bundled defaults
    are reconciled to the active topology.
    """
    default_base_urls = {
        ProviderName.OPENAI: OPENAI_BASE_URL,
        ProviderName.OPENAI_COMPATIBLE: container.settings.vllm_base_url,
        ProviderName.AZURE_OPENAI: None,
    }
    for name, base_url in default_base_urls.items():
        provider = container.providers.get(name)
        if provider is None:
            container.providers.save(Provider(name=name, base_url=base_url))
        elif (
            name == ProviderName.OPENAI_COMPATIBLE
            and base_url
            and provider.base_url != base_url
            and (provider.base_url is None or provider.base_url in KNOWN_BUNDLED_RUNTIME_BASE_URLS)
        ):
            container.providers.save(
                provider.model_copy(update={"base_url": base_url, "updated_at": utc_now()})
            )


def seed_prebuilt_data_in_container(container: Container) -> None:
    seed_providers_in_container(container)

    existing = [
        extractor
        for extractor in container.extractor_service.list()
        if extractor.seed_key == RECEIPT_EXTRACTOR_SEED_KEY
    ]
    if existing:
        return

    container.extractor_service.create(
        name="receipt",
        display_name="Receipt",
        instructions=(
            "Extract the receipt fields from the document. Return null for fields that are "
            "not present in the source."
        ),
        schema=RECEIPT_SCHEMA,
        examples=[],
        source=ExtractorSource.PREBUILT,
        seed_key=RECEIPT_EXTRACTOR_SEED_KEY,
        seed_version=RECEIPT_EXTRACTOR_SEED_VERSION,
    )
