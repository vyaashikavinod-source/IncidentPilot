import io
import json
from pathlib import Path

import pytest
import yaml
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import generate_latest
from pydantic import ValidationError

from incidentpilot.shared.config import Settings
from incidentpilot.shared.correlation import request_id
from incidentpilot.shared.logging import configure_logging
from incidentpilot.shared.metrics import Metrics


def test_telemetry_configuration_is_explicit_and_validated() -> None:
    assert Settings().telemetry_enabled is False
    enabled = Settings(telemetry_enabled=True, otlp_endpoint="http://collector:4318/")
    assert enabled.otlp_endpoint == "http://collector:4318"
    with pytest.raises(ValidationError):
        Settings(otlp_endpoint="http://user:secret@collector:4318")


def test_json_log_contains_request_trace_and_span_correlation() -> None:
    stream = io.StringIO()
    logger = configure_logging(Settings(service_name="gateway"), stream)
    provider = TracerProvider()
    token = request_id.set("11111111-1111-1111-1111-111111111111")
    try:
        with provider.get_tracer("test").start_as_current_span("operation"):
            logger.info("observed")
    finally:
        request_id.reset(token)
        provider.shutdown()
    event = json.loads(stream.getvalue())
    assert event["request_id"] == "11111111-1111-1111-1111-111111111111"
    assert len(event["trace_id"]) == 32
    assert len(event["span_id"]) == 16


def test_metric_labels_are_bounded_and_exclude_identifiers() -> None:
    metrics = Metrics("gateway")
    metrics.jobs.labels("gateway", "submitted").inc()
    output = generate_latest(metrics.registry).decode()
    forbidden = {"job_id", "request_id", "trace_id", "user_id", "description"}
    metric_labels = {
        label
        for collector in metrics.registry.collect()
        for metric in collector.samples
        for label in metric.labels
    }
    assert forbidden.isdisjoint(metric_labels)
    assert 'incidentpilot_jobs_total{event="submitted",service="gateway"} 1.0' in output


def test_grafana_provisions_all_sources_and_dashboards() -> None:
    root = Path(__file__).resolve().parents[2]
    sources = yaml.safe_load(
        (root / "infra/grafana/provisioning/datasources/datasources.yaml").read_text()
    )
    assert {item["uid"] for item in sources["datasources"]} == {"prometheus", "loki", "tempo"}
    dashboard_dir = root / "infra/grafana/dashboards"
    dashboards = [json.loads(path.read_text()) for path in dashboard_dir.glob("*.json")]
    assert {item["uid"] for item in dashboards} == {
        "incidentpilot-services",
        "incidentpilot-jobs",
    }
