# IncidentPilot

Phase 3 adds a bounded evidence-driven investigation service. It produces structured diagnoses and
proposal-only remediation recommendations, then stops. See
[agent investigation](docs/agent-investigation.md). It cannot execute remediation.

Phase 2 adds operator-side failure benchmark infrastructure and deterministic
ground-truth scoring. See [chaos and evaluation](docs/chaos-evaluation.md). It does
not implement an autonomous incident agent or remediation execution.

Phase 1 application slice: an asynchronous job workflow using FastAPI,
PostgreSQL, Redis and Celery. Service code and Compose configuration are present;
see `docs/validation.md` for what has actually been executed in this environment.
There is no remediation execution, long-term incident memory, multi-agent orchestration, or
infrastructure mutation API. Chaos remains an operator-only host capability.
The sandbox now includes metrics, tracing, centralized logs, and provisioned
dashboards.

## Implemented workflow

1. Client submits `POST /v1/jobs` with a sandbox bearer token and an
   `Idempotency-Key`.
2. Gateway calls auth, which returns the single `sandbox-user` identity.
3. Gateway calls data to persist a queued job, then publishes its ID and the
   originating request ID to the Redis-backed Celery queue.
4. Worker reads and updates the job through the data API: running, then completed
   with word count, character count and SHA-256 of the description.
5. Authenticated `GET /v1/jobs/{id}` retrieves the current state. Gateway checks
   ownership; a different owner is reported as not found.

Only data (and the one-shot migration process) receives PostgreSQL credentials.
Gateway and worker use HTTP; neither contains database-access code.

## Local sandbox startup

Requires Docker Engine with Linux containers and Docker Compose. Python 3.11+
is required for host-side development; checks here use Python 3.12.

Copy `.env.example` to `.env`, then fill the four blank values with independent
random hexadecimal strings. For example, run `python -c "import secrets;
print(secrets.token_hex(24))"` separately for each value. Never commit `.env`.
An ignored `.env` may already exist from local validation; preserve it.

**SANDBOX ONLY:** the bearer token authenticates one fixed development identity.
This is not a production identity system. Internal HTTP uses a separate shared
sandbox token, and Redis trusts the isolated local network. No production use.
Compose requires nonempty values; application settings also validate token lengths,
URLs, timeouts and retry limits. Use hexadecimal DB passwords so they are URL-safe.

```sh
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f gateway auth data worker
```

`config --quiet` validates without printing resolved credentials. The `migrate`
service must exit successfully before data starts. It runs `alembic upgrade head`;
normal HTTP service startup never creates tables automatically. PostgreSQL's
initialization SQL creates a non-superuser application role only for a fresh volume.
Changing `.env` does not rotate credentials inside an existing database volume.

Stop with `docker compose down`; named PostgreSQL and Redis volumes remain.
Do not remove volumes unless you intend to discard sandbox data.

| Service | Port / access | Readiness |
| --- | --- | --- |
| Gateway | host `127.0.0.1:${INCIDENTPILOT_GATEWAY_PORT:-8000}` | auth, data and Redis respond |
| Auth | internal `auth:8000` | validated configuration loaded |
| Data | internal `data:8000` | PostgreSQL query against jobs succeeds |
| Worker | internal `worker:9100` | Prometheus metrics endpoint responds |
| PostgreSQL | internal `postgres:5432` | pg_isready |
| Redis | internal `redis:6379` | PING |
| Grafana | host `127.0.0.1:3000` | Grafana health endpoint |
| Prometheus, Loki, Tempo, Collector | internal only | container health checks |

HTTP services expose `/health` for process liveness and `/ready` for readiness.
Readiness failures return 503. The worker ping confirms worker/broker connectivity;
it does not promise the data service will remain available when a task starts.

To submit and retrieve a job from PowerShell (set the token from your local `.env`):

```powershell
$headers = @{ Authorization = "Bearer $env:INCIDENTPILOT_SANDBOX_AUTH_TOKEN"; "X-Request-ID" = [guid]::NewGuid().ToString(); "Idempotency-Key" = [guid]::NewGuid().ToString() }
$job = Invoke-RestMethod http://127.0.0.1:8000/v1/jobs -Method Post -Headers $headers -ContentType application/json -Body '{"description":"hello incident pilot"}'
Invoke-RestMethod "http://127.0.0.1:8000/v1/jobs/$($job.id)" -Headers $headers
```

Successful POST returns HTTP 202 with the queued record and an
`Idempotency-Replayed` header. Repeating the same owner/key/payload returns the
original row without another queue publication; changing the payload returns
409. GET uses the same Job
schema: ID, owner, description, status, result, error and UTC timestamps.
Missing or invalid credentials return 401; invalid bodies return 422. Valid
UUID `X-Request-ID` headers are preserved (canonicalized); others are replaced.
The ID appears in response headers, inter-service requests, Celery arguments and
application JSON logs. This is correlation, not distributed tracing.

## Failure and delivery semantics

Jobs progress `queued -> running -> completed`, or `queued/running -> failed`.
Terminal outcomes are immutable; repeating an identical PATCH is idempotent.
Data locks the row for transitions. Redis uses AOF and no-eviction behavior;
Celery uses JSON serialization, late acknowledgement, a 300-second visibility
timeout and a 90-second task hard limit. Work is deterministic and has no external
side effects, so duplicate deliveries can safely repeat the calculation.

Worker transport/5xx/429 failures retry at most three times after the initial
attempt, with a two-second delay by default (validated limits: 0–5 retries).
Permanent HTTP errors and processing errors do not retry. At exhaustion it tries
to persist a failed outcome, logs if that is impossible, and raises the error.
A complete data outage or hard worker termination can leave a nonterminal row.
There is no reconciliation or remediation process in this slice.

PostgreSQL commit and broker publication are **not atomic**. If publication fails,
the gateway returns 503 with the job ID and attempts to mark the job failed. An
ambiguous broker acknowledgement can race with processing. Query the returned ID;
retrying POST with the same key returns that failed job without publishing it
again. A transactional outbox is not implemented, and exactly-once delivery is
not claimed.

## Development and tests

```sh
python -m venv .venv
# POSIX: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements-dev.lock
python -m pip install --no-deps -e .
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pip check
```

GNU Make equivalents: `make install-locked`, `make check`, `make test`, `make lint`,
`make typecheck`. `make lock` regenerates both hash-pinned lock files with pip-tools.
Dependency extras separate API, database and queue tooling.
The observability extra contains the OpenTelemetry SDK, exporters, and framework instrumentations used by the services.
Application builds install the runtime lock before installing the local package
without dependency resolution. External images retain readable version tags and
are pinned to registry digests.

Tests use explicit mock transports for unit isolation and label these as unit
checks. Real integration tests require the running Compose stack and opt-in:

```powershell
$env:INCIDENTPILOT_RUN_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest -m integration --no-cov
```

Without opt-in, integration tests explicitly skip. Once enabled, unavailable
services are failures, not skips. Tests verify real Celery completion, the
persisted PostgreSQL row, per-service correlation logs and internal CRUD. They
leave their job rows in the sandbox. They do not stop services or inject faults.
The 90% branch-coverage gate currently covers shared code, not the entire system.

Service processes read environment variables, not `.env` automatically. Compose
selectively injects them. For manual startup, export only the variables needed
by that service and run `uvicorn incidentpilot.services.<service>.app:create_app
--factory --port 8000 --no-access-log` (service is auth, data or gateway).
Worker command: `celery -A incidentpilot.services.worker.app:app worker
--concurrency=1 --loglevel=INFO`. Run workers in Linux containers.

See [architecture](docs/architecture.md), [hardening](docs/hardening.md),
[observability](docs/observability.md), and [validation](docs/validation.md).
The [evidence-plane guide](docs/evidence-plane.md) documents the bounded read-only
operator API and its enforced permission boundary.
