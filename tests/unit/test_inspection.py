from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.application.inspection import (
    InspectionOwnershipError,
    InspectionWindowError,
    OwnerInspectionService,
    _delivery_summary,
    _processing_summary,
)
from melloa.apps.core import create_app
from melloa.domain.audit import AuditContent
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import canonical_json_bytes, sha256_digest
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingState,
    ConversationReplyWork,
    ConversationThread,
    ConversationTurn,
    DeliveryState,
    MessageKind,
    MessagePart,
)
from melloa.domain.delivery import DeliveryWorkState, DeliveryWorkStatus
from melloa.domain.events import EventEnvelope, EventIntegrity, EventProducer, EventSource
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.inspection import (
    ModelDisclosureInspection,
    OwnerModelActivityReport,
    OwnerTimelineReport,
)
from melloa.domain.memory import AssertionStatus
from melloa.domain.models import (
    ModelAttemptOutcome,
    ModelResult,
    ModelRouteAttempt,
    ProcessingLocation,
)
from melloa.domain.retrieval import MemoryCitation, RetrievalManifest, RetrievalMethod
from melloa.ports.conversation import CompletedConversationTurn
from tests.conftest import record_id

_BOOTSTRAP_TOKEN = "synthetic-bootstrap-token-value-0001"


def _principal(fixed_time: datetime, owner_number: int = 1) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=record_id("owner", owner_number),
        session_id=record_id("session", owner_number),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )


def _guardian(fixed_time: datetime) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="synthetic-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def _citation(fixed_time: datetime, number: int) -> MemoryCitation:
    return MemoryCitation(
        citation_id=record_id("citation", number),
        assertion_id=record_id("assertion", number),
        predicate=f"preference.review-{number}",
        value={"topic": f"synthetic-{number}"},
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        assertion_status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=fixed_time,
        provenance_edge_ids=(),
        rank_score=1.0,
        rank_reasons=("rank.owner-authored",),
    )


def _append_completed_turn(
    store: InMemoryConversationStore,
    thread: ConversationThread,
    fixed_time: datetime,
    *,
    number: int,
    external_disclosure: bool,
    input_tokens: int,
    output_tokens: int,
    cost_gbp: float,
    citations: tuple[MemoryCitation, ...] = (),
) -> CompletedConversationTurn:
    completed_at = fixed_time + timedelta(hours=number)
    inbound = ConversationMessage(
        message_id=record_id("message", number * 2 - 1),
        thread_id=thread.thread_id,
        author_principal_id=thread.owner_id,
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text=f"Synthetic prompt {number}"),),
        delivery_state=DeliveryState.DELIVERED,
        sensitivity=Sensitivity.PERSONAL,
        created_at=completed_at - timedelta(minutes=1),
        observed_at=completed_at - timedelta(minutes=1),
    )
    store.append_inbound(
        inbound,
        f"inspection:{number}",
        ConversationReplyWork(
            work_id=record_id("work", number),
            thread_id=thread.thread_id,
            message_id=inbound.message_id,
            created_at=inbound.created_at,
        ),
        max_attempts=3,
    )
    selected_citations = (citations[0].citation_id,) if citations else ()
    output = ConversationMessage(
        message_id=record_id("message", number * 2),
        thread_id=thread.thread_id,
        author_principal_id=thread.intelligence_id,
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text=f"Synthetic reply {number}"),),
        reply_to_message_id=inbound.message_id,
        citation_ids=selected_citations,
        delivery_state=DeliveryState.DELIVERED,
        sensitivity=Sensitivity.PERSONAL,
        created_at=completed_at,
        observed_at=completed_at,
    )
    manifest = RetrievalManifest(
        manifest_id=record_id("retrieval_manifest", number),
        requester_id=thread.intelligence_id,
        subject_id=thread.owner_id,
        purpose="conversation.owner-reply",
        query_hash=sha256_digest(f"query-{number}".encode()),
        allowed_sensitivities=frozenset({Sensitivity.PERSONAL}),
        methods=(RetrievalMethod.EXACT_RELATIONAL,),
        candidate_assertion_ids=tuple(
            citation.assertion_id for citation in citations
        ),
        citations=citations,
        excluded_assertion_ids=(),
        created_at=completed_at - timedelta(minutes=1),
        external_disclosure=external_disclosure,
    )
    location = (
        ProcessingLocation.APPROVED_PROVIDER
        if external_disclosure
        else ProcessingLocation.DEVICE
    )
    route_id = "model.synthetic-remote" if external_disclosure else "model.synthetic-local"
    attempt = ModelRouteAttempt(
        route_id=route_id,
        provider_id="provider.synthetic",
        model_id=f"synthetic-model-{number}",
        processing_location=location,
        outcome=ModelAttemptOutcome.SUCCEEDED,
        started_at=completed_at - timedelta(seconds=1),
        completed_at=completed_at,
        external_disclosure=external_disclosure,
    )
    result = ModelResult(
        result_id=record_id("model_result", number),
        request_id=record_id("request", number),
        route_id=attempt.route_id,
        provider_id=attempt.provider_id,
        model_id=attempt.model_id,
        output={"text": f"raw-output-{number}"},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_gbp=cost_gbp,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
        external_disclosure=external_disclosure,
        attempts=(attempt,),
    )
    turn = ConversationTurn(
        turn_id=record_id("turn", number),
        thread_id=thread.thread_id,
        triggering_message_ids=(inbound.message_id,),
        retrieval_manifest_id=manifest.manifest_id,
        evidence_ids=tuple(citation.assertion_id for citation in citations[:1]),
        model_run_ids=(result.result_id,),
        output_message_ids=(output.message_id,),
        decision_record={"summary": "Synthetic inspection fixture."},
        started_at=inbound.created_at,
        completed_at=completed_at,
    )
    completed = CompletedConversationTurn(
        turn=turn,
        output_message=output,
        model_result=result,
        retrieval_manifest=manifest,
    )
    store.complete_turn(completed)
    return completed


def _populated_store(fixed_time: datetime) -> tuple[InMemoryConversationStore, ConversationThread]:
    store = InMemoryConversationStore()
    thread = ConversationThread(
        thread_id=record_id("thread", 1),
        owner_id=record_id("owner", 1),
        intelligence_id=record_id("intelligence", 1),
        title="Synthetic model activity",
        sensitivity=Sensitivity.PERSONAL,
        retention_policy="retention.owner-conversation",
        created_at=fixed_time,
        updated_at=fixed_time,
    )
    store.create_thread(thread)
    _append_completed_turn(
        store,
        thread,
        fixed_time,
        number=1,
        external_disclosure=True,
        input_tokens=120,
        output_tokens=30,
        cost_gbp=0.5,
        citations=(_citation(fixed_time, 1), _citation(fixed_time, 2)),
    )
    _append_completed_turn(
        store,
        thread,
        fixed_time,
        number=2,
        external_disclosure=False,
        input_tokens=80,
        output_tokens=20,
        cost_gbp=0.25,
    )
    return store, thread


def test_owner_model_activity_reports_cost_and_every_disclosed_memory(fixed_time) -> None:
    store, thread = _populated_store(fixed_time)
    service = OwnerInspectionService(
        owner_id=thread.owner_id,
        conversation_store=store,
        clock=lambda: fixed_time + timedelta(hours=3),
    )

    report = service.model_activity(
        _principal(fixed_time),
        window_start=fixed_time,
        window_end=fixed_time + timedelta(hours=3),
    )

    assert report.total_runs == 2
    assert report.external_disclosure_runs == 1
    assert report.total_input_tokens == 200
    assert report.total_output_tokens == 50
    assert report.total_cost_gbp == 0.75
    assert report.external_cost_gbp == 0.5
    external, local = report.entries
    assert external.disclosure is not None
    assert tuple(
        reference.assertion_id for reference in external.disclosure.memory_references
    ) == (record_id("assertion", 1), record_id("assertion", 2))
    assert external.disclosure.triggering_message_ids == (record_id("message", 1),)
    assert len(external.disclosure.external_attempts) == 1
    assert local.disclosure is None
    assert "raw-output" not in report.model_dump_json()

    narrow = service.model_activity(
        _principal(fixed_time),
        window_start=fixed_time + timedelta(hours=1, microseconds=1),
        window_end=fixed_time + timedelta(hours=3),
    )
    assert tuple(entry.result_id for entry in narrow.entries) == (
        record_id("model_result", 2),
    )


def test_owner_timeline_aggregates_canonical_records_without_content(fixed_time) -> None:
    store, thread = _populated_store(fixed_time)
    service = OwnerInspectionService(
        owner_id=thread.owner_id,
        conversation_store=store,
        clock=lambda: fixed_time + timedelta(hours=3),
    )

    report = service.timeline(
        _principal(fixed_time),
        window_start=fixed_time,
        window_end=fixed_time + timedelta(hours=3),
        limit=50,
    )

    assert report.coverage == (
        "timeline.coverage.canonical-conversation",
        "timeline.coverage.model-activity",
        "timeline.coverage.reply-processing",
    )
    assert "timeline.limit.no-message-or-model-text" in report.limitations
    assert "timeline.limit.no-outbound-delivery-store-configured" in report.limitations
    assert "timeline.limit.newest-events-only" not in report.limitations
    assert report.matching_events == report.total_events
    assert report.truncated is False
    assert report.entries == tuple(
        sorted(
            report.entries,
            key=lambda entry: (entry.occurred_at, entry.event_id),
            reverse=True,
        )
    )
    kinds = {entry.kind for entry in report.entries}
    assert {
        "timeline.conversation.thread-created",
        "timeline.conversation.message-created",
        "timeline.conversation.turn-recorded",
        "timeline.reply-processing.ready",
        "timeline.model-route.completed",
    } <= kinds
    external_model = next(
        entry
        for entry in report.entries
        if entry.kind == "timeline.model-route.completed"
        and entry.status == "model.disclosure.external"
    )
    assert external_model.references == (
        record_id("request", 1),
        record_id("retrieval_manifest", 1),
        record_id("message", 1),
        record_id("assertion", 1),
        record_id("assertion", 2),
    )
    assert external_model.metadata["disclosed_memory_count"] == 2
    encoded = report.model_dump_json()
    assert "Synthetic prompt" not in encoded
    assert "Synthetic reply" not in encoded
    assert "raw-output" not in encoded

    limited = service.timeline(
        _principal(fixed_time),
        window_start=fixed_time,
        window_end=fixed_time + timedelta(hours=3),
        limit=3,
    )
    assert limited.total_events == 3
    assert limited.matching_events == report.total_events
    assert limited.truncated is True
    assert "timeline.limit.newest-events-only" in limited.limitations
    assert len(limited.entries) == 3


def test_owner_timeline_includes_redacted_export_audit_events(fixed_time) -> None:
    store, thread = _populated_store(fixed_time)
    audit_store = InMemoryEventAuditStore()
    payload = {
        "export_id": record_id("export", 1),
        "format_id": "melloa.canonical-owner-export",
        "format_version": "1.0.0",
        "encrypted": False,
        "includes_sql_snapshot": False,
        "includes_blobs": False,
        "file_count": 12,
        "data_file_count": 8,
        "exported_record_count": 21,
        "limitation_count": 4,
        "limitation_ids": ("export.preview-unencrypted",),
        "archive_path": "server-workspace/melloa-owner-export/owner-export.zip",
        "content_hash": "sha256:" + "a" * 64,
        "message_text": "Synthetic prompt",
        "result": "generated",
    }
    event = EventEnvelope(
        event_id=record_id("event", 1),
        event_type="export.owner-preview-generated.v1",
        schema_version="1.0.0",
        occurred_at=fixed_time + timedelta(hours=2, minutes=30),
        recorded_at=fixed_time + timedelta(hours=2, minutes=30),
        subject_ids=(thread.owner_id, record_id("export", 1)),
        source=EventSource(
            capability_id="export.owner-preview",
            execution_id=record_id("event", 1),
        ),
        producer=EventProducer(component="export.private-core", version="0.1.0"),
        epistemic_status=EpistemicStatus.OBSERVATION,
        sensitivity=Sensitivity.INTERNAL,
        trust=TrustLabel.TRUSTED_SYSTEM,
        retention_policy="retention.audit-ledger",
        payload=payload,
        integrity=EventIntegrity(payload_hash=sha256_digest(canonical_json_bytes(payload))),
    )
    audit_store.append_event(
        event,
        AuditContent(
            audit_id=record_id("audit", 1),
            event_type="audit.event-appended.v1",
            occurred_at=event.occurred_at,
            actor_id=thread.owner_id,
            action="export.owner-preview.generate",
            object_ids=(event.event_id, record_id("export", 1)),
            metadata={"event_id": event.event_id, "result": "generated"},
        ),
    )
    service = OwnerInspectionService(
        owner_id=thread.owner_id,
        conversation_store=store,
        event_audit_store=audit_store,
        clock=lambda: fixed_time + timedelta(hours=3),
    )

    report = service.timeline(
        _principal(fixed_time),
        window_start=fixed_time,
        window_end=fixed_time + timedelta(hours=3),
    )

    assert "timeline.coverage.owner-export-audit-projection" in report.coverage
    assert "timeline.limit.no-audit-event-store-configured" not in report.limitations
    audit_event = next(
        entry
        for entry in report.entries
        if entry.kind == "timeline.audit.owner-export-preview-generated"
    )
    assert audit_event.source == "timeline.source.audit-ledger"
    assert audit_event.status == "audit.owner-export-preview.generated"
    assert audit_event.references == (record_id("export", 1), record_id("event", 1))
    assert audit_event.metadata == {
        "export_id": record_id("export", 1),
        "source_event_id": record_id("event", 1),
        "format_id": "melloa.canonical-owner-export",
        "format_version": "1.0.0",
        "file_count": 12,
        "data_file_count": 8,
        "exported_record_count": 21,
        "limitation_count": 4,
        "encrypted": False,
        "includes_sql_snapshot": False,
        "includes_blobs": False,
    }
    encoded = report.model_dump_json()
    assert "Synthetic prompt" not in encoded
    assert "owner-export.zip" not in encoded
    assert "sha256:" + "a" * 64 not in encoded
    assert "export.preview-unencrypted" not in encoded


def test_owner_timeline_includes_delivery_when_configured(fixed_time) -> None:
    store, thread = _populated_store(fixed_time)
    delivery_status = DeliveryWorkStatus(
        work_id=record_id("deliverywork", 1),
        thread_id=thread.thread_id,
        message_id=record_id("message", 2),
        client_adapter="client.telegram.synthetic",
        destination_ref="synthetic:owner",
        action_hash="sha256:" + "2" * 64,
        current_policy_decision_id=record_id("decision", 1),
        state=DeliveryWorkState.READY,
        attempt_count=0,
        max_attempts=3,
        available_at=fixed_time + timedelta(hours=2, minutes=1),
    )
    outside_window = delivery_status.model_copy(
        update={
            "work_id": record_id("deliverywork", 2),
            "available_at": fixed_time + timedelta(days=2),
        }
    )

    class TimelineDelivery:
        def list_deliveries(
            self,
            principal: AuthenticatedOwner,
            thread_id: str,
        ) -> tuple[DeliveryWorkStatus, ...]:
            assert principal.owner_id == thread.owner_id
            assert thread_id == thread.thread_id
            return (delivery_status, outside_window)

    service = OwnerInspectionService(
        owner_id=thread.owner_id,
        conversation_store=store,
        delivery=TimelineDelivery(),  # type: ignore[arg-type]
        clock=lambda: fixed_time + timedelta(hours=3),
    )

    report = service.timeline(
        _principal(fixed_time),
        window_start=fixed_time,
        window_end=fixed_time + timedelta(hours=3),
    )

    assert "timeline.coverage.outbound-delivery" in report.coverage
    assert "timeline.limit.no-outbound-delivery-store-configured" not in report.limitations
    delivery_event = next(
        entry
        for entry in report.entries
        if entry.kind == "timeline.outbound-delivery.ready"
    )
    assert delivery_event.status == "delivery.work.ready"
    assert delivery_event.metadata["client_adapter"] == "client.telegram.synthetic"
    assert record_id("deliverywork", 2) not in report.model_dump_json()


def test_timeline_state_summaries_are_owner_visible() -> None:
    assert (
        _processing_summary(ConversationProcessingState.COMPLETED)
        == "Reply processing completed."
    )
    assert (
        _processing_summary(ConversationProcessingState.DEAD)
        == "Reply processing reached terminal failure."
    )
    assert (
        _processing_summary(ConversationProcessingState.RUNNING)
        == "Reply processing is leased to a worker."
    )
    assert (
        _processing_summary(ConversationProcessingState.CANCELLED)
        == "Reply processing was cancelled."
    )
    assert (
        _processing_summary(ConversationProcessingState.READY)
        == "Reply processing is queued or waiting."
    )
    assert (
        _delivery_summary(DeliveryWorkState.COMPLETED)
        == "Outbound delivery completed under exact authorization."
    )
    assert (
        _delivery_summary(DeliveryWorkState.DEAD)
        == "Outbound delivery reached terminal failure."
    )
    assert (
        _delivery_summary(DeliveryWorkState.RUNNING)
        == "Outbound delivery is leased to a worker."
    )
    assert (
        _delivery_summary(DeliveryWorkState.CANCELLED)
        == "Outbound delivery was cancelled."
    )
    assert (
        _delivery_summary(DeliveryWorkState.READY)
        == "Outbound delivery is queued or waiting."
    )


def test_timeline_rejects_bad_owner_window_limit_and_contract_shape(fixed_time) -> None:
    store, thread = _populated_store(fixed_time)
    service = OwnerInspectionService(
        owner_id=thread.owner_id,
        conversation_store=store,
        clock=lambda: fixed_time + timedelta(hours=3),
    )

    with pytest.raises(InspectionOwnershipError):
        service.timeline(_principal(fixed_time, owner_number=2))
    with pytest.raises(InspectionWindowError, match="limit"):
        service.timeline(_principal(fixed_time), limit=0)
    with pytest.raises(InspectionWindowError, match="end after"):
        service.timeline(
            _principal(fixed_time),
            window_start=fixed_time,
            window_end=fixed_time,
        )

    report = service.timeline(
        _principal(fixed_time),
        window_start=fixed_time,
        window_end=fixed_time + timedelta(hours=3),
    )
    with pytest.raises(ValidationError, match="total"):
        OwnerTimelineReport.model_validate({**report.model_dump(), "total_events": 99})
    with pytest.raises(ValidationError, match="matching total"):
        OwnerTimelineReport.model_validate({**report.model_dump(), "matching_events": 0})
    with pytest.raises(ValidationError, match="truncation state"):
        OwnerTimelineReport.model_validate({**report.model_dump(), "truncated": True})
    with pytest.raises(ValidationError, match="newest-first"):
        OwnerTimelineReport.model_validate(
            {**report.model_dump(), "entries": tuple(reversed(report.entries))}
        )
    with pytest.raises(ValidationError, match="coverage values"):
        OwnerTimelineReport.model_validate(
            {
                **report.model_dump(),
                "coverage": (
                    report.coverage[0],
                    report.coverage[0],
                    *report.coverage[1:],
                ),
            }
        )
    with pytest.raises(ValidationError, match="canonical owner records"):
        report.entries[0].__class__.model_validate(
            {
                **report.entries[0].model_dump(),
                "thread_id": None,
                "message_id": None,
                "turn_id": None,
                "work_id": None,
                "references": (),
            }
        )


def test_model_activity_rejects_bad_owner_window_and_contract_totals(fixed_time) -> None:
    store, thread = _populated_store(fixed_time)
    service = OwnerInspectionService(
        owner_id=thread.owner_id,
        conversation_store=store,
        clock=lambda: fixed_time + timedelta(hours=3),
    )
    with pytest.raises(InspectionOwnershipError):
        service.model_activity(_principal(fixed_time, owner_number=2))
    with pytest.raises(InspectionWindowError, match="timezone"):
        service.model_activity(
            _principal(fixed_time),
            window_start=fixed_time.replace(tzinfo=None),
        )
    with pytest.raises(InspectionWindowError, match="end after"):
        service.model_activity(
            _principal(fixed_time),
            window_start=fixed_time,
            window_end=fixed_time,
        )
    with pytest.raises(InspectionWindowError, match="366 days"):
        service.model_activity(
            _principal(fixed_time),
            window_start=fixed_time - timedelta(days=367),
            window_end=fixed_time,
        )

    report = service.model_activity(
        _principal(fixed_time),
        window_start=fixed_time,
        window_end=fixed_time + timedelta(hours=3),
    )
    with pytest.raises(ValidationError, match="totals"):
        OwnerModelActivityReport.model_validate(
            {**report.model_dump(), "total_runs": 99}
        )
    with pytest.raises(ValidationError, match="deterministic completion order"):
        OwnerModelActivityReport.model_validate(
            {**report.model_dump(), "entries": tuple(reversed(report.entries))}
        )
    with pytest.raises(ValidationError, match="detail does not match"):
        report.entries[0].__class__.model_validate(
            {**report.entries[0].model_dump(), "disclosure": None}
        )
    with pytest.raises(ValidationError, match="cannot complete before"):
        report.entries[0].__class__.model_validate(
            {
                **report.entries[0].model_dump(),
                "started_at": report.entries[0].completed_at + timedelta(seconds=1),
            }
        )
    disclosure = report.entries[0].disclosure
    assert disclosure is not None
    first_reference, second_reference = disclosure.memory_references
    with pytest.raises(ValidationError, match="citation IDs must be unique"):
        ModelDisclosureInspection.model_validate(
            {
                **disclosure.model_dump(),
                "memory_references": (first_reference, first_reference),
            }
        )
    with pytest.raises(ValidationError, match="assertion can be disclosed only once"):
        ModelDisclosureInspection.model_validate(
            {
                **disclosure.model_dump(),
                "memory_references": (
                    first_reference,
                    second_reference.model_copy(
                        update={"assertion_id": first_reference.assertion_id}
                    ),
                ),
            }
        )
    with pytest.raises(ValidationError, match="local model attempts"):
        ModelDisclosureInspection.model_validate(
            {
                **disclosure.model_dump(),
                "external_attempts": report.entries[1].model_dump()["disclosure"]
                or (
                    ModelRouteAttempt(
                        route_id="model.synthetic-local",
                        provider_id="provider.synthetic",
                        model_id="synthetic-local",
                        processing_location=ProcessingLocation.DEVICE,
                        outcome=ModelAttemptOutcome.SUCCEEDED,
                        started_at=fixed_time,
                        completed_at=fixed_time,
                        external_disclosure=False,
                    ),
                ),
            }
        )
    with pytest.raises(ValidationError, match="window must end after"):
        OwnerModelActivityReport.model_validate(
            {**report.model_dump(), "window_end": report.window_start}
        )
    with pytest.raises(ValidationError, match="result IDs must be unique"):
        OwnerModelActivityReport.model_validate(
            {
                **report.model_dump(),
                "total_runs": 2,
                "external_disclosure_runs": 2,
                "total_input_tokens": report.entries[0].input_tokens * 2,
                "total_output_tokens": report.entries[0].output_tokens * 2,
                "total_cost_gbp": report.entries[0].cost_gbp * 2,
                "external_cost_gbp": report.entries[0].cost_gbp * 2,
                "entries": (report.entries[0], report.entries[0]),
            }
        )
    with pytest.raises(ValidationError, match="outside the report window"):
        OwnerModelActivityReport.model_validate(
            {
                **report.model_dump(),
                "window_start": report.entries[0].completed_at + timedelta(microseconds=1),
            }
        )


def test_authenticated_model_activity_api_is_bounded_and_fail_closed(fixed_time) -> None:
    store, thread = _populated_store(fixed_time)
    inspection = OwnerInspectionService(
        owner_id=thread.owner_id,
        conversation_store=store,
        clock=lambda: fixed_time + timedelta(hours=3),
    )
    tokens = iter(("session-token", "csrf-token"))
    sessions = InMemoryOwnerSessionManager(
        thread.owner_id,
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    client = TestClient(
        create_app(_guardian(fixed_time), sessions, inspection_service=inspection),
        base_url="https://testserver",
    )
    endpoint = "/api/v1/inspection/model-activity"
    assert client.get(endpoint).status_code == 401
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert login.status_code == 200
    report = client.get(
        endpoint,
        params={
            "from": fixed_time.isoformat(),
            "to": (fixed_time + timedelta(hours=3)).isoformat(),
        },
    )
    assert report.status_code == 200
    assert report.json()["total_cost_gbp"] == 0.75
    assert len(report.json()["entries"][0]["disclosure"]["memory_references"]) == 2
    invalid = client.get(
        endpoint,
        params={"from": fixed_time.isoformat(), "to": fixed_time.isoformat()},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_inspection_window"

    absent_client = TestClient(
        create_app(_guardian(fixed_time), sessions),
        base_url="https://testserver",
    )
    absent_client.cookies.update(client.cookies)
    absent = absent_client.get(endpoint)
    assert absent.status_code == 503
    assert absent.json()["detail"] == "Owner activity inspection is not configured."

    foreign_inspection = OwnerInspectionService(
        owner_id=record_id("owner", 2),
        conversation_store=store,
        clock=lambda: fixed_time,
    )
    foreign_client = TestClient(
        create_app(
            _guardian(fixed_time),
            sessions,
            inspection_service=foreign_inspection,
        ),
        base_url="https://testserver",
    )
    foreign_client.cookies.update(client.cookies)
    concealed = foreign_client.get(endpoint)
    assert concealed.status_code == 404
    assert concealed.json()["code"] == "inspection_not_found"


def test_authenticated_timeline_api_is_bounded_and_fail_closed(fixed_time) -> None:
    store, thread = _populated_store(fixed_time)
    inspection = OwnerInspectionService(
        owner_id=thread.owner_id,
        conversation_store=store,
        clock=lambda: fixed_time + timedelta(hours=3),
    )
    tokens = iter(("session-token", "csrf-token"))
    sessions = InMemoryOwnerSessionManager(
        thread.owner_id,
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )
    client = TestClient(
        create_app(_guardian(fixed_time), sessions, inspection_service=inspection),
        base_url="https://testserver",
    )
    endpoint = "/api/v1/inspection/timeline"
    assert client.get(endpoint).status_code == 401
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert login.status_code == 200
    report = client.get(
        endpoint,
        params={
            "from": fixed_time.isoformat(),
            "to": (fixed_time + timedelta(hours=3)).isoformat(),
            "limit": 5,
        },
    )
    assert report.status_code == 200
    assert report.json()["total_events"] == 5
    assert all("Synthetic prompt" not in str(entry) for entry in report.json()["entries"])
    invalid = client.get(endpoint, params={"limit": 0})
    assert invalid.status_code == 422

    absent_client = TestClient(
        create_app(_guardian(fixed_time), sessions),
        base_url="https://testserver",
    )
    absent_client.cookies.update(client.cookies)
    absent = absent_client.get(endpoint)
    assert absent.status_code == 503
    assert absent.json()["detail"] == "Owner activity inspection is not configured."

    foreign_inspection = OwnerInspectionService(
        owner_id=record_id("owner", 2),
        conversation_store=store,
        clock=lambda: fixed_time,
    )
    foreign_client = TestClient(
        create_app(
            _guardian(fixed_time),
            sessions,
            inspection_service=foreign_inspection,
        ),
        base_url="https://testserver",
    )
    foreign_client.cookies.update(client.cookies)
    concealed = foreign_client.get(endpoint)
    assert concealed.status_code == 404
    assert concealed.json()["code"] == "inspection_not_found"
