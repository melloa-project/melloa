"""Atomic PostgreSQL event and audit append implementation."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from melloa.domain.audit import AuditContent, AuditRecord, audit_record_hash
from melloa.domain.base import QualifiedName
from melloa.domain.events import EventEnvelope
from melloa.domain.retention import (
    RetentionInventoryCoverage,
    RetentionInventoryStatus,
)
from melloa.ports.store import EventConflictError

_AUDIT_LOCK_ID = 5_281_102_019_001


class PostgresEventAuditStore:
    def __init__(self, connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        self._connection = connection

    def append_event(self, event: EventEnvelope, audit: AuditContent) -> AuditRecord | None:
        event_document = event.model_dump(mode="json")
        with self._connection.transaction():
            inserted = self._connection.execute(
                """
                INSERT INTO melloa.canonical_events (
                    event_id, event_type, schema_version, occurred_at, recorded_at,
                    epistemic_status, confidence, sensitivity, trust_label,
                    correlation_id, causation_id, payload_hash, document
                ) VALUES (
                    %(event_id)s, %(event_type)s, %(schema_version)s, %(occurred_at)s,
                    %(recorded_at)s, %(epistemic_status)s, %(confidence)s, %(sensitivity)s,
                    %(trust_label)s, %(correlation_id)s, %(causation_id)s,
                    %(payload_hash)s, %(document)s
                )
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "schema_version": event.schema_version,
                    "occurred_at": event.occurred_at,
                    "recorded_at": event.recorded_at,
                    "epistemic_status": event.epistemic_status.value,
                    "confidence": event.confidence,
                    "sensitivity": event.sensitivity.value,
                    "trust_label": event.trust.value,
                    "correlation_id": event.correlation_id,
                    "causation_id": event.causation_id,
                    "payload_hash": event.integrity.payload_hash,
                    "document": Jsonb(event_document),
                },
            ).fetchone()
            if inserted is None:
                existing = self._connection.execute(
                    "SELECT document FROM melloa.canonical_events WHERE event_id = %s",
                    (event.event_id,),
                ).fetchone()
                if existing is None or existing[0] != event_document:
                    raise EventConflictError(
                        f"event ID conflicts with immutable data: {event.event_id}"
                    )
                return None

            self._connection.execute("SELECT pg_advisory_xact_lock(%s)", (_AUDIT_LOCK_ID,))
            previous_row = self._connection.execute(
                "SELECT record_hash FROM melloa.audit_events ORDER BY audit_sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = None if previous_row is None else str(previous_row[0])
            record = AuditRecord(
                content=audit,
                previous_hash=previous_hash,
                record_hash=audit_record_hash(audit, previous_hash),
            )
            self._connection.execute(
                """
                INSERT INTO melloa.audit_events (
                    audit_id, event_type, occurred_at, actor_id, action_name,
                    previous_hash, record_hash, document
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    audit.audit_id,
                    audit.event_type,
                    audit.occurred_at,
                    audit.actor_id,
                    audit.action,
                    record.previous_hash,
                    record.record_hash,
                    Jsonb(record.model_dump(mode="json")),
                ),
            )
            return record

    def audit_retention_inventory(
        self,
        *,
        policy_id: QualifiedName = "retention.audit-ledger",
    ) -> RetentionInventoryStatus:
        row = self._connection.execute(
            """
            SELECT
                count(*)::bigint,
                coalesce(sum(octet_length(document::text)), 0)::bigint,
                min(occurred_at)
              FROM melloa.audit_events
            """
        ).fetchone()
        if row is None:
            retained_objects = 0
            retained_bytes = 0
            oldest_retained_at = None
        else:
            retained_objects = int(row[0])
            retained_bytes = int(row[1])
            oldest_retained_at = row[2]
        return RetentionInventoryStatus(
            policy_id=policy_id,
            coverage=RetentionInventoryCoverage.COMPLETE,
            retained_objects=retained_objects,
            retained_bytes=retained_bytes,
            overdue_objects=0,
            pending_deletions=0,
            deletion_receipts=0,
            oldest_retained_at=oldest_retained_at,
            status_reason="retention.inventory.audit_event_store",
        )
