"""Authenticated owner inspection of redacted model cost and disclosure activity."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta

from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId, utc_now
from melloa.domain.inspection import (
    DisclosedMemoryReference,
    ModelActivityEntry,
    ModelDisclosureInspection,
    OwnerModelActivityReport,
)
from melloa.ports.conversation import CompletedConversationTurn, ConversationStore

_DEFAULT_WINDOW = timedelta(days=7)
_MAXIMUM_WINDOW = timedelta(days=366)


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
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._owner_id = owner_id
        self._conversation_store = conversation_store
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
