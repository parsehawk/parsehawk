from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from parsehawk.core.domain.models import JobStatus
from parsehawk.server.api.fastapi.app import create_app
from parsehawk.server.worker.main import run_once

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "receipt"


def test_root_api_route(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Welcome to the ParseHawk API! Documentation is available at https://docs.parsehawk.com"
    }


def test_receipt_api_workflow(monkeypatch, tmp_path, mock_inference) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    schema = json.loads((FIXTURE_DIR / "receipt_schema.json").read_text(encoding="utf-8"))
    ground_truth = json.loads(
        (FIXTURE_DIR / "receipt_ground_truth.json").read_text(encoding="utf-8")
    )

    with TestClient(create_app()) as client:
        schema_response = client.post(
            "/v1/schemas/validate",
            json={"schema": schema},
        )
        assert schema_response.status_code == 200
        assert schema_response.json()["valid"] is True
        assert "field_schema" not in schema_response.json()
        assert "json_schema" not in schema_response.json()
        assert "capabilities" not in schema_response.json()
        canonical_schema = schema_response.json()["schema"]

        file_response = client.post(
            "/v1/files",
            files={
                "upload": (
                    "receipt.md",
                    (FIXTURE_DIR / "receipt.md").read_bytes(),
                    "text/markdown",
                )
            },
        )
        assert file_response.status_code == 201
        file_id = file_response.json()["id"]
        assert file_response.json()["file_name"] == "receipt.md"
        assert "filename" not in file_response.json()
        assert file_response.json()["source"] == "user"
        assert file_response.json()["is_example"] is False

        content_response = client.get(f"/v1/files/{file_id}/content")
        assert content_response.status_code == 200
        assert content_response.content == (FIXTURE_DIR / "receipt.md").read_bytes()

        extractor_response = client.post(
            "/v1/extractors",
            json={
                "name": "receipt_test",
                "display_name": "Receipt Test",
                "instructions": "Extract the receipt fields.",
                "enable_thinking": True,
                "schema": schema,
                "examples": [],
            },
        )
        assert extractor_response.status_code == 201
        extractor_payload = extractor_response.json()
        assert "nuextract_template" not in extractor_payload
        assert "field_schema" not in extractor_payload
        assert "json_schema" not in extractor_payload
        assert extractor_payload["source"] == "user"
        assert extractor_payload["is_prebuilt"] is False
        assert extractor_payload["enable_thinking"] is True
        assert extractor_payload["schema"] == canonical_schema
        extractor_id = extractor_payload["id"]
        assert file_id.startswith("file_")
        assert extractor_id.startswith("extractor_")

        job_response = client.post(
            "/v1/jobs",
            json={"extractor_id": extractor_id, "file_id": file_id},
        )
        assert job_response.status_code == 201
        job_id = job_response.json()["id"]
        assert job_id.startswith("job_")

        jobs_response = client.get(f"/v1/jobs?extractor_id={extractor_id}")
        assert jobs_response.status_code == 200
        assert [job["id"] for job in jobs_response.json()] == [job_id]

        assert run_once() is True

        result_response = client.get(f"/v1/jobs/{job_id}")
        assert result_response.status_code == 200
        payload = result_response.json()
        assert payload["status"] == "completed"
        assert payload["provider_name_used"] == "openai_compatible_api"
        assert payload["model_used"] == "numind/NuExtract3-W4A16"
        assert "artifact_dir" not in payload
        assert "raw_output" not in payload["result"]
        assert "valid" not in payload["result"]
        assert "validation_errors" not in payload["result"]
        assert payload["result"]["data"] == ground_truth


def test_failed_schema_validation_hides_internal_result(
    monkeypatch, tmp_path, mock_inference
) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    with TestClient(create_app()) as client:
        extractor_response = client.post(
            "/v1/extractors",
            json={
                "name": "strict_receipt_id",
                "instructions": "Extract the receipt id.",
                "schema": {
                    "type": "object",
                    "required": ["receipt_id"],
                    "properties": {"receipt_id": {"type": "string"}},
                },
                "examples": [],
            },
        )
        assert extractor_response.status_code == 201

        job_response = client.post(
            "/v1/jobs",
            json={
                "extractor_id": extractor_response.json()["id"],
                "text": "This source has no receipt ids.",
            },
        )
        assert job_response.status_code == 201

        assert run_once() is True

        result_response = client.get(f"/v1/jobs/{job_response.json()['id']}")
        assert result_response.status_code == 200
        payload = result_response.json()
        assert payload["status"] == "failed"
        assert payload["result"] is None
        assert payload["error"]["code"] == "schema_validation_failed"


def test_delete_running_job_returns_accepted_and_marks_deleting(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    schema = json.loads((FIXTURE_DIR / "receipt_schema.json").read_text(encoding="utf-8"))

    with TestClient(create_app()) as client:
        extractor_response = client.post(
            "/v1/extractors",
            json={
                "name": "receipt_delete_test",
                "instructions": "Extract the receipt fields.",
                "schema": schema,
                "examples": [],
            },
        )
        assert extractor_response.status_code == 201

        job_response = client.post(
            "/v1/jobs",
            json={
                "extractor_id": extractor_response.json()["id"],
                "text": "Receipt #R-42",
            },
        )
        assert job_response.status_code == 201
        job_id = job_response.json()["id"]

        job = client.app.state.container.jobs.get(job_id)
        assert job is not None
        client.app.state.container.jobs.save(job.mark_running())

        response = client.delete(f"/v1/jobs/{job_id}")

        assert response.status_code == 202
        persisted = client.app.state.container.jobs.get(job_id)
        assert persisted is not None
        assert persisted.status == JobStatus.DELETING


def test_schema_validation_reports_errors(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/schemas/validate",
            json={
                "schema": {"type": 123},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is False
        assert payload["errors"][0]["code"] == "invalid_json_schema"


def test_schema_validation_returns_canonical_schema(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    with TestClient(create_app()) as client:
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
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["valid"] is True
        assert payload["schema"]["properties"]["invoice_number"] == {
            "type": ["string", "null"],
            "x-parsehawk": {"semantic": "verbatim-string"},
        }
        assert "nuextract_template" not in payload
        assert "field_schema" not in payload
        assert "json_schema" not in payload


def test_openapi_links_parsehawk_schema_dialect(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/v1/files/{file_id}/pages" not in paths
    assert "/v1/files/{file_id}/pages/{page_number}" not in paths
    operation = paths["/v1/schemas/validate"]["post"]
    assert operation["externalDocs"] == {
        "description": "ParseHawk extraction schema dialect",
        "url": "https://docs.parsehawk.com/schemas/parsehawk-extraction-schema.schema.json",
    }
    schema_property = response.json()["components"]["schemas"]["ValidateSchemaRequest"][
        "properties"
    ]["schema"]
    assert "ParseHawk extraction schema" in schema_property["description"]


def test_job_can_run_against_inline_text(monkeypatch, tmp_path, mock_inference) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    schema = json.loads((FIXTURE_DIR / "receipt_schema.json").read_text(encoding="utf-8"))

    with TestClient(create_app()) as client:
        extractor_response = client.post(
            "/v1/extractors",
            json={
                "name": "receipt_test",
                "display_name": "Receipt Test",
                "instructions": "Extract the receipt fields.",
                "schema": schema,
                "examples": [],
            },
        )
        extractor_id = extractor_response.json()["id"]

        job_response = client.post(
            "/v1/jobs",
            json={
                "extractor_id": extractor_id,
                "text": "Corner Market\nReceipt #R-42\nDate: 2026-06-21\nTotal EUR 12.40",
            },
        )
        assert job_response.status_code == 201
        assert job_response.json()["file_id"] is None
        assert job_response.json()["source_text"] == (
            "Corner Market\nReceipt #R-42\nDate: 2026-06-21\nTotal EUR 12.40"
        )
        job_id = job_response.json()["id"]

        assert run_once() is True
        result_response = client.get(f"/v1/jobs/{job_id}")
        assert result_response.status_code == 200
        assert result_response.json()["source_text"] == (
            "Corner Market\nReceipt #R-42\nDate: 2026-06-21\nTotal EUR 12.40"
        )
        assert result_response.json()["result"]["data"]["receipt_id"] == "R-42"


def pdf_bytes() -> bytes:
    first = Image.new("RGB", (96, 96), "white")
    second = Image.new("RGB", (96, 96), "white")
    buffer = BytesIO()
    first.save(buffer, "PDF", save_all=True, append_images=[second])
    return buffer.getvalue()
