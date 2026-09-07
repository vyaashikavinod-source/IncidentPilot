# Architecture: Phase 1 application slice

## Implemented boundaries

A single installable `src/incidentpilot` distribution contains separate process
entrypoints. Docker builds service-specific dependency extras. `shared` contains
configuration, contracts, bounded HTTP clients, request context and JSON logging.

- Gateway -> auth: sandbox bearer validation; typed identity, one sandbox role.
- Gateway -> data: create/read jobs with an internal sandbox token.
- Gateway -> Redis: publish the fixed `incidentpilot.process_job` task.
- Worker -> data: read jobs and PATCH running/completed/failed outcomes.
- Data -> PostgreSQL: SQLAlchemy 2 transactions; row locks for status updates.
- Migration process -> PostgreSQL: Alembic revision `0001_jobs`.

The control-plane namespace remains empty. There is no shell endpoint, Docker
socket, privileged container, infrastructure mutation API, execution capability,
AI component or incident memory. The fixed Dockerfile/build and integration-test
commands are development tooling, not runtime command-execution APIs.

## Persistence and contracts

Jobs store UUID ID, owner, description, explicit status, typed result, bounded
error code, created_at and updated_at. Database constraints enforce valid states
and consistent terminal outcomes. Only legal transitions are accepted; identical
updates are idempotent. Concurrent state changes serialize using row locks.
Reads are owner-checked at the gateway. Data's token permits internal job access;
it is sandbox service authentication, not a production authorization system.

Alembic creates the schema; there is no create_all fallback. Data readiness checks
both database access and table presence. PostgreSQL gets a persistent named volume
and a non-superuser application role. The migration and data processes share that
schema-owning role for this sandbox. Gateway/worker have neither its credentials
nor a database client dependency in their container installation extras.

## Failures and correlation

HTTP clients set explicit timeouts and surface timeout, connection, HTTP and
malformed-response failures. Gateway returns safe upstream error categories with
appropriate 401/403/404/409 or 503 status codes. Secrets, upstream response bodies
and arbitrary exception text are not placed in application logs.

Incoming valid UUID request IDs propagate through HTTP and Celery task arguments.
ContextVar state is reset after each HTTP request/task. JSON logs include the
current request ID. No OpenTelemetry tracing or telemetry backend is running.

The worker computes word count, character count and SHA-256 deterministically.
Terminal jobs are skipped on redelivery. Retryable errors have a finite retry
budget; persistent failures are recorded where possible and remain visible as
errors. A data outage can prevent even failure recording. There is no automated
repair or reconciliation. The database/broker dual write is not atomic; ambiguous
publication and duplicate POSTs are documented limitations. No exactly-once claim.

## Local isolation

Only gateway publishes `127.0.0.1:8000`. All services use an internal Compose
network. Application containers run as UID 10001, with a read-only root filesystem,
all capabilities dropped and no-new-privileges. PostgreSQL and Redis use their
upstream image startup behavior and named volumes. Credentials are generated for
local use in ignored `.env`, never embedded in images. Docker daemon administrators
can inspect container environments; this is not a production secret store.

Base-image tags and dependency ranges are not immutable pins. Shared source is a
maintainability choice, not an OS security boundary. Network routing is not a
substitute for production firewall/identity controls.

## Future invariant and reserved paths (not implemented)

The future incident agent must never cause a production-changing action without
explicit human approval. Investigation credentials must stay read-only and
separate from executor credentials. A future executor must independently verify
human approval bound to exact action, target, parameters, expiry and single-use
identity, failing closed on absent, altered, expired or replayed approval.

Reserved areas remain documentation only: `evidence/`, `investigation/`,
`approvals/`, `execution/`, `audit/`, `scenarios/` and `evaluations/`. JSON application
logs are not a tamper-evident audit trail. No Phase 2 behavior is included.

## Remaining Phase 1 work

1. Complete real Linux Compose build/start and database/queue integration validation
   wherever unavailable; exercise the provided persisted-row and correlation checks.
2. Add authorized observability in a later slice: metrics, tracing, log collection,
   Prometheus, Loki, Tempo and dashboards, with retention and sensitive-data rules.
3. Implement read-only operational evidence adapters and the control-plane read API.
4. Add CI, reviewed dependency locks and image digests; extend coverage to real
   persistence and multi-process failure handling once the sandbox is available.
5. Decide and implement submission idempotency/outbox reliability if required;
   current dual-write and stranded-job limitations are explicit.

No chaos injection, AI investigation or remediation work is authorized here.
