"""Shared utilities for ShipsAhoy services.

Provides a single source of truth for the default database path,
the runtime log file path, and the logging configuration used by all
four services.

Log files
---------
logs/runtime.log  — INFO+, human-readable, read by the web dashboard
logs/info.log     — INFO+, clean prose format, 30-day retention
logs/debug.log    — DEBUG+, full module/function/line context, 24-hour retention
"""

import logging
import sys
from pathlib import Path

from loguru import logger

DEFAULT_DB_PATH = "ships.db"

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

# Runtime log written by all services; read by the web dashboard.
LOG_FILE = _LOG_DIR / "runtime.log"

# Pretty format for info-level logs (no noise, easy to read).
_INFO_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"

# Verbose format for debug-level logs (full source context).
_DEBUG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} | {message}"
)


class _InterceptHandler(logging.Handler):
    """Route stdlib logging records through loguru.

    Flask, pyais, and other dependencies use the stdlib logger. This handler
    forwards their records into loguru so everything appears in one stream.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(verbose: bool) -> None:
    """Configure loguru sinks:

    - stderr: colorised, DEBUG if --verbose else INFO
    - logs/runtime.log: INFO+, for the web dashboard (10 MB rotation, 3 files)
    - logs/info.log: INFO+, pretty, 30-day retention
    - logs/debug.log: DEBUG+, full context, 24-hour retention
    """
    _LOG_DIR.mkdir(exist_ok=True)
    logger.remove()

    # Stderr — respects --verbose
    logger.add(
        sys.stderr,
        level="DEBUG" if verbose else "INFO",
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan> — "
            "<level>{message}</level>"
        ),
    )

    # Dashboard log (unchanged path so web_service keeps working)
    logger.add(
        LOG_FILE,
        level="INFO",
        rotation="10 MB",
        retention=3,
        encoding="utf-8",
        format=_INFO_FORMAT,
    )

    # Pretty info log — long retention for post-mortems
    logger.add(
        _LOG_DIR / "info.log",
        level="INFO",
        rotation="1 day",
        retention="30 days",
        encoding="utf-8",
        format=_INFO_FORMAT,
    )

    # Detailed debug log — short retention, auto-cleaned
    logger.add(
        _LOG_DIR / "debug.log",
        level="DEBUG",
        rotation="100 MB",
        retention="1 day",
        encoding="utf-8",
        format=_DEBUG_FORMAT,
    )

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
