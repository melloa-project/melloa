"""Durable, owner-approved changes to Melloa's reviewed source."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import (
    AwareDatetime,
    ContractModel,
    QualifiedName,
    RecordId,
    Sha256Digest,
    canonical_json_bytes,
    sha256_digest,
)

ChangeRequestText = Annotated[str, Field(min_length=10, max_length=2_000)]
ChangeSummary = Annotated[str, Field(min_length=1, max_length=2_000)]
ChangePatch = Annotated[str, Field(min_length=1, max_length=60_000)]
GitRevision = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class SelfChangeState(StrEnum):
    REQUESTED = "requested"
    PLANNING = "planning"
    PROPOSAL_READY = "proposal_ready"
    APPROVED = "approved"
    APPLYING = "applying"
    DEPLOYED = "deployed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"


class SelfChange(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    change_id: RecordId
    owner_id: RecordId
    request_text: ChangeRequestText
    request_digest: Sha256Digest
    requested_update_id: Annotated[int, Field(ge=0)]
    state: SelfChangeState
    base_revision: GitRevision | None = None
    proposal_summary: ChangeSummary | None = None
    proposal_patch: ChangePatch | None = None
    proposal_digest: Sha256Digest | None = None
    approval_update_id: Annotated[int, Field(ge=0)] | None = None
    approved_digest: Sha256Digest | None = None
    candidate_revision: GitRevision | None = None
    failure_reason: QualifiedName | None = None
    attempt_count: Annotated[int, Field(ge=0, le=10)] = 0
    max_attempts: Annotated[int, Field(ge=1, le=10)] = 3
    available_at: AwareDatetime
    lease_owner: RecordId | None = None
    lease_expires_at: AwareDatetime | None = None
    requested_at: AwareDatetime
    updated_at: AwareDatetime
    approved_at: AwareDatetime | None = None
    deployed_at: AwareDatetime | None = None
    cancelled_update_id: Annotated[int, Field(ge=0)] | None = None
    cancelled_at: AwareDatetime | None = None
    rolled_back_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_change(self) -> SelfChange:
        if self.updated_at < self.requested_at or self.available_at < self.requested_at:
            raise ValueError("self-change timestamps are inconsistent")
        retained_timestamps = (
            self.approved_at,
            self.deployed_at,
            self.cancelled_at,
            self.rolled_back_at,
        )
        if any(
            timestamp < self.requested_at or timestamp > self.updated_at
            for timestamp in retained_timestamps
            if timestamp is not None
        ):
            raise ValueError("self-change evidence timestamps are inconsistent")
        if self.attempt_count > self.max_attempts:
            raise ValueError("self-change attempts exceed their maximum")
        running = self.state in {SelfChangeState.PLANNING, SelfChangeState.APPLYING}
        if running != (self.lease_owner is not None and self.lease_expires_at is not None):
            raise ValueError("only active self-change work may hold a lease")
        if self.lease_expires_at is not None and self.lease_expires_at <= self.updated_at:
            raise ValueError("self-change lease must expire after its update")
        if self.request_digest != self_change_request_digest(self.request_text):
            raise ValueError("self-change request digest does not match its exact text")

        proposal_values = (
            self.base_revision,
            self.proposal_summary,
            self.proposal_patch,
            self.proposal_digest,
        )
        has_proposal = all(value is not None for value in proposal_values)
        if has_proposal != any(value is not None for value in proposal_values):
            raise ValueError("self-change proposal fields must be retained together")
        if self.state in {
            SelfChangeState.PROPOSAL_READY,
            SelfChangeState.APPROVED,
            SelfChangeState.APPLYING,
            SelfChangeState.DEPLOYED,
            SelfChangeState.ROLLED_BACK,
        } and not has_proposal:
            raise ValueError("self-change state requires an exact proposal")
        if (
            self.base_revision is not None
            and self.proposal_summary is not None
            and self.proposal_patch is not None
            and self.proposal_digest
            != self_change_proposal_digest(
                base_revision=self.base_revision,
                summary=self.proposal_summary,
                patch=self.proposal_patch,
            )
        ):
            raise ValueError("self-change proposal digest does not match its exact content")

        approval_values = (
            self.approval_update_id,
            self.approved_digest,
            self.approved_at,
        )
        approved = all(value is not None for value in approval_values)
        if approved != any(value is not None for value in approval_values):
            raise ValueError("self-change approval evidence must be retained together")
        if (
            self.approval_update_id is not None
            and self.approval_update_id <= self.requested_update_id
        ):
            raise ValueError("self-change approval must follow its request")
        if self.approved_digest is not None and self.approved_digest != self.proposal_digest:
            raise ValueError("self-change approval must bind the exact proposal")
        if self.state in {
            SelfChangeState.APPROVED,
            SelfChangeState.APPLYING,
            SelfChangeState.DEPLOYED,
            SelfChangeState.ROLLED_BACK,
        } and not approved:
            raise ValueError("self-change state requires owner approval")

        if self.state is SelfChangeState.DEPLOYED:
            if (
                self.candidate_revision is None
                or self.deployed_at is None
                or self.rolled_back_at is not None
            ):
                raise ValueError("deployed self-change requires release evidence")
        elif self.state is SelfChangeState.ROLLED_BACK:
            if (
                self.candidate_revision is None
                or self.deployed_at is None
                or self.rolled_back_at is None
            ):
                raise ValueError("rolled-back self-change requires deployment evidence")
        elif self.deployed_at is not None or self.rolled_back_at is not None:
            raise ValueError("undeployed self-change cannot retain release timestamps")

        if (self.state is SelfChangeState.FAILED) != (self.failure_reason is not None):
            raise ValueError("only failed self-change work requires a reason")
        cancellation_values = (self.cancelled_update_id, self.cancelled_at)
        cancelled = all(value is not None for value in cancellation_values)
        if cancelled != any(value is not None for value in cancellation_values):
            raise ValueError("self-change cancellation evidence must be retained together")
        if (
            self.cancelled_update_id is not None
            and self.cancelled_update_id <= self.requested_update_id
        ):
            raise ValueError("self-change cancellation must follow its request")
        if (self.state is SelfChangeState.CANCELLED) != cancelled:
            raise ValueError("only cancelled self-change work requires a cancellation time")
        return self


def self_change_request_digest(request_text: str) -> str:
    return sha256_digest(request_text.encode("utf-8"))


def self_change_proposal_digest(
    *,
    base_revision: str,
    summary: str,
    patch: str,
) -> str:
    return sha256_digest(
        canonical_json_bytes(
            {
                "base_revision": base_revision,
                "proposal_patch": patch,
                "proposal_summary": summary,
                "schema_version": "1.0.0",
            }
        )
    )


__all__ = [
    "ChangePatch",
    "ChangeSummary",
    "GitRevision",
    "SelfChange",
    "SelfChangeState",
    "self_change_proposal_digest",
    "self_change_request_digest",
]
