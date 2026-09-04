# Infrastructure reserved for Phase 1

Docker Compose will orchestrate gateway, auth, data, worker, control-plane,
PostgreSQL, Redis, Prometheus, an OpenTelemetry collector, Tempo, Loki and a
compatible log collector. No Compose manifest is provided in this foundation:
there are not yet runnable application entrypoints to orchestrate.

Future configuration must use pinned images, service health checks, private
networks, persistent data volumes and explicitly provisioned local credentials.
Publish only required local ports on loopback. Never mount the Docker socket
into the control plane. Do not introduce production credentials or imply that
observability backends are already collecting data.

