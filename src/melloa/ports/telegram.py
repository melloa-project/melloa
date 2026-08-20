"""Persistence boundary for the one-owner Telegram polling loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from melloa.domain.base import QualifiedName, RecordId
from melloa.domain.models import ModelRoute
from melloa.domain.telegram import TelegramDelivery, TelegramOwnerChannel


class TelegramStateConflictError(RuntimeError):
    """The durable owner binding or update identity conflicts with existing state."""


@dataclass(frozen=True)
class TelegramDeliverySummary:
    awaiting_reply: int
    ready: int
    running: int
    sent: int
    dead: int

    @property
    def pending(self) -> int:
        return self.awaiting_reply + self.ready + self.running


class TelegramStore(Protocol):
    def bind_owner_channel(
        self,
        *,
        owner_user_id: int,
        owner_chat_id: int,
        initial_model_route: ModelRoute,
        now: datetime,
    ) -> TelegramOwnerChannel:
        """Create or validate the permanent exact-owner channel binding."""

    def owner_channel(self) -> TelegramOwnerChannel:
        """Return the permanent owner channel binding and durable update cursor."""

    def advance_update(self, update_id: int, *, now: datetime) -> TelegramOwnerChannel:
        """Durably acknowledge an update that needs no owner response."""

    def accept_conversation_update(
        self,
        *,
        update_id: int,
        incoming_message_id: int,
        inbound_message_id: RecordId,
        now: datetime,
        max_attempts: int,
    ) -> TelegramDelivery:
        """Atomically advance the cursor and retain a conversation delivery."""

    def accept_status_update(
        self,
        *,
        update_id: int,
        incoming_message_id: int,
        now: datetime,
        max_attempts: int,
    ) -> TelegramDelivery:
        """Atomically advance the cursor and enqueue an owner status response."""

    def accept_model_route_update(
        self,
        *,
        update_id: int,
        incoming_message_id: int,
        model_route: ModelRoute | None,
        now: datetime,
        max_attempts: int,
    ) -> TelegramDelivery:
        """Persist an optional route change and its exact acknowledgement atomically."""

    def awaiting_conversation_deliveries(self, *, limit: int) -> tuple[TelegramDelivery, ...]:
        """Return accepted owner messages whose canonical reply is not ready yet."""

    def mark_conversation_ready(
        self,
        update_id: int,
        *,
        response_message_id: RecordId,
        now: datetime,
    ) -> TelegramDelivery:
        """Make an immutable canonical conversation reply deliverable."""

    def mark_conversation_notice_ready(
        self,
        update_id: int,
        *,
        notice_code: QualifiedName,
        now: datetime,
    ) -> TelegramDelivery:
        """Make a bounded deterministic failure notice deliverable."""

    def claim_next_delivery(
        self,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> TelegramDelivery | None:
        """Lease the next due response, reclaiming an expired send attempt."""

    def record_delivery_part(
        self,
        claim: TelegramDelivery,
        *,
        telegram_message_id: int,
        now: datetime,
    ) -> TelegramDelivery:
        """Record one remotely accepted response chunk under the active lease."""

    def complete_delivery(
        self,
        claim: TelegramDelivery,
        *,
        now: datetime,
    ) -> TelegramDelivery:
        """Mark a fully sent owner response complete."""

    def record_delivery_failure(
        self,
        claim: TelegramDelivery,
        *,
        error_code: QualifiedName,
        retry_at: datetime,
        now: datetime,
    ) -> TelegramDelivery:
        """Schedule a redacted delivery retry or terminate exhausted work."""

    def delivery_summary(self) -> TelegramDeliverySummary:
        """Return bounded owner-visible backlog counts."""


__all__ = [
    "TelegramDeliverySummary",
    "TelegramStateConflictError",
    "TelegramStore",
]
