"""Shared utilities for ShipsAhoy services.

Provides a single source of truth for the default database path and
the logging configuration used by all four services.
"""

import logging

DEFAULT_DB_PATH = "ships.db"


def configure_logging(verbose: bool) -> None:
    """Configure root logger level based on the --verbose flag."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level)
