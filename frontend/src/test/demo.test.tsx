import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { App } from '../main';
import { demoRequest } from '../api/demo';

beforeEach(() => {
  sessionStorage.clear();
  window.location.hash = '/login';
  vi.stubEnv('VITE_DEMO_MODE', 'true');
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Demo must not use a backend'));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllEnvs(); });

it('opens the sample workspace and records a local decision without network calls', async () => {
  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Explore demo' }));
  fireEvent.click(await screen.findByText('Gateway latency after configuration rollout'));
  fireEvent.click(await screen.findByRole('button', { name: 'Evidence' }));
  expect(await screen.findByText(/simulated metrics/)).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Diagnosis' }));
  expect(await screen.findByText('This is a prepared sample diagnosis, not live AI inference.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Proposal' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm approve' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(screen.getByText('approved')).toBeVisible();
  expect(sessionStorage.getItem('demo-decision-demo-001')).toBe('approved');
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it('filters, paginates, and isolates sample decisions to the browser session', async () => {
  const first = await demoRequest<{items: {incident_id: string}[]; next_offset: number}>('GET', '/v1/incidents', {limit: 5});
  expect(first.items).toHaveLength(5);
  expect(first.next_offset).toBe(5);
  const next = await demoRequest<{items: unknown[]; next_offset: null}>('GET', '/v1/incidents', {limit: 5, offset: 5});
  expect(next.items).toHaveLength(1);
  expect(next.next_offset).toBeNull();
  const filtered = await demoRequest<{items: {severity: string}[]}>('GET', '/v1/incidents', {severity: 'critical'});
  expect(filtered.items).toHaveLength(1);
  expect(filtered.items[0].severity).toBe('critical');
  sessionStorage.setItem('demo-decision-demo-001', 'rejected');
  sessionStorage.clear();
  const proposals = await demoRequest<{status: string}[]>('GET', '/v1/incidents/demo-001/proposals');
  expect(proposals[0].status).toBe('proposed');
});
