from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime

from fastapi.testclient import TestClient

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.application.conversation import ConversationService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.core import create_app
from melloa.domain.audit import AuditContent, AuditRecord
from melloa.domain.base import JsonObject
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import ConversationThread
from melloa.domain.events import EventEnvelope
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from tests.conftest import record_id

_BOOTSTRAP_TOKEN = "synthetic-bootstrap-token-value-0001"


class FailingOnceEventAuditStore(InMemoryEventAuditStore):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    def append_event(
        self,
        event: EventEnvelope,
        audit: AuditContent,
    ) -> AuditRecord | None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("synthetic audit append failure")
        return super().append_event(event, audit)


def _sequential_id_factory() -> Callable[[str], str]:
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return record_id(prefix, counts[prefix])

    return create


def _guardian(fixed_time: datetime) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="synthetic-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def _client(
    fixed_time: datetime,
    *,
    response: JsonObject | Callable[[object], JsonObject] | None = None,
    max_processing_attempts: int = 3,
    event_audit_store: InMemoryEventAuditStore | None = None,
    raise_server_exceptions: bool = True,
    session_owner_number: int = 1,
    seed_owned_thread: bool = False,
) -> tuple[TestClient, FakeModelGateway]:
    id_factory = _sequential_id_factory()
    tokens = iter(("session-one", "csrf-one", "session-two", "csrf-two"))
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", session_owner_number),
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    model = FakeModelGateway(
        {"text": "Synthetic authenticated reply."} if response is None else response,
        clock=lambda: fixed_time,
        id_factory=id_factory,
    )
    store = InMemoryConversationStore(id_factory=id_factory)
    conversation = ConversationService(
        owner_id=record_id("owner", 1),
        intelligence_id=record_id("intelligence", 1),
        store=store,
        model_gateway=model,
        retriever=PolicyConstrainedRetriever(
            InMemoryMemoryRepository(),
            clock=lambda: fixed_time,
            id_factory=id_factory,
        ),
        guardian_reader=_guardian(fixed_time),
        clock=lambda: fixed_time,
        id_factory=id_factory,
        max_processing_attempts=max_processing_attempts,
    )
    if seed_owned_thread:
        store.create_thread(
            ConversationThread(
                thread_id=record_id("thread", 42),
                owner_id=record_id("owner", 1),
                intelligence_id=record_id("intelligence", 1),
                title="Concealed owner thread",
                sensitivity=Sensitivity.PERSONAL,
                retention_policy="retention.owner-conversation",
                created_at=fixed_time,
                updated_at=fixed_time,
            )
        )
    app = create_app(
        _guardian(fixed_time),
        sessions,
        conversation,
        owner_id=record_id("owner", 1) if event_audit_store is not None else None,
        event_audit_store=event_audit_store,
        security_event_clock=lambda: fixed_time,
        security_event_id_factory=id_factory,
    )
    return (
        TestClient(
            app,
            base_url="https://testserver",
            raise_server_exceptions=raise_server_exceptions,
        ),
        model,
    )


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _create_thread(client: TestClient, csrf: str) -> str:
    response = client.post(
        "/api/v1/conversations",
        headers={"X-Melloa-CSRF": csrf},
        json={
            "title": "Canonical audit thread",
            "sensitivity": "personal",
            "retention_policy": "retention.owner-conversation",
        },
    )
    assert response.status_code == 201
    return response.json()["thread_id"]


def _audit_json(audit_store: InMemoryEventAuditStore) -> str:
    return "\n".join(
        (
            *(event.model_dump_json() for event in audit_store.events),
            *(record.model_dump_json() for record in audit_store.audit_records),
        )
    )


def test_conversation_api_appends_content_free_audit_for_accept_success_and_denial(
    fixed_time: datetime,
) -> None:
    audit_store = InMemoryEventAuditStore()
    client, _model = _client(fixed_time, event_audit_store=audit_store)
    csrf = _login(client)
    thread_id = _create_thread(client, csrf)
    path = f"/api/v1/conversations/{thread_id}/messages"

    accepted = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json={
            "text": "Owner private request.",
            "idempotency_key": "browser:message:audit:1",
        },
    )
    conflict = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json={
            "text": "Changed private request.",
            "idempotency_key": "browser:message:audit:1",
        },
    )
    missing_thread = client.post(
        f"/api/v1/conversations/{record_id('thread', 99)}/messages",
        headers={"X-Melloa-CSRF": csrf},
        json={
            "text": "Missing thread request.",
            "idempotency_key": "browser:message:audit:missing",
        },
    )

    assert accepted.status_code == 200
    assert conflict.status_code == 409
    assert missing_thread.status_code == 404
    assert tuple(event.event_type for event in audit_store.events) == (
        "conversation.owner-message-accept-accepted.v1",
        "conversation.owner-message-accept-denied.v1",
        "conversation.owner-message-accept-denied.v1",
    )
    accepted_payload = audit_store.events[0].payload
    assert accepted_payload == {
        "attempt_count": 1,
        "duplicate": False,
        "max_attempts": 3,
        "message_id": accepted.json()["inbound_message"]["message_id"],
        "operation": "accept",
        "output_message_id": accepted.json()["output_message"]["message_id"],
        "processing_state": "completed",
        "reason_code": "conversation.owner_message_accept.accepted",
        "result": "accepted",
        "resumption_count": 0,
        "thread_id": thread_id,
        "turn_id": accepted.json()["turn"]["turn_id"],
        "work_id": accepted.json()["processing"]["work_id"],
    }
    assert audit_store.events[1].payload == {
        "operation": "accept",
        "reason_code": "conversation.conflict",
        "result": "denied",
        "thread_id": thread_id,
    }
    assert audit_store.events[2].payload == {
        "operation": "accept",
        "reason_code": "conversation.not_found",
        "result": "denied",
        "thread_id": record_id("thread", 99),
    }
    audit_json = _audit_json(audit_store)
    assert "Owner private request." not in audit_json
    assert "Changed private request." not in audit_json
    assert "Missing thread request." not in audit_json
    assert "Synthetic authenticated reply." not in audit_json
    assert "browser:message:audit" not in audit_json
    assert "m1-conversation-v1" not in audit_json
    assert "citation" not in audit_json
    assert "external_disclosure" not in audit_json
    assert _BOOTSTRAP_TOKEN not in audit_json
    assert "session-one" not in audit_json
    assert "csrf-one" not in audit_json
    assert "action_hash" not in audit_json


def test_conversation_api_appends_content_free_audit_for_resume_success_and_denial(
    fixed_time: datetime,
) -> None:
    audit_store = InMemoryEventAuditStore()
    invocations = 0

    def recovering_response(_request: object) -> JsonObject:
        nonlocal invocations
        invocations += 1
        return {"unexpected": True} if invocations == 1 else {"text": "Recovered reply."}

    client, _model = _client(
        fixed_time,
        response=recovering_response,
        max_processing_attempts=1,
        event_audit_store=audit_store,
    )
    csrf = _login(client)
    thread_id = _create_thread(client, csrf)
    accepted = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers={"X-Melloa-CSRF": csrf},
        json={
            "text": "Recover this private request.",
            "idempotency_key": "browser:message:resume:1",
        },
    )
    message_id = accepted.json()["inbound_message"]["message_id"]

    resumed = client.post(
        f"/api/v1/conversations/{thread_id}/messages/{message_id}/resume",
        headers={"X-Melloa-CSRF": csrf},
    )
    denied = client.post(
        f"/api/v1/conversations/{thread_id}/messages/{record_id('message', 99)}/resume",
        headers={"X-Melloa-CSRF": csrf},
    )

    assert accepted.status_code == 202
    assert resumed.status_code == 200
    assert denied.status_code == 404
    assert tuple(event.event_type for event in audit_store.events) == (
        "conversation.owner-message-accept-accepted.v1",
        "conversation.owner-message-resume-accepted.v1",
        "conversation.owner-message-resume-denied.v1",
    )
    assert audit_store.events[1].payload == {
        "attempt_count": 2,
        "duplicate": True,
        "max_attempts": 2,
        "message_id": message_id,
        "operation": "resume",
        "output_message_id": resumed.json()["output_message"]["message_id"],
        "processing_state": "completed",
        "reason_code": "conversation.owner_message_resume.accepted",
        "result": "accepted",
        "resumption_count": 1,
        "thread_id": thread_id,
        "turn_id": resumed.json()["turn"]["turn_id"],
        "work_id": resumed.json()["processing"]["work_id"],
    }
    assert audit_store.events[2].payload == {
        "message_id": record_id("message", 99),
        "operation": "resume",
        "reason_code": "conversation.not_found",
        "result": "denied",
        "thread_id": thread_id,
    }
    audit_json = _audit_json(audit_store)
    assert "Recover this private request." not in audit_json
    assert "Recovered reply." not in audit_json
    assert "browser:message:resume:1" not in audit_json
    assert "m1-conversation-v1" not in audit_json
    assert "citation" not in audit_json
    assert "unexpected" not in audit_json
    assert "external_disclosure" not in audit_json
    assert _BOOTSTRAP_TOKEN not in audit_json
    assert "session-one" not in audit_json
    assert "csrf-one" not in audit_json
    assert "action_hash" not in audit_json


def test_conversation_api_conceals_and_audits_foreign_owner_denials(
    fixed_time: datetime,
) -> None:
    audit_store = InMemoryEventAuditStore()
    client, _model = _client(
        fixed_time,
        event_audit_store=audit_store,
        session_owner_number=2,
        seed_owned_thread=True,
    )
    csrf = _login(client)
    thread_id = record_id("thread", 42)

    accept_denied = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers={"X-Melloa-CSRF": csrf},
        json={
            "text": "Foreign owner text must stay concealed.",
            "idempotency_key": "browser:message:foreign-owner",
        },
    )
    resume_denied = client.post(
        f"/api/v1/conversations/{thread_id}/messages/"
        f"{record_id('message', 99)}/resume",
        headers={"X-Melloa-CSRF": csrf},
    )

    assert accept_denied.status_code == 404
    assert accept_denied.json()["code"] == "conversation_not_found"
    assert resume_denied.status_code == 404
    assert resume_denied.json()["code"] == "conversation_not_found"
    assert tuple(event.event_type for event in audit_store.events) == (
        "conversation.owner-message-accept-denied.v1",
        "conversation.owner-message-resume-denied.v1",
    )
    assert tuple(event.payload["reason_code"] for event in audit_store.events) == (
        "conversation.not_found",
        "conversation.not_found",
    )
    audit_json = _audit_json(audit_store)
    assert "Foreign owner text must stay concealed." not in audit_json
    assert "browser:message:foreign-owner" not in audit_json
    assert _BOOTSTRAP_TOKEN not in audit_json
    assert "session-one" not in audit_json
    assert "csrf-one" not in audit_json


def test_conversation_audit_failure_after_acceptance_can_be_retried_by_idempotency(
    fixed_time: datetime,
) -> None:
    audit_store = FailingOnceEventAuditStore()
    client, model = _client(
        fixed_time,
        event_audit_store=audit_store,
        raise_server_exceptions=False,
    )
    csrf = _login(client)
    thread_id = _create_thread(client, csrf)
    payload = {
        "text": "Persisted before audit failure.",
        "idempotency_key": "browser:message:audit-failure",
    }

    failed = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers={"X-Melloa-CSRF": csrf},
        json=payload,
    )
    retried = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers={"X-Melloa-CSRF": csrf},
        json=payload,
    )

    assert failed.status_code == 500
    assert retried.status_code == 200
    assert retried.json()["duplicate"] is True
    assert len(model.requests) == 1
    messages = client.get(f"/api/v1/conversations/{thread_id}/messages")
    turns = client.get(f"/api/v1/conversations/{thread_id}/turns")
    assert messages.status_code == 200
    assert turns.status_code == 200
    assert len(messages.json()) == 2
    assert len(turns.json()) == 1
    assert messages.json()[0]["message_id"] == retried.json()["inbound_message"][
        "message_id"
    ]
    assert len(audit_store.events) == 1
    assert audit_store.events[0].payload["duplicate"] is True
    assert audit_store.events[0].payload["processing_state"] == "completed"
    audit_json = _audit_json(audit_store)
    assert "Persisted before audit failure." not in audit_json
    assert "browser:message:audit-failure" not in audit_json
    assert "Synthetic authenticated reply." not in audit_json
    assert _BOOTSTRAP_TOKEN not in audit_json
    assert "session-one" not in audit_json
    assert "csrf-one" not in audit_json
