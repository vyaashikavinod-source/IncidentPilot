# Local fault evaluation and public recorded replay

`src/incidentpilot/evaluation/toy_faults.py` starts two real HTTP services on
random loopback-only ports. The gateway calls a dependency and uses a bounded
connection pool. Each run verifies a healthy control, injects one fault, issues
four concurrent requests, investigates bounded logs/metrics, restores the
service, and verifies recovery. No production service is touched and the
agent never executes its proposed fix.

Faults: request_limit=0 (bad configuration); occupied pool permits (exhaustion);
dependency sleeps past the gateway timeout (slow dependency). These are actual
HTTP failures and timings, not prerecorded strings standing in for a server.

On 2026-11-17, nine cases were recorded at
`evaluation/runs/portfolio-rules-2026-11-17.json`. All nine faults and recoveries
were verified. The deterministic diagnostic baseline got six of nine correct,
with median 45.33 ms from probe initiation to diagnosis, zero model tokens,
and zero API spend. Slow-dependency cases also caused pool pressure and the rule
misdiagnosed them. This is a useful negative result, not LLM performance evidence.
The input ground truth is not passed to the investigation function or prompt.

```powershell
$env:PYTHONPATH = 'src'
python -m incidentpilot.evaluation.toy_faults --count 9 --output evaluation/runs/new-rules-run.json
python -m incidentpilot.evaluation.toy_faults --count 9 --output evaluation/runs/new-model-run.json --endpoint http://127.0.0.1:8080/v1/chat/completions --model YOUR_LOCAL_MODEL
```

The actual model loop is a bounded state machine: choose read_metrics/read_logs,
observe the tool result, repeat up to six turns, then propose a diagnosis and fix
with evidence references. A generic URL, filesystem, shell or mutation tool is
not available. LangGraph is unnecessary for this small graph. Real model runs
need a local model server or securely configured MODEL_API_KEY for an external
HTTPS chat-completions endpoint. Missing usage/pricing remains unavailable.
Optional --input-rate/--output-rate supplies USD per million tokens for cost
estimates. There is no provider credential in the replay or public site.

Rules-baseline results are replayed in a separate Recorded experiments panel.
The original six synthetic console scenarios remain explicitly illustrative.
Do not relabel them as real AI traces. The replay includes logs, metrics, chosen
tool actions, diagnoses, errors, HTTP statuses, timings, and the failed cases.
Downloadable public JSON contains only the controlled toy experiment.

## Actual local model run

Nine real LLM investigations subsequently ran on the same toy faults, using
Qwen2.5-1.5B-Instruct-GGUF Q4_K_M on CPU via official llama.cpp b12494.
Publisher revision: `91cad51170dc346986eccefdc2dd33a9da36ead9`.
Model SHA256: `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`.

All nine faults/recoveries were verified. The model diagnosed 3/9 correctly
(33.3%), taking median 8.156 seconds and 3,280 input + 977 output tokens.
API token charges were zero; hardware/electricity is excluded. The model called
read-only evidence tools and proposed fixes but consistently chose pool exhaustion,
including cases whose actual root cause was different. Failed diagnoses remain
visible. This small public instruction model is not project-fine-tuned.

`frontend/public/recorded-runs.json` contains these real runs.
The public replay now presents the LLM result alongside the earlier rules-baseline
summary. No public request invokes the model, and no model/API key is exposed.
The local inference process was stopped after measurement. The user chose the free recorded replay instead of public runtime model hosting.


## Failure audit — 21 November 2026

All nine raw diagnoses predict `pool_exhaustion`. Each trace calls only
`read_metrics` for `gateway`, then diagnoses: no logs, config or dependency
evidence is read. Accuracy 3/9 matches an always-pool predictor on the balanced
three-fault sample; it does not demonstrate root-cause discrimination.
Bad-config evidence has `request_limit: 0`. The model also invents 50 requests
where the recorded counter is 5. Rules outperform it (6/9). No improved agent
run is claimed. The browser's incident list now maps the nine recorded run IDs
to the actual evidence/diagnoses, replacing unrelated synthetic sample rows.

## Broader-evidence and taxonomy follow-ups

Original nine-case records remain unchanged: Qwen2.5-1.5B 3/9, rules 6/9.
The original model predicted pool exhaustion every time after a single gateway
metrics read, including the unsupported 50-request claim.

The new host policy reads metrics, logs and configuration from both gateway
and dependency before model decisions. These six initial reads are selected
by the host, not the agent. The model can request additional allowlisted reads,
must cite both services and at least two tool types, and cannot execute fixes.
Invalid citations and unsupported explicit request counts are rejected. This
does not certify the explanation's semantics.

All runs use the same balanced nine-case toy protocol and retain failures:

| Model / policy | Correct | Notes |
| --- | ---: | --- |
| Original 1.5B metrics-only | 3/9 | Always pool exhaustion |
| 1.5B broader evidence v2 | 0/9 | More evidence did not improve interpretation |
| 3B broader evidence v2 | 4/9 | Includes timeout and rejected diagnosis |
| Gemini Flash-Lite v2 | 3/9 | Calls capacity/latency configuration bad_config |
| Gemini Flash-Lite taxonomy v3 | 8/9 | Eight accepted diagnoses correct; one API error counted incorrect |
| Original rules baseline | 6/9 | Deterministic baseline |

Taxonomy v3 explicitly distinguishes gateway admission rejection, unavailable
connection slots with responsive dependency, and upstream latency exceeding
the gateway deadline. Definitions were clarified after reviewing v2 errors.
This is exploratory on reused toy fault templates, not independent validation,
proof of general diagnostic ability, or a fair model-only ablation. A broader
unseen-fault evaluation remains necessary. No expected case identity, ground
truth service, or correctness feedback is given to the model.

V3 median time: 3.711342 seconds. Known successful-call usage: 8,811 input and
1,508 output tokens. The failed call omitted usage, so complete totals remain
unavailable. Existing Google project billing stayed disabled; actual API
charge $0, with no paid fallback. Local CPU costs exclude hardware/electricity.

The console defaults to the latest recorded v3 incidents, with all older sets
selectable for trace comparison and JSON download. The failed API case is
marked investigation_failed. Original records are not overwritten. Future
harness runs also fsync a JSONL record after each completed injected fault.
