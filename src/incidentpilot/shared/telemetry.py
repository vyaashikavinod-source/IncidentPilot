"""OpenTelemetry lifecycle and supported framework instrumentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from incidentpilot.shared.config import Settings


@dataclass
class Telemetry:
    tracer_provider: TracerProvider | None = None
    logger_provider: LoggerProvider | None = None

    def shutdown(self) -> None:
        if self.logger_provider:
            self.logger_provider.shutdown()
        if self.tracer_provider:
            self.tracer_provider.shutdown()


def configure_telemetry(
    settings: Settings, app: FastAPI | None = None, *, instrument_celery: bool = False
) -> Telemetry:
    if not settings.telemetry_enabled:
        return Telemetry()
    resource = Resource.create(
        {"service.name": settings.service_name, "deployment.environment.name": settings.environment}
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{settings.otlp_endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{settings.otlp_endpoint}/v1/logs"))
    )
    from opentelemetry._logs import set_logger_provider

    set_logger_provider(logger_provider)
    metrics.set_meter_provider(MeterProvider(resource=resource))
    HTTPXClientInstrumentor().instrument()
    if instrument_celery:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        cast(Any, CeleryInstrumentor)().instrument()
    if app is not None:
        FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/metrics")
    return Telemetry(tracer_provider, logger_provider)
