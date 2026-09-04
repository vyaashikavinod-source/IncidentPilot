import io
import json
import logging
from collections.abc import Iterator
from datetime import datetime

import pytest

from incidentpilot.shared.config import Settings
from incidentpilot.shared.logging import configure_logging


@pytest.fixture(autouse=True)
def restore_logger() -> Iterator[None]:
    logger = logging.getLogger("incidentpilot")
    handlers, level, propagate = logger.handlers[:], logger.level, logger.propagate
    logger.handlers = []
    yield
    for handler in logger.handlers:
        handler.close()
    logger.handlers, logger.level, logger.propagate = handlers, level, propagate


def test_json_and_level_filtering() -> None:
    stream = io.StringIO()
    root_handlers = logging.getLogger().handlers[:]
    configure_logging(Settings(service_name="auth", log_level="INFO"), stream)
    logger = logging.getLogger("incidentpilot.auth")
    logger.debug("hidden")
    logger.info("request_completed", extra={"password": "must-not-appear"})
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["service"] == "auth"
    assert event["level"] == "INFO"
    assert event["message"] == "request_completed"
    assert event["logger"] == "incidentpilot.auth"
    assert datetime.fromisoformat(event["timestamp"]).utcoffset() is not None
    assert "password" not in event
    assert "must-not-appear" not in lines[0]
    assert logging.getLogger().handlers == root_handlers


def test_reconfiguration_does_not_duplicate_logs() -> None:
    old, new = io.StringIO(), io.StringIO()
    configure_logging(Settings(), old)
    logger = configure_logging(Settings(), new)
    logger.info("startup")
    assert old.getvalue() == ""
    assert len(new.getvalue().splitlines()) == 1


def test_exception_excludes_sensitive_text() -> None:
    stream = io.StringIO()
    logger = configure_logging(Settings(), stream)
    try:
        raise ValueError("sensitive detail")
    except ValueError:
        logger.exception("operation_failed")
    event = json.loads(stream.getvalue())
    assert event["exception_type"] == "ValueError"
    assert "sensitive detail" not in stream.getvalue()
