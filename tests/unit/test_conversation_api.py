from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from threading import Event, Thread

from fastapi.testclient import TestClient

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.application.conversation import ConversationService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.core import create_app
from melloa.domain.base import JsonObject
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import ConversationThread
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.models import ModelRequest, ProcessingLocation
from melloa.ports.model import ModelInvocationError
from tests.conftest import record_id

_BOOTSTRAP_TOKEN = "owner-conversation-test-credential-0001"


def _ids() -> Callable[[str], str]:
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return record_id(prefix, counts[prefix])

    return create


def _guardian(
    observed_at: datetime,
    mode: GuardianMode = GuardianMode.NORMAL,
) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="conversation-test-guardian",
            mode=mode,
            sequence=1,
            changed_at=observed_at,
            reason_code="guardian.test",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def _client(
    fixed_time: datetime,
    *,
    owner_number: int = 1,
    guardian_mode: GuardianMode = GuardianMode.NORMAL,
    seed_thread: bool = False,
    expose_model_health: bool = True,
    model_response: JsonObject | Callable[[ModelRequest], JsonObject] | None = None,
) -> TestClient:
    owner_id = record_id("owner", 1)
    ids = _ids()
    store = InMemoryConversationStore(id_factory=ids)
    if seed_thread:
        store.create_thread(
            ConversationThread(
                thread_id=record_id("thread", 42),
                owner_id=owner_id,
                intelligence_id=record_id("intelligence", 1),
                title="Private owner thread",
                sensitivity=Sensitivity.PERSONAL,
                created_at=fixed_time,
                updated_at=fixed_time,
            )
        )
    guardian = _guardian(fixed_time, guardian_mode)
    model = FakeModelGateway(
        {"text": "I have the context."} if model_response is None else model_response,
        clock=lambda: fixed_time,
        id_factory=ids,
    )
    service = ConversationService(
        owner_id=owner_id,
        intelligence_id=record_id("intelligence", 1),
        store=store,
        model_gateway=model,
        retriever=PolicyConstrainedRetriever(
            InMemoryMemoryRepository(),
            clock=lambda: fixed_time,
            id_factory=ids,
        ),
        guardian_reader=guardian,
        clock=lambda: fixed_time,
        id_factory=ids,
    )
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", owner_number),
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
    )
    return TestClient(
        create_app(
            guardian,
            sessions,
            service,
            model_health=model.health if expose_model_health else None,
        ),
        base_url="https://testserver",
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert response.status_code == 200
    return {"X-Melloa-CSRF": response.json()["csrf_token"]}


def test_conversation_availability_is_owner_only_and_reflects_model_health(
    fixed_time,
) -> None:
    with _client(fixed_time) as available_client:
        assert available_client.get("/api/v1/conversations/availability").status_code == 401
        _login(available_client)
        assert available_client.get("/api/v1/conversations/availability").json() == {
            "available": True
        }

    with _client(fixed_time, expose_model_health=False) as unavailable_client:
        _login(unavailable_client)
        assert unavailable_client.get("/api/v1/conversations/availability").json() == {
            "available": False
        }


def test_owner_conversation_round_trip_uses_one_transcript_read(fixed_time) -> None:
    client = _client(fixed_time)
    assert client.get("/api/v1/conversations").status_code == 401
    headers = _login(client)
    assert (
        client.post(
            "/api/v1/conversations",
            json={
                "title": "Context that should persist",
                "sensitivity": "personal",
            },
        ).status_code
        == 403
    )
    created = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={
            "title": "Context that should persist",
            "sensitivity": "personal",
        },
    )
    assert created.status_code == 201
    thread_id = created.json()["thread_id"]

    sent = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers=headers,
        json={
            "text": "My sister is visiting next week.",
            "idempotency_key": "owner-message-1",
        },
    )
    assert sent.status_code == 200
    assert sent.json()["output_message"]["parts"][0]["text"] == "I have the context."

    transcript = client.get(f"/api/v1/conversations/{thread_id}/transcript")
    assert transcript.status_code == 200
    document = transcript.json()
    assert [item["parts"][0]["text"] for item in document["messages"]] == [
        "My sister is visiting next week.",
        "I have the context.",
    ]
    assert len(document["turns"]) == 1
    assert document["processing"][0]["state"] == "completed"


def test_failed_external_destination_is_returned_and_remains_in_transcript(
    fixed_time,
) -> None:
    def fail_external(_request: ModelRequest) -> JsonObject:
        raise ModelInvocationError(
            provider_id="provider.approved-test",
            model_id="capable-external-v1",
            processing_location=ProcessingLocation.APPROVED_PROVIDER,
        )

    client = _client(fixed_time, model_response=fail_external)
    headers = _login(client)
    created = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "External failure", "sensitivity": "personal"},
    )
    thread_id = created.json()["thread_id"]

    sent = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers=headers,
        json={
            "text": "Use the approved model.",
            "idempotency_key": "failed-external-destination",
        },
    )

    assert sent.status_code == 202
    attempt = sent.json()["processing"]["attempts"][0]
    assert attempt["external_disclosure"] is True
    assert attempt["failed_model_target"] == {
        "provider_id": "provider.approved-test",
        "model_id": "capable-external-v1",
        "processing_location": "approved_provider",
    }
    assert attempt["model_result_summary"] is None

    transcript = client.get(f"/api/v1/conversations/{thread_id}/transcript")
    assert transcript.status_code == 200
    assert transcript.json()["processing"][0]["attempts"][0] == attempt


def test_owner_can_correct_a_message_with_transcript_provenance(fixed_time) -> None:
    client = _client(fixed_time)
    headers = _login(client)
    created = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "Correctable history", "sensitivity": "personal"},
    )
    assert created.status_code == 201
    thread_id = created.json()["thread_id"]
    sent = client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers=headers,
        json={
            "text": "My sister arrives Tuesday.",
            "idempotency_key": "correction-original",
        },
    )
    assert sent.status_code == 200
    original_id = sent.json()["inbound_message"]["message_id"]
    original_reply_id = sent.json()["output_message"]["message_id"]
    correction_path = (
        f"/api/v1/conversations/{thread_id}/messages/{original_id}/correction"
    )

    missing_csrf = client.post(
        correction_path,
        json={
            "text": "My sister arrives Thursday.",
            "idempotency_key": "correction-valid",
        },
    )
    assert missing_csrf.status_code == 403
    no_change = client.post(
        correction_path,
        headers=headers,
        json={
            "text": "  My sister arrives Tuesday.  ",
            "idempotency_key": "correction-no-change",
        },
    )
    assert no_change.status_code == 409
    melli_target = client.post(
        f"/api/v1/conversations/{thread_id}/messages/{original_reply_id}/correction",
        headers=headers,
        json={
            "text": "An owner cannot rewrite Melli's answer.",
            "idempotency_key": "correction-melli-target",
        },
    )
    assert melli_target.status_code == 404

    corrected = client.post(
        correction_path,
        headers=headers,
        json={
            "text": "My sister arrives Thursday.",
            "idempotency_key": "correction-valid",
        },
    )
    assert corrected.status_code == 200
    corrected_document = corrected.json()
    corrected_id = corrected_document["inbound_message"]["message_id"]
    assert corrected_document["inbound_message"]["corrects_message_id"] == original_id
    assert corrected_document["output_message"]["reply_to_message_id"] == corrected_id

    duplicate = client.post(
        correction_path,
        headers=headers,
        json={
            "text": "My sister arrives Thursday.",
            "idempotency_key": "correction-valid",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    second_correction = client.post(
        correction_path,
        headers=headers,
        json={
            "text": "My sister arrives Friday.",
            "idempotency_key": "correction-second",
        },
    )
    assert second_correction.status_code == 409

    transcript = client.get(f"/api/v1/conversations/{thread_id}/transcript")
    assert transcript.status_code == 200
    document = transcript.json()
    assert sorted(item["parts"][0]["text"] for item in document["messages"]) == sorted([
        "My sister arrives Tuesday.",
        "I have the context.",
        "My sister arrives Thursday.",
        "I have the context.",
    ])
    corrected_transcript_message = next(
        item for item in document["messages"] if item["message_id"] == corrected_id
    )
    assert corrected_transcript_message["corrects_message_id"] == original_id
    corrected_turn = next(
        turn for turn in document["turns"] if turn["triggering_message_ids"] == [corrected_id]
    )
    assert corrected_turn["decision_record"]["corrects_message_id"] == original_id


def test_foreign_owner_cannot_discover_a_thread(fixed_time) -> None:
    client = _client(fixed_time, owner_number=2, seed_thread=True)
    _login(client)

    assert (
        client.get(
            f"/api/v1/conversations/{record_id('thread', 42)}/transcript"
        ).status_code
        == 404
    )


def test_recently_confirmed_owner_can_delete_active_conversation_data(fixed_time) -> None:
    client = _client(
        fixed_time,
        guardian_mode=GuardianMode.STOPPED,
        seed_thread=True,
    )
    thread_id = record_id("thread", 42)

    assert client.delete(f"/api/v1/conversations/{thread_id}").status_code == 401
    headers = _login(client)
    assert (
        client.delete(f"/api/v1/conversations/{thread_id}").status_code == 403
    )

    deleted = client.delete(
        f"/api/v1/conversations/{thread_id}",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["thread_id"] == thread_id
    assert deleted.json()["active_data_deleted"] is True
    assert deleted.json()["backup_expiry_state"] == "unknown"
    assert client.get("/api/v1/conversations").json() == []
    assert client.get(f"/api/v1/conversations/{thread_id}/transcript").status_code == 404
    assert (
        client.delete(f"/api/v1/conversations/{thread_id}", headers=headers).status_code
        == 404
    )


def test_guardian_stop_blocks_readiness_and_conversation_writes(fixed_time) -> None:
    client = _client(fixed_time, guardian_mode=GuardianMode.STOPPED)
    headers = _login(client)

    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
    created = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={
            "title": "Blocked while stopped",
            "sensitivity": "personal",
        },
    )
    assert created.status_code == 503
    assert created.json()["code"] == "conversation_write_unavailable"


def test_blocked_model_invocation_does_not_block_core_liveness(fixed_time) -> None:
    model_started = Event()
    release_model = Event()

    def blocking_response(_request: ModelRequest) -> JsonObject:
        model_started.set()
        release_model.wait(timeout=5)
        return {"text": "The blocked model completed."}

    with _client(fixed_time, model_response=blocking_response) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={
                "title": "Responsiveness check",
                "sensitivity": "personal",
            },
        )
        assert created.status_code == 201
        thread_id = created.json()["thread_id"]
        message_statuses: list[int] = []
        message_errors: list[Exception] = []
        live_statuses: list[int] = []
        live_errors: list[Exception] = []
        live_done = Event()

        def send_message() -> None:
            try:
                response = client.post(
                    f"/api/v1/conversations/{thread_id}/messages",
                    headers=headers,
                    json={
                        "text": "Keep the core responsive.",
                        "idempotency_key": "responsiveness-check-1",
                    },
                )
                message_statuses.append(response.status_code)
            except Exception as error:  # pragma: no cover - surfaced by assertions below
                message_errors.append(error)

        def check_liveness() -> None:
            try:
                live_statuses.append(client.get("/health/live").status_code)
            except Exception as error:  # pragma: no cover - surfaced by assertions below
                live_errors.append(error)
            finally:
                live_done.set()

        message_thread = Thread(target=send_message)
        live_thread: Thread | None = None
        responsive = False
        message_thread.start()
        try:
            assert model_started.wait(timeout=1)
            live_thread = Thread(target=check_liveness)
            live_thread.start()
            responsive = live_done.wait(timeout=1)
        finally:
            release_model.set()
            message_thread.join(timeout=2)
            if live_thread is not None:
                live_thread.join(timeout=2)

        assert responsive
        assert not message_thread.is_alive()
        assert live_thread is not None and not live_thread.is_alive()
        assert message_errors == []
        assert live_errors == []
        assert message_statuses == [200]
        assert live_statuses == [200]
