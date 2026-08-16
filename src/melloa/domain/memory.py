"""Assertions, corrections, and provenance edges."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from melloa.domain.base import (
    AwareDatetime,
    ContractModel,
    JsonObject,
    QualifiedName,
    RecordId,
    Sha256Digest,
)
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.events import Confidence
from melloa.domain.retention import BackupExpiryDisclosure


class AssertionStatus(StrEnum):
    PROVISIONAL = "provisional"
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    EXPIRED = "expired"


class AssertionContentState(StrEnum):
    RETAINED = "retained"
    DELETED = "deleted"


class ProvenanceRelation(StrEnum):
    DERIVED_FROM = "derived_from"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    CORRECTS = "corrects"
    CITES = "cites"


class AssertionMetadata(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    assertion_id: RecordId
    subject_id: RecordId
    predicate: QualifiedName
    epistemic_status: EpistemicStatus
    status: AssertionStatus
    confidence: Confidence
    source_authority: TrustLabel
    sensitivity: Sensitivity
    observed_at: AwareDatetime
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None
    correction_target_id: RecordId | None = None

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to <= self.valid_from:
                raise ValueError("assertion validity must end after it starts")
        if self.epistemic_status is EpistemicStatus.CORRECTION:
            if self.correction_target_id is None:
                raise ValueError("corrections require a target assertion")
        elif self.correction_target_id is not None:
            raise ValueError("only corrections may set correction_target_id")
        if self.epistemic_status is EpistemicStatus.OWNER_CONFIRMED:
            if self.source_authority is not TrustLabel.OWNER_AUTHORED:
                raise ValueError("owner-confirmed assertions require owner authority")
        return self


class Assertion(AssertionMetadata):
    value: JsonObject


class AssertionContentDeletionTombstone(ContractModel):
    """Content-free evidence that one assertion value was intentionally removed."""

    contract_version: Literal["1.0.0"] = "1.0.0"
    tombstone_id: RecordId
    assertion_id: RecordId
    owner_id: RecordId
    deleted_by_record_id: RecordId
    content_hash: Sha256Digest
    size_bytes: Annotated[int, Field(gt=0)]
    retention_policy: QualifiedName
    retained_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    deleted_at: AwareDatetime
    reason_code: QualifiedName
    rebuild_work_id: RecordId

    @model_validator(mode="after")
    def validate_chronology(self) -> AssertionContentDeletionTombstone:
        if self.expires_at is not None and self.expires_at <= self.retained_at:
            raise ValueError("assertion content expiry must follow initial retention")
        if self.deleted_at < self.retained_at:
            raise ValueError("assertion content deletion cannot precede initial retention")
        return self


class AssertionDerivedRebuildWork(ContractModel):
    """Content-free work request to purge and rebuild assertion-derived data."""

    contract_version: Literal["1.0.0"] = "1.0.0"
    work_id: RecordId
    work_type: Literal["memory.assertion-derived-rebuild"] = (
        "memory.assertion-derived-rebuild"
    )
    assertion_id: RecordId
    tombstone_id: RecordId
    requested_by_record_id: RecordId
    requested_at: AwareDatetime


class ProvenanceEdge(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    edge_id: RecordId
    from_id: RecordId
    to_id: RecordId
    relation: ProvenanceRelation
    created_at: AwareDatetime
    producer_id: RecordId
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_self_edges(self) -> ProvenanceEdge:
        if self.from_id == self.to_id:
            raise ValueError("provenance edges cannot point to the same record")
        return self


class AssertionStateProjection(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    assertion_id: RecordId
    current_status: AssertionStatus
    preferred_assertion_id: RecordId | None = None
    changed_by_record_id: RecordId
    changed_at: AwareDatetime
    version: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_preferred_assertion(self) -> AssertionStateProjection:
        if self.preferred_assertion_id == self.assertion_id:
            raise ValueError("an assertion cannot supersede itself")
        if (
            self.current_status is AssertionStatus.SUPERSEDED
            and self.preferred_assertion_id is None
        ):
            raise ValueError("superseded assertions require a preferred replacement")
        return self


class AssertionContentDeletionResult(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    assertion: AssertionMetadata
    current_state: AssertionStateProjection
    tombstone: AssertionContentDeletionTombstone
    rebuild_work: AssertionDerivedRebuildWork
    backup_expiry: BackupExpiryDisclosure
    created: bool

    @model_validator(mode="after")
    def validate_links(self) -> AssertionContentDeletionResult:
        assertion_id = self.assertion.assertion_id
        if (
            self.current_state.assertion_id != assertion_id
            or self.tombstone.assertion_id != assertion_id
            or self.rebuild_work.assertion_id != assertion_id
        ):
            raise ValueError("assertion content deletion references another assertion")
        if self.tombstone.owner_id != self.assertion.subject_id:
            raise ValueError("assertion content deletion owner does not match its subject")
        if (
            self.tombstone.rebuild_work_id != self.rebuild_work.work_id
            or self.tombstone.tombstone_id != self.rebuild_work.tombstone_id
            or self.tombstone.deleted_by_record_id
            != self.rebuild_work.requested_by_record_id
            or self.tombstone.deleted_at != self.rebuild_work.requested_at
        ):
            raise ValueError("assertion content deletion rebuild work is inconsistent")
        return self


class AssertionStateChange(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    change_id: RecordId
    assertion_id: RecordId
    previous_status: AssertionStatus | None
    new_status: AssertionStatus
    preferred_assertion_id: RecordId | None = None
    changed_by_record_id: RecordId
    reason: QualifiedName
    changed_at: AwareDatetime
    version: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_transition(self) -> AssertionStateChange:
        if (self.version == 1) != (self.previous_status is None):
            raise ValueError("only an initial assertion state may omit previous_status")
        if self.preferred_assertion_id == self.assertion_id:
            raise ValueError("an assertion state change cannot prefer itself")
        if (
            self.new_status is AssertionStatus.SUPERSEDED
            and self.preferred_assertion_id is None
        ):
            raise ValueError("a supersession change requires a preferred replacement")
        return self


class AssertionCorrectionResult(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    correction: Assertion
    provenance_edge: ProvenanceEdge
    target_state: AssertionStateProjection
    correction_state: AssertionStateProjection
    target_change: AssertionStateChange

    @model_validator(mode="after")
    def validate_correction_links(self) -> AssertionCorrectionResult:
        target_id = self.correction.correction_target_id
        if self.correction.epistemic_status is not EpistemicStatus.CORRECTION:
            raise ValueError("correction result requires a correction assertion")
        if (
            self.provenance_edge.relation is not ProvenanceRelation.CORRECTS
            or self.provenance_edge.from_id != self.correction.assertion_id
            or self.provenance_edge.to_id != target_id
        ):
            raise ValueError("correction provenance does not match the correction target")
        if (
            self.target_state.assertion_id != target_id
            or self.target_change.assertion_id != target_id
            or self.target_state.version != self.target_change.version
            or self.target_state.current_status is not self.target_change.new_status
        ):
            raise ValueError("target correction state and state change do not match")
        if self.correction_state.assertion_id != self.correction.assertion_id:
            raise ValueError("correction projection does not match the correction assertion")
        return self


class AssertionStateTransitionResult(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    assertion: Assertion
    current_state: AssertionStateProjection
    state_change: AssertionStateChange

    @model_validator(mode="after")
    def validate_transition(self) -> AssertionStateTransitionResult:
        assertion_id = self.assertion.assertion_id
        if (
            self.current_state.assertion_id != assertion_id
            or self.state_change.assertion_id != assertion_id
        ):
            raise ValueError("assertion state transition references another assertion")
        if self.state_change.previous_status is None:
            raise ValueError("assertion state transition cannot represent initialization")
        if (
            self.current_state.version != self.state_change.version
            or self.current_state.current_status is not self.state_change.new_status
            or self.current_state.preferred_assertion_id
            != self.state_change.preferred_assertion_id
            or self.current_state.changed_by_record_id
            != self.state_change.changed_by_record_id
            or self.current_state.changed_at != self.state_change.changed_at
        ):
            raise ValueError("assertion state transition result is inconsistent")
        return self


class MemoryInspection(ContractModel):
    contract_version: Literal["1.1.0"] = "1.1.0"
    content_state: AssertionContentState
    assertion: Assertion | AssertionMetadata
    deletion_tombstone: AssertionContentDeletionTombstone | None = None
    backup_expiry: BackupExpiryDisclosure | None = None
    current_state: AssertionStateProjection
    provenance_edges: tuple[ProvenanceEdge, ...]
    state_changes: tuple[AssertionStateChange, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_inspection(self) -> MemoryInspection:
        assertion_id = self.assertion.assertion_id
        if self.content_state is AssertionContentState.RETAINED:
            if not isinstance(self.assertion, Assertion):
                raise ValueError("retained memory inspection requires assertion content")
            if self.deletion_tombstone is not None or self.backup_expiry is not None:
                raise ValueError("retained memory inspection cannot include deletion evidence")
        else:
            if isinstance(self.assertion, Assertion):
                raise ValueError("deleted memory inspection cannot include assertion content")
            if self.deletion_tombstone is None or self.backup_expiry is None:
                raise ValueError("deleted memory inspection requires deletion evidence")
            if (
                self.deletion_tombstone.assertion_id != assertion_id
                or self.deletion_tombstone.owner_id != self.assertion.subject_id
            ):
                raise ValueError("memory deletion evidence does not match the assertion")
        if self.current_state.assertion_id != assertion_id:
            raise ValueError("memory projection does not match the assertion")
        if any(
            edge.from_id != assertion_id and edge.to_id != assertion_id
            for edge in self.provenance_edges
        ):
            raise ValueError("memory inspection includes unrelated provenance")
        if any(change.assertion_id != assertion_id for change in self.state_changes):
            raise ValueError("memory inspection includes unrelated state history")
        latest = self.state_changes[-1]
        if (
            latest.version != self.current_state.version
            or latest.new_status is not self.current_state.current_status
        ):
            raise ValueError("memory state history does not match its current projection")
        return self
