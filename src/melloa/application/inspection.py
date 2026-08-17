"""Authenticated owner inspection of redacted model cost and disclosure activity."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta

from melloa.application.delivery import DeliveryService
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import (
    JsonObject,
    QualifiedName,
    RecordId,
    canonical_json_bytes,
    sha256_digest,
    utc_now,
)
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import ConversationProcessingState
from melloa.domain.delivery import DeliveryWorkState
from melloa.domain.inspection import (
    DisclosedMemoryReference,
    ModelActivityEntry,
    ModelDisclosureInspection,
    OwnerModelActivityReport,
    OwnerTimelineEvent,
    OwnerTimelineReport,
)
from melloa.ports.conversation import CompletedConversationTurn, ConversationStore

_DEFAULT_WINDOW = timedelta(days=7)
_MAXIMUM_WINDOW = timedelta(days=366)
_DEFAULT_TIMELINE_LIMIT = 100
_MAXIMUM_TIMELINE_LIMIT = 500


class InspectionOwnershipError(PermissionError):
    """An authenticated owner attempted to inspect another runtime."""


class InspectionWindowError(ValueError):
    """A requested inspection window is invalid or unbounded."""


class OwnerInspectionService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        conversation_store: ConversationStore,
        delivery: DeliveryService | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._owner_id = owner_id
        self._conversation_store = conversation_store
        self._delivery = delivery
        self._clock = clock

    def model_activity(
        self,
        principal: AuthenticatedOwner,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> OwnerModelActivityReport:
        self._require_owner(principal)
        generated_at = self._clock()
        end = window_end or generated_at
        start = window_start or end - _DEFAULT_WINDOW
        self._validate_window(start, end)
        completed_turns = self._conversation_store.list_completed_turns(
            self._owner_id,
            completed_from=start,
            completed_before=end,
        )
        entries = tuple(self._entry(completed) for completed in completed_turns)
        return OwnerModelActivityReport(
            owner_id=self._owner_id,
            window_start=start,
            window_end=end,
            generated_at=generated_at,
            total_runs=len(entries),
            external_disclosure_runs=sum(entry.external_disclosure for entry in entries),
            total_input_tokens=sum(entry.input_tokens for entry in entries),
            total_output_tokens=sum(entry.output_tokens for entry in entries),
            total_cost_gbp=math.fsum(entry.cost_gbp for entry in entries),
            external_cost_gbp=math.fsum(
                entry.cost_gbp for entry in entries if entry.external_disclosure
            ),
            entries=entries,
        )

    def timeline(
        self,
        principal: AuthenticatedOwner,
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        limit: int = _DEFAULT_TIMELINE_LIMIT,
    ) -> OwnerTimelineReport:
        self._require_owner(principal)
        if not 1 <= limit <= _MAXIMUM_TIMELINE_LIMIT:
            raise InspectionWindowError("timeline limit must be between 1 and 500")
        generated_at = self._clock()
        end = window_end or generated_at
        start = window_start or end - _DEFAULT_WINDOW
        self._validate_window(start, end)
        entries = list(self._timeline_entries(principal, start, end))
        entries.sort(key=lambda entry: (entry.occurred_at, entry.event_id), reverse=True)
        bounded = tuple(entries[:limit])
        coverage: list[QualifiedName] = [
            "timeline.coverage.canonical-conversation",
            "timeline.coverage.model-activity",
            "timeline.coverage.reply-processing",
        ]
        if self._delivery is not None:
            coverage.append("timeline.coverage.outbound-delivery")
        limitations: list[QualifiedName] = [
            "timeline.limit.current-mvp-canonical-records",
            "timeline.limit.no-message-or-model-text",
            "timeline.limit.no-process-local-auth-events",
        ]
        if self._delivery is None:
            limitations.append("timeline.limit.no-outbound-delivery-store-configured")
        return OwnerTimelineReport(
            owner_id=self._owner_id,
            window_start=start,
            window_end=end,
            generated_at=generated_at,
            total_events=len(bounded),
            coverage=tuple(sorted(coverage)),
            limitations=tuple(sorted(limitations)),
            entries=bounded,
        )

    def _entry(self, completed: CompletedConversationTurn) -> ModelActivityEntry:
        result = completed.model_result
        manifest = completed.retrieval_manifest
        disclosure = None
        if result.external_disclosure:
            disclosure = ModelDisclosureInspection(
                retrieval_manifest_id=manifest.manifest_id,
                purpose=manifest.purpose,
                triggering_message_ids=completed.turn.triggering_message_ids,
                memory_references=tuple(
                    DisclosedMemoryReference(
                        citation_id=citation.citation_id,
                        assertion_id=citation.assertion_id,
                        sensitivity=citation.sensitivity,
                    )
                    for citation in manifest.citations
                ),
                external_attempts=tuple(
                    attempt for attempt in result.attempts if attempt.external_disclosure
                ),
            )
        return ModelActivityEntry(
            turn_id=completed.turn.turn_id,
            thread_id=completed.turn.thread_id,
            result_id=result.result_id,
            request_id=result.request_id,
            route_id=result.route_id,
            provider_id=result.provider_id,
            model_id=result.model_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_gbp=result.cost_gbp,
            started_at=result.started_at,
            completed_at=result.completed_at,
            external_disclosure=result.external_disclosure,
            disclosure=disclosure,
        )

    def _timeline_entries(
        self,
        principal: AuthenticatedOwner,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[OwnerTimelineEvent, ...]:
        events: list[OwnerTimelineEvent] = []
        threads = self._conversation_store.list_threads(self._owner_id)
        for thread in threads:
            if window_start <= thread.created_at < window_end:
                events.append(
                    self._timeline_event(
                        "timeline.conversation.thread-created",
                        record_id=thread.thread_id,
                        occurred_at=thread.created_at,
                        source="timeline.source.canonical-conversation",
                        summary="Canonical conversation thread created.",
                        thread_id=thread.thread_id,
                        status=f"conversation.thread.{thread.status.value}",
                        sensitivity=thread.sensitivity,
                        metadata={
                            "retention_policy": thread.retention_policy,
                            "title_length": len(thread.title),
                        },
                    )
                )
            messages = self._conversation_store.list_messages(thread.thread_id)
            for message in messages:
                if not window_start <= message.created_at < window_end:
                    continue
                is_owner = message.author_principal_id == self._owner_id
                source = (
                    "timeline.source.owner-message"
                    if is_owner
                    else "timeline.source.intelligence-message"
                )
                summary = (
                    "Owner message accepted into canonical conversation."
                    if is_owner
                    else "Melli reply persisted in canonical conversation."
                )
                events.append(
                    self._timeline_event(
                        "timeline.conversation.message-created",
                        record_id=message.message_id,
                        occurred_at=message.created_at,
                        source=source,
                        summary=summary,
                        thread_id=message.thread_id,
                        message_id=message.message_id,
                        status=f"conversation.delivery.{message.delivery_state.value}",
                        sensitivity=message.sensitivity,
                        references=tuple(
                            reference
                            for reference in (
                                message.reply_to_message_id,
                                message.corrects_message_id,
                                *message.citation_ids,
                            )
                            if reference is not None
                        ),
                        metadata={
                            "source_client": message.source_client,
                            "part_count": len(message.parts),
                            "citation_count": len(message.citation_ids),
                            "contains_text": any(part.text is not None for part in message.parts),
                            "contains_attachment_reference": any(
                                part.attachment_id is not None for part in message.parts
                            ),
                        },
                    )
                )
            for turn in self._conversation_store.list_turns(thread.thread_id):
                occurred_at = turn.completed_at or turn.started_at
                if not window_start <= occurred_at < window_end:
                    continue
                events.append(
                    self._timeline_event(
                        "timeline.conversation.turn-recorded",
                        record_id=turn.turn_id,
                        occurred_at=occurred_at,
                        source="timeline.source.structured-turn",
                        summary="Structured reply turn recorded with decision evidence.",
                        thread_id=turn.thread_id,
                        turn_id=turn.turn_id,
                        status=(
                            "conversation.turn.completed"
                            if turn.completed_at is not None
                            else "conversation.turn.started"
                        ),
                        references=(
                            *turn.triggering_message_ids,
                            *turn.evidence_ids,
                            *turn.model_run_ids,
                            *turn.policy_decision_ids,
                            *turn.proposed_action_ids,
                            *turn.executed_action_ids,
                            *turn.output_message_ids,
                        ),
                        metadata={
                            "trigger_count": len(turn.triggering_message_ids),
                            "evidence_count": len(turn.evidence_ids),
                            "model_run_count": len(turn.model_run_ids),
                            "policy_decision_count": len(turn.policy_decision_ids),
                            "executed_action_count": len(turn.executed_action_ids),
                        },
                    )
                )
            for processing in self._conversation_store.list_reply_processing(
                thread.thread_id
            ):
                occurred_at = processing.completed_at or processing.available_at
                if not window_start <= occurred_at < window_end:
                    continue
                events.append(
                    self._timeline_event(
                        f"timeline.reply-processing.{processing.state.value}",
                        record_id=processing.work_id,
                        occurred_at=occurred_at,
                        source="timeline.source.reply-processing",
                        summary=_processing_summary(processing.state),
                        thread_id=processing.thread_id,
                        message_id=processing.message_id,
                        work_id=processing.work_id,
                        status=f"conversation.processing.{processing.state.value}",
                        references=tuple(
                            attempt.attempt_id for attempt in processing.attempts
                        )
                        + tuple(
                            resumption.resumption_id
                            for resumption in processing.resumptions
                        ),
                        metadata={
                            "attempt_count": processing.attempt_count,
                            "max_attempts": processing.max_attempts,
                            "last_error_code": processing.last_error_code,
                            "resumption_count": len(processing.resumptions),
                        },
                    )
                )
            if self._delivery is not None:
                for delivery in self._delivery.list_deliveries(
                    principal,
                    thread.thread_id,
                ):
                    occurred_at = delivery.completed_at or delivery.available_at
                    if not window_start <= occurred_at < window_end:
                        continue
                    events.append(
                        self._timeline_event(
                            f"timeline.outbound-delivery.{delivery.state.value}",
                            record_id=delivery.work_id,
                            occurred_at=occurred_at,
                            source="timeline.source.outbound-delivery",
                            summary=_delivery_summary(delivery.state),
                            thread_id=delivery.thread_id,
                            message_id=delivery.message_id,
                            work_id=delivery.work_id,
                            status=f"delivery.work.{delivery.state.value}",
                            references=tuple(
                                attempt.attempt_id for attempt in delivery.attempts
                            )
                            + tuple(
                                resumption.resumption_id
                                for resumption in delivery.resumptions
                            ),
                            metadata={
                                "client_adapter": delivery.client_adapter,
                                "attempt_count": delivery.attempt_count,
                                "max_attempts": delivery.max_attempts,
                                "last_error_code": delivery.last_error_code,
                                "resumption_count": len(delivery.resumptions),
                            },
                        )
                    )
        activity = self.model_activity(
            principal,
            window_start=window_start,
            window_end=window_end,
        )
        for entry in activity.entries:
            events.append(
                self._timeline_event(
                    "timeline.model-route.completed",
                    record_id=entry.result_id,
                    occurred_at=entry.completed_at,
                    source="timeline.source.model-activity",
                    summary=(
                        "Model route completed with external disclosure evidence."
                        if entry.external_disclosure
                        else "Device or private model route completed."
                    ),
                    thread_id=entry.thread_id,
                    turn_id=entry.turn_id,
                    status=(
                        "model.disclosure.external"
                        if entry.external_disclosure
                        else "model.disclosure.local"
                    ),
                    references=(
                        (entry.request_id,)
                        + (
                            ()
                            if entry.disclosure is None
                            else (
                                entry.disclosure.retrieval_manifest_id,
                                *entry.disclosure.triggering_message_ids,
                                *(
                                    reference.assertion_id
                                    for reference in entry.disclosure.memory_references
                                ),
                            )
                        )
                    ),
                    metadata={
                        "route_id": entry.route_id,
                        "provider_id": entry.provider_id,
                        "model_id": entry.model_id,
                        "input_tokens": entry.input_tokens,
                        "output_tokens": entry.output_tokens,
                        "cost_gbp": entry.cost_gbp,
                        "external_disclosure": entry.external_disclosure,
                        "disclosed_memory_count": 0
                        if entry.disclosure is None
                        else len(entry.disclosure.memory_references),
                    },
                )
            )
        return tuple(events)

    def _timeline_event(
        self,
        kind: QualifiedName,
        *,
        record_id: RecordId,
        occurred_at: datetime,
        source: QualifiedName,
        summary: str,
        thread_id: RecordId | None = None,
        message_id: RecordId | None = None,
        turn_id: RecordId | None = None,
        work_id: RecordId | None = None,
        status: QualifiedName | None = None,
        sensitivity: Sensitivity | None = None,
        references: tuple[RecordId, ...] = (),
        metadata: JsonObject | None = None,
    ) -> OwnerTimelineEvent:
        digest = sha256_digest(
            canonical_json_bytes(
                {
                    "kind": kind,
                    "record_id": record_id,
                    "source": source,
                }
            )
        ).removeprefix("sha256:")
        return OwnerTimelineEvent(
            event_id=f"timeline_{digest[:32]}",
            kind=kind,
            occurred_at=occurred_at,
            source=source,
            summary=summary,
            thread_id=thread_id,
            message_id=message_id,
            turn_id=turn_id,
            work_id=work_id,
            status=status,
            sensitivity=sensitivity,
            references=tuple(dict.fromkeys(references)),
            metadata={} if metadata is None else metadata,
        )

    def _require_owner(self, principal: AuthenticatedOwner) -> None:
        if principal.owner_id != self._owner_id:
            raise InspectionOwnershipError(
                "authenticated principal does not own this runtime"
            )

    @staticmethod
    def _validate_window(start: datetime, end: datetime) -> None:
        if start.tzinfo is None or end.tzinfo is None:
            raise InspectionWindowError("inspection timestamps must include a timezone")
        if end <= start:
            raise InspectionWindowError("inspection window must end after it starts")
        if end - start > _MAXIMUM_WINDOW:
            raise InspectionWindowError("inspection window cannot exceed 366 days")


def _processing_summary(state: ConversationProcessingState) -> str:
    if state is ConversationProcessingState.COMPLETED:
        return "Reply processing completed."
    if state is ConversationProcessingState.DEAD:
        return "Reply processing reached terminal failure."
    if state is ConversationProcessingState.RUNNING:
        return "Reply processing is leased to a worker."
    if state is ConversationProcessingState.CANCELLED:
        return "Reply processing was cancelled."
    return "Reply processing is queued or waiting."


def _delivery_summary(state: DeliveryWorkState) -> str:
    if state is DeliveryWorkState.COMPLETED:
        return "Outbound delivery completed under exact authorization."
    if state is DeliveryWorkState.DEAD:
        return "Outbound delivery reached terminal failure."
    if state is DeliveryWorkState.RUNNING:
        return "Outbound delivery is leased to a worker."
    if state is DeliveryWorkState.CANCELLED:
        return "Outbound delivery was cancelled."
    return "Outbound delivery is queued or waiting."
