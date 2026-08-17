"""Process-local event and audit append store for tests and preview runtimes."""

from __future__ import annotations

from datetime import datetime

from melloa.domain.audit import AuditContent, AuditRecord, audit_record_hash
from melloa.domain.base import JsonObject, QualifiedName, RecordId, canonical_json_bytes
from melloa.domain.events import EventEnvelope
from melloa.domain.retention import (
    RetentionInventoryCoverage,
    RetentionInventoryStatus,
)
from melloa.ports.store import EventAuditQueryResult, EventConflictError


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

    def audit_retention_inventory(
        self,
        *,
        policy_id: QualifiedName = "retention.audit-ledger",
    ) -> RetentionInventoryStatus:
        retained_bytes = sum(
            len(canonical_json_bytes(record.model_dump(mode="json")))
            for record in self._audit_records
        )
        return RetentionInventoryStatus(
            policy_id=policy_id,
            coverage=RetentionInventoryCoverage.COMPLETE,
            retained_objects=len(self._audit_records),
            retained_bytes=retained_bytes,
            overdue_objects=0,
            pending_deletions=0,
            deletion_receipts=0,
            oldest_retained_at=(
                None
                if not self._audit_records
                else min(record.content.occurred_at for record in self._audit_records)
            ),
            status_reason="retention.inventory.audit_event_store",
        )

    def list_events(
        self,
        *,
        event_types: tuple[QualifiedName, ...],
        subject_id: RecordId,
        occurred_from: datetime,
        occurred_before: datetime,
        limit: int,
    ) -> EventAuditQueryResult:
        if not event_types:
            return EventAuditQueryResult(events=(), matching_events=0)
        selected = [
            event
            for event in self._events
            if event.event_type in event_types
            and subject_id in event.subject_ids
            and occurred_from <= event.occurred_at < occurred_before
        ]
        selected.sort(key=lambda event: (event.occurred_at, event.event_id), reverse=True)
        if limit <= 0:
            return EventAuditQueryResult(events=(), matching_events=len(selected))
        return EventAuditQueryResult(
            events=tuple(selected[:limit]),
            matching_events=len(selected),
        )
