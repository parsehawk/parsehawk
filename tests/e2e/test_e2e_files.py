from __future__ import annotations

from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "receipt"


def test_file_crud_roundtrip(client: httpx.Client) -> None:
    content = (FIXTURE_DIR / "receipt.md").read_bytes()

    upload = client.post(
        "/v1/files",
        files={"upload": ("receipt.md", content, "text/markdown")},
    )
    assert upload.status_code == 201
    body = upload.json()
    file_id = body["id"]
    assert file_id.startswith("file_")
    assert body["file_name"] == "receipt.md"
    assert body["size_bytes"] == len(content)
    assert len(body["sha256"]) == 64
    assert body["source"] == "user"
    assert body["is_example"] is False

    listed = client.get("/v1/files")
    assert listed.status_code == 200
    assert file_id in [item["id"] for item in listed.json()]

    metadata = client.get(f"/v1/files/{file_id}")
    assert metadata.status_code == 200
    assert metadata.json()["id"] == file_id

    fetched = client.get(f"/v1/files/{file_id}/content")
    assert fetched.status_code == 200
    assert fetched.content == content

    deleted = client.delete(f"/v1/files/{file_id}")
    assert deleted.status_code == 204
    assert client.get(f"/v1/files/{file_id}").status_code == 404


def test_upload_rejects_unsupported_type(client: httpx.Client) -> None:
    response = client.post(
        "/v1/files",
        files={"upload": ("notes.exe", b"binary blob", "application/octet-stream")},
    )
    assert response.status_code == 422
