"""Thread-safe in-memory canonical conversation store for synthetic M1 runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from threading import RLock
from typing import TypeVar

from melloa.domain.base import RecordId, new_record_id
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingAttempt,
    ConversationProcessingOutcome,
    ConversationProcessingResumption,
    ConversationProcessingState,
    ConversationProcessingStatus,
    ConversationReplyWork,
    ConversationThread,
    ConversationTurn,
    processing_model_result,
)
from melloa.domain.models import ModelResult
from melloa.domain.retrieval import RetrievalManifest
from melloa.ports.conversation import (
    ClaimedConversationReplyWork,
    CompletedConversationTurn,
    ConversationConflictError,
    ConversationNotFoundError,
    InboundAppendResult,
)

_Record = TypeVar("_Record")


@dataclass(frozen=True)
class _ReplyWorkRecord:
    work: ConversationReplyWork
    state: ConversationProcessingState
    available_at: datetime
    attempt_count: int
    max_attempts: int
    updated_at: datetime
    lease_owner: RecordId | None = None
    lease_expires_at: datetime | None = None


class InMemoryConversationStore:
    def __init__(
        self,
        *,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._lock = RLock()
        self._id_factory = id_factory
        self._threads: dict[RecordId, ConversationThread] = {}
        self._messages: dict[RecordId, ConversationMessage] = {}
        self._turns: dict[RecordId, ConversationTurn] = {}
        self._model_results: dict[RecordId, ModelResult] = {}
        self._retrieval_manifests: dict[RecordId, RetrievalManifest] = {}
        self._inbound_idempotency: dict[tuple[RecordId, str], RecordId] = {}
        self._completed_by_trigger: dict[RecordId, CompletedConversationTurn] = {}
        self._reply_work: dict[RecordId, _ReplyWorkRecord] = {}
        self._work_by_message: dict[RecordId, RecordId] = {}

    def create_thread(self, thread: ConversationThread) -> None:
        with self._lock:
            existing = self._threads.get(thread.thread_id)
            if existing is None:
                self._threads[thread.thread_id] = thread
            elif existing != thread:
                raise ConversationConflictError(f"thread ID conflicts: {thread.thread_id}")

    def get_thread(self, thread_id: RecordId) -> ConversationThread:
        with self._lock:
            try:
                return self._threads[thread_id]
            except KeyError as error:
                raise ConversationNotFoundError(f"thread not found: {thread_id}") from error

    def list_threads(self, owner_id: RecordId) -> tuple[ConversationThread, ...]:
        with self._lock:
            threads = (thread for thread in self._threads.values() if thread.owner_id == owner_id)
            return tuple(sorted(threads, key=lambda thread: (thread.updated_at, thread.thread_id)))

    def get_inbound_by_idempotency_key(
        self,
        thread_id: RecordId,
        idempotency_key: str,
    ) -> ConversationMessage | None:
        with self._lock:
            message_id = self._inbound_idempotency.get((thread_id, idempotency_key))
            return None if message_id is None else self._messages[message_id]

    def append_inbound(
        self,
        message: ConversationMessage,
        idempotency_key: str,
        work: ConversationReplyWork,
        *,
        max_attempts: int,
    ) -> InboundAppendResult:
        if not 1 <= len(idempotency_key) <= 256:
            raise ValueError("idempotency key must contain between 1 and 256 characters")
        if max_attempts < 1:
            raise ValueError("max attempts must be positive")
        if (
            work.thread_id != message.thread_id
            or work.message_id != message.message_id
            or work.created_at != message.created_at
            or work.attempts
            or work.resumptions
        ):
            raise ConversationConflictError("reply work does not match the accepted message")
        with self._lock:
            self._require_thread(message.thread_id)
            key = (message.thread_id, idempotency_key)
            existing_id = self._inbound_idempotency.get(key)
            if existing_id is not None:
                return InboundAppendResult(message=self._messages[existing_id], created=False)
            existing_message = self._messages.get(message.message_id)
            if existing_message is not None and existing_message != message:
                raise ConversationConflictError(f"message ID conflicts: {message.message_id}")
            if work.work_id in self._reply_work or message.message_id in self._work_by_message:
                raise ConversationConflictError("accepted message already has reply work")
            self._messages[message.message_id] = message
            self._inbound_idempotency[key] = message.message_id
            self._reply_work[work.work_id] = _ReplyWorkRecord(
                work=work,
                state=ConversationProcessingState.READY,
                available_at=work.created_at,
                attempt_count=0,
                max_attempts=max_attempts,
                updated_at=work.created_at,
            )
            self._work_by_message[message.message_id] = work.work_id
            thread = self._threads[message.thread_id]
            if message.created_at > thread.updated_at:
                self._threads[message.thread_id] = thread.model_copy(
                    update={"updated_at": message.created_at}
                )
            return InboundAppendResult(message=message, created=True)

    def get_message(self, message_id: RecordId) -> ConversationMessage:
        with self._lock:
            try:
                return self._messages[message_id]
            except KeyError as error:
                raise ConversationNotFoundError(f"message not found: {message_id}") from error

    def claim_reply_work(
        self,
        message_id: RecordId,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedConversationReplyWork | None:
        with self._lock:
            work_id = self._work_by_message.get(message_id)
            if work_id is None:
                raise ConversationNotFoundError(
                    f"reply processing not found for message: {message_id}"
                )
            return self._claim_work(
                work_id,
                lease_owner=lease_owner,
                now=now,
                lease_expires_at=lease_expires_at,
            )

    def claim_next_reply_work(
        self,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedConversationReplyWork | None:
        with self._lock:
            ordered_ids = tuple(
                record.work.work_id
                for record in sorted(
                    self._reply_work.values(),
                    key=lambda record: (record.available_at, record.work.work_id),
                )
            )
            for work_id in ordered_ids:
                claim = self._claim_work(
                    work_id,
                    lease_owner=lease_owner,
                    now=now,
                    lease_expires_at=lease_expires_at,
                )
                if claim is not None:
                    return claim
            return None

    def record_reply_failure(
        self,
        claim: ClaimedConversationReplyWork,
        attempt: ConversationProcessingAttempt,
        retrieval_manifest: RetrievalManifest | None,
        model_result: ModelResult | None,
    ) -> ConversationProcessingStatus:
        with self._lock:
            record = self._require_claim(claim)
            self._validate_processing_attempt(claim, attempt)
            if attempt.outcome is ConversationProcessingOutcome.SUCCEEDED:
                raise ConversationConflictError("failure record cannot be successful")
            if attempt.outcome is ConversationProcessingOutcome.RETRY_SCHEDULED:
                if claim.attempt >= claim.max_attempts or attempt.retry_at is None:
                    raise ConversationConflictError("retry exceeds the leased attempt budget")
                state = ConversationProcessingState.READY
                available_at = attempt.retry_at
            else:
                state = ConversationProcessingState.DEAD
                available_at = attempt.completed_at
            self._persist_failed_model_records(attempt, retrieval_manifest, model_result)
            work = record.work.model_copy(
                update={"attempts": (*record.work.attempts, attempt)}
            )
            updated = replace(
                record,
                work=work,
                state=state,
                available_at=available_at,
                updated_at=attempt.completed_at,
                lease_owner=None,
                lease_expires_at=None,
            )
            self._reply_work[work.work_id] = updated
            return self._status(updated)

    def complete_reply_work(
        self,
        claim: ClaimedConversationReplyWork,
        completed: CompletedConversationTurn,
        attempt: ConversationProcessingAttempt,
    ) -> ConversationProcessingStatus:
        with self._lock:
            record = self._require_claim(claim)
            self._validate_processing_attempt(claim, attempt)
            if (
                attempt.outcome is not ConversationProcessingOutcome.SUCCEEDED
                or attempt.model_result_summary
                != processing_model_result(completed.model_result)
                or attempt.retrieval_manifest_id
                != completed.retrieval_manifest.manifest_id
            ):
                raise ConversationConflictError("successful work does not match its completed turn")
            self.complete_turn(completed)
            work = record.work.model_copy(
                update={"attempts": (*record.work.attempts, attempt)}
            )
            updated = replace(
                record,
                work=work,
                state=ConversationProcessingState.COMPLETED,
                available_at=attempt.completed_at,
                updated_at=attempt.completed_at,
                lease_owner=None,
                lease_expires_at=None,
            )
            self._reply_work[work.work_id] = updated
            return self._status(updated)

    def reply_processing(self, message_id: RecordId) -> ConversationProcessingStatus:
        with self._lock:
            work_id = self._work_by_message.get(message_id)
            if work_id is None:
                raise ConversationNotFoundError(
                    f"reply processing not found for message: {message_id}"
                )
            return self._status(self._reply_work[work_id])

    def list_reply_processing(
        self,
        thread_id: RecordId,
    ) -> tuple[ConversationProcessingStatus, ...]:
        with self._lock:
            self._require_thread(thread_id)
            records = tuple(
                record
                for record in self._reply_work.values()
                if record.work.thread_id == thread_id
            )
            return tuple(
                self._status(record)
                for record in sorted(
                    records,
                    key=lambda record: (record.work.created_at, record.work.work_id),
                )
            )

    def resume_reply_work(
        self,
        message_id: RecordId,
        resumption: ConversationProcessingResumption,
        *,
        available_at: datetime,
        added_attempts: int,
    ) -> ConversationProcessingStatus:
        if added_attempts < 1 or resumption.added_attempts != added_attempts:
            raise ValueError("added attempts must match the resumption record")
        with self._lock:
            work_id = self._work_by_message.get(message_id)
            if work_id is None:
                raise ConversationNotFoundError(
                    f"reply processing not found for message: {message_id}"
                )
            record = self._reply_work[work_id]
            if record.state is not ConversationProcessingState.DEAD:
                return self._status(record)
            if (
                resumption.work_id != work_id
                or resumption.message_id != message_id
                or resumption.prior_attempts != record.attempt_count
                or resumption.requested_at != available_at
            ):
                raise ConversationConflictError("resumption does not match dead reply work")
            work = record.work.model_copy(
                update={"resumptions": (*record.work.resumptions, resumption)}
            )
            updated = replace(
                record,
                work=work,
                state=ConversationProcessingState.READY,
                available_at=available_at,
                max_attempts=record.max_attempts + added_attempts,
                updated_at=available_at,
                lease_owner=None,
                lease_expires_at=None,
            )
            self._reply_work[work_id] = updated
            return self._status(updated)

    def complete_turn(self, completed: CompletedConversationTurn) -> None:
        with self._lock:
            turn = completed.turn
            output = completed.output_message
            result = completed.model_result
            manifest = completed.retrieval_manifest
            self._require_thread(turn.thread_id)
            if output.thread_id != turn.thread_id:
                raise ConversationConflictError("turn output belongs to a different thread")
            if any(message_id not in self._messages for message_id in turn.triggering_message_ids):
                raise ConversationConflictError("turn references an unknown triggering message")
            if turn.output_message_ids != (output.message_id,):
                raise ConversationConflictError(
                    "turn output reference does not match output message"
                )
            if turn.model_run_ids != (result.result_id,):
                raise ConversationConflictError("turn model reference does not match model result")
            if turn.retrieval_manifest_id != manifest.manifest_id:
                raise ConversationConflictError(
                    "turn retrieval reference does not match retrieval manifest"
                )
            if manifest.external_disclosure != result.external_disclosure:
                raise ConversationConflictError(
                    "retrieval disclosure does not match model result"
                )
            citations_by_id = {
                citation.citation_id: citation for citation in manifest.citations
            }
            if not set(output.citation_ids) <= citations_by_id.keys():
                raise ConversationConflictError(
                    "output message cites memory outside the retrieval manifest"
                )
            expected_evidence_ids = tuple(
                citations_by_id[citation_id].assertion_id
                for citation_id in output.citation_ids
            )
            if turn.evidence_ids != expected_evidence_ids:
                raise ConversationConflictError(
                    "turn evidence does not match output memory citations"
                )
            self._assert_exact_or_absent(self._messages, output.message_id, output, "message")
            self._assert_exact_or_absent(self._turns, turn.turn_id, turn, "turn")
            self._assert_exact_or_absent(
                self._model_results,
                result.result_id,
                result,
                "model result",
            )
            self._assert_exact_or_absent(
                self._retrieval_manifests,
                manifest.manifest_id,
                manifest,
                "retrieval manifest",
            )
            for trigger_id in turn.triggering_message_ids:
                existing = self._completed_by_trigger.get(trigger_id)
                if existing is not None and existing != completed:
                    raise ConversationConflictError(
                        f"trigger already completed by another turn: {trigger_id}"
                    )
            self._messages[output.message_id] = output
            self._turns[turn.turn_id] = turn
            self._model_results[result.result_id] = result
            self._retrieval_manifests[manifest.manifest_id] = manifest
            thread = self._threads[turn.thread_id]
            if output.created_at > thread.updated_at:
                self._threads[turn.thread_id] = thread.model_copy(
                    update={"updated_at": output.created_at}
                )
            for trigger_id in turn.triggering_message_ids:
                self._completed_by_trigger[trigger_id] = completed

    def completed_turn_for_trigger(
        self,
        message_id: RecordId,
    ) -> CompletedConversationTurn | None:
        with self._lock:
            return self._completed_by_trigger.get(message_id)

    def list_completed_turns(
        self,
        owner_id: RecordId,
        *,
        completed_from: datetime,
        completed_before: datetime,
    ) -> tuple[CompletedConversationTurn, ...]:
        with self._lock:
            completed_turns: list[CompletedConversationTurn] = []
            for turn in self._turns.values():
                thread = self._threads[turn.thread_id]
                if thread.owner_id != owner_id:
                    continue
                completed = self._completed_by_trigger.get(turn.triggering_message_ids[0])
                if completed is None or completed.turn != turn:
                    raise ConversationConflictError(
                        f"completed turn is missing its canonical trigger: {turn.turn_id}"
                    )
                if not (
                    completed_from
                    <= completed.model_result.completed_at
                    < completed_before
                ):
                    continue
                completed_turns.append(completed)
            return tuple(
                sorted(
                    completed_turns,
                    key=lambda completed: (
                        completed.model_result.completed_at,
                        completed.model_result.result_id,
                    ),
                )
            )

    def get_retrieval_manifest(self, manifest_id: RecordId) -> RetrievalManifest:
        with self._lock:
            try:
                return self._retrieval_manifests[manifest_id]
            except KeyError as error:
                raise ConversationNotFoundError(
                    f"retrieval manifest not found: {manifest_id}"
                ) from error

    def list_messages(self, thread_id: RecordId) -> tuple[ConversationMessage, ...]:
        with self._lock:
            self._require_thread(thread_id)
            messages = (
                message for message in self._messages.values() if message.thread_id == thread_id
            )
            return tuple(
                sorted(messages, key=lambda message: (message.created_at, message.message_id))
            )

    def list_turns(self, thread_id: RecordId) -> tuple[ConversationTurn, ...]:
        with self._lock:
            self._require_thread(thread_id)
            turns = (turn for turn in self._turns.values() if turn.thread_id == thread_id)
            return tuple(sorted(turns, key=lambda turn: (turn.started_at, turn.turn_id)))

    def _claim_work(
        self,
        work_id: RecordId,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedConversationReplyWork | None:
        if lease_expires_at <= now:
            raise ValueError("reply-work lease must expire after it starts")
        record = self._reply_work[work_id]
        if record.state is ConversationProcessingState.RUNNING:
            if record.lease_expires_at is None or record.lease_expires_at > now:
                return None
            record = self._expire_lease(record, now)
            self._reply_work[work_id] = record
        if (
            record.state is not ConversationProcessingState.READY
            or record.available_at > now
        ):
            return None
        if record.attempt_count >= record.max_attempts:
            raise ConversationConflictError("ready reply work exhausted its attempt budget")
        attempt = record.attempt_count + 1
        updated = replace(
            record,
            state=ConversationProcessingState.RUNNING,
            attempt_count=attempt,
            updated_at=now,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
        )
        self._reply_work[work_id] = updated
        return ClaimedConversationReplyWork(
            work=updated.work,
            attempt=attempt,
            max_attempts=updated.max_attempts,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
        )

    def _expire_lease(
        self,
        record: _ReplyWorkRecord,
        now: datetime,
    ) -> _ReplyWorkRecord:
        if record.lease_expires_at is None or record.attempt_count < 1:
            raise ConversationConflictError("running reply work has an invalid lease")
        terminal = record.attempt_count >= record.max_attempts
        completed_at = max(record.updated_at, record.lease_expires_at)
        retry_at = None
        outcome = ConversationProcessingOutcome.DEAD
        state = ConversationProcessingState.DEAD
        available_at = completed_at
        if not terminal:
            retry_at = now if now > completed_at else now + timedelta(microseconds=1)
            outcome = ConversationProcessingOutcome.RETRY_SCHEDULED
            state = ConversationProcessingState.READY
            available_at = retry_at
        attempt = ConversationProcessingAttempt(
            attempt_id=self._id_factory("attempt"),
            work_id=record.work.work_id,
            message_id=record.work.message_id,
            attempt=record.attempt_count,
            outcome=outcome,
            error_code="work.lease_expired",
            started_at=record.updated_at,
            completed_at=completed_at,
            retry_at=retry_at,
        )
        work = record.work.model_copy(
            update={"attempts": (*record.work.attempts, attempt)}
        )
        return replace(
            record,
            work=work,
            state=state,
            available_at=available_at,
            updated_at=completed_at,
            lease_owner=None,
            lease_expires_at=None,
        )

    def _require_claim(
        self,
        claim: ClaimedConversationReplyWork,
    ) -> _ReplyWorkRecord:
        try:
            record = self._reply_work[claim.work.work_id]
        except KeyError as error:
            raise ConversationNotFoundError(
                f"reply work not found: {claim.work.work_id}"
            ) from error
        if (
            record.state is not ConversationProcessingState.RUNNING
            or record.work != claim.work
            or record.attempt_count != claim.attempt
            or record.max_attempts != claim.max_attempts
            or record.lease_owner != claim.lease_owner
            or record.lease_expires_at != claim.lease_expires_at
        ):
            raise ConversationConflictError("reply-work lease is stale or mismatched")
        return record

    @staticmethod
    def _validate_processing_attempt(
        claim: ClaimedConversationReplyWork,
        attempt: ConversationProcessingAttempt,
    ) -> None:
        if (
            attempt.work_id != claim.work.work_id
            or attempt.message_id != claim.work.message_id
            or attempt.attempt != claim.attempt
        ):
            raise ConversationConflictError("processing attempt does not match its lease")

    def _persist_failed_model_records(
        self,
        attempt: ConversationProcessingAttempt,
        retrieval_manifest: RetrievalManifest | None,
        model_result: ModelResult | None,
    ) -> None:
        if (retrieval_manifest is None) != (attempt.retrieval_manifest_id is None):
            raise ConversationConflictError("processing manifest reference is incomplete")
        if retrieval_manifest is not None:
            if (
                retrieval_manifest.manifest_id != attempt.retrieval_manifest_id
                or (
                    retrieval_manifest.external_disclosure != attempt.external_disclosure
                    and attempt.error_code != "model.disclosure_invalid"
                )
            ):
                raise ConversationConflictError("failed processing manifest does not match")
            self._assert_exact_or_absent(
                self._retrieval_manifests,
                retrieval_manifest.manifest_id,
                retrieval_manifest,
                "retrieval manifest",
            )
        if (model_result is None) != (attempt.model_result_summary is None):
            raise ConversationConflictError("processing model result reference is incomplete")
        if model_result is not None:
            if processing_model_result(model_result) != attempt.model_result_summary:
                raise ConversationConflictError("failed processing result does not match")
            self._assert_exact_or_absent(
                self._model_results,
                model_result.result_id,
                model_result,
                "model result",
            )
        if retrieval_manifest is not None:
            self._retrieval_manifests[retrieval_manifest.manifest_id] = retrieval_manifest
        if model_result is not None:
            self._model_results[model_result.result_id] = model_result

    @staticmethod
    def _status(record: _ReplyWorkRecord) -> ConversationProcessingStatus:
        latest = record.work.attempts[-1] if record.work.attempts else None
        completed_at = (
            latest.completed_at
            if record.state is ConversationProcessingState.COMPLETED and latest is not None
            else None
        )
        last_error_code = (
            None
            if record.state is ConversationProcessingState.COMPLETED
            else next(
                (
                    attempt.error_code
                    for attempt in reversed(record.work.attempts)
                    if attempt.error_code is not None
                ),
                None,
            )
        )
        return ConversationProcessingStatus(
            work_id=record.work.work_id,
            thread_id=record.work.thread_id,
            message_id=record.work.message_id,
            state=record.state,
            attempt_count=record.attempt_count,
            max_attempts=record.max_attempts,
            available_at=record.available_at,
            lease_expires_at=record.lease_expires_at,
            last_error_code=last_error_code,
            completed_at=completed_at,
            attempts=record.work.attempts,
            resumptions=record.work.resumptions,
        )

    def _require_thread(self, thread_id: RecordId) -> None:
        if thread_id not in self._threads:
            raise ConversationNotFoundError(f"thread not found: {thread_id}")

    @staticmethod
    def _assert_exact_or_absent(
        records: dict[RecordId, _Record],
        record_id: RecordId,
        value: _Record,
        record_type: str,
    ) -> None:
        existing = records.get(record_id)
        if existing is not None and existing != value:
            raise ConversationConflictError(f"{record_type} ID conflicts: {record_id}")
