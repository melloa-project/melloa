"""Durable append ports for events and audit."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from melloa.domain.audit import AuditContent, AuditRecord
from melloa.domain.base import QualifiedName, RecordId
from melloa.domain.events import EventEnvelope
from melloa.domain.retention import RetentionInventoryStatus


class EventConflictError(RuntimeError):
    """An immutable event ID was reused with different content."""


@dataclass(frozen=True)
class EventAuditQueryResult:
    events: tuple[EventEnvelope, ...]
    matching_events: int

    def __post_init__(self) -> None:
        if self.matching_events < len(self.events):
            raise ValueError("event query matches cannot be below returned events")


class EventAuditStore(Protocol):
    def append_event(self, event: EventEnvelope, audit: AuditContent) -> AuditRecord | None:
        """Atomically append an event and audit, or return None for an exact duplicate."""

    def audit_retention_inventory(
        self,
        *,
        policy_id: QualifiedName = "retention.audit-ledger",
    ) -> RetentionInventoryStatus:
        """Return aggregate audit-ledger retention counts without exposing records."""

    def list_events(
        self,
        *,
        event_types: tuple[QualifiedName, ...],
        subject_id: RecordId,
        occurred_from: datetime,
        occurred_before: datetime,
        limit: int,
    ) -> EventAuditQueryResult:
        """Return owner-scoped canonical events and total matches for redacted projections."""
