# Local infrastructure

`docker-compose.yml` defines gateway, auth, data, worker, PostgreSQL, Redis and a
one-shot Alembic migration service. The reusable multi-stage Dockerfile installs
only each service's selected extras and runs application processes as non-root.

`postgres/001-app-role.sql` provisions a non-superuser application role on a fresh
PostgreSQL volume. Local credentials come from ignored `.env`; blank example
values intentionally fail Compose validation. No Docker socket is mounted.

See the repository README for startup, readiness and persistence behavior.
Prometheus, Loki, Tempo, Grafana and telemetry collectors are not added.
