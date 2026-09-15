import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audit_id: UUID = Field(default_factory=uuid4)
    sequence: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str = Field(min_length=1, max_length=100)
    incident_id: UUID
    actor: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AuditAppend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(min_length=1, max_length=100)
    actor: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


def make_record(
    *,
    sequence: int,
    event_type: str,
    incident_id: UUID,
    actor: str,
    metadata: dict[str, Any],
    previous_hash: str | None,
) -> AuditRecord:
    audit_id, timestamp = uuid4(), datetime.now(UTC)
    body = {
        "audit_id": audit_id,
        "sequence": sequence,
        "timestamp": timestamp,
        "event_type": event_type,
        "incident_id": str(incident_id),
        "actor": actor,
        "metadata": metadata,
        "previous_hash": previous_hash,
    }
    draft = AuditRecord(**body, record_hash="0" * 64)
    digest = hashlib.sha256(
        canonical(draft.model_dump(exclude={"record_hash"}, mode="json"))
    ).hexdigest()
    return draft.model_copy(update={"record_hash": digest})


def verify_chain(records: list[AuditRecord]) -> bool:
    previous: str | None = None
    for expected, record in enumerate(records, 1):
        body = record.model_dump(exclude={"record_hash"}, mode="json")
        if record.sequence != expected or record.previous_hash != previous:
            return False
        if hashlib.sha256(canonical(body)).hexdigest() != record.record_hash:
            return False
        previous = record.record_hash
    return True
