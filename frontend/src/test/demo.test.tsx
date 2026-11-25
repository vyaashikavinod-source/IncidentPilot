import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../main';
import { demoRequest } from '../api/demo';
import recorded from '../recorded-runs-v2.json';

beforeEach(() => {
  sessionStorage.clear();
  window.location.hash = '/login';
  vi.stubEnv('VITE_DEMO_MODE', 'true');
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Demo must not use a backend'));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllEnvs(); });

it('uses recorded incident IDs and actual evidence without backend calls', async () => {
  const list = await demoRequest<{items:{incident_id:string}[]}>('GET','/v1/incidents',{limit:20});
  expect(list.items.map(x=>x.incident_id)).toEqual(recorded.runs.map(x=>x.run_id));
  const id=recorded.runs[0].run_id;
  const detail = await demoRequest<{evidence:unknown}>('GET',`/v1/incidents/${id}`);
  expect(detail.evidence).toEqual(recorded.runs[0].evidence);
  const investigation = await demoRequest<{tool_call_count:number;diagnosis:{likely_root_cause:string;confidence:null}}>('GET',`/v1/incidents/${id}/investigation`);
  expect(investigation.tool_call_count).toBeGreaterThanOrEqual(6);
  expect(investigation.diagnosis.likely_root_cause).toBe(recorded.runs[0].diagnosis?.root_cause);
  expect(investigation.diagnosis.confidence).toBeNull();
  expect(globalThis.fetch).not.toHaveBeenCalled();
});
it('renders the measured failure audit and nine recorded incidents', async () => {
  render(<App />);
  fireEvent.click(screen.getByRole('button',{name:'Explore demo'}));
  expect(await screen.findByText('Recorded incidents')).toBeVisible();
  expect(screen.getByText(/all nine predictions are pool_exhaustion/)).toBeVisible();
  expect(screen.queryByText('Gateway latency after configuration rollout')).not.toBeInTheDocument();
});
