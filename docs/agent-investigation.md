# Phase 3: evidence-driven incident investigation

Phase 3 adds one bounded investigation agent. It creates evidence-backed diagnoses and
remediation proposals, then stops. It has no remediation executor.

## Boundaries

The `agent` service is separate from the GET-only control plane. Its only operational client is
`EvidenceTools`, whose schema exposes service status, four allowlisted metric families, bounded log
search, exact trace lookup, and recent deployments. The model cannot provide a URL, PromQL, LogQL,
TraceQL, SQL, command, file path, Docker target, Celery task, or Redis operation. The OpenAI provider
uses one code-fixed HTTPS endpoint. The service receives no database URL, broker URL, Docker socket,
host mount, deployment credential, chaos package, or ground truth.

Incident state is sent to typed internal Data-service endpoints. Data remains the only PostgreSQL
owner. The control-plane API remains GET-only. The agent's localhost API requires the sandbox
internal credential and never accepts code, URLs, queries, or commands.

Operational evidence and incident text are untrusted data. Prompts have separate system-policy,
incident-data, evidence/tool-result, and concise-step sections. The policy says data cannot override
the capability boundary. Only concise operational summaries are stored; hidden chain-of-thought is
neither requested nor persisted.

## State machine and limits

An incident progresses from `open` to `investigating`, `diagnosed`, and `proposal_ready`. Approval
may move it to `approved`; there is no executed state. Each loop turn either requests one typed
evidence operation or returns a structured diagnosis. Defaults enforce six turns, eight tool calls,
90 seconds, 100 KB retained evidence, 1,200 output tokens per provider request, and a 20-second LLM
timeout. Any provider, schema, evidence, reference, wall-clock, turn, tool, or payload failure ends
the run cleanly and emits an audit event.

Every evidence object retains its control-plane UUID. A diagnosis requires at least one supporting
evidence UUID, and every supporting or contradicting UUID must exist in the investigation. Unknown
references reject the diagnosis. Steps record the hypothesis, typed action, returned IDs, concise
observation, and disposition without hidden reasoning.

## Proposals and approval

A proposal contains only an allowlisted conceptual action category, target, rationale, expected
effect, risk, rollback plan, and verification plan. It contains no command. Canonical JSON excluding
status and the hash itself is SHA-256 hashed. An approval binds proposal ID, exact hash, approver, and
timestamp. `require_valid_approval` recomputes the hash; changing proposal content invalidates prior
approval. Approval and rejection only update persisted accountability state. No execution route or
executor exists.

## Audit chain

Data serializes audit appends by locking the incident row. Records contain an incident-local
sequence, previous hash, canonical record hash, event type, actor, timestamp, and safe metadata.
The verifier detects content modification, broken links, deletion from the observed chain, and
reordering. There are no update or delete audit endpoints.

## Provider configuration

`fake` is the safe default and is accepted only when explicitly injected by unit tests. A normal
investigation returns `real_llm_provider_not_configured` until the operator selects `openai` and sets
`INCIDENTPILOT_LLM_API_KEY` outside version control. The provider abstraction validates structured
output and normalizes timeouts, HTTP errors, and malformed responses. Provider/model and available
token counts are persisted. Prompts and full provider responses are not logged.

## Phase 2 evaluation

The operator-only evaluation bridge starts one allowlisted chaos run, creates a generic observable
incident while the fault is active, runs the agent, then lets the fail-safe harness recover the
service. Only after investigation and recovery does it load private truth and apply deterministic
scoring. Runtime investigation and score files remain ignored. Scenario IDs, definitions,
acceptable diagnoses, and ground truth are never sent to the agent.

Real scenario results require one configured real provider and a single blinded pass across all
nine scenarios. A human comparison remains pending until engineers use the Phase 2 manual recorder
while blinded to the same private truth. No synthetic or fake-provider result is a performance
claim.

## API

- `POST /v1/incidents`
- `GET /v1/incidents/{incident_id}`
- `POST /v1/incidents/{incident_id}/investigate`
- `GET /v1/incidents/{incident_id}/investigation`
- `GET /v1/incidents/{incident_id}/proposals`
- `POST /v1/incidents/{incident_id}/proposals/{proposal_id}/approve`
- `POST /v1/incidents/{incident_id}/proposals/{proposal_id}/reject`
- `GET /v1/incidents/{incident_id}/audit/verify`

There is no execute, shell, restart, deployment, rollback, chaos, or arbitrary request endpoint.
