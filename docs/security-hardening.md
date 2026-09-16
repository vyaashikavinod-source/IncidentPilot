# Phase 4 security hardening

IncidentPilot still cannot execute remediation. The agent can collect evidence through eight
typed, read-only operations and can create a proposal. Approval records intent; it has no
infrastructure side effect.

## Trust boundaries and threats

The public operator boundary ends at the agent API. Operators authenticate with short-lived,
HMAC-signed local bearer tokens containing a subject, token ID, issuer, audience, expiry, and
roles. The agent uses a separate incident-data credential to reach Data. The control plane keeps
its existing read-only evidence credential. The agent has no Docker socket, database URL, broker
URL, generic HTTP tool, shell, SQL, Redis, or Celery interface.

The threat model covers malicious incident payloads, malicious log or trace producers,
compromised or incorrect model output, unauthorized operators, replayed approval requests, and
accidental configuration exposure. A host or database administrator remains trusted; the audit
design detects stored-record changes but does not claim immutability against an attacker holding
the audit signing secret.

## Authorization

| Endpoint operation | viewer | investigator | approver | admin |
|---|---:|---:|---:|---:|
| Read incident, investigation, proposals, audit | yes | yes | yes | yes |
| Create incident or start investigation | no | yes | no | yes |
| Approve or reject an exact proposal | no | no | yes | yes |
| Create audit checkpoint or verify all chains | no | no | no | yes |

Roles are additive. Authentication failures return a generic 401 and authorization failures a
generic 403. Neither response nor security log contains the submitted bearer credential.

## Approval integrity and concurrency

An approval binds the incident ID, proposal ID, canonical proposal hash, proposal version,
authenticated approver subject, decision, request ID, and server timestamp. Data performs the
transition under a PostgreSQL row lock. An identical request ID and identical decision is a safe
idempotent replay; reuse with changed semantics is rejected. A decided proposal cannot be decided
again. Proposal mutation, stale versions, wrong incident binding, and unauthorized callers are
rejected. Investigation claims also use a row lock, so only one claimant can move an open or
recoverable failed incident to `investigating`.

## Audit assurance

New records use chain version 2, explicit all-zero genesis hash, and
`incidentpilot-canonical-json-v1`. Verification reports the failing sequence and reason for a
bad sequence, link, version, or record digest. Legacy version 1 records remain verifiable during
migration. Operators can verify one incident; admins can verify all incident chains. Verification
never repairs records.

An admin can create an HMAC-SHA256 checkpoint over the incident ID, last sequence, last record
hash, timestamp, and checkpoint version. The signing secret is configured only on Data. A
checkpoint anchors the prefix that existed when it was created. It provides tamper evidence only
while the signing secret and checkpoint table are protected independently from an attacker able
to rewrite both.

## Model and evidence boundaries

Prompts label incident fields and collected observations as untrusted data. Text embedded in
alerts, logs, traces, or deployment metadata cannot add tools or alter policy. Provider output is
parsed with strict Pydantic models that reject extra fields, unknown tools, unsupported proposal
categories, arbitrary URLs, command fields, invalid confidence, and malformed evidence IDs.
Diagnosis evidence references must match evidence actually collected in the current run.

Evidence arguments expose allowlisted service names, bounded time windows and result counts, and
a fixed trace-ID format. Raw PromQL, LogQL, TraceQL, SQL, paths, URLs, and commands are not schema
fields. Agent HTTP base URLs come only from validated configuration and must resolve to `data:8000`
or `control-plane:8000` with no credentials, query, fragment, or path. This blocks model-directed
SSRF to loopback, cloud metadata, host gateways, and external sites.

Secrets use Pydantic secret types and environment configuration. Incident metadata rejects
sensitive key names and bounded payload checks prevent it becoming a credential dump. Provider
and HTTP failures are normalized before logging or persistence. Authorization headers, API keys,
internal credentials, and signing secrets are excluded from incident, evidence, audit, and prompt
models.

## Limits, recovery, and observability

Each process applies a sliding 60-second rate window per signed token ID: 10 incident creations,
3 investigation starts, and 10 approval decisions. This is intentionally local to one agent
process; counters reset on restart and are not coordinated between replicas.

Provider, malformed-output, evidence, turn, tool-call, evidence-size, and wall-clock failures set
the incident to `investigation_failed`, record completion and failure timestamps plus a bounded
reason, and permit a later atomic retry. Claims carry a ten-minute database lease; after an
agent crash, a later request can atomically reclaim an expired `investigating` incident. A failure
before persistence may require an operator to retry after Data recovers.

Security metrics use a bounded event label for authentication failure, authorization denial,
state conflicts, approval conflicts, invalid provider output, limit termination, rate rejection,
and audit verification failure. They never label operator, incident, request, or trace IDs.
Incident-scoped authorization and decision failures are appended to the audit chain when Data is
available; unauthenticated requests cannot safely be attributed to an incident identity.

## Known limitations

The sandbox token issuer is a local utility rather than external IAM. HMAC signing assumes secret
distribution is protected. Rate limiting is process-local. Expired investigations are reclaimed
on request rather than by a background reaper. Audit checkpoints are stored in the same PostgreSQL deployment, so an independent export
would strengthen their trust boundary. No remediation executor exists.
