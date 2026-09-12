# Phase 2: failure benchmark infrastructure

Phase 2 provides repeatable labeled failures and deterministic evaluation data.
It does not contain an autonomous diagnosis agent, remediation, approval
execution, LangGraph, or multi-agent behavior.

## Privilege boundary

Chaos is an operator-side host capability. `python -m incidentpilot.chaos` invokes
only four fixed Compose lifecycle verbs against nine code-allowlisted service
names. Scenario files cannot supply commands, arguments, container names, URLs,
or shell text. There is no chaos HTTP API, arbitrary command command, Docker API
proxy, privileged application container, or Docker socket mount.

The Dockerfile removes `incidentpilot.chaos` and `incidentpilot.evaluation` from
service images. The default-deny `.dockerignore` excludes `chaos/ground_truth`,
`evaluation/ground_truth`, and runtime runs. The read-only control plane retains
only GET evidence routes and has no path to operator tooling or private truth.

## Scenario catalog

| ID | Failure class | Injection | Recovery |
| --- | --- | --- | --- |
| `postgres-unavailable` | dependency unavailable | stop PostgreSQL | start and wait healthy |
| `redis-unavailable` | dependency unavailable | stop Redis | start and wait healthy |
| `worker-stopped` | service unavailable | stop worker | start and wait healthy |
| `worker-paused` | processing delay | pause worker | unpause and wait healthy |
| `auth-unavailable` | service unavailable | stop auth | start and wait healthy |
| `data-unavailable` | service unavailable | stop Data | start and wait healthy |
| `gateway-unavailable` | service unavailable | stop gateway | start and wait healthy |
| `tempo-unavailable` | observability degraded | stop Tempo | start and wait healthy |
| `prometheus-unavailable` | observability degraded | stop Prometheus | start and wait healthy |

The paused-worker case replaces host CPU or memory pressure. Container resource
stress could destabilize a developer workstation and varies by Docker Desktop
allocation; pausing is bounded, deterministic, and produces queue delay without
data corruption. PostgreSQL latency and auth elevated-error hooks are deferred:
adding a proxy or runtime mutation endpoint solely for these cases would widen
the Phase 2 attack surface. The catalog instead spans dependency, application,
processing, deployment, and observability failures.

## Operator workflow and recovery

Run commands from a trusted repository checkout with Docker access:

```text
python -m incidentpilot.chaos list
python -m incidentpilot.chaos inspect worker-stopped
python -m incidentpilot.chaos run worker-stopped
python -m incidentpilot.chaos recover <run-id>
```

`run` injects exactly one scenario, verifies it, captures evidence, and always
attempts recovery in `finally`. There is no retain mode, so normal execution never
deliberately leaves a fault active. An active-state file prevents overlap and
survives an interrupted operator process; `recover` uses its recorded allowlisted
scenario. Every scenario has a validated 10–300 second maximum, and every Docker
operation and recovery poll is bounded. If recovery fails, the active marker is
retained and the command fails visibly.

## Run package and evidence

Runtime output is written under ignored `evaluation/runs/<run-id>/`:

- `manifest.json` records scenario identity/version, repository commit, UTC
  injection/recovery timestamps, affected service, results, image-set checksum,
  evidence window, private truth reference, and SHA-256 checksums of both source
  definitions.
- `evidence.json` contains bounded service status, readiness/dependency metrics,
  logs, and deployment history retrieved only through the existing read-only
  control-plane API. Backend errors are recorded as evidence instead of replaced
  by direct infrastructure reads.

Manifest and evidence JSON use stable sorted serialization and contain no
credentials. Administrative injection verification may use Compose state; the
evaluation evidence never queries PostgreSQL, Redis, Loki, Prometheus, or Tempo
directly.

## Private ground truth and scoring

Public scenario metadata under `chaos/scenarios` describes the expected visible
behavior and recovery contract. Private files under `chaos/ground_truth` contain
the labeled root cause and acceptable equivalent diagnoses. Their identity,
version, affected service, and failure class must match mechanically. Root-cause
text is absent from public inspection, evidence snapshots, logs, metrics, and
service images.

`incidentpilot.evaluation.scoring` compares a submitted diagnosis with private
truth using normalized exact/allowlisted matching. It reports root-cause,
affected-service and failure-class correctness, diagnosis latency, evidence count,
unsupported references, aggregate accuracy, pass rate, median time, and failures
by class. There is no LLM judge and no IncidentPilot performance result.

## Manual baseline

A human participant receives only one run's `evidence.json`. The recorder stores
participant ID, run/scenario IDs, start/end times, diagnosis fields, confidence,
and consulted evidence references using `ManualDiagnosis`. The evaluator later
scores that submission against private truth. No manual results are prefilled or
manufactured.

`record_manual_diagnosis` writes this typed record as stable JSON to an
operator-selected run path without embedding private ground truth.
