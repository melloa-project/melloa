"""Thread-safe process-local outbound delivery queue for synthetic M1 runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from threading import RLock

from melloa.domain.base import RecordId, new_record_id
from melloa.domain.delivery import (
    DeliveryWorkAttempt,
    DeliveryWorkOutcome,
    DeliveryWorkResumption,
    DeliveryWorkState,
    DeliveryWorkStatus,
    OutboundDeliveryWork,
)
from melloa.ports.delivery import (
    ClaimedDeliveryWork,
    DeliveryConflictError,
    DeliveryNotFoundError,
    EnqueuedDeliveryWork,
)


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


class InMemoryDeliveryStore:
    def __init__(
        self,
        *,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._lock = RLock()
        self._id_factory = id_factory
        self._records: dict[RecordId, _DeliveryRecord] = {}
        self._work_by_idempotency: dict[str, RecordId] = {}

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
        with self._lock:
            existing_id = self._work_by_idempotency.get(work.idempotency_key)
            if existing_id is not None:
                existing = self._records[existing_id]
                self._require_same_submission(existing.work, work)
                return EnqueuedDeliveryWork(
                    work=existing.work,
                    status=self._status(existing),
                    created=False,
                )
            if work.work_id in self._records:
                raise DeliveryConflictError(f"delivery work ID conflicts: {work.work_id}")
            record = _DeliveryRecord(
                work=work,
                state=DeliveryWorkState.READY,
                available_at=work.created_at,
                attempt_count=0,
                max_attempts=max_attempts,
                updated_at=work.created_at,
            )
            self._records[work.work_id] = record
            self._work_by_idempotency[work.idempotency_key] = work.work_id
            return EnqueuedDeliveryWork(
                work=work,
                status=self._status(record),
                created=True,
            )

    def get_work(self, work_id: RecordId) -> OutboundDeliveryWork:
        with self._lock:
            return self._record(work_id).work

    def claim_work(
        self,
        work_id: RecordId,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedDeliveryWork | None:
        with self._lock:
            self._record(work_id)
            return self._claim(
                work_id,
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
        with self._lock:
            for work_id, record in tuple(self._records.items()):
                if (
                    record.state is DeliveryWorkState.RUNNING
                    and record.lease_expires_at is not None
                    and record.lease_expires_at <= now
                ):
                    self._records[work_id] = self._expire_lease(record, now)
            candidates = sorted(
                (
                    record
                    for record in self._records.values()
                    if record.state is DeliveryWorkState.READY and record.available_at <= now
                ),
                key=lambda record: (
                    record.available_at,
                    record.work.created_at,
                    record.work.work_id,
                ),
            )
            if not candidates:
                return None
            return self._claim(
                candidates[0].work.work_id,
                lease_owner=lease_owner,
                now=now,
                lease_expires_at=lease_expires_at,
            )

    def record_failure(
        self,
        claim: ClaimedDeliveryWork,
        attempt: DeliveryWorkAttempt,
    ) -> DeliveryWorkStatus:
        with self._lock:
            existing = self._records.get(claim.work.work_id)
            if existing is not None and attempt in existing.work.attempts:
                return self._status(existing)
            record = self._require_claim(claim)
            self._validate_attempt(record, attempt)
            terminal = attempt.outcome is DeliveryWorkOutcome.DEAD
            if attempt.outcome is DeliveryWorkOutcome.SUCCEEDED or (
                attempt.outcome is DeliveryWorkOutcome.RETRY_SCHEDULED
                and claim.attempt >= claim.max_attempts
            ):
                raise DeliveryConflictError(
                    "delivery failure outcome conflicts with attempt budget"
                )
            work = record.work.model_copy(update={"attempts": (*record.work.attempts, attempt)})
            available_at = attempt.completed_at
            if not terminal:
                if attempt.retry_at is None:
                    raise DeliveryConflictError("retryable delivery has no retry time")
                available_at = attempt.retry_at
            updated = replace(
                record,
                work=work,
                state=(DeliveryWorkState.DEAD if terminal else DeliveryWorkState.READY),
                available_at=available_at,
                updated_at=attempt.completed_at,
                lease_owner=None,
                lease_expires_at=None,
            )
            self._records[work.work_id] = updated
            return self._status(updated)

    def complete(
        self,
        claim: ClaimedDeliveryWork,
        attempt: DeliveryWorkAttempt,
    ) -> DeliveryWorkStatus:
        with self._lock:
            existing = self._records.get(claim.work.work_id)
            if existing is not None and attempt in existing.work.attempts:
                return self._status(existing)
            record = self._require_claim(claim)
            self._validate_attempt(record, attempt)
            if attempt.outcome is not DeliveryWorkOutcome.SUCCEEDED:
                raise DeliveryConflictError("completed delivery requires a successful attempt")
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
            self._records[work.work_id] = updated
            return self._status(updated)

    def status(self, work_id: RecordId) -> DeliveryWorkStatus:
        with self._lock:
            return self._status(self._record(work_id))

    def list_status(self, thread_id: RecordId) -> tuple[DeliveryWorkStatus, ...]:
        with self._lock:
            records = tuple(
                record for record in self._records.values() if record.work.thread_id == thread_id
            )
            return tuple(
                self._status(record)
                for record in sorted(
                    records,
                    key=lambda record: (record.work.created_at, record.work.work_id),
                )
            )

    def find_by_message(
        self,
        message_id: RecordId,
    ) -> tuple[DeliveryWorkStatus, ...]:
        with self._lock:
            records = tuple(
                record for record in self._records.values() if record.work.message_id == message_id
            )
            return tuple(
                self._status(record)
                for record in sorted(
                    records,
                    key=lambda record: (
                        record.work.client_adapter,
                        record.work.destination_ref,
                        record.work.work_id,
                    ),
                )
            )

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
        with self._lock:
            record = self._record(work_id)
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
            self._records[work_id] = updated
            return self._status(updated)

    def _claim(
        self,
        work_id: RecordId,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedDeliveryWork | None:
        if lease_expires_at <= now:
            raise ValueError("delivery lease must expire after it starts")
        record = self._records[work_id]
        if record.state is DeliveryWorkState.RUNNING:
            if record.lease_expires_at is None or record.lease_expires_at > now:
                return None
            record = self._expire_lease(record, now)
            self._records[work_id] = record
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
        self._records[work_id] = updated
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

    def _record(self, work_id: RecordId) -> _DeliveryRecord:
        try:
            return self._records[work_id]
        except KeyError as error:
            raise DeliveryNotFoundError(f"delivery work not found: {work_id}") from error

    def _require_claim(self, claim: ClaimedDeliveryWork) -> _DeliveryRecord:
        record = self._record(claim.work.work_id)
        if (
            record.state is not DeliveryWorkState.RUNNING
            or record.attempt_count != claim.attempt
            or record.max_attempts != claim.max_attempts
            or record.lease_owner != claim.lease_owner
            or record.lease_expires_at != claim.lease_expires_at
            or record.work != claim.work
        ):
            raise DeliveryConflictError("delivery claim is stale or does not hold the lease")
        return record

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
