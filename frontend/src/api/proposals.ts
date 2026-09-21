import { ApiClient } from "./client";
export type Proposal={proposal_id:string;version:number;proposal_hash:string;status:string;proposed_action_type:string;target_service:string;description:string;rationale:string;expected_effect:string;risk:string;rollback_plan:string;verification_plan:string};
export const getProposals=(client:ApiClient,id:string)=>client.get<Proposal[]>(`/v1/incidents/${id}/proposals`);
