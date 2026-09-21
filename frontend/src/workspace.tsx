import { useEffect, useState } from "react";

import { ApiClient, ApiError } from "./api/client";
import { decideProposal } from "./api/decisions";
import type { IncidentDetail } from "./api/incidents";
import { getInvestigation, type Investigation } from "./api/investigations";
import { searchMemory, type Memory } from "./api/memory";
import { getProposals, type Proposal } from "./api/proposals";
import type { Session } from "./api/session";

type Tab = "Overview" | "Investigation" | "Evidence" | "Historical Memory" | "Diagnosis" | "Proposal";
type Decision = "approve" | "reject";

const tabs: Tab[] = ["Overview", "Investigation", "Evidence", "Historical Memory", "Diagnosis", "Proposal"];

function Failure({ error }: { error: ApiError | null }) {
  return error ? <p className="error" role="alert">{error.message}</p> : null;
}

export function Workspace({ client, incident, role }: { client: ApiClient; incident: IncidentDetail; role: Session["role"] | null }) {
  const [tab, setTab] = useState<Tab>("Overview");
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [memory, setMemory] = useState<Memory[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirm, setConfirm] = useState<{ proposal: Proposal; decision: Decision } | null>(null);

  useEffect(() => {
    setInvestigation(null); setProposals(null); setMemory(null); setError(null);
    void Promise.all([
      getInvestigation(client, incident.incident_id),
      getProposals(client, incident.incident_id),
      searchMemory(client, incident.affected_service ?? undefined),
    ]).then(([loadedInvestigation, loadedProposals, loadedMemory]) => {
      setInvestigation(loadedInvestigation); setProposals(loadedProposals); setMemory(loadedMemory);
    }).catch((reason: ApiError) => setError(reason));
  }, [client, incident.affected_service, incident.incident_id]);

  const submitDecision = () => {
    if (!confirm) return;
    void decideProposal(client, incident.incident_id, confirm.proposal, confirm.decision)
      .then(() => getProposals(client, incident.incident_id))
      .then((updated) => { setProposals(updated); setConfirm(null); })
      .catch((reason: ApiError) => setError(reason));
  };

  return <>
    <div className="tabs" aria-label="Incident workspace">{tabs.map((item) => <button className={tab === item ? "active" : "quiet"} onClick={() => setTab(item)} key={item}>{item}</button>)}</div>
    <Failure error={error} />
    {tab === "Overview" && <article className="card detail-card"><h2>Overview</h2><p>{incident.description}</p></article>}
    {tab === "Investigation" && <InvestigationPanel investigation={investigation} />}
    {tab === "Evidence" && <EvidencePanel incident={incident} />}
    {tab === "Historical Memory" && <MemoryPanel memory={memory} />}
    {tab === "Diagnosis" && <DiagnosisPanel investigation={investigation} />}
    {tab === "Proposal" && <ProposalPanel proposals={proposals} role={role} onDecide={(proposal, decision) => setConfirm({ proposal, decision })} />}
    {confirm && <section className="modal-backdrop" role="presentation"><div className="card detail-card" role="dialog" aria-modal="true" aria-labelledby="decision-title"><h2 id="decision-title">Confirm {confirm.decision}</h2><dl><dt>Proposal ID</dt><dd><code>{confirm.proposal.proposal_id}</code></dd><dt>Version</dt><dd>{confirm.proposal.version}</dd><dt>Proposal hash</dt><dd><code>{confirm.proposal.proposal_hash}</code></dd><dt>Action</dt><dd>{confirm.proposal.description}</dd></dl><p className="warning">APPROVAL DOES NOT EXECUTE REMEDIATION</p><p>This records a human decision only. IncidentPilot does not execute remediation.</p><button onClick={submitDecision}>Confirm {confirm.decision}</button><button className="quiet" onClick={() => setConfirm(null)}>Cancel</button></div></section>}
  </>;
}

function InvestigationPanel({ investigation }: { investigation: Investigation | null }) {
  if (!investigation) return <p role="status">Loading investigation…</p>;
  if (!investigation.steps.length) return <section><h2>Investigation</h2><p>No persisted investigation steps are available.</p></section>;
  return <section><h2>Investigation</h2><p>Status: {investigation.status} · Turns: {investigation.turns} · Tool calls: {investigation.tool_call_count}</p>{investigation.steps.map((step) => <article className="card detail-card" key={step.step_number}><p><strong>Disposition: {step.disposition}</strong></p><p>{step.current_hypothesis}</p><p>{step.observation}</p><p>Evidence IDs</p><code>{step.evidence_ids.join(", ") || "None"}</code></article>)}</section>;
}

function EvidencePanel({ incident }: { incident: IncidentDetail }) {
  const evidence = incident.evidence ?? {};
  const entries = Object.entries(evidence);
  return <section><h2>Current evidence</h2>{entries.length === 0 ? <p>No current evidence is available.</p> : entries.map(([id, value]) => <article className="card detail-card" key={id}><code>{id}</code><pre>{JSON.stringify(value, null, 2)}</pre></article>)}</section>;
}

function MemoryPanel({ memory }: { memory: Memory[] | null }) {
  if (!memory) return <p role="status">Loading historical memory…</p>;
  if (!memory.length) return <section><h2>Historical Memory</h2><strong>Historical analogy — not current proof</strong><p>No historical memory is available.</p></section>;
  return <section><h2>Historical Memory</h2>{memory.map((item) => <article className="card detail-card" key={item.memory.memory_id}><strong>Historical analogy — not current proof</strong><p>{item.memory.root_cause_summary}</p><p>Similarity score: {item.score}</p><code>{item.memory.memory_id}</code></article>)}</section>;
}

function DiagnosisPanel({ investigation }: { investigation: Investigation | null }) {
  if (!investigation) return <p role="status">Loading diagnosis…</p>;
  const diagnosis = investigation.diagnosis;
  if (!diagnosis) return <section><h2>Diagnosis</h2><p>No diagnosis is available.</p></section>;
  return <section><h2>Diagnosis</h2><article className="card detail-card"><p>{diagnosis.likely_root_cause}</p><p>{diagnosis.concise_explanation}</p><p>Confidence: {diagnosis.confidence}</p><p>Supporting evidence IDs</p><code>{diagnosis.supporting_evidence_ids.join(", ")}</code><p>Remaining uncertainty</p><ul>{diagnosis.remaining_uncertainties.map((uncertainty) => <li key={uncertainty}>{uncertainty}</li>)}</ul></article></section>;
}

function ProposalPanel({ proposals, role, onDecide }: { proposals: Proposal[] | null; role: Session["role"] | null; onDecide: (proposal: Proposal, decision: Decision) => void }) {
  if (!proposals) return <p role="status">Loading proposals…</p>;
  return <section><h2>Remediation Proposal</h2><p className="warning">APPROVAL DOES NOT EXECUTE REMEDIATION</p><p>This records a human decision only. IncidentPilot does not execute remediation.</p>{proposals.length === 0 ? <p>No proposal is available.</p> : proposals.map((proposal) => <article className="card detail-card" key={proposal.proposal_id}><dl><dt>Proposal ID</dt><dd><code>{proposal.proposal_id}</code></dd><dt>Version</dt><dd>{proposal.version}</dd><dt>Proposal hash</dt><dd><code>{proposal.proposal_hash}</code></dd><dt>Status</dt><dd>{proposal.status}</dd></dl><p>{proposal.description}</p><p>Risk: {proposal.risk}</p>{role === "approver" && proposal.status === "proposed" && <div className="decision-actions"><button onClick={() => onDecide(proposal, "approve")}>Approve</button><button className="quiet" onClick={() => onDecide(proposal, "reject")}>Reject</button></div>}{role === "viewer" && proposal.status === "proposed" && <p className="muted">Viewer access is read-only.</p>}</article>)}</section>;
}