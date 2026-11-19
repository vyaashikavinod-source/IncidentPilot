
import type { IncidentDetail } from './incidents';
import type { Proposal } from './proposals';

const scenarios = [
  ['gateway', 'Gateway latency after configuration rollout', 'critical', 'Connection pool limit reduced during a sample rollout.', 'Restore the previous connection pool configuration after operator review.'],
  ['worker', 'Background job queue growing', 'high', 'Worker concurrency is below the synthetic arrival rate.', 'Review worker capacity and test a bounded concurrency increase.'],
  ['auth', 'Authentication timeout spike', 'high', 'The simulated identity dependency is responding slowly.', 'Investigate the identity dependency and validate timeout settings.'],
  ['data', 'Database connection saturation', 'medium', 'A sample reporting query is holding connections longer than expected.', 'Review the sample query and apply a statement timeout after approval.'],
  ['gateway', 'Elevated upstream error rate', 'medium', 'A sample upstream health check is failing.', 'Inspect upstream health and compare with the last known healthy release.'],
  ['worker', 'Scheduled export delayed', 'low', 'A synthetic export is waiting behind a long-running job.', 'Review queue priorities for scheduled exports.'],
];
const incidents: IncidentDetail[] = scenarios.map(([service, title, severity, cause], i) => ({
  incident_id: 'demo-' + (i + 1).toString().padStart(3, '0'), title,
  severity: severity as IncidentDetail['severity'], source: 'synthetic-demo',
  status: 'proposal_ready', affected_service: service, affected_service_hint: service,
  description: 'SYNTHETIC DEMO: ' + cause + ' All evidence and diagnoses are simulated; no live systems are connected.',
  created_at: new Date(Date.UTC(2026, 10, 17, 9, i * 5)).toISOString(),
  updated_at: new Date(Date.UTC(2026, 10, 17, 10, i * 5)).toISOString(),
  evidence: {
    ['demo-metrics-' + i]: { source: 'simulated metrics', affected_service: service, latency_p95_ms: 820 + i * 70, baseline_p95_ms: 110, synthetic: true },
    ['demo-logs-' + i]: { source: 'simulated logs', message: cause, synthetic: true },
    ['demo-release-' + i]: { source: 'simulated deployment history', release: 'sample-v2', synthetic: true },
  },
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
  } else if (path === '/v1/memory' && method === 'GET') {
    result = scenarios.filter(s => !query.affected_service || s[0] === query.affected_service).slice(0, 1).map((s, i) => ({ score: 0.84, memory: { memory_id: 'sample-memory-' + i, incident_id: 'historical-demo', affected_service: s[0], failure_class: 'sample', root_cause_summary: 'SYNTHETIC historical analogy: ' + s[3], investigation_summary: 'Example of a similar symptom, not current proof.', remediation_proposal_summary: s[4], outcome: 'Simulated recovery', evidence_categories: ['metrics', 'logs'], confidence: 0.8, tags: ['synthetic'] } }));
  } else {
    const parts = path.split('/');
    const index = incidents.findIndex(item => item.incident_id === parts[3]);
    if (index < 0) throw new Error('Unknown demo incident');
    const incident = incidents[index], evidenceIds = Object.keys(incident.evidence ?? {});
    if (method === 'GET' && parts.length === 4) result = incident;
    else if (method === 'GET' && parts[4] === 'investigation') result = {
      status: 'completed', turns: 3, tool_call_count: 3, error: null, last_failure_at: null,
      steps: evidenceIds.map((id, step) => ({ step_number: step + 1, timestamp: incident.updated_at, current_hypothesis: 'Simulated investigation of ' + incident.affected_service, observation: ['Sample metrics exceed the synthetic baseline.', scenarios[index][3], 'Sample rollout timing matches the observed symptom.'][step], disposition: 'continue', evidence_ids: [id] })),
      diagnosis: { diagnosis_id: 'diagnosis-' + incident.incident_id, likely_root_cause: scenarios[index][3], affected_service: incident.affected_service, failure_class: 'synthetic-example', confidence: 0.86, concise_explanation: 'This is a prepared sample diagnosis, not live AI inference.', investigation_summary: 'Correlated synthetic metrics, logs and release history.', supporting_evidence_ids: evidenceIds, contradicting_evidence_ids: [], remaining_uncertainties: ['No live telemetry has been collected.', 'The sample hypothesis has not been verified on a real system.'] },
    };
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
