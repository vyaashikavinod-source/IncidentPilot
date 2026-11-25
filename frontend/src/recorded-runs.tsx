import { useState } from 'react';
import original from './recorded-runs.json';
import small from './recorded-runs-v2-small.json';
import latest from './recorded-runs-v2.json';
import large from './recorded-runs-v2-large.json';
import apiV2 from './recorded-runs-v2-gemini.json';

type Run = {run_id:string;fault:string;correct:boolean;time_to_diagnosis_seconds:number;http_statuses:number[];recovery_verified:boolean;recorded_at:string;evidence:Record<string,unknown>;trace:unknown;error:string|null;diagnosis:{root_cause:string;affected_service:string;explanation:string;proposed_fix:string}|null};
type Report = {known_input_tokens?:number;known_output_tokens?:number;model:string|null;faults_verified:number;recoveries_verified:number;accuracy:number;runs:Run[];sample_size:number;median_time_to_diagnosis_seconds:number;input_tokens:number|null;output_tokens:number|null;estimated_cost_usd:number|null};
const reports = { latest: latest as unknown as Report, small: small as unknown as Report, original: original as unknown as Report, large: large as unknown as Report, apiV2: apiV2 as unknown as Report };
export function RecordedRuns() {
  const [selected,setSelected]=useState<keyof typeof reports>('latest');
  const report=reports[selected];
  return <section className="card detail-card" aria-labelledby="recorded-runs-title">
    <p className="eyebrow">RECORDED EXPERIMENTS</p>
    <h2 id="recorded-runs-title">Real faults, recorded evidence</h2>
    <p>Two local HTTP services were exercised with bad configuration, pool exhaustion, and a slow dependency. Saved observations replay here without live model calls or executed fixes.</p>
    <div style={{overflowX:'auto'}}><table><thead><tr><th>Experiment</th><th>Correct</th><th>Evidence policy</th></tr></thead><tbody>
      <tr><td>Original Qwen2.5-1.5B</td><td>3/9</td><td>One gateway metrics read</td></tr>
      <tr><td>Qwen2.5-1.5B, broader evidence</td><td>{small.runs.filter(r=>r.correct).length}/9</td><td>Host gathers metrics, logs and config from both services</td></tr>
      <tr><td>Qwen2.5-3B, broader evidence</td><td>{large.runs.filter(r=>r.correct).length}/9</td><td>Same v2 evidence policy</td></tr>
      <tr><td>Gemini 3.5 Flash-Lite, v2</td><td>{apiV2.runs.filter(r=>r.correct).length}/9</td><td>Same v2 evidence policy; ambiguous cause definitions</td></tr>
      <tr><td>Latest taxonomy-clarified API run</td><td>{latest.runs.filter(r=>r.correct).length}/9</td><td>Same six initial reads; model can request more</td></tr>
      <tr><td>Original rules baseline</td><td>6/9</td><td>Deterministic diagnostic rules</td></tr>
    </tbody></table></div>
    <p className="warning">These nine-case diagnostic experiments are too small to establish general accuracy. Broader collection is host-enforced, not chosen by the model. No expected fault label or correctness feedback is supplied to it. More evidence does not guarantee correct interpretation.</p>
    <p>Original failure audit: all nine predictions are pool_exhaustion. Only three actual pool faults are correct, matching an always-pool baseline. The original model ignored request_limit: 0 and invented 50 requests when the counter was 5. Original records are preserved below.</p>
    <label>Recorded run set <select value={selected} onChange={e=>setSelected(e.target.value as keyof typeof reports)}>
      <option value="latest">Latest taxonomy-clarified API run</option><option value="large">3B broader-evidence run</option><option value="apiV2">Gemini broader-evidence v2 failure</option><option value="small">1.5B broader-evidence failure</option><option value="original">Original 1.5B baseline</option>
    </select></label>
    <p>Taxonomy v3 adds definitions distinguishing admission rejection, unavailable connection slots and upstream latency after examining v2 failures. It is an exploratory follow-up on the same nine toy templates, not independent validation or general production accuracy.</p>
    <p>Model: {report.model}. {report.model?.startsWith('gemini')?'Free Google API project; no paid fallback.':'Public quantized instruction model on local CPU.'} No incident-specific fine-tuning.</p>
    <dl><dt>Faults verified / recovered</dt><dd>{report.faults_verified} / {report.recoveries_verified}</dd>
      <dt>Root cause and service accuracy</dt><dd>{(report.accuracy*100).toFixed(1)}% ({report.runs.filter(r=>r.correct).length}/{report.sample_size})</dd>
      <dt>Median time to diagnosis</dt><dd>{report.median_time_to_diagnosis_seconds.toFixed(3)} seconds</dd>
      <dt>Model tokens / API charge</dt><dd>{report.input_tokens!==null&&report.output_tokens!==null?(report.input_tokens+report.output_tokens).toLocaleString():report.known_input_tokens!=null?`At least ${(report.known_input_tokens+(report.known_output_tokens??0)).toLocaleString()} known tokens; complete usage unavailable`:'Unavailable for complete run'} / {report.model?.startsWith('gemini')?'Free API project; actual charge $0':'Local CPU; hardware and electricity excluded'}</dd></dl>
    {report.runs.map(run=><details id={run.run_id} key={run.run_id} style={{margin:'12px 0'}}>
      <summary>{run.fault.replaceAll('_',' ')} · {run.correct?'correct diagnosis':run.diagnosis?'incorrect diagnosis':'no accepted diagnosis'} · {(run.time_to_diagnosis_seconds*1000).toFixed(1)} ms</summary>
      <p>HTTP statuses: {run.http_statuses.join(', ')}. Recovery {run.recovery_verified?'verified':'failed'}. No proposed fix executed.</p>
      <p>Diagnosed: {run.diagnosis?.root_cause??'none'} / {run.diagnosis?.affected_service??'none'}. {run.diagnosis?.explanation}</p>
      <p>Proposed fix (untrusted model output): {run.diagnosis?.proposed_fix??'none'}. {run.error&&`Run error: ${run.error}`}</p>
      <h3>Recorded evidence and tool trace</h3><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify({recorded_at:run.recorded_at,evidence:run.evidence,trace:run.trace},null,2)}</pre>
    </details>)}
    <a href={selected==='original'?'/recorded-runs.json':selected==='small'?'/recorded-runs-v2-small.json':selected==='large'?'/recorded-runs-v2-large.json':selected==='apiV2'?'/recorded-runs-v2-gemini.json':'/recorded-runs-v2.json'} download>Download selected results (JSON)</a>
  </section>;
}
