from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from parsehawk.config import Settings
from parsehawk.core.domain.errors import ProviderRequestError
from parsehawk.server.api.fastapi import app as app_module
from parsehawk.server.api.fastapi.app import create_app, get_container
from parsehawk.server.bootstrap.seeds import seed_prebuilt_data_in_container
from parsehawk.server.container import Container, build_container

_OBJECT_SCHEMA = {"type": "object", "properties": {}}


@pytest.fixture
def client(tmp_path) -> Iterator[tuple[TestClient, Container]]:
    settings = Settings(data_dir=tmp_path, database_path=tmp_path / "parsehawk.db")
    container = build_container(settings)
    seed_prebuilt_data_in_container(container)
    app = create_app()
    app.dependency_overrides[get_container] = lambda: container
    try:
        yield TestClient(app), container
    finally:
        container.close()


def test_list_providers_never_exposes_secret(client: tuple[TestClient, Container]) -> None:
    api, _container = client

    response = api.get("/v1/providers")

    assert response.status_code == 200
    providers = {provider["name"]: provider for provider in response.json()}
    assert set(providers) == {"openai", "microsoft_foundry", "openai_compatible_api"}
    assert providers["openai"]["base_url"] == "https://api.openai.com/v1"
    assert providers["openai"]["has_api_key"] is False
    assert providers["openai"]["configuration"] == {}
    assert providers["microsoft_foundry"]["base_url"] is None
    assert all("api_key" not in provider for provider in providers.values())


def test_configure_provider_stores_key_without_returning_it(
    client: tuple[TestClient, Container],
) -> None:
    api, _container = client

    response = api.patch(
        "/v1/providers/openai", json={"base_url": "https://proxy/v1", "api_key": "sk-secret"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["base_url"] == "https://proxy/v1"
    assert body["has_api_key"] is True
    assert "api_key" not in body
    assert api.get("/v1/providers/openai").json()["has_api_key"] is True
    assert "sk-secret" not in api.get("/v1/providers").text


def test_unknown_provider_name_is_rejected(client: tuple[TestClient, Container]) -> None:
    api, _container = client

    assert api.get("/v1/providers/not_a_provider").status_code == 422


def test_create_extractor_defaults_and_overrides_provider(
    client: tuple[TestClient, Container],
) -> None:
    api, _container = client

    default = api.post(
        "/v1/extractors", json={"name": "d", "instructions": "i", "schema": _OBJECT_SCHEMA}
    )
    assert default.status_code == 201
    assert default.json()["provider_name"] == "openai_compatible_api"
    assert default.json()["model"] is None

    override = api.post(
        "/v1/extractors",
        json={
            "name": "o",
            "instructions": "i",
            "provider_name": "openai",
            "model": "gpt-4o-mini",
            "schema": _OBJECT_SCHEMA,
        },
    )
    assert override.status_code == 201
    assert override.json()["provider_name"] == "openai"
    assert override.json()["model"] == "gpt-4o-mini"

    missing_model = api.post(
        "/v1/extractors",
        json={
            "name": "missing_model",
            "instructions": "i",
            "provider_name": "openai",
            "schema": _OBJECT_SCHEMA,
        },
    )
    assert missing_model.status_code == 422
    assert "model is required for provider openai" in missing_model.text


def test_update_extractor_model_can_be_omitted_or_cleared_for_local_default(
    client: tuple[TestClient, Container],
) -> None:
    api, _container = client
    created = api.post(
        "/v1/extractors",
        json={
            "name": "editable",
            "instructions": "i",
            "provider_name": "openai",
            "model": "gpt-4o-mini",
            "schema": _OBJECT_SCHEMA,
        },
    )
    assert created.status_code == 201

    omitted = api.patch("/v1/extractors/editable", json={"instructions": "updated"})
    assert omitted.status_code == 200
    assert omitted.json()["model"] == "gpt-4o-mini"

    inherited = api.patch(
        "/v1/extractors/editable",
        json={"provider_name": "openai_compatible_api", "model": None},
    )
    assert inherited.status_code == 200
    assert inherited.json()["provider_name"] == "openai_compatible_api"
    assert inherited.json()["model"] is None


def test_list_openai_provider_models_uses_chat_filter(
    client: tuple[TestClient, Container], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _container = client
    monkeypatch.setattr(
        app_module, "list_openai_chat_models", lambda **kwargs: ["gpt-4o", "gpt-4o-mini"]
    )

    response = api.get("/v1/providers/openai/models")

    assert response.status_code == 200
    assert response.json() == {"models": ["gpt-4o", "gpt-4o-mini"]}


def test_list_openai_compatible_provider_models_uses_raw_model_list(
    client: tuple[TestClient, Container], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _container = client
    monkeypatch.setattr(
        app_module,
        "list_models",
        lambda **kwargs: ["numind/NuExtract3-W4A16", "custom-local-extractor"],
    )

    response = api.get("/v1/providers/openai_compatible_api/models")

    assert response.status_code == 200
    assert response.json() == {"models": ["numind/NuExtract3-W4A16", "custom-local-extractor"]}


def test_list_microsoft_foundry_models_uses_project_deployments(
    client: tuple[TestClient, Container], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _container = client
    captured: dict[str, object] = {}
    configured = api.patch(
        "/v1/providers/microsoft_foundry",
        json={
            "base_url": "https://resource.services.ai.azure.com/openai/v1",
            "configuration": {
                "project_url": "https://resource.services.ai.azure.com/api/projects/project",
            },
            "api_key": "sk-secret",
        },
    )
    assert configured.status_code == 200

    def _deployments(**kwargs: object) -> list[str]:
        captured.update(kwargs)
        return ["gpt-5.4-dzs"]

    monkeypatch.setattr(app_module, "list_foundry_chat_deployments", _deployments)

    response = api.get("/v1/providers/microsoft_foundry/models")

    assert response.status_code == 200
    assert response.json() == {"models": ["gpt-5.4-dzs"]}
    assert captured == {
        "project_url": "https://resource.services.ai.azure.com/api/projects/project",
        "api_key": "sk-secret",
    }


def test_list_provider_models_maps_provider_error_to_400(
    client: tuple[TestClient, Container], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _container = client

    def _boom(**kwargs: object) -> list[str]:
        raise ProviderRequestError("model provider is unreachable: down")

    monkeypatch.setattr(app_module, "list_openai_chat_models", _boom)

    response = api.get("/v1/providers/openai/models")

    assert response.status_code == 400
    assert "unreachable" in response.json()["detail"]


def test_app_lifespan_seeds_fixed_providers(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that starts the app directly (Docker runs uvicorn, not the
    CLI) must still get the fixed providers on first boot."""
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    with TestClient(create_app()) as api:
        response = api.get("/v1/providers")

    assert response.status_code == 200
    assert {provider["name"] for provider in response.json()} == {
        "openai",
        "microsoft_foundry",
        "openai_compatible_api",
    }


def test_app_lifespan_seeding_keeps_operator_config(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    with TestClient(create_app()) as api:
        configured = api.patch(
            "/v1/providers/microsoft_foundry",
            json={"base_url": "https://resource.example/openai/v1", "api_key": "sk-secret"},
        )
        assert configured.status_code == 200

    # A restart re-runs the lifespan seeding; the operator's config survives.
    with TestClient(create_app()) as api:
        provider = api.get("/v1/providers/microsoft_foundry").json()

    assert provider["base_url"] == "https://resource.example/openai/v1"
    assert provider["has_api_key"] is True
