"""Persistence boundary for owner-approved source changes."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from melloa.domain.base import RecordId, Sha256Digest
from melloa.domain.self_change import SelfChange


class SelfChangeConflictError(RuntimeError):
    """A change command or worker claim conflicts with durable state."""


class SelfChangeNotFoundError(LookupError):
    """The requested self-change does not exist for this owner."""


class SelfChangeStore(Protocol):
    def create(self, change: SelfChange) -> SelfChange:
        """Create one idempotent owner-requested change."""

    def latest(self, owner_id: RecordId) -> SelfChange | None:
        """Return the owner's newest change, if any."""

    def get(self, owner_id: RecordId, change_id: RecordId) -> SelfChange:
        """Return one exact owner change."""

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
    "SelfChangeStore",
]
