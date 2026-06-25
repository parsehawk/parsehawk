from __future__ import annotations

from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.e2e


def test_list_includes_seeded_prebuilt(client: httpx.Client) -> None:
    response = client.get("/v1/extractors")
    assert response.status_code == 200
    assert any(extractor["is_prebuilt"] for extractor in response.json())


def test_extractor_create_get_patch_delete(
    client: httpx.Client, receipt_schema: dict[str, Any]
) -> None:
    created = client.post(
        "/v1/extractors",
        json={
            "name": "e2e-lifecycle",
            "instructions": "Extract receipt fields.",
            "schema": receipt_schema,
            "examples": [],
        },
    )
    assert created.status_code == 201
    body = created.json()
    extractor_id = body["id"]
    assert extractor_id.startswith("extractor_")
    assert body["is_prebuilt"] is False
    assert body["source"] == "user"

    got = client.get(f"/v1/extractors/{extractor_id}")
    assert got.status_code == 200
    assert got.json()["id"] == extractor_id

    patched = client.patch(
        f"/v1/extractors/{extractor_id}",
        json={"name": "e2e-lifecycle-renamed"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "e2e-lifecycle-renamed"

    deleted = client.delete(f"/v1/extractors/{extractor_id}")
    assert deleted.status_code == 204
    assert client.get(f"/v1/extractors/{extractor_id}").status_code == 404


def test_prebuilt_extractor_is_read_only(client: httpx.Client) -> None:
    extractors = client.get("/v1/extractors").json()
    prebuilt = next((extractor for extractor in extractors if extractor["is_prebuilt"]), None)
    if prebuilt is None:
        pytest.skip("no prebuilt extractor seeded")

    prebuilt_id = prebuilt["id"]
    assert client.patch(f"/v1/extractors/{prebuilt_id}", json={"name": "nope"}).status_code == 422
    assert client.delete(f"/v1/extractors/{prebuilt_id}").status_code == 422
