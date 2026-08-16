from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event

from fastapi.testclient import TestClient

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.client import FakeClientAdapter
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.delivery import InMemoryDeliveryStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.application.delivery import ClientDeliveryRoute, DeliveryService
from melloa.apps.core import create_app
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationReplyWork,
    ConversationThread,
    DeliveryState,
    MessageKind,
    MessagePart,
)
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from tests.conftest import record_id

_BOOTSTRAP_TOKEN = "synthetic-bootstrap-token-value-0001"
_DELIVERY_PAYLOAD = {
    "message_id": record_id("message", 1),
    "client_adapter": "client.fake",
    "destination_ref": "synthetic:owner",
    "idempotency_key": "delivery:owner-console:1",
}


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@dataclass(frozen=True)
class DeliveryApiFixture:
    service: DeliveryService
    delivery_store: InMemoryDeliveryStore
    adapter: FakeClientAdapter
    guardian: FakeGuardianStatusReader
    clock: MutableClock
    conversation_store: InMemoryConversationStore
    thread: ConversationThread
    message: ConversationMessage


class RecordingDeliveryWorker:
    def __init__(self) -> None:
        self.processed = Event()
        self.cycles = 0

    def process_ready(self) -> tuple[()]:
        self.cycles += 1
        self.processed.set()
        return ()


def _sequential_id_factory() -> Callable[[str], str]:
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return record_id(prefix, counts[prefix])

    return create


def _delivery_fixture(
    fixed_time: datetime,
    *,
    owner_number: int = 1,
    failure_codes: tuple[str, ...] = (),
    max_attempts: int = 3,
) -> DeliveryApiFixture:
    clock = MutableClock(fixed_time)
    id_factory = _sequential_id_factory()
    owner_id = record_id("owner", owner_number)
    intelligence_id = record_id("intelligence", owner_number)
    conversation_store = InMemoryConversationStore()
    thread = ConversationThread(
        thread_id=record_id("thread", owner_number),
        owner_id=owner_id,
        intelligence_id=intelligence_id,
        title="Delivery API fixture",
        sensitivity=Sensitivity.PERSONAL,
        retention_policy="retention.owner-conversation",
        created_at=fixed_time,
        updated_at=fixed_time,
    )
    message = ConversationMessage(
        message_id=record_id("message", 1),
        thread_id=thread.thread_id,
        author_principal_id=intelligence_id,
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text="Synthetic outbound message."),),
        delivery_state=DeliveryState.DELIVERED,
        sensitivity=Sensitivity.PERSONAL,
        created_at=fixed_time,
        observed_at=fixed_time,
    )
    conversation_store.create_thread(thread)
    conversation_store.append_inbound(
        message,
        f"fixture:canonical-message:{owner_number}",
        ConversationReplyWork(
            work_id=record_id("work", owner_number),
            thread_id=thread.thread_id,
            message_id=message.message_id,
            created_at=fixed_time,
        ),
        max_attempts=1,
    )
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="synthetic-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    adapter = FakeClientAdapter(
        failure_codes=failure_codes,
        clock=clock,
        id_factory=id_factory,
    )
    delivery_store = InMemoryDeliveryStore(id_factory=id_factory)
    service = DeliveryService(
        owner_id=owner_id,
        intelligence_id=intelligence_id,
        conversation_store=conversation_store,
        delivery_store=delivery_store,
        routes=(
            ClientDeliveryRoute(
                adapter_id="client.fake",
                destination_ref="synthetic:owner",
                external_destination="synthetic:owner",
                purpose="conversation.owner_delivery",
                adapter=adapter,
                allowed_sensitivities=frozenset(Sensitivity),
            ),
        ),
        guardian_reader=guardian,
        clock=clock,
        id_factory=id_factory,
        max_attempts=max_attempts,
        lease_duration=timedelta(seconds=1),
        retry_base=timedelta(seconds=1),
        retry_ceiling=timedelta(seconds=4),
    )
    return DeliveryApiFixture(
        service=service,
        delivery_store=delivery_store,
        adapter=adapter,
        guardian=guardian,
        clock=clock,
        conversation_store=conversation_store,
        thread=thread,
        message=message,
    )


def _client(
    fixture: DeliveryApiFixture,
    *,
    delivery_service: DeliveryService | None,
    session_owner_number: int = 1,
    recent_auth_ttl: timedelta = timedelta(minutes=5),
) -> TestClient:
    tokens = iter(("session-one", "csrf-one", "session-two", "csrf-two"))
    sessions = InMemoryOwnerSessionManager(
        record_id("owner", session_owner_number),
        _BOOTSTRAP_TOKEN,
        clock=fixture.clock,
        token_factory=lambda: next(tokens),
        recent_auth_ttl=recent_auth_ttl,
    )
    return TestClient(
        create_app(
            fixture.guardian,
            sessions,
            delivery_service=delivery_service,
        ),
        base_url="https://testserver",
    )


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_delivery_api_requires_authentication_csrf_and_recent_authentication(
    fixed_time: datetime,
) -> None:
    fixture = _delivery_fixture(fixed_time)
    client = _client(
        fixture,
        delivery_service=fixture.service,
        recent_auth_ttl=timedelta(minutes=1),
    )
    path = f"/api/v1/conversations/{fixture.thread.thread_id}/deliveries"

    assert client.get(path).status_code == 401
    assert client.post(path, json=_DELIVERY_PAYLOAD).status_code == 401

    csrf = _login(client)
    missing_csrf = client.post(path, json=_DELIVERY_PAYLOAD)
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "csrf_validation_failed"
    wrong_csrf = client.post(
        path,
        headers={"X-Melloa-CSRF": "wrong"},
        json=_DELIVERY_PAYLOAD,
    )
    assert wrong_csrf.status_code == 403
    assert wrong_csrf.json()["code"] == "csrf_validation_failed"

    fixture.clock.now = fixed_time + timedelta(minutes=1)
    expired = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json=_DELIVERY_PAYLOAD,
    )
    assert expired.status_code == 403
    assert expired.json()["code"] == "recent_authentication_required"
    assert fixture.delivery_store.list_status(fixture.thread.thread_id) == ()


def test_delivery_api_enqueues_duplicates_lists_and_inspects(fixed_time: datetime) -> None:
    fixture = _delivery_fixture(fixed_time)
    client = _client(fixture, delivery_service=fixture.service)
    csrf = _login(client)
    path = f"/api/v1/conversations/{fixture.thread.thread_id}/deliveries"

    created = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json=_DELIVERY_PAYLOAD,
    )
    assert created.status_code == 200
    assert created.json()["created"] is True
    assert created.json()["delivery"]["state"] == "completed"

    duplicate = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json=_DELIVERY_PAYLOAD,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    assert duplicate.json()["delivery"] == created.json()["delivery"]
    assert fixture.adapter.sent == [fixture.message]

    listed = client.get(path)
    assert listed.status_code == 200
    assert listed.json() == [created.json()["delivery"]]
    work_id = created.json()["delivery"]["work_id"]
    inspected = client.get(f"{path}/{work_id}")
    assert inspected.status_code == 200
    assert inspected.json() == created.json()["delivery"]


def test_delivery_api_returns_dead_work_as_accepted_and_requires_fresh_resume(
    fixed_time: datetime,
) -> None:
    fixture = _delivery_fixture(
        fixed_time,
        failure_codes=("channel.synthetic_unavailable",),
        max_attempts=1,
    )
    client = _client(
        fixture,
        delivery_service=fixture.service,
        recent_auth_ttl=timedelta(minutes=1),
    )
    csrf = _login(client)
    path = f"/api/v1/conversations/{fixture.thread.thread_id}/deliveries"

    accepted = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json=_DELIVERY_PAYLOAD,
    )
    assert accepted.status_code == 202
    dead = accepted.json()["delivery"]
    assert dead["state"] == "dead"
    assert dead["last_error_code"] == "channel.synthetic_unavailable"
    original_decision_id = dead["current_policy_decision_id"]
    resume_path = f"{path}/{dead['work_id']}/resume"

    fixture.clock.now = fixed_time + timedelta(minutes=2)
    expired = client.post(resume_path, headers={"X-Melloa-CSRF": csrf})
    assert expired.status_code == 403
    assert expired.json()["code"] == "recent_authentication_required"

    fresh_csrf = _login(client)
    resumed = client.post(resume_path, headers={"X-Melloa-CSRF": fresh_csrf})
    assert resumed.status_code == 200
    assert resumed.json()["state"] == "completed"
    assert resumed.json()["current_policy_decision_id"] != original_decision_id
    assert resumed.json()["resumptions"][0]["prior_attempts"] == 1
    assert fixture.adapter.sent == [fixture.message]


def test_delivery_api_conceals_cross_thread_and_foreign_owner_work(
    fixed_time: datetime,
) -> None:
    fixture = _delivery_fixture(fixed_time)
    client = _client(fixture, delivery_service=fixture.service)
    csrf = _login(client)
    path = f"/api/v1/conversations/{fixture.thread.thread_id}/deliveries"
    created = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json=_DELIVERY_PAYLOAD,
    )
    work_id = created.json()["delivery"]["work_id"]

    other_thread = fixture.thread.model_copy(
        update={
            "thread_id": record_id("thread", 2),
            "title": "Other owner thread",
        }
    )
    fixture.conversation_store.create_thread(other_thread)
    cross_thread_path = f"/api/v1/conversations/{other_thread.thread_id}/deliveries/{work_id}"
    concealed = client.get(cross_thread_path)
    assert concealed.status_code == 404
    assert concealed.json()["code"] == "delivery_not_found"
    concealed_resume = client.post(
        f"{cross_thread_path}/resume",
        headers={"X-Melloa-CSRF": csrf},
    )
    assert concealed_resume.status_code == 404
    assert concealed_resume.json()["code"] == "delivery_not_found"

    foreign_fixture = _delivery_fixture(fixed_time, owner_number=2)
    foreign_client = _client(
        foreign_fixture,
        delivery_service=foreign_fixture.service,
        session_owner_number=1,
    )
    _login(foreign_client)
    foreign_path = f"/api/v1/conversations/{foreign_fixture.thread.thread_id}/deliveries"
    foreign = foreign_client.get(foreign_path)
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "delivery_not_found"


def test_delivery_api_maps_conflict_unavailable_and_unconfigured_failures(
    fixed_time: datetime,
) -> None:
    fixture = _delivery_fixture(fixed_time)
    client = _client(fixture, delivery_service=fixture.service)
    csrf = _login(client)
    path = f"/api/v1/conversations/{fixture.thread.thread_id}/deliveries"

    unavailable_payload = {
        **_DELIVERY_PAYLOAD,
        "destination_ref": "synthetic:missing",
    }
    unavailable = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json=unavailable_payload,
    )
    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "code": "delivery_unavailable",
        "message": "Outbound delivery is unavailable.",
    }
    assert "route_not_configured" not in unavailable.text

    created = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json={**_DELIVERY_PAYLOAD, "idempotency_key": "delivery:conflict"},
    )
    assert created.status_code == 200
    other_message = fixture.message.model_copy(
        update={
            "message_id": record_id("message", 2),
            "parts": (MessagePart(kind=MessageKind.TEXT, text="Different content."),),
        }
    )
    fixture.conversation_store.append_inbound(
        other_message,
        "fixture:canonical-message:conflict",
        ConversationReplyWork(
            work_id=record_id("work", 2),
            thread_id=fixture.thread.thread_id,
            message_id=other_message.message_id,
            created_at=fixed_time,
        ),
        max_attempts=1,
    )
    conflict = client.post(
        path,
        headers={"X-Melloa-CSRF": csrf},
        json={
            **_DELIVERY_PAYLOAD,
            "message_id": other_message.message_id,
            "idempotency_key": "delivery:conflict",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "delivery_conflict"

    unconfigured = _client(fixture, delivery_service=None)
    _login(unconfigured)
    missing_service = unconfigured.get(path)
    assert missing_service.status_code == 503
    assert missing_service.json() == {"detail": "Outbound delivery is not configured."}


def test_delivery_worker_runs_inside_the_bounded_app_lifespan(fixed_time: datetime) -> None:
    fixture = _delivery_fixture(fixed_time)
    worker = RecordingDeliveryWorker()
    app = create_app(
        fixture.guardian,
        delivery_service=worker,
        run_delivery_worker=True,
        delivery_worker_interval=0.01,
    )

    with TestClient(app, base_url="https://testserver"):
        assert worker.processed.wait(timeout=1)
        assert worker.cycles >= 1
