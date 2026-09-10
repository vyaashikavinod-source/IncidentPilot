# Read-only operational evidence plane

The Phase 1 control plane exposes typed reads from Prometheus, Loki, Tempo,
allowlisted service health endpoints, and deployment history owned by Data. Each
source implements a separate protocol; there is no generic URL, HTTP method, query
language, command, container, or filesystem interface.

The operator API listens only on `127.0.0.1:8001` by default:

- `GET /health` reports process liveness.
- `GET /ready` reports `ready` or `degraded` plus per-source availability.
- `GET /v1/evidence/services` checks gateway, auth, data, and the worker metrics endpoint.
- `GET /v1/evidence/deployments?limit=20` reads recent records through Data.
- `GET /v1/evidence/metrics/{requests|jobs|dependencies|readiness}` runs an internal allowlisted PromQL template.
- `GET /v1/evidence/logs` accepts typed service, environment, level, request ID, trace ID, UTC range, and limit filters.
- `GET /v1/evidence/traces/{trace_id}` retrieves one validated 32-character lowercase hexadecimal trace ID.

Defaults are a 15-minute log lookback, 100 log results, and a 15-minute metrics
window. Hard limits are a 24-hour window, 500 log results, 100 deployment records,
500 returned trace spans, and a three-second backend timeout. Unsupported filters,
oversized windows, and oversized limits return validation errors. Backend timeout,
non-2xx, and malformed responses return 503 instead of fabricated empty evidence.

Every result includes an evidence UUID, source type/name, collection time, safe
request description, requested window, result count, truncation state, backend
latency, and the control-plane request ID. Evidence types retain distinct payloads.
Obvious password, secret, token, and authorization fields in parsed logs are
redacted. Trace attributes use a small safe allowlist.

Deployment history is stored in PostgreSQL by Data and created by Alembic. The
initial row records the previously verified observability commit. The evidence API
has only a Data read credential; its container has no database URL, Redis/Celery
configuration, Docker socket, privileged mode, writable root filesystem, or
application mutation endpoint.
Compose places it on a dedicated internal evidence network shared only with its
allowlisted sources. PostgreSQL and Redis remain exclusively on the application
network, so the control plane has no route to either stateful backend.

Given request ID `X` and trace ID `Y`, an operator can inspect:

```text
GET http://127.0.0.1:8001/v1/evidence/services
GET http://127.0.0.1:8001/v1/evidence/metrics/requests?window_seconds=900
GET http://127.0.0.1:8001/v1/evidence/logs?service=gateway&request_id=X
GET http://127.0.0.1:8001/v1/evidence/traces/Y
GET http://127.0.0.1:8001/v1/evidence/deployments?limit=20
```

This is an operator-facing read API. It does not implement an autonomous agent,
approval execution, remediation, or chaos injection.
