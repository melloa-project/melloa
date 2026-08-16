from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from melloa.adapters.fakes.delivery import InMemoryDeliveryStore
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import (
    ConversationMessage,
    DeliveryAttempt,
    DeliveryState,
    MessageKind,
    MessagePart,
)
from melloa.domain.delivery import (
    DeliveryExecutionReceipt,
    DeliveryWorkAttempt,
    DeliveryWorkOutcome,
    DeliveryWorkResumption,
    DeliveryWorkState,
    DeliveryWorkStatus,
    OutboundDeliveryWork,
    canonical_delivery_action,
    conversation_message_hash,
)
from melloa.domain.guardian import GuardianMode
from melloa.domain.policy import (
    AuthorizationRequest,
    DecisionEffect,
    DeterministicPolicyEvaluator,
    PolicyContext,
    PolicyDecision,
    action_hash,
)
from melloa.ports.delivery import DeliveryConflictError, DeliveryNotFoundError
from tests.conftest import record_id


def message(fixed_time: datetime, *, number: int = 1) -> ConversationMessage:
    return ConversationMessage(
        message_id=record_id("message", number),
        thread_id=record_id("thread", 1),
        author_principal_id=record_id("intelligence", 1),
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text=f"outbound {number}"),),
        delivery_state=DeliveryState.PENDING,
        sensitivity=Sensitivity.PERSONAL,
        created_at=fixed_time,
        observed_at=fixed_time,
    )


def authorization(
    canonical_message: ConversationMessage,
    at: datetime,
    *,
    number: int,
) -> tuple[AuthorizationRequest, PolicyDecision]:
    action = canonical_delivery_action(
        canonical_message,
        client_adapter="client.fake",
        destination_ref="synthetic:owner",
        external_destination="synthetic:owner",
        purpose="conversation.owner_delivery",
        estimated_cost_gbp=Decimal("0"),
    )
    request = AuthorizationRequest(
        request_id=record_id("request", number),
        proposal_id=record_id("proposal", number),
        principal_id=canonical_message.author_principal_id,
        action=action,
        action_hash=action_hash(action),
        guardian_sequence=1,
        requested_at=at,
    )
    decision = DeterministicPolicyEvaluator().evaluate(
        request,
        PolicyContext(
            guardian_mode=GuardianMode.NORMAL,
            guardian_sequence=1,
            granted_operations=frozenset({"client.fake/messages.send"}),
            approved_action_hashes=frozenset({request.action_hash}),
            remaining_daily_budget_gbp=Decimal("1"),
        ),
        decision_id=record_id("decision", number),
        decided_at=at,
    )
    return request, decision


def work(fixed_time: datetime, *, number: int = 1) -> OutboundDeliveryWork:
    canonical_message = message(fixed_time, number=number)
    request, decision = authorization(canonical_message, fixed_time, number=number)
    return OutboundDeliveryWork(
        work_id=record_id("deliverywork", number),
        thread_id=canonical_message.thread_id,
        message_id=canonical_message.message_id,
        message_hash=conversation_message_hash(canonical_message),
        requested_by=record_id("owner", 1),
        client_adapter="client.fake",
        destination_ref="synthetic:owner",
        idempotency_key=f"delivery:{number}",
        authorization_request=request,
        policy_decision=decision,
        authorized_at=fixed_time,
        created_at=fixed_time,
    )


def failed_attempt(
    delivery_work: OutboundDeliveryWork,
    *,
    attempt: int,
    started_at: datetime,
    terminal: bool,
) -> DeliveryWorkAttempt:
    completed_at = started_at + timedelta(milliseconds=1)
    request, decision, _authorized_at = delivery_work.current_authorization()
    return DeliveryWorkAttempt(
        attempt_id=record_id("deliveryattempt", attempt),
        work_id=delivery_work.work_id,
        message_id=delivery_work.message_id,
        attempt=attempt,
        authorization_request_id=request.request_id,
        policy_decision_id=decision.decision_id,
        action_hash=request.action_hash,
        outcome=(DeliveryWorkOutcome.DEAD if terminal else DeliveryWorkOutcome.RETRY_SCHEDULED),
        error_code="channel.synthetic_unavailable",
        started_at=started_at,
        completed_at=completed_at,
        retry_at=None if terminal else completed_at + timedelta(seconds=1),
    )


def successful_attempt(
    delivery_work: OutboundDeliveryWork,
    *,
    attempt: int,
    started_at: datetime,
) -> DeliveryWorkAttempt:
    completed_at = started_at + timedelta(milliseconds=1)
    request, decision, _authorized_at = delivery_work.current_authorization()
    adapter_receipt = DeliveryAttempt(
        delivery_id=record_id("delivery", attempt),
        message_id=delivery_work.message_id,
        client_adapter=delivery_work.client_adapter,
        destination_ref=delivery_work.destination_ref,
        attempt=attempt,
        state=DeliveryState.DELIVERED,
        attempted_at=completed_at,
    )
    execution_receipt = DeliveryExecutionReceipt(
        action_id=record_id("action", attempt),
        decision_id=decision.decision_id,
        action_hash=request.action_hash,
        capability_id=delivery_work.client_adapter,
        operation="messages.send",
        delivery_id=adapter_receipt.delivery_id,
        executed_at=completed_at,
    )
    return DeliveryWorkAttempt(
        attempt_id=record_id("deliveryattempt", attempt),
        work_id=delivery_work.work_id,
        message_id=delivery_work.message_id,
        attempt=attempt,
        authorization_request_id=request.request_id,
        policy_decision_id=decision.decision_id,
        action_hash=request.action_hash,
        outcome=DeliveryWorkOutcome.SUCCEEDED,
        started_at=started_at,
        completed_at=completed_at,
        adapter_receipt=adapter_receipt,
        execution_receipt=execution_receipt,
    )


def resumption(
    delivery_work: OutboundDeliveryWork,
    canonical_message: ConversationMessage,
    at: datetime,
) -> DeliveryWorkResumption:
    request, decision = authorization(canonical_message, at, number=2)
    return DeliveryWorkResumption(
        resumption_id=record_id("deliveryresume", 1),
        work_id=delivery_work.work_id,
        message_id=delivery_work.message_id,
        requested_by=delivery_work.requested_by,
        requested_at=at,
        prior_attempts=1,
        added_attempts=2,
        authorization_request=request,
        policy_decision=decision,
    )


def validate_copy(model, **updates):
    document = model.model_dump(mode="python")
    document.update(updates)
    return type(model).model_validate(document)


def test_delivery_attempt_outcomes_require_consistent_receipts_and_times(fixed_time) -> None:
    delivery_work = work(fixed_time)
    success = successful_attempt(delivery_work, attempt=1, started_at=fixed_time)
    retry = failed_attempt(
        delivery_work,
        attempt=1,
        started_at=fixed_time,
        terminal=False,
    )
    dead = failed_attempt(
        delivery_work,
        attempt=1,
        started_at=fixed_time,
        terminal=True,
    )

    with pytest.raises(ValidationError, match="complete before"):
        validate_copy(success, completed_at=fixed_time - timedelta(microseconds=1))
    with pytest.raises(ValidationError, match="failure metadata"):
        validate_copy(success, error_code="channel.unexpected")
    with pytest.raises(ValidationError, match="adapter and execution receipts"):
        validate_copy(success, adapter_receipt=None)
    with pytest.raises(ValidationError, match="successful adapter receipt"):
        validate_copy(
            success,
            adapter_receipt=success.adapter_receipt.model_copy(
                update={"state": DeliveryState.FAILED}
            ),
        )
    with pytest.raises(ValidationError, match="does not match its delivery attempt"):
        validate_copy(
            success,
            adapter_receipt=success.adapter_receipt.model_copy(update={"attempt": 2}),
        )
    with pytest.raises(ValidationError, match="does not match delivery authority"):
        validate_copy(
            success,
            execution_receipt=success.execution_receipt.model_copy(
                update={"decision_id": record_id("decision", 99)}
            ),
        )
    with pytest.raises(ValidationError, match="client adapter operation"):
        validate_copy(
            success,
            execution_receipt=success.execution_receipt.model_copy(
                update={"capability_id": "client.other"}
            ),
        )
    with pytest.raises(ValidationError, match="receipt chronology"):
        validate_copy(
            success,
            execution_receipt=success.execution_receipt.model_copy(
                update={"executed_at": success.completed_at + timedelta(seconds=1)}
            ),
        )
    with pytest.raises(ValidationError, match="requires an error and retry time"):
        validate_copy(retry, error_code=None)
    with pytest.raises(ValidationError, match="retry must follow"):
        validate_copy(retry, retry_at=retry.completed_at)
    with pytest.raises(ValidationError, match="cannot claim execution receipts"):
        validate_copy(retry, adapter_receipt=success.adapter_receipt)
    with pytest.raises(ValidationError, match="dead delivery requires"):
        validate_copy(dead, error_code=None)


def test_delivery_work_and_status_reject_mixed_or_inconsistent_history(fixed_time) -> None:
    canonical_message = message(fixed_time)
    delivery_work = work(fixed_time)
    dead = failed_attempt(
        delivery_work,
        attempt=1,
        started_at=fixed_time,
        terminal=True,
    )
    resumed = resumption(
        delivery_work,
        canonical_message,
        fixed_time + timedelta(seconds=2),
    )
    resumed_work = validate_copy(
        delivery_work,
        attempts=(dead,),
        resumptions=(resumed,),
    )
    success = successful_attempt(
        resumed_work,
        attempt=2,
        started_at=fixed_time + timedelta(seconds=3),
    )
    completed_work = validate_copy(resumed_work, attempts=(dead, success))
    status = DeliveryWorkStatus(
        work_id=completed_work.work_id,
        thread_id=completed_work.thread_id,
        message_id=completed_work.message_id,
        client_adapter=completed_work.client_adapter,
        destination_ref=completed_work.destination_ref,
        action_hash=completed_work.authorization_request.action_hash,
        current_policy_decision_id=resumed.policy_decision.decision_id,
        state=DeliveryWorkState.COMPLETED,
        attempt_count=2,
        max_attempts=3,
        available_at=success.completed_at,
        completed_at=success.completed_at,
        attempts=(dead, success),
        resumptions=(resumed,),
    )

    with pytest.raises(ValidationError, match="exact canonical action"):
        validate_copy(delivery_work, thread_id=record_id("thread", 2))
    with pytest.raises(ValidationError, match="created before authorization"):
        validate_copy(
            delivery_work,
            created_at=fixed_time - timedelta(microseconds=1),
        )
    with pytest.raises(ValidationError, match="unique increasing numbers"):
        duplicate_number = successful_attempt(
            resumed_work,
            attempt=1,
            started_at=fixed_time + timedelta(seconds=3),
        )
        validate_copy(completed_work, attempts=(dead, duplicate_number))
    with pytest.raises(ValidationError, match="same exact work"):
        validate_copy(
            completed_work,
            attempts=(dead.model_copy(update={"work_id": record_id("deliverywork", 9)}), success),
        )
    with pytest.raises(ValidationError, match="same exact work"):
        validate_copy(
            completed_work,
            attempts=(
                dead,
                success.model_copy(
                    update={
                        "adapter_receipt": success.adapter_receipt.model_copy(
                            update={"destination_ref": "synthetic:other"}
                        )
                    }
                ),
            ),
        )
    with pytest.raises(ValidationError, match="resumption IDs must be unique"):
        validate_copy(completed_work, resumptions=(resumed, resumed))
    later = resumed.model_copy(
        update={
            "resumption_id": record_id("deliveryresume", 2),
            "requested_at": resumed.requested_at + timedelta(seconds=1),
        }
    )
    with pytest.raises(ValidationError, match="deterministic time order"):
        validate_copy(completed_work, resumptions=(later, resumed))
    with pytest.raises(ValidationError, match="preserve the exact action hash"):
        validate_copy(
            completed_work,
            resumptions=(resumed.model_copy(update={"work_id": record_id("deliverywork", 9)}),),
        )

    with pytest.raises(ValidationError, match="configured maximum"):
        validate_copy(status, max_attempts=1)
    with pytest.raises(ValidationError, match="precede recorded attempt"):
        validate_copy(status, attempt_count=1)
    with pytest.raises(ValidationError, match="another work item's attempts"):
        validate_copy(
            status,
            attempts=(dead.model_copy(update={"work_id": record_id("deliverywork", 9)}), success),
        )
    with pytest.raises(ValidationError, match="another work item's resumptions"):
        validate_copy(
            status,
            resumptions=(resumed.model_copy(update={"message_id": record_id("message", 9)}),),
        )
    with pytest.raises(ValidationError, match="only running"):
        validate_copy(status, lease_expires_at=fixed_time + timedelta(seconds=10))
    with pytest.raises(ValidationError, match="successful final attempt"):
        validate_copy(status, completed_at=None)
    with pytest.raises(ValidationError, match="incomplete delivery"):
        validate_copy(status, state=DeliveryWorkState.READY)
    with pytest.raises(ValidationError, match="terminal final attempt"):
        validate_copy(status, state=DeliveryWorkState.DEAD, completed_at=None)


@pytest.mark.parametrize(
    ("request_update", "decision_update", "message_pattern"),
    [
        ({}, {"request_id": record_id("request", 99)}, "does not belong"),
        ({}, {"action_hash": "sha256:" + "0" * 64}, "exact delivery action"),
        ({}, {"effect": DecisionEffect.DENY}, "allow decision"),
        (
            {"requested_at": datetime(2026, 8, 16, 12, 0, 1, tzinfo=UTC)},
            {},
            "chronology",
        ),
    ],
)
def test_delivery_resumption_rejects_invalid_policy_pair(
    fixed_time,
    request_update,
    decision_update,
    message_pattern,
) -> None:
    delivery_work = work(fixed_time)
    request, decision = authorization(message(fixed_time), fixed_time, number=2)
    request = request.model_copy(update=request_update)
    decision = decision.model_copy(update=decision_update)

    with pytest.raises(ValidationError, match=message_pattern):
        DeliveryWorkResumption(
            resumption_id=record_id("deliveryresume", 1),
            work_id=delivery_work.work_id,
            message_id=delivery_work.message_id,
            requested_by=delivery_work.requested_by,
            requested_at=fixed_time,
            prior_attempts=1,
            added_attempts=1,
            authorization_request=request,
            policy_decision=decision,
        )


def test_delivery_resumption_rejects_authority_expired_at_request_time(fixed_time) -> None:
    delivery_work = work(fixed_time)
    requested_at = fixed_time + timedelta(seconds=2)
    request, decision = authorization(message(fixed_time), fixed_time, number=2)
    decision = decision.model_copy(update={"expires_at": fixed_time + timedelta(seconds=1)})

    with pytest.raises(ValidationError, match="already expired"):
        DeliveryWorkResumption(
            resumption_id=record_id("deliveryresume", 1),
            work_id=delivery_work.work_id,
            message_id=delivery_work.message_id,
            requested_by=delivery_work.requested_by,
            requested_at=requested_at,
            prior_attempts=1,
            added_attempts=1,
            authorization_request=request,
            policy_decision=decision,
        )


def test_in_memory_delivery_store_leases_retries_and_completes_idempotently(
    fixed_time,
) -> None:
    store = InMemoryDeliveryStore(id_factory=lambda prefix: record_id(prefix, 99))
    delivery_work = work(fixed_time)
    enqueued = store.enqueue(delivery_work, max_attempts=2)
    duplicate = store.enqueue(delivery_work, max_attempts=2)

    assert enqueued.created is True
    assert duplicate.created is False
    initial_inventory = store.retention_inventory(record_id("owner", 1))
    assert initial_inventory.retained_objects == 1
    assert initial_inventory.retained_bytes > 0
    assert initial_inventory.oldest_retained_at == fixed_time
    assert store.retention_inventory(record_id("owner", 2)).retained_objects == 0
    assert store.list_status(delivery_work.thread_id) == (enqueued.status,)
    assert store.find_by_message(delivery_work.message_id) == (enqueued.status,)
    assert (
        store.claim_next_work(
            lease_owner=record_id("worker", 1),
            now=fixed_time - timedelta(seconds=1),
            lease_expires_at=fixed_time,
        )
        is None
    )
    with pytest.raises(ValueError, match="expire after"):
        store.claim_work(
            delivery_work.work_id,
            lease_owner=record_id("worker", 1),
            now=fixed_time,
            lease_expires_at=fixed_time,
        )

    claim = store.claim_work(
        delivery_work.work_id,
        lease_owner=record_id("worker", 1),
        now=fixed_time,
        lease_expires_at=fixed_time + timedelta(seconds=1),
    )
    assert claim is not None
    assert (
        store.claim_work(
            delivery_work.work_id,
            lease_owner=record_id("worker", 2),
            now=fixed_time,
            lease_expires_at=fixed_time + timedelta(seconds=1),
        )
        is None
    )
    retry = failed_attempt(
        delivery_work,
        attempt=1,
        started_at=fixed_time,
        terminal=False,
    )
    ready = store.record_failure(claim, retry)
    assert store.record_failure(claim, retry) == ready
    assert ready.state is DeliveryWorkState.READY
    assert (
        store.claim_next_work(
            lease_owner=record_id("worker", 2),
            now=retry.completed_at,
            lease_expires_at=retry.retry_at,
        )
        is None
    )

    second_claim = store.claim_work(
        delivery_work.work_id,
        lease_owner=record_id("worker", 2),
        now=retry.retry_at,
        lease_expires_at=retry.retry_at + timedelta(seconds=1),
    )
    assert second_claim is not None
    with pytest.raises(DeliveryConflictError, match="attempt budget"):
        store.record_failure(
            second_claim,
            failed_attempt(
                second_claim.work,
                attempt=2,
                started_at=retry.retry_at,
                terminal=False,
            ),
        )
    with pytest.raises(DeliveryConflictError, match="successful attempt"):
        store.complete(
            second_claim,
            failed_attempt(
                second_claim.work,
                attempt=2,
                started_at=retry.retry_at,
                terminal=True,
            ),
        )
    success = successful_attempt(
        second_claim.work,
        attempt=2,
        started_at=retry.retry_at,
    )
    completed = store.complete(second_claim, success)
    final_inventory = store.retention_inventory(record_id("owner", 1))
    assert final_inventory.retained_objects == 3
    assert final_inventory.retained_bytes > initial_inventory.retained_bytes
    assert final_inventory.oldest_retained_at == fixed_time
    assert store.complete(second_claim, success) == completed
    with pytest.raises(DeliveryConflictError, match="stale"):
        store.complete(
            second_claim,
            success.model_copy(update={"attempt_id": record_id("deliveryattempt", 22)}),
        )
    with pytest.raises(DeliveryNotFoundError, match="not found"):
        store.status(record_id("deliverywork", 99))


def test_in_memory_delivery_store_rejects_conflicts_and_resumes_dead_work(
    fixed_time,
) -> None:
    store = InMemoryDeliveryStore()
    delivery_work = work(fixed_time)
    with pytest.raises(ValueError, match="must be positive"):
        store.enqueue(delivery_work, max_attempts=0)
    with pytest.raises(DeliveryConflictError, match="cannot contain history"):
        store.enqueue(
            delivery_work.model_copy(
                update={
                    "attempts": (
                        failed_attempt(
                            delivery_work,
                            attempt=1,
                            started_at=fixed_time,
                            terminal=True,
                        ),
                    )
                }
            ),
            max_attempts=1,
        )
    store.enqueue(delivery_work, max_attempts=1)
    conflicting_id = work(fixed_time, number=2).model_copy(
        update={"work_id": delivery_work.work_id}
    )
    with pytest.raises(DeliveryConflictError, match="ID conflicts"):
        store.enqueue(conflicting_id, max_attempts=1)

    claim = store.claim_work(
        delivery_work.work_id,
        lease_owner=record_id("worker", 1),
        now=fixed_time,
        lease_expires_at=fixed_time + timedelta(seconds=1),
    )
    assert claim is not None
    dead_attempt = failed_attempt(
        delivery_work,
        attempt=1,
        started_at=fixed_time,
        terminal=True,
    )
    dead_status = store.record_failure(claim, dead_attempt)
    resume_at = dead_attempt.completed_at + timedelta(seconds=1)
    resume = resumption(delivery_work, message(fixed_time), resume_at)
    with pytest.raises(ValueError, match="must match"):
        store.resume(
            delivery_work.work_id,
            resume,
            available_at=resume_at,
            added_attempts=1,
        )
    resumed = store.resume(
        delivery_work.work_id,
        resume,
        available_at=resume_at,
        added_attempts=2,
    )
    assert resumed.state is DeliveryWorkState.READY
    assert resumed.max_attempts == dead_status.max_attempts + 2
    assert (
        store.resume(
            delivery_work.work_id,
            resume,
            available_at=resume_at,
            added_attempts=2,
        )
        == resumed
    )
    another = resume.model_copy(update={"resumption_id": record_id("deliveryresume", 2)})
    assert (
        store.resume(
            delivery_work.work_id,
            another,
            available_at=resume_at,
            added_attempts=2,
        )
        == resumed
    )


def test_in_memory_delivery_store_expires_terminal_lease(fixed_time) -> None:
    store = InMemoryDeliveryStore(id_factory=lambda prefix: record_id(prefix, 99))
    delivery_work = work(fixed_time)
    store.enqueue(delivery_work, max_attempts=1)
    claim = store.claim_work(
        delivery_work.work_id,
        lease_owner=record_id("worker", 1),
        now=fixed_time,
        lease_expires_at=fixed_time + timedelta(seconds=1),
    )
    assert claim is not None

    assert (
        store.claim_work(
            delivery_work.work_id,
            lease_owner=record_id("worker", 2),
            now=fixed_time + timedelta(seconds=2),
            lease_expires_at=fixed_time + timedelta(seconds=3),
        )
        is None
    )
    status = store.status(delivery_work.work_id)
    assert status.state is DeliveryWorkState.DEAD
    assert status.attempts[0].error_code == "delivery.lease_expired"
