from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from parsehawk.config import Settings
from parsehawk.server.api.fastapi.app import create_app, get_container
from parsehawk.server.container import Container

_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}


@pytest.fixture
def concurrent_client(tmp_path) -> Iterator[tuple[TestClient, Container]]:
    settings = Settings(data_dir=tmp_path, database_path=tmp_path / "parsehawk.db")
    container = Container(settings)
    app = create_app()
    app.dependency_overrides[get_container] = lambda: container
    client = TestClient(app)
    try:
        yield client, container
    finally:
        client.close()
        container.close()


def create_extractor(client: TestClient, name: str = "concurrency_test") -> str:
    response = client.post(
        "/v1/extractors",
        json={"name": name, "instructions": "Extract value.", "schema": _SCHEMA},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.concurrency
def test_parallel_job_workflows_have_no_false_not_found_or_server_errors(
    concurrent_client: tuple[TestClient, Container],
) -> None:
    client, _container = concurrent_client
    extractor_id = create_extractor(client)

    def run_workflow(index: int) -> str:
        created = client.post(
            "/v1/jobs",
            json={"extractor_id": extractor_id, "text": f"value {index}"},
        )
        assert created.status_code == 201, created.text
        job_id = created.json()["id"]

        fetched = client.get(f"/v1/jobs/{job_id}")
        assert fetched.status_code == 200, fetched.text
        listed = client.get(f"/v1/jobs?extractor_id={extractor_id}")
        assert listed.status_code == 200, listed.text
        assert job_id in {job["id"] for job in listed.json()}

        canceled = client.post(f"/v1/jobs/{job_id}/cancel")
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["status"] == "canceled"
        assert client.get(f"/v1/jobs/{job_id}").status_code == 200
        assert client.delete(f"/v1/jobs/{job_id}").status_code == 204
        return job_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        job_ids = list(executor.map(run_workflow, range(40)))

    assert len(set(job_ids)) == 40


@pytest.mark.concurrency
def test_parent_deletion_is_rejected_until_job_is_explicitly_deleted(
    concurrent_client: tuple[TestClient, Container],
) -> None:
    client, _container = concurrent_client
    extractor_id = create_extractor(client, "parent_guard")
    uploaded = client.post(
        "/v1/files",
        files={"upload": ("source.md", b"value", "text/markdown")},
    )
    assert uploaded.status_code == 201
    file_id = uploaded.json()["id"]
    created = client.post(
        "/v1/jobs",
        json={"extractor_id": extractor_id, "file_id": file_id},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]

    assert client.delete(f"/v1/files/{file_id}").status_code == 422
    assert client.delete(f"/v1/extractors/{extractor_id}").status_code == 422
    assert client.get(f"/v1/jobs/{job_id}").status_code == 200

    assert client.delete(f"/v1/jobs/{job_id}").status_code == 204
    assert client.delete(f"/v1/files/{file_id}").status_code == 204
    assert client.delete(f"/v1/extractors/{extractor_id}").status_code == 204


@pytest.mark.concurrency
def test_exhausted_write_contention_returns_retryable_503(
    tmp_path,
) -> None:
    settings = Settings(data_dir=tmp_path, database_path=tmp_path / "parsehawk.db")
    container = Container(settings, sqlite_busy_timeout_ms=50)
    app = create_app()
    app.dependency_overrides[get_container] = lambda: container
    client = TestClient(app)
    try:
        extractor_id = create_extractor(client, "busy_test")

        with container.uow_factory(write=True):
            response = client.post(
                "/v1/jobs",
                json={"extractor_id": extractor_id, "text": "value"},
            )

        assert response.status_code == 503
        assert response.json() == {
            "code": "persistence_busy",
            "detail": "Persistence is temporarily busy; retry the request",
        }
        assert response.headers["retry-after"] == "1"
    finally:
        client.close()
        container.close()
