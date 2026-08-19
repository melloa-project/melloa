"""Canonical event envelope and evidence contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import (
    AwareDatetime,
    ContractModel,
    JsonObject,
    NonEmptyText,
    QualifiedName,
    RecordId,
    SemanticVersion,
    Sha256Digest,
    canonical_json_bytes,
    sha256_digest,
)
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class EventSource(ContractModel):
    capability_id: QualifiedName
    observation_ids: tuple[RecordId, ...] = ()
    execution_id: RecordId | None = None


class EventProducer(ContractModel):
    component: QualifiedName
    version: SemanticVersion
    model_id: str | None = Field(default=None, min_length=1, max_length=256)
    prompt_version: str | None = Field(default=None, min_length=1, max_length=128)
    configuration_version: str | None = Field(default=None, min_length=1, max_length=128)


class EventAlternative(ContractModel):
    claim: NonEmptyText
    confidence: Confidence


class EvidenceReference(ContractModel):
    blob_hash: Sha256Digest
    media_type: Annotated[str, Field(pattern=r"^[a-z0-9.+-]+/[a-z0-9.+-]+$")]
    expires_at: AwareDatetime | None = None


class EventIntegrity(ContractModel):
    payload_hash: Sha256Digest


class EventEnvelope(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    event_id: RecordId
    event_type: QualifiedName
    schema_version: SemanticVersion
    occurred_at: AwareDatetime
    recorded_at: AwareDatetime
    subject_ids: tuple[RecordId, ...] = ()
    source: EventSource
    producer: EventProducer
    epistemic_status: EpistemicStatus
    confidence: Confidence | None = None
    alternatives: tuple[EventAlternative, ...] = ()
    sensitivity: Sensitivity
    trust: TrustLabel
    retention_policy: QualifiedName
    correlation_id: RecordId | None = None
    causation_id: RecordId | None = None
    payload: JsonObject
    evidence: tuple[EvidenceReference, ...] = ()
    integrity: EventIntegrity

    @model_validator(mode="after")
    def require_uncertainty_for_semantic_claims(self) -> EventEnvelope:
        if self.epistemic_status in {EpistemicStatus.INTERPRETATION, EpistemicStatus.BELIEF}:
            if self.confidence is None:
                raise ValueError("interpretations and beliefs require confidence")
        if self.causation_id == self.event_id:
            raise ValueError("an event cannot cause itself")
        if self.integrity.payload_hash != sha256_digest(canonical_json_bytes(self.payload)):
            raise ValueError("payload hash does not match the canonical payload")
        return self
