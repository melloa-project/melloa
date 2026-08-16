"""Atomic PostgreSQL persistence for exact outbound delivery work."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, cast

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from melloa.domain.base import RecordId, canonical_json_bytes, new_record_id
from melloa.domain.conversation import DeliveryAttempt
from melloa.domain.delivery import (
    DeliveryExecutionReceipt,
    DeliveryWorkAttempt,
    DeliveryWorkOutcome,
    DeliveryWorkResumption,
    DeliveryWorkState,
    DeliveryWorkStatus,
    OutboundDeliveryWork,
)
from melloa.domain.policy import PolicyDecision
from melloa.ports.delivery import (
    ClaimedDeliveryWork,
    DeliveryConflictError,
    DeliveryNotFoundError,
    EnqueuedDeliveryWork,
)

_DELIVERY_WORK_TYPE = "conversation.outbound_delivery"


@dataclass(frozen=True)
class _DeliveryRecord:
    work: OutboundDeliveryWork
    state: DeliveryWorkState
    available_at: datetime
    attempt_count: int
    max_attempts: int
    updated_at: datetime
    lease_owner: RecordId | None = None
    lease_expires_at: datetime | None = None


class PostgresDeliveryStore:
    def __init__(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._connection = connection
        self._id_factory = id_factory

    def enqueue(
        self,
        work: OutboundDeliveryWork,
        *,
        max_attempts: int,
    ) -> EnqueuedDeliveryWork:
        if max_attempts < 1:
            raise ValueError("max delivery attempts must be positive")
        if work.attempts or work.resumptions:
            raise DeliveryConflictError("new delivery work cannot contain history")
        with self._connection.transaction():
            existing = self._connection.execute(
                """
                SELECT work_type, payload, state, available_at, attempts, max_attempts,
                       updated_at, lease_owner, lease_expires_at
                  FROM melloa.jobs_outbox
                 WHERE idempotency_key = %s
                 FOR UPDATE
                """,
                (work.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != _DELIVERY_WORK_TYPE:
                    raise DeliveryConflictError(
                        "delivery idempotency key conflicts with another work type"
                    )
                record = self._parse_record(existing[1:])
                self._verify_history(record.work)
                self._require_same_submission(record.work, work)
                return EnqueuedDeliveryWork(
                    work=record.work,
                    status=self._status(record),
                    created=False,
                )
            collision = self._connection.execute(
                "SELECT work_type FROM melloa.jobs_outbox WHERE work_id = %s FOR UPDATE",
                (work.work_id,),
            ).fetchone()
            if collision is not None:
                raise DeliveryConflictError(f"delivery work ID conflicts: {work.work_id}")
            self._persist_policy_decision(work.policy_decision)
            try:
                self._connection.execute(
                    """
                    INSERT INTO melloa.jobs_outbox (
                        work_id, work_kind, work_type, schema_version, payload, state,
                        available_at, attempts, max_attempts, idempotency_key,
                        created_at, updated_at
                    ) VALUES (%s, 'outbox', %s, %s, %s, 'ready', %s, 0, %s, %s, %s, %s)
                    """,
                    (
                        work.work_id,
                        _DELIVERY_WORK_TYPE,
                        work.contract_version,
                        Jsonb(work.model_dump(mode="json")),
                        work.created_at,
                        max_attempts,
                        work.idempotency_key,
                        work.created_at,
                        work.created_at,
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO melloa.outbound_deliveries (
                        work_id, thread_id, message_id, requested_by, client_adapter,
                        destination_ref, action_hash, initial_policy_decision_id,
                        created_at, document
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        work.work_id,
                        work.thread_id,
                        work.message_id,
                        work.requested_by,
                        work.client_adapter,
                        work.destination_ref,
                        work.authorization_request.action_hash,
                        work.policy_decision.decision_id,
                        work.created_at,
                        Jsonb(work.model_dump(mode="json")),
                    ),
                )
            except UniqueViolation as error:
                raise DeliveryConflictError("delivery work identity conflicts") from error
            record = _DeliveryRecord(
                work=work,
                state=DeliveryWorkState.READY,
                available_at=work.created_at,
                attempt_count=0,
                max_attempts=max_attempts,
                updated_at=work.created_at,
            )
            return EnqueuedDeliveryWork(
                work=work,
                status=self._status(record),
                created=True,
            )

    def get_work(self, work_id: RecordId) -> OutboundDeliveryWork:
        return self._read_record(work_id).work

    def claim_work(
        self,
        work_id: RecordId,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedDeliveryWork | None:
        return self._claim(
            work_id=work_id,
            lease_owner=lease_owner,
            now=now,
            lease_expires_at=lease_expires_at,
        )

    def claim_next_work(
        self,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedDeliveryWork | None:
        return self._claim(
            work_id=None,
            lease_owner=lease_owner,
            now=now,
            lease_expires_at=lease_expires_at,
        )

    def record_failure(
        self,
        claim: ClaimedDeliveryWork,
        attempt: DeliveryWorkAttempt,
    ) -> DeliveryWorkStatus:
        with self._connection.transaction():
            record = self._locked_record(claim.work.work_id)
            if attempt in record.work.attempts:
                return self._status(record)
            self._require_claim(record, claim)
            self._validate_attempt(record, attempt)
            terminal = attempt.outcome is DeliveryWorkOutcome.DEAD
            if attempt.outcome is DeliveryWorkOutcome.SUCCEEDED or (
                attempt.outcome is DeliveryWorkOutcome.RETRY_SCHEDULED
                and claim.attempt >= claim.max_attempts
            ):
                raise DeliveryConflictError(
                    "delivery failure outcome conflicts with attempt budget"
                )
            available_at = attempt.completed_at
            if not terminal:
                if attempt.retry_at is None:
                    raise DeliveryConflictError("retryable delivery has no retry time")
                available_at = attempt.retry_at
            self._persist_work_attempt(attempt)
            work = record.work.model_copy(update={"attempts": (*record.work.attempts, attempt)})
            updated = replace(
                record,
                work=work,
                state=(DeliveryWorkState.DEAD if terminal else DeliveryWorkState.READY),
                available_at=available_at,
                updated_at=attempt.completed_at,
                lease_owner=None,
                lease_expires_at=None,
            )
            self._write_record(updated)
            return self._status(updated)

    def complete(
        self,
        claim: ClaimedDeliveryWork,
        attempt: DeliveryWorkAttempt,
    ) -> DeliveryWorkStatus:
        with self._connection.transaction():
            record = self._locked_record(claim.work.work_id)
            if attempt in record.work.attempts:
                return self._status(record)
            self._require_claim(record, claim)
            self._validate_attempt(record, attempt)
            if (
                attempt.outcome is not DeliveryWorkOutcome.SUCCEEDED
                or attempt.adapter_receipt is None
                or attempt.execution_receipt is None
            ):
                raise DeliveryConflictError("completed delivery requires a successful attempt")
            self._persist_adapter_receipt(record.work.work_id, attempt.adapter_receipt)
            self._persist_execution_receipt(
                record.work.work_id,
                attempt.execution_receipt,
            )
            self._persist_work_attempt(attempt)
            work = record.work.model_copy(update={"attempts": (*record.work.attempts, attempt)})
            updated = replace(
                record,
                work=work,
                state=DeliveryWorkState.COMPLETED,
                available_at=attempt.completed_at,
                updated_at=attempt.completed_at,
                lease_owner=None,
                lease_expires_at=None,
            )
            self._write_record(updated)
            return self._status(updated)

    def status(self, work_id: RecordId) -> DeliveryWorkStatus:
        return self._status(self._read_record(work_id))

    def list_status(self, thread_id: RecordId) -> tuple[DeliveryWorkStatus, ...]:
        rows = self._connection.execute(
            """
            SELECT queued.payload, queued.state, queued.available_at, queued.attempts,
                   queued.max_attempts, queued.updated_at, queued.lease_owner,
                   queued.lease_expires_at
              FROM melloa.jobs_outbox AS queued
              JOIN melloa.outbound_deliveries AS delivery
                ON delivery.work_id = queued.work_id
             WHERE queued.work_type = %s AND delivery.thread_id = %s
             ORDER BY queued.created_at, queued.work_id
            """,
            (_DELIVERY_WORK_TYPE, thread_id),
        ).fetchall()
        records = tuple(self._parse_record(row) for row in rows)
        for record in records:
            self._verify_history(record.work)
        return tuple(self._status(record) for record in records)

    def find_by_message(
        self,
        message_id: RecordId,
    ) -> tuple[DeliveryWorkStatus, ...]:
        rows = self._connection.execute(
            """
            SELECT queued.payload, queued.state, queued.available_at, queued.attempts,
                   queued.max_attempts, queued.updated_at, queued.lease_owner,
                   queued.lease_expires_at
              FROM melloa.jobs_outbox AS queued
              JOIN melloa.outbound_deliveries AS delivery
                ON delivery.work_id = queued.work_id
             WHERE queued.work_type = %s AND delivery.message_id = %s
             ORDER BY delivery.client_adapter, delivery.destination_ref, queued.work_id
            """,
            (_DELIVERY_WORK_TYPE, message_id),
        ).fetchall()
        records = tuple(self._parse_record(row) for row in rows)
        for record in records:
            self._verify_history(record.work)
        return tuple(self._status(record) for record in records)

    def resume(
        self,
        work_id: RecordId,
        resumption: DeliveryWorkResumption,
        *,
        available_at: datetime,
        added_attempts: int,
    ) -> DeliveryWorkStatus:
        if added_attempts < 1 or resumption.added_attempts != added_attempts:
            raise ValueError("added attempts must match the delivery resumption")
        with self._connection.transaction():
            record = self._locked_record(work_id)
            if resumption in record.work.resumptions:
                return self._status(record)
            if record.state is not DeliveryWorkState.DEAD:
                return self._status(record)
            if (
                resumption.work_id != work_id
                or resumption.message_id != record.work.message_id
                or resumption.prior_attempts != record.attempt_count
                or resumption.requested_at != available_at
                or resumption.authorization_request.action_hash
                != record.work.authorization_request.action_hash
            ):
                raise DeliveryConflictError("resumption does not match dead delivery work")
            self._persist_policy_decision(resumption.policy_decision)
            self._persist_resumption(resumption)
            work = record.work.model_copy(
                update={"resumptions": (*record.work.resumptions, resumption)}
            )
            updated = replace(
                record,
                work=work,
                state=DeliveryWorkState.READY,
                available_at=available_at,
                max_attempts=record.max_attempts + added_attempts,
                updated_at=available_at,
                lease_owner=None,
                lease_expires_at=None,
            )
            self._write_record(updated)
            return self._status(updated)

    def _claim(
        self,
        *,
        work_id: RecordId | None,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedDeliveryWork | None:
        if lease_expires_at <= now:
            raise ValueError("delivery lease must expire after it starts")
        with self._connection.transaction():
            if work_id is None:
                row = self._connection.execute(
                    """
                    SELECT payload, state, available_at, attempts, max_attempts,
                           updated_at, lease_owner, lease_expires_at
                      FROM melloa.jobs_outbox
                     WHERE work_type = %s
                       AND (
                            (state = 'ready' AND available_at <= %s)
                            OR (state = 'running' AND lease_expires_at <= %s)
                       )
                     ORDER BY available_at, created_at, work_id
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                    """,
                    (_DELIVERY_WORK_TYPE, now, now),
                ).fetchone()
                if row is None:
                    return None
            else:
                row = self._connection.execute(
                    """
                    SELECT payload, state, available_at, attempts, max_attempts,
                           updated_at, lease_owner, lease_expires_at
                      FROM melloa.jobs_outbox
                     WHERE work_type = %s AND work_id = %s
                     FOR UPDATE
                    """,
                    (_DELIVERY_WORK_TYPE, work_id),
                ).fetchone()
                if row is None:
                    raise DeliveryNotFoundError(f"delivery work not found: {work_id}")
            record = self._parse_record(row)
            self._verify_history(record.work)
            if record.state is DeliveryWorkState.RUNNING:
                if record.lease_expires_at is None or record.lease_expires_at > now:
                    return None
                record = self._expire_lease(record, now)
                self._write_record(record)
            if record.state is not DeliveryWorkState.READY or record.available_at > now:
                return None
            if record.attempt_count >= record.max_attempts:
                raise DeliveryConflictError("ready delivery exhausted its attempt budget")
            attempt = record.attempt_count + 1
            updated = replace(
                record,
                state=DeliveryWorkState.RUNNING,
                attempt_count=attempt,
                updated_at=now,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
            )
            self._write_record(updated)
            return ClaimedDeliveryWork(
                work=updated.work,
                attempt=attempt,
                max_attempts=updated.max_attempts,
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
            )

    def _expire_lease(
        self,
        record: _DeliveryRecord,
        now: datetime,
    ) -> _DeliveryRecord:
        if record.lease_expires_at is None or record.attempt_count < 1:
            raise DeliveryConflictError("running delivery has an invalid lease")
        request, decision, _authorized_at = record.work.current_authorization()
        terminal = record.attempt_count >= record.max_attempts
        completed_at = max(record.updated_at, record.lease_expires_at)
        retry_at = None
        outcome = DeliveryWorkOutcome.DEAD
        state = DeliveryWorkState.DEAD
        available_at = completed_at
        if not terminal:
            retry_at = now if now > completed_at else now + timedelta(microseconds=1)
            outcome = DeliveryWorkOutcome.RETRY_SCHEDULED
            state = DeliveryWorkState.READY
            available_at = retry_at
        attempt = DeliveryWorkAttempt(
            attempt_id=self._id_factory("deliveryattempt"),
            work_id=record.work.work_id,
            message_id=record.work.message_id,
            attempt=record.attempt_count,
            authorization_request_id=request.request_id,
            policy_decision_id=decision.decision_id,
            action_hash=request.action_hash,
            outcome=outcome,
            error_code="delivery.lease_expired",
            started_at=record.updated_at,
            completed_at=completed_at,
            retry_at=retry_at,
        )
        self._persist_work_attempt(attempt)
        work = record.work.model_copy(update={"attempts": (*record.work.attempts, attempt)})
        return replace(
            record,
            work=work,
            state=state,
            available_at=available_at,
            updated_at=completed_at,
            lease_owner=None,
            lease_expires_at=None,
        )

    def _read_record(self, work_id: RecordId) -> _DeliveryRecord:
        row = self._connection.execute(
            """
            SELECT payload, state, available_at, attempts, max_attempts,
                   updated_at, lease_owner, lease_expires_at
              FROM melloa.jobs_outbox
             WHERE work_type = %s AND work_id = %s
            """,
            (_DELIVERY_WORK_TYPE, work_id),
        ).fetchone()
        if row is None:
            raise DeliveryNotFoundError(f"delivery work not found: {work_id}")
        record = self._parse_record(row)
        self._verify_history(record.work)
        return record

    def _locked_record(self, work_id: RecordId) -> _DeliveryRecord:
        row = self._connection.execute(
            """
            SELECT payload, state, available_at, attempts, max_attempts,
                   updated_at, lease_owner, lease_expires_at
              FROM melloa.jobs_outbox
             WHERE work_type = %s AND work_id = %s
             FOR UPDATE
            """,
            (_DELIVERY_WORK_TYPE, work_id),
        ).fetchone()
        if row is None:
            raise DeliveryNotFoundError(f"delivery work not found: {work_id}")
        record = self._parse_record(row)
        self._verify_history(record.work)
        return record

    def _write_record(self, record: _DeliveryRecord) -> None:
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
                _DELIVERY_WORK_TYPE,
            ),
        )
        if updated.rowcount != 1:
            raise DeliveryConflictError(
                f"delivery work disappeared during update: {record.work.work_id}"
            )

    def _persist_policy_decision(self, decision: PolicyDecision) -> None:
        inserted = self._connection.execute(
            """
            INSERT INTO melloa.policy_decisions (
                decision_id, request_id, action_hash, effect, policy_version,
                reason_codes, decided_at, expires_at, document
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (decision_id) DO NOTHING
            """,
            (
                decision.decision_id,
                decision.request_id,
                decision.action_hash,
                decision.effect.value,
                decision.policy_version,
                list(decision.reason_codes),
                decision.decided_at,
                decision.expires_at,
                Jsonb(decision.model_dump(mode="json")),
            ),
        )
        if inserted.rowcount == 1:
            return
        row = self._connection.execute(
            "SELECT document FROM melloa.policy_decisions WHERE decision_id = %s",
            (decision.decision_id,),
        ).fetchone()
        if row is None or row[0] != decision.model_dump(mode="json"):
            raise DeliveryConflictError(f"policy decision ID conflicts: {decision.decision_id}")

    def _persist_adapter_receipt(
        self,
        work_id: RecordId,
        receipt: DeliveryAttempt,
    ) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO melloa.delivery_attempts (
                    delivery_id, message_id, client_adapter, destination_ref,
                    attempt, state, attempted_at, document, outbound_work_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    receipt.delivery_id,
                    receipt.message_id,
                    receipt.client_adapter,
                    receipt.destination_ref,
                    receipt.attempt,
                    receipt.state.value,
                    receipt.attempted_at,
                    Jsonb(receipt.model_dump(mode="json")),
                    work_id,
                ),
            )
        except UniqueViolation as error:
            raise DeliveryConflictError("adapter delivery receipt conflicts") from error

    def _persist_execution_receipt(
        self,
        work_id: RecordId,
        receipt: DeliveryExecutionReceipt,
    ) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO melloa.executed_actions (
                    action_id, decision_id, action_hash, capability_id, operation,
                    executed_at, result_document, outbound_work_id, delivery_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    receipt.action_id,
                    receipt.decision_id,
                    receipt.action_hash,
                    receipt.capability_id,
                    receipt.operation,
                    receipt.executed_at,
                    Jsonb(receipt.model_dump(mode="json")),
                    work_id,
                    receipt.delivery_id,
                ),
            )
        except UniqueViolation as error:
            raise DeliveryConflictError("delivery execution receipt conflicts") from error

    def _persist_work_attempt(self, attempt: DeliveryWorkAttempt) -> None:
        adapter_delivery_id = (
            None if attempt.adapter_receipt is None else attempt.adapter_receipt.delivery_id
        )
        execution_action_id = (
            None if attempt.execution_receipt is None else attempt.execution_receipt.action_id
        )
        try:
            self._connection.execute(
                """
                INSERT INTO melloa.delivery_work_attempts (
                    attempt_id, work_id, message_id, attempt, authorization_request_id,
                    policy_decision_id, action_hash, outcome, error_code, started_at,
                    completed_at, retry_at, adapter_delivery_id, execution_action_id,
                    document
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    attempt.attempt_id,
                    attempt.work_id,
                    attempt.message_id,
                    attempt.attempt,
                    attempt.authorization_request_id,
                    attempt.policy_decision_id,
                    attempt.action_hash,
                    attempt.outcome.value,
                    attempt.error_code,
                    attempt.started_at,
                    attempt.completed_at,
                    attempt.retry_at,
                    adapter_delivery_id,
                    execution_action_id,
                    Jsonb(attempt.model_dump(mode="json")),
                ),
            )
        except UniqueViolation as error:
            raise DeliveryConflictError("delivery work attempt conflicts") from error

    def _persist_resumption(self, resumption: DeliveryWorkResumption) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO melloa.delivery_work_resumptions (
                    resumption_id, work_id, message_id, requested_by, prior_attempts,
                    added_attempts, authorization_request_id, policy_decision_id,
                    action_hash, requested_at, document
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    resumption.resumption_id,
                    resumption.work_id,
                    resumption.message_id,
                    resumption.requested_by,
                    resumption.prior_attempts,
                    resumption.added_attempts,
                    resumption.authorization_request.request_id,
                    resumption.policy_decision.decision_id,
                    resumption.authorization_request.action_hash,
                    resumption.requested_at,
                    Jsonb(resumption.model_dump(mode="json")),
                ),
            )
        except UniqueViolation as error:
            raise DeliveryConflictError("delivery work resumption conflicts") from error

    def _verify_history(self, work: OutboundDeliveryWork) -> None:
        row = self._connection.execute(
            """
            SELECT thread_id, message_id, requested_by, client_adapter, destination_ref,
                   action_hash, initial_policy_decision_id, created_at, document
              FROM melloa.outbound_deliveries
             WHERE work_id = %s
            """,
            (work.work_id,),
        ).fetchone()
        initial = work.model_copy(update={"attempts": (), "resumptions": ()})
        expected = (
            work.thread_id,
            work.message_id,
            work.requested_by,
            work.client_adapter,
            work.destination_ref,
            work.authorization_request.action_hash,
            work.policy_decision.decision_id,
            work.created_at,
            initial.model_dump(mode="json"),
        )
        if row != expected:
            raise DeliveryConflictError("delivery identity differs from its immutable record")
        attempt_documents = tuple(
            item[0]
            for item in self._connection.execute(
                """
                SELECT document
                  FROM melloa.delivery_work_attempts
                 WHERE work_id = %s
                 ORDER BY attempt
                """,
                (work.work_id,),
            ).fetchall()
        )
        expected_attempts = tuple(attempt.model_dump(mode="json") for attempt in work.attempts)
        if attempt_documents != expected_attempts:
            raise DeliveryConflictError("delivery attempt history differs from its job payload")
        resumption_documents = tuple(
            item[0]
            for item in self._connection.execute(
                """
                SELECT document
                  FROM melloa.delivery_work_resumptions
                 WHERE work_id = %s
                 ORDER BY requested_at, resumption_id
                """,
                (work.work_id,),
            ).fetchall()
        )
        expected_resumptions = tuple(
            resumption.model_dump(mode="json") for resumption in work.resumptions
        )
        if resumption_documents != expected_resumptions:
            raise DeliveryConflictError("delivery resumption history differs from its job payload")

    @staticmethod
    def _parse_record(row: tuple[Any, ...]) -> _DeliveryRecord:
        try:
            work = OutboundDeliveryWork.model_validate_json(canonical_json_bytes(row[0]))
            state = DeliveryWorkState(str(row[1]))
        except (ValidationError, ValueError) as error:
            raise DeliveryConflictError("delivery job contains an invalid contract") from error
        return _DeliveryRecord(
            work=work,
            state=state,
            available_at=cast(datetime, row[2]),
            attempt_count=int(row[3]),
            max_attempts=int(row[4]),
            updated_at=cast(datetime, row[5]),
            lease_owner=(None if row[6] is None else cast(RecordId, row[6])),
            lease_expires_at=(None if row[7] is None else cast(datetime, row[7])),
        )

    @staticmethod
    def _require_claim(record: _DeliveryRecord, claim: ClaimedDeliveryWork) -> None:
        if (
            record.state is not DeliveryWorkState.RUNNING
            or record.work != claim.work
            or record.attempt_count != claim.attempt
            or record.max_attempts != claim.max_attempts
            or record.lease_owner != claim.lease_owner
            or record.lease_expires_at != claim.lease_expires_at
        ):
            raise DeliveryConflictError("delivery claim is stale or does not hold the lease")

    @staticmethod
    def _validate_attempt(
        record: _DeliveryRecord,
        attempt: DeliveryWorkAttempt,
    ) -> None:
        request, decision, _authorized_at = record.work.current_authorization()
        if (
            attempt.work_id != record.work.work_id
            or attempt.message_id != record.work.message_id
            or attempt.attempt != record.attempt_count
            or attempt.authorization_request_id != request.request_id
            or attempt.policy_decision_id != decision.decision_id
            or attempt.action_hash != request.action_hash
            or (
                attempt.adapter_receipt is not None
                and (
                    attempt.adapter_receipt.client_adapter != record.work.client_adapter
                    or attempt.adapter_receipt.destination_ref
                    != record.work.destination_ref
                )
            )
        ):
            raise DeliveryConflictError("delivery attempt does not match its leased work")

    @staticmethod
    def _require_same_submission(
        existing: OutboundDeliveryWork,
        submitted: OutboundDeliveryWork,
    ) -> None:
        if (
            existing.thread_id != submitted.thread_id
            or existing.message_id != submitted.message_id
            or existing.message_hash != submitted.message_hash
            or existing.requested_by != submitted.requested_by
            or existing.client_adapter != submitted.client_adapter
            or existing.destination_ref != submitted.destination_ref
            or existing.authorization_request.action_hash
            != submitted.authorization_request.action_hash
        ):
            raise DeliveryConflictError("delivery idempotency key was reused with different work")

    @staticmethod
    def _status(record: _DeliveryRecord) -> DeliveryWorkStatus:
        latest = record.work.attempts[-1] if record.work.attempts else None
        completed_at = (
            latest.completed_at
            if record.state is DeliveryWorkState.COMPLETED and latest is not None
            else None
        )
        last_error_code = (
            None
            if record.state is DeliveryWorkState.COMPLETED
            else next(
                (
                    attempt.error_code
                    for attempt in reversed(record.work.attempts)
                    if attempt.error_code is not None
                ),
                None,
            )
        )
        request, decision, _authorized_at = record.work.current_authorization()
        return DeliveryWorkStatus(
            work_id=record.work.work_id,
            thread_id=record.work.thread_id,
            message_id=record.work.message_id,
            client_adapter=record.work.client_adapter,
            destination_ref=record.work.destination_ref,
            action_hash=request.action_hash,
            current_policy_decision_id=decision.decision_id,
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
