# Phase 5: memory and evaluation controls

IncidentPilot retains one investigation agent. It still cannot execute remediation.

## Memory

Data owns the `incident_memory` PostgreSQL table. The agent uses typed Data-service endpoints and
has no database connection or arbitrary query interface. A memory record is created only for a
proposal-ready, approved, or closed incident with a diagnosis, supporting current evidence, a
proposal, and evidence categories. Failed, incomplete, and security-rejected incidents are
ineligible. Memory excludes prompts, credentials, audit contents, and benchmark ground truth.

Retrieval is deterministic and bounded to ten records. It ranks service match, failure-class match,
tag overlap, and recency. Historical records reach the model as untrusted analogy, never proof. A
final diagnosis still requires current evidence references.

## Controls and recovery

The engine bounds provider calls, input tokens, total tokens, turns, evidence calls, wall-clock
duration, retained evidence bytes, and prompt context. Unknown provider pricing remains unavailable.
A provider or budget failure retains collected evidence and records a truthful failed state. One
concise reflection stores evidence and historical-memory IDs, never chain-of-thought.

## Evaluation and manual baseline

The Phase 2 scorer reads private ground truth only after investigation. `ManualDiagnosis` records a
participant pseudonym, timing, submitted diagnosis, and consulted evidence without private truth.
The comparison report emits `MANUAL BASELINE PENDING — NO RECORDED HUMAN RUNS` without real human
records. Until credentials exist: **REAL AGENT EVALUATION BLOCKED — NO CONFIGURED LLM PROVIDER**.
