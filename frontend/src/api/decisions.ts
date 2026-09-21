import { ApiClient } from "./client";
import { Proposal } from "./proposals";
export const decideProposal=(client:ApiClient,incidentId:string,proposal:Proposal,decision:"approve"|"reject")=>client.post(`/v1/incidents/${incidentId}/proposals/${proposal.proposal_id}/${decision}`,{proposal_hash:proposal.proposal_hash,proposal_version:proposal.version,request_id:crypto.randomUUID()});
