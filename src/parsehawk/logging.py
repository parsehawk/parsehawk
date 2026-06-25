from __future__ import annotations

import logging
import os
import sys


class ColoredFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;31m",
    }
    RESET = "\033[0m"

    def __init__(self, datefmt: str | None = None, use_colors: bool = True) -> None:
        super().__init__(datefmt=datefmt)
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        formatted_time = self.formatTime(record, self.datefmt)
        if self.use_colors:
            color = self.COLORS.get(record.levelno, self.RESET)
            return (
                f"{color}{formatted_time} - {record.name}:{record.levelname}{self.RESET}: "
                f"{record.filename}:{record.lineno} - {record.getMessage()}"
            )
        return (
            f"{formatted_time} - {record.name}:{record.levelname}: "
            f"{record.filename}:{record.lineno} - {record.getMessage()}"
        )


def configure_logging(
    logger_name: str = "parsehawk",
    *,
    configure_uvicorn: bool = False,
) -> logging.Logger:
    log_level = _log_level()
    use_colors = _use_colors()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter(datefmt="%H:%M:%S", use_colors=use_colors))

    package_logger = logging.getLogger(logger_name)
    package_logger.handlers = []
    package_logger.addHandler(handler)
    package_logger.setLevel(log_level)
    package_logger.propagate = False

    if configure_uvicorn:
        for uvicorn_logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
            uvicorn_logger = logging.getLogger(uvicorn_logger_name)
            uvicorn_logger.handlers = []
            uvicorn_logger.addHandler(handler)
            uvicorn_logger.setLevel(log_level)
            uvicorn_logger.propagate = False

    return package_logger


def _log_level() -> int:
    configured = os.getenv("PARSEHAWK_LOG_LEVEL", "INFO").upper()
    return logging.getLevelNamesMapping().get(configured, logging.INFO)


def _use_colors() -> bool:
    configured = os.getenv("PARSEHAWK_LOG_COLORS")
    if configured is not None:
        return configured.lower() in {"1", "true", "yes", "on"}
    return sys.stdout.isatty()
