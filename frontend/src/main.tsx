import { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";

import { ApiClient, ApiError } from "./api/client";
import { getIncident, listIncidents, type IncidentDetail, type IncidentFilters, type IncidentList, type IncidentSummary, type Severity } from "./api/incidents";
import { getSession, type Session } from "./api/session";
import { Workspace } from "./workspace";
import "./styles.css";

const sessionKey = "incidentpilot.operator-token";
const deploymentLabel =
  import.meta.env.VITE_DEPLOYMENT_LABEL ??
  (import.meta.env.PROD ? "PRODUCTION" : "LOCAL");
const formatTime = (value: string) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
const SeverityBadge = ({ severity }: { severity: Severity }) => <span className={`badge severity-${severity}`}>{severity}</span>;
const StatusBadge = ({ status }: { status: string }) => <span className="badge status">{status.replaceAll("_", " ")}</span>;
const Loading = ({ label = "Loading incident data…" }: { label?: string }) => <div className="state" role="status">{label}</div>;
const Empty = ({ label }: { label: string }) => <div className="state">{label}</div>;
const ErrorView = ({ error, retry }: { error: ApiError; retry: () => void }) => <div className="state error" role="alert"><p>{error.message}</p><button onClick={retry}>Retry</button></div>;

function IncidentTable({ items }: { items: IncidentSummary[] }) {
  return <div className="table-wrap"><table><thead><tr><th>Incident</th><th>Severity</th><th>Status</th><th>Source</th><th>Service</th><th>Created</th><th>Updated</th></tr></thead><tbody>{items.map((incident) => <tr key={incident.incident_id}><td><Link to={`/incidents/${incident.incident_id}`} className="incident-link">{incident.title}<code>{incident.incident_id}</code></Link></td><td><SeverityBadge severity={incident.severity} /></td><td><StatusBadge status={incident.status} /></td><td>{incident.source}</td><td>{incident.affected_service ?? "—"}</td><td>{formatTime(incident.created_at)}</td><td>{formatTime(incident.updated_at)}</td></tr>)}</tbody></table></div>;
}

function useList(client: ApiClient, filters: IncidentFilters) {
  const [data, setData] = useState<IncidentList>();
  const [error, setError] = useState<ApiError>();
  const reload = useCallback(() => { setData(undefined); setError(undefined); void listIncidents(client, filters).then(setData).catch((reason: ApiError) => setError(reason)); }, [client, filters]);
  useEffect(reload, [reload]);
  return { data, error, reload };
}

export function Login({ connect, message }: { connect: (value: string) => void; message: string }) {
  const [token, setToken] = useState("");
  return <main className="login-page"><section className="login-card"><p className="eyebrow">INCIDENT RESPONSE</p><h1>IncidentPilot</h1><h2>Operator Console</h2><p className="muted">Connect with an existing operator bearer token.</p>{message && <p className="login-error" role="alert">{message}</p>}<form onSubmit={(event) => { event.preventDefault(); if (token.trim()) connect(token.trim()); }}><label htmlFor="token">Bearer Token<input id="token" type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} /></label><button type="submit" disabled={!token.trim()}>Connect</button></form></section></main>;
}

export function Dashboard({ client, setConnected }: { client: ApiClient; setConnected: (value: boolean) => void }) {
  const filters = useMemo(() => ({ limit: 5, offset: 0 }), []);
  const { data, error, reload } = useList(client, filters);
  useEffect(() => { if (data) setConnected(true); if (error) setConnected(false); }, [data, error, setConnected]);
  return <section className="page"><div className="page-title"><div><p className="eyebrow">OPERATOR OVERVIEW</p><h1>Dashboard</h1><p className="muted">Recent persisted incidents from the visible API page.</p></div></div><div className="card"><div className="card-title"><h2>Recent incidents</h2>{data && <span>Visible incidents: {data.items.length}</span>}</div>{error ? <ErrorView error={error} retry={reload} /> : !data ? <Loading /> : data.items.length === 0 ? <Empty label="No incidents are available on this page." /> : <IncidentTable items={data.items} />}</div></section>;
}

export function Incidents({ client, setConnected }: { client: ApiClient; setConnected: (value: boolean) => void }) {
  const [filters, setFilters] = useState<IncidentFilters>({ limit: 10, offset: 0 });
  const { data, error, reload } = useList(client, filters);
  useEffect(() => { if (data) setConnected(true); if (error) setConnected(false); }, [data, error, setConnected]);
  const change = (name: "status" | "severity" | "affected_service", value: string) => setFilters((current) => ({ ...current, [name]: value || undefined, offset: 0 }));
  return <section className="page"><div className="page-title"><div><p className="eyebrow">INCIDENT QUEUE</p><h1>Incidents</h1><p className="muted">Server-side filtering and pagination.</p></div></div><div className="filter-bar"><label>Status<select aria-label="Status filter" value={filters.status ?? ""} onChange={(event) => change("status", event.target.value)}><option value="">All statuses</option>{["open", "investigating", "diagnosed", "proposal_ready", "approved", "investigation_failed", "closed"].map((value) => <option key={value}>{value}</option>)}</select></label><label>Severity<select aria-label="Severity filter" value={filters.severity ?? ""} onChange={(event) => change("severity", event.target.value)}><option value="">All severities</option>{["low", "medium", "high", "critical"].map((value) => <option key={value}>{value}</option>)}</select></label><label>Affected service<input aria-label="Affected service filter" value={filters.affected_service ?? ""} placeholder="e.g. gateway" onChange={(event) => change("affected_service", event.target.value)} /></label></div><div className="card">{error ? <ErrorView error={error} retry={reload} /> : !data ? <Loading /> : data.items.length === 0 ? <Empty label="No incidents match these filters." /> : <><IncidentTable items={data.items} /><div className="pagination"><span>Offset {data.offset}</span><div><button className="quiet" disabled={data.offset === 0} onClick={() => setFilters((current) => ({ ...current, offset: Math.max(0, (current.offset ?? 0) - (current.limit ?? 10)) }))}>Previous</button><button disabled={data.next_offset === null} onClick={() => setFilters((current) => ({ ...current, offset: data.next_offset ?? current.offset }))}>Next</button></div></div></>}</div></section>;
}

export function Detail({ client, setConnected, role }: { client: ApiClient; setConnected: (value: boolean) => void; role: Session["role"] | null }) {
  const { incidentId = "" } = useParams();
  const [incident, setIncident] = useState<IncidentDetail>();
  const [error, setError] = useState<ApiError>();
  const load = useCallback(() => { setIncident(undefined); setError(undefined); void getIncident(client, incidentId).then((value) => { setIncident(value); setConnected(true); }).catch((reason: ApiError) => { setError(reason); setConnected(false); }); }, [client, incidentId, setConnected]);
  useEffect(load, [load]);
  if (error) return <section className="page"><ErrorView error={error} retry={load} /></section>;
  if (!incident) return <section className="page"><Loading label="Loading incident…" /></section>;
  return <section className="page"><p className="eyebrow">INCIDENT OVERVIEW</p><div className="incident-header"><div><h1>{incident.title}</h1><code>{incident.incident_id}</code></div><div className="badges"><SeverityBadge severity={incident.severity} /><StatusBadge status={incident.status} /></div></div><Workspace client={client} incident={incident} role={role} /></section>;
}

function Shell({ children, connected, signOut, role }: { children: React.ReactNode; connected: boolean; signOut: () => void; role: string | null }) {
  return <div className="shell"><aside><Link className="brand" to="/dashboard">IncidentPilot<span>OPERATOR CONSOLE</span></Link><nav><Link to="/dashboard">Dashboard</Link><Link to="/incidents">Incidents</Link></nav></aside><main><header><span className={`connection ${connected ? "online" : "offline"}`}><i />API {connected ? "Connected" : "Unavailable"}</span>{role && <span className="role">{role}</span>}<span className="environment">{deploymentLabel}</span><button className="quiet" onClick={signOut}>Sign out</button></header>{children}</main></div>;
}

export function Console() {
  const navigate = useNavigate();
  const [token, setToken] = useState(() => sessionStorage.getItem(sessionKey) ?? "");
  const [message, setMessage] = useState("");
  const [connected, setConnected] = useState(false);
  const [identity, setIdentity] = useState<Session | null>(null);
  const signOut = useCallback((reason = "") => { sessionStorage.removeItem(sessionKey); setToken(""); setIdentity(null); setConnected(false); setMessage(reason); navigate("/login"); }, [navigate]);
  const client = useMemo(() => new ApiClient(token, () => signOut("Session expired or invalid")), [signOut, token]);
  useEffect(() => { if (!token) return; void getSession(client).then((value) => { setIdentity(value); setConnected(true); }).catch((reason: ApiError) => { if (reason.code === "forbidden") setMessage(reason.message); }); }, [client, token]);
  const connect = (value: string) => { sessionStorage.setItem(sessionKey, value); setMessage(""); setToken(value); navigate("/dashboard"); };
  if (!token) return <Routes><Route path="/login" element={<Login connect={connect} message={message} />} /><Route path="*" element={<Navigate to="/login" replace />} /></Routes>;
  return <Shell connected={connected} signOut={() => signOut()} role={identity?.role ?? null}><Routes><Route path="/dashboard" element={<Dashboard client={client} setConnected={setConnected} />} /><Route path="/incidents" element={<Incidents client={client} setConnected={setConnected} />} /><Route path="/incidents/:incidentId" element={<Detail client={client} setConnected={setConnected} role={identity?.role ?? null} />} /><Route path="*" element={<Navigate to="/dashboard" replace />} /></Routes></Shell>;
}

export function App() { return <BrowserRouter><Console /></BrowserRouter>; }
if (import.meta.env.MODE !== "test") createRoot(document.getElementById("root")!).render(<App />);
