from __future__ import annotations

from datetime import timedelta

import pytest

from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.domain.base import canonical_json_bytes, sha256_digest
from melloa.domain.events import EventEnvelope
from melloa.ports.store import EventConflictError
from tests.conftest import record_id


def test_event_append_is_idempotent_and_hash_chained(event, audit_content) -> None:
    store = InMemoryEventAuditStore()

    first = store.append_event(event, audit_content)
    assert first is not None
    assert first.previous_hash is None
    assert store.append_event(event, audit_content) is None

    second_event = event.model_copy(
        update={
            "event_id": record_id("event", 2),
            "causation_id": event.event_id,
            "occurred_at": event.occurred_at + timedelta(minutes=2),
            "recorded_at": event.recorded_at + timedelta(minutes=2),
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
    assert store.events == (event, second_event)
    assert store.audit_records == (first, second)


def test_changed_event_replay_is_rejected(event: EventEnvelope, audit_content) -> None:
    store = InMemoryEventAuditStore()
    assert store.append_event(event, audit_content) is not None

    payload = {"zone": "window", "direction": "in"}
    document = event.model_dump()
    document["payload"] = payload
    document["integrity"]["payload_hash"] = sha256_digest(canonical_json_bytes(payload))
    changed = EventEnvelope.model_validate(document)

    with pytest.raises(EventConflictError, match=event.event_id):
        store.append_event(changed, audit_content)

    assert store.events == (event,)
