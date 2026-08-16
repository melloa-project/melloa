from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.guardian.file import GuardianVerificationError
from melloa.application.conversation import ConversationService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.core import create_app
from melloa.domain.classification import Sensitivity
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
