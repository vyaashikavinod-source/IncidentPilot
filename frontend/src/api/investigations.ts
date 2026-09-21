import { ApiClient } from "./client";

export type Investigation = {
  status: string;
  steps: Array<{ step_number: number; timestamp: string; current_hypothesis: string; observation: string; disposition: string; evidence_ids: string[] }>;
  diagnosis: Diagnosis | null;
  tool_call_count: number;
  turns: number;
  error: string | null;
  last_failure_at: string | null;
};
export type Diagnosis = { diagnosis_id: string; likely_root_cause: string; affected_service: string; failure_class: string; confidence: number; concise_explanation: string; investigation_summary: string; supporting_evidence_ids: string[]; contradicting_evidence_ids: string[]; remaining_uncertainties: string[] };
export const getInvestigation = (client: ApiClient, id: string) => client.get<Investigation>(`/v1/incidents/${encodeURIComponent(id)}/investigation`);