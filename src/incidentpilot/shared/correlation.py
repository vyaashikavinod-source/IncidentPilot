"""Dependency-free context for application and worker logs."""

from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="-")
