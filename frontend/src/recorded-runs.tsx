import recorded from './recorded-runs.json';

type Run = { run_id:string; fault:string; correct:boolean; time_to_diagnosis_seconds:number; http_statuses:number[]; recovery_verified:boolean; recorded_at:string; evidence:unknown; trace:unknown; error:string|null; diagnosis:{root_cause:string;proposed_fix:string}|null };
type Report = { agent_type:string; model:string|null; faults_verified:number; recoveries_verified:number; accuracy:number; runs:Run[]; sample_size:number; median_time_to_diagnosis_seconds:number; input_tokens:number|null; output_tokens:number|null; estimated_cost_usd:number|null };
const report = recorded as unknown as Report;

export function RecordedRuns() {
  return <section className="card detail-card" aria-labelledby="recorded-runs-title">
    <p className="eyebrow">RECORDED EXPERIMENTS</p>
    <h2 id="recorded-runs-title">Real faults, recorded evidence</h2>
    <p>Two local HTTP services were exercised with bad configuration, pool exhaustion, and a slow dependency. These are recorded observations, replayed without any live model calls.</p>
    <p className="warning">{report.agent_type === 'real_model' ? `Real LLM investigation: ${report.model}. Public quantized instruction model on CPU, without project-specific fine-tuning.` : 'Diagnostic method: deterministic rules baseline.'} This is a small controlled benchmark, not production accuracy.</p>
    <dl><dt>Faults verified / recovered</dt><dd>{report.faults_verified} / {report.recoveries_verified}</dd>
      <dt>Root cause and service accuracy</dt><dd>{(report.accuracy * 100).toFixed(1)}% ({report.runs.filter(r => r.correct).length}/{report.sample_size})</dd>
      <dt>Median time to diagnosis</dt><dd>{report.median_time_to_diagnosis_seconds.toFixed(3)} seconds</dd>
      <dt>Model tokens / API cost</dt><dd>{report.input_tokens !== null && report.output_tokens !== null ? (report.input_tokens + report.output_tokens).toLocaleString() : 'Unavailable'} / {report.estimated_cost_usd === null ? 'Unavailable' : `$${report.estimated_cost_usd.toFixed(2)}`} â€” hardware/electricity excluded</dd></dl>
    <p>Previous rules baseline on the same nine toy faults: 6/9 correct (66.7%), 45.3 ms median, no model tokens. These are different diagnostic methods.</p>
    <p>Failure audit: all nine predictions are pool_exhaustion. Only the three actual pool faults are correct: 33.3%, matching an always-pool baseline on these balanced fault types. This does not demonstrate useful root-cause discrimination. Each run reads gateway metrics once, then diagnoses; none reads logs, config, or the dependency. Bad-config evidence has request_limit: 0. A slow-dependency explanation claims 50 requests, but the recorded counter is 5. The rules baseline performs better (6/9 versus 3/9).</p>
    {report.runs.map(run => <details id={run.run_id} key={run.run_id} style={{margin:'12px 0'}}>
      <summary>{run.fault.replaceAll('_', ' ')} Â· {run.correct ? 'correct diagnosis' : 'incorrect diagnosis'} Â· {(run.time_to_diagnosis_seconds * 1000).toFixed(1)} ms</summary>
      <p>HTTP statuses: {run.http_statuses.join(', ')}. Healthy control passed; recovery {run.recovery_verified ? 'verified' : 'failed'}. No proposed fix executed.</p>
      <p>Diagnosed: {run.diagnosis?.root_cause ?? 'no diagnosis'} Â· {run.diagnosis?.proposed_fix} {run.error && `Run error: ${run.error}`}</p>
      <h3>Recorded evidence and tool trace</h3><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify({recorded_at:run.recorded_at,evidence:run.evidence,trace:run.trace},null,2)}</pre>
    </details>)}
    <a href="/recorded-runs.json" download>Download recorded results (JSON)</a>
  </section>;
}
