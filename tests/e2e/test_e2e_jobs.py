from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.e2e

RECEIPT_TEXT = "PARSEHAWK COFFEE\nReceipt #R-1001\nDate: 2026-06-21\nTotal EUR 11.22"
RECEIPT_FIELDS = {"merchant_name", "receipt_id", "date", "total", "currency"}


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


def test_extraction_job_api_and_execution(
    client: httpx.Client,
    receipt_extractor: str,
    poll_job: Callable[..., dict[str, Any]],
    cleanup: Callable[[str], None],
) -> None:
    """Cover extraction-job CRUD and execution with one model request."""
    created = client.post(
        "/v1/extraction-jobs",
        json={"extractor_id": receipt_extractor, "text": RECEIPT_TEXT},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    assert job_id.startswith("job_")
    cleanup(f"/v1/extraction-jobs/{job_id}")

    listed = client.get(f"/v1/extraction-jobs?extractor_id={receipt_extractor}")
    assert listed.status_code == 200
    assert job_id in [job["id"] for job in listed.json()]

    got = client.get(f"/v1/extraction-jobs/{job_id}")
    assert got.status_code == 200
    assert got.json()["id"] == job_id

    # The deprecated route remains a byte-for-byte-compatible alias during v0.3.
    legacy = client.get(f"/v1/jobs/{job_id}")
    assert legacy.status_code == 200
    assert legacy.json() == got.json()

    legacy_list = client.get(f"/v1/jobs?extractor_id={receipt_extractor}")
    assert legacy_list.status_code == 200
    assert job_id in [job["id"] for job in legacy_list.json()]

    _assert_completed_receipt(poll_job(job_id))

    # Cover cancellation on a terminal job and the deprecated write aliases
    # without queuing additional model-bound extraction jobs.
    assert client.post(f"/v1/extraction-jobs/{job_id}/cancel").status_code == 422
    assert client.post(f"/v1/jobs/{job_id}/cancel").status_code == 422
    invalid_legacy_create = client.post(
        "/v1/jobs",
        json={"extractor_id": receipt_extractor},
    )
    assert invalid_legacy_create.status_code == 422

    deleted = client.delete(f"/v1/jobs/{job_id}")
    assert deleted.status_code == 204
    assert client.get(f"/v1/extraction-jobs/{job_id}").status_code == 404
