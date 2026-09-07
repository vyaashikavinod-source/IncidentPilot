# Real integration tests

Start the Linux Compose sandbox, then set `INCIDENTPILOT_RUN_INTEGRATION=1` and
run `python -m pytest -m integration --no-cov`. Credentials are read from the
local environment or ignored repository `.env`.

These tests use real gateway HTTP, internal data HTTP, Redis/Celery processing,
PostgreSQL row queries and container logs. Without explicit opt-in they skip;
with opt-in, missing dependencies fail. Tests leave diagnostic job rows behind.
No service outage is injected. Readiness error paths are separately unit-tested
with explicit unavailable-dependency mocks and are not labeled end-to-end.
