import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../main";
const summary = { incident_id: "11111111-1111-1111-1111-111111111111", title: "Gateway timeout", source: "monitor", severity: "high", status: "open", affected_service: "gateway", created_at: "2026-09-16T12:00:00Z", updated_at: "2026-09-16T12:01:00Z" } as const;
const list = { items: [summary], limit: 10, offset: 0, next_offset: 10 };
const detail = { ...summary, description: "Requests exceeded the latency threshold.", affected_service_hint: "gateway" };
function mockApi(responses: Array<{ status?: number; body?: unknown }>) { vi.spyOn(globalThis, "fetch").mockImplementation(async () => { const response = responses.shift() ?? { body: list }; return new Response(JSON.stringify(response.body ?? {}), { status: response.status ?? 200 }); }); }
function login() { fireEvent.change(screen.getByLabelText("Bearer Token"), { target: { value: "test-token" } }); fireEvent.click(screen.getByRole("button", { name: "Connect" })); }
describe("operator console routes", () => {
  beforeEach(() => { sessionStorage.clear(); localStorage.clear(); window.history.pushState({}, "", "/login"); }); afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  it("redirects protected routes to the masked token login", () => { window.history.pushState({}, "", "/incidents"); render(<App/>); expect(screen.getByLabelText("Bearer Token")).toHaveAttribute("type", "password"); });
  it("renders dashboard incidents after an authenticated session", async () => { mockApi([{ body: list }]); render(<App/>); login(); expect(await screen.findByText("Gateway timeout")).toBeVisible(); expect(screen.getByText("Visible incidents: 1")).toBeVisible(); expect(localStorage.length).toBe(0); });
  it("shows loading and empty dashboard states", async () => { let resolve!: (value: Response) => void; vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise<Response>((done) => { resolve = done; })); render(<App/>); login(); expect(screen.getByRole("status")).toHaveTextContent("Loading incident data"); resolve(new Response(JSON.stringify({ ...list, items: [] }), { status: 200 })); expect(await screen.findByText("No incidents are available on this page.")).toBeVisible(); });
  it("clears session and returns to login on 401", async () => { mockApi([{ status: 401 }]); render(<App/>); login(); expect(await screen.findByText("Session expired or invalid")).toBeVisible(); expect(sessionStorage.getItem("incidentpilot.operator-token")).toBeNull(); });
  it("keeps the session and shows insufficient permissions on 403", async () => { mockApi([{ status: 403 }]); render(<App/>); login(); expect(await screen.findByText("Insufficient permissions")).toBeVisible(); expect(sessionStorage.getItem("incidentpilot.operator-token")).toBe("test-token"); });
  it("renders incidents, sends filters, and paginates", async () => { mockApi([{ body: list }, { body: list }, { body: list }, { body: list }, { body: { ...list, offset: 10, next_offset: null } }]); window.history.pushState({}, "", "/incidents"); sessionStorage.setItem("incidentpilot.operator-token", "test-token"); render(<App/>); expect(await screen.findByText("Gateway timeout")).toBeVisible(); fireEvent.change(screen.getByLabelText("Status filter"), { target: { value: "open" } }); await waitFor(() => expect(vi.mocked(globalThis.fetch).mock.calls.length).toBeGreaterThan(1)); fireEvent.change(screen.getByLabelText("Severity filter"), { target: { value: "high" } }); fireEvent.change(screen.getByLabelText("Affected service filter"), { target: { value: "gateway" } }); await waitFor(() => expect(vi.mocked(globalThis.fetch).mock.calls.length).toBeGreaterThan(3)); fireEvent.click(screen.getByRole("button", { name: "Next" })); await waitFor(() => expect(screen.getByText("Offset 10")).toBeVisible()); const calls = vi.mocked(globalThis.fetch).mock.calls.map((call) => String(call[0])); expect(calls.some((url) => url.includes("status=open"))).toBe(true); expect(calls.some((url) => url.includes("severity=high"))).toBe(true); expect(calls.some((url) => url.includes("affected_service=gateway"))).toBe(true); fireEvent.click(screen.getByRole("button", { name: "Previous" })); });
  it("shows real detail fields without fabricated sections or execution", async () => { mockApi([{ body: detail }]); window.history.pushState({}, "", `/incidents/${summary.incident_id}`); sessionStorage.setItem("incidentpilot.operator-token", "test-token"); render(<App/>); expect(await screen.findByText("Requests exceeded the latency threshold.")).toBeVisible(); expect(screen.queryByRole("button", { name: /execute/i })).not.toBeInTheDocument(); });
  it("shows a safe not-found detail error", async () => { mockApi([{ status: 404 }]); window.history.pushState({}, "", `/incidents/${summary.incident_id}`); sessionStorage.setItem("incidentpilot.operator-token", "test-token"); render(<App/>); expect(await screen.findByText("The requested incident was not found")).toBeVisible(); });
});

const investigation = {
  status: "diagnosed", turns: 2, tool_call_count: 3, error: null, last_failure_at: null,
  steps: [{ step_number: 1, timestamp: "2026-09-16T12:00:00Z", current_hypothesis: "Gateway latency is elevated", observation: "Current metrics show latency", disposition: "supported", evidence_ids: ["evidence-current-1"] }],
  diagnosis: { diagnosis_id: "diagnosis-1", likely_root_cause: "Gateway saturation", affected_service: "gateway", failure_class: "latency", confidence: 0.8, concise_explanation: "A current latency signal supports saturation.", investigation_summary: "Structured investigation summary.", supporting_evidence_ids: ["evidence-current-1"], contradicting_evidence_ids: [], remaining_uncertainties: ["Confirm load distribution"] },
};
const proposal = { proposal_id: "proposal-1", version: 2, proposal_hash: "a".repeat(64), status: "proposed", proposed_action_type: "investigate_manually", target_service: "gateway", description: "Inspect gateway capacity", rationale: "Current evidence supports review", expected_effect: "Clarify capacity", risk: "No execution occurs", rollback_plan: "Not applicable", verification_plan: "Review current metrics" };
const memory = [{ memory: { memory_id: "memory-1", incident_id: summary.incident_id, affected_service: "gateway", failure_class: "latency", root_cause_summary: "Earlier gateway saturation", investigation_summary: "Historical record", remediation_proposal_summary: "Manual review", outcome: "resolved", evidence_categories: ["metrics"], confidence: 0.7, tags: ["gateway"] }, score: 7 }];
function mockWorkspaceApi(role: "viewer" | "approver") {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = input.toString();
    if (url.includes("/v1/me")) return new Response(JSON.stringify({ token_id: "safe-token-id", role }), { status: 200 });
    if (url.includes("/investigation")) return new Response(JSON.stringify(investigation), { status: 200 });
    if (url.includes("/proposals")) return new Response(JSON.stringify([proposal]), { status: 200 });
    if (url.includes("memory")) return new Response(JSON.stringify(memory), { status: 200 });
    if (url.includes(`/v1/incidents/${summary.incident_id}`)) return new Response(JSON.stringify({ ...detail, evidence: { "evidence-current-1": { source: "metrics" } } }), { status: 200 });
    if ((init as RequestInit | undefined)?.method === "POST") return new Response(JSON.stringify({}), { status: 200 });
    return new Response(JSON.stringify(list), { status: 200 });
  });
}
describe("incident workspace safety", () => {
  beforeEach(() => { sessionStorage.clear(); window.history.pushState({}, "", `/incidents/${summary.incident_id}`); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  it("loads the backend viewer role and keeps proposals read-only", async () => {
    mockWorkspaceApi("viewer"); sessionStorage.setItem("incidentpilot.operator-token", "test-token"); render(<App />);
    expect(await screen.findByText("viewer")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Proposal" }));
    expect(await screen.findByText("Viewer access is read-only.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute/i })).not.toBeInTheDocument();
  });
  it("renders persisted investigation, evidence, historical memory, and diagnosis without execution", async () => {
    mockWorkspaceApi("viewer"); sessionStorage.setItem("incidentpilot.operator-token", "test-token"); render(<App />);
    await screen.findByText("Gateway timeout");
    fireEvent.click(screen.getByRole("button", { name: "Investigation" }));
    expect(await screen.findByText("Disposition: supported")).toBeVisible(); expect(screen.getByText("evidence-current-1")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Evidence" })); expect(await screen.findByText("Current evidence")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Historical Memory" })); expect(await screen.findByText("Historical analogy — not current proof")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Diagnosis" })); expect(await screen.findByText("Remaining uncertainty")).toBeVisible();
    expect(screen.queryByText(/chain.of.thought/i)).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: /execute/i })).not.toBeInTheDocument();
  });
  it("shows approver confirmation and sends a decision without execution", async () => {
    mockWorkspaceApi("approver"); sessionStorage.setItem("incidentpilot.operator-token", "test-token"); render(<App />);
    await screen.findByText("approver"); fireEvent.click(screen.getByRole("button", { name: "Proposal" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" })); expect(await screen.findByRole("dialog")).toHaveTextContent("This records a human decision only");
    fireEvent.click(screen.getByRole("button", { name: "Confirm approve" }));
    await waitFor(() => expect(vi.mocked(globalThis.fetch).mock.calls.some(([input, init]) => String(input).includes("/approve") && (init as RequestInit).method === "POST")).toBe(true));
    expect(vi.mocked(globalThis.fetch).mock.calls.some(([input]) => /execute|restart|docker|shell/i.test(String(input)))).toBe(false);
  });
});
