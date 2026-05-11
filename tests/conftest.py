"""Shared pytest fixtures for the ShipsAhoy test suite."""
import logging
import pytest
from loguru import logger


@pytest.fixture(autouse=True)
def propagate_loguru_to_caplog(caplog):
    """Bridge loguru log records into pytest's caplog fixture.

    loguru does not propagate to the stdlib logging hierarchy by default,
    so caplog.records would be empty for all loguru-emitting code.
    This fixture installs a temporary loguru sink that forwards each record
    into caplog's handler so tests can assert on log output normally.
    """
    handler_id = logger.add(
        lambda msg: caplog.handler.emit(
            logging.LogRecord(
                name=msg.record["name"],
                level=msg.record["level"].no,
                pathname=str(msg.record["file"].path),
                lineno=msg.record["line"],
                msg=msg.record["message"],
                args=(),
                exc_info=None,
            )
        )
    )
    yield
    try:
        logger.remove(handler_id)
    except ValueError:
        pass  # configure_logging() may have already called logger.remove()
