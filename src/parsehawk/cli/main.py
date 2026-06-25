from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from parsehawk.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_VLLM_MAX_MODEL_LEN,
    DEFAULT_VLLM_MODEL,
    Settings,
    default_inference_engine,
)
from parsehawk.server.runtime.vllm_env import (
    ensure_vllm_metal_venv,
    ensure_vllm_venv,
    vllm_launch_env,
)

UNSUPPORTED_RUNTIME = "unsupported"
NUEXTRACT3_W4A16_HIGH_MEMORY_THRESHOLD_BYTES = 32_000_000_000
NUEXTRACT3_W4A16_HIGH_MEMORY_MAX_MODEL_LEN = 32768


def _default_runtime() -> str:
    """Pick the inference runtime that ships for the current platform.

    Returns ``UNSUPPORTED_RUNTIME`` when the host has no bundled runtime; `start`
    turns that into a clear error instead of falling back to a fake engine.
    """
    engine = default_inference_engine()
    if engine == "vllm":
        return "vllm"
    return UNSUPPORTED_RUNTIME


def _default_model() -> str:
    return DEFAULT_VLLM_MODEL


def _system_memory_bytes() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None
    if not isinstance(pages, int) or not isinstance(page_size, int):
        return None
    if pages <= 0 or page_size <= 0:
        return None
    return pages * page_size


def _default_vllm_max_model_len_for_host(model: str) -> int:
    if model.lower() != DEFAULT_VLLM_MODEL.lower():
        return DEFAULT_VLLM_MAX_MODEL_LEN
    if not _is_macos_apple_silicon():
        return DEFAULT_VLLM_MAX_MODEL_LEN
    memory_bytes = _system_memory_bytes()
    if memory_bytes is not None and memory_bytes >= NUEXTRACT3_W4A16_HIGH_MEMORY_THRESHOLD_BYTES:
        return NUEXTRACT3_W4A16_HIGH_MEMORY_MAX_MODEL_LEN
    return DEFAULT_VLLM_MAX_MODEL_LEN


def _resolve_vllm_settings(settings: Settings, *, model: str) -> Settings:
    if os.getenv("PARSEHAWK_VLLM_MAX_MODEL_LEN") is not None:
        return settings
    return settings.model_copy(
        update={"vllm_max_model_len": _default_vllm_max_model_len_for_host(model)}
    )


def _has_nvidia_gpu() -> bool:
    """Best-effort check that an NVIDIA GPU is usable for the vLLM runtime."""
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() != b""


def _is_macos_apple_silicon() -> bool:
    return sys.platform == "darwin" and os.uname().machine == "arm64"


def _is_linux_x86_64() -> bool:
    return sys.platform.startswith("linux") and os.uname().machine == "x86_64"


def _vllm_runtime_command(
    *,
    settings: Settings,
    model: str,
    host: str,
    port: int,
    python: str = sys.executable,
) -> list[str]:
    command = [
        python,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        model,
        "--served-model-name",
        model,
        "--host",
        host,
        "--port",
        str(port),
        "--trust-remote-code",
        "--chat-template-content-format",
        "openai",
        "--generation-config",
        "vllm",
        "--reasoning-parser",
        "qwen3",
        "--limit-mm-per-prompt",
        json.dumps({"image": settings.pdf_max_pages, "video": 0}),
        "--gpu-memory-utilization",
        str(settings.vllm_gpu_memory_utilization),
        "--max-model-len",
        str(settings.vllm_max_model_len),
        "--structured-outputs-config.enable_in_reasoning=True",
    ]
    if settings.vllm_enable_mtp:
        command += [
            "--speculative-config",
            json.dumps({"method": "qwen3_next_mtp", "num_speculative_tokens": 2}),
        ]
    return command


DEFAULT_CLI_CONFIG = {
    "server.url": "http://127.0.0.1:8000",
    "web.url": "http://127.0.0.1:5173",
    "runtime.url": "http://127.0.0.1:8080/v1",
    "runtime.model": _default_model(),
    "data.dir": str(DEFAULT_DATA_DIR),
    "log.level": "INFO",
}
CONFIG_ENV_OVERRIDES = {
    "server.url": "PARSEHAWK_API_URL",
    "web.url": "PARSEHAWK_WEB_URL",
    "runtime.url": "PARSEHAWK_VLLM_BASE_URL",
    "runtime.model": "PARSEHAWK_VLLM_MODEL",
    "data.dir": "PARSEHAWK_DATA_DIR",
    "log.level": "PARSEHAWK_LOG_LEVEL",
}


@dataclass(frozen=True)
class ManagedProcess:
    name: str
    pid: int
    log_path: str


@dataclass(frozen=True)
class ParseHawkState:
    data_dir: str
    api_url: str
    runtime_url: str | None
    web_url: str | None
    processes: list[ManagedProcess]
    mode: str = "local"
    compose_project: str | None = None
    compose_files: list[str] | None = None


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "start":
        start(args)
    elif args.command == "dev":
        dev(args)
    elif args.command == "restart":
        restart(args)
    elif args.command == "stop":
        stop(_resolve_data_dir(args.data_dir))
    elif args.command == "status":
        status(_resolve_data_dir(args.data_dir))
    elif args.command == "files":
        files(args)
    elif args.command == "schemas":
        schemas(args)
    elif args.command == "extractors":
        extractors(args)
    elif args.command == "jobs":
        jobs(args)
    elif args.command == "extract":
        extract(args)
    elif args.command == "config":
        config_command(args)
    elif args.command == "doctor":
        doctor(args)
    elif args.command == "runtime":
        runtime_command(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="parsehawk")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start")
    _add_start_options(start_parser)

    dev_parser = subparsers.add_parser("dev", help="Run ParseHawk from local source")
    _add_start_options(dev_parser, include_docker_options=False)

    restart_parser = subparsers.add_parser("restart")
    _add_start_options(restart_parser)

    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--data-dir")

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--data-dir")

    doctor_parser = subparsers.add_parser("doctor", help="Check local ParseHawk setup")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument("--api-url")
    doctor_parser.add_argument("--web-url")
    doctor_parser.add_argument("--runtime-url")
    doctor_parser.add_argument("--data-dir")

    config_parser = subparsers.add_parser("config", help="Manage ParseHawk CLI config")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_list_parser = config_subparsers.add_parser("list")
    config_list_parser.add_argument("--json", action="store_true")
    config_set_parser = config_subparsers.add_parser("set")
    config_set_parser.add_argument("key")
    config_set_parser.add_argument("value")

    runtime_parser = subparsers.add_parser("runtime", help="Inspect the configured model runtime")
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_info_parser = runtime_subparsers.add_parser("info")
    runtime_info_parser.add_argument("--runtime-url")
    runtime_info_parser.add_argument("--model")
    runtime_info_parser.add_argument("--json", action="store_true")
    runtime_test_parser = runtime_subparsers.add_parser("test")
    runtime_test_parser.add_argument("--runtime-url")
    runtime_test_parser.add_argument("--model")
    runtime_test_parser.add_argument("--json", action="store_true")
    runtime_doctor_parser = runtime_subparsers.add_parser("doctor")
    runtime_doctor_parser.add_argument("--runtime-url")
    runtime_doctor_parser.add_argument("--model")
    runtime_doctor_parser.add_argument("--json", action="store_true")

    extract_parser = subparsers.add_parser("extract", help="Run a one-shot extraction")
    extract_parser.add_argument("source", nargs="?")
    extract_parser.add_argument("--extractor")
    extract_parser.add_argument("--schema")
    extract_parser.add_argument("--instructions")
    extract_parser.add_argument("--name")
    extract_parser.add_argument("--enable-thinking", action="store_true")
    extract_input = extract_parser.add_mutually_exclusive_group()
    extract_input.add_argument("--file-id")
    extract_input.add_argument("--text")
    extract_input.add_argument("--text-file")
    extract_parser.add_argument("--wait", action="store_true")
    extract_parser.add_argument("--poll-seconds", type=float, default=1.0)
    extract_parser.add_argument("--timeout-seconds", type=float, default=600.0)
    extract_parser.add_argument("--output")
    _add_api_url(extract_parser)

    files_parser = subparsers.add_parser("files", help="Manage uploaded files")
    files_subparsers = files_parser.add_subparsers(dest="files_command", required=True)
    files_list_parser = files_subparsers.add_parser("list")
    _add_api_url(files_list_parser)
    files_get_parser = files_subparsers.add_parser("get")
    files_get_parser.add_argument("file_id")
    _add_api_url(files_get_parser)
    files_upload_parser = files_subparsers.add_parser("upload", aliases=["create"])
    files_upload_parser.add_argument("path", nargs="?")
    files_upload_parser.add_argument("--file", dest="file_path")
    _add_api_url(files_upload_parser)
    files_delete_parser = files_subparsers.add_parser("delete")
    files_delete_parser.add_argument("file_id")
    _add_api_url(files_delete_parser)

    schemas_parser = subparsers.add_parser("schemas", help="Validate schema drafts")
    schemas_subparsers = schemas_parser.add_subparsers(dest="schemas_command", required=True)
    schemas_validate_parser = schemas_subparsers.add_parser("validate")
    schemas_validate_parser.add_argument("schema_path")
    _add_api_url(schemas_validate_parser)

    extractors_parser = subparsers.add_parser("extractors", help="Manage extractors")
    extractors_subparsers = extractors_parser.add_subparsers(
        dest="extractors_command", required=True
    )
    extractors_list_parser = extractors_subparsers.add_parser("list")
    _add_api_url(extractors_list_parser)
    extractors_get_parser = extractors_subparsers.add_parser("get")
    extractors_get_parser.add_argument("extractor_id")
    _add_api_url(extractors_get_parser)
    extractors_create_parser = extractors_subparsers.add_parser("create")
    extractors_create_parser.add_argument("--name", required=True)
    extractors_create_parser.add_argument("--instructions", required=True)
    extractors_create_parser.add_argument("--schema", required=True)
    extractors_create_parser.add_argument("--examples")
    extractors_create_parser.add_argument("--enable-thinking", action="store_true")
    _add_api_url(extractors_create_parser)
    extractors_update_parser = extractors_subparsers.add_parser("update")
    extractors_update_parser.add_argument("extractor_id")
    extractors_update_parser.add_argument("--name")
    extractors_update_parser.add_argument("--instructions")
    extractors_update_parser.add_argument("--schema")
    extractors_update_parser.add_argument("--examples")
    extractors_update_parser.add_argument(
        "--enable-thinking",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    _add_api_url(extractors_update_parser)
    extractors_delete_parser = extractors_subparsers.add_parser("delete")
    extractors_delete_parser.add_argument("extractor_id")
    _add_api_url(extractors_delete_parser)

    jobs_parser = subparsers.add_parser("jobs", help="Manage extraction jobs")
    jobs_subparsers = jobs_parser.add_subparsers(dest="jobs_command", required=True)
    jobs_create_parser = jobs_subparsers.add_parser("create")
    jobs_create_parser.add_argument("extractor_id", nargs="?")
    jobs_create_parser.add_argument("--extractor", dest="extractor_id_option")
    jobs_input = jobs_create_parser.add_mutually_exclusive_group(required=True)
    jobs_input.add_argument("--file-id", "--file", dest="file_id")
    jobs_input.add_argument("--text")
    jobs_input.add_argument("--text-file")
    _add_api_url(jobs_create_parser)
    jobs_list_parser = jobs_subparsers.add_parser("list")
    jobs_list_parser.add_argument("--extractor-id", "--extractor", dest="extractor_id")
    _add_api_url(jobs_list_parser)
    jobs_get_parser = jobs_subparsers.add_parser("get")
    jobs_get_parser.add_argument("job_id")
    _add_api_url(jobs_get_parser)
    jobs_delete_parser = jobs_subparsers.add_parser("delete")
    jobs_delete_parser.add_argument("job_id")
    _add_api_url(jobs_delete_parser)

    return parser


def start(args: argparse.Namespace) -> None:
    start_docker(args)


def _progress(message: str) -> None:
    print(f"==> {message}", flush=True)


_TELEMETRY_NOTICE_MARKER = ".telemetry-notice-shown"


def _print_telemetry_notice(data_dir: Path) -> None:
    """Tell users about anonymous usage analytics and how to opt out.

    The full notice is shown once per install (tracked by a marker file in the data
    directory); subsequent starts print only a one-line reminder. Honors the same
    opt-out signals as the telemetry itself.
    """
    from parsehawk import telemetry

    if not telemetry.telemetry_enabled():
        _progress("Usage analytics are disabled (opt-out respected)")
        return

    marker = data_dir / _TELEMETRY_NOTICE_MARKER
    if marker.exists():
        _progress(
            "Anonymous usage analytics enabled; opt out with "
            "PARSEHAWK_TELEMETRY_DISABLED=1 (or DO_NOT_TRACK=1)"
        )
        return

    print(
        "\n"
        "ParseHawk collects anonymous usage analytics (counts of installs and extraction\n"
        "Runs, plus the approximate region they come from, derived from your IP) to help\n"
        "improve the product. No file contents, names, or extracted data are ever sent.\n"
        "Opt out any time with PARSEHAWK_TELEMETRY_DISABLED=1 (or DO_NOT_TRACK=1).\n",
        flush=True,
    )
    # First start on this install: record the install once the user has been told.
    telemetry.track_install(data_dir=data_dir)
    try:
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass


def dev(args: argparse.Namespace) -> None:
    if args.runtime == UNSUPPORTED_RUNTIME:
        raise SystemExit(
            "No bundled model runtime is available for this platform. ParseHawk's local "
            "runtime requires macOS Apple Silicon (vLLM Metal) or Linux x86_64 with an NVIDIA "
            "GPU (vLLM). Pass --runtime none to start the API without a model runtime."
        )
    settings = Settings.from_env()
    config = load_cli_config(apply_env=True)
    data_dir = Path(args.data_dir).expanduser() if args.data_dir else settings.data_dir
    model = args.model or settings.vllm_model
    runtime_settings = _resolve_vllm_settings(settings, model=model)
    log_level = args.log_level or config["log.level"]
    state_path = _state_path(data_dir)
    _progress("Starting ParseHawk in local dev mode")
    _progress(f"Using data directory: {data_dir}")
    if state_path.exists():
        current = _load_state(state_path)
        live_processes = [process for process in current.processes if _pid_running(process.pid)]
        if len(live_processes) == len(current.processes):
            print("ParseHawk is already running")
            _print_status(current)
            return
        _progress("Stopping stale ParseHawk processes")
        _stop_processes(live_processes)
        state_path.unlink()

    web_dir = _repo_root() / "apps" / "web"
    _progress("Checking ports")
    _ensure_start_ports_available(args, web_dir=web_dir)

    _progress("Preparing data directory and seed data")
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "parsehawk.db"
    _print_telemetry_notice(data_dir)
    from parsehawk.server.bootstrap.seeds import seed_prebuilt_data

    seed_prebuilt_data(
        settings.model_copy(
            update={
                "data_dir": data_dir,
                "database_path": database_path,
                "inference_engine": "none",
            }
        )
    )

    runtime_url: str | None = None
    runtime_process: ManagedProcess | None = None
    processes: list[ManagedProcess] = []
    base_env = os.environ.copy()
    base_env["PARSEHAWK_DATA_DIR"] = str(data_dir)
    base_env["PARSEHAWK_DATABASE_PATH"] = str(database_path)
    base_env["PARSEHAWK_LOG_COLORS"] = "0"
    base_env["PARSEHAWK_LOG_LEVEL"] = log_level.upper()

    if args.runtime == "vllm":
        runtime_url = f"http://{args.runtime_host}:{args.runtime_port}/v1"
        runtime_env = base_env.copy()
        runtime_env.update(vllm_launch_env())
        _progress(f"Preparing model runtime: {model}")
        _progress(
            "Model Runtime limits: "
            f"max_model_len={runtime_settings.vllm_max_model_len}, "
            f"gpu_memory_utilization={runtime_settings.vllm_gpu_memory_utilization}"
        )
        runtime_cmd = _vllm_runtime_command(
            settings=runtime_settings,
            model=model,
            host=args.runtime_host,
            port=args.runtime_port,
        )
        if _is_macos_apple_silicon():
            runtime_env.update(
                vllm_launch_env(metal_memory_fraction=runtime_settings.vllm_gpu_memory_utilization)
            )
            runtime_cmd[0] = str(
                ensure_vllm_metal_venv(
                    settings.vllm_metal_home,
                    install_url=settings.vllm_metal_install_url,
                )
            )
        else:
            if not _has_nvidia_gpu():
                raise SystemExit(
                    "--runtime vllm needs an NVIDIA CUDA GPU, but none was detected "
                    "(nvidia-smi is missing or reported no devices). Run ParseHawk on a "
                    "Linux x86_64 host with an NVIDIA GPU, or use --runtime none to start "
                    "without a model runtime."
                )
            runtime_cmd[0] = str(
                ensure_vllm_venv(
                    settings.vllm_venv_dir,
                    pip_spec=settings.vllm_pip_spec,
                    python_version=settings.vllm_python_version,
                )
            )
        _progress(f"Starting model runtime: {runtime_url}")
        runtime_process = _spawn(
            name="runtime",
            cmd=runtime_cmd,
            env=runtime_env,
            logs_dir=logs_dir,
        )
        processes.append(runtime_process)
        base_env["PARSEHAWK_INFERENCE_ENGINE"] = "vllm"
        base_env["PARSEHAWK_VLLM_BASE_URL"] = runtime_url
        base_env["PARSEHAWK_VLLM_MODEL"] = model
    elif args.runtime == "none":
        _progress("Starting without a model runtime")
        base_env["PARSEHAWK_INFERENCE_ENGINE"] = "none"

    api_url = f"http://{args.host}:{args.port}"
    web_url: str | None = None
    api_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "parsehawk.server.api.fastapi.app:create_app",
        "--factory",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--no-use-colors",
    ]
    if args.reload:
        api_cmd.append("--reload")
    _progress(f"Starting ParseHawk API: {api_url}")
    processes.append(_spawn("api", api_cmd, base_env, logs_dir))
    _progress("Starting worker")
    processes.append(
        _spawn(
            "worker",
            [sys.executable, "-m", "parsehawk.server.worker.main"],
            base_env,
            logs_dir,
        )
    )
    if not args.no_web and (web_dir / "package.json").exists():
        web_url = f"http://{args.web_host}:{args.web_port}"
        _progress(f"Starting ParseHawk Web UI: {web_url}")
        processes.append(
            _spawn(
                "web",
                [
                    sys.executable,
                    "-m",
                    "parsehawk.cli.log_proxy",
                    "--logger-name",
                    "parsehawk.web",
                    "--source",
                    "vite",
                    "--",
                    "pnpm",
                    "--dir",
                    str(web_dir),
                    "exec",
                    "vite",
                    "--host",
                    args.web_host,
                    "--port",
                    str(args.web_port),
                ],
                base_env,
                logs_dir,
            )
        )

    state = ParseHawkState(
        data_dir=str(data_dir),
        api_url=api_url,
        runtime_url=runtime_url,
        web_url=web_url,
        processes=processes,
    )
    _write_state(state_path, state)
    try:
        if runtime_url and runtime_process is not None:
            _progress("Waiting for model runtime")
            _wait_for_runtime(
                _runtime_health_url(runtime_url), runtime_process, timeout_seconds=1800
            )
        _progress("Waiting for API")
        _wait_for_api(api_url)
        if web_url:
            _progress("Waiting for ParseHawk Web UI")
            _wait_for_url(web_url, name="ParseHawk Web UI")
        _ensure_managed_processes_alive(processes)
    except BaseException:
        _stop_processes(processes)
        state_path.unlink(missing_ok=True)
        raise
    print(f"ParseHawk started: {api_url}")
    if web_url:
        print(f"ParseHawk Web UI: {web_url}")
    if runtime_url:
        print(f"Model Runtime: {runtime_url}")
    print(f"Logs: {logs_dir}")


def start_docker(args: argparse.Namespace) -> None:
    if args.runtime == UNSUPPORTED_RUNTIME:
        raise SystemExit(
            "No bundled model runtime is available for this platform. ParseHawk's Docker "
            "start mode currently supports macOS Apple Silicon and Linux x86_64 with "
            "an NVIDIA GPU. Pass --runtime none to start without a model runtime."
        )

    settings = Settings.from_env()
    config = load_cli_config(apply_env=True)
    data_dir = Path(args.data_dir).expanduser() if args.data_dir else settings.data_dir
    data_dir = data_dir.resolve()
    model = args.model or settings.vllm_model
    runtime_settings = _resolve_vllm_settings(settings, model=model)
    log_level = args.log_level or config["log.level"]
    state_path = _state_path(data_dir)
    _progress("Starting ParseHawk in Docker mode")
    _progress(f"Using data directory: {data_dir}")

    if state_path.exists():
        current = _load_state(state_path)
        if current.mode == "docker" and _compose_is_running(current):
            print("ParseHawk is already running")
            _print_status(current)
            return
        _progress("Stopping stale ParseHawk state")
        _stop_state(current)
        state_path.unlink(missing_ok=True)

    web_dir = _repo_root() / "apps" / "web"
    _progress("Checking ports")
    _ensure_start_ports_available(args, web_dir=web_dir)
    _progress("Checking Docker")
    _ensure_docker_available()
    _progress("Checking platform dependencies")
    _ensure_platform_dependencies(args.runtime)

    _progress("Preparing data directory and seed data")
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "parsehawk.db"
    _print_telemetry_notice(data_dir)

    from parsehawk.server.bootstrap.seeds import seed_prebuilt_data

    seed_prebuilt_data(
        settings.model_copy(
            update={
                "data_dir": data_dir,
                "database_path": database_path,
                "inference_engine": "none",
            }
        )
    )

    runtime_url: str | None = None
    container_runtime_url: str | None = None
    processes: list[ManagedProcess] = []
    runtime_process: ManagedProcess | None = None
    if args.runtime == "vllm":
        runtime_url = f"http://{args.runtime_host}:{args.runtime_port}/v1"
        _progress(
            "Model Runtime limits: "
            f"max_model_len={runtime_settings.vllm_max_model_len}, "
            f"gpu_memory_utilization={runtime_settings.vllm_gpu_memory_utilization}"
        )
        if _is_macos_apple_silicon():
            _progress(f"Preparing vLLM Metal runtime: {model}")
            runtime_process = _spawn(
                name="runtime",
                cmd=_vllm_runtime_command(
                    settings=runtime_settings,
                    model=model,
                    host=args.runtime_host,
                    port=args.runtime_port,
                    python=str(
                        ensure_vllm_metal_venv(
                            settings.vllm_metal_home,
                            install_url=settings.vllm_metal_install_url,
                        )
                    ),
                ),
                env={
                    **os.environ.copy(),
                    **vllm_launch_env(
                        metal_memory_fraction=runtime_settings.vllm_gpu_memory_utilization
                    ),
                },
                logs_dir=logs_dir,
            )
            processes.append(runtime_process)
            container_runtime_url = f"http://host.docker.internal:{args.runtime_port}/v1"
        elif _is_linux_x86_64():
            _progress(f"Using Linux vLLM runtime service: {model}")
            container_runtime_url = "http://runtime:8080/v1"
        else:
            raise SystemExit("The bundled vLLM runtime is not available on this platform.")
    elif args.runtime == "none":
        _progress("Starting without a model runtime")
        container_runtime_url = None

    compose_project = _compose_project_name(data_dir)
    compose_files = _compose_files(runtime=args.runtime)
    compose_env = _compose_env(
        args=args,
        settings=runtime_settings,
        data_dir=data_dir,
        database_path=database_path,
        log_level=log_level,
        model=model,
        runtime_url=container_runtime_url,
    )
    services = ["api", "worker"]
    web_enabled = not args.no_web and (web_dir / "package.json").exists()
    if web_enabled:
        services.append("web")
    if args.runtime == "vllm" and _is_linux_x86_64():
        services.insert(0, "runtime")

    state = ParseHawkState(
        data_dir=str(data_dir),
        api_url=f"http://{args.host}:{args.port}",
        runtime_url=runtime_url,
        web_url=f"http://{args.web_host}:{args.web_port}" if web_enabled else None,
        processes=processes,
        mode="docker",
        compose_project=compose_project,
        compose_files=[str(path) for path in compose_files],
    )
    _write_state(state_path, state)
    try:
        if runtime_url and runtime_process is not None:
            _progress(f"Waiting for Model Runtime: {runtime_url}")
            _progress(
                "First vLLM startup can take several minutes while it loads model weights, "
                "profiles GPU memory, and warms kernels."
            )
            _wait_for_runtime(
                _runtime_health_url(runtime_url), runtime_process, timeout_seconds=1800
            )
        _progress(f"Building and starting Docker services: {', '.join(services)}")
        _compose_up(
            compose_files=compose_files,
            project_name=compose_project,
            env=compose_env,
            services=services,
        )
        if runtime_url and runtime_process is None:
            _progress(f"Waiting for Model Runtime: {runtime_url}")
            _progress(
                "First vLLM startup can take several minutes while it loads model weights, "
                "profiles GPU memory, and warms kernels."
            )
            _wait_for_url(
                _runtime_health_url(runtime_url), name="Model Runtime", timeout_seconds=1800
            )
        _progress(f"Waiting for ParseHawk API: {state.api_url}")
        _wait_for_api(state.api_url)
        if state.web_url:
            _progress(f"Waiting for ParseHawk Web UI: {state.web_url}")
            _wait_for_url(state.web_url, name="ParseHawk Web UI")
        _ensure_managed_processes_alive(processes)
    except BaseException:
        _compose_down(compose_files=compose_files, project_name=compose_project, env=compose_env)
        _stop_processes(processes)
        state_path.unlink(missing_ok=True)
        raise

    print(f"ParseHawk started: {state.api_url}")
    if state.web_url:
        print(f"ParseHawk Web UI: {state.web_url}")
    if runtime_url:
        print(f"Model Runtime: {runtime_url}")
    print(f"Logs: {logs_dir}")


def restart(args: argparse.Namespace) -> None:
    data_dir = _resolve_data_dir(args.data_dir)
    if _state_path(data_dir).exists():
        stop(data_dir)
    start(args)


def stop(data_dir: Path) -> None:
    state_path = _state_path(data_dir)
    if not state_path.exists():
        print("ParseHawk is not running")
        return
    state = _load_state(state_path)
    _stop_state(state)
    state_path.unlink(missing_ok=True)
    print("ParseHawk stopped")


def status(data_dir: Path) -> None:
    state_path = _state_path(data_dir)
    if not state_path.exists():
        print("ParseHawk is not running")
        return
    state = _load_state(state_path)
    _print_status(state)


def _print_status(state: ParseHawkState) -> None:
    if state.mode == "docker":
        print("Mode: docker")
    print(f"ParseHawk API: {state.api_url}")
    if state.runtime_url:
        print(f"Model Runtime: {state.runtime_url}")
    if state.web_url:
        print(f"ParseHawk Web UI: {state.web_url}")
    if state.mode == "docker" and state.compose_project and state.compose_files:
        running = "running" if _compose_is_running(state) else "stopped"
        print(f"Docker Compose: {running} project={state.compose_project}")
        for service in ("api", "worker", "web"):
            status_text = "running" if _compose_service_running(state, service) else "stopped"
            print(f"{_service_display_name(service)}: {status_text}")
    for process in state.processes:
        status_text = "running" if _pid_running(process.pid) else "stopped"
        print(
            f"{_service_display_name(process.name)}: "
            f"{status_text} pid={process.pid} log={process.log_path}"
        )


def files(args: argparse.Namespace) -> None:
    if args.files_command == "list":
        print_json(api_request(args.api_url, "GET", "/v1/files"))
    elif args.files_command == "get":
        print_json(api_request(args.api_url, "GET", f"/v1/files/{args.file_id}"))
    elif args.files_command in {"upload", "create"}:
        file_path = args.file_path or args.path
        if not file_path:
            raise SystemExit("Provide a file path or --file @path/to/document.pdf")
        print_json(upload_file(args.api_url, file_path.removeprefix("@")))
    elif args.files_command == "delete":
        api_request(args.api_url, "DELETE", f"/v1/files/{args.file_id}")
        print_deleted("file", args.file_id)


def schemas(args: argparse.Namespace) -> None:
    schema = read_json_file(args.schema_path)
    payload = {"schema": schema}
    print_json(api_request(args.api_url, "POST", "/v1/schemas/validate", payload=payload))


def extractors(args: argparse.Namespace) -> None:
    if args.extractors_command == "list":
        print_json(api_request(args.api_url, "GET", "/v1/extractors"))
    elif args.extractors_command == "get":
        print_json(api_request(args.api_url, "GET", f"/v1/extractors/{args.extractor_id}"))
    elif args.extractors_command == "create":
        payload = {
            "name": args.name,
            "instructions": read_text_argument(args.instructions),
            "enable_thinking": args.enable_thinking,
            "schema": read_json_file(args.schema),
            "examples": read_json_file(args.examples) if args.examples else [],
        }
        print_json(api_request(args.api_url, "POST", "/v1/extractors", payload=payload))
    elif args.extractors_command == "update":
        payload: dict[str, Any] = {}
        if args.name is not None:
            payload["name"] = args.name
        if args.instructions is not None:
            payload["instructions"] = read_text_argument(args.instructions)
        if args.enable_thinking is not None:
            payload["enable_thinking"] = args.enable_thinking
        if args.schema is not None:
            payload["schema"] = read_json_file(args.schema)
        if args.examples is not None:
            payload["examples"] = read_json_file(args.examples)
        if not payload:
            raise SystemExit("No extractor updates provided")
        print_json(
            api_request(
                args.api_url,
                "PATCH",
                f"/v1/extractors/{args.extractor_id}",
                payload=payload,
            )
        )
    elif args.extractors_command == "delete":
        api_request(args.api_url, "DELETE", f"/v1/extractors/{args.extractor_id}")
        print_deleted("extractor", args.extractor_id)


def jobs(args: argparse.Namespace) -> None:
    if args.jobs_command == "create":
        extractor_id = args.extractor_id or args.extractor_id_option
        if not extractor_id:
            raise SystemExit("Provide an extractor id or --extractor extractor_123")
        payload: dict[str, str] = {"extractor_id": extractor_id}
        if args.file_id:
            payload["file_id"] = args.file_id
        elif args.text:
            payload["text"] = args.text
        else:
            payload["text"] = Path(args.text_file).expanduser().read_text(encoding="utf-8")
        print_json(
            api_request(
                args.api_url,
                "POST",
                "/v1/jobs",
                payload=payload,
            )
        )
    elif args.jobs_command == "list":
        query = _query_string({"extractor_id": args.extractor_id})
        print_json(api_request(args.api_url, "GET", f"/v1/jobs{query}"))
    elif args.jobs_command == "get":
        print_json(api_request(args.api_url, "GET", f"/v1/jobs/{args.job_id}"))
    elif args.jobs_command == "delete":
        api_request(args.api_url, "DELETE", f"/v1/jobs/{args.job_id}")
        print_deleted("job", args.job_id)


def extract(args: argparse.Namespace) -> None:
    extractor_id = args.extractor or create_ad_hoc_extractor(args)
    job_input = extraction_job_input(args)
    job = api_request(
        args.api_url,
        "POST",
        "/v1/jobs",
        payload={"extractor_id": extractor_id, **job_input},
    )
    if args.wait:
        job = wait_for_job(
            args.api_url,
            str(job["id"]),
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )

    payload = extraction_result_payload(job)
    if args.output:
        write_json_file(args.output, payload)
        print(f"Wrote extraction output: {args.output}")
    else:
        print_json(payload)


def config_command(args: argparse.Namespace) -> None:
    if args.config_command == "list":
        config = load_cli_config(apply_env=True)
        if args.json:
            print_json(config)
        else:
            for key in sorted(config):
                print(f"{key}={config[key]}")
    elif args.config_command == "set":
        if args.key not in DEFAULT_CLI_CONFIG:
            valid = ", ".join(sorted(DEFAULT_CLI_CONFIG))
            raise SystemExit(f"Unknown config key: {args.key}. Valid keys: {valid}")
        config = load_cli_config(apply_env=False)
        config[args.key] = args.value
        write_cli_config(config)
        print(f"Set {args.key}={args.value}")


def doctor(args: argparse.Namespace) -> None:
    config = load_cli_config(apply_env=True)
    api_url = args.api_url or config["server.url"]
    web_url = args.web_url or config["web.url"]
    runtime_url = args.runtime_url or config["runtime.url"]
    data_dir = Path(args.data_dir or config["data.dir"]).expanduser()
    checks = doctor_checks(
        api_url=api_url,
        web_url=web_url,
        runtime_url=runtime_url,
        model=DEFAULT_CLI_CONFIG["runtime.model"],
        data_dir=data_dir,
    )
    print_check_results(checks, as_json=args.json)
    if any(check.status == "fail" for check in checks):
        raise SystemExit(1)


def runtime_command(args: argparse.Namespace) -> None:
    config = load_cli_config(apply_env=True)
    runtime_url = args.runtime_url or config["runtime.url"]
    model = args.model or config["runtime.model"]
    if args.runtime_command == "info":
        payload = {"runtime_url": runtime_url, "model": model}
        if args.json:
            print_json(payload)
        else:
            print(f"Runtime URL: {runtime_url}")
            print(f"Model: {model}")
    elif args.runtime_command in {"test", "doctor"}:
        checks = runtime_checks(runtime_url=runtime_url, model=model)
        print_check_results(checks, as_json=args.json)
        if any(check.status == "fail" for check in checks):
            raise SystemExit(1)


def doctor_checks(
    *, api_url: str, web_url: str, runtime_url: str, model: str, data_dir: Path
) -> list[CheckResult]:
    return [
        check_python(),
        check_data_dir(data_dir),
        check_http_json(
            name="ParseHawk API",
            url=f"{api_url.rstrip('/')}/health",
            success_detail=f"reachable at {api_url}",
        ),
        check_http(
            name="ParseHawk Web UI",
            url=web_url,
            success_detail=f"reachable at {web_url}",
        ),
        check_worker(data_dir),
        *runtime_checks(runtime_url=runtime_url, model=model),
    ]


def runtime_checks(*, runtime_url: str, model: str) -> list[CheckResult]:
    health_url = _runtime_health_url(runtime_url)
    checks = [
        check_http_json(
            name="Model Runtime",
            url=health_url,
            success_detail=f"reachable at {runtime_url}",
        )
    ]
    models_url = f"{runtime_url.rstrip('/')}/models"
    ok, payload, error = http_get_json(models_url, timeout=3)
    if not ok:
        checks.append(CheckResult("Model Runtime Models", "fail", error))
        return checks
    models = payload.get("data", []) if isinstance(payload, dict) else []
    model_ids = [item.get("id") for item in models if isinstance(item, dict)]
    if model in model_ids:
        checks.append(CheckResult("Model Runtime Model", "ok", f"model is available: {model}"))
    else:
        available = ", ".join(str(model_id) for model_id in model_ids) or "<none>"
        checks.append(
            CheckResult(
                "Model Runtime Model",
                "fail",
                f"model {model!r} was not listed; available models: {available}",
            )
        )
    return checks


def check_python() -> CheckResult:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info >= (3, 11):
        return CheckResult("Python", "ok", f"Python {version}")
    return CheckResult("Python", "fail", f"Python {version}; ParseHawk requires Python 3.11+")


def check_data_dir(data_dir: Path) -> CheckResult:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".parsehawk-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return CheckResult("Data directory", "fail", str(exc))
    return CheckResult("Data directory", "ok", f"writable at {data_dir}")


def _ensure_docker_available() -> None:
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit(
            "Docker is required for `parsehawk start` but was not found on PATH. "
            "Install Docker Desktop on macOS or Docker Engine with Compose on Linux."
        )
    try:
        subprocess.run(
            [docker, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=True,
        )
        subprocess.run(
            [docker, "compose", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(
            "Docker is installed but not ready. Start Docker Desktop or the Docker daemon, "
            "then run `uv run parsehawk start` again."
        ) from exc


def _ensure_platform_dependencies(runtime: str) -> None:
    if runtime == "none":
        return
    if _is_macos_apple_silicon():
        _ensure_xcode_command_line_tools()
        return
    if _is_linux_x86_64():
        if not _has_nvidia_gpu():
            raise SystemExit(
                "Linux model runtime requires an NVIDIA GPU and driver, but `nvidia-smi` "
                "did not report a usable GPU."
            )
        if not _docker_supports_nvidia_runtime():
            raise SystemExit(
                "Docker does not appear to expose the NVIDIA runtime. Install the NVIDIA "
                "Container Toolkit and verify `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`."
            )
        return
    raise SystemExit("ParseHawk's bundled model runtime supports macOS arm64 or Linux x86_64.")


def _ensure_xcode_command_line_tools() -> None:
    try:
        subprocess.run(
            ["xcode-select", "-p"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if sys.stdin.isatty():
            answer = input(
                "Xcode Command Line Tools are required for vLLM Metal. Install them now? [y/N] "
            )
            if answer.strip().lower() in {"y", "yes"}:
                subprocess.run(["xcode-select", "--install"], check=False)
                raise SystemExit(
                    "Finish the Xcode Command Line Tools installer, then run "
                    "`uv run parsehawk start` again."
                ) from exc
        raise SystemExit(
            "Xcode Command Line Tools are required for vLLM Metal. Install them with "
            "`xcode-select --install`, then run `uv run parsehawk start` again."
        ) from exc


def _docker_supports_nvidia_runtime() -> bool:
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        result = subprocess.run(
            [docker, "info", "--format", "{{json .Runtimes}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "nvidia" in result.stdout


def _compose_project_name(data_dir: Path) -> str:
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, str(data_dir)).hex[:8]
    return f"parsehawk_{suffix}"


def _compose_files(*, runtime: str) -> list[Path]:
    docker_dir = _repo_root() / "docker"
    files = [docker_dir / "docker-compose.yml"]
    if runtime == "vllm" and _is_linux_x86_64():
        files.append(docker_dir / "docker-compose.linux.yml")
    return files


def _compose_env(
    *,
    args: argparse.Namespace,
    settings: Settings,
    data_dir: Path,
    database_path: Path,
    log_level: str,
    model: str,
    runtime_url: str | None,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PARSEHAWK_HOST_DATA_DIR": str(data_dir),
            "PARSEHAWK_DATA_DIR": "/data",
            "PARSEHAWK_DATABASE_PATH": "/data/parsehawk.db",
            "PARSEHAWK_LOG_LEVEL": log_level.upper(),
            "PARSEHAWK_API_HOST": args.host,
            "PARSEHAWK_API_PORT": str(args.port),
            "PARSEHAWK_WEB_HOST": args.web_host,
            "PARSEHAWK_WEB_PORT": str(args.web_port),
            "PARSEHAWK_RUNTIME_PORT": str(args.runtime_port),
            "PARSEHAWK_VLLM_MODEL": model,
            "PARSEHAWK_VLLM_MAX_MODEL_LEN": str(settings.vllm_max_model_len),
            "PARSEHAWK_VLLM_GPU_MEMORY_UTILIZATION": str(settings.vllm_gpu_memory_utilization),
            "PARSEHAWK_PDF_MAX_PAGES": str(settings.pdf_max_pages),
            "PARSEHAWK_HF_HOME": str(Path.home() / ".cache" / "huggingface"),
            "PARSEHAWK_INFERENCE_ENGINE": "vllm" if runtime_url else "none",
            "PARSEHAWK_VLLM_BASE_URL": runtime_url or "http://127.0.0.1:8080/v1",
        }
    )
    env["PARSEHAWK_DATABASE_PATH"] = str(database_path).replace(str(data_dir), "/data", 1)
    return env


def _compose_command(compose_files: list[Path], project_name: str, *args: str) -> list[str]:
    command = ["docker", "compose", "--project-name", project_name]
    for compose_file in compose_files:
        command.extend(["--file", str(compose_file)])
    command.extend(args)
    return command


def _compose_up(
    *,
    compose_files: list[Path],
    project_name: str,
    env: dict[str, str],
    services: list[str],
) -> None:
    try:
        subprocess.run(
            _compose_command(compose_files, project_name, "up", "--detach", "--build", *services),
            cwd=_repo_root(),
            env=env,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "Docker Compose failed to build or start ParseHawk. Check the Docker output "
            "above for the failing image or service. If it failed while loading metadata "
            "or pulling base images such as node, nginx, python, or vLLM, Docker could "
            "not reach Docker Hub or the registry timed out. Wait for Docker Desktop/network "
            "to recover and retry `uv run parsehawk start`."
        ) from exc


def _compose_down(*, compose_files: list[Path], project_name: str, env: dict[str, str]) -> None:
    subprocess.run(
        _compose_command(compose_files, project_name, "down", "--remove-orphans"),
        cwd=_repo_root(),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _compose_is_running(state: ParseHawkState) -> bool:
    return bool(_compose_running_services(state))


def _compose_service_running(state: ParseHawkState, service: str) -> bool:
    return service in _compose_running_services(state)


def _compose_running_services(state: ParseHawkState) -> set[str]:
    if state.compose_project is None or state.compose_files is None:
        return set()
    try:
        result = subprocess.run(
            _compose_command(
                [Path(path) for path in state.compose_files],
                state.compose_project,
                "ps",
                "--status",
                "running",
                "--format",
                "json",
            ),
            cwd=_repo_root(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return _compose_services_from_ps_json(result.stdout)


def _compose_services_from_ps_json(output: str) -> set[str]:
    output = output.strip()
    if not output:
        return set()
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        services: set[str] = set()
        for line in output.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            service = _compose_service_name(item)
            if service:
                services.add(service)
        return services
    items = payload if isinstance(payload, list) else [payload]
    return {
        service
        for item in items
        if isinstance(item, dict)
        for service in [_compose_service_name(item)]
        if service
    }


def _compose_service_name(item: dict[str, Any]) -> str | None:
    service = item.get("Service")
    if isinstance(service, str) and service:
        return service
    name = item.get("Name")
    if not isinstance(name, str) or not name:
        return None
    for service_name in ("api", "worker", "web", "runtime"):
        if (
            f"-{service_name}-" in name
            or f"_{service_name}_" in name
            or name.endswith(f"-{service_name}")
            or name.endswith(f"_{service_name}")
        ):
            return service_name
    return None


def _service_display_name(name: str) -> str:
    return {
        "api": "ParseHawk API",
        "worker": "ParseHawk Worker",
        "web": "ParseHawk Web UI",
        "runtime": "Model Runtime",
    }.get(name, name)


def _stop_state(state: ParseHawkState) -> None:
    if state.mode == "docker" and state.compose_project and state.compose_files:
        data_dir = Path(state.data_dir)
        _compose_down(
            compose_files=[Path(path) for path in state.compose_files],
            project_name=state.compose_project,
            env={
                **os.environ.copy(),
                "PARSEHAWK_HOST_DATA_DIR": str(data_dir),
                "PARSEHAWK_DATA_DIR": "/data",
            },
        )
    _stop_processes(state.processes)


def check_http_json(*, name: str, url: str, success_detail: str) -> CheckResult:
    ok, _, error = http_get_json(url, timeout=3)
    if ok:
        return CheckResult(name, "ok", success_detail)
    return CheckResult(name, "fail", error)


def check_http(*, name: str, url: str, success_detail: str) -> CheckResult:
    ok, error = http_get(url, timeout=3)
    if ok:
        return CheckResult(name, "ok", success_detail)
    return CheckResult(name, "fail", error)


def check_worker(data_dir: Path) -> CheckResult:
    state_path = _state_path(data_dir)
    if not state_path.exists():
        return CheckResult("ParseHawk Worker", "fail", f"state file not found at {state_path}")
    try:
        state = _load_state(state_path)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return CheckResult("ParseHawk Worker", "fail", f"invalid state at {state_path}: {exc}")
    if state.mode == "docker":
        if _compose_service_running(state, "worker"):
            return CheckResult("ParseHawk Worker", "ok", "Docker service is running")
        return CheckResult("ParseHawk Worker", "fail", "Docker service is not running")
    worker = next((process for process in state.processes if process.name == "worker"), None)
    if worker is None:
        return CheckResult("ParseHawk Worker", "fail", "worker process is not tracked")
    if _pid_running(worker.pid):
        return CheckResult("ParseHawk Worker", "ok", f"running pid={worker.pid}")
    return CheckResult("ParseHawk Worker", "fail", f"stopped pid={worker.pid}")


def http_get(url: str, *, timeout: float) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read(1)
            if response.status >= 400:
                return False, f"HTTP {response.status} from {url}"
            return True, ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code} from {url}: {body}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"unreachable at {url}: {exc}"


def http_get_json(url: str, *, timeout: float) -> tuple[bool, Any, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read()
            if response.status >= 400:
                return False, None, f"HTTP {response.status} from {url}"
            if not body:
                return True, {}, ""
            return True, json.loads(body.decode("utf-8")), ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, None, f"HTTP {exc.code} from {url}: {body}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, None, f"unreachable at {url}: {exc}"
    except json.JSONDecodeError as exc:
        return False, None, f"invalid JSON from {url}: {exc}"


def print_check_results(checks: list[CheckResult], *, as_json: bool) -> None:
    if as_json:
        print_json([asdict(check) for check in checks])
        return
    for check in checks:
        print(f"{check.status.upper():4} {check.name}: {check.detail}")


def load_cli_config(*, apply_env: bool) -> dict[str, str]:
    config = dict(DEFAULT_CLI_CONFIG)
    path = cli_config_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid ParseHawk config at {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SystemExit(f"Invalid ParseHawk config at {path}: expected object")
        for key, value in payload.items():
            if key in DEFAULT_CLI_CONFIG and isinstance(value, str):
                config[key] = value
    if apply_env:
        for key, env_name in CONFIG_ENV_OVERRIDES.items():
            env_value = os.getenv(env_name)
            if env_value:
                config[key] = env_value
    return config


def write_cli_config(config: dict[str, str]) -> None:
    path = cli_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    persisted = {key: config[key] for key in sorted(DEFAULT_CLI_CONFIG)}
    path.write_text(json.dumps(persisted, indent=2) + "\n", encoding="utf-8")


def cli_config_path() -> Path:
    configured = os.getenv("PARSEHAWK_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".parsehawk" / "config.json"


def create_ad_hoc_extractor(args: argparse.Namespace) -> str:
    if not args.schema:
        raise SystemExit("Provide --extractor or --schema")
    if args.instructions is None:
        raise SystemExit("Provide --instructions when creating an ad hoc extractor")
    payload = {
        "name": args.name or default_extractor_name(args),
        "instructions": read_text_argument(args.instructions),
        "enable_thinking": args.enable_thinking,
        "schema": read_json_file(args.schema),
        "examples": [],
    }
    extractor = api_request(args.api_url, "POST", "/v1/extractors", payload=payload)
    return str(extractor["id"])


def extraction_job_input(args: argparse.Namespace) -> dict[str, str]:
    provided_inputs = [
        args.source is not None,
        args.file_id is not None,
        args.text is not None,
        args.text_file is not None,
    ]
    if provided_inputs.count(True) != 1:
        raise SystemExit(
            "Provide exactly one input: source path, --file-id, --text, or --text-file"
        )
    if args.file_id is not None:
        return {"file_id": args.file_id}
    if args.text is not None:
        return {"text": args.text}
    if args.text_file is not None:
        return {"text": Path(args.text_file).expanduser().read_text(encoding="utf-8")}
    uploaded = upload_file(args.api_url, str(args.source).removeprefix("@"))
    return {"file_id": str(uploaded["id"])}


def _query_string(params: dict[str, str | None]) -> str:
    filtered = {key: value for key, value in params.items() if value}
    if not filtered:
        return ""
    return "?" + urllib.parse.urlencode(filtered)


def wait_for_job(
    api_url: str,
    job_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        job = api_request(api_url, "GET", f"/v1/jobs/{job_id}")
        status_value = str(job.get("status", ""))
        if status_value in {"completed", "failed", "canceled"}:
            return job
        time.sleep(max(poll_seconds, 0.0))
    raise SystemExit(f"Timed out waiting for job: {job_id}")


def extraction_result_payload(job: dict[str, Any]) -> Any:
    result = job.get("result")
    if isinstance(result, dict) and "data" in result:
        return result["data"]
    return job


def default_extractor_name(args: argparse.Namespace) -> str:
    if args.source:
        return f"{Path(str(args.source)).stem}_extractor"
    return "ad_hoc_extractor"


def read_text_argument(value: str) -> str:
    if value.startswith("@"):
        return Path(value[1:]).expanduser().read_text(encoding="utf-8")
    path = Path(value).expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return value


def api_request(
    api_url: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    request_headers = {"Accept": "application/json", **(headers or {})}
    body = data
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{api_url.rstrip('/')}{path}",
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_body = response.read()
            if response.status == 204 or not response_body:
                return None
            return json.loads(response_body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"API returned HTTP {exc.code}: {body_text}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"API is unreachable at {api_url}: {exc.reason}") from exc


def upload_file(api_url: str, file_path: str) -> Any:
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise SystemExit(f"File does not exist: {path}")

    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    boundary = f"----parsehawk-{uuid.uuid4().hex}"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (f'Content-Disposition: form-data; name="upload"; filename="{path.name}"\r\n').encode(
                "utf-8"
            ),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return api_request(
        api_url,
        "POST",
        "/v1/files",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def read_json_file(path: str) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def write_json_file(path: str, payload: Any) -> None:
    Path(path).expanduser().write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def print_deleted(resource: str, resource_id: str) -> None:
    print(f"Deleted {resource}: {resource_id}")


def _add_start_options(
    parser: argparse.ArgumentParser, *, include_docker_options: bool = True
) -> None:
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir")
    parser.add_argument(
        "--runtime",
        choices=["vllm", "none"],
        default=_default_runtime(),
    )
    parser.add_argument("--runtime-host", default="127.0.0.1")
    parser.add_argument("--runtime-port", type=int, default=8080)
    parser.add_argument("--model")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the log level for all ParseHawk services.",
    )
    parser.add_argument(
        "--runtime-keep-alive-seconds",
        type=int,
        help="Unload the model runtime after this many idle seconds. Use 0 to keep it loaded.",
    )
    if not include_docker_options:
        parser.add_argument("--reload", action="store_true")
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=5173)
    parser.add_argument("--no-web", action="store_true")


def _add_api_url(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--api-url",
        default=os.getenv("PARSEHAWK_API_URL", "http://127.0.0.1:8000"),
    )


def _resolve_data_dir(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    return Settings.from_env().data_dir


def _ensure_start_ports_available(args: argparse.Namespace, *, web_dir: Path) -> None:
    checks = [("API", args.host, args.port)]
    if args.runtime == "vllm":
        checks.append(("Model Runtime", args.runtime_host, args.runtime_port))
    if not args.no_web and (web_dir / "package.json").exists():
        checks.append(("Web UI", args.web_host, args.web_port))

    for name, host, port in checks:
        if _tcp_port_open(host, port):
            raise SystemExit(
                f"{name} port {host}:{port} is already in use, but ParseHawk does not "
                "have a live state file for that process. Run `parsehawk stop` before "
                "deleting the data directory. If the data directory was already deleted, "
                "stop the process using that port and then run `parsehawk start` again."
            )


def _tcp_port_open(host: str, port: int) -> bool:
    connect_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((connect_host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _ensure_managed_processes_alive(processes: list[ManagedProcess]) -> None:
    stopped = [process for process in processes if not _pid_running(process.pid)]
    if stopped:
        names = ", ".join(process.name for process in stopped)
        raise SystemExit(f"ParseHawk failed to start: process exited early: {names}")


def _spawn(
    name: str,
    cmd: list[str],
    env: dict[str, str],
    logs_dir: Path,
) -> ManagedProcess:
    log_path = logs_dir / f"{name}.log"
    log_file = log_path.open("ab")
    process = subprocess.Popen(
        cmd,
        cwd=Path.cwd(),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return ManagedProcess(name=name, pid=process.pid, log_path=str(log_path))


def _wait_for_api(api_url: str) -> None:
    _wait_for_url(f"{api_url}/health", name="ParseHawk API")


def _wait_for_url(url: str, name: str = "URL", timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 500:
                    return
        except (http.client.HTTPException, urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)
    raise SystemExit(f"{name} did not become ready at {url}")


def _wait_for_runtime(health_url: str, process: ManagedProcess, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_running(process.pid):
            raise SystemExit(
                "Model Runtime exited before becoming ready. Last lines from "
                f"{process.log_path}:\n{_log_tail(process.log_path)}"
            )
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if 200 <= response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    raise SystemExit(f"Model Runtime did not become ready at {health_url}")


def _log_tail(log_path: str, *, lines: int = 20) -> str:
    try:
        content = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no log output captured)"
    tail = content.splitlines()[-lines:]
    return "\n".join(tail) if tail else "(log was empty)"


def _runtime_health_url(runtime_url: str) -> str:
    return runtime_url.removesuffix("/v1").rstrip("/") + "/health"


def _state_path(data_dir: Path) -> Path:
    return data_dir / "parsehawk-state.json"


def _write_state(path: Path, state: ParseHawkState) -> None:
    payload = asdict(state)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_state(path: Path) -> ParseHawkState:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ParseHawkState(
        data_dir=payload["data_dir"],
        api_url=payload["api_url"],
        runtime_url=payload.get("runtime_url"),
        web_url=payload.get("web_url"),
        processes=[ManagedProcess(**process) for process in payload["processes"]],
        mode=payload.get("mode", "local"),
        compose_project=payload.get("compose_project"),
        compose_files=payload.get("compose_files"),
    )


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not _pid_running(pid):
            return
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return


def _stop_processes(processes: list[ManagedProcess]) -> None:
    for process in reversed(processes):
        if _pid_running(process.pid):
            _terminate(process.pid)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


if __name__ == "__main__":
    main()
