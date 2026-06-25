from __future__ import annotations

import re
import sys

from parsehawk.cli import log_proxy


def test_log_proxy_prefixes_lines_and_strips_ansi(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "log_proxy",
            "--logger-name",
            "parsehawk.web",
            "--source",
            "vite",
            "--",
            sys.executable,
            "-c",
            "print('\\033[32mready\\033[0m')",
        ],
    )

    try:
        log_proxy.main()
    except SystemExit as exc:
        assert exc.code == 0

    output = capsys.readouterr().out.strip()
    assert re.match(r"\d\d:\d\d:\d\d - parsehawk\.web:INFO: vite:0 - ready", output)
    assert "\033[" not in output
