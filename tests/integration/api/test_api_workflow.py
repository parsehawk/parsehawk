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
                "reasoning_effort": "medium",
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
        assert extractor_payload["reasoning_effort"] == "medium"
        assert extractor_payload["schema"] == canonical_schema
        extractor_id = extractor_payload["id"]
        assert file_id.startswith("file_")
        assert extractor_id.startswith("extractor_")

        job_response = client.post(
            "/v1/extraction-jobs",
            json={"extractor_id": extractor_id, "file_id": file_id},
        )
        assert job_response.status_code == 201
        job_id = job_response.json()["id"]
        assert job_id.startswith("job_")

        jobs_response = client.get(f"/v1/extraction-jobs?extractor_id={extractor_id}")
        assert jobs_response.status_code == 200
        assert [job["id"] for job in jobs_response.json()] == [job_id]
        legacy_jobs_response = client.get(f"/v1/jobs?extractor_id={extractor_id}")
        assert legacy_jobs_response.json() == jobs_response.json()

        assert run_once() is True

        result_response = client.get(f"/v1/extraction-jobs/{job_id}")
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
        assert client.get(f"/v1/jobs/{job_id}").json() == payload


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

        container = client.app.state.container
        with container.uow_factory(write=True) as uow:
            job = uow.extraction_jobs.get(job_id)
            assert job is not None
            uow.extraction_jobs.save(job.mark_running())
            uow.commit()

        response = client.delete(f"/v1/jobs/{job_id}")

        assert response.status_code == 202
        persisted = container.extraction_job_service.get(job_id)
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
    for path in ("/v1/jobs", "/v1/jobs/{job_id}", "/v1/jobs/{job_id}/cancel"):
        for operation in paths[path].values():
            assert operation["deprecated"] is True
    assert paths["/v1/extraction-jobs"]["post"].get("deprecated") is not True
    assert paths["/v1/parse-jobs"]["post"].get("deprecated") is not True


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


def test_parser_and_parse_job_api_workflow(monkeypatch, tmp_path, mock_inference) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    with TestClient(create_app()) as client:
        prebuilt = client.get("/v1/parsers/document-to-markdown")
        assert prebuilt.status_code == 200
        assert prebuilt.json()["is_prebuilt"] is True
        assert prebuilt.json()["output_format"] == "markdown"

        created = client.post(
            "/v1/parsers",
            json={
                "name": "integration-parser",
                "display_name": "Integration Parser",
                "instructions": "Preserve page headings.",
            },
        )
        assert created.status_code == 201
        parser_id = created.json()["id"]
        assert client.get("/v1/parsers/integration-parser").json()["id"] == parser_id

        updated = client.patch(
            f"/v1/parsers/{parser_id}",
            json={"instructions": "Preserve headings and lists."},
        )
        assert updated.status_code == 200
        assert updated.json()["instructions"] == "Preserve headings and lists."

        uploaded = client.post(
            "/v1/files",
            files={"upload": ("two-pages.pdf", pdf_bytes(), "application/pdf")},
        )
        assert uploaded.status_code == 201
        file_id = uploaded.json()["id"]

        queued = client.post(
            "/v1/parse-jobs",
            json={"parser_name": "integration-parser", "file_id": file_id},
        )
        assert queued.status_code == 201
        job_id = queued.json()["id"]
        assert job_id.startswith("parse_job_")
        assert queued.json()["parser_snapshot"]["instructions"] == ("Preserve headings and lists.")
        listed = client.get("/v1/parse-jobs?parser_name=integration-parser")
        assert [job["id"] for job in listed.json()] == [job_id]

        client.patch(
            f"/v1/parsers/{parser_id}",
            json={"instructions": "This must not alter the queued snapshot."},
        )
        assert run_once() is True

        completed = client.get(f"/v1/parse-jobs/{job_id}")
        assert completed.status_code == 200
        payload = completed.json()
        assert payload["status"] == "completed"
        assert payload["parser_snapshot"]["instructions"] == "Preserve headings and lists."
        assert payload["provider_name_used"] == "openai_compatible_api"
        assert payload["model_adapter_used"] == "nuextract_markdown"
        assert payload["result"] == {
            "format": "markdown",
            "content": "# Parsed page 1\n\n<!-- page-break -->\n\n# Parsed page 2",
            "page_count": 2,
            "pages": [
                {"page_number": 1, "content": "# Parsed page 1"},
                {"page_number": 2, "content": "# Parsed page 2"},
            ],
        }

        assert client.delete(f"/v1/parse-jobs/{job_id}").status_code == 204
        assert client.delete(f"/v1/parsers/{parser_id}").status_code == 204


def test_parse_job_validation_cancellation_and_deletion_api(
    monkeypatch,
    tmp_path,
    mock_inference,
) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PARSEHAWK_DATABASE_PATH", str(tmp_path / "parsehawk.db"))

    with TestClient(create_app()) as client:
        uploaded = client.post(
            "/v1/files",
            files={"upload": ("page.png", b"png", "image/png")},
        )
        file_id = uploaded.json()["id"]
        invalid = client.post(
            "/v1/parse-jobs",
            json={
                "parser_id": "parser_unknown",
                "parser_name": "document-to-markdown",
                "file_id": file_id,
            },
        )
        assert invalid.status_code == 422

        queued = client.post(
            "/v1/parse-jobs",
            json={"parser_name": "document-to-markdown", "file_id": file_id},
        )
        job_id = queued.json()["id"]
        canceled = client.post(f"/v1/parse-jobs/{job_id}/cancel")
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"
        assert client.delete(f"/v1/parse-jobs/{job_id}").status_code == 204
        assert client.get(f"/v1/parse-jobs/{job_id}").status_code == 404


def pdf_bytes() -> bytes:
    first = Image.new("RGB", (96, 96), "white")
    second = Image.new("RGB", (96, 96), "white")
    buffer = BytesIO()
    first.save(buffer, "PDF", save_all=True, append_images=[second])
    return buffer.getvalue()
