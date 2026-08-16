"""Durable outbound-delivery persistence port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from melloa.domain.base import RecordId
from melloa.domain.delivery import (
    DeliveryWorkAttempt,
    DeliveryWorkResumption,
    DeliveryWorkStatus,
    OutboundDeliveryWork,
)


class DeliveryNotFoundError(LookupError):
    """A canonical outbound-delivery record was not found."""


class DeliveryConflictError(RuntimeError):
    """Immutable delivery identity or work state conflicts."""


@dataclass(frozen=True)
class EnqueuedDeliveryWork:
    work: OutboundDeliveryWork
    status: DeliveryWorkStatus
    created: bool


@dataclass(frozen=True)
class ClaimedDeliveryWork:
    work: OutboundDeliveryWork
    attempt: int
    max_attempts: int
    lease_owner: RecordId
    lease_expires_at: datetime


class DeliveryStore(Protocol):
    def enqueue(
        self,
        work: OutboundDeliveryWork,
        *,
        max_attempts: int,
    ) -> EnqueuedDeliveryWork:
        """Atomically persist exact authority and enqueue one idempotent delivery."""

    def get_work(self, work_id: RecordId) -> OutboundDeliveryWork:
        """Return immutable delivery work with append-only attempt history."""

    def claim_work(
        self,
        work_id: RecordId,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedDeliveryWork | None:
        """Lease one due delivery item, recovering an expired lease first."""

    def claim_next_work(
        self,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedDeliveryWork | None:
        """Lease the next due delivery in deterministic queue order."""

    def record_failure(
        self,
        claim: ClaimedDeliveryWork,
        attempt: DeliveryWorkAttempt,
    ) -> DeliveryWorkStatus:
        """Append one failure and either schedule retry or mark work dead."""

    def complete(
        self,
        claim: ClaimedDeliveryWork,
        attempt: DeliveryWorkAttempt,
    ) -> DeliveryWorkStatus:
        """Atomically append side-effect receipts and complete leased work."""

    def status(self, work_id: RecordId) -> DeliveryWorkStatus:
        """Return owner-visible delivery status."""

    def list_status(self, thread_id: RecordId) -> tuple[DeliveryWorkStatus, ...]:
        """Return one thread's deliveries in deterministic queue order."""

    def find_by_message(
        self,
        message_id: RecordId,
    ) -> tuple[DeliveryWorkStatus, ...]:
        """Return every channel delivery for one canonical message."""

    def resume(
        self,
        work_id: RecordId,
        resumption: DeliveryWorkResumption,
        *,
        available_at: datetime,
        added_attempts: int,
    ) -> DeliveryWorkStatus:
        """Requeue terminal work with a fresh exact allow decision."""
