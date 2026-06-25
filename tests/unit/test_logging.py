from __future__ import annotations

import logging
import re

from parsehawk.logging import ColoredFormatter


def test_colored_formatter_matches_expected_shape_without_colors() -> None:
    record = logging.LogRecord(
        name="parsehawk.api",
        level=logging.INFO,
        pathname="/tmp/app.py",
        lineno=42,
        msg="started",
        args=(),
        exc_info=None,
    )
    formatter = ColoredFormatter(datefmt="%H:%M:%S", use_colors=False)

    formatted = formatter.format(record)

    assert re.match(r"\d\d:\d\d:\d\d - parsehawk\.api:INFO: app\.py:42 - started", formatted)
    assert "\033[" not in formatted


def test_colored_formatter_uses_ansi_when_enabled() -> None:
    record = logging.LogRecord(
        name="parsehawk.worker",
        level=logging.ERROR,
        pathname="/tmp/worker.py",
        lineno=12,
        msg="failed",
        args=(),
        exc_info=None,
    )
    formatter = ColoredFormatter(datefmt="%H:%M:%S", use_colors=True)

    formatted = formatter.format(record)

    assert "\033[31m" in formatted
    assert "\033[0m" in formatted
    assert "parsehawk.worker:ERROR" in formatted
