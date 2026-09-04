# Architecture and implementation boundary

## Current state

One installable distribution (`incidentpilot`) uses a `src/` layout so tests
exercise installed imports. Shared configuration and JSON logging are the only
implemented runtime behavior. Strict mypy, Ruff lint/format, and pytest with
branch coverage enforce the foundation. Coverage is intentionally scoped to
shared code and must expand as services gain behavior; it is not service or
system coverage. The minimum coverage gate is 90%.

One distribution keeps initial development simple. Each service has its own
namespace and will receive a separate process/container entrypoint. This does
not provide dependency or security isolation by itself: deployed images,
credentials and network boundaries must enforce that isolation. Avoid importing
another service's internals; share contracts through `shared` or explicit APIs.

## Intended Phase 1 topology (not implemented)

| Package / infrastructure | Intended responsibility |
| --- | --- |
| `services.gateway` | FastAPI ingress and downstream request propagation |
| `services.auth` | Authentication sandbox workflows, owned persistence |
| `services.data` | Data API and owned PostgreSQL schema/migrations |
| `services.worker` | Celery tasks and Redis queue integration |
| `services.control_plane` | Separate FastAPI operational read surface |
| `shared` | Small configuration, logging and eventual telemetry contracts |
| PostgreSQL | Durable sandbox data, service-scoped users and ownership |
| Redis | Sandbox broker/cache; no public exposure |
| Prometheus | Metrics collection |
| OpenTelemetry / Tempo | Trace instrumentation, export and storage |
| Loki | Structured log storage through a dedicated collector |

The gateway will call auth/data over explicit network contracts; the data
workflow may enqueue worker jobs. The exact business flow and delivery semantics
are future Phase 1 decisions. The control plane will query operational evidence
via narrowly scoped read-only adapters, not reach into application internals.

## Reserved future architecture

These are intended paths, **not executable packages or implemented features**:

| Future path | Boundary |
| --- | --- |
| `src/incidentpilot/evidence` | Typed read-only metrics/logs/traces adapters |
| `scenarios/` | Explicit sandbox-only chaos scenarios, outside control plane |
| `src/incidentpilot/investigation` | Agent reasoning with evidence access only |
| `src/incidentpilot/approvals` | Human identity and action-scoped approval policy |
| `src/incidentpilot/execution` | Separately deployed constrained action executor |
| `src/incidentpilot/audit` | Tamper-evident decision/approval/execution records |
| `evaluations/` | Investigation and safety evaluation framework |

Reserve names in documentation rather than installing empty capabilities that
could be mistaken for available features. No multi-agent orchestration or
incident-memory implementation is included.

## Security invariant

A future incident agent must never make a production-changing action without
explicit human approval. Investigation and execution remain separate capability
and deployment boundaries. No generic shell endpoint, subprocess tool, privileged
container, or unrestricted Docker socket belongs in the control plane.

Future investigation credentials must be read-only and scoped to evidence.
The executor must independently verify an authenticated human approval bound
to the exact action, target, parameters, expiry and single-use request identity;
missing, changed, expired or replayed authorization must fail closed. Approval
must not be inferred from a model response. Execution credentials stay solely
with the executor. Audit integrity needs durable external verification and
must not be claimed merely because application logs are JSON.

These are design requirements, not implemented safeguards. The current code has
no action execution path. Production deployment is outside this foundation.

## Remaining Phase 1 work

1. Define the real sandbox business flow and service contracts, then add FastAPI
   entrypoints, readiness/liveness behavior and validated service configuration.
2. Implement PostgreSQL migrations and least-privilege service users; Redis and
   Celery wiring, bounded timeouts, retries, idempotency and failure semantics.
3. Build non-root Docker images and Compose orchestration with health checks,
   internal networks, resource limits, local secret provisioning and volumes.
4. Wire Prometheus metrics, OpenTelemetry context propagation/traces, Tempo,
   Loki and a log collector. Specify retention and sensitive-data handling.
5. Add read-only evidence adapters with bounded queries and independent access
   controls. Keep the control plane free of execution capabilities.
6. Add integration and end-to-end tests demonstrating actual cross-service work,
   failure visibility and trace/log correlation; extend coverage accordingly.
7. Add CI, a reviewed dependency lock and pinned container images; document
   startup/shutdown and verify the sandbox from a clean checkout.

Phase 2 (agents, chaos, remediation, approvals implementation, memory, audit
implementation and agent evaluation) must be separately authorized.

