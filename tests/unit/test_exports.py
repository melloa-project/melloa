from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.application.conversation import ConversationService
from melloa.application.exports import OwnerExportService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.runtime import build_runtime
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import Assertion, AssertionStatus, ProvenanceEdge, ProvenanceRelation
from melloa.domain.models import ModelRoute, ProcessingLocation
from melloa.ports.memory import AssertionContentDeletionWrite
from melloa.ports.model import ModelInvocationError
from tests.conftest import record_id

_OWNER_CREDENTIAL = "owner-export-test-credential-value-0001"


def _ids() -> Callable[[str], str]:
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return record_id(prefix, counts[prefix])

    return create


def _guardian(observed_at: datetime) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="export-test-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=observed_at,
            reason_code="guardian.test",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def test_authenticated_owner_downloads_small_provider_independent_archive(fixed_time) -> None:
    runtime = build_runtime(
        _guardian(fixed_time),
        _OWNER_CREDENTIAL,
        clock=lambda: fixed_time,
        id_factory=_ids(),
    )
    with TestClient(runtime.app, base_url="https://testserver") as client:
        assert client.get("/api/v1/data-export").status_code == 401
        login = client.post(
            "/api/v1/auth/session",
            json={"credential": _OWNER_CREDENTIAL},
        )
        csrf = login.json()["csrf_token"]
        headers = {"X-Melloa-CSRF": csrf}
        created = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={
                "title": "A private plan",
                "sensitivity": "personal",
            },
        )
        assert created.status_code == 201
        thread_id = created.json()["thread_id"]
        accepted = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=headers,
            json={
                "text": "Remember the context, not this credential.",
                "idempotency_key": "export-message-1",
            },
        )
        assert accepted.status_code == 202

        readiness = client.get("/api/v1/data-export")
        assert readiness.status_code == 200
        assert [item["group"] for item in readiness.json()["coverage"]] == [
            "conversation-history",
            "answer-provenance",
            "memory-history",
            "conversation-deletion-receipts",
            "account-and-security-history",
            "system-events-and-audit-history",
        ]
        assert [item["included"] for item in readiness.json()["coverage"]] == [
            True,
            True,
            True,
            False,
            False,
            False,
        ]
        assert readiness.json()["encrypted"] is False
        assert any(
            "not encrypted" in limitation
            for limitation in readiness.json()["limitations"]
        )

        response = client.post("/api/v1/data-export/archive", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "melloa-owner-export-" in response.headers["content-disposition"]
    assert _OWNER_CREDENTIAL.encode() not in response.content

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "conversations.json",
            "memories.json",
        }
        manifest = json.loads(archive.read("manifest.json"))
        conversation_content = archive.read("conversations.json")
        memory_content = archive.read("memories.json")
        conversations = json.loads(conversation_content)
        memories = json.loads(memory_content)

    assert manifest["format"] == "melloa-owner-export-v2"
    assert manifest["encrypted"] is False
    assert [item["group"] for item in manifest["coverage"] if not item["included"]] == [
        "conversation-deletion-receipts",
        "account-and-security-history",
        "system-events-and-audit-history",
    ]
    assert any("Backups are separate" in item for item in manifest["limitations"])
    assert {item["path"] for item in manifest["files"]} == {
        "conversations.json",
        "memories.json",
    }
    content_by_path = {
        "conversations.json": conversation_content,
        "memories.json": memory_content,
    }
    for item in manifest["files"]:
        assert item["sha256"] == hashlib.sha256(content_by_path[item["path"]]).hexdigest()
    assert conversations["conversations"][0]["thread"]["title"] == "A private plan"
    assert conversations["conversations"][0]["messages"][0]["parts"][0]["text"].startswith(
        "Remember the context"
    )
    assert conversations["conversations"][0]["answer_provenance"] == []
    assert conversations["conversations"][0]["processing"][0]["state"] == "ready"
    assert memories == {"assertions": [], "provenance_edges": []}


def test_export_preserves_retained_and_deleted_memory_history(fixed_time) -> None:
    retained = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=record_id("owner", 1),
        predicate="preference.exported",
        value={"statement": "Keep this value."},
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=fixed_time,
    )
    deleted = Assertion(
        assertion_id=record_id("assertion", 2),
        subject_id=retained.subject_id,
        predicate="preference.deleted",
        value={"statement": "Remove this value."},
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=fixed_time,
    )
    edge = ProvenanceEdge(
        edge_id=record_id("edge", 1),
        from_id=retained.assertion_id,
        to_id=deleted.assertion_id,
        relation=ProvenanceRelation.SUPPORTS,
        created_at=fixed_time,
        producer_id=record_id("intelligence", 1),
    )
    memory = InMemoryMemoryRepository((retained, deleted), (edge,))
    memory.delete_assertion_content(
        AssertionContentDeletionWrite(
            assertion_id=deleted.assertion_id,
            owner_id=retained.subject_id,
            tombstone_id=record_id("tombstone", 1),
            rebuild_work_id=record_id("work", 1),
            deleted_by_record_id=retained.subject_id,
            deleted_at=fixed_time,
            reason_code="owner.requested-deletion",
        )
    )
    principal = AuthenticatedOwner(
        owner_id=retained.subject_id,
        session_id=record_id("session", 1),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )
    ids = _ids()
    conversation = ConversationService(
        owner_id=retained.subject_id,
        intelligence_id=record_id("intelligence", 1),
        store=InMemoryConversationStore(id_factory=ids),
        model_gateway=FakeModelGateway(
            {"text": "Exported answer provenance."},
            clock=lambda: fixed_time,
            id_factory=ids,
        ),
        retriever=PolicyConstrainedRetriever(
            memory,
            clock=lambda: fixed_time,
            id_factory=ids,
        ),
        guardian_reader=_guardian(fixed_time),
        clock=lambda: fixed_time,
        id_factory=ids,
    )
    thread = conversation.create_thread(
        principal,
        title="Exported conversation",
        sensitivity=Sensitivity.PERSONAL,
    )
    conversation.post_owner_message(
        principal,
        thread_id=thread.thread_id,
        text="Include why this answer was produced.",
        idempotency_key="export-provenance",
    )
    service = OwnerExportService(
        owner_id=retained.subject_id,
        conversation=conversation,
        memory=memory,
        clock=lambda: fixed_time,
        id_factory=_ids(),
    )

    archive = service.build_archive(principal)

    with zipfile.ZipFile(io.BytesIO(archive.content)) as exported:
        conversations = json.loads(exported.read("conversations.json"))
        memories = json.loads(exported.read("memories.json"))
    provenance = conversations["conversations"][0]["answer_provenance"][0]
    assert provenance["model_result"]["output"]["text"] == (
        "Exported answer provenance."
    )
    assert provenance["retrieval_manifest"]["external_disclosure"] is False
    assert conversations["conversations"][0]["processing"][0]["state"] == "completed"
    assert [item["content_state"] for item in memories["assertions"]] == [
        "retained",
        "deleted",
    ]
    assert memories["assertions"][0]["assertion"]["value"] == {
        "statement": "Keep this value."
    }
    assert "value" not in memories["assertions"][1]["assertion"]
    assert memories["assertions"][1]["deletion_tombstone"]["assertion_id"] == (
        deleted.assertion_id
    )
    assert memories["assertions"][1]["state_changes"][0]["version"] == 1
    assert memories["provenance_edges"][0]["edge_id"] == edge.edge_id


def test_export_includes_failed_external_destination_without_provider_output(
    fixed_time,
) -> None:
    owner_id = record_id("owner", 1)
    memory = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=owner_id,
        predicate="preference.export-disclosure",
        value={"statement": "Use this context carefully."},
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=fixed_time,
    )
    repository = InMemoryMemoryRepository((memory,))
    principal = AuthenticatedOwner(
        owner_id=owner_id,
        session_id=record_id("session", 1),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )

    def fail_external(_request):
        raise ModelInvocationError(
            provider_id="provider.export-approved",
            model_id="export-model-v1",
            processing_location=ProcessingLocation.APPROVED_PROVIDER,
            route=ModelRoute.ECONOMY,
        )

    ids = _ids()
    conversation = ConversationService(
        owner_id=owner_id,
        intelligence_id=record_id("intelligence", 1),
        store=InMemoryConversationStore(id_factory=ids),
        model_gateway=FakeModelGateway(
            fail_external,
            clock=lambda: fixed_time,
            id_factory=ids,
        ),
        retriever=PolicyConstrainedRetriever(
            repository,
            clock=lambda: fixed_time,
            id_factory=ids,
        ),
        guardian_reader=_guardian(fixed_time),
        clock=lambda: fixed_time,
        id_factory=ids,
    )
    thread = conversation.create_thread(
        principal,
        title="Exported disclosure",
        sensitivity=Sensitivity.PERSONAL,
    )
    conversation.post_owner_message(
        principal,
        thread_id=thread.thread_id,
        text="Use the context with the external model.",
        idempotency_key="export-failed-disclosure",
    )
    service = OwnerExportService(
        owner_id=owner_id,
        conversation=conversation,
        memory=repository,
        clock=lambda: fixed_time,
        id_factory=_ids(),
    )

    archive = service.build_archive(principal)

    with zipfile.ZipFile(io.BytesIO(archive.content)) as exported:
        conversations = json.loads(exported.read("conversations.json"))
    attempt = conversations["conversations"][0]["processing"][0]["attempts"][0]
    assert attempt["failed_model_target"] == {
        "provider_id": "provider.export-approved",
        "model_id": "export-model-v1",
        "processing_location": "approved_provider",
        "route": "economy",
    }
    assert attempt["disclosed_memory_ids"] == [memory.assertion_id]
    assert attempt["model_result_summary"] is None
    assert conversations["conversations"][0]["answer_provenance"] == []
