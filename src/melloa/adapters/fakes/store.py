"""Process-local event and audit append store for tests and preview runtimes."""

from __future__ import annotations

from melloa.domain.audit import AuditContent, AuditRecord, audit_record_hash
from melloa.domain.base import JsonObject
from melloa.domain.events import EventEnvelope
from melloa.ports.store import EventConflictError


class InMemoryEventAuditStore:
    def __init__(self) -> None:
        self._event_documents: dict[str, JsonObject] = {}
        self._events: list[EventEnvelope] = []
        self._audit_records: list[AuditRecord] = []

    def append_event(self, event: EventEnvelope, audit: AuditContent) -> AuditRecord | None:
        event_document = event.model_dump(mode="json")
        existing = self._event_documents.get(event.event_id)
        if existing is not None:
            if existing != event_document:
                raise EventConflictError(
                    f"event ID conflicts with immutable data: {event.event_id}"
                )
            return None

        previous_hash = (
            None if not self._audit_records else self._audit_records[-1].record_hash
        )
        record = AuditRecord(
            content=audit,
            previous_hash=previous_hash,
            record_hash=audit_record_hash(audit, previous_hash),
        )
        self._event_documents[event.event_id] = event_document
        self._events.append(event)
        self._audit_records.append(record)
        return record

    @property
    def events(self) -> tuple[EventEnvelope, ...]:
        return tuple(self._events)

    @property
    def audit_records(self) -> tuple[AuditRecord, ...]:
        return tuple(self._audit_records)
