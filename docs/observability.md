# Observability

Phase 1 sends OTLP traces and structured application logs from gateway, auth,
data, and worker to an OpenTelemetry Collector. The Collector writes traces to
Tempo and logs to Loki. Prometheus scrapes each service's private `/metrics`
endpoint. Grafana is the only observability UI exposed to the host and starts
with Prometheus, Loki, and Tempo datasources plus service and job dashboards.

HTTP spans propagate W3C trace context through internal HTTP calls. Celery
instrumentation carries the same context into worker execution. JSON stdout and
centralized logs retain `request_id`, `trace_id`, `span_id`, `service`, and
`environment`; secrets and request bodies are excluded. Loki indexes the service
name while correlation identifiers remain structured metadata to avoid unbounded
label cardinality.

Metrics use bounded labels such as service, route template, method, status,
dependency, outcome, and event. Request IDs, job IDs, trace IDs, user IDs, and
payload values are never metric labels. Exported metrics cover HTTP traffic and
latency, dependency outcomes, readiness, submitted/completed/failed jobs, worker
task outcomes and duration, queue depth, and database readiness-query latency.

Prometheus retains its local time series in a named volume. Loki uses TSDB storage
with a 72-hour retention period; Tempo retains local traces for 24 hours. These
settings are for the disposable sandbox. Grafana credentials must be supplied in
the ignored `.env`; `.env.example` contains no credential values.

Operational backends have no host ports. Grafana listens on loopback port 3000.
No container is privileged, no Docker socket is mounted, and the control plane
has no telemetry credentials or mutation interface. Dashboards are diagnostic
views, not an approval or remediation mechanism.
