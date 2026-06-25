from __future__ import annotations

import json
import socket
import subprocess
import sys
import urllib.request


def test_cli_dev_status_stop(tmp_path) -> None:
    port = _free_port()
    start = subprocess.run(
        [
            sys.executable,
            "-m",
            "parsehawk.cli.main",
            "dev",
            "--runtime",
            "none",
            "--data-dir",
            str(tmp_path),
            "--port",
            str(port),
            "--no-web",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        assert "ParseHawk started" in start.stdout

        status = subprocess.run(
            [sys.executable, "-m", "parsehawk.cli.main", "status", "--data-dir", str(tmp_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "ParseHawk API: running" in status.stdout
        assert "ParseHawk Worker: running" in status.stdout

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            assert json.loads(response.read().decode("utf-8")) == {"status": "ok"}
    finally:
        subprocess.run(
            [sys.executable, "-m", "parsehawk.cli.main", "stop", "--data-dir", str(tmp_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
