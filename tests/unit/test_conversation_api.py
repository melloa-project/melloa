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
from melloa.application.conversation import ConversationService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.core import create_app
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import ConversationThread
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
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
                retention_policy="retention.owner-conversation",
                created_at=fixed_time,
                updated_at=fixed_time,
            )
        )
    guardian = _guardian(fixed_time, guardian_mode)
    service = ConversationService(
        owner_id=owner_id,
        intelligence_id=record_id("intelligence", 1),
        store=store,
        model_gateway=FakeModelGateway(
            {"text": "I have the context."},
            clock=lambda: fixed_time,
            id_factory=ids,
        ),
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
        create_app(guardian, sessions, service),
        base_url="https://testserver",
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert response.status_code == 200
    return {"X-Melloa-CSRF": response.json()["csrf_token"]}


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
                "retention_policy": "retention.owner-conversation",
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
            "retention_policy": "retention.owner-conversation",
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


def test_foreign_owner_cannot_discover_a_thread(fixed_time) -> None:
    client = _client(fixed_time, owner_number=2, seed_thread=True)
    _login(client)

    assert (
        client.get(
            f"/api/v1/conversations/{record_id('thread', 42)}/transcript"
        ).status_code
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
            "retention_policy": "retention.owner-conversation",
        },
    )
    assert created.status_code == 503
    assert created.json()["code"] == "conversation_write_unavailable"
