from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.e2e

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "receipt"


def test_parse_job_api_and_execution(
    client: httpx.Client,
    poll_parse_job: Callable[..., dict[str, Any]],
    cleanup: Callable[[str], None],
) -> None:
    """Cover the complete parse-job surface with exactly one model-bound job."""
    parser_response = client.get("/v1/parsers/document-to-markdown")
    assert parser_response.status_code == 200
    parser = parser_response.json()

    image_path = FIXTURE_DIR / "receipt.png"
    upload = client.post(
        "/v1/files",
        files={"upload": (image_path.name, image_path.read_bytes(), "image/png")},
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]
    cleanup(f"/v1/files/{file_id}")

    created = client.post(
        "/v1/parse-jobs",
        json={"parser_name": parser["name"], "file_id": file_id},
    )
    assert created.status_code == 201
    body = created.json()
    job_id = body["id"]
    cleanup(f"/v1/parse-jobs/{job_id}")
    assert job_id.startswith("parse_job_")
    assert body["parser_id"] == parser["id"]
    assert body["file_id"] == file_id
    assert body["parser_snapshot"]["parser_id"] == parser["id"]
    assert body["parser_snapshot"]["name"] == "document-to-markdown"

    by_id = client.get(f"/v1/parse-jobs?parser_id={parser['id']}")
    assert by_id.status_code == 200
    assert job_id in [job["id"] for job in by_id.json()]
    by_name = client.get(f"/v1/parse-jobs?parser_name={parser['name']}")
    assert by_name.status_code == 200
    assert job_id in [job["id"] for job in by_name.json()]

    got = client.get(f"/v1/parse-jobs/{job_id}")
    assert got.status_code == 200
    assert got.json()["id"] == job_id

    completed = poll_parse_job(job_id)
    assert completed["status"] == "completed", completed
    assert completed["provider_name_used"] == "openai_compatible_api"
    assert completed["model_used"]
    assert completed["model_adapter_used"] == "nuextract_markdown"
    assert completed["started_at"] is not None
    assert completed["completed_at"] is not None

    result = completed["result"]
    assert result["format"] == "markdown"
    assert result["page_count"] == 1
    assert len(result["pages"]) == 1
    assert result["pages"][0]["page_number"] == 1
    assert result["pages"][0]["content"].strip()
    assert result["content"] == result["pages"][0]["content"]

    # The route is covered without spending another model request on a cancel-only job.
    terminal_cancel = client.post(f"/v1/parse-jobs/{job_id}/cancel")
    assert terminal_cancel.status_code == 422

    assert client.delete(f"/v1/files/{file_id}").status_code == 422
    assert client.delete(f"/v1/parse-jobs/{job_id}").status_code == 204
    assert client.get(f"/v1/parse-jobs/{job_id}").status_code == 404
    assert client.delete(f"/v1/files/{file_id}").status_code == 204
