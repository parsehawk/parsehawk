from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e


def test_root(client: httpx.Client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "ParseHawk API" in response.json()["message"]


def test_health(client: httpx.Client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
