from __future__ import annotations

import pytest

from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.domain.base import canonical_json_bytes, sha256_digest
from melloa.domain.events import EventEnvelope
from melloa.ports.store import EventConflictError
from tests.conftest import record_id


def test_in_memory_event_audit_store_is_idempotent_and_chains(
    event,
    audit_content,
) -> None:
    store = InMemoryEventAuditStore()
    first = store.append_event(event, audit_content)
    assert first is not None
    assert first.previous_hash is None
    assert store.append_event(event, audit_content) is None

    second_event = event.model_copy(
        update={
            "event_id": record_id("event", 2),
            "causation_id": event.event_id,
        }
    )
    second_audit = audit_content.model_copy(
        update={
            "audit_id": record_id("audit", 2),
            "object_ids": (second_event.event_id,),
        }
    )
    second = store.append_event(second_event, second_audit)

    assert second is not None
    assert second.previous_hash == first.record_hash
    assert tuple(record.content.audit_id for record in store.audit_records) == (
        audit_content.audit_id,
        second_audit.audit_id,
    )
    assert tuple(item.event_id for item in store.events) == (
        event.event_id,
        second_event.event_id,
    )

    inventory = store.audit_retention_inventory()
    assert inventory.retained_objects == 2
    assert inventory.retained_bytes is not None and inventory.retained_bytes > 0
    assert inventory.oldest_retained_at == event.occurred_at
    assert inventory.status_reason == "retention.inventory.audit_event_store"


def test_in_memory_event_audit_store_rejects_changed_event_replay(
    event: EventEnvelope,
    audit_content,
) -> None:
    store = InMemoryEventAuditStore()
    assert store.append_event(event, audit_content) is not None

    changed_payload = {"zone": "window", "direction": "in"}
    changed_document = event.model_dump()
    changed_document["payload"] = changed_payload
    changed_document["integrity"]["payload_hash"] = sha256_digest(
        canonical_json_bytes(changed_payload)
    )
    changed_event = EventEnvelope.model_validate(changed_document)

    with pytest.raises(EventConflictError, match=event.event_id):
        store.append_event(changed_event, audit_content)

    assert len(store.events) == 1
    assert len(store.audit_records) == 1
