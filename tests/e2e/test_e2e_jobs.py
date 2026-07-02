from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.e2e

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "receipt"

RECEIPT_TEXT = "PARSEHAWK COFFEE\nReceipt #R-1001\nDate: 2026-06-21\nTotal EUR 11.22"
RECEIPT_FIELDS = {"merchant_name", "receipt_id", "date", "total", "currency"}

# One distinct file type per row (.jpg/.jpeg and .md/.markdown are aliases).
RECEIPT_FILES = [
    ("receipt.md", "text/markdown"),
    ("receipt.txt", "text/plain"),
    ("receipt.png", "image/png"),
    ("receipt.jpg", "image/jpeg"),
    ("receipt.pdf", "application/pdf"),
]


def _assert_completed_receipt(payload: dict[str, Any]) -> None:
    # Shape only — extracted values are model-dependent (NuExtract has no seed)
    # and not asserted.
    assert payload["status"] == "completed", payload
    result = payload["result"]
    assert result is not None
    data = result["data"]
    assert set(data) == RECEIPT_FIELDS
    assert isinstance(data["merchant_name"], (str, type(None)))
    assert isinstance(data["receipt_id"], (str, type(None)))
    assert isinstance(data["date"], (str, type(None)))
    assert isinstance(data["total"], (int, float, type(None)))
    assert isinstance(data["currency"], (str, type(None)))


def test_job_crud_delete(
    client: httpx.Client,
    receipt_extractor: str,
    cleanup: Callable[[str], None],
) -> None:
    created = client.post(
        "/v1/jobs",
        json={"extractor_id": receipt_extractor, "text": RECEIPT_TEXT},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert job_id.startswith("job_")
    cleanup(f"/v1/jobs/{job_id}")

    listed = client.get(f"/v1/jobs?extractor_id={receipt_extractor}")
    assert listed.status_code == 200
    assert job_id in [job["id"] for job in listed.json()]

    got = client.get(f"/v1/jobs/{job_id}")
    assert got.status_code == 200
    assert got.json()["id"] == job_id

    deleted = client.delete(f"/v1/jobs/{job_id}")
    assert deleted.status_code == 204
    assert client.get(f"/v1/jobs/{job_id}").status_code == 404


def test_job_execution_inline_text(
    client: httpx.Client,
    receipt_extractor: str,
    poll_job: Callable[..., dict[str, Any]],
    cleanup: Callable[[str], None],
) -> None:
    created = client.post(
        "/v1/jobs",
        json={"extractor_id": receipt_extractor, "text": RECEIPT_TEXT},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    cleanup(f"/v1/jobs/{job_id}")

    _assert_completed_receipt(poll_job(job_id))


@pytest.mark.parametrize("filename,content_type", RECEIPT_FILES)
def test_job_execution_file(
    client: httpx.Client,
    receipt_extractor: str,
    poll_job: Callable[..., dict[str, Any]],
    cleanup: Callable[[str], None],
    filename: str,
    content_type: str,
) -> None:
    path = FIXTURE_DIR / filename
    if not path.exists():
        pytest.skip(f"fixture {filename} not provided yet")

    upload = client.post(
        "/v1/files",
        files={"upload": (filename, path.read_bytes(), content_type)},
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]
    cleanup(f"/v1/files/{file_id}")

    created = client.post(
        "/v1/jobs",
        json={"extractor_id": receipt_extractor, "file_id": file_id},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    cleanup(f"/v1/jobs/{job_id}")

    _assert_completed_receipt(poll_job(job_id))


def test_cancel_queued_job(
    client: httpx.Client,
    receipt_extractor: str,
    cleanup: Callable[[str], None],
) -> None:
    created = client.post(
        "/v1/jobs",
        json={
            "extractor_id": receipt_extractor,
            "text": RECEIPT_TEXT,
        },
    )

    assert created.status_code == 201

    job_id = created.json()["id"]
    cleanup(f"/v1/jobs/{job_id}")

    canceled = client.post(f"/v1/jobs/{job_id}/cancel")

    assert canceled.status_code == 200, canceled.text
    status = canceled.json()["status"]
    assert status in ("canceled", "canceling")
    job = client.get(f"/v1/jobs/{job_id}")

    assert job.status_code == 200
    assert job.json()["status"] in ("canceled", "canceling")
