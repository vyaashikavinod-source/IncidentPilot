# Phase 1 hardening

## Submission idempotency

`POST /v1/jobs` requires an `Idempotency-Key` containing 1–128 ASCII letters,
digits, dots, underscores, colons, or hyphens. The data service stores the key and
a canonical request-body SHA-256 beside the job. A unique PostgreSQL constraint
on `(owner_id, idempotency_key)` is the concurrency authority. Concurrent inserts
recover from the losing unique-constraint race by reading the winning row.

The same owner, key, and payload returns the original job with
`Idempotency-Replayed: true`; the gateway does not publish another Celery message.
The same owner and key with a different payload returns 409. Keys are scoped by
the authenticated owner. Migration `0003_job_idempotency` gives legacy rows a
unique `legacy-<job-id>` key before making the columns non-null.

`X-Request-ID` correlates one traversal through HTTP, Celery, logs, and traces.
`Idempotency-Key` identifies a logical submission across separate attempts and
restarts. Reusing a request ID does not deduplicate work, and a replay may carry a
new request ID while still returning the original job.

This preserves the Phase 1 database-then-broker sequence. A broker failure returns
503 and attempts to mark the durable job `failed/enqueue_failed`. Retrying that
submission returns the failed job. There is no outbox, automatic reconciliation,
or exactly-once claim.

## Reproducible dependencies and images

`requirements.lock` contains the runtime union used by every application image.
`requirements-dev.lock` adds test, lint, typing, and lock-generation tools. Both
are generated from `pyproject.toml` by `make lock`, contain hashes, and must be
reviewed like source. Local and CI installation uses `--require-hashes`; the
project itself is then installed with `--no-deps`.

Compose external images use a readable version tag plus an immutable registry
digest. Updating an image requires selecting the intended tag, pulling it,
recording its reported `RepoDigest`, then validating the full stack. Locally built
IncidentPilot images derive Python dependencies from the runtime lock.

## CI and boundaries

GitHub Actions runs unit coverage, Ruff lint and formatting, strict mypy, `pip
check`, Compose validation, image builds, migrations, and live integration tests.
CI values are isolated sandbox credentials used only for the ephemeral runner.

The control plane remains read-only and connects only to the evidence and edge
networks. It receives no Docker socket, generic shell facility, PostgreSQL or
Redis access, queue publication capability, or action execution endpoint. Human
approval and execution remain future work and are not simulated here.

## Phase 1 exit criteria

Phase 1 can exit when local and CI quality gates pass, a clean schema reaches the
Alembic head, the live workflow and evidence queries pass, concurrent and restart
idempotency passes, dependency and image pins build, and a tracked-file secret
scan is clean. Phase 2 remains out of scope.

## Remaining limitations

The sandbox has one fixed development identity, shared internal credentials, and
a single Celery worker. Database commit and broker publication remain non-atomic.
No reconciler repairs stranded nonterminal rows, and no production deployment or
high-availability behavior is claimed. The repository defines CI locally; its
first hosted run remains external evidence after the commit is pushed.
