"""End-to-end API test harness.

Runs the real API + worker as subprocesses against an isolated temp data dir,
reusing whatever model runtime is already up (the GPU only hosts one). Speaks
HTTP over the wire via ``httpx`` — never the in-process ``TestClient``.

It reuses the already-running model runtime rather than starting a second one
(the GPU hosts only one), and asserts response shape rather than exact extracted
values (NuExtract has no seed and samples at the configured temperature).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "receipt"
DEFAULT_RUNTIME_URL = "http://127.0.0.1:8080/v1"
API_HEALTH_TIMEOUT = float(os.environ.get("PARSEHAWK_E2E_API_TIMEOUT", "30"))
JOB_TIMEOUT = float(os.environ.get("PARSEHAWK_E2E_JOB_TIMEOUT", "120"))
JOB_POLL_INTERVAL = float(os.environ.get("PARSEHAWK_E2E_POLL_INTERVAL", "1.0"))


@dataclass(frozen=True)
class Stack:
    base_url: str
    engine_available: bool


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _runtime_reachable(runtime_url: str) -> bool:
    try:
        response = httpx.get(f"{runtime_url.rstrip('/')}/models", timeout=3.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def _wait_for_health(base_url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=2.0)
            if response.status_code == 200 and response.json() == {"status": "ok"}:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    return False


def _seed_temp_database(data_dir: Path, database_path: Path) -> None:
    # The API does not seed on startup (create_app()'s lifespan only builds the
    # container), so seed the temp DB the same way `parsehawk dev` does.
    from parsehawk.config import Settings
    from parsehawk.server.bootstrap.seeds import seed_prebuilt_data

    seed_prebuilt_data(
        Settings.from_env().model_copy(
            update={
                "data_dir": data_dir,
                "database_path": database_path,
                "inference_engine": "none",
            }
        )
    )


@pytest.fixture(scope="session")
def _stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    runtime_url = os.environ.get("PARSEHAWK_VLLM_BASE_URL", DEFAULT_RUNTIME_URL)

    external = os.environ.get("PARSEHAWK_E2E_BASE_URL")
    if external:
        base_url = external.rstrip("/")
        if not _wait_for_health(base_url, timeout=5.0):
            pytest.skip(f"PARSEHAWK_E2E_BASE_URL={base_url} is not serving /health")
        yield Stack(base_url=base_url, engine_available=True)
        return

    engine_available = _runtime_reachable(runtime_url)

    data_dir = tmp_path_factory.mktemp("e2e-data")
    database_path = data_dir / "parsehawk.db"
    _seed_temp_database(data_dir, database_path)

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    # Override BOTH data-dir env vars: `just e2e` runs under a justfile that
    # exports PARSEHAWK_DATABASE_PATH=data/..., which would otherwise leak the
    # real database into the test stack.
    env = os.environ.copy()
    env["PARSEHAWK_DATA_DIR"] = str(data_dir)
    env["PARSEHAWK_DATABASE_PATH"] = str(database_path)
    env["PARSEHAWK_INFERENCE_ENGINE"] = "vllm" if engine_available else "none"
    env["PARSEHAWK_VLLM_BASE_URL"] = runtime_url
    env["PARSEHAWK_VLLM_TEMPERATURE"] = "0"
    env["PARSEHAWK_LOG_LEVEL"] = "WARNING"

    api_log_path = data_dir / "api.log"
    worker_log_path = data_dir / "worker.log"
    with api_log_path.open("wb") as api_log, worker_log_path.open("wb") as worker_log:
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "parsehawk.server.api.fastapi.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=api_log,
            stderr=subprocess.STDOUT,
        )
        worker = subprocess.Popen(
            [sys.executable, "-m", "parsehawk.server.worker.main"],
            env=env,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
        )
        try:
            if not _wait_for_health(base_url, timeout=API_HEALTH_TIMEOUT):
                tail = api_log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                pytest.fail(f"e2e API never became healthy at {base_url}\n--- api.log ---\n{tail}")
            yield Stack(base_url=base_url, engine_available=engine_available)
        finally:
            for process in (worker, api):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


@pytest.fixture(scope="session")
def base_url(_stack: Stack) -> str:
    return _stack.base_url


@pytest.fixture
def client(base_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        yield client


@pytest.fixture
def requires_engine(_stack: Stack) -> None:
    if not _stack.engine_available:
        runtime_url = os.environ.get("PARSEHAWK_VLLM_BASE_URL", DEFAULT_RUNTIME_URL)
        pytest.skip(
            f"model runtime not reachable at {runtime_url}; "
            "start it (e.g. `parsehawk start`) to run job-execution tests"
        )


@pytest.fixture
def poll_job(client: httpx.Client) -> Callable[..., dict[str, Any]]:
    def _poll(job_id: str, timeout: float = JOB_TIMEOUT) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            response = client.get(f"/v1/jobs/{job_id}")
            response.raise_for_status()
            payload = response.json()
            if payload["status"] in {"completed", "failed"}:
                return payload
            if time.monotonic() >= deadline:
                pytest.fail(
                    f"job {job_id} did not finish within {timeout}s "
                    f"(last status {payload['status']})"
                )
            time.sleep(JOB_POLL_INTERVAL)

    return _poll


@pytest.fixture
def cleanup(client: httpx.Client) -> Iterator[Callable[[str], None]]:
    paths: list[str] = []
    yield paths.append
    for path in reversed(paths):
        try:
            client.delete(path)
        except httpx.HTTPError:
            pass


@pytest.fixture
def receipt_schema() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "receipt_schema.json").read_text(encoding="utf-8"))


@pytest.fixture
def receipt_extractor(
    client: httpx.Client,
    receipt_schema: dict[str, Any],
    cleanup: Callable[[str], None],
) -> str:
    response = client.post(
        "/v1/extractors",
        json={
            "name": "e2e-receipt",
            "instructions": "Extract the receipt fields. Return null for missing fields.",
            "schema": receipt_schema,
            "examples": [],
        },
    )
    response.raise_for_status()
    extractor_id = response.json()["id"]
    cleanup(f"/v1/extractors/{extractor_id}")
    return extractor_id
