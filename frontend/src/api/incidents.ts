import { ApiClient } from "./client";
export type Severity = "low" | "medium" | "high" | "critical";
export type IncidentStatus = "open" | "investigating" | "diagnosed" | "proposal_ready" | "approved" | "investigation_failed" | "closed";
export type IncidentSummary = { incident_id: string; title: string; source: string; severity: Severity; status: IncidentStatus; affected_service: string | null; created_at: string; updated_at: string };
export type IncidentList = { items: IncidentSummary[]; limit: number; offset: number; next_offset: number | null };
export type IncidentDetail = IncidentSummary & { description: string; affected_service_hint: string | null };
export type IncidentFilters = { status?: IncidentStatus; severity?: Severity; affected_service?: string; limit?: number; offset?: number };
export const listIncidents = (client: ApiClient, filters: IncidentFilters = {}) => client.get<IncidentList>("/v1/incidents", filters);
export const getIncident = (client: ApiClient, incidentId: string) => client.get<IncidentDetail>(`/v1/incidents/${encodeURIComponent(incidentId)}`);
