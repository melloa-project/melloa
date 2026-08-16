from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.application.memory import MemoryService
from melloa.apps.core import create_app
from melloa.domain.base import RecordId
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import Assertion, AssertionStatus
from tests.conftest import record_id

_BOOTSTRAP_TOKEN = "synthetic-bootstrap-token-value-0001"


def _assertion(
    fixed_time: datetime,
    *,
    assertion_id: RecordId | None = None,
    subject_id: RecordId | None = None,
) -> Assertion:
    return Assertion(
        assertion_id=assertion_id or record_id("assertion", 1),
        subject_id=subject_id or record_id("owner", 1),
        predicate="activity.current",
        value={"activity": "sleeping"},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.61,
        source_authority=TrustLabel.MODEL_GENERATED,
        sensitivity=Sensitivity.SENSITIVE,
        observed_at=fixed_time,
    )


def _guardian(
    fixed_time: datetime,
    mode: GuardianMode = GuardianMode.NO_ACTIONS,
) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="synthetic-guardian",
            mode=mode,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def _authenticated_client(
    fixed_time: datetime,
    *,
    memory_service: MemoryService | None,
    guardian_reader: FakeGuardianStatusReader | None = None,
    clock=None,
    recent_auth_ttl: timedelta = timedelta(minutes=5),
) -> tuple[TestClient, str]:
    active_clock = clock or (lambda: fixed_time)
    tokens = iter(("session-token", "csrf-token"))
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        clock=active_clock,
        token_factory=lambda: next(tokens),
        recent_auth_ttl=recent_auth_ttl,
    )
    client = TestClient(
        create_app(
            guardian_reader or _guardian(fixed_time),
            sessions,
            memory_service=memory_service,
        ),
        base_url="https://testserver",
    )
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert login.status_code == 200
    return client, login.json()["csrf_token"]


def test_memory_api_inspects_and_corrects_with_recent_csrf_session(fixed_time) -> None:
    original = _assertion(fixed_time)
    repository = InMemoryMemoryRepository((original,))
    guardian = _guardian(fixed_time)
    memory = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=guardian,
        clock=lambda: fixed_time + timedelta(minutes=1),
        id_factory={
            "assertion": record_id("assertion", 2),
            "edge": record_id("edge", 1),
            "state_change": record_id("state_change", 2),
        }.__getitem__,
    )
    unauthenticated_tokens = iter(("session-token", "csrf-token"))
    unauthenticated_sessions = InMemoryOwnerSessionManager(
        original.subject_id,
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        token_factory=lambda: next(unauthenticated_tokens),
    )
    unauthenticated = TestClient(
        create_app(guardian, unauthenticated_sessions, memory_service=memory),
        base_url="https://testserver",
    )
    assert unauthenticated.get(
        f"/api/v1/memory/{original.assertion_id}"
    ).status_code == 401

    client, csrf = _authenticated_client(
        fixed_time,
        memory_service=memory,
        guardian_reader=guardian,
    )
    initial = client.get(f"/api/v1/memory/{original.assertion_id}")
    assert initial.status_code == 200
    assert initial.json()["assertion"] == original.model_dump(mode="json")
    assert initial.json()["current_state"]["current_status"] == "active"
    assert initial.json()["state_changes"][0]["reason"] == "assertion.initialized"

    denied = client.post(
        f"/api/v1/memory/{original.assertion_id}/corrections",
        json={"value": {"activity": "reading"}, "expected_version": 1},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "csrf_validation_failed"

    corrected = client.post(
        f"/api/v1/memory/{original.assertion_id}/corrections",
        headers={"X-Melloa-CSRF": csrf},
        json={"value": {"activity": "reading"}, "expected_version": 1},
    )
    assert corrected.status_code == 201
    body = corrected.json()
    assert body["correction"]["value"] == {"activity": "reading"}
    assert body["correction"]["epistemic_status"] == "correction"
    assert body["provenance_edge"]["relation"] == "corrects"
    assert body["target_state"]["current_status"] == "superseded"
    assert body["target_state"]["preferred_assertion_id"] == (
        body["correction"]["assertion_id"]
    )

    inspection = client.get(f"/api/v1/memory/{original.assertion_id}")
    assert inspection.status_code == 200
    assert inspection.json()["assertion"]["status"] == "active"
    assert inspection.json()["current_state"] == body["target_state"]
    assert len(inspection.json()["state_changes"]) == 2
    stale = client.post(
        f"/api/v1/memory/{original.assertion_id}/corrections",
        headers={"X-Melloa-CSRF": csrf},
        json={"value": {"activity": "walking"}, "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "memory_conflict"
    missing = client.get(f"/api/v1/memory/{record_id('assertion', 99)}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "memory_not_found"


def test_memory_api_requires_recent_authentication(fixed_time) -> None:
    now = [fixed_time]
    original = _assertion(fixed_time)
    guardian = _guardian(fixed_time)
    memory = MemoryService(
        owner_id=original.subject_id,
        store=InMemoryMemoryRepository((original,)),
        guardian_reader=guardian,
        clock=lambda: now[0],
        id_factory={
            "assertion": record_id("assertion", 2),
            "edge": record_id("edge", 1),
            "state_change": record_id("state_change", 2),
        }.__getitem__,
    )
    client, csrf = _authenticated_client(
        fixed_time,
        memory_service=memory,
        guardian_reader=guardian,
        clock=lambda: now[0],
        recent_auth_ttl=timedelta(minutes=1),
    )
    now[0] = fixed_time + timedelta(minutes=1)

    response = client.post(
        f"/api/v1/memory/{original.assertion_id}/corrections",
        headers={"X-Melloa-CSRF": csrf},
        json={"value": {"activity": "reading"}, "expected_version": 1},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "recent_authentication_required"


def test_memory_api_deletes_content_with_recent_csrf_and_preserves_tombstone(
    fixed_time,
) -> None:
    original = _assertion(fixed_time)
    ids = iter(
        (
            record_id("deletion", 1),
            record_id("work", 1),
            record_id("deletion", 2),
            record_id("work", 2),
        )
    )

    def id_factory(_prefix: str) -> str:
        return next(ids)

    memory = MemoryService(
        owner_id=original.subject_id,
        store=InMemoryMemoryRepository((original,)),
        guardian_reader=_guardian(fixed_time),
        clock=lambda: fixed_time + timedelta(minutes=2),
        id_factory=id_factory,
    )
    client, csrf = _authenticated_client(fixed_time, memory_service=memory)

    missing_csrf = client.delete(f"/api/v1/memory/{original.assertion_id}/content")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "csrf_validation_failed"

    deleted = client.delete(
        f"/api/v1/memory/{original.assertion_id}/content",
        headers={"X-Melloa-CSRF": csrf},
    )
    assert deleted.status_code == 200
    body = deleted.json()
    assert body["created"] is True
    assert body["assertion"]["assertion_id"] == original.assertion_id
    assert "value" not in body["assertion"]
    assert body["tombstone"]["assertion_id"] == original.assertion_id
    assert body["tombstone"]["deleted_by_record_id"] == original.subject_id
    assert body["tombstone"]["reason_code"] == "memory.assertion-content-owner-deleted"
    assert body["rebuild_work"]["assertion_id"] == original.assertion_id
    assert body["backup_expiry"]["state"] == "unknown"

    inspection = client.get(f"/api/v1/memory/{original.assertion_id}")
    assert inspection.status_code == 200
    inspected = inspection.json()
    assert inspected["content_state"] == "deleted"
    assert "value" not in inspected["assertion"]
    assert inspected["deletion_tombstone"] == body["tombstone"]
    assert inspected["backup_expiry"]["state"] == "unknown"

    repeated = client.delete(
        f"/api/v1/memory/{original.assertion_id}/content",
        headers={"X-Melloa-CSRF": csrf},
    )
    assert repeated.status_code == 200
    assert repeated.json()["created"] is False
    assert repeated.json()["tombstone"] == body["tombstone"]


def test_memory_api_appends_dispute_and_retraction_transitions(fixed_time) -> None:
    original = _assertion(fixed_time)
    guardian = _guardian(fixed_time)
    state_change_ids = iter(
        (record_id("state_change", 2), record_id("state_change", 3))
    )

    def id_factory(prefix: str) -> str:
        assert prefix == "state_change"
        return next(state_change_ids)

    memory = MemoryService(
        owner_id=original.subject_id,
        store=InMemoryMemoryRepository((original,)),
        guardian_reader=guardian,
        clock=lambda: fixed_time + timedelta(minutes=1),
        id_factory=id_factory,
    )
    client, csrf = _authenticated_client(
        fixed_time,
        memory_service=memory,
        guardian_reader=guardian,
    )

    disputed = client.post(
        f"/api/v1/memory/{original.assertion_id}/disputes",
        headers={"X-Melloa-CSRF": csrf},
        json={"expected_version": 1},
    )
    assert disputed.status_code == 201
    assert disputed.json()["assertion"]["status"] == "active"
    assert disputed.json()["current_state"]["current_status"] == "disputed"
    assert disputed.json()["state_change"]["reason"] == "assertion.owner-disputed"

    retracted = client.post(
        f"/api/v1/memory/{original.assertion_id}/retractions",
        headers={"X-Melloa-CSRF": csrf},
        json={"expected_version": 2},
    )
    assert retracted.status_code == 201
    assert retracted.json()["current_state"]["current_status"] == "retracted"
    assert retracted.json()["current_state"]["version"] == 3
    assert retracted.json()["state_change"]["reason"] == "assertion.owner-retracted"

    inspection = client.get(f"/api/v1/memory/{original.assertion_id}")
    assert inspection.json()["assertion"]["status"] == "active"
    assert inspection.json()["current_state"] == retracted.json()["current_state"]
    assert [change["new_status"] for change in inspection.json()["state_changes"]] == [
        "active",
        "disputed",
        "retracted",
    ]
    terminal = client.post(
        f"/api/v1/memory/{original.assertion_id}/disputes",
        headers={"X-Melloa-CSRF": csrf},
        json={"expected_version": 3},
    )
    assert terminal.status_code == 409
    assert terminal.json()["code"] == "memory_conflict"


def test_memory_api_conceals_ownership_and_fails_closed(fixed_time) -> None:
    foreign = _assertion(fixed_time, subject_id=record_id("owner", 2))
    guardian = _guardian(fixed_time)
    foreign_memory = MemoryService(
        owner_id=record_id("owner", 1),
        store=InMemoryMemoryRepository((foreign,)),
        guardian_reader=guardian,
        clock=lambda: fixed_time,
    )
    client, csrf = _authenticated_client(
        fixed_time,
        memory_service=foreign_memory,
        guardian_reader=guardian,
    )
    assert client.get(f"/api/v1/memory/{foreign.assertion_id}").status_code == 404
    correction = client.post(
        f"/api/v1/memory/{foreign.assertion_id}/corrections",
        headers={"X-Melloa-CSRF": csrf},
        json={"value": {"activity": "reading"}, "expected_version": 1},
    )
    assert correction.status_code == 404
    assert correction.json()["code"] == "memory_not_found"

    original = _assertion(fixed_time)
    read_only_guardian = _guardian(fixed_time, GuardianMode.READ_ONLY)
    read_only_memory = MemoryService(
        owner_id=original.subject_id,
        store=InMemoryMemoryRepository((original,)),
        guardian_reader=read_only_guardian,
        clock=lambda: fixed_time,
    )
    read_only_client, read_only_csrf = _authenticated_client(
        fixed_time,
        memory_service=read_only_memory,
        guardian_reader=read_only_guardian,
    )
    unavailable = read_only_client.post(
        f"/api/v1/memory/{original.assertion_id}/corrections",
        headers={"X-Melloa-CSRF": read_only_csrf},
        json={"value": {"activity": "reading"}, "expected_version": 1},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "memory_write_unavailable"
    delete_unavailable = read_only_client.delete(
        f"/api/v1/memory/{original.assertion_id}/content",
        headers={"X-Melloa-CSRF": read_only_csrf},
    )
    assert delete_unavailable.status_code == 503
    assert delete_unavailable.json()["code"] == "memory_write_unavailable"

    absent_client, _csrf = _authenticated_client(fixed_time, memory_service=None)
    absent = absent_client.get(f"/api/v1/memory/{original.assertion_id}")
    assert absent.status_code == 503
    assert absent.json()["detail"] == "Memory inspection and correction are not configured."
