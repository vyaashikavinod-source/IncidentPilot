# Validation record

Validation performed on September 7, 2026 with Python 3.12.14.

## Successful checks

- `python -m pytest`: 71 passed, 2 skipped, 2 visible upstream deprecation warnings.
- Shared-code coverage: 100% statements and branches; threshold 90%.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: 36 files formatted.
- `python -m mypy`: passed for 32 source, test and migration files.
- `python -m pip check`: no broken requirements.
- `docker compose config --quiet`: passed using generated, ignored local values.
- `python -m alembic history`: `0001_jobs` is the single head.
- `python -m alembic upgrade head --sql`: generated complete PostgreSQL DDL,
  constraints, index and Alembic version update without an error.

Pytest exposes two dependency warnings from FastAPI/Starlette test-client imports:
the bundled FastAPI compatibility shim warns about an eventual `httpx2` move,
and Starlette uses a deprecated AnyIO alias. They are not suppressed. Tests pass.

## Docker limitation

Docker CLI 29.6.2 and Compose 5.3.1 are installed. Both sandboxed and elevated
`docker version` calls failed to reach
`npipe:////./pipe/dockerDesktopLinuxEngine`; the socket did not exist. A
`docker desktop start` attempt made no progress and was interrupted after more
than one minute. A final engine check produced the same missing-socket error.

Therefore `docker compose build`, `up -d` and `ps` could not complete. PostgreSQL
and Redis were not started, Alembic was not applied to a live database, Celery
did not execute a real job, and no persisted row or cross-process request-ID log
can truthfully be reported. The two opt-in real integration tests skipped because
`INCIDENTPILOT_RUN_INTEGRATION` was unset. Their code is present for validation
on a machine with a running Linux Docker engine.

Unit tests do verify request-ID propagation through HTTP mock transports and
Celery arguments, JSON log inclusion, retry exhaustion, unavailable readiness
dependencies, and safe handling of concurrent duplicate task delivery. These
are unit-level evidence and are not described as end-to-end validation.
