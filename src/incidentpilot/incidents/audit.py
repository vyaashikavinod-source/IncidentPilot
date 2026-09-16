import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

GENESIS_HASH = "0" * 64
CHAIN_VERSION = 2
CANONICALIZATION_VERSION = "incidentpilot-canonical-json-v1"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audit_id: UUID = Field(default_factory=uuid4)
    chain_version: int = CHAIN_VERSION
    canonicalization_version: str = CANONICALIZATION_VERSION
    sequence: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str = Field(min_length=1, max_length=100)
    incident_id: UUID
    actor: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AuditAppend(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(min_length=1, max_length=100)
    actor: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChainVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid: bool
    records: int = Field(ge=0)
    failure_sequence: int | None = None
    reason: str | None = None


class AuditCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_version: int = 1
    incident_id: UUID
    last_sequence: int = Field(ge=1)
    last_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_timestamp: datetime
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


def make_record(
    *,
    sequence: int,
    event_type: str,
    incident_id: UUID,
    actor: str,
    metadata: dict[str, Any],
    previous_hash: str | None,
) -> AuditRecord:
    if sequence == 1 and previous_hash is None:
        previous_hash = GENESIS_HASH
    draft = AuditRecord(
        audit_id=uuid4(),
        sequence=sequence,
        timestamp=datetime.now(UTC),
        event_type=event_type,
        incident_id=incident_id,
        actor=actor,
        metadata=metadata,
        previous_hash=previous_hash,
        record_hash="0" * 64,
    )
    digest = hashlib.sha256(
        canonical(draft.model_dump(exclude={"record_hash"}, mode="json"))
    ).hexdigest()
    return draft.model_copy(update={"record_hash": digest})


def verify_chain_report(records: list[AuditRecord]) -> ChainVerification:
    previous: str | None = None
    for expected, record in enumerate(records, 1):
        if record.chain_version not in {1, CHAIN_VERSION}:
            return ChainVerification(
                valid=False,
                records=len(records),
                failure_sequence=expected,
                reason="unsupported_chain_version",
            )
        if record.chain_version == 1:
            body = record.model_dump(
                exclude={"record_hash", "chain_version", "canonicalization_version"}, mode="json"
            )
        else:
            body = record.model_dump(exclude={"record_hash"}, mode="json")
        if record.chain_version == CHAIN_VERSION and (
            record.canonicalization_version != CANONICALIZATION_VERSION
        ):
            return ChainVerification(
                valid=False,
                records=len(records),
                failure_sequence=expected,
                reason="unsupported_canonicalization_version",
            )
        if record.sequence != expected:
            return ChainVerification(
                valid=False,
                records=len(records),
                failure_sequence=expected,
                reason="sequence_discontinuity",
            )
        expected_previous = (
            GENESIS_HASH if expected == 1 and record.chain_version == 2 else previous
        )
        if record.previous_hash != expected_previous:
            return ChainVerification(
                valid=False,
                records=len(records),
                failure_sequence=expected,
                reason="broken_previous_hash",
            )
        if hashlib.sha256(canonical(body)).hexdigest() != record.record_hash:
            return ChainVerification(
                valid=False,
                records=len(records),
                failure_sequence=expected,
                reason="incorrect_record_hash",
            )
        previous = record.record_hash
    return ChainVerification(valid=True, records=len(records))


def verify_chain(records: list[AuditRecord]) -> bool:
    return verify_chain_report(records).valid


def create_checkpoint(records: list[AuditRecord], secret: str) -> AuditCheckpoint:
    if not verify_chain(records) or not records:
        raise ValueError("cannot checkpoint an empty or invalid audit chain")
    last = records[-1]
    draft = AuditCheckpoint(
        incident_id=last.incident_id,
        last_sequence=last.sequence,
        last_record_hash=last.record_hash,
        checkpoint_timestamp=datetime.now(UTC),
        signature="0" * 64,
    )
    signature = hmac.new(
        secret.encode(),
        canonical(draft.model_dump(exclude={"signature"}, mode="json")),
        hashlib.sha256,
    ).hexdigest()
    return draft.model_copy(update={"signature": signature})


def verify_checkpoint(checkpoint: AuditCheckpoint, records: list[AuditRecord], secret: str) -> bool:
    if not verify_chain(records) or not records:
        return False
    last = records[-1]
    expected = hmac.new(
        secret.encode(),
        canonical(checkpoint.model_dump(exclude={"signature"}, mode="json")),
        hashlib.sha256,
    ).hexdigest()
    return (
        checkpoint.checkpoint_version == 1
        and checkpoint.incident_id == last.incident_id
        and checkpoint.last_sequence == last.sequence
        and checkpoint.last_record_hash == last.record_hash
        and hmac.compare_digest(checkpoint.signature, expected)
    )
