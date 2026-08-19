"""Atomic PostgreSQL persistence for canonical conversation turns."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, TypeVar, cast

import psycopg
from psycopg import sql
from psycopg.errors import CheckViolation, NoDataFound, SerializationFailure, UniqueViolation
from psycopg.types.json import Jsonb

from melloa.domain.base import (
    ContractModel,
    JsonObject,
    RecordId,
    canonical_json_bytes,
    new_record_id,
)
from melloa.domain.conversation import (
    ConversationDeletionReceipt,
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

_Contract = TypeVar("_Contract", bound=ContractModel)
_REPLY_WORK_TYPE = "conversation.owner_reply"


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


class PostgresConversationStore:
    def __init__(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._connection = connection
        self._id_factory = id_factory

    def create_thread(self, thread: ConversationThread) -> None:
        document = thread.model_dump(mode="json")
        with self._connection.transaction():
            inserted = self._connection.execute(
                """
                INSERT INTO melloa.conversation_threads (
                    thread_id, owner_id, intelligence_id, title, status, sensitivity,
                    created_at, updated_at, document
                ) VALUES (
                    %(thread_id)s, %(owner_id)s, %(intelligence_id)s, %(title)s,
                    %(status)s, %(sensitivity)s, %(created_at)s,
                    %(updated_at)s, %(document)s
                )
                ON CONFLICT (thread_id) DO NOTHING
                RETURNING thread_id
                """,
                {
                    "thread_id": thread.thread_id,
                    "owner_id": thread.owner_id,
                    "intelligence_id": thread.intelligence_id,
                    "title": thread.title,
                    "status": thread.status.value,
                    "sensitivity": thread.sensitivity.value,
                    "created_at": thread.created_at,
                    "updated_at": thread.updated_at,
                    "document": Jsonb(document),
                },
            ).fetchone()
            if inserted is None:
                self._assert_exact_document(
                    "conversation_threads",
                    "thread_id",
                    thread.thread_id,
                    document,
                    "thread",
                )

    def get_thread(self, thread_id: RecordId) -> ConversationThread:
        return self._read_contract(
            ConversationThread,
            "conversation_threads",
            "thread_id",
            thread_id,
            "thread",
        )

    def list_threads(self, owner_id: RecordId) -> tuple[ConversationThread, ...]:
        rows = self._connection.execute(
            """
            SELECT document
              FROM melloa.conversation_threads
             WHERE owner_id = %s
             ORDER BY updated_at, thread_id
            """,
            (owner_id,),
        ).fetchall()
        return tuple(self._parse_contract(ConversationThread, row[0]) for row in rows)

    def delete_thread(
        self,
        deletion: ConversationDeletionReceipt,
    ) -> ConversationDeletionReceipt:
        try:
            with self._connection.transaction():
                row = self._connection.execute(
                    """
                    SELECT deletion_document
                      FROM melloa.delete_conversation(
                        %(deletion_id)s,
                        %(thread_id)s,
                        %(owner_id)s,
                        %(deleted_at)s
                      )
                    """,
                    {
                        "deletion_id": deletion.deletion_id,
                        "thread_id": deletion.thread_id,
                        "owner_id": deletion.owner_id,
                        "deleted_at": deletion.deleted_at,
                    },
                ).fetchone()
                if row is None:
                    raise ConversationConflictError(
                        "conversation deletion returned no result"
                    )
                persisted = self._parse_contract(
                    ConversationDeletionReceipt,
                    row[0],
                )
                if persisted != deletion:
                    raise ConversationConflictError(
                        "persisted conversation deletion does not match its request"
                    )
                return persisted
        except NoDataFound as error:
            raise ConversationNotFoundError(
                f"thread not found: {deletion.thread_id}"
            ) from error
        except (CheckViolation, SerializationFailure, UniqueViolation) as error:
            raise ConversationConflictError(
                "conversation deletion conflicts with durable state"
            ) from error

    def get_inbound_by_idempotency_key(
        self,
        thread_id: RecordId,
        idempotency_key: str,
    ) -> ConversationMessage | None:
        row = self._connection.execute(
            """
            SELECT message.document
              FROM melloa.conversation_inbound_idempotency AS accepted
              JOIN melloa.conversation_messages AS message
                ON message.message_id = accepted.message_id
             WHERE accepted.thread_id = %s
               AND accepted.idempotency_key = %s
            """,
            (thread_id, idempotency_key),
        ).fetchone()
        return None if row is None else self._parse_contract(ConversationMessage, row[0])

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
        with self._connection.transaction():
            thread = self._thread_for_update(message.thread_id)
            existing = self.get_inbound_by_idempotency_key(
                message.thread_id,
                idempotency_key,
            )
            if existing is not None:
                return InboundAppendResult(message=existing, created=False)
            self._persist_message(message)
            try:
                self._connection.execute(
                    """
                    INSERT INTO melloa.conversation_inbound_idempotency (
                        thread_id, idempotency_key, message_id
                    ) VALUES (%s, %s, %s)
                    """,
                    (message.thread_id, idempotency_key, message.message_id),
                )
            except UniqueViolation as error:
                raise ConversationConflictError(
                    "inbound message conflicts with an existing idempotency binding"
                ) from error
            try:
                self._connection.execute(
                    """
                    INSERT INTO melloa.jobs_outbox (
                        work_id, work_kind, work_type, schema_version, payload, state,
                        available_at, attempts, max_attempts, idempotency_key,
                        created_at, updated_at
                    ) VALUES (%s, 'job', %s, %s, %s, 'ready', %s, 0, %s, %s, %s, %s)
                    """,
                    (
                        work.work_id,
                        _REPLY_WORK_TYPE,
                        work.contract_version,
                        Jsonb(work.model_dump(mode="json")),
                        work.created_at,
                        max_attempts,
                        self._reply_work_key(message.message_id),
                        work.created_at,
                        work.created_at,
                    ),
                )
            except UniqueViolation as error:
                raise ConversationConflictError(
                    "accepted message conflicts with existing reply work"
                ) from error
            self._update_thread(thread, message.created_at)
            return InboundAppendResult(message=message, created=True)

    def get_message(self, message_id: RecordId) -> ConversationMessage:
        return self._read_contract(
            ConversationMessage,
            "conversation_messages",
            "message_id",
            message_id,
            "message",
        )

    def claim_reply_work(
        self,
        message_id: RecordId,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedConversationReplyWork | None:
        return self._claim_reply_work(
            message_id=message_id,
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
        return self._claim_reply_work(
            message_id=None,
            lease_owner=lease_owner,
            now=now,
            lease_expires_at=lease_expires_at,
        )

    def record_reply_failure(
        self,
        claim: ClaimedConversationReplyWork,
        attempt: ConversationProcessingAttempt,
        retrieval_manifest: RetrievalManifest | None,
        model_result: ModelResult | None,
    ) -> ConversationProcessingStatus:
        self._validate_processing_attempt(claim, attempt)
        if attempt.outcome is ConversationProcessingOutcome.SUCCEEDED:
            raise ConversationConflictError("failure record cannot be successful")
        with self._connection.transaction():
            record = self._locked_reply_work(claim.work.work_id)
            self._require_claim(record, claim)
            if attempt.outcome is ConversationProcessingOutcome.RETRY_SCHEDULED:
                if claim.attempt >= claim.max_attempts or attempt.retry_at is None:
                    raise ConversationConflictError("retry exceeds the leased attempt budget")
                state = ConversationProcessingState.READY
                available_at = attempt.retry_at
            else:
                state = ConversationProcessingState.DEAD
                available_at = attempt.completed_at
            self._persist_failed_processing(attempt, retrieval_manifest, model_result)
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
            self._write_reply_work(updated)
            return self._status(updated)

    def complete_reply_work(
        self,
        claim: ClaimedConversationReplyWork,
        completed: CompletedConversationTurn,
        attempt: ConversationProcessingAttempt,
    ) -> ConversationProcessingStatus:
        self._validate_processing_attempt(claim, attempt)
        if (
            attempt.outcome is not ConversationProcessingOutcome.SUCCEEDED
            or attempt.model_result_summary != processing_model_result(completed.model_result)
            or attempt.retrieval_manifest_id != completed.retrieval_manifest.manifest_id
        ):
            raise ConversationConflictError("successful work does not match its completed turn")
        with self._connection.transaction():
            record = self._locked_reply_work(claim.work.work_id)
            self._require_claim(record, claim)
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
            self._write_reply_work(updated)
            return self._status(updated)

    def reply_processing(self, message_id: RecordId) -> ConversationProcessingStatus:
        row = self._connection.execute(
            """
            SELECT payload, state, available_at, attempts, max_attempts,
                   updated_at, lease_owner, lease_expires_at
              FROM melloa.jobs_outbox
             WHERE work_type = %s AND idempotency_key = %s
            """,
            (_REPLY_WORK_TYPE, self._reply_work_key(message_id)),
        ).fetchone()
        if row is None:
            raise ConversationNotFoundError(
                f"reply processing not found for message: {message_id}"
            )
        return self._status(self._parse_reply_work_row(row))

    def list_reply_processing(
        self,
        thread_id: RecordId,
    ) -> tuple[ConversationProcessingStatus, ...]:
        self.get_thread(thread_id)
        rows = self._connection.execute(
            """
            SELECT payload, state, available_at, attempts, max_attempts,
                   updated_at, lease_owner, lease_expires_at
              FROM melloa.jobs_outbox
             WHERE work_type = %s AND payload ->> 'thread_id' = %s
             ORDER BY created_at, work_id
            """,
            (_REPLY_WORK_TYPE, thread_id),
        ).fetchall()
        return tuple(self._status(self._parse_reply_work_row(row)) for row in rows)

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
        with self._connection.transaction():
            record = self._locked_reply_work_by_message(message_id)
            if record.state is not ConversationProcessingState.DEAD:
                return self._status(record)
            if (
                resumption.work_id != record.work.work_id
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
            self._write_reply_work(updated)
            return self._status(updated)

    def complete_turn(self, completed: CompletedConversationTurn) -> None:
        self._validate_completed(completed)
        turn = completed.turn
        output = completed.output_message
        result = completed.model_result
        manifest = completed.retrieval_manifest
        with self._connection.transaction():
            thread = self._thread_for_update(turn.thread_id)
            for trigger_id in turn.triggering_message_ids:
                trigger = self._read_contract(
                    ConversationMessage,
                    "conversation_messages",
                    "message_id",
                    trigger_id,
                    "triggering message",
                )
                if trigger.thread_id != turn.thread_id:
                    raise ConversationConflictError(
                        "turn references a triggering message from another thread"
                    )
            self._persist_manifest(manifest)
            self._persist_model_result(result)
            self._persist_message(output)
            self._persist_turn(turn)
            for trigger_id in turn.triggering_message_ids:
                self._persist_turn_trigger(turn.thread_id, trigger_id, turn.turn_id)
            if result.external_disclosure:
                self._persist_disclosure(completed)
            self._update_thread(thread, output.created_at)

    def completed_turn_for_trigger(
        self,
        message_id: RecordId,
    ) -> CompletedConversationTurn | None:
        row = self._connection.execute(
            """
            SELECT turn.document
              FROM melloa.conversation_turn_triggers AS trigger
              JOIN melloa.conversation_turns AS turn ON turn.turn_id = trigger.turn_id
             WHERE trigger.message_id = %s
            """,
            (message_id,),
        ).fetchone()
        if row is None:
            return None
        turn = self._parse_contract(ConversationTurn, row[0])
        if (
            len(turn.output_message_ids) != 1
            or len(turn.model_run_ids) != 1
            or turn.retrieval_manifest_id is None
        ):
            raise ConversationConflictError(
                "persisted completed turn does not match the single-reply contract"
            )
        return CompletedConversationTurn(
            turn=turn,
            output_message=self._read_contract(
                ConversationMessage,
                "conversation_messages",
                "message_id",
                turn.output_message_ids[0],
                "output message",
            ),
            model_result=self._read_contract(
                ModelResult,
                "model_runs",
                "result_id",
                turn.model_run_ids[0],
                "model result",
            ),
            retrieval_manifest=self.get_retrieval_manifest(turn.retrieval_manifest_id),
        )

    def list_completed_turns(
        self,
        owner_id: RecordId,
        *,
        completed_from: datetime,
        completed_before: datetime,
    ) -> tuple[CompletedConversationTurn, ...]:
        rows = self._connection.execute(
            """
            SELECT turn.document
              FROM melloa.conversation_turns AS turn
              JOIN melloa.conversation_threads AS thread
                ON thread.thread_id = turn.thread_id
              JOIN melloa.model_runs AS model
                ON model.result_id = turn.document->'model_run_ids'->>0
             WHERE thread.owner_id = %s
               AND model.completed_at >= %s
               AND model.completed_at < %s
             ORDER BY model.completed_at, model.result_id
            """,
            (owner_id, completed_from, completed_before),
        ).fetchall()
        completed_turns: list[CompletedConversationTurn] = []
        for row in rows:
            turn = self._parse_contract(ConversationTurn, row[0])
            completed = self.completed_turn_for_trigger(turn.triggering_message_ids[0])
            if completed is None or completed.turn != turn:
                raise ConversationConflictError(
                    f"completed turn is missing its canonical trigger: {turn.turn_id}"
                )
            completed_turns.append(completed)
        return tuple(completed_turns)

    def get_retrieval_manifest(self, manifest_id: RecordId) -> RetrievalManifest:
        return self._read_contract(
            RetrievalManifest,
            "retrieval_manifests",
            "manifest_id",
            manifest_id,
            "retrieval manifest",
        )

    def list_messages(self, thread_id: RecordId) -> tuple[ConversationMessage, ...]:
        self.get_thread(thread_id)
        rows = self._connection.execute(
            """
            SELECT document
              FROM melloa.conversation_messages
             WHERE thread_id = %s
             ORDER BY created_at, message_id
            """,
            (thread_id,),
        ).fetchall()
        return tuple(self._parse_contract(ConversationMessage, row[0]) for row in rows)

    def list_turns(self, thread_id: RecordId) -> tuple[ConversationTurn, ...]:
        self.get_thread(thread_id)
        rows = self._connection.execute(
            """
            SELECT document
              FROM melloa.conversation_turns
             WHERE thread_id = %s
             ORDER BY started_at, turn_id
            """,
            (thread_id,),
        ).fetchall()
        return tuple(self._parse_contract(ConversationTurn, row[0]) for row in rows)

    def _thread_for_update(self, thread_id: RecordId) -> ConversationThread:
        row = self._connection.execute(
            """
            SELECT document
              FROM melloa.conversation_threads
             WHERE thread_id = %s
             FOR UPDATE
            """,
            (thread_id,),
        ).fetchone()
        if row is None:
            raise ConversationNotFoundError(f"thread not found: {thread_id}")
        return self._parse_contract(ConversationThread, row[0])

    def _update_thread(self, thread: ConversationThread, updated_at: datetime) -> None:
        if updated_at <= thread.updated_at:
            return
        updated = thread.model_copy(update={"updated_at": updated_at})
        self._connection.execute(
            """
            UPDATE melloa.conversation_threads
               SET updated_at = %s,
                   document = %s
             WHERE thread_id = %s
            """,
            (
                updated.updated_at,
                Jsonb(updated.model_dump(mode="json")),
                updated.thread_id,
            ),
        )

    def _persist_message(self, message: ConversationMessage) -> None:
        document = message.model_dump(mode="json")
        inserted = self._connection.execute(
            """
            INSERT INTO melloa.conversation_messages (
                message_id, thread_id, author_principal_id, source_client,
                sensitivity, created_at, observed_at, document
            ) VALUES (
                %(message_id)s, %(thread_id)s, %(author_principal_id)s,
                %(source_client)s, %(sensitivity)s, %(created_at)s,
                %(observed_at)s, %(document)s
            )
            ON CONFLICT (message_id) DO NOTHING
            RETURNING message_id
            """,
            {
                "message_id": message.message_id,
                "thread_id": message.thread_id,
                "author_principal_id": message.author_principal_id,
                "source_client": message.source_client,
                "sensitivity": message.sensitivity.value,
                "created_at": message.created_at,
                "observed_at": message.observed_at,
                "document": Jsonb(document),
            },
        ).fetchone()
        if inserted is None:
            self._assert_exact_document(
                "conversation_messages",
                "message_id",
                message.message_id,
                document,
                "message",
            )

    def _persist_turn(self, turn: ConversationTurn) -> None:
        document = turn.model_dump(mode="json")
        inserted = self._connection.execute(
            """
            INSERT INTO melloa.conversation_turns (
                turn_id, thread_id, retrieval_manifest_id,
                started_at, completed_at, document
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (turn_id) DO NOTHING
            RETURNING turn_id
            """,
            (
                turn.turn_id,
                turn.thread_id,
                turn.retrieval_manifest_id,
                turn.started_at,
                turn.completed_at,
                Jsonb(document),
            ),
        ).fetchone()
        if inserted is None:
            self._assert_exact_document(
                "conversation_turns",
                "turn_id",
                turn.turn_id,
                document,
                "turn",
            )

    def _persist_model_result(self, result: ModelResult) -> None:
        document = result.model_dump(mode="json")
        inserted = self._connection.execute(
            """
            INSERT INTO melloa.model_runs (
                result_id, request_id, provider_id, model_id,
                input_tokens, output_tokens, cost_gbp, external_disclosure,
                started_at, completed_at, document
            ) VALUES (
                %(result_id)s, %(request_id)s, %(provider_id)s,
                %(model_id)s, %(input_tokens)s, %(output_tokens)s, %(cost_gbp)s,
                %(external_disclosure)s, %(started_at)s, %(completed_at)s,
                %(document)s
            )
            ON CONFLICT (result_id) DO NOTHING
            RETURNING result_id
            """,
            {
                "result_id": result.result_id,
                "request_id": result.request_id,
                "provider_id": result.provider_id,
                "model_id": result.model_id,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_gbp": result.cost_gbp,
                "external_disclosure": result.external_disclosure,
                "started_at": result.started_at,
                "completed_at": result.completed_at,
                "document": Jsonb(document),
            },
        ).fetchone()
        if inserted is None:
            self._assert_exact_document(
                "model_runs",
                "result_id",
                result.result_id,
                document,
                "model result",
            )

    def _persist_manifest(self, manifest: RetrievalManifest) -> None:
        document = manifest.model_dump(mode="json")
        document["allowed_sensitivities"] = sorted(
            sensitivity.value for sensitivity in manifest.allowed_sensitivities
        )
        inserted = self._connection.execute(
            """
            INSERT INTO melloa.retrieval_manifests (
                manifest_id, requester_id, subject_id, purpose, query_hash,
                external_disclosure, created_at, document
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (manifest_id) DO NOTHING
            RETURNING manifest_id
            """,
            (
                manifest.manifest_id,
                manifest.requester_id,
                manifest.subject_id,
                manifest.purpose,
                manifest.query_hash,
                manifest.external_disclosure,
                manifest.created_at,
                Jsonb(document),
            ),
        ).fetchone()
        if inserted is None:
            self._assert_exact_document(
                "retrieval_manifests",
                "manifest_id",
                manifest.manifest_id,
                document,
                "retrieval manifest",
            )

    def _persist_turn_trigger(
        self,
        thread_id: RecordId,
        message_id: RecordId,
        turn_id: RecordId,
    ) -> None:
        inserted = self._connection.execute(
            """
            INSERT INTO melloa.conversation_turn_triggers (
                message_id, thread_id, turn_id
            ) VALUES (%s, %s, %s)
            ON CONFLICT (message_id) DO NOTHING
            RETURNING message_id
            """,
            (message_id, thread_id, turn_id),
        ).fetchone()
        if inserted is not None:
            return
        existing = self._connection.execute(
            """
            SELECT thread_id, turn_id
              FROM melloa.conversation_turn_triggers
             WHERE message_id = %s
            """,
            (message_id,),
        ).fetchone()
        if existing != (thread_id, turn_id):
            raise ConversationConflictError(
                f"trigger already completed by another turn: {message_id}"
            )

    def _persist_disclosure(self, completed: CompletedConversationTurn) -> None:
        result = completed.model_result
        manifest = completed.retrieval_manifest
        disclosed_citation_ids = tuple(
            citation.citation_id for citation in manifest.citations
        )
        disclosed_evidence_ids = tuple(
            citation.assertion_id for citation in manifest.citations
        )
        document: JsonObject = {
            "model_result_id": result.result_id,
            "retrieval_manifest_id": manifest.manifest_id,
            "purpose": manifest.purpose,
            "triggering_message_ids": list(completed.turn.triggering_message_ids),
            "disclosed_citation_ids": list(disclosed_citation_ids),
            "disclosed_evidence_ids": list(disclosed_evidence_ids),
            "output_citation_ids": list(completed.output_message.citation_ids),
            "output_evidence_ids": list(completed.turn.evidence_ids),
            "model": {
                "provider_id": result.provider_id,
                "model_id": result.model_id,
                "processing_location": result.processing_location.value,
            },
        }
        inserted = self._connection.execute(
            """
            INSERT INTO melloa.model_disclosures (
                result_id, retrieval_manifest_id, purpose,
                evidence_ids, disclosed_at, document
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (result_id) DO NOTHING
            RETURNING result_id
            """,
            (
                result.result_id,
                manifest.manifest_id,
                manifest.purpose,
                list(disclosed_evidence_ids),
                result.completed_at,
                Jsonb(document),
            ),
        ).fetchone()
        if inserted is None:
            self._assert_exact_document(
                "model_disclosures",
                "result_id",
                result.result_id,
                document,
                "model disclosure",
            )

    def _persist_failed_disclosure(
        self,
        result: ModelResult,
        manifest: RetrievalManifest,
        message_id: RecordId,
    ) -> None:
        disclosed_evidence_ids = tuple(
            citation.assertion_id for citation in manifest.citations
        )
        document: JsonObject = {
            "model_result_id": result.result_id,
            "retrieval_manifest_id": manifest.manifest_id,
            "purpose": manifest.purpose,
            "triggering_message_ids": [message_id],
            "disclosed_citation_ids": [
                citation.citation_id for citation in manifest.citations
            ],
            "disclosed_evidence_ids": list(disclosed_evidence_ids),
            "output_citation_ids": [],
            "output_evidence_ids": [],
            "processing_outcome": "rejected_before_turn_completion",
            "model": {
                "provider_id": result.provider_id,
                "model_id": result.model_id,
                "processing_location": result.processing_location.value,
            },
        }
        inserted = self._connection.execute(
            """
            INSERT INTO melloa.model_disclosures (
                result_id, retrieval_manifest_id, purpose,
                evidence_ids, disclosed_at, document
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (result_id) DO NOTHING
            RETURNING result_id
            """,
            (
                result.result_id,
                manifest.manifest_id,
                manifest.purpose,
                list(disclosed_evidence_ids),
                result.completed_at,
                Jsonb(document),
            ),
        ).fetchone()
        if inserted is None:
            self._assert_exact_document(
                "model_disclosures",
                "result_id",
                result.result_id,
                document,
                "model disclosure",
            )

    def _claim_reply_work(
        self,
        *,
        message_id: RecordId | None,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedConversationReplyWork | None:
        if lease_expires_at <= now:
            raise ValueError("reply-work lease must expire after it starts")
        parameters: list[Any] = [_REPLY_WORK_TYPE, now, now]
        query = """
                SELECT payload, state, available_at, attempts, max_attempts,
                       updated_at, lease_owner, lease_expires_at
                  FROM melloa.jobs_outbox
                 WHERE work_type = %s
                   AND (
                        (state = 'ready' AND available_at <= %s)
                        OR (state = 'running' AND lease_expires_at <= %s)
                   )
                 ORDER BY available_at, work_id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            """
        if message_id is not None:
            query = """
                SELECT payload, state, available_at, attempts, max_attempts,
                       updated_at, lease_owner, lease_expires_at
                  FROM melloa.jobs_outbox
                 WHERE work_type = %s
                   AND (
                        (state = 'ready' AND available_at <= %s)
                        OR (state = 'running' AND lease_expires_at <= %s)
                   )
                   AND idempotency_key = %s
                 ORDER BY available_at, work_id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            """
            parameters.append(self._reply_work_key(message_id))
        with self._connection.transaction():
            row = self._connection.execute(query, parameters).fetchone()
            if row is None:
                return None
            record = self._parse_reply_work_row(row)
            if record.state is ConversationProcessingState.RUNNING:
                record = self._expire_lease(record, now)
                self._write_reply_work(record)
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
            self._write_reply_work(updated)
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

    def _locked_reply_work(self, work_id: RecordId) -> _ReplyWorkRecord:
        row = self._connection.execute(
            """
            SELECT payload, state, available_at, attempts, max_attempts,
                   updated_at, lease_owner, lease_expires_at
              FROM melloa.jobs_outbox
             WHERE work_type = %s AND work_id = %s
             FOR UPDATE
            """,
            (_REPLY_WORK_TYPE, work_id),
        ).fetchone()
        if row is None:
            raise ConversationNotFoundError(f"reply work not found: {work_id}")
        return self._parse_reply_work_row(row)

    def _locked_reply_work_by_message(self, message_id: RecordId) -> _ReplyWorkRecord:
        row = self._connection.execute(
            """
            SELECT payload, state, available_at, attempts, max_attempts,
                   updated_at, lease_owner, lease_expires_at
              FROM melloa.jobs_outbox
             WHERE work_type = %s AND idempotency_key = %s
             FOR UPDATE
            """,
            (_REPLY_WORK_TYPE, self._reply_work_key(message_id)),
        ).fetchone()
        if row is None:
            raise ConversationNotFoundError(
                f"reply processing not found for message: {message_id}"
            )
        return self._parse_reply_work_row(row)

    @staticmethod
    def _require_claim(
        record: _ReplyWorkRecord,
        claim: ClaimedConversationReplyWork,
    ) -> None:
        if (
            record.state is not ConversationProcessingState.RUNNING
            or record.work != claim.work
            or record.attempt_count != claim.attempt
            or record.max_attempts != claim.max_attempts
            or record.lease_owner != claim.lease_owner
            or record.lease_expires_at != claim.lease_expires_at
        ):
            raise ConversationConflictError("reply-work lease is stale or mismatched")

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

    def _persist_failed_processing(
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
            self._persist_manifest(retrieval_manifest)
        if (model_result is None) != (attempt.model_result_summary is None):
            raise ConversationConflictError("processing model result reference is incomplete")
        if model_result is not None:
            if processing_model_result(model_result) != attempt.model_result_summary:
                raise ConversationConflictError("failed processing result does not match")
            self._persist_model_result(model_result)
            if model_result.external_disclosure and retrieval_manifest is not None:
                self._persist_failed_disclosure(
                    model_result,
                    retrieval_manifest,
                    attempt.message_id,
                )

    def _write_reply_work(self, record: _ReplyWorkRecord) -> None:
        updated = self._connection.execute(
            """
            UPDATE melloa.jobs_outbox
               SET payload = %s,
                   state = %s,
                   available_at = %s,
                   attempts = %s,
                   max_attempts = %s,
                   updated_at = %s,
                   lease_owner = %s,
                   lease_expires_at = %s
             WHERE work_id = %s AND work_type = %s
            """,
            (
                Jsonb(record.work.model_dump(mode="json")),
                record.state.value,
                record.available_at,
                record.attempt_count,
                record.max_attempts,
                record.updated_at,
                record.lease_owner,
                record.lease_expires_at,
                record.work.work_id,
                _REPLY_WORK_TYPE,
            ),
        )
        if updated.rowcount != 1:
            raise ConversationConflictError(
                f"reply work disappeared during update: {record.work.work_id}"
            )

    def _parse_reply_work_row(self, row: tuple[Any, ...]) -> _ReplyWorkRecord:
        work = self._parse_contract(ConversationReplyWork, row[0])
        try:
            state = ConversationProcessingState(str(row[1]))
        except ValueError as error:
            raise ConversationConflictError("reply work has an invalid state") from error
        lease_owner = None if row[6] is None else cast(RecordId, row[6])
        return _ReplyWorkRecord(
            work=work,
            state=state,
            available_at=cast(datetime, row[2]),
            attempt_count=int(row[3]),
            max_attempts=int(row[4]),
            updated_at=cast(datetime, row[5]),
            lease_owner=lease_owner,
            lease_expires_at=(None if row[7] is None else cast(datetime, row[7])),
        )

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

    @staticmethod
    def _reply_work_key(message_id: RecordId) -> str:
        return f"conversation.owner-reply:{message_id}"

    def _assert_exact_document(
        self,
        table: str,
        id_column: str,
        record_id: RecordId,
        expected: JsonObject,
        record_type: str,
    ) -> None:
        query = sql.SQL("SELECT document FROM melloa.{} WHERE {} = %s").format(
            sql.Identifier(table),
            sql.Identifier(id_column),
        )
        row = self._connection.execute(query, (record_id,)).fetchone()
        if row is None or row[0] != expected:
            raise ConversationConflictError(
                f"{record_type} ID conflicts with immutable data: {record_id}"
            )

    def _read_contract(
        self,
        contract_type: type[_Contract],
        table: str,
        id_column: str,
        record_id: RecordId,
        record_type: str,
    ) -> _Contract:
        query = sql.SQL("SELECT document FROM melloa.{} WHERE {} = %s").format(
            sql.Identifier(table),
            sql.Identifier(id_column),
        )
        row = self._connection.execute(query, (record_id,)).fetchone()
        if row is None:
            raise ConversationNotFoundError(f"{record_type} not found: {record_id}")
        return self._parse_contract(contract_type, row[0])

    @staticmethod
    def _parse_contract(
        contract_type: type[_Contract],
        document: Any,
    ) -> _Contract:
        if not isinstance(document, dict):
            raise ConversationConflictError("persisted contract document is not an object")
        return contract_type.model_validate_json(
            canonical_json_bytes(cast(JsonObject, document))
        )

    @staticmethod
    def _validate_completed(completed: CompletedConversationTurn) -> None:
        turn = completed.turn
        output = completed.output_message
        result = completed.model_result
        manifest = completed.retrieval_manifest
        if output.thread_id != turn.thread_id:
            raise ConversationConflictError("turn output belongs to a different thread")
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
