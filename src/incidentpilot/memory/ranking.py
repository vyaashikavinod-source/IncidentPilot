from datetime import UTC, datetime

from incidentpilot.memory.models import IncidentMemory, MemoryQuery, MemorySearchResult


def rank_memory(items: list[IncidentMemory], query: MemoryQuery) -> list[MemorySearchResult]:
    """Deterministic, explainable ranking with recency as a stable tie-breaker."""
    now = datetime.now(UTC)

    def score(item: IncidentMemory) -> int:
        value = 0
        if query.affected_service and item.affected_service == query.affected_service:
            value += 8
        if query.failure_class and item.failure_class == query.failure_class:
            value += 6
        value += 2 * len(set(query.tags).intersection(item.tags))
        if (now - item.created_at).days <= 30:
            value += 1
        return value

    ranked = [MemorySearchResult(memory=item, score=score(item)) for item in items]
    return sorted(
        ranked, key=lambda item: (-item.score, item.memory.created_at, str(item.memory.memory_id))
    )[: query.limit]
