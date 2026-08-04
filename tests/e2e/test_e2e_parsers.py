from __future__ import annotations

import uuid

import httpx
import pytest

pytestmark = pytest.mark.e2e


def test_parser_api_surface(client: httpx.Client) -> None:
    """Cover parser CRUD and PUT semantics without invoking a model."""
    listed = client.get("/v1/parsers")
    assert listed.status_code == 200
    prebuilt = next(parser for parser in listed.json() if parser["name"] == "document-to-markdown")
    assert prebuilt["is_prebuilt"] is True
    assert prebuilt["output_format"] == "markdown"

    parser_name = f"e2e-parser-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/v1/parsers",
        json={
            "name": parser_name,
            "display_name": "E2E Parser",
            "instructions": "Preserve section numbering.",
        },
    )
    assert created.status_code == 201
    body = created.json()
    parser_id = body["id"]
    assert parser_id.startswith("parser_")
    assert body["source"] == "user"
    assert body["is_prebuilt"] is False

    try:
        got = client.get(f"/v1/parsers/{parser_id}")
        assert got.status_code == 200
        assert got.json()["id"] == parser_id

        got_by_name = client.get(f"/v1/parsers/{parser_name}")
        assert got_by_name.status_code == 200
        assert got_by_name.json()["id"] == parser_id

        patched = client.patch(
            f"/v1/parsers/{parser_id}",
            json={"display_name": "E2E Parser Patched"},
        )
        assert patched.status_code == 200
        assert patched.json()["display_name"] == "E2E Parser Patched"
        assert patched.json()["instructions"] == "Preserve section numbering."

        replaced = client.put(
            f"/v1/parsers/{parser_name}",
            json={
                "name": parser_name,
                "display_name": "E2E Parser Replaced",
                "instructions": "Describe charts and diagrams.",
                "output_format": "markdown",
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["id"] == parser_id
        assert replaced.json()["display_name"] == "E2E Parser Replaced"
        assert replaced.json()["instructions"] == "Describe charts and diagrams."
    finally:
        assert client.delete(f"/v1/parsers/{parser_id}").status_code in {204, 404}

    assert client.get(f"/v1/parsers/{parser_id}").status_code == 404
    assert (
        client.patch(
            f"/v1/parsers/{prebuilt['id']}",
            json={"display_name": "Do not mutate"},
        ).status_code
        == 422
    )
    assert client.delete(f"/v1/parsers/{prebuilt['id']}").status_code == 422
