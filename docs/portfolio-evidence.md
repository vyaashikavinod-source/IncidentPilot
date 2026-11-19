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
