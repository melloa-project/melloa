"""Persistence boundary for owner-approved source changes."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from melloa.domain.base import QualifiedName, RecordId, Sha256Digest
from melloa.domain.self_change import (
    ChangePatch,
    ChangeSummary,
    GitRevision,
    PlannedSelfChange,
    SelfChange,
)


class SelfChangeConflictError(RuntimeError):
    """A change command or worker claim conflicts with durable state."""


class SelfChangeNotFoundError(LookupError):
    """The requested self-change does not exist for this owner."""


class SelfChangePlanningError(RuntimeError):
    """A coding agent could not produce a policy-compliant proposal."""

    def __init__(self, reason_code: QualifiedName) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class SelfChangePlanner(Protocol):
    def plan(self, change: SelfChange) -> PlannedSelfChange:
        """Prepare one untrusted proposal from explicit request text and public source."""


class SelfChangeStore(Protocol):
    def create(self, change: SelfChange) -> SelfChange:
        """Create one idempotent owner-requested change."""

    def latest(self, owner_id: RecordId) -> SelfChange | None:
        """Return the owner's newest change, if any."""

    def get(self, owner_id: RecordId, change_id: RecordId) -> SelfChange:
        """Return one exact owner change."""

    def claim_next_planning(
        self,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> SelfChange | None:
        """Lease the next requested proposal, reclaiming expired planning work."""

    def record_proposal(
        self,
        claim: SelfChange,
        *,
        base_revision: GitRevision,
        summary: ChangeSummary,
        patch: ChangePatch,
        now: datetime,
    ) -> SelfChange:
        """Retain the exact proposal produced under an active planning lease."""

    def record_planning_failure(
        self,
        claim: SelfChange,
        *,
        error_code: QualifiedName,
        retry_at: datetime,
        now: datetime,
    ) -> SelfChange:
        """Release failed planning work for bounded retry or terminal failure."""

    def approve(
        self,
        owner_id: RecordId,
        change_id: RecordId,
        *,
        proposal_digest: Sha256Digest,
        approval_update_id: int,
        now: datetime,
    ) -> SelfChange:
        """Bind an exact proposal to one exact owner approval."""

    def cancel(
        self,
        owner_id: RecordId,
        change_id: RecordId,
        *,
        cancellation_update_id: int,
        now: datetime,
    ) -> SelfChange:
        """Cancel work that has not started applying."""


__all__ = [
    "SelfChangeConflictError",
    "SelfChangeNotFoundError",
    "SelfChangePlanner",
    "SelfChangePlanningError",
    "SelfChangeStore",
]
