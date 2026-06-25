from __future__ import annotations

from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.e2e


def test_valid_schema_returns_canonical(
    client: httpx.Client, receipt_schema: dict[str, Any]
) -> None:
    response = client.post("/v1/schemas/validate", json={"schema": receipt_schema})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert "schema" in body
    assert "json_schema" not in body
    assert "field_schema" not in body


def test_invalid_schema_reports_error(client: httpx.Client) -> None:
    response = client.post("/v1/schemas/validate", json={"schema": {"type": 123}})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["errors"][0]["code"] == "invalid_json_schema"


def test_canonical_schema_preserves_parsehawk_extensions(client: httpx.Client) -> None:
    response = client.post(
        "/v1/schemas/validate",
        json={
            "schema": {
                "type": "object",
                "properties": {
                    "invoice_number": {
                        "type": ["string", "null"],
                        "x-parsehawk": {"semantic": "verbatim-string"},
                    }
                },
                "required": ["invoice_number"],
                "additionalProperties": False,
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["schema"]["properties"]["invoice_number"] == {
        "type": ["string", "null"],
        "x-parsehawk": {"semantic": "verbatim-string"},
    }
