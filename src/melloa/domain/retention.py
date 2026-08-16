"""Owner-scoped retention and deletion evidence contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import (
    AwareDatetime,
    ContractModel,
    QualifiedName,
    RecordId,
    Sha256Digest,
)


class RetentionDeletionReceipt(ContractModel):
    """A content-free tombstone proving one retained object was deleted."""

    contract_version: Literal["1.0.0"] = "1.0.0"
    receipt_id: RecordId
    owner_id: RecordId
    object_id: RecordId
    object_type: QualifiedName
    content_hash: Sha256Digest
    size_bytes: Annotated[int, Field(ge=0)]
    retention_policy: QualifiedName
    retained_at: AwareDatetime
    expires_at: AwareDatetime
    deleted_at: AwareDatetime
    reason_code: QualifiedName

    @model_validator(mode="after")
    def validate_chronology(self) -> RetentionDeletionReceipt:
        if self.expires_at <= self.retained_at:
            raise ValueError("retention expiry must follow initial retention")
        if self.deleted_at < self.expires_at:
            raise ValueError("retention deletion cannot precede scheduled expiry")
        return self
