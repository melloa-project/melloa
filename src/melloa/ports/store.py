"""Content-minimal security event append port."""

from typing import Protocol

from melloa.domain.audit import AuditContent, AuditRecord
from melloa.domain.events import EventEnvelope


class EventConflictError(RuntimeError):
    """An immutable event ID was reused with different content."""


class EventAuditStore(Protocol):
    def append_event(self, event: EventEnvelope, audit: AuditContent) -> AuditRecord | None:
        """Atomically append an event and audit, or return None for an exact duplicate."""
