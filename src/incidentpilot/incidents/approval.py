import hashlib

from incidentpilot.incidents.audit import canonical
from incidentpilot.incidents.models import ApprovalRecord, RemediationProposal


def proposal_hash(proposal: RemediationProposal) -> str:
    payload = proposal.model_dump(mode="json", exclude={"proposal_hash", "status"})
    return hashlib.sha256(canonical(payload)).hexdigest()


def require_valid_approval(
    proposal: RemediationProposal, approvals: list[ApprovalRecord]
) -> ApprovalRecord:
    current_hash = proposal_hash(proposal)
    for approval in reversed(approvals):
        if (
            approval.proposal_id == proposal.proposal_id
            and approval.decision == "approved"
            and approval.proposal_hash == current_hash == proposal.proposal_hash
        ):
            return approval
    raise PermissionError("proposal has no valid hash-bound approval")
