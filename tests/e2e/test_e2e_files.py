from __future__ import annotations

from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "receipt"
SUPPORTED_FILES = [
    ("receipt.txt", "text/plain"),
    ("receipt.png", "image/png"),
    ("receipt.jpg", "image/jpeg"),
    ("receipt.pdf", "application/pdf"),
]


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


@pytest.mark.parametrize("filename,content_type", SUPPORTED_FILES)
def test_upload_accepts_supported_file_types(
    client: httpx.Client,
    filename: str,
    content_type: str,
) -> None:
    """Exercise supported upload types without spending one model run per type."""
    path = FIXTURE_DIR / filename
    response = client.post(
        "/v1/files",
        files={"upload": (filename, path.read_bytes(), content_type)},
    )
    assert response.status_code == 201
    file_id = response.json()["id"]
    try:
        assert response.json()["content_type"] == content_type
    finally:
        assert client.delete(f"/v1/files/{file_id}").status_code == 204
