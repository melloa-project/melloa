"""Read-only Guardian protocol consumed by the autonomous plane."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import (
    AwareDatetime,
    ContractModel,
    QualifiedName,
    Sha256Digest,
)

Base64Url = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$")]


class GuardianMode(StrEnum):
    NORMAL = "normal"
    NO_ACTIONS = "no-actions"
    READ_ONLY = "read-only"
    OFFLINE = "offline"
    STOPPED = "stopped"
    RECOVERY = "recovery"


class GuardianStatusPayload(ContractModel):
    protocol_version: Literal["1.0.0"] = "1.0.0"
    instance_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")]
    mode: GuardianMode
    sequence: Annotated[int, Field(ge=1)]
    changed_at: AwareDatetime
    reason_code: QualifiedName
    previous_receipt_hash: Sha256Digest | None = None

    @model_validator(mode="after")
    def require_chain_after_genesis(self) -> GuardianStatusPayload:
        if self.sequence == 1 and self.previous_receipt_hash is not None:
            raise ValueError("the first Guardian receipt cannot have a predecessor")
        if self.sequence > 1 and self.previous_receipt_hash is None:
            raise ValueError("later Guardian receipts require a predecessor hash")
        return self


class SignedGuardianStatus(ContractModel):
    envelope_version: Literal["1.0.0"] = "1.0.0"
    algorithm: Literal["Ed25519"] = "Ed25519"
    key_id: QualifiedName
    payload: Base64Url
    signature: Base64Url


class VerifiedGuardianStatus(ContractModel):
    payload: GuardianStatusPayload
    receipt_hash: Sha256Digest
    key_id: QualifiedName
