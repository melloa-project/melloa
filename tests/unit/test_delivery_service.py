from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import pytest

from melloa.adapters.fakes.client import FakeClientAdapter
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.delivery import InMemoryDeliveryStore
from melloa.application.delivery import (
    ClientDeliveryRoute,
    DeliveryService,
    DeliveryUnavailableError,
)
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationReplyWork,
    ConversationThread,
    DeliveryState,
    MessageKind,
    MessagePart,
)
from melloa.domain.delivery import DeliveryWorkOutcome, DeliveryWorkState
from melloa.domain.guardian import (
    GuardianMode,
    GuardianStatusPayload,
    VerifiedGuardianStatus,
)
from melloa.ports.delivery import DeliveryConflictError
from tests.conftest import record_id


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class MutableGuardianReader:
    def __init__(self, now: datetime, mode: GuardianMode = GuardianMode.NORMAL) -> None:
        self._now = now
        self._mode = mode
        self._sequence = 1

    def set(self, *, now: datetime, mode: GuardianMode, sequence: int) -> None:
        self._now = now
        self._mode = mode
        self._sequence = sequence

    def read_status(self) -> VerifiedGuardianStatus:
        return VerifiedGuardianStatus(
            payload=GuardianStatusPayload(
                instance_id="home-guardian",
                mode=self._mode,
                sequence=self._sequence,
                changed_at=self._now,
                reason_code="guardian.synthetic-test",
                previous_receipt_hash=(None if self._sequence == 1 else "sha256:" + "0" * 64),
            ),
            receipt_hash="sha256:" + f"{self._sequence:064x}",
            key_id="guardian.test-key",
        )


class CrashOnceDeliveryStore(InMemoryDeliveryStore):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.crash_on_complete = True

    def complete(self, claim, attempt):
        if self.crash_on_complete:
            self.crash_on_complete = False
            raise RuntimeError("synthetic crash after adapter receipt")
        return super().complete(claim, attempt)


def sequential_id_factory():
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return record_id(prefix, counts[prefix])

    return create


def principal(fixed_time: datetime, *, owner_number: int = 1) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=record_id("owner", owner_number),
        session_id=record_id("session", owner_number),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )


def conversation_fixture(
    fixed_time: datetime,
    *,
    sensitivity: Sensitivity = Sensitivity.PERSONAL,
) -> tuple[InMemoryConversationStore, ConversationThread, ConversationMessage]:
    store = InMemoryConversationStore()
    thread = ConversationThread(
        thread_id=record_id("thread", 1),
        owner_id=record_id("owner", 1),
        intelligence_id=record_id("intelligence", 1),
        title="Delivery fixture",
        sensitivity=sensitivity,
        retention_policy="retention.owner-conversation",
        created_at=fixed_time,
        updated_at=fixed_time,
    )
    message = ConversationMessage(
        message_id=record_id("message", 1),
        thread_id=thread.thread_id,
        author_principal_id=thread.intelligence_id,
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text="Synthetic outbound message."),),
        delivery_state=DeliveryState.DELIVERED,
        sensitivity=sensitivity,
        created_at=fixed_time,
        observed_at=fixed_time,
    )
    store.create_thread(thread)
    store.append_inbound(
        message,
        "fixture:canonical-message",
        ConversationReplyWork(
            work_id=record_id("work", 1),
            thread_id=thread.thread_id,
            message_id=message.message_id,
            created_at=fixed_time,
        ),
        max_attempts=1,
    )
    return store, thread, message


def delivery_fixture(
    fixed_time: datetime,
    *,
    failure_codes: tuple[str, ...] = (),
    max_attempts: int = 3,
    delivery_store: InMemoryDeliveryStore | None = None,
    sensitivity: Sensitivity = Sensitivity.PERSONAL,
):
    clock = MutableClock(fixed_time)
    ids = sequential_id_factory()
    conversation_store, thread, message = conversation_fixture(
        fixed_time,
        sensitivity=sensitivity,
    )
    adapter = FakeClientAdapter(
        failure_codes=failure_codes,
        clock=clock,
        id_factory=ids,
    )
    guardian = MutableGuardianReader(fixed_time)
    store = delivery_store or InMemoryDeliveryStore(id_factory=ids)
    service = DeliveryService(
        owner_id=thread.owner_id,
        intelligence_id=thread.intelligence_id,
        conversation_store=conversation_store,
        delivery_store=store,
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
        id_factory=ids,
        max_attempts=max_attempts,
        lease_duration=timedelta(seconds=1),
        retry_base=timedelta(seconds=1),
        retry_ceiling=timedelta(seconds=4),
    )
    return service, store, adapter, guardian, clock, conversation_store, thread, message


def enqueue(service, fixed_time, thread, message, *, key="delivery:fixture:1"):
    return service.enqueue_owner_delivery(
        principal(fixed_time),
        thread_id=thread.thread_id,
        message_id=message.message_id,
        client_adapter="client.fake",
        destination_ref="synthetic:owner",
        idempotency_key=key,
    )


def test_owner_delivery_persists_exact_policy_and_side_effect_receipts(fixed_time) -> None:
    (
        service,
        _store,
        adapter,
        _guardian,
        _clock,
        _conversation_store,
        thread,
        message,
    ) = delivery_fixture(fixed_time)

    submitted = enqueue(service, fixed_time, thread, message)
    duplicate = enqueue(service, fixed_time, thread, message)

    assert submitted.created is True
    assert duplicate.created is False
    assert submitted.status == duplicate.status
    assert submitted.status.state is DeliveryWorkState.COMPLETED
    assert submitted.status.attempt_count == 1
    assert submitted.status.last_error_code is None
    attempt = submitted.status.attempts[0]
    assert attempt.outcome is DeliveryWorkOutcome.SUCCEEDED
    assert attempt.policy_decision_id == submitted.status.current_policy_decision_id
    assert attempt.execution_receipt is not None
    assert attempt.execution_receipt.action_hash == submitted.status.action_hash
    assert attempt.adapter_receipt is not None
    assert attempt.adapter_receipt.adapter_metadata["authorization_id"] == (
        attempt.policy_decision_id
    )
    assert adapter.sent == [message]
    assert service.list_deliveries(principal(fixed_time), thread.thread_id) == (submitted.status,)
    assert (
        service.inspect_delivery(
            principal(fixed_time),
            thread_id=thread.thread_id,
            work_id=submitted.status.work_id,
        )
        == submitted.status
    )


def test_delivery_retries_become_visible_dead_and_resume_with_fresh_policy(
    fixed_time,
) -> None:
    (
        service,
        _store,
        adapter,
        _guardian,
        clock,
        _conversation_store,
        thread,
        message,
    ) = delivery_fixture(
        fixed_time,
        failure_codes=(
            "channel.synthetic_unavailable",
            "channel.synthetic_unavailable",
            "channel.synthetic_unavailable",
        ),
        max_attempts=2,
    )

    first = enqueue(service, fixed_time, thread, message).status
    assert first.state is DeliveryWorkState.READY
    assert first.attempts[0].outcome is DeliveryWorkOutcome.RETRY_SCHEDULED
    clock.now = first.available_at

    dead = service.process_ready(limit=1)[0]
    assert dead.state is DeliveryWorkState.DEAD
    assert dead.attempt_count == 2
    assert dead.last_error_code == "channel.synthetic_unavailable"
    original_decision_id = dead.current_policy_decision_id

    resumed = service.resume_delivery(
        principal(fixed_time),
        thread_id=thread.thread_id,
        work_id=dead.work_id,
    )
    assert resumed.state is DeliveryWorkState.READY
    assert resumed.attempt_count == 3
    assert resumed.max_attempts == 4
    assert resumed.current_policy_decision_id != original_decision_id
    assert resumed.resumptions[0].prior_attempts == 2
    assert resumed.resumptions[0].authorization_request.action_hash == dead.action_hash
    clock.now = resumed.available_at

    completed = service.process_ready(limit=1)[0]
    assert completed.state is DeliveryWorkState.COMPLETED
    assert tuple(attempt.outcome for attempt in completed.attempts) == (
        DeliveryWorkOutcome.RETRY_SCHEDULED,
        DeliveryWorkOutcome.DEAD,
        DeliveryWorkOutcome.RETRY_SCHEDULED,
        DeliveryWorkOutcome.SUCCEEDED,
    )
    assert adapter.sent == [message]


def test_expired_lease_retries_without_duplicate_external_send(fixed_time) -> None:
    ids = sequential_id_factory()
    crash_store = CrashOnceDeliveryStore(id_factory=ids)
    (
        service,
        store,
        adapter,
        _guardian,
        clock,
        _conversation_store,
        thread,
        message,
    ) = delivery_fixture(fixed_time, delivery_store=crash_store)

    with pytest.raises(RuntimeError, match="synthetic crash"):
        enqueue(service, fixed_time, thread, message)
    running = store.find_by_message(message.message_id)[0]
    assert running.state is DeliveryWorkState.RUNNING
    assert adapter.sent == [message]

    clock.now = fixed_time + timedelta(seconds=2)
    completed = service.process_ready(limit=1)[0]

    assert completed.state is DeliveryWorkState.COMPLETED
    assert completed.attempts[0].error_code == "delivery.lease_expired"
    assert completed.attempts[1].adapter_receipt is not None
    assert completed.attempts[1].adapter_receipt.adapter_metadata["deduplicated"] is True
    assert adapter.sent == [message]


def test_delivery_fails_closed_on_guardian_privacy_route_and_key_conflicts(
    fixed_time,
) -> None:
    (
        service,
        _store,
        _adapter,
        guardian,
        _clock,
        conversation_store,
        thread,
        message,
    ) = delivery_fixture(fixed_time)
    guardian.set(now=fixed_time, mode=GuardianMode.NO_ACTIONS, sequence=2)
    with pytest.raises(DeliveryUnavailableError, match=r"guardian\.no_actions"):
        enqueue(service, fixed_time, thread, message)

    (
        device_service,
        _store,
        _adapter,
        _guardian,
        _clock,
        _device_conversation_store,
        thread,
        message,
    ) = delivery_fixture(fixed_time, sensitivity=Sensitivity.DEVICE_ONLY)
    with pytest.raises(DeliveryUnavailableError, match=r"privacy\.device_only_egress"):
        enqueue(device_service, fixed_time, thread, message)

    (
        service,
        _store,
        _adapter,
        _guardian,
        _clock,
        conversation_store,
        thread,
        message,
    ) = delivery_fixture(fixed_time)
    enqueue(service, fixed_time, thread, message, key="delivery:conflict")
    other_message = message.model_copy(
        update={
            "message_id": record_id("message", 2),
            "parts": (MessagePart(kind=MessageKind.TEXT, text="Different."),),
        }
    )
    conversation_store.append_inbound(
        other_message,
        "fixture:canonical-message:2",
        ConversationReplyWork(
            work_id=record_id("work", 2),
            thread_id=thread.thread_id,
            message_id=other_message.message_id,
            created_at=fixed_time,
        ),
        max_attempts=1,
    )
    with pytest.raises(DeliveryConflictError, match="idempotency key"):
        service.enqueue_owner_delivery(
            principal(fixed_time),
            thread_id=thread.thread_id,
            message_id=other_message.message_id,
            client_adapter="client.fake",
            destination_ref="synthetic:owner",
            idempotency_key="delivery:conflict",
        )
