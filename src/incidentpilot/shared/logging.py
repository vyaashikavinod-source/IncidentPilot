"""JSON application logs with an intentionally small field allowlist.

Messages must be static event names: do not interpolate secrets or request bodies.
Arbitrary extras and exception text are excluded; this is not an audit log.
"""

import json
import logging
from datetime import UTC, datetime
from typing import TextIO

from opentelemetry import trace

from incidentpilot.shared.config import Settings
from incidentpilot.shared.correlation import request_id


class JsonFormatter(logging.Formatter):
    """Format predictable JSON without serializing arbitrary record attributes."""

    def __init__(self, service_name: str, environment: str = "local") -> None:
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str | int] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id.get(),
            "environment": self.environment,
        }
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            payload["trace_id"] = format(context.trace_id, "032x")
            payload["span_id"] = format(context.span_id, "016x")
        if record.exc_info is not None and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        http_status = getattr(record, "http_status", None)
        if isinstance(http_status, int):
            payload["http_status"] = http_status
        return json.dumps(payload, ensure_ascii=False)


class CorrelationFilter(logging.Filter):
    """Attach correlation fields for OTLP export without making them Loki labels."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            record.trace_id = format(context.trace_id, "032x")
            record.span_id = format(context.span_id, "016x")
        return True


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
    handler.addFilter(CorrelationFilter())
    handler.setFormatter(JsonFormatter(settings.service_name, settings.environment))
    logger.addHandler(handler)
    if settings.telemetry_enabled:
        from opentelemetry.sdk._logs import LoggingHandler

        otlp_handler = LoggingHandler(level=logging._nameToLevel[settings.log_level])
        otlp_handler.addFilter(CorrelationFilter())
        logger.addHandler(otlp_handler)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    return logger
