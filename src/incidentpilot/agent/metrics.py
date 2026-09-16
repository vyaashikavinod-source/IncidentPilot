from prometheus_client import CollectorRegistry, Counter, Histogram


class AgentMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.investigations = Counter(
            "incidentpilot_agent_investigations_total",
            "Investigation outcomes",
            ["outcome"],
            registry=registry,
        )
        self.duration = Histogram(
            "incidentpilot_agent_investigation_duration_seconds",
            "Investigation duration",
            registry=registry,
        )
        self.evidence_calls = Counter(
            "incidentpilot_agent_evidence_calls_total",
            "Typed evidence calls",
            ["outcome"],
            registry=registry,
        )
        self.proposals = Counter(
            "incidentpilot_agent_proposals_total", "Proposals created", registry=registry
        )
        self.decisions = Counter(
            "incidentpilot_agent_proposal_decisions_total",
            "Proposal decisions",
            ["decision"],
            registry=registry,
        )
        self.llm_requests = Counter(
            "incidentpilot_agent_llm_requests_total",
            "LLM requests",
            ["outcome"],
            registry=registry,
        )
        self.security_events = Counter(
            "incidentpilot_agent_security_events_total",
            "Bounded security control events",
            ["event"],
            registry=registry,
        )
