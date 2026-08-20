from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.application.conversation import (
    ConversationOwnershipError,
    ConversationService,
    ConversationUnavailableError,
)
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingOutcome,
    ConversationProcessingState,
    ConversationReplyWork,
    MessageKind,
    MessagePart,
)
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import Assertion, AssertionStatus
from melloa.domain.models import ProcessingLocation
from melloa.ports.conversation import ConversationConflictError, ConversationNotFoundError
from melloa.ports.model import ModelInvocationError
from melloa.release import CURRENT_RELEASE
from tests.conftest import record_id


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def set(self, now: datetime) -> None:
        self.now = now


def principal(fixed_time, owner_number=1) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=record_id("owner", owner_number),
        session_id=record_id("session", owner_number),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )


def guardian(fixed_time, mode=GuardianMode.NO_ACTIONS) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=mode,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.initialized",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def service_fixture(
    fixed_time,
    *,
    mode=GuardianMode.NO_ACTIONS,
    response=None,
    assertions=(),
    external_disclosure=False,
    clock=None,
    max_processing_attempts=3,
    model_gateway=None,
):
    effective_clock = (lambda: fixed_time) if clock is None else clock
    store = InMemoryConversationStore()
    model = FakeModelGateway(
        {"text": "Synthetic reply."} if response is None else response,
        clock=effective_clock,
        external_disclosure=external_disclosure,
    )
    service = ConversationService(
        owner_id=record_id("owner", 1),
        intelligence_id=record_id("intelligence", 1),
        store=store,
        model_gateway=model if model_gateway is None else model_gateway,
        retriever=PolicyConstrainedRetriever(
            InMemoryMemoryRepository(assertions),
            clock=effective_clock,
        ),
        guardian_reader=guardian(fixed_time, mode),
        clock=effective_clock,
        max_processing_attempts=max_processing_attempts,
    )
    return service, store, model


def test_canonical_conversation_persists_validated_turn(fixed_time) -> None:
    service, store, model = service_fixture(fixed_time)
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Synthetic planning",
        sensitivity=Sensitivity.PERSONAL,
    )

    reply = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="What should I review?",
        idempotency_key="owner-console:message:1",
    )

    assert reply.duplicate is False
    assert reply.processing.state is ConversationProcessingState.COMPLETED
    assert reply.processing.attempt_count == 1
    assert reply.output_message is not None
    assert reply.output_message.parts[0].text == "Synthetic reply."
    assert reply.output_message.reply_to_message_id == reply.inbound_message.message_id
    assert reply.turn is not None
    assert reply.turn.triggering_message_ids == (reply.inbound_message.message_id,)
    assert reply.turn.retrieval_manifest_id is not None
    manifest = store.get_retrieval_manifest(reply.turn.retrieval_manifest_id)
    assert manifest.citations == ()
    assert manifest.external_disclosure is False
    assert reply.turn.decision_record["external_disclosure"] is False
    assert reply.turn.decision_record["runtime_version"] == (
        CURRENT_RELEASE.runtime_identifier
    )
    assert len(model.requests) == 1
    assert model.requests[0].input["text"] == "What should I review?"
    assert model.requests[0].input["recent_conversation"] == []
    assert model.requests[0].allowed_processing_locations == frozenset(
        {ProcessingLocation.DEVICE}
    )
    assert model.requests[0].input["retrieval_manifest_id"] == manifest.manifest_id
    assert model.requests[0].input["memory_citations"] == []
    assert store.list_messages(thread.thread_id) == (
        reply.inbound_message,
        reply.output_message,
    )
    assert store.list_turns(thread.thread_id) == (reply.turn,)
    assert service.list_turns(owner, thread.thread_id) == (reply.turn,)
    assert service.list_processing(owner, thread.thread_id) == (reply.processing,)
    assert service.inspect_processing(
        owner,
        thread_id=thread.thread_id,
        message_id=reply.inbound_message.message_id,
    ) == reply.processing
    inspection = service.inspect_turn(
        owner,
        thread_id=thread.thread_id,
        turn_id=reply.turn.turn_id,
    )
    assert inspection.turn == reply.turn
    assert inspection.retrieval_manifest == manifest
    assert inspection.output_message == reply.output_message
    assert inspection.model_result.result_id == reply.turn.model_run_ids[0]


def test_follow_up_includes_active_recent_conversation(fixed_time) -> None:
    service, _store, model = service_fixture(fixed_time)
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Continuous conversation",
        sensitivity=Sensitivity.PERSONAL,
    )
    first = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="I am choosing between the red and blue plans.",
        idempotency_key="continuity:1",
    )

    service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Which one did I say felt safer?",
        idempotency_key="continuity:2",
    )

    assert first.output_message is not None
    assert model.requests[1].input["recent_conversation"] == [
        {
            "message_id": first.inbound_message.message_id,
            "role": "owner",
            "text": "I am choosing between the red and blue plans.",
        },
        {
            "message_id": first.output_message.message_id,
            "role": "melli",
            "text": "Synthetic reply.",
        },
    ]


def test_message_idempotency_does_not_reinvoke_model(fixed_time) -> None:
    service, _store, model = service_fixture(fixed_time)
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Synthetic",
        sensitivity=Sensitivity.INTERNAL,
    )
    first = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Hello",
        idempotency_key="stable-key",
    )
    duplicate = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Hello",
        idempotency_key="stable-key",
    )

    assert duplicate.duplicate is True
    assert duplicate.inbound_message == first.inbound_message
    assert duplicate.output_message == first.output_message
    assert len(model.requests) == 1

    with pytest.raises(ConversationConflictError, match="different message content"):
        service.post_owner_message(
            owner,
            thread_id=thread.thread_id,
            text="Changed retry payload",
            idempotency_key="stable-key",
        )

    with pytest.raises(ValueError, match="idempotency key"):
        service.post_owner_message(
            owner,
            thread_id=thread.thread_id,
            text="Hello",
            idempotency_key="",
        )


def test_owner_correction_preserves_linkage_and_is_idempotent(fixed_time) -> None:
    service, store, model = service_fixture(fixed_time)
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Correctable context",
        sensitivity=Sensitivity.PERSONAL,
    )
    original = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="My sister arrives on Tuesday.",
        idempotency_key="original-message",
    )
    assert original.output_message is not None

    with pytest.raises(ConversationConflictError, match="must change its text"):
        service.correct_owner_message(
            owner,
            thread_id=thread.thread_id,
            message_id=original.inbound_message.message_id,
            text="  My sister arrives on Tuesday.  ",
            idempotency_key="no-op-correction",
        )
    with pytest.raises(ConversationNotFoundError, match="owner message not found"):
        service.correct_owner_message(
            owner,
            thread_id=thread.thread_id,
            message_id=original.output_message.message_id,
            text="This cannot correct Melli's answer.",
            idempotency_key="melli-target",
        )

    corrected = service.correct_owner_message(
        owner,
        thread_id=thread.thread_id,
        message_id=original.inbound_message.message_id,
        text="My sister arrives on Thursday.",
        idempotency_key="correction-message",
    )
    duplicate = service.correct_owner_message(
        owner,
        thread_id=thread.thread_id,
        message_id=original.inbound_message.message_id,
        text="My sister arrives on Thursday.",
        idempotency_key="correction-message",
    )

    assert corrected.inbound_message.corrects_message_id == (
        original.inbound_message.message_id
    )
    assert corrected.output_message is not None
    assert corrected.output_message.reply_to_message_id == corrected.inbound_message.message_id
    assert corrected.turn is not None
    assert corrected.turn.decision_record["corrects_message_id"] == (
        original.inbound_message.message_id
    )
    assert duplicate.duplicate is True
    assert duplicate.inbound_message == corrected.inbound_message
    assert duplicate.output_message == corrected.output_message
    assert len(model.requests) == 2
    assert model.requests[1].input["text"] == "My sister arrives on Thursday."
    assert model.requests[1].input["corrects_message_id"] == (
        original.inbound_message.message_id
    )
    assert model.requests[1].input["recent_conversation"] == []
    assert set(store.list_messages(thread.thread_id)) == {
        original.inbound_message,
        original.output_message,
        corrected.inbound_message,
        corrected.output_message,
    }

    with pytest.raises(ConversationConflictError, match="already corrected"):
        service.correct_owner_message(
            owner,
            thread_id=thread.thread_id,
            message_id=original.inbound_message.message_id,
            text="My sister arrives on Friday.",
            idempotency_key="second-correction",
        )


def test_owner_correction_cancels_superseded_pending_reply(fixed_time) -> None:
    invocations = 0

    def recover_for_correction(_request):
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            raise TimeoutError("synthetic provider outage")
        return {"text": "Answered from the corrected wording."}

    service, store, model = service_fixture(
        fixed_time,
        response=recover_for_correction,
    )
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Pending correction",
        sensitivity=Sensitivity.INTERNAL,
    )
    original = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="The appointment is Tuesday.",
        idempotency_key="pending-original",
    )
    assert original.processing.state is ConversationProcessingState.READY

    corrected = service.correct_owner_message(
        owner,
        thread_id=thread.thread_id,
        message_id=original.inbound_message.message_id,
        text="The appointment is Thursday.",
        idempotency_key="pending-correction",
    )

    assert store.reply_processing(original.inbound_message.message_id).state is (
        ConversationProcessingState.CANCELLED
    )
    assert corrected.processing.state is ConversationProcessingState.COMPLETED
    assert corrected.output_message is not None
    assert corrected.output_message.parts[0].text == "Answered from the corrected wording."
    assert len(model.requests) == 2
    assert service.process_ready() == ()


def test_accepted_message_retries_after_backoff_and_completes(fixed_time) -> None:
    clock = MutableClock(fixed_time)
    invocations = 0

    def flaky_response(_request):
        nonlocal invocations
        invocations += 1
        if invocations <= 2:
            raise TimeoutError("synthetic provider outage")
        return {"text": "Recovered reply."}

    service, store, model = service_fixture(
        fixed_time,
        response=flaky_response,
        clock=clock,
    )
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Retry",
        sensitivity=Sensitivity.INTERNAL,
    )

    accepted = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Please retry safely",
        idempotency_key="retry-safe",
    )
    assert accepted.output_message is None
    assert accepted.processing.state is ConversationProcessingState.READY
    assert accepted.processing.last_error_code == "model.gateway_failed"
    assert accepted.processing.attempt_count == 1
    assert len(store.list_messages(thread.thread_id)) == 1
    assert service.process_ready() == ()
    duplicate = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Please retry safely",
        idempotency_key="retry-safe",
    )
    assert duplicate.duplicate is True
    assert len(model.requests) == 1

    first_retry = accepted.processing.attempts[-1].retry_at
    assert first_retry is not None
    clock.set(first_retry)
    second = service.process_ready()
    assert second[0].state is ConversationProcessingState.READY
    assert second[0].attempt_count == 2
    second_retry = second[0].attempts[-1].retry_at
    assert second_retry is not None
    clock.set(second_retry)
    final = service.process_ready()

    assert final[0].state is ConversationProcessingState.COMPLETED
    assert final[0].attempt_count == 3
    assert tuple(attempt.outcome for attempt in final[0].attempts) == (
        ConversationProcessingOutcome.RETRY_SCHEDULED,
        ConversationProcessingOutcome.RETRY_SCHEDULED,
        ConversationProcessingOutcome.SUCCEEDED,
    )
    assert len(model.requests) == 3
    assert len(store.list_messages(thread.thread_id)) == 2
    assert len(store.list_turns(thread.thread_id)) == 1


def test_owner_can_resume_dead_accepted_message_with_new_bounded_budget(fixed_time) -> None:
    clock = MutableClock(fixed_time)
    invocations = 0

    def recovering_response(_request):
        nonlocal invocations
        invocations += 1
        if invocations <= 2:
            raise TimeoutError("synthetic provider outage")
        return {"text": "Recovered after owner resume."}

    service, _store, _model = service_fixture(
        fixed_time,
        response=recovering_response,
        clock=clock,
        max_processing_attempts=2,
    )
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Dead letter",
        sensitivity=Sensitivity.INTERNAL,
    )
    accepted = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Resume this accepted message",
        idempotency_key="dead-letter",
    )
    retry_at = accepted.processing.attempts[-1].retry_at
    assert retry_at is not None
    clock.set(retry_at)
    dead = service.process_ready()[0]
    assert dead.state is ConversationProcessingState.DEAD
    assert dead.attempt_count == dead.max_attempts == 2

    resumed = service.resume_owner_message(
        owner,
        thread_id=thread.thread_id,
        message_id=accepted.inbound_message.message_id,
    )
    assert resumed.output_message is not None
    assert resumed.processing.state is ConversationProcessingState.COMPLETED
    assert resumed.processing.attempt_count == 3
    assert resumed.processing.max_attempts == 4
    assert len(resumed.processing.resumptions) == 1
    assert resumed.processing.resumptions[0].prior_attempts == 2
    assert resumed.processing.resumptions[0].added_attempts == 2


def test_expired_processing_lease_is_visible_and_reclaimable(fixed_time) -> None:
    service, store, _model = service_fixture(fixed_time)
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Lease recovery",
        sensitivity=Sensitivity.INTERNAL,
    )
    inbound = ConversationMessage(
        message_id=record_id("message", 50),
        thread_id=thread.thread_id,
        author_principal_id=owner.owner_id,
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text="Recover my lease"),),
        sensitivity=thread.sensitivity,
        created_at=fixed_time,
        observed_at=fixed_time,
    )
    work = ConversationReplyWork(
        work_id=record_id("work", 50),
        thread_id=thread.thread_id,
        message_id=inbound.message_id,
        created_at=fixed_time,
    )
    store.append_inbound(inbound, "lease-recovery", work, max_attempts=3)
    first = store.claim_reply_work(
        inbound.message_id,
        lease_owner=record_id("worker", 1),
        now=fixed_time,
        lease_expires_at=fixed_time + timedelta(seconds=10),
    )
    assert first is not None
    reclaimed = store.claim_reply_work(
        inbound.message_id,
        lease_owner=record_id("worker", 2),
        now=fixed_time + timedelta(seconds=11),
        lease_expires_at=fixed_time + timedelta(seconds=30),
    )
    assert reclaimed is not None
    assert reclaimed.attempt == 2
    processing = store.reply_processing(inbound.message_id)
    assert processing.state is ConversationProcessingState.RUNNING
    assert processing.attempts[0].error_code == "work.lease_expired"
    assert processing.attempts[0].outcome is ConversationProcessingOutcome.RETRY_SCHEDULED


def test_guardian_read_only_and_owner_scope_fail_closed(fixed_time) -> None:
    with pytest.raises(ValueError, match="max processing attempts"):
        service_fixture(fixed_time, max_processing_attempts=0)
    service, store, _model = service_fixture(fixed_time, mode=GuardianMode.READ_ONLY)
    with pytest.raises(ConversationUnavailableError):
        service.create_thread(
            principal(fixed_time),
            title="Denied",
            sensitivity=Sensitivity.INTERNAL,
        )
    assert store.list_threads(record_id("owner", 1)) == ()

    service, _store, _model = service_fixture(fixed_time)
    with pytest.raises(ConversationOwnershipError):
        service.list_threads(principal(fixed_time, owner_number=2))


def test_owner_deletion_removes_active_conversation_content(fixed_time) -> None:
    service, store, _model = service_fixture(fixed_time)
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Delete this private history",
        sensitivity=Sensitivity.PERSONAL,
    )
    reply = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="A private detail that should be deleted.",
        idempotency_key="delete-private-history",
    )
    assert reply.output_message is not None
    assert reply.turn is not None
    assert reply.turn.retrieval_manifest_id is not None

    with pytest.raises(ConversationOwnershipError):
        service.delete_thread(principal(fixed_time, owner_number=2), thread.thread_id)

    receipt = service.delete_thread(owner, thread.thread_id)

    assert receipt.thread_id == thread.thread_id
    assert receipt.owner_id == owner.owner_id
    assert receipt.active_data_deleted is True
    assert receipt.backup_expiry_state == "unknown"
    assert service.list_threads(owner) == ()
    with pytest.raises(ConversationNotFoundError):
        store.get_thread(thread.thread_id)
    with pytest.raises(ConversationNotFoundError):
        store.get_message(reply.inbound_message.message_id)
    with pytest.raises(ConversationNotFoundError):
        store.get_message(reply.output_message.message_id)
    with pytest.raises(ConversationNotFoundError):
        store.get_retrieval_manifest(reply.turn.retrieval_manifest_id)
    assert store.completed_turn_for_trigger(reply.inbound_message.message_id) is None
    assert (
        store.reply_processing(reply.inbound_message.message_id).state
        is ConversationProcessingState.CANCELLED
    )


def test_invalid_or_uncited_model_output_is_not_persisted_as_reply(fixed_time) -> None:
    owner = principal(fixed_time)
    service, store, _model = service_fixture(fixed_time, response={"unexpected": True})
    thread = service.create_thread(
        owner,
        title="Synthetic",
        sensitivity=Sensitivity.INTERNAL,
    )
    invalid = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Hello",
        idempotency_key="invalid-output",
    )
    assert invalid.output_message is None
    assert invalid.processing.state is ConversationProcessingState.READY
    assert invalid.processing.last_error_code == "model.invalid_output"
    assert len(store.list_messages(thread.thread_id)) == 1
    assert store.list_turns(thread.thread_id) == ()

    service, _store, _model = service_fixture(
        fixed_time,
        response={"text": "Unsupported citation", "citation_ids": [record_id("citation", 1)]},
    )
    thread = service.create_thread(
        owner,
        title="Synthetic 2",
        sensitivity=Sensitivity.INTERNAL,
    )
    uncited = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Hello",
        idempotency_key="uncited-output",
    )
    assert uncited.processing.last_error_code == "model.invalid_citations"


def test_cited_retrieval_flows_through_model_message_and_turn(fixed_time) -> None:
    memory = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=record_id("owner", 1),
        predicate="preference.review-topic",
        value={"topic": "finances"},
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=fixed_time,
    )

    def cited_response(request):
        citation = request.input["memory_citations"][0]
        return {
            "text": "Review the confirmed finance topic.",
            "citation_ids": [citation["citation_id"]],
        }

    service, store, model = service_fixture(
        fixed_time,
        mode=GuardianMode.NORMAL,
        response=cited_response,
        assertions=(memory,),
        external_disclosure=True,
    )
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Cited planning",
        sensitivity=Sensitivity.PERSONAL,
    )

    reply = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="What should I review about finances?",
        idempotency_key="cited-turn",
    )

    assert reply.output_message is not None
    assert reply.turn is not None
    assert reply.turn.retrieval_manifest_id is not None
    manifest = store.get_retrieval_manifest(reply.turn.retrieval_manifest_id)
    citation = manifest.citations[0]
    assert manifest.external_disclosure is True
    assert reply.output_message.citation_ids == (citation.citation_id,)
    assert reply.output_message.sensitivity is Sensitivity.PERSONAL
    assert reply.turn.evidence_ids == (memory.assertion_id,)
    assert reply.turn.decision_record["selected_citation_ids"] == [citation.citation_id]
    assert reply.turn.decision_record["evidence_ids"] == [memory.assertion_id]
    assert model.requests[0].sensitivity is Sensitivity.PERSONAL
    assert model.requests[0].input["memory_citations"][0]["assertion_id"] == (
        memory.assertion_id
    )

    completed = store.completed_turn_for_trigger(reply.inbound_message.message_id)
    assert completed is not None
    tampered_turn = completed.turn.model_copy(update={"evidence_ids": ()})
    with pytest.raises(ConversationConflictError, match="evidence"):
        store.complete_turn(replace(completed, turn=tampered_turn))


def test_device_only_retrieval_cannot_be_marked_externally_disclosed(fixed_time) -> None:
    memory = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=record_id("owner", 1),
        predicate="secret.review-topic",
        value={"topic": "private"},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.8,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.DEVICE_ONLY,
        observed_at=fixed_time,
    )
    service, store, model = service_fixture(
        fixed_time,
        response={"text": "Unsafe disclosure."},
        assertions=(memory,),
        external_disclosure=True,
    )
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="Device only",
        sensitivity=Sensitivity.DEVICE_ONLY,
    )

    rejected = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Review the private topic",
        idempotency_key="device-only-disclosure",
    )

    assert model.requests[0].sensitivity is Sensitivity.DEVICE_ONLY
    assert model.requests[0].allowed_processing_locations == frozenset(
        {ProcessingLocation.DEVICE}
    )
    assert len(store.list_messages(thread.thread_id)) == 1
    assert store.list_turns(thread.thread_id) == ()
    assert rejected.processing.last_error_code == "model.disclosure_invalid"
    assert rejected.processing.attempts[0].external_disclosure is True
    assert rejected.processing.attempts[0].disclosed_memory_ids == (memory.assertion_id,)


def test_failed_external_model_records_disclosed_memory(fixed_time) -> None:
    memory = Assertion(
        assertion_id=record_id("assertion", 2),
        subject_id=record_id("owner", 1),
        predicate="preference.review-topic",
        value={"topic": "provider failure"},
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=fixed_time,
    )

    invocations = 0

    def fail_provider(_request):
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            return {"text": "First external reply."}
        raise ModelInvocationError(
            provider_id="provider.synthetic-external",
            model_id="review-model-v2",
            processing_location=ProcessingLocation.APPROVED_PROVIDER,
        )

    backend = FakeModelGateway(
        fail_provider,
        clock=lambda: fixed_time,
        external_disclosure=True,
        provider_id="provider.synthetic-external",
    )
    service, store, _model = service_fixture(
        fixed_time,
        mode=GuardianMode.NORMAL,
        assertions=(memory,),
        model_gateway=backend,
    )
    owner = principal(fixed_time)
    thread = service.create_thread(
        owner,
        title="External outage",
        sensitivity=Sensitivity.PERSONAL,
    )
    first = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Remember this context",
        idempotency_key="external-context",
    )
    assert first.output_message is not None
    accepted = service.post_owner_message(
        owner,
        thread_id=thread.thread_id,
        text="Use the provider",
        idempotency_key="external-outage",
    )

    attempt = accepted.processing.attempts[0]
    assert accepted.processing.last_error_code == "model.gateway_failed"
    assert attempt.external_disclosure is True
    assert attempt.model_result_summary is None
    assert attempt.failed_model_target is not None
    assert attempt.failed_model_target.provider_id == "provider.synthetic-external"
    assert attempt.failed_model_target.model_id == "review-model-v2"
    assert (
        attempt.failed_model_target.processing_location
        is ProcessingLocation.APPROVED_PROVIDER
    )
    assert attempt.disclosed_memory_ids == (memory.assertion_id,)
    assert attempt.disclosed_history_message_ids == (
        first.inbound_message.message_id,
        first.output_message.message_id,
    )
    assert attempt.retrieval_manifest_id is not None
    assert store.get_retrieval_manifest(attempt.retrieval_manifest_id).external_disclosure is True
