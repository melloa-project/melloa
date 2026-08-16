"""Append-oriented audit record contract with tamper-evident chaining."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from melloa.domain.base import (
    AwareDatetime,
    ContractModel,
    JsonObject,
    QualifiedName,
    RecordId,
    Sha256Digest,
    canonical_json_bytes,
    sha256_digest,
)


class AuditContent(ContractModel):
    audit_id: RecordId
    event_type: QualifiedName
    occurred_at: AwareDatetime
    actor_id: RecordId
    action: QualifiedName
    object_ids: tuple[RecordId, ...] = ()
    decision_id: RecordId | None = None
    run_id: RecordId | None = None
    metadata: JsonObject


def audit_record_hash(content: AuditContent, previous_hash: str | None) -> str:
    document = {
        "content": content.model_dump(mode="json"),
        "previous_hash": previous_hash,
    }
    return sha256_digest(canonical_json_bytes(document))


class AuditRecord(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    content: AuditContent
    previous_hash: Sha256Digest | None = None
    record_hash: Sha256Digest

    @model_validator(mode="after")
    def verify_record_hash(self) -> AuditRecord:
        expected = audit_record_hash(self.content, self.previous_hash)
        if self.record_hash != expected:
            raise ValueError("audit record hash does not match content and predecessor")
        return self
