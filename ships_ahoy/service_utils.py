"""Shared utilities for ShipsAhoy services.

Provides a single source of truth for the default database path and
the logging configuration used by all four services.
"""

import logging
import sys

from loguru import logger

DEFAULT_DB_PATH = "ships.db"


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
    """Configure loguru as the sole logging sink, intercepting stdlib logging."""
    level = "DEBUG" if verbose else "INFO"
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan> — "
            "<level>{message}</level>"
        ),
    )
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
