
import type { IncidentDetail } from './incidents';
import type { Proposal } from './proposals';

import recorded from '../recorded-runs.json';
const scenarios = recorded.runs.map(run => [run.expected_service, run.fault.replaceAll('_', ' '), 'high', run.diagnosis?.explanation ?? 'No diagnosis', run.diagnosis?.proposed_fix ?? 'No proposal']);
const incidents: IncidentDetail[] = recorded.runs.map(run => ({
  incident_id: run.run_id, title: run.fault.replaceAll('_', ' '), severity: 'high', source: 'recorded-real-fault',
  status: 'diagnosed', affected_service: run.expected_service, affected_service_hint: run.expected_service,
  description: `Recorded injected fault: ${run.fault}. Model diagnosis: ${run.diagnosis?.root_cause}. ${run.correct ? 'Correct' : 'Incorrect'} diagnosis. No remediation executed.`,
  created_at:run.recorded_at, updated_at:run.recorded_at, evidence:run.evidence,
}));
function proposal(index: number): Proposal {
  const id = incidents[index].incident_id;
  return { proposal_id: 'proposal-' + id, version: 1, proposal_hash: 'demo-only-' + id,
    status: sessionStorage.getItem('demo-decision-' + id) ?? 'proposed', proposed_action_type: 'review',
    target_service: scenarios[index][0], description: scenarios[index][4], rationale: scenarios[index][3],
    expected_effect: 'Demonstrate a review workflow only.', risk: 'Simulated. No infrastructure action occurs.',
    rollback_plan: 'No real changes are made.', verification_plan: 'Review the simulated evidence.' };
}
export async function demoRequest<T>(method: 'GET' | 'POST', path: string, query: Record<string, string | number | undefined> = {}, body?: unknown): Promise<T> {
  let result: unknown;
  if (path === '/v1/me' && method === 'GET') result = { token_id: 'public-demo-session', role: 'approver' };
  else if (path === '/v1/incidents' && method === 'GET') {
    const matching = incidents.filter(item => (!query.status || item.status === query.status) && (!query.severity || item.severity === query.severity) && (!query.affected_service || item.affected_service?.includes(String(query.affected_service))));
    const offset = Number(query.offset ?? 0), limit = Number(query.limit ?? 10);
    result = { items: matching.slice(offset, offset + limit), offset, limit, next_offset: offset + limit < matching.length ? offset + limit : null };
  } else if (path === '/v1/memory' && method === 'GET') { result = [];
  } else {
    const parts = path.split('/');
    const index = incidents.findIndex(item => item.incident_id === parts[3]);
    if (index < 0) throw new Error('Unknown demo incident');
    const incident = incidents[index], evidenceIds = Object.keys(incident.evidence ?? {});
    if (method === 'GET' && parts.length === 4) result = incident;
    else if (method === 'GET' && parts[4] === 'investigation') {
      const run = recorded.runs[index];
      result = {status:'completed', turns:run.trace.length, tool_call_count:Object.keys(run.evidence).length,error:run.error,last_failure_at:null,
        steps:run.trace.map((step,i)=>({step_number:i+1,timestamp:run.recorded_at,current_hypothesis:'Recorded model decision',observation:JSON.stringify(step.decision),disposition:'continue',evidence_ids:'evidence_id' in step ? [step.evidence_id]:[]})),
        diagnosis:{diagnosis_id:run.run_id,likely_root_cause:run.diagnosis?.root_cause,affected_service:run.expected_service,failure_class:run.fault,confidence:null,concise_explanation:run.diagnosis?.explanation,investigation_summary:'One gateway metrics read followed by diagnosis; no logs, config or dependency reads.',supporting_evidence_ids:evidenceIds,contradicting_evidence_ids:[],remaining_uncertainties:['Model predicted pool exhaustion in all nine runs; no evidence of diagnostic discrimination.']}};
    }
    else if (method === 'GET' && parts[4] === 'proposals') result = [proposal(index)];
    else if (method === 'POST' && parts[4] === 'proposals' && parts[5] === proposal(index).proposal_id && ['approve', 'reject'].includes(parts[6])) {
      const decision = body as { proposal_hash?: string; proposal_version?: number };
      if (decision.proposal_hash !== proposal(index).proposal_hash || decision.proposal_version !== 1 || proposal(index).status !== 'proposed') throw new Error('Demo proposal state changed');
      sessionStorage.setItem('demo-decision-' + incident.incident_id, parts[6] === 'approve' ? 'approved' : 'rejected');
      result = { status: 'recorded_in_browser_only', remediation_executed: false };
    } else throw new Error('Unsupported demo action');
  }
  return structuredClone(result) as T;
}
