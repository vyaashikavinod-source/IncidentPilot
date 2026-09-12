# Validation record

Live validation was completed on September 7, 2026 with Python 3.12.14,
Docker Engine 29.6.2 on WSL2, and Docker Compose 5.3.1.

## Docker diagnosis and repair

The `desktop-linux` context was correct, but the Linux engine pipe did not exist,
the `docker-desktop` WSL distribution and `com.docker.service` were stopped, and
no Docker backend process was running. Starting the Windows service directly was
denied. The installed `docker desktop start` command initially appeared idle but
completed startup asynchronously; a later `docker info` returned the Linux server.
No reinstall, reset, WSL change, or data deletion was performed.

All five application images built successfully. The first live start exposed one
Compose defect: gateway was attached only to the internal application network.
Docker retained its HostConfig port request but did not publish a host endpoint.
Gateway now also attaches to a dedicated edge network; backend services remain
only on the internal network. A topology regression test enforces that boundary.

## Live stack and migration

PostgreSQL, Redis, auth, data, worker, and gateway became healthy. The one-shot
migration container exited 0. Live `alembic current` reported `0001_jobs (head)`.
Catalog queries confirmed the jobs table, job_status and job_outcome constraints,
primary key, and owner index. Schema creation used Alembic; no `create_all()`
fallback was used.

## Real workflow evidence

A real host request to gateway returned HTTP 202 and an initial queued job. The
worker received `incidentpilot.process_job`, logged running and completed, and
Celery logged task success. Final gateway retrieval returned completed with the
expected word count, character count, and SHA-256. A direct read-only PostgreSQL
query found the same ID, sandbox owner, description, result, and UTC timestamps.
Redis command counters increased and the jobs queue was empty after consumption.

One correlation ID was present in gateway, auth, data, and worker structured logs.
The worker running/completed entries and its surrounding data-service PATCH calls
used that ID, demonstrating queue argument and worker-to-data propagation. Runtime
job, task, and correlation IDs are intentionally kept out of version control.

Two opt-in integration tests passed against real containers. They exercise real
Celery completion and persistence, per-service correlation logs, direct database
evidence, internal data CRUD, invalid transitions, and gateway ownership behavior.

## Readiness and recovery

- PostgreSQL stopped: data health stayed 200, data readiness became 503,
  gateway health stayed 200, and gateway readiness/job retrieval became 503.
  PostgreSQL and gateway readiness recovered after restart.
- Auth stopped: gateway health stayed 200 and readiness became 503 connection
  failure. Auth and gateway readiness recovered after restart.
- Redis stopped: gateway health stayed 200, readiness became 503 broker unavailable,
  and submission returned 503; its created row was marked failed/enqueue_failed.
  Redis and gateway readiness recovered after restart. The Celery worker logged
  its expected broker disconnect/retry sequence and reconnected.

No data was deleted and every stopped dependency was restored. The PostgreSQL
catalog contains one expected ERROR from an initially ambiguous read-only
inspection expression; its corrected casted query passed. Worker connection
errors and gateway enqueue error in the logs correspond to the intentional Redis
stop. They are retained as operational evidence, not suppressed.

## Quality checks

The final command results are recorded in the task completion report. FastAPI and
Starlette currently emit two upstream test-client deprecation warnings. Celery
emits a pending-deprecation warning about broker retry settings during a forced
disconnect. These warnings are visible and are not suppressed.

## September 11 hardening validation

Migration `0003_job_idempotency` reached head on the existing volume and on a
temporary empty database; the clean catalog contained the owner/key unique
constraint. The temporary database was removed afterward. Six concurrent gateway
submissions produced one job and one queue publication, payload conflict returned
409, owner scoping allowed independent rows, and replay survived data and gateway
restarts. Queued work survived a worker restart; duplicate Celery deliveries were
terminally idempotent; a Redis interruption produced a durable failed job whose
same-key retry did not republish. All six live integration tests passed, including
the read-only evidence queries. Hash-verified application images built
successfully from the pinned runtime lock.

## September 12 Phase 2 validation

The operator-side chaos harness ran all nine catalog scenarios serially against
the live Compose sandbox. Every run injected its declared failure, captured the
expected bounded evidence through the read-only control-plane API, restored the
affected service, and waited for control-plane readiness to recover. The final
run completed with 9 passed, 107 deselected, and 3 visible upstream/cache
warnings in 314.17 seconds.

Each run produced an ignored, stable manifest with scenario and private
ground-truth checksums, repository revision, Compose and image provenance,
timestamps, injection and recovery results, and evidence file references.
Inspection confirmed that evidence snapshots contain no private root-cause
field. Imports inside the rebuilt control-plane image confirmed that neither
`incidentpilot.chaos` nor `incidentpilot.evaluation` is present in service
images.
