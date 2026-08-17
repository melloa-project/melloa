from __future__ import annotations

import time
from datetime import timedelta
from io import BytesIO
from itertools import count
from zipfile import ZipFile

from fastapi.testclient import TestClient

from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.delivery import InMemoryDeliveryStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.application.exports import ExportBundleError
from melloa.apps import core as core_app
from melloa.apps.mvp import build_mvp_runtime
from melloa.apps.synthetic import (
    SYNTHETIC_ASSERTION_ID,
    SYNTHETIC_TELEGRAM_ADAPTER_ID,
    DurableRuntimeStores,
    RuntimePersistenceStatus,
    build_synthetic_runtime,
    synthetic_seed_assertion,
)
from melloa.domain.base import sha256_digest
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.operations import ComponentHealth, HealthCategory, HealthState
from melloa.domain.telegram import (
    TelegramAttachmentDisposition,
    TelegramAttachmentKind,
    TelegramAttachmentReference,
    TelegramChatType,
    TelegramInboundMessage,
    TelegramInboundUpdate,
)
from melloa.ports.memory import AssertionContentDeletionWrite

_BOOTSTRAP_TOKEN = "synthetic-owner-bootstrap-token-value-0001"


def test_mvp_runtime_exposes_partial_durable_store_boundaries(fixed_time) -> None:
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.durable-preview",
        ),
        receipt_hash="sha256:" + "0" * 64,
    )
    assertion = synthetic_seed_assertion(fixed_time)
    database_health = ComponentHealth(
        component_id="database.postgresql-mvp",
        category=HealthCategory.DATABASE,
        state=HealthState.HEALTHY,
        required=True,
        observed_at=fixed_time,
        summary="Private PostgreSQL is healthy.",
        version="18.0",
    )
    stores = DurableRuntimeStores(
        seeded_at=fixed_time,
        conversation_store=InMemoryConversationStore(),
        memory_store=InMemoryMemoryRepository((assertion,)),
        delivery_store=InMemoryDeliveryStore(),
        database_health_reader=lambda: database_health,
        status=RuntimePersistenceStatus(
            mode="postgresql-partial-preview",
            durable_state=("canonical conversations",),
            ephemeral_state=("authentication sessions",),
        ),
    )

    runtime = build_mvp_runtime(
        guardian,
        _BOOTSTRAP_TOKEN,
        durable_stores=stores,
        clock=lambda: fixed_time,
    )

    assert runtime.persistence == stores.status
    with TestClient(runtime.app, base_url="https://testserver") as client:
        login = client.post(
            "/api/v1/auth/session",
            json={"credential": _BOOTSTRAP_TOKEN},
        )
        assert login.status_code == 200
        health = client.get("/api/v1/inspection/health").json()

    components = {component["component_id"]: component for component in health["components"]}
    assert components["database.postgresql-mvp"]["state"] == "healthy"
    assert components["queue.postgresql-durable"]["state"] == "healthy"
    assert components["storage.postgresql-canonical"]["state"] == "healthy"
    assert components["storage.process-local-control-state"]["state"] == "degraded"
    assert components["backup.not-configured"]["state"] == "disabled"


def test_mvp_runtime_preserves_deleted_durable_seed_inspection(fixed_time) -> None:
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.durable-deletion-preview",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    assertion = synthetic_seed_assertion(fixed_time)
    memory_store = InMemoryMemoryRepository((assertion,))
    deletion = memory_store.delete_assertion_content(
        AssertionContentDeletionWrite(
            assertion_id=assertion.assertion_id,
            owner_id=assertion.subject_id,
            tombstone_id="deletion_00000000000000000000000000000001",
            rebuild_work_id="work_00000000000000000000000000000001",
            deleted_by_record_id=assertion.subject_id,
            deleted_at=fixed_time,
            reason_code="memory.assertion-content-owner-deleted",
        )
    )
    stores = DurableRuntimeStores(
        seeded_at=fixed_time,
        conversation_store=InMemoryConversationStore(),
        memory_store=memory_store,
        delivery_store=InMemoryDeliveryStore(),
        database_health_reader=lambda: ComponentHealth(
            component_id="database.postgresql-mvp",
            category=HealthCategory.DATABASE,
            state=HealthState.HEALTHY,
            required=True,
            observed_at=fixed_time,
            summary="Private PostgreSQL is healthy.",
            version="18.0",
        ),
        status=RuntimePersistenceStatus(
            mode="postgresql-partial-preview",
            durable_state=("memory assertions",),
            ephemeral_state=("authentication sessions",),
        ),
    )

    runtime = build_mvp_runtime(
        guardian,
        _BOOTSTRAP_TOKEN,
        durable_stores=stores,
        clock=lambda: fixed_time,
    )

    with TestClient(runtime.app, base_url="https://testserver") as client:
        login = client.post(
            "/api/v1/auth/session",
            json={"credential": _BOOTSTRAP_TOKEN},
        )
        assert login.status_code == 200
        response = client.get(f"/api/v1/memory/{assertion.assertion_id}")

    assert response.status_code == 200
    inspection = response.json()
    assert inspection["content_state"] == "deleted"
    assert inspection["assertion"]["assertion_id"] == assertion.assertion_id
    assert "value" not in inspection["assertion"]
    assert inspection["deletion_tombstone"]["tombstone_id"] == (
        deletion.tombstone.tombstone_id
    )


def test_synthetic_runtime_exercises_private_m1_workflows_without_disclosure(
    fixed_time,
    monkeypatch,
) -> None:
    payload = GuardianStatusPayload(
        instance_id="home-guardian",
        mode=GuardianMode.NO_ACTIONS,
        sequence=1,
        changed_at=fixed_time,
        reason_code="guardian.synthetic-acceptance",
    )
    guardian = FakeGuardianStatusReader.from_payload(
        payload,
        receipt_hash="sha256:" + "1" * 64,
    )
    identifiers = count(10)

    def id_factory(prefix: str) -> str:
        return f"{prefix}_{next(identifiers):032x}"

    runtime = build_synthetic_runtime(
        guardian,
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        id_factory=id_factory,
    )
    export_workspaces = []
    create_export_workspace = core_app._create_export_workspace

    def tracked_export_workspace():
        workspace = create_export_workspace()
        export_workspaces.append(workspace)
        return workspace

    monkeypatch.setattr(core_app, "_create_export_workspace", tracked_export_workspace)
    client = TestClient(runtime.app, base_url="https://testserver")
    assert client.post("/api/v1/exports/preview").status_code == 401
    assert runtime.event_audit_store.events[-1].event_type == (
        "auth.owner-session-denied.v1"
    )
    assert runtime.event_audit_store.events[-1].payload == {
        "boundary": "owner-session",
        "reason_code": "auth.owner-session.missing",
        "request_authenticated": False,
        "result": "denied",
        "session_verified": False,
    }

    status = client.get("/api/v1/system/status")
    assert status.status_code == 200
    assert status.json()["guardian"]["mode"] == "no-actions"
    assert status.json()["external_actions_enabled"] is False

    login = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    headers = {"X-Melloa-CSRF": csrf}

    health = client.get("/api/v1/inspection/health")
    assert health.status_code == 200
    assert health.json()["overall_state"] == "degraded"
    assert any(
        component["category"] == "camera" and component["state"] == "disabled"
        for component in health.json()["components"]
    )
    retention = client.get("/api/v1/retention")
    assert retention.status_code == 200
    retention_report = retention.json()
    assert retention_report["backup_expiry"]["state"] == "not-configured"
    policies = {
        item["policy_id"]: item for item in retention_report["policies"]
    }
    assert policies["retention.audit-ledger"]["deletion_control"] == "restricted"
    audit_inventory = next(
        item
        for item in retention_report["inventory"]
        if item["policy_id"] == "retention.audit-ledger"
    )
    assert audit_inventory["coverage"] == "complete"
    assert audit_inventory["retained_objects"] == 1
    assert audit_inventory["retained_bytes"] > 0
    assert audit_inventory["deletion_receipts"] == 0
    assert audit_inventory["status_reason"] == "retention.inventory.audit_event_store"
    assert policies["retention.owner-conversation"]["deletion_control"] == (
        "not-implemented"
    )
    conversation_inventory = next(
        item
        for item in retention_report["inventory"]
        if item["policy_id"] == "retention.owner-conversation"
    )
    assert conversation_inventory["coverage"] == "complete"
    assert conversation_inventory["retained_objects"] == 1
    assert conversation_inventory["retained_bytes"] > 0
    assert conversation_inventory["deletion_receipts"] == 0
    assert conversation_inventory["oldest_retained_at"] is not None
    assert policies["retention.owner-delivery"]["deletion_control"] == (
        "not-implemented"
    )
    delivery_inventory = next(
        item
        for item in retention_report["inventory"]
        if item["policy_id"] == "retention.owner-delivery"
    )
    assert delivery_inventory["coverage"] == "complete"
    assert delivery_inventory["retained_objects"] == 0
    assert delivery_inventory["retained_bytes"] == 0
    assert delivery_inventory["deletion_receipts"] == 0
    assert delivery_inventory["status_reason"] == "retention.inventory.owner_delivery"
    assert policies["retention.owner-memory"]["deletion_control"] == "owner-request"
    assert policies["retention.owner-memory"]["owner_deletion_scopes"] == [
        "memory-claim"
    ]
    memory_inventory = next(
        item
        for item in retention_report["inventory"]
        if item["policy_id"] == "retention.owner-memory"
    )
    assert memory_inventory["coverage"] == "complete"
    assert memory_inventory["retained_objects"] == 1
    assert memory_inventory["retained_bytes"] > 0
    assert memory_inventory["deletion_receipts"] == 0
    assert memory_inventory["oldest_retained_at"] is not None
    quarantine_policy = policies["retention.telegram-quarantine"]
    assert quarantine_policy["duration_bounds"] == {
        "minimum_seconds": 3_600,
        "default_seconds": 86_400,
        "maximum_seconds": 604_800,
    }
    quarantine_inventory = next(
        item
        for item in retention_report["inventory"]
        if item["policy_id"] == "retention.telegram-quarantine"
    )
    assert quarantine_inventory["coverage"] == "complete"
    assert quarantine_inventory["retained_objects"] == 0
    assert quarantine_inventory["retained_bytes"] == 0
    assert quarantine_inventory["deletion_receipts"] == 0
    assert quarantine_inventory["status_reason"] == (
        "retention.inventory.telegram_quarantine_backend"
    )
    media_catalog = client.get("/api/v1/inspection/media")
    assert media_catalog.status_code == 200
    assert media_catalog.json()["capture_enabled"] is False
    assert media_catalog.json()["content_endpoint_available"] is False
    assert media_catalog.json()["items"] == []
    export_before = client.get("/api/v1/inspection/export")
    assert export_before.status_code == 200
    export_before_coverage = {
        item["group_id"]: item for item in export_before.json()["coverage"]
    }
    assert export_before_coverage["export.assertion-inspections"]["estimated_records"] == 1
    assert export_before_coverage["export.conversation-records"]["estimated_records"] == 1
    assert export_before_coverage["export.model-activity"]["estimated_records"] == 0
    assert export_before_coverage["export.blobs"].get("estimated_records") is None
    export_before_checks = {
        item["check_id"]: item for item in export_before.json()["validation_checks"]
    }
    assert export_before_checks["export.validation.checksums"]["implemented"] is True
    assert export_before_checks["export.validation.restore-execution"][
        "implemented"
    ] is False

    memory = client.get(f"/api/v1/memory/{runtime.seed_assertion_id}")
    assert memory.status_code == 200
    assert memory.json()["assertion"]["value"]["fixture"] is True
    assert memory.json()["current_state"]["version"] == 1

    thread = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={
            "title": "Synthetic acceptance",
            "sensitivity": "personal",
            "retention_policy": "retention.owner-conversation",
        },
    )
    assert thread.status_code == 201
    thread_id = thread.json()["thread_id"]
    reply = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers=headers,
        json={
            "text": "Please use my reading preference.",
            "idempotency_key": "synthetic-runtime:message:1",
        },
    )
    assert reply.status_code == 200
    assert reply.json()["output_message"]["citation_ids"]
    assert "No external model" in reply.json()["output_message"]["parts"][0]["text"]

    turn_id = reply.json()["turn"]["turn_id"]
    inspection = client.get(
        f"/api/v1/conversations/{thread_id}/turns/{turn_id}"
    )
    assert inspection.status_code == 200
    result = inspection.json()["model_result"]
    assert result["cost_gbp"] == 0.0
    assert result["external_disclosure"] is False
    assert result["attempts"][0]["processing_location"] == "device"
    assert inspection.json()["retrieval_manifest"]["external_disclosure"] is False

    activity = client.get(
        "/api/v1/inspection/model-activity",
        params={
            "from": (fixed_time - timedelta(minutes=1)).isoformat(),
            "to": (fixed_time + timedelta(minutes=1)).isoformat(),
        },
    )
    assert activity.status_code == 200
    assert activity.json()["total_runs"] == 1
    assert activity.json()["external_disclosure_runs"] == 0
    assert activity.json()["total_cost_gbp"] == 0.0
    timeline = client.get(
        "/api/v1/inspection/timeline",
        params={
            "from": (fixed_time - timedelta(minutes=1)).isoformat(),
            "to": (fixed_time + timedelta(minutes=1)).isoformat(),
            "limit": 20,
        },
    )
    assert timeline.status_code == 200
    timeline_kinds = {entry["kind"] for entry in timeline.json()["entries"]}
    assert "timeline.conversation.message-created" in timeline_kinds
    assert "timeline.conversation.turn-recorded" in timeline_kinds
    assert "timeline.model-route.completed" in timeline_kinds
    assert "Please use my reading preference." not in timeline.text
    assert "No external model" not in timeline.text
    export_after = client.get("/api/v1/inspection/export")
    export_after_coverage = {
        item["group_id"]: item for item in export_after.json()["coverage"]
    }
    assert export_after_coverage["export.conversation-records"]["estimated_records"] == 7
    assert export_after_coverage["export.delivery-records"]["estimated_records"] == 0
    assert export_after_coverage["export.model-activity"]["estimated_records"] == 1
    assert export_after_coverage["export.retention-report"]["estimated_records"] == 1
    assert export_after_coverage["export.schemas-checksums"]["estimated_records"] == 14
    csrf_denied_export = client.post("/api/v1/exports/preview")
    assert csrf_denied_export.status_code == 403
    assert runtime.event_audit_store.events[-1].event_type == (
        "auth.owner-mutation-denied.v1"
    )
    assert runtime.event_audit_store.events[-1].payload == {
        "boundary": "csrf",
        "mutation_authorized": False,
        "reason_code": "auth.csrf.invalid",
        "result": "denied",
    }
    archive_response = client.post("/api/v1/exports/preview", headers=headers)
    assert archive_response.status_code == 200
    assert archive_response.headers["content-type"] == "application/zip"
    assert archive_response.headers["cache-control"] == "no-store"
    assert "melloa-owner-export-export_" in archive_response.headers[
        "content-disposition"
    ]
    with ZipFile(BytesIO(archive_response.content)) as archive:
        assert archive.testzip() is None
        messages = archive.read("conversations/messages.jsonl").decode("utf-8")
        assert "Please use my reading preference." in messages
        archive_text = "".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )
        assert _BOOTSTRAP_TOKEN not in archive_text
        assert csrf not in archive_text
    assert export_workspaces
    assert all(not workspace.exists() for workspace in export_workspaces)

    correction = client.post(
        f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}/corrections",
        headers=headers,
        json={
            "value": {"activity": "walking", "fixture": True},
            "expected_version": 1,
        },
    )
    assert correction.status_code == 201
    assert correction.json()["provenance_edge"]["relation"] == "corrects"
    updated = client.get(f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}").json()
    assert updated["assertion"]["status"] == "confirmed"
    assert updated["current_state"]["current_status"] == "superseded"
    assert updated["current_state"]["version"] == 2

    deletion = client.delete(
        f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}/content",
        headers=headers,
    )
    assert deletion.status_code == 200
    assert deletion.json()["created"] is True
    retention_after_deletion = client.get("/api/v1/retention").json()
    inventory_after_deletion = {
        item["policy_id"]: item for item in retention_after_deletion["inventory"]
    }
    audit_after_deletion = inventory_after_deletion["retention.audit-ledger"]
    assert audit_after_deletion["coverage"] == "complete"
    assert audit_after_deletion["retained_objects"] == 4
    assert audit_after_deletion["retained_bytes"] > 0
    assert audit_after_deletion["oldest_retained_at"] is not None
    memory_after_deletion = inventory_after_deletion["retention.owner-memory"]
    assert memory_after_deletion["retained_objects"] == 1
    assert memory_after_deletion["deletion_receipts"] == 1


def test_synthetic_runtime_counts_failed_login_security_audit(fixed_time) -> None:
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.normal",
        ),
        receipt_hash="sha256:" + "0" * 64,
    )
    runtime = build_synthetic_runtime(
        guardian,
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
    )
    client = TestClient(runtime.app, base_url="https://testserver")

    failed = client.post(
        "/api/v1/auth/session",
        json={"credential": "incorrect-owner-bootstrap-token-0001"},
    )
    assert failed.status_code == 401
    assert failed.json()["code"] == "owner_authentication_failed"
    assert len(runtime.event_audit_store.events) == 1
    assert runtime.event_audit_store.events[0].event_type == (
        "auth.owner-login-denied.v1"
    )

    login = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert login.status_code == 200
    retention = client.get("/api/v1/retention")
    assert retention.status_code == 200
    audit_inventory = next(
        item
        for item in retention.json()["inventory"]
        if item["policy_id"] == "retention.audit-ledger"
    )
    assert audit_inventory["coverage"] == "complete"
    assert audit_inventory["retained_objects"] == 1
    assert audit_inventory["retained_bytes"] > 0
    assert audit_inventory["oldest_retained_at"] == fixed_time.isoformat().replace(
        "+00:00",
        "Z",
    )

    documents = tuple(
        event.model_dump_json() for event in runtime.event_audit_store.events
    ) + tuple(
        record.model_dump_json() for record in runtime.event_audit_store.audit_records
    )
    assert all(
        "incorrect-owner-bootstrap-token-0001" not in document
        for document in documents
    )
    assert all(_BOOTSTRAP_TOKEN not in document for document in documents)


def test_synthetic_runtime_preserves_guardian_write_denial(fixed_time) -> None:
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.READ_ONLY,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic-read-only",
        ),
        receipt_hash="sha256:" + "2" * 64,
    )
    runtime = build_synthetic_runtime(
        guardian,
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
    )
    client = TestClient(runtime.app, base_url="https://testserver")
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    headers = {"X-Melloa-CSRF": login.json()["csrf_token"]}

    assert client.get(f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}").status_code == 200
    conversation = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={
            "title": "Denied synthetic write",
            "sensitivity": "personal",
            "retention_policy": "retention.owner-conversation",
        },
    )
    assert conversation.status_code == 503
    assert conversation.json()["code"] == "conversation_write_unavailable"
    correction = client.post(
        f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}/corrections",
        headers=headers,
        json={"value": {"activity": "walking"}, "expected_version": 1},
    )
    assert correction.status_code == 503
    assert correction.json()["code"] == "memory_write_unavailable"


def test_live_export_requires_recent_authentication_and_redacts_failures(
    fixed_time,
    monkeypatch,
) -> None:
    now = fixed_time
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.export-auth-test",
        ),
        receipt_hash="sha256:" + "3" * 64,
    )
    runtime = build_synthetic_runtime(
        guardian,
        _BOOTSTRAP_TOKEN,
        clock=lambda: now,
    )
    client = TestClient(runtime.app, base_url="https://testserver")
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    now = fixed_time + timedelta(minutes=5)
    stale = client.post(
        "/api/v1/exports/preview",
        headers={"X-Melloa-CSRF": login.json()["csrf_token"]},
    )
    assert stale.status_code == 403
    assert stale.json()["code"] == "recent_authentication_required"

    fresh = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )

    class FailingExportService:
        def write_validated_zip(self, *_args, **_kwargs):
            raise ExportBundleError("sensitive internal export path")

    runtime.app.state.export_service = FailingExportService()
    workspaces = []
    create_export_workspace = core_app._create_export_workspace

    def tracked_export_workspace():
        workspace = create_export_workspace()
        workspaces.append(workspace)
        return workspace

    monkeypatch.setattr(core_app, "_create_export_workspace", tracked_export_workspace)
    failed = client.post(
        "/api/v1/exports/preview",
        headers={"X-Melloa-CSRF": fresh.json()["csrf_token"]},
    )
    assert failed.status_code == 503
    assert failed.json() == {
        "code": "export_preview_unavailable",
        "message": "The owner export preview could not be generated and validated.",
    }
    assert "sensitive" not in failed.text
    assert workspaces
    assert all(not workspace.exists() for workspace in workspaces)


def test_synthetic_runtime_delivers_canonical_output_without_channel_network(
    fixed_time,
) -> None:
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic-normal",
        ),
        receipt_hash="sha256:" + "3" * 64,
    )
    identifiers = count(100)

    def id_factory(prefix: str) -> str:
        return f"{prefix}_{next(identifiers):032x}"

    runtime = build_synthetic_runtime(
        guardian,
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        id_factory=id_factory,
        telegram_retention_worker_interval=0.01,
    )
    with TestClient(runtime.app, base_url="https://testserver") as client:
        _wait_for_telegram_retention_sweep(runtime)
        login = client.post(
            "/api/v1/auth/session",
            json={"credential": _BOOTSTRAP_TOKEN},
        )
        headers = {"X-Melloa-CSRF": login.json()["csrf_token"]}
        thread = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={
                "title": "Synthetic delivery acceptance",
                "sensitivity": "personal",
                "retention_policy": "retention.owner-conversation",
            },
        )
        thread_id = thread.json()["thread_id"]
        reply = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=headers,
            json={
                "text": "Create a canonical synthetic reply.",
                "idempotency_key": "synthetic-runtime:delivery-message:1",
            },
        )
        output_message_id = reply.json()["output_message"]["message_id"]
        delivery_path = f"/api/v1/conversations/{thread_id}/deliveries"
        delivery_payload = {
            "message_id": output_message_id,
            "client_adapter": "client.fake",
            "destination_ref": "synthetic:owner",
            "idempotency_key": "synthetic-runtime:delivery:1",
        }

        delivered = client.post(delivery_path, headers=headers, json=delivery_payload)
        assert delivered.status_code == 200
        assert delivered.json()["created"] is True
        status = delivered.json()["delivery"]
        assert status["state"] == "completed"
        assert status["client_adapter"] == "client.fake"
        assert status["destination_ref"] == "synthetic:owner"
        attempt = status["attempts"][0]
        assert attempt["adapter_receipt"]["message_id"] == output_message_id
        assert attempt["adapter_receipt"]["adapter_metadata"]["deduplicated"] is False
        assert attempt["execution_receipt"]["action_hash"] == status["action_hash"]

        duplicate = client.post(delivery_path, headers=headers, json=delivery_payload)
        assert duplicate.status_code == 200
        assert duplicate.json()["created"] is False
        assert duplicate.json()["delivery"] == status
        assert client.get(delivery_path).json() == [status]
        retention = client.get("/api/v1/retention").json()
        delivery_inventory = next(
            item
            for item in retention["inventory"]
            if item["policy_id"] == "retention.owner-delivery"
        )
        assert delivery_inventory["coverage"] == "complete"
        assert delivery_inventory["retained_objects"] == 2
        assert delivery_inventory["retained_bytes"] > 0
        assert delivery_inventory["deletion_receipts"] == 0
        assert delivery_inventory["oldest_retained_at"] is not None
        export = client.get("/api/v1/inspection/export").json()
        export_coverage = {item["group_id"]: item for item in export["coverage"]}
        assert export_coverage["export.delivery-records"]["estimated_records"] == 1

        health = client.get("/api/v1/inspection/health").json()
        delivery_worker = next(
            component
            for component in health["components"]
            if component["component_id"] == "worker.synthetic-delivery"
        )
        assert delivery_worker["state"] == "healthy"
        retention_worker = next(
            component
            for component in health["components"]
            if component["component_id"] == "worker.synthetic-retention"
        )
        assert retention_worker["state"] == "healthy"
        assert retention_worker["required"] is False


def test_synthetic_runtime_polls_telegram_without_network_or_duplicate_history(
    fixed_time,
) -> None:
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic-telegram",
        ),
        receipt_hash="sha256:" + "4" * 64,
    )
    identifiers = count(300)

    def id_factory(prefix: str) -> str:
        return f"{prefix}_{next(identifiers):032x}"

    runtime = build_synthetic_runtime(
        guardian,
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        id_factory=id_factory,
        telegram_worker_interval=0.01,
        telegram_retention_worker_interval=0.01,
    )
    start = TelegramInboundUpdate(
        update_id=50,
        message=TelegramInboundMessage(
            telegram_message_id=51,
            sender_user_id=1001,
            chat_id=1001,
            chat_type=TelegramChatType.PRIVATE,
            sent_at=fixed_time,
            text="/start",
        ),
        received_at=fixed_time,
        raw_size_bytes=256,
        source_payload_hash=sha256_digest(b"synthetic-runtime-telegram-start-50"),
    )
    runtime.telegram_source.add_update(start)

    with TestClient(runtime.app, base_url="https://testserver") as client:
        login = client.post(
            "/api/v1/auth/session",
            json={"credential": _BOOTSTRAP_TOKEN},
        )
        assert login.status_code == 200
        headers = {"X-Melloa-CSRF": login.json()["csrf_token"]}

        _wait_for_telegram_revision(runtime, 1)
        candidates = client.get(
            "/api/v1/integrations/telegram/pairing/candidates"
        ).json()
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["telegram_user_id"] == 1001
        assert candidate["telegram_chat_id"] == 1001
        assert "confirmation_code_hash" not in candidate
        challenge = runtime.telegram_challenge_publisher.challenge_for(
            candidate["candidate_id"]
        )
        confirmed = client.post(
            "/api/v1/integrations/telegram/pairing/candidates/"
            f"{candidate['candidate_id']}/confirm",
            headers=headers,
            json={"confirmation_code": challenge.confirmation_code},
        )
        assert confirmed.status_code == 200
        pairing = confirmed.json()
        assert pairing["owner_id"] == runtime.owner_id
        assert pairing["confirmed_by_owner_id"] == runtime.owner_id
        assert client.get("/api/v1/integrations/telegram/pairing").json() == pairing

        inbound = TelegramInboundUpdate(
            update_id=51,
            message=TelegramInboundMessage(
                telegram_message_id=52,
                sender_user_id=1001,
                chat_id=1001,
                chat_type=TelegramChatType.PRIVATE,
                sent_at=fixed_time,
                text="Synthetic secondary-channel intake",
                attachments=(
                    TelegramAttachmentReference(
                        kind=TelegramAttachmentKind.DOCUMENT,
                        file_id="synthetic-runtime-file-51",
                        file_unique_id="synthetic-runtime-unique-51",
                        declared_size_bytes=64,
                        media_type="text/plain",
                        file_name="runtime-attachment.txt",
                    ),
                ),
            ),
            received_at=fixed_time,
            raw_size_bytes=256,
            source_payload_hash=sha256_digest(
                b"synthetic-runtime-telegram-update-51"
            ),
        )
        runtime.telegram_source.add_update(inbound)
        _wait_for_telegram_revision(runtime, 2)
        messages = client.get(f"/api/v1/conversations/{runtime.telegram_thread_id}/messages")
        assert messages.status_code == 200
        telegram_messages = [
            message
            for message in messages.json()
            if message["source_client"] == SYNTHETIC_TELEGRAM_ADAPTER_ID
        ]
        assert len(telegram_messages) == 1
        assert telegram_messages[0]["parts"] == [
            {
                "kind": "text",
                "text": inbound.message.text,
                "attachment_id": None,
                "media_type": None,
                "content_hash": None,
            }
        ]
        assert telegram_messages[0]["author_principal_id"] == runtime.owner_id
        attachment_requests = runtime.telegram_attachment_backend.requests
        assert len(attachment_requests) == 1
        assert attachment_requests[0].attachments == inbound.message.attachments
        receipt = runtime.telegram_poll_state_store.get_receipt(
            SYNTHETIC_TELEGRAM_ADAPTER_ID,
            inbound.update_id,
        )
        assert receipt is not None
        assert receipt.attachment_receipts[0].disposition is (
            TelegramAttachmentDisposition.REJECTED
        )
        assert receipt.attachment_receipts[0].reason_code == (
            "telegram.attachment.unsupported"
        )
        assert runtime.telegram_source.health()["network"] is False

        revoked = client.post(
            "/api/v1/integrations/telegram/pairing/"
            f"{pairing['pairing_id']}/revoke",
            headers=headers,
        )
        assert revoked.status_code == 200
        assert revoked.json()["revoked_at"] is not None
        assert client.get("/api/v1/integrations/telegram/pairing").json() is None

        runtime.telegram_source.add_update(
            TelegramInboundUpdate(
                update_id=52,
                message=TelegramInboundMessage(
                    telegram_message_id=53,
                    sender_user_id=1001,
                    chat_id=1001,
                    chat_type=TelegramChatType.PRIVATE,
                    sent_at=fixed_time,
                    text="Rejected after local revocation",
                ),
                received_at=fixed_time,
                raw_size_bytes=256,
                source_payload_hash=sha256_digest(
                    b"synthetic-runtime-telegram-update-52"
                ),
            )
        )
        _wait_for_telegram_revision(runtime, 3)
        messages_after_revocation = client.get(
            f"/api/v1/conversations/{runtime.telegram_thread_id}/messages"
        ).json()
        assert len(
            [
                message
                for message in messages_after_revocation
                if message["source_client"] == SYNTHETIC_TELEGRAM_ADAPTER_ID
            ]
        ) == 1

        health = client.get("/api/v1/inspection/health").json()
        telegram_worker = next(
            component
            for component in health["components"]
            if component["component_id"] == "worker.synthetic-telegram"
        )
        assert telegram_worker["state"] == "healthy"
        assert telegram_worker["required"] is False
        retention_worker = next(
            component
            for component in health["components"]
            if component["component_id"] == "worker.synthetic-retention"
        )
        assert retention_worker["state"] == "healthy"
        assert retention_worker["required"] is False
        assert runtime.telegram_attachment_backend.sweeps
        assert set(runtime.telegram_attachment_backend.sweeps) == {(fixed_time, 100)}


def _wait_for_telegram_revision(runtime, revision: int) -> None:
    for _ in range(100):
        poll_state = runtime.telegram_poll_state_store.read_state(
            SYNTHETIC_TELEGRAM_ADAPTER_ID
        )
        if poll_state.revision == revision:
            return
        time.sleep(0.01)
    raise AssertionError("synthetic Telegram worker did not advance its cursor")


def _wait_for_telegram_retention_sweep(runtime) -> None:
    for _ in range(100):
        if runtime.telegram_attachment_backend.sweeps:
            return
        time.sleep(0.01)
    raise AssertionError("synthetic Telegram retention worker did not run")
