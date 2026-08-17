from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.adapters.guardian.file import GuardianVerificationError
from melloa.application.conversation import ConversationService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.core import create_app
from melloa.domain.classification import Sensitivity
from melloa.domain.exports import (
    CanonicalExportManifest,
    ExportFileEntry,
    ExportFileKind,
)
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.models import ModelRouteRequest, ProcessingLocation
from tests.conftest import record_id


def guardian_reader(fixed_time, mode=GuardianMode.NO_ACTIONS):
    payload = GuardianStatusPayload(
        instance_id="home-guardian",
        mode=mode,
        sequence=1,
        changed_at=fixed_time,
        reason_code="guardian.initialized",
    )
    return FakeGuardianStatusReader.from_payload(
        payload,
        receipt_hash="sha256:" + "1" * 64,
    )


def test_fake_model_is_zero_cost_and_device_local(fixed_time) -> None:
    request = ModelRouteRequest(
        request_id=record_id("request", 1),
        task_type="test.extraction",
        required_modalities=("text",),
        minimum_quality_profile="quality.synthetic",
        sensitivity=Sensitivity.INTERNAL,
        allowed_processing_locations=frozenset({ProcessingLocation.DEVICE}),
        latency_deadline_ms=1000,
        max_input_tokens=100,
        max_output_tokens=100,
        cost_ceiling_gbp=0.0,
        provider_retention_policy="retention.no-training",
        minimum_reliability=0.0,
        fallback_route_ids=(),
        output_schema_id="schema.synthetic",
        prompt_version="fixture-v1",
        input={"text": "synthetic"},
    )
    result = FakeModelGateway({"value": "fixture"}).invoke(request)
    assert result.cost_gbp == 0.0
    assert result.external_disclosure is False
    assert result.output == {"value": "fixture"}

    callable_result = FakeModelGateway(lambda route: {"task": route.task_type}).invoke(request)
    assert callable_result.output == {"task": "test.extraction"}

    ineligible = request.model_copy(
        update={"allowed_processing_locations": frozenset({ProcessingLocation.APPROVED_PROVIDER})}
    )
    try:
        FakeModelGateway({}).invoke(ineligible)
    except ValueError as error:
        assert "device processing" in str(error)
    else:
        raise AssertionError("fake model accepted external-only eligibility")


def test_private_api_exposes_verified_status_and_security_headers(fixed_time) -> None:
    client = TestClient(create_app(guardian_reader(fixed_time)))
    response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    assert response.json()["guardian"]["mode"] == "no-actions"
    assert response.json()["external_actions_enabled"] is False
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert client.get("/openapi.json").status_code == 404


def test_private_api_rejects_invalid_background_worker_configuration(fixed_time) -> None:
    with pytest.raises(ValueError, match="interval"):
        create_app(guardian_reader(fixed_time), conversation_worker_interval=0)
    with pytest.raises(ValueError, match="configured conversation service"):
        create_app(guardian_reader(fixed_time), run_conversation_worker=True)
    with pytest.raises(ValueError, match="delivery worker interval"):
        create_app(guardian_reader(fixed_time), delivery_worker_interval=0)
    with pytest.raises(ValueError, match="configured delivery service"):
        create_app(guardian_reader(fixed_time), run_delivery_worker=True)
    with pytest.raises(ValueError, match="Telegram worker interval"):
        create_app(guardian_reader(fixed_time), telegram_worker_interval=0)
    with pytest.raises(ValueError, match="configured poll worker"):
        create_app(guardian_reader(fixed_time), run_telegram_worker=True)
    with pytest.raises(ValueError, match="retention worker interval"):
        create_app(guardian_reader(fixed_time), telegram_retention_worker_interval=0)
    with pytest.raises(ValueError, match="configured retention worker"):
        create_app(guardian_reader(fixed_time), run_telegram_retention_worker=True)


def test_readiness_is_unavailable_when_guardian_stops_runtime(fixed_time) -> None:
    client = TestClient(create_app(guardian_reader(fixed_time, GuardianMode.STOPPED)))
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503


def test_unverified_guardian_status_fails_closed() -> None:
    class BrokenReader:
        def read_status(self):
            raise GuardianVerificationError("synthetic failure")

    response = TestClient(create_app(BrokenReader())).get("/api/v1/system/status")
    assert response.status_code == 503
    assert response.json()["code"] == "guardian_status_unverified"


def test_owner_login_session_csrf_and_logout(fixed_time) -> None:
    tokens = iter(("session-token", "csrf-token"))
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    client = TestClient(
        create_app(guardian_reader(fixed_time), sessions),
        base_url="https://testserver",
    )

    failed = client.post(
        "/api/v1/auth/session",
        json={"credential": "incorrect-bootstrap-token-value-0000"},
    )
    assert failed.status_code == 401
    assert failed.json()["code"] == "owner_authentication_failed"

    login = client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    assert login.status_code == 200
    assert login.json()["principal"]["owner_id"] == record_id("owner", 1)
    assert login.json()["csrf_token"] == "csrf-token"
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie
    assert client.get("/api/v1/auth/session").status_code == 200

    missing_csrf = client.delete("/api/v1/auth/session")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "csrf_validation_failed"
    logout = client.delete(
        "/api/v1/auth/session",
        headers={"X-Melloa-CSRF": "csrf-token"},
    )
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/session").status_code == 401


def test_failed_owner_login_appends_content_free_security_audit(fixed_time) -> None:
    ids = iter((record_id("event", 1), record_id("audit", 1)))
    tokens = iter(("session-token", "csrf-token"))
    audit_store = InMemoryEventAuditStore()
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    client = TestClient(
        create_app(
            guardian_reader(fixed_time),
            sessions,
            owner_id=record_id("owner", 1),
            event_audit_store=audit_store,
            security_event_clock=lambda: fixed_time,
            security_event_id_factory=lambda prefix: next(ids),
        ),
        base_url="https://testserver",
    )

    failed = client.post(
        "/api/v1/auth/session",
        json={"credential": "incorrect-bootstrap-token-value-0000"},
    )

    assert failed.status_code == 401
    assert failed.json()["code"] == "owner_authentication_failed"
    assert len(audit_store.events) == 1
    assert len(audit_store.audit_records) == 1
    event = audit_store.events[0]
    assert event.event_type == "auth.owner-login-denied.v1"
    assert event.subject_ids == (record_id("owner", 1),)
    assert event.payload == {
        "authentication_method": "auth.local-opaque-token",
        "reason_code": "auth.owner-credential.invalid",
        "result": "denied",
        "session_issued": False,
    }
    audit = audit_store.audit_records[0].content
    assert audit.actor_id.startswith("actor_")
    assert audit.actor_id != record_id("owner", 1)
    assert audit.action == "auth.owner-login.deny"
    assert audit.object_ids == (record_id("event", 1),)
    assert audit.metadata == {
        "event_id": record_id("event", 1),
        "reason_code": "auth.owner-credential.invalid",
        "result": "denied",
    }
    documents = tuple(event.model_dump_json() for event in audit_store.events) + tuple(
        record.model_dump_json() for record in audit_store.audit_records
    )
    assert all("incorrect-bootstrap-token-value-0000" not in document for document in documents)
    assert all("synthetic-bootstrap-token-value-0001" not in document for document in documents)
    assert all("session-token" not in document for document in documents)
    assert all("csrf-token" not in document for document in documents)

    login = client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    assert login.status_code == 200
    assert len(audit_store.events) == 1


def test_owner_mutation_boundary_denials_append_content_free_security_audits(
    fixed_time,
) -> None:
    now = fixed_time
    ids = iter(
        (
            record_id("event", 1),
            record_id("audit", 1),
            record_id("event", 2),
            record_id("audit", 2),
        )
    )
    tokens = iter(("session-token", "csrf-token"))
    audit_store = InMemoryEventAuditStore()
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: now,
        token_factory=lambda: next(tokens),
    )
    client = TestClient(
        create_app(
            guardian_reader(fixed_time),
            sessions,
            owner_id=record_id("owner", 1),
            event_audit_store=audit_store,
            security_event_clock=lambda: now,
            security_event_id_factory=lambda prefix: next(ids),
        ),
        base_url="https://testserver",
    )

    login = client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    assert login.status_code == 200
    missing_csrf = client.delete("/api/v1/auth/session")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "csrf_validation_failed"

    now = fixed_time + timedelta(minutes=5)
    stale_recent = client.delete(
        "/api/v1/auth/sessions/others",
        headers={"X-Melloa-CSRF": login.json()["csrf_token"]},
    )
    assert stale_recent.status_code == 403
    assert stale_recent.json()["code"] == "recent_authentication_required"

    assert [event.event_type for event in audit_store.events] == [
        "auth.owner-mutation-denied.v1",
        "auth.owner-mutation-denied.v1",
    ]
    assert [event.payload for event in audit_store.events] == [
        {
            "boundary": "csrf",
            "mutation_authorized": False,
            "reason_code": "auth.csrf.invalid",
            "result": "denied",
        },
        {
            "boundary": "recent-auth",
            "mutation_authorized": False,
            "reason_code": "auth.recent-auth.required",
            "result": "denied",
        },
    ]
    assert [record.content.action for record in audit_store.audit_records] == [
        "auth.owner-mutation.deny",
        "auth.owner-mutation.deny",
    ]
    assert [record.content.object_ids for record in audit_store.audit_records] == [
        (record_id("event", 1),),
        (record_id("event", 2),),
    ]
    assert all(
        record.content.actor_id.startswith("actor_")
        and record.content.actor_id != record_id("owner", 1)
        for record in audit_store.audit_records
    )
    assert [record.content.metadata for record in audit_store.audit_records] == [
        {
            "event_id": record_id("event", 1),
            "reason_code": "auth.csrf.invalid",
            "result": "denied",
        },
        {
            "event_id": record_id("event", 2),
            "reason_code": "auth.recent-auth.required",
            "result": "denied",
        },
    ]
    documents = tuple(event.model_dump_json() for event in audit_store.events) + tuple(
        record.model_dump_json() for record in audit_store.audit_records
    )
    assert all("synthetic-bootstrap-token-value-0001" not in document for document in documents)
    assert all("session-token" not in document for document in documents)
    assert all("csrf-token" not in document for document in documents)


def test_owner_session_denials_append_content_free_security_audits(fixed_time) -> None:
    now = fixed_time
    ids = iter(
        (
            record_id("event", 1),
            record_id("audit", 1),
            record_id("event", 2),
            record_id("audit", 2),
        )
    )
    tokens = iter(("session-token", "csrf-token"))
    audit_store = InMemoryEventAuditStore()
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: now,
        token_factory=lambda: next(tokens),
        session_ttl=timedelta(minutes=1),
        recent_auth_ttl=timedelta(seconds=30),
    )
    client = TestClient(
        create_app(
            guardian_reader(fixed_time),
            sessions,
            owner_id=record_id("owner", 1),
            event_audit_store=audit_store,
            security_event_clock=lambda: now,
            security_event_id_factory=lambda prefix: next(ids),
        ),
        base_url="https://testserver",
    )

    routine_probe = client.get("/api/v1/auth/session")
    assert routine_probe.status_code == 401
    assert audit_store.events == ()

    missing_session = client.get("/api/v1/auth/sessions")
    assert missing_session.status_code == 401
    assert missing_session.json()["code"] == "owner_authentication_failed"

    login = client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    assert login.status_code == 200
    now = fixed_time + timedelta(minutes=1)
    expired_session = client.get("/api/v1/auth/sessions")
    assert expired_session.status_code == 401
    assert expired_session.json()["code"] == "owner_authentication_failed"

    assert [event.event_type for event in audit_store.events] == [
        "auth.owner-session-denied.v1",
        "auth.owner-session-denied.v1",
    ]
    assert [event.payload for event in audit_store.events] == [
        {
            "boundary": "owner-session",
            "reason_code": "auth.owner-session.missing",
            "request_authenticated": False,
            "result": "denied",
            "session_verified": False,
        },
        {
            "boundary": "owner-session",
            "reason_code": "auth.owner-session.expired",
            "request_authenticated": False,
            "result": "denied",
            "session_verified": False,
        },
    ]
    assert [record.content.action for record in audit_store.audit_records] == [
        "auth.owner-session.deny",
        "auth.owner-session.deny",
    ]
    assert [record.content.metadata for record in audit_store.audit_records] == [
        {
            "event_id": record_id("event", 1),
            "reason_code": "auth.owner-session.missing",
            "result": "denied",
        },
        {
            "event_id": record_id("event", 2),
            "reason_code": "auth.owner-session.expired",
            "result": "denied",
        },
    ]
    documents = tuple(event.model_dump_json() for event in audit_store.events) + tuple(
        record.model_dump_json() for record in audit_store.audit_records
    )
    assert all("synthetic-bootstrap-token-value-0001" not in document for document in documents)
    assert all("session-token" not in document for document in documents)
    assert all("csrf-token" not in document for document in documents)


def test_owner_export_preview_appends_content_free_generation_audit(fixed_time) -> None:
    class StubExportService:
        def write_validated_zip(self, archive_path, *, schema_root, principal):
            assert schema_root == Path("schemas")
            assert principal.owner_id == record_id("owner", 1)
            with ZipFile(archive_path, "x") as archive:
                archive.writestr("manifest.json", "{}\n")
            return CanonicalExportManifest(
                export_id=record_id("export", 1),
                owner_id=record_id("owner", 1),
                intelligence_id=record_id("intelligence", 1),
                created_at=fixed_time,
                source_runtime="melloa-core/0.1.0-export-preview",
                encrypted=False,
                includes_sql_snapshot=False,
                includes_blobs=False,
                files=(
                    ExportFileEntry(
                        path="conversations/messages.jsonl",
                        kind=ExportFileKind.DATA,
                        record_type="export.conversation-message",
                        schema_path="schemas/conversation/message-v1.json",
                        content_hash="sha256:" + "a" * 64,
                        size_bytes=12,
                        record_count=2,
                    ),
                    ExportFileEntry(
                        path="schemas/conversation/message-v1.json",
                        kind=ExportFileKind.SCHEMA,
                        content_hash="sha256:" + "b" * 64,
                        size_bytes=24,
                    ),
                ),
                limitations=(
                    "export.preview-unencrypted",
                    "export.sql-snapshot-not-included",
                    "export.blobs-not-included",
                ),
            )

    ids = iter((record_id("event", 1), record_id("audit", 1)))
    tokens = iter(("session-token", "csrf-token"))
    audit_store = InMemoryEventAuditStore()
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    client = TestClient(
        create_app(
            guardian_reader(fixed_time),
            sessions,
            owner_id=record_id("owner", 1),
            event_audit_store=audit_store,
            security_event_clock=lambda: fixed_time,
            security_event_id_factory=lambda prefix: next(ids),
            export_service=StubExportService(),
            export_schema_root=Path("schemas"),
        ),
        base_url="https://testserver",
    )
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    assert login.status_code == 200

    archive_response = client.post(
        "/api/v1/exports/preview",
        headers={"X-Melloa-CSRF": login.json()["csrf_token"]},
    )

    assert archive_response.status_code == 200
    assert archive_response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(archive_response.content)) as archive:
        assert archive.testzip() is None
    assert len(audit_store.events) == 1
    assert len(audit_store.audit_records) == 1
    event = audit_store.events[0]
    assert event.event_type == "export.owner-preview-generated.v1"
    assert event.subject_ids == (record_id("owner", 1), record_id("export", 1))
    assert event.source.capability_id == "export.owner-preview"
    assert event.producer.component == "export.private-core"
    assert event.payload == {
        "export_id": record_id("export", 1),
        "format_id": "melloa.canonical-owner-export",
        "format_version": "1.0.0",
        "encrypted": False,
        "includes_sql_snapshot": False,
        "includes_blobs": False,
        "file_count": 2,
        "data_file_count": 1,
        "exported_record_count": 2,
        "limitation_ids": (
            "export.preview-unencrypted",
            "export.sql-snapshot-not-included",
            "export.blobs-not-included",
        ),
        "limitation_count": 3,
        "reason_code": "export.owner-preview.generated",
        "result": "generated",
    }
    audit = audit_store.audit_records[0].content
    assert audit.actor_id == record_id("owner", 1)
    assert audit.action == "export.owner-preview.generate"
    assert audit.object_ids == (record_id("event", 1), record_id("export", 1))
    assert audit.metadata == {
        "event_id": record_id("event", 1),
        "export_id": record_id("export", 1),
        "format_id": "melloa.canonical-owner-export",
        "reason_code": "export.owner-preview.generated",
        "result": "generated",
        "file_count": 2,
        "data_file_count": 1,
        "exported_record_count": 2,
        "limitation_count": 3,
    }
    documents = tuple(event.model_dump_json() for event in audit_store.events) + tuple(
        record.model_dump_json() for record in audit_store.audit_records
    )
    assert all("synthetic-bootstrap-token-value-0001" not in document for document in documents)
    assert all("session-token" not in document for document in documents)
    assert all("csrf-token" not in document for document in documents)
    assert all("owner-export.zip" not in document for document in documents)
    assert all("manifest.json" not in document for document in documents)
    assert all(("sha256:" + "a" * 64) not in document for document in documents)


def test_owner_lists_sessions_and_recently_revokes_others(fixed_time) -> None:
    now = fixed_time
    tokens = iter(
        (
            "first-session-token",
            "first-csrf-token",
            "second-session-token",
            "second-csrf-token",
            "fresh-session-token",
            "fresh-csrf-token",
        )
    )
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: now,
        token_factory=lambda: next(tokens),
    )
    app = create_app(guardian_reader(fixed_time), sessions)
    first_client = TestClient(app, base_url="https://testserver")
    second_client = TestClient(app, base_url="https://testserver")
    anonymous_client = TestClient(app, base_url="https://testserver")
    first_login = first_client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    second_login = second_client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    assert first_login.status_code == 200
    assert second_login.status_code == 200

    assert anonymous_client.get("/api/v1/auth/sessions").status_code == 401
    inventory = first_client.get("/api/v1/auth/sessions")
    assert inventory.status_code == 200
    assert inventory.json()["current_session_id"] == first_login.json()["principal"][
        "session_id"
    ]
    assert {
        session["session_id"] for session in inventory.json()["sessions"]
    } == {
        first_login.json()["principal"]["session_id"],
        second_login.json()["principal"]["session_id"],
    }
    assert first_client.delete("/api/v1/auth/sessions/others").status_code == 403

    now = fixed_time + timedelta(minutes=5)
    stale = first_client.delete(
        "/api/v1/auth/sessions/others",
        headers={"X-Melloa-CSRF": first_login.json()["csrf_token"]},
    )
    assert stale.status_code == 403
    assert stale.json()["code"] == "recent_authentication_required"

    fresh_client = TestClient(app, base_url="https://testserver")
    fresh_login = fresh_client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    revoked = fresh_client.delete(
        "/api/v1/auth/sessions/others",
        headers={"X-Melloa-CSRF": fresh_login.json()["csrf_token"]},
    )
    assert revoked.status_code == 200
    assert revoked.json() == {"revoked_count": 2}
    assert first_client.get("/api/v1/auth/session").status_code == 401
    assert second_client.get("/api/v1/auth/session").status_code == 401
    assert fresh_client.get("/api/v1/auth/session").status_code == 200
    assert fresh_client.get("/api/v1/auth/sessions").json()["sessions"] == [
        fresh_login.json()["principal"]
    ]
    assert fresh_client.delete(
        "/api/v1/auth/sessions/others",
        headers={"X-Melloa-CSRF": fresh_login.json()["csrf_token"]},
    ).json() == {"revoked_count": 0}


def test_owner_authentication_routes_fail_closed_when_unconfigured(fixed_time) -> None:
    client = TestClient(create_app(guardian_reader(fixed_time)), base_url="https://testserver")
    response = client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Owner authentication is not configured."


def test_authenticated_conversation_api_is_channel_neutral_and_csrf_protected(
    fixed_time,
) -> None:
    tokens = iter(("session-token", "csrf-token"))
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    store = InMemoryConversationStore()
    conversation = ConversationService(
        owner_id=record_id("owner", 1),
        intelligence_id=record_id("intelligence", 1),
        store=store,
        model_gateway=FakeModelGateway(
            {"text": "Synthetic authenticated reply."},
            clock=lambda: fixed_time,
        ),
        retriever=PolicyConstrainedRetriever(
            InMemoryMemoryRepository(),
            clock=lambda: fixed_time,
        ),
        guardian_reader=guardian_reader(fixed_time),
        clock=lambda: fixed_time,
    )
    client = TestClient(
        create_app(guardian_reader(fixed_time), sessions, conversation),
        base_url="https://testserver",
    )

    assert client.get("/api/v1/conversations").status_code == 401
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    csrf = login.json()["csrf_token"]
    assert client.post(
        "/api/v1/conversations",
        json={
            "title": "Denied without CSRF",
            "sensitivity": "personal",
            "retention_policy": "retention.owner-conversation",
        },
    ).status_code == 403

    created = client.post(
        "/api/v1/conversations",
        headers={"X-Melloa-CSRF": csrf},
        json={
            "title": "Canonical thread",
            "sensitivity": "personal",
            "retention_policy": "retention.owner-conversation",
        },
    )
    assert created.status_code == 201
    thread_id = created.json()["thread_id"]
    reply = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers={"X-Melloa-CSRF": csrf},
        json={"text": "Hello", "idempotency_key": "browser:message:1"},
    )
    assert reply.status_code == 200
    assert reply.json()["processing"]["state"] == "completed"
    assert reply.json()["output_message"]["parts"][0]["text"] == (
        "Synthetic authenticated reply."
    )
    assert reply.json()["inbound_message"]["source_client"] == "client.owner-console"
    assert "telegram" not in reply.text.lower()
    messages = client.get(f"/api/v1/conversations/{thread_id}/messages")
    assert messages.status_code == 200
    turns = client.get(f"/api/v1/conversations/{thread_id}/turns")
    assert turns.status_code == 200
    assert len(turns.json()) == 1
    processing = client.get(f"/api/v1/conversations/{thread_id}/processing")
    assert processing.status_code == 200
    assert processing.json()[0]["message_id"] == reply.json()["inbound_message"]["message_id"]
    assert processing.json()[0]["state"] == "completed"
    turn_id = turns.json()[0]["turn_id"]
    inspection = client.get(
        f"/api/v1/conversations/{thread_id}/turns/{turn_id}"
    )
    assert inspection.status_code == 200
    assert inspection.json()["turn"]["turn_id"] == turn_id
    assert inspection.json()["retrieval_manifest"]["manifest_id"] == (
        turns.json()[0]["retrieval_manifest_id"]
    )
    assert inspection.json()["model_result"]["external_disclosure"] is False
    assert inspection.json()["output_message"] == reply.json()["output_message"]
    assert len(messages.json()) == 2
    assert len(client.get("/api/v1/conversations").json()) == 1


def test_conversation_api_reports_accepted_failure_and_allows_csrf_resume(fixed_time) -> None:
    tokens = iter(("session-token", "csrf-token"))
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    invocations = 0

    def recovering_response(_request):
        nonlocal invocations
        invocations += 1
        return {"unexpected": True} if invocations == 1 else {"text": "Recovered reply."}

    conversation = ConversationService(
        owner_id=record_id("owner", 1),
        intelligence_id=record_id("intelligence", 1),
        store=InMemoryConversationStore(),
        model_gateway=FakeModelGateway(recovering_response, clock=lambda: fixed_time),
        retriever=PolicyConstrainedRetriever(
            InMemoryMemoryRepository(),
            clock=lambda: fixed_time,
        ),
        guardian_reader=guardian_reader(fixed_time),
        clock=lambda: fixed_time,
        max_processing_attempts=1,
    )
    client = TestClient(
        create_app(guardian_reader(fixed_time), sessions, conversation),
        base_url="https://testserver",
    )
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    csrf = login.json()["csrf_token"]
    created = client.post(
        "/api/v1/conversations",
        headers={"X-Melloa-CSRF": csrf},
        json={
            "title": "Recoverable thread",
            "sensitivity": "internal",
            "retention_policy": "retention.owner-conversation",
        },
    )
    thread_id = created.json()["thread_id"]
    accepted = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers={"X-Melloa-CSRF": csrf},
        json={"text": "Recover safely", "idempotency_key": "browser:recover:1"},
    )
    assert accepted.status_code == 202
    assert accepted.json()["processing"]["state"] == "dead"
    assert "output" not in accepted.json()["processing"]["attempts"][0][
        "model_result_summary"
    ]
    message_id = accepted.json()["inbound_message"]["message_id"]
    detail = client.get(
        f"/api/v1/conversations/{thread_id}/messages/{message_id}/processing"
    )
    assert detail.status_code == 200
    assert detail.json()["last_error_code"] == "model.invalid_output"
    resume_path = f"/api/v1/conversations/{thread_id}/messages/{message_id}/resume"
    assert client.post(resume_path).status_code == 403
    resumed = client.post(resume_path, headers={"X-Melloa-CSRF": csrf})
    assert resumed.status_code == 200
    assert resumed.json()["processing"]["state"] == "completed"
    assert resumed.json()["processing"]["max_attempts"] == 2
    assert resumed.json()["output_message"]["parts"][0]["text"] == "Recovered reply."


def test_authenticated_conversation_api_fails_closed_when_service_is_absent(fixed_time) -> None:
    tokens = iter(("session-token", "csrf-token"))
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    client = TestClient(
        create_app(guardian_reader(fixed_time), sessions),
        base_url="https://testserver",
    )
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": "synthetic-bootstrap-token-value-0001"},
    )
    assert login.status_code == 200
    response = client.get("/api/v1/conversations")
    assert response.status_code == 503
    assert response.json()["detail"] == "Canonical conversation is not configured."
