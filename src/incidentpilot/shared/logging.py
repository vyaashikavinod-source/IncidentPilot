"""JSON application logs with an intentionally small field allowlist.

Messages must be static event names: do not interpolate secrets or request bodies.
Arbitrary extras and exception text are excluded; this is not an audit log.
"""

import json
import logging
from datetime import UTC, datetime
from typing import TextIO

from incidentpilot.shared.config import Settings


class JsonFormatter(logging.Formatter):
    """Format predictable JSON without serializing arbitrary record attributes."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info is not None and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: Settings, stream: TextIO | None = None) -> logging.Logger:
    """Configure only the owned application logger; leave the host root logger alone.

    Call once at process startup, before concurrent application work begins.
    Repeated calls replace owned handlers rather than duplicating output.
    """
    logger = logging.getLogger("incidentpilot")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(settings.service_name))
    logger.addHandler(handler)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    return logger
