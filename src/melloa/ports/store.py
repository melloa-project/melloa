"""Durable append ports for events and audit."""

from typing import Protocol

from melloa.domain.audit import AuditContent, AuditRecord
from melloa.domain.base import QualifiedName
from melloa.domain.events import EventEnvelope
from melloa.domain.retention import RetentionInventoryStatus


class EventConflictError(RuntimeError):
    """An immutable event ID was reused with different content."""


class EventAuditStore(Protocol):
    def append_event(self, event: EventEnvelope, audit: AuditContent) -> AuditRecord | None:
        """Atomically append an event and audit, or return None for an exact duplicate."""

    def audit_retention_inventory(
        self,
        *,
        policy_id: QualifiedName = "retention.audit-ledger",
    ) -> RetentionInventoryStatus:
        """Return aggregate audit-ledger retention counts without exposing records."""
