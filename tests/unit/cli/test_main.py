from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pytest

from parsehawk.cli import main as cli


def test_files_list_prints_api_response(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    calls = []

    def api_request(api_url: str, method: str, path: str, **kwargs: Any) -> list[dict[str, str]]:
        calls.append((api_url, method, path, kwargs))
        return [{"id": "file_1"}]

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(["files", "list", "--api-url", "http://api"])

    assert calls == [("http://api", "GET", "/v1/files", {})]
    assert json.loads(capsys.readouterr().out) == [{"id": "file_1"}]


def test_data_plane_commands_do_not_parse_runtime_settings(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("PARSEHAWK_VLLM_MAX_MODEL_LEN", "not-an-int")

    def api_request(api_url: str, method: str, path: str, **kwargs: Any) -> list[Any]:
        return []

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(["files", "list", "--api-url", "http://api"])

    assert json.loads(capsys.readouterr().out) == []


def test_config_set_persists_log_level(tmp_path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("PARSEHAWK_CONFIG_PATH", str(config_path))

    cli.main(["config", "set", "log.level", "DEBUG"])
    capsys.readouterr()
    cli.main(["config", "list", "--json"])

    assert json.loads(config_path.read_text(encoding="utf-8"))["log.level"] == "DEBUG"
    assert json.loads(capsys.readouterr().out)["log.level"] == "DEBUG"


def test_files_create_accepts_file_flag(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    calls = []

    def upload_file(api_url: str, path: str) -> dict[str, str]:
        calls.append((api_url, path))
        return {"id": "file_1"}

    monkeypatch.setattr(cli, "upload_file", upload_file)

    cli.main(["files", "create", "--file", "@document.pdf", "--api-url", "http://api"])

    assert calls == [("http://api", "document.pdf")]
    assert json.loads(capsys.readouterr().out) == {"id": "file_1"}


def test_schema_validate_posts_schema(tmp_path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    schema_path = tmp_path / "schema.json"
    schema_path.write_text('{"type": "object"}', encoding="utf-8")
    calls = []

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, bool]:
        calls.append((api_url, method, path, payload, kwargs))
        return {"valid": True}

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(
        [
            "schemas",
            "validate",
            str(schema_path),
            "--api-url",
            "http://api",
        ]
    )

    assert calls == [
        (
            "http://api",
            "POST",
            "/v1/schemas/validate",
            {"schema": {"type": "object"}},
            {},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"valid": True}


def test_extractors_create_reads_schema_and_examples(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    schema_path = tmp_path / "schema.json"
    examples_path = tmp_path / "examples.json"
    instructions_path = tmp_path / "instructions.md"
    schema_path.write_text('{"type": "object"}', encoding="utf-8")
    examples_path.write_text('[{"input": "hi", "output": {"answer": "ok"}}]', encoding="utf-8")
    instructions_path.write_text("Extract invoice fields.", encoding="utf-8")
    calls = []

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        calls.append((api_url, method, path, payload, kwargs))
        return {"id": "extractor_1"}

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(
        [
            "extractors",
            "create",
            "--name",
            "Invoices",
            "--instructions",
            str(instructions_path),
            "--schema",
            str(schema_path),
            "--examples",
            str(examples_path),
            "--enable-thinking",
            "--api-url",
            "http://api",
        ]
    )

    assert calls == [
        (
            "http://api",
            "POST",
            "/v1/extractors",
            {
                "name": "Invoices",
                "instructions": "Extract invoice fields.",
                "enable_thinking": True,
                "schema": {"type": "object"},
                "examples": [{"input": "hi", "output": {"answer": "ok"}}],
            },
            {},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"id": "extractor_1"}


def test_jobs_create_posts_file_id(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    calls = []

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        calls.append((api_url, method, path, payload, kwargs))
        return {"id": "job_1"}

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(
        [
            "jobs",
            "create",
            "extractor_1",
            "--file-id",
            "file_1",
            "--api-url",
            "http://api",
        ]
    )

    assert calls == [
        (
            "http://api",
            "POST",
            "/v1/jobs",
            {"extractor_id": "extractor_1", "file_id": "file_1"},
            {},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"id": "job_1"}


def test_jobs_create_accepts_extractor_and_file_aliases(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    calls = []

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        calls.append((api_url, method, path, payload, kwargs))
        return {"id": "job_1"}

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(
        [
            "jobs",
            "create",
            "--extractor",
            "extractor_1",
            "--file",
            "file_1",
            "--api-url",
            "http://api",
        ]
    )

    assert calls == [
        (
            "http://api",
            "POST",
            "/v1/jobs",
            {"extractor_id": "extractor_1", "file_id": "file_1"},
            {},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"id": "job_1"}


def test_jobs_create_posts_text_file(tmp_path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    text_path = tmp_path / "input.txt"
    text_path.write_text("Inline input", encoding="utf-8")
    calls = []

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        calls.append((api_url, method, path, payload, kwargs))
        return {"id": "job_1"}

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(
        [
            "jobs",
            "create",
            "extractor_1",
            "--text-file",
            str(text_path),
            "--api-url",
            "http://api",
        ]
    )

    assert calls == [
        (
            "http://api",
            "POST",
            "/v1/jobs",
            {"extractor_id": "extractor_1", "text": "Inline input"},
            {},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"id": "job_1"}


def test_extract_creates_ad_hoc_extractor_uploads_file_and_waits(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    document_path = tmp_path / "invoice.pdf"
    schema_path = tmp_path / "schema.json"
    instructions_path = tmp_path / "instructions.md"
    document_path.write_bytes(b"%PDF")
    schema_path.write_text('{"type": "object"}', encoding="utf-8")
    instructions_path.write_text("Extract invoice fields.", encoding="utf-8")
    calls: list[tuple[str, str, str, dict[str, Any] | None]] = []
    uploads: list[tuple[str, str]] = []

    def upload_file(api_url: str, path: str) -> dict[str, str]:
        uploads.append((api_url, path))
        return {"id": "file_1"}

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        calls.append((api_url, method, path, payload))
        if path == "/v1/extractors":
            return {"id": "extractor_1"}
        if path == "/v1/jobs":
            return {"id": "job_1", "status": "queued"}
        if path == "/v1/jobs/job_1":
            return {
                "id": "job_1",
                "status": "completed",
                "result": {"data": {"invoice_number": "A-123"}},
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(cli, "upload_file", upload_file)
    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(
        [
            "extract",
            str(document_path),
            "--schema",
            str(schema_path),
            "--instructions",
            str(instructions_path),
            "--wait",
            "--poll-seconds",
            "0",
            "--enable-thinking",
            "--api-url",
            "http://api",
        ]
    )

    assert uploads == [("http://api", str(document_path))]
    assert calls == [
        (
            "http://api",
            "POST",
            "/v1/extractors",
            {
                "name": "invoice_extractor",
                "instructions": "Extract invoice fields.",
                "enable_thinking": True,
                "schema": {"type": "object"},
                "examples": [],
            },
        ),
        (
            "http://api",
            "POST",
            "/v1/jobs",
            {"extractor_id": "extractor_1", "file_id": "file_1"},
        ),
        ("http://api", "GET", "/v1/jobs/job_1", None),
    ]
    assert json.loads(capsys.readouterr().out) == {"invoice_number": "A-123"}


def test_extract_reuses_extractor_with_text_and_writes_result(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    output_path = tmp_path / "result.json"
    calls: list[tuple[str, str, str, dict[str, Any] | None]] = []

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        calls.append((api_url, method, path, payload))
        if path == "/v1/jobs":
            return {"id": "job_1", "status": "running"}
        if path == "/v1/jobs/job_1":
            return {
                "id": "job_1",
                "status": "completed",
                "result": {"data": {"buyer": "Jane"}},
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(
        [
            "extract",
            "--extractor",
            "extractor_1",
            "--text",
            "Jane bought tea.",
            "--wait",
            "--poll-seconds",
            "0",
            "--output",
            str(output_path),
            "--api-url",
            "http://api",
        ]
    )

    assert calls == [
        (
            "http://api",
            "POST",
            "/v1/jobs",
            {"extractor_id": "extractor_1", "text": "Jane bought tea."},
        ),
        ("http://api", "GET", "/v1/jobs/job_1", None),
    ]
    assert json.loads(output_path.read_text(encoding="utf-8")) == {"buyer": "Jane"}
    assert capsys.readouterr().out == f"Wrote extraction output: {output_path}\n"


def test_extract_requires_exactly_one_input() -> None:
    with pytest.raises(SystemExit, match="Provide exactly one input"):
        cli.main(["extract", "document.pdf", "--file-id", "file_1", "--extractor", "extractor_1"])


def test_dev_uses_settings_defaults_for_runtime_process(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir = tmp_path / "parsehawk-data"
    config_path = tmp_path / "config.json"
    spawned: list[dict[str, Any]] = []

    config_path.write_text(json.dumps({"log.level": "DEBUG"}), encoding="utf-8")
    monkeypatch.setenv("PARSEHAWK_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PARSEHAWK_VLLM_MODEL", "model-from-env")
    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: True)
    monkeypatch.setattr(cli, "_is_linux_x86_64", lambda: False)
    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_ensure_managed_processes_alive", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cli,
        "ensure_vllm_metal_venv",
        lambda *args, **kwargs: Path("/fake/vllm-metal/bin/python"),
    )

    def spawn(
        name: str,
        cmd: list[str],
        env: dict[str, str],
        logs_dir,
    ) -> cli.ManagedProcess:
        spawned.append({"name": name, "cmd": cmd, "env": env, "logs_dir": logs_dir})
        return cli.ManagedProcess(name=name, pid=len(spawned), log_path=f"{name}.log")

    monkeypatch.setattr(cli, "_spawn", spawn)

    monkeypatch.setattr(cli, "_default_runtime", lambda: "vllm")
    cli.main(["dev", "--no-web"])

    assert [process["name"] for process in spawned] == ["runtime", "api", "worker"]
    api_env = spawned[1]["env"]
    runtime_cmd = spawned[0]["cmd"]
    assert runtime_cmd[0] == "/fake/vllm-metal/bin/python"
    assert runtime_cmd[runtime_cmd.index("--model") + 1] == "model-from-env"
    assert runtime_cmd[runtime_cmd.index("--gpu-memory-utilization") + 1] == "0.5"
    assert runtime_cmd[runtime_cmd.index("--max-model-len") + 1] == "8192"
    assert runtime_cmd[runtime_cmd.index("--max-num-seqs") + 1] == "1"
    assert spawned[0]["env"]["VLLM_USE_FLASHINFER_SAMPLER"] == "0"
    assert spawned[0]["env"]["VLLM_METAL_MEMORY_FRACTION"] == "0.5"
    assert "--no-use-colors" in spawned[1]["cmd"]
    assert api_env["PARSEHAWK_DATA_DIR"] == str(data_dir)
    assert api_env["PARSEHAWK_DATABASE_PATH"] == str(data_dir / "parsehawk.db")
    assert api_env["PARSEHAWK_LOG_LEVEL"] == "DEBUG"
    assert api_env["PARSEHAWK_INFERENCE_ENGINE"] == "vllm"
    assert api_env["PARSEHAWK_VLLM_MODEL"] == "model-from-env"
    assert "ParseHawk started: http://127.0.0.1:8000" in capsys.readouterr().out


def test_dev_launches_vllm_runtime_when_selected(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir = tmp_path / "parsehawk-data"
    spawned: list[dict[str, Any]] = []

    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PARSEHAWK_VLLM_MODEL", "numind/NuExtract3-W4A16")
    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: False)
    monkeypatch.setattr(cli, "_is_linux_x86_64", lambda: True)
    monkeypatch.setattr(cli, "_has_nvidia_gpu", lambda: True)
    monkeypatch.setattr(cli, "_nvidia_gpu_memory_bytes", lambda: 24 * 1024**3)
    monkeypatch.setattr(
        cli, "ensure_vllm_venv", lambda *args, **kwargs: Path("/fake/vllm/bin/python")
    )
    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_ensure_managed_processes_alive", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_runtime", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_api", lambda *args, **kwargs: None)

    def spawn(
        name: str,
        cmd: list[str],
        env: dict[str, str],
        logs_dir,
    ) -> cli.ManagedProcess:
        spawned.append({"name": name, "cmd": cmd, "env": env, "logs_dir": logs_dir})
        return cli.ManagedProcess(name=name, pid=len(spawned), log_path=f"{name}.log")

    monkeypatch.setattr(cli, "_spawn", spawn)

    monkeypatch.setattr(cli, "_default_runtime", lambda: "vllm")
    cli.main(["dev", "--no-web"])

    assert [process["name"] for process in spawned] == ["runtime", "api", "worker"]
    runtime_cmd = spawned[0]["cmd"]
    assert runtime_cmd[0] == "/fake/vllm/bin/python"
    assert "vllm.entrypoints.openai.api_server" in runtime_cmd
    assert runtime_cmd[runtime_cmd.index("--model") + 1] == "numind/NuExtract3-W4A16"
    assert runtime_cmd[runtime_cmd.index("--reasoning-parser") + 1] == "qwen3"
    assert runtime_cmd[runtime_cmd.index("--gpu-memory-utilization") + 1] == "0.85"
    assert runtime_cmd[runtime_cmd.index("--max-model-len") + 1] == "16384"
    assert runtime_cmd[runtime_cmd.index("--max-num-seqs") + 1] == "4"
    assert "--structured-outputs-config.enable_in_reasoning=True" in runtime_cmd
    assert spawned[0]["env"]["VLLM_USE_FLASHINFER_SAMPLER"] == "0"
    api_env = spawned[1]["env"]
    assert api_env["PARSEHAWK_INFERENCE_ENGINE"] == "vllm"
    assert api_env["PARSEHAWK_VLLM_MODEL"] == "numind/NuExtract3-W4A16"
    assert api_env["PARSEHAWK_VLLM_BASE_URL"] == "http://127.0.0.1:8080/v1"
    assert "ParseHawk started: http://127.0.0.1:8000" in capsys.readouterr().out


def test_default_runtime_selects_per_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "default_inference_engine", lambda: "vllm")
    assert cli._default_runtime() == "vllm"

    monkeypatch.setattr(cli, "default_inference_engine", lambda: None)
    assert cli._default_runtime() == cli.UNSUPPORTED_RUNTIME


def test_vllm_settings_default_to_macos_memory_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PARSEHAWK_VLLM_MAX_MODEL_LEN", raising=False)
    monkeypatch.delenv("PARSEHAWK_VLLM_GPU_MEMORY_UTILIZATION", raising=False)
    monkeypatch.delenv("PARSEHAWK_VLLM_MAX_NUM_SEQS", raising=False)
    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: True)
    monkeypatch.setattr(cli, "_is_linux_x86_64", lambda: False)
    settings = cli.Settings()

    monkeypatch.setattr(cli, "_system_memory_bytes", lambda: 36_000_000_000)
    resolved = cli._resolve_vllm_settings(settings, model="numind/NuExtract3-W4A16")
    assert resolved.vllm_max_model_len == 32768
    assert resolved.vllm_gpu_memory_utilization == 0.5
    assert resolved.vllm_max_num_seqs == 4

    monkeypatch.setattr(cli, "_system_memory_bytes", lambda: 18_000_000_000)
    resolved = cli._resolve_vllm_settings(settings, model="numind/NuExtract3-W4A16")
    assert resolved.vllm_max_model_len == 8192
    assert resolved.vllm_gpu_memory_utilization == 0.7
    assert resolved.vllm_max_num_seqs == 1


def test_vllm_settings_default_to_linux_vram_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PARSEHAWK_VLLM_MAX_MODEL_LEN", raising=False)
    monkeypatch.delenv("PARSEHAWK_VLLM_GPU_MEMORY_UTILIZATION", raising=False)
    monkeypatch.delenv("PARSEHAWK_VLLM_MAX_NUM_SEQS", raising=False)
    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: False)
    monkeypatch.setattr(cli, "_is_linux_x86_64", lambda: True)
    settings = cli.Settings()

    monkeypatch.setattr(cli, "_nvidia_gpu_memory_bytes", lambda: 12 * 1024**3)
    resolved = cli._resolve_vllm_settings(settings, model="numind/NuExtract3-W4A16")
    assert resolved.vllm_max_model_len == 8192
    assert resolved.vllm_gpu_memory_utilization == 0.9
    assert resolved.vllm_max_num_seqs == 1

    monkeypatch.setattr(cli, "_nvidia_gpu_memory_bytes", lambda: 24 * 1024**3)
    resolved = cli._resolve_vllm_settings(settings, model="numind/NuExtract3-W4A16")
    assert resolved.vllm_max_model_len == 16384
    assert resolved.vllm_gpu_memory_utilization == 0.85
    assert resolved.vllm_max_num_seqs == 4

    monkeypatch.setattr(cli, "_nvidia_gpu_memory_bytes", lambda: 48 * 1024**3)
    resolved = cli._resolve_vllm_settings(settings, model="numind/NuExtract3-W4A16")
    assert resolved.vllm_max_model_len == 32768
    assert resolved.vllm_gpu_memory_utilization == 0.75
    assert resolved.vllm_max_num_seqs == 8


def test_vllm_settings_env_overrides_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSEHAWK_VLLM_MAX_MODEL_LEN", "16384")
    monkeypatch.setenv("PARSEHAWK_VLLM_GPU_MEMORY_UTILIZATION", "0.6")
    monkeypatch.setenv("PARSEHAWK_VLLM_MAX_NUM_SEQS", "2")
    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: True)
    monkeypatch.setattr(cli, "_is_linux_x86_64", lambda: False)
    monkeypatch.setattr(cli, "_system_memory_bytes", lambda: 36_000_000_000)

    resolved = cli._resolve_vllm_settings(
        cli.Settings.from_env(),
        model="numind/NuExtract3-W4A16",
    )
    assert resolved.vllm_max_model_len == 16384
    assert resolved.vllm_gpu_memory_utilization == 0.6
    assert resolved.vllm_max_num_seqs == 2


def test_platform_dependencies_skip_runtime_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "_ensure_xcode_command_line_tools",
        lambda: pytest.fail("runtime none should not check platform runtime deps"),
    )
    monkeypatch.setattr(cli, "_has_nvidia_gpu", lambda: pytest.fail("unexpected GPU check"))
    monkeypatch.setattr(
        cli,
        "_docker_supports_nvidia_runtime",
        lambda: pytest.fail("unexpected Docker runtime check"),
    )

    cli._ensure_platform_dependencies("none")


def test_platform_dependencies_macos_checks_xcode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: True)
    monkeypatch.setattr(cli, "_is_linux_x86_64", lambda: False)
    monkeypatch.setattr(cli, "_ensure_xcode_command_line_tools", lambda: calls.append("xcode"))
    monkeypatch.setattr(cli, "_has_nvidia_gpu", lambda: pytest.fail("unexpected GPU check"))
    monkeypatch.setattr(
        cli,
        "_docker_supports_nvidia_runtime",
        lambda: pytest.fail("unexpected Docker runtime check"),
    )

    cli._ensure_platform_dependencies("vllm")

    assert calls == ["xcode"]


def test_platform_dependencies_linux_checks_gpu_and_docker_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: False)
    monkeypatch.setattr(cli, "_is_linux_x86_64", lambda: True)
    monkeypatch.setattr(cli, "_has_nvidia_gpu", lambda: True)
    monkeypatch.setattr(cli, "_docker_supports_nvidia_runtime", lambda: True)
    monkeypatch.setattr(
        cli,
        "_ensure_xcode_command_line_tools",
        lambda: pytest.fail("unexpected Xcode check"),
    )

    cli._ensure_platform_dependencies("vllm")


def test_platform_dependencies_linux_requires_nvidia_docker_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: False)
    monkeypatch.setattr(cli, "_is_linux_x86_64", lambda: True)
    monkeypatch.setattr(cli, "_has_nvidia_gpu", lambda: True)
    monkeypatch.setattr(cli, "_docker_supports_nvidia_runtime", lambda: False)

    with pytest.raises(SystemExit, match="NVIDIA Container Toolkit"):
        cli._ensure_platform_dependencies("vllm")


def test_dev_vllm_without_gpu_exits_with_clear_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: False)
    monkeypatch.setattr(cli, "_has_nvidia_gpu", lambda: False)
    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)

    def spawn(*args: Any, **kwargs: Any) -> cli.ManagedProcess:
        raise AssertionError("vllm runtime must not spawn without a GPU")

    monkeypatch.setattr(cli, "_spawn", spawn)

    with pytest.raises(SystemExit, match="needs an NVIDIA CUDA GPU"):
        monkeypatch.setattr(cli, "_default_runtime", lambda: "vllm")
        cli.main(["dev", "--no-web", "--data-dir", str(tmp_path)])


def test_start_errors_when_platform_has_no_model_runtime(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_default_runtime", lambda: cli.UNSUPPORTED_RUNTIME)

    def spawn(*args: Any, **kwargs: Any) -> cli.ManagedProcess:
        raise AssertionError("start must not spawn on an unsupported platform")

    monkeypatch.setattr(cli, "_spawn", spawn)

    with pytest.raises(SystemExit, match="No bundled model runtime is available"):
        cli.main(["start", "--no-web", "--data-dir", str(tmp_path)])


def test_wait_for_runtime_fails_fast_when_process_dies(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "runtime.log"
    log_path.write_text("boom: No CUDA GPUs are available\n", encoding="utf-8")
    process = cli.ManagedProcess(name="runtime", pid=4321, log_path=str(log_path))
    monkeypatch.setattr(cli, "_pid_running", lambda pid: False)

    with pytest.raises(SystemExit, match="exited before becoming ready"):
        cli._wait_for_runtime("http://127.0.0.1:8080/health", process, timeout_seconds=5)


def test_start_refuses_untracked_api_port(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(tmp_path))

    def tcp_port_open(host: str, port: int) -> bool:
        return host == "127.0.0.1" and port == 8000

    def spawn(*args: Any, **kwargs: Any) -> cli.ManagedProcess:
        raise AssertionError("start should fail before spawning processes")

    monkeypatch.setattr(cli, "_tcp_port_open", tcp_port_open)
    monkeypatch.setattr(cli, "_spawn", spawn)

    with pytest.raises(SystemExit, match="API port 127.0.0.1:8000 is already in use"):
        cli.main(["start", "-x", "runtime", "--no-web"])


def test_dev_discards_partial_stale_state(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    cli._write_state(
        tmp_path / "parsehawk-state.json",
        cli.ParseHawkState(
            data_dir=str(tmp_path),
            api_url="http://127.0.0.1:8000",
            runtime_url=None,
            web_url=None,
            processes=[
                cli.ManagedProcess(name="api", pid=101, log_path="api.log"),
                cli.ManagedProcess(name="worker", pid=102, log_path="worker.log"),
            ],
        ),
    )
    stopped: list[list[str]] = []
    spawned: list[str] = []

    monkeypatch.setattr(cli, "_pid_running", lambda pid: pid == 102)
    monkeypatch.setattr(
        cli,
        "_stop_processes",
        lambda processes: stopped.append([process.name for process in processes]),
    )
    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_ensure_managed_processes_alive", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_api", lambda *args, **kwargs: None)

    def spawn(
        name: str,
        cmd: list[str],
        env: dict[str, str],
        logs_dir,
    ) -> cli.ManagedProcess:
        spawned.append(name)
        return cli.ManagedProcess(name=name, pid=200 + len(spawned), log_path=f"{name}.log")

    monkeypatch.setattr(cli, "_spawn", spawn)

    cli.main(
        [
            "dev",
            "-x",
            "runtime",
            "--data-dir",
            str(tmp_path),
            "--no-web",
        ]
    )

    assert stopped == [["worker"]]
    assert spawned == ["api", "worker"]
    assert "ParseHawk started: http://127.0.0.1:8000" in capsys.readouterr().out


def test_start_uses_docker_compose_mode(tmp_path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    data_dir = tmp_path / "parsehawk-data"
    compose_ups: list[dict[str, Any]] = []

    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(data_dir))
    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_ensure_docker_available", lambda: None)
    monkeypatch.setattr(cli, "_ensure_platform_dependencies", lambda runtime: None)
    monkeypatch.setattr(cli, "_wait_for_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cli,
        "_compose_up",
        lambda **kwargs: compose_ups.append(kwargs),
    )

    cli.main(["start", "-x", "runtime"])

    assert compose_ups[0]["services"] == ["api", "worker", "web"]
    assert compose_ups[0]["env"]["PARSEHAWK_INFERENCE_ENGINE"] == "none"
    assert compose_ups[0]["env"]["PARSEHAWK_HOST_DATA_DIR"] == str(data_dir.resolve())
    state = cli._load_state(data_dir / "parsehawk-state.json")
    assert state.mode == "docker"
    assert state.api_url == "http://127.0.0.1:8000"
    assert state.web_url == "http://127.0.0.1:5173"
    output = capsys.readouterr().out
    assert "==> Starting ParseHawk in Docker mode" in output
    assert "==> Checking Docker" in output
    assert "==> Building and starting Docker services: api, worker, web" in output
    assert "ParseHawk started: http://127.0.0.1:8000" in output


def test_status_uses_dev_checkout_data_dir_from_any_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "config.json"
    project_dir = tmp_path / "project"
    other_dir = tmp_path / "elsewhere"
    project_dir.mkdir()
    (project_dir / ".git").mkdir()
    (project_dir / "pyproject.toml").write_text("[project]\nname = 'parsehawk'\n", encoding="utf-8")
    other_dir.mkdir()

    monkeypatch.setenv("PARSEHAWK_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("PARSEHAWK_DATA_DIR", raising=False)
    monkeypatch.setattr(cli, "_repo_root", lambda: project_dir)
    monkeypatch.setattr(cli, "_print_telemetry_notice", lambda data_dir: None)
    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_ensure_docker_available", lambda: None)
    monkeypatch.setattr(cli, "_ensure_platform_dependencies", lambda runtime: None)
    monkeypatch.setattr(cli, "_wait_for_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_compose_up", lambda **kwargs: None)
    monkeypatch.setattr(cli, "_compose_is_running", lambda state: True)
    monkeypatch.setattr(cli, "_compose_service_running", lambda state, service: True)
    monkeypatch.chdir(project_dir)

    cli.main(["start", "-x", "runtime", "--no-web"])

    data_dir = project_dir / "data"
    assert not config_path.exists()
    assert (data_dir / "parsehawk-state.json").is_file()

    capsys.readouterr()
    monkeypatch.chdir(other_dir)

    cli.main(["status"])

    output = capsys.readouterr().out
    assert "ParseHawk is not running" not in output
    assert "ParseHawk API: http://127.0.0.1:8000" in output
    assert "Docker Compose:" in output


def test_start_does_not_persist_env_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    env_data_dir = tmp_path / "env-data"
    config_path.write_text(json.dumps({"data.dir": "data"}), encoding="utf-8")

    monkeypatch.setenv("PARSEHAWK_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(env_data_dir))
    monkeypatch.setattr(cli, "_print_telemetry_notice", lambda data_dir: None)
    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_ensure_docker_available", lambda: None)
    monkeypatch.setattr(cli, "_ensure_platform_dependencies", lambda runtime: None)
    monkeypatch.setattr(cli, "_wait_for_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_compose_up", lambda **kwargs: None)

    cli.main(["start", "-x", "runtime", "--no-web"])

    assert json.loads(config_path.read_text(encoding="utf-8"))["data.dir"] == "data"
    assert (env_data_dir / "parsehawk-state.json").is_file()


def test_default_data_dir_uses_user_home_outside_dev_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package_dir = tmp_path / "installed-package"
    home_dir = tmp_path / "home"
    package_dir.mkdir()
    home_dir.mkdir()

    monkeypatch.setattr(cli, "_repo_root", lambda: package_dir)
    monkeypatch.setattr(cli.Path, "home", lambda: home_dir)

    assert cli._default_data_dir() == home_dir / ".parsehawk" / "data"


def test_start_linux_vllm_uses_internal_runtime_port(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir = tmp_path / "parsehawk-data"
    compose_ups: list[dict[str, Any]] = []
    runtime_health_urls: list[str] = []

    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(data_dir))
    monkeypatch.setattr(cli, "_is_macos_apple_silicon", lambda: False)
    monkeypatch.setattr(cli, "_is_linux_x86_64", lambda: True)
    monkeypatch.setattr(cli, "_nvidia_gpu_memory_bytes", lambda: 24 * 1024**3)
    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_ensure_docker_available", lambda: None)
    monkeypatch.setattr(cli, "_ensure_platform_dependencies", lambda runtime: None)
    monkeypatch.setattr(cli, "_wait_for_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_wait_for_url", lambda url, **kwargs: runtime_health_urls.append(url))
    monkeypatch.setattr(
        cli,
        "_compose_up",
        lambda **kwargs: compose_ups.append(kwargs),
    )

    monkeypatch.setattr(cli, "_default_runtime", lambda: "vllm")
    cli.main(["start", "--runtime-port", "18080", "--no-web"])

    assert compose_ups[0]["services"] == ["runtime", "api", "worker"]
    assert any(path.name == "docker-compose.linux.yml" for path in compose_ups[0]["compose_files"])
    assert compose_ups[0]["env"]["PARSEHAWK_RUNTIME_PORT"] == "18080"
    assert compose_ups[0]["env"]["PARSEHAWK_INFERENCE_ENGINE"] == "vllm"
    assert compose_ups[0]["env"]["PARSEHAWK_VLLM_BASE_URL"] == "http://runtime:8080/v1"
    assert compose_ups[0]["env"]["PARSEHAWK_VLLM_MAX_MODEL_LEN"] == "16384"
    assert compose_ups[0]["env"]["PARSEHAWK_VLLM_MAX_NUM_SEQS"] == "4"
    assert compose_ups[0]["env"]["PARSEHAWK_VLLM_GPU_MEMORY_UTILIZATION"] == "0.85"
    assert runtime_health_urls == ["http://127.0.0.1:18080/health"]
    state = cli._load_state(data_dir / "parsehawk-state.json")
    assert state.runtime_url == "http://127.0.0.1:18080/v1"
    output = capsys.readouterr().out
    assert "First vLLM startup can take several minutes" in output


def test_start_prints_status_when_docker_state_is_running(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir = tmp_path / "parsehawk-data"
    state = cli.ParseHawkState(
        data_dir=str(data_dir),
        api_url="http://127.0.0.1:8000",
        runtime_url="http://127.0.0.1:8080/v1",
        web_url="http://127.0.0.1:5173",
        processes=[
            cli.ManagedProcess(
                name="runtime",
                pid=82304,
                log_path=str(data_dir / "logs" / "runtime.log"),
            )
        ],
        mode="docker",
        compose_project="parsehawk_test",
        compose_files=["docker/docker-compose.yml"],
    )
    data_dir.mkdir(parents=True)
    cli._write_state(data_dir / "parsehawk-state.json", state)

    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(data_dir))
    monkeypatch.setattr(cli, "_compose_is_running", lambda current: True)
    monkeypatch.setattr(cli, "_compose_service_running", lambda current, service: True)
    monkeypatch.setattr(cli, "_pid_running", lambda pid: pid == 82304)

    cli.main(["start"])

    output = capsys.readouterr().out
    assert "ParseHawk is already running\n" in output
    assert "Mode: docker\n" in output
    assert "ParseHawk API: http://127.0.0.1:8000\n" in output
    assert "Model Runtime: http://127.0.0.1:8080/v1\n" in output
    assert "ParseHawk Web UI: http://127.0.0.1:5173\n" in output
    assert "Docker Compose: running project=parsehawk_test\n" in output
    assert "ParseHawk API: running\n" in output
    assert "ParseHawk Worker: running\n" in output
    assert "ParseHawk Web UI: running\n" in output
    assert f"Model Runtime: running pid=82304 log={data_dir / 'logs' / 'runtime.log'}\n" in output


def test_compose_up_error_mentions_registry_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*args: Any, **kwargs: Any) -> None:
        raise cli.subprocess.CalledProcessError(1, ["docker", "compose"])

    monkeypatch.setattr(cli.subprocess, "run", fail_run)

    with pytest.raises(SystemExit) as exc_info:
        cli._compose_up(
            compose_files=[Path("docker/docker-compose.yml")],
            project_name="parsehawk_test",
            env={},
            services=["api", "worker", "web"],
        )

    message = str(exc_info.value)
    assert "Docker Hub" in message
    assert "retry `uv run parsehawk start`" in message


def test_restart_stops_tracked_processes_then_starts(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    cli._write_state(
        tmp_path / "parsehawk-state.json",
        cli.ParseHawkState(
            data_dir=str(tmp_path),
            api_url="http://127.0.0.1:8000",
            runtime_url=None,
            web_url=None,
            processes=[],
            mode="docker",
            compose_project="parsehawk_test",
            compose_files=["docker/docker-compose.yml"],
        ),
    )
    compose_downs: list[str] = []
    compose_ups: list[list[str]] = []

    monkeypatch.setattr(cli, "_stop_processes", lambda processes: None)
    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_ensure_docker_available", lambda: None)
    monkeypatch.setattr(cli, "_ensure_platform_dependencies", lambda runtime: None)
    monkeypatch.setattr(cli, "_wait_for_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cli,
        "_compose_down",
        lambda **kwargs: compose_downs.append(kwargs["project_name"]),
    )
    monkeypatch.setattr(
        cli,
        "_compose_up",
        lambda **kwargs: compose_ups.append(kwargs["services"]),
    )

    cli.main(
        [
            "restart",
            "-x",
            "runtime",
            "--data-dir",
            str(tmp_path),
            "--no-web",
        ]
    )

    state = cli._load_state(tmp_path / "parsehawk-state.json")
    assert compose_downs == ["parsehawk_test"]
    assert compose_ups == [["api", "worker"]]
    assert state.mode == "docker"
    assert state.processes == []
    assert "ParseHawk stopped" in capsys.readouterr().out


def test_config_set_and_list_uses_config_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("PARSEHAWK_CONFIG_PATH", str(config_path))

    cli.main(["config", "set", "server.url", "http://api"])
    assert capsys.readouterr().out == "Set server.url=http://api\n"

    cli.main(["config", "list", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["server.url"] == "http://api"
    assert payload["runtime.model"] == "numind/NuExtract3-W4A16"
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"server.url": "http://api"}


def test_runtime_test_checks_health_and_model(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    calls: list[tuple[str, float]] = []

    def http_get_json(url: str, *, timeout: float) -> tuple[bool, Any, str]:
        calls.append((url, timeout))
        if url == "http://runtime/health":
            return True, {"status": "ok"}, ""
        if url == "http://runtime/v1/models":
            return True, {"data": [{"id": "model-a"}]}, ""
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(cli, "http_get_json", http_get_json)

    cli.main(
        [
            "runtime",
            "test",
            "--runtime-url",
            "http://runtime/v1",
            "--model",
            "model-a",
            "--json",
        ]
    )

    assert calls == [("http://runtime/health", 3), ("http://runtime/v1/models", 3)]
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "name": "Model Runtime",
            "status": "ok",
            "detail": "reachable at http://runtime/v1",
        },
        {
            "name": "Model Runtime Model",
            "status": "ok",
            "detail": "model is available: model-a",
        },
    ]


def test_doctor_checks_default_runtime_model_even_with_saved_model_config(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "server.url": "http://api",
                "web.url": "http://web",
                "runtime.url": "http://runtime/v1",
                "runtime.model": "configured-model",
                "data.dir": str(tmp_path / "data"),
                "log.level": "INFO",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PARSEHAWK_CONFIG_PATH", str(config_path))
    calls: list[dict[str, Any]] = []

    def doctor_checks(**kwargs: Any) -> list[cli.CheckResult]:
        calls.append(kwargs)
        return [cli.CheckResult("Model Runtime Model", "ok", "model is available")]

    monkeypatch.setattr(cli, "doctor_checks", doctor_checks)

    cli.main(["doctor"])

    assert calls == [
        {
            "api_url": "http://api",
            "web_url": "http://web",
            "runtime_url": "http://runtime/v1",
            "model": "numind/NuExtract3-W4A16",
            "data_dir": tmp_path / "data",
        }
    ]
    assert capsys.readouterr().out == "OK   Model Runtime Model: model is available\n"


def test_doctor_checks_web_ui(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    http_json_calls: list[str] = []
    http_calls: list[str] = []
    runtime_calls: list[dict[str, str]] = []

    def check_http_json(**kwargs: Any) -> cli.CheckResult:
        http_json_calls.append(kwargs["url"])
        return cli.CheckResult(kwargs["name"], "ok", kwargs["success_detail"])

    def check_http(**kwargs: Any) -> cli.CheckResult:
        http_calls.append(kwargs["url"])
        return cli.CheckResult(kwargs["name"], "ok", kwargs["success_detail"])

    def runtime_checks(**kwargs: str) -> list[cli.CheckResult]:
        runtime_calls.append(dict(kwargs))
        return [cli.CheckResult("Model Runtime Model", "ok", "model is available")]

    def check_worker(data_dir: Path) -> cli.CheckResult:
        return cli.CheckResult("ParseHawk Worker", "ok", f"running from {data_dir}")

    monkeypatch.setattr(cli, "check_http_json", check_http_json)
    monkeypatch.setattr(cli, "check_http", check_http)
    monkeypatch.setattr(cli, "check_worker", check_worker)
    monkeypatch.setattr(cli, "runtime_checks", runtime_checks)

    checks = cli.doctor_checks(
        api_url="http://api",
        web_url="http://web",
        runtime_url="http://runtime/v1",
        model="numind/NuExtract3-W4A16",
        data_dir=tmp_path,
    )

    assert [check.name for check in checks] == [
        "Python",
        "Data directory",
        "ParseHawk API",
        "ParseHawk Web UI",
        "ParseHawk Worker",
        "Model Runtime Model",
    ]
    assert http_json_calls == ["http://api/health"]
    assert http_calls == ["http://web"]
    assert runtime_calls == [
        {"runtime_url": "http://runtime/v1", "model": "numind/NuExtract3-W4A16"}
    ]


def test_check_worker_uses_tracked_local_worker_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli._write_state(
        tmp_path / "parsehawk-state.json",
        cli.ParseHawkState(
            data_dir=str(tmp_path),
            api_url="http://127.0.0.1:8000",
            runtime_url=None,
            web_url=None,
            processes=[
                cli.ManagedProcess(name="api", pid=101, log_path="api.log"),
                cli.ManagedProcess(name="worker", pid=102, log_path="worker.log"),
            ],
        ),
    )
    monkeypatch.setattr(cli, "_pid_running", lambda pid: pid == 102)

    check = cli.check_worker(tmp_path)

    assert check == cli.CheckResult("ParseHawk Worker", "ok", "running pid=102")


def test_check_worker_uses_docker_compose_worker_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli._write_state(
        tmp_path / "parsehawk-state.json",
        cli.ParseHawkState(
            data_dir=str(tmp_path),
            api_url="http://127.0.0.1:8000",
            runtime_url=None,
            web_url=None,
            processes=[],
            mode="docker",
            compose_project="parsehawk_test",
            compose_files=["docker/docker-compose.yml"],
        ),
    )
    monkeypatch.setattr(
        cli,
        "_compose_service_running",
        lambda state, service: service == "worker",
    )

    check = cli.check_worker(tmp_path)

    assert check == cli.CheckResult("ParseHawk Worker", "ok", "Docker service is running")


def test_compose_services_from_ps_json_supports_array_and_lines() -> None:
    assert cli._compose_services_from_ps_json(
        json.dumps([{"Service": "api"}, {"Service": "worker"}])
    ) == {"api", "worker"}
    assert cli._compose_services_from_ps_json('{"Service":"web"}\n{"Service":"worker"}\n') == {
        "web",
        "worker",
    }
    assert cli._compose_services_from_ps_json(
        json.dumps([{"Name": "parsehawk_test-api-1"}, {"Name": "parsehawk_test-worker-1"}])
    ) == {"api", "worker"}


def test_doctor_exits_nonzero_for_failed_check(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("PARSEHAWK_CONFIG_PATH", str(tmp_path / "config.json"))

    def doctor_checks(**kwargs: Any) -> list[cli.CheckResult]:
        return [cli.CheckResult("ParseHawk API", "fail", "unreachable")]

    monkeypatch.setattr(cli, "doctor_checks", doctor_checks)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["doctor", "--api-url", "http://api"])

    assert exc_info.value.code == 1
    assert capsys.readouterr().out == "FAIL ParseHawk API: unreachable\n"


def test_upload_file_sends_multipart(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = tmp_path / "document.txt"
    document.write_text("hello", encoding="utf-8")
    calls = []

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, str]:
        calls.append((api_url, method, path, data, headers, kwargs))
        return {"id": "file_1"}

    monkeypatch.setattr(cli, "api_request", api_request)

    assert cli.upload_file("http://api", str(document)) == {"id": "file_1"}

    api_url, method, path, data, headers, kwargs = calls[0]
    assert (api_url, method, path, kwargs) == ("http://api", "POST", "/v1/files", {})
    assert headers is not None
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert data is not None
    assert b'name="upload"; filename="document.txt"' in data
    assert b"hello" in data


def test_migrate_applies_pending_then_reports_up_to_date(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PARSEHAWK_SKIP_MIGRATIONS", "0")

    cli.main(["migrate"])

    first = capsys.readouterr().out
    assert "20260701092442_initial_schema" in first
    assert (data_dir / "parsehawk.db").exists()

    cli.main(["migrate"])

    assert "up to date" in capsys.readouterr().out


def test_migrate_status_reports_applied_and_pending(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(data_dir))

    cli.main(["migrate", "status", "--json"])

    assert json.loads(capsys.readouterr().out) == {
        "applied": [],
        "pending": ["20260701092442_initial_schema", "20260701121138_add_providers"],
    }

    cli.main(["migrate"])
    capsys.readouterr()
    cli.main(["migrate", "status", "--json"])

    assert json.loads(capsys.readouterr().out) == {
        "applied": ["20260701092442_initial_schema", "20260701121138_add_providers"],
        "pending": [],
    }


def test_apply_migrations_at_start_skips_and_sets_env_when_excluded(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("PARSEHAWK_SKIP_MIGRATIONS", "0")
    database_path = tmp_path / "parsehawk.db"

    cli._apply_migrations_at_start(argparse.Namespace(exclude=["migrate"]), database_path)

    assert os.environ["PARSEHAWK_SKIP_MIGRATIONS"] == "1"
    assert not database_path.exists()
    assert "Skipping database migrations" in capsys.readouterr().out


def test_apply_migrations_at_start_applies_when_not_excluded(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("PARSEHAWK_SKIP_MIGRATIONS", "0")
    database_path = tmp_path / "parsehawk.db"

    cli._apply_migrations_at_start(argparse.Namespace(exclude=None), database_path)

    assert database_path.exists()
    assert (
        "Applied 2 migration(s): 20260701092442_initial_schema, 20260701121138_add_providers"
        in capsys.readouterr().out
    )


def test_start_exclude_migrate_propagates_skip_to_containers(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data_dir = tmp_path / "data"
    compose_ups: list[dict[str, Any]] = []

    monkeypatch.setenv("PARSEHAWK_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PARSEHAWK_SKIP_MIGRATIONS", "0")
    # Pre-migrate so seeding has a schema even though start will skip migrations.
    cli.main(["migrate"])
    capsys.readouterr()

    monkeypatch.setattr(cli, "_ensure_start_ports_available", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_ensure_docker_available", lambda: None)
    monkeypatch.setattr(cli, "_ensure_platform_dependencies", lambda runtime: None)
    monkeypatch.setattr(cli, "_wait_for_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_compose_up", lambda **kwargs: compose_ups.append(kwargs))

    cli.main(["start", "-x", "runtime", "--no-web", "-x", "migrate"])

    assert compose_ups[0]["env"]["PARSEHAWK_SKIP_MIGRATIONS"] == "1"
    assert "Skipping database migrations" in capsys.readouterr().out


def test_providers_list_get_and_models_hit_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def api_request(api_url: str, method: str, path: str, **kwargs: Any) -> list[Any]:
        calls.append((method, path))
        return []

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(["providers", "list", "--api-url", "http://api"])
    cli.main(["providers", "get", "azure_openai", "--api-url", "http://api"])
    cli.main(["providers", "models", "openai", "--api-url", "http://api"])

    assert calls == [
        ("GET", "/v1/providers"),
        ("GET", "/v1/providers/azure_openai"),
        ("GET", "/v1/providers/openai/models"),
    ]


def test_providers_configure_builds_patch_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, str, dict[str, Any] | None]] = []

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        captured.append((method, path, payload))
        return {"name": "openai", "has_api_key": True}

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(
        [
            "providers",
            "configure",
            "openai",
            "--base-url",
            "https://api.openai.com/v1",
            "--api-key",
            "sk-secret",
            "--api-url",
            "http://api",
        ]
    )

    assert captured == [
        (
            "PATCH",
            "/v1/providers/openai",
            {"base_url": "https://api.openai.com/v1", "api_key": "sk-secret"},
        )
    ]


def test_providers_configure_requires_an_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "api_request", lambda *args, **kwargs: {})

    with pytest.raises(SystemExit):
        cli.main(["providers", "configure", "openai", "--api-url", "http://api"])


def test_extractors_create_includes_provider_and_model(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_path = tmp_path / "schema.json"
    schema_path.write_text('{"type": "object"}', encoding="utf-8")
    captured: list[dict[str, Any] | None] = []

    def api_request(
        api_url: str,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        captured.append(payload)
        return {"id": "extractor_1"}

    monkeypatch.setattr(cli, "api_request", api_request)

    cli.main(
        [
            "extractors",
            "create",
            "--name",
            "X",
            "--instructions",
            "Extract.",
            "--schema",
            str(schema_path),
            "--provider",
            "openai",
            "--model",
            "gpt-4o-mini",
            "--api-url",
            "http://api",
        ]
    )

    assert captured[0] is not None
    assert captured[0]["provider_name"] == "openai"
    assert captured[0]["model"] == "gpt-4o-mini"
