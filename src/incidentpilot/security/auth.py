import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    VIEWER = "viewer"
    INVESTIGATOR = "investigator"
    APPROVER = "approver"
    ADMIN = "admin"


class OperatorIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    subject: str = Field(min_length=1, max_length=200)
    roles: frozenset[Role] = Field(min_length=1)
    expires_at: datetime
    token_id: str = Field(min_length=8, max_length=100)
    issuer: str
    audience: str


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token(identity: OperatorIdentity, secret: str) -> str:
    payload = json.dumps(
        identity.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"ip1.{_encode(payload)}.{_encode(signature)}"


def verify_token(
    token: str, secret: str, issuer: str, audience: str, now: datetime | None = None
) -> OperatorIdentity:
    try:
        version, encoded, signature = token.split(".")
        payload = _decode(encoded)
        supplied = _decode(signature)
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        if version != "ip1" or not hmac.compare_digest(supplied, expected):
            raise ValueError("invalid signature")
        identity = OperatorIdentity.model_validate_json(payload)
    except Exception as exc:
        raise ValueError("invalid operator token") from exc
    current = now or datetime.now(UTC)
    if identity.expires_at <= current or identity.issuer != issuer or identity.audience != audience:
        raise ValueError("expired or incorrectly scoped operator token")
    return identity


class OperatorAuthenticator:
    def __init__(self, secret: str, issuer: str, audience: str) -> None:
        self.secret, self.issuer, self.audience = secret, issuer, audience

    def authenticate(
        self, authorization: Annotated[str | None, Header()] = None
    ) -> OperatorIdentity:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "valid operator bearer token required")
        try:
            return verify_token(
                authorization.removeprefix("Bearer "), self.secret, self.issuer, self.audience
            )
        except ValueError as exc:
            raise HTTPException(401, "valid operator bearer token required") from exc


def require_role(identity: OperatorIdentity, *allowed: Role) -> None:
    if Role.VIEWER in allowed and identity.roles:
        return
    if Role.ADMIN not in identity.roles and identity.roles.isdisjoint(allowed):
        raise HTTPException(403, "operator role is not authorized")
