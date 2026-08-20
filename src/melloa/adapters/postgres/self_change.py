"""PostgreSQL state and evidence for exact owner-approved source changes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg import sql
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from melloa.domain.base import QualifiedName, RecordId, Sha256Digest
from melloa.domain.self_change import (
    ChangePatch,
    ChangeSummary,
    GitRevision,
    SelfChange,
    SelfChangeState,
    self_change_proposal_digest,
)
from melloa.ports.self_change import (
    SelfChangeConflictError,
    SelfChangeNotFoundError,
)

_CHANGE_COLUMNS = sql.SQL("""
    change_id, owner_id, request_text, request_digest, requested_update_id,
    state, base_revision, proposal_summary, proposal_patch, proposal_digest,
    approval_update_id, approved_digest, candidate_revision, failure_reason,
    attempt_count, max_attempts, available_at, lease_owner, lease_expires_at,
    requested_at, updated_at, approved_at, deployed_at, cancelled_update_id,
    cancelled_at, rolled_back_at
""")
_INTEGRITY_ERRORS = (CheckViolation, ForeignKeyViolation, UniqueViolation)


class PostgresSelfChangeStore:
    def __init__(self, connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        self._connection = connection

    def create(self, change: SelfChange) -> SelfChange:
        if (
            change.state is not SelfChangeState.REQUESTED
            or change.attempt_count != 0
            or change.requested_at != change.updated_at
            or change.requested_at != change.available_at
        ):
            raise ValueError("new self-change must be pristine requested work")
        try:
            with self._connection.transaction():
                existing_row = self._connection.execute(
                    sql.SQL("""
                    SELECT {}
                      FROM melloa.self_changes
                     WHERE requested_update_id = %s
                     FOR UPDATE
                    """).format(_CHANGE_COLUMNS),
                    (change.requested_update_id,),
                ).fetchone()
                if existing_row is not None:
                    existing = self._change(existing_row)
                    if (
                        existing.owner_id == change.owner_id
                        and existing.request_text == change.request_text
                        and existing.request_digest == change.request_digest
                    ):
                        return existing
                    raise SelfChangeConflictError(
                        "Telegram update already identifies a different self-change request"
                    )
                self._connection.execute(
                    """
                    INSERT INTO melloa.self_changes (
                        change_id, owner_id, request_text, request_digest,
                        requested_update_id, state, attempt_count, max_attempts,
                        available_at, requested_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        change.change_id,
                        change.owner_id,
                        change.request_text,
                        change.request_digest,
                        change.requested_update_id,
                        change.state.value,
                        change.attempt_count,
                        change.max_attempts,
                        change.available_at,
                        change.requested_at,
                        change.updated_at,
                    ),
                )
                self._insert_event(
                    change.change_id,
                    event_type="self_change.requested",
                    state=SelfChangeState.REQUESTED,
                    occurred_at=change.requested_at,
                    telegram_update_id=change.requested_update_id,
                )
                return self._read(change.owner_id, change.change_id, for_update=True)
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change request conflicts with durable state"
            ) from error

    def latest(self, owner_id: RecordId) -> SelfChange | None:
        row = self._connection.execute(
            sql.SQL("""
            SELECT {}
              FROM melloa.self_changes
             WHERE owner_id = %s
             ORDER BY requested_at DESC, change_id DESC
             LIMIT 1
            """).format(_CHANGE_COLUMNS),
            (owner_id,),
        ).fetchone()
        return None if row is None else self._change(row)

    def get(self, owner_id: RecordId, change_id: RecordId) -> SelfChange:
        return self._read(owner_id, change_id, for_update=False)

    def claim_next_planning(
        self,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> SelfChange | None:
        if lease_expires_at <= now:
            raise ValueError("self-change planning lease must expire in the future")
        try:
            with self._connection.transaction():
                self._fail_exhausted_planning(now)
                row = self._connection.execute(
                    sql.SQL("""
                    SELECT {}
                      FROM melloa.self_changes
                     WHERE attempt_count < max_attempts
                       AND (
                           (state = 'requested' AND available_at <= %s)
                           OR (state = 'planning' AND lease_expires_at <= %s)
                       )
                     ORDER BY available_at, requested_at, change_id
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                    """).format(_CHANGE_COLUMNS),
                    (now, now),
                ).fetchone()
                if row is None:
                    return None
                existing = self._change(row)
                if lease_expires_at <= existing.updated_at:
                    raise ValueError("self-change planning lease predates durable state")
                claimed_row = self._connection.execute(
                    sql.SQL("""
                    UPDATE melloa.self_changes
                       SET state = 'planning',
                           attempt_count = attempt_count + 1,
                           lease_owner = %s,
                           lease_expires_at = %s,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE change_id = %s
                     RETURNING {}
                    """).format(_CHANGE_COLUMNS),
                    (lease_owner, lease_expires_at, now, existing.change_id),
                ).fetchone()
                if claimed_row is None:
                    raise SelfChangeConflictError(
                        "self-change disappeared while planning was claimed"
                    )
                claimed = self._change(claimed_row)
                self._insert_event(
                    claimed.change_id,
                    event_type="self_change.planning_started",
                    state=SelfChangeState.PLANNING,
                    occurred_at=now,
                )
                return claimed
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change planning claim conflicts with durable state"
            ) from error

    def record_proposal(
        self,
        claim: SelfChange,
        *,
        base_revision: GitRevision,
        summary: ChangeSummary,
        patch: ChangePatch,
        now: datetime,
    ) -> SelfChange:
        proposal_digest = self_change_proposal_digest(
            base_revision=base_revision,
            summary=summary,
            patch=patch,
        )
        try:
            with self._connection.transaction():
                existing = self._read(claim.owner_id, claim.change_id, for_update=True)
                if existing.state is SelfChangeState.PROPOSAL_READY:
                    if (
                        existing.base_revision == base_revision
                        and existing.proposal_summary == summary
                        and existing.proposal_patch == patch
                        and existing.proposal_digest == proposal_digest
                    ):
                        return existing
                    raise SelfChangeConflictError(
                        "self-change already retains a different proposal"
                    )
                self._require_active_claim(
                    existing,
                    claim,
                    SelfChangeState.PLANNING,
                    now,
                )
                updated_row = self._connection.execute(
                    sql.SQL("""
                    UPDATE melloa.self_changes
                       SET state = 'proposal_ready',
                           base_revision = %s,
                           proposal_summary = %s,
                           proposal_patch = %s,
                           proposal_digest = %s,
                           attempt_count = 0,
                           available_at = %s,
                           lease_owner = NULL,
                           lease_expires_at = NULL,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE owner_id = %s AND change_id = %s
                     RETURNING {}
                    """).format(_CHANGE_COLUMNS),
                    (
                        base_revision,
                        summary,
                        patch,
                        proposal_digest,
                        now,
                        now,
                        claim.owner_id,
                        claim.change_id,
                    ),
                ).fetchone()
                if updated_row is None:
                    raise SelfChangeConflictError(
                        "self-change disappeared while its proposal was retained"
                    )
                updated = self._change(updated_row)
                self._insert_event(
                    updated.change_id,
                    event_type="self_change.proposal_ready",
                    state=SelfChangeState.PROPOSAL_READY,
                    occurred_at=now,
                    proposal_digest=proposal_digest,
                )
                return updated
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change proposal conflicts with durable state"
            ) from error

    def record_planning_failure(
        self,
        claim: SelfChange,
        *,
        error_code: QualifiedName,
        retry_at: datetime,
        now: datetime,
    ) -> SelfChange:
        if retry_at <= now:
            raise ValueError("self-change planning retry must be scheduled in the future")
        try:
            with self._connection.transaction():
                existing = self._read(claim.owner_id, claim.change_id, for_update=True)
                self._require_active_claim(
                    existing,
                    claim,
                    SelfChangeState.PLANNING,
                    now,
                )
                terminal = existing.attempt_count >= existing.max_attempts
                next_state = (
                    SelfChangeState.FAILED if terminal else SelfChangeState.REQUESTED
                )
                available_at = now if terminal else retry_at
                failure_reason = error_code if terminal else None
                updated_row = self._connection.execute(
                    sql.SQL("""
                    UPDATE melloa.self_changes
                       SET state = %s,
                           failure_reason = %s,
                           available_at = %s,
                           lease_owner = NULL,
                           lease_expires_at = NULL,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE owner_id = %s AND change_id = %s
                     RETURNING {}
                    """).format(_CHANGE_COLUMNS),
                    (
                        next_state.value,
                        failure_reason,
                        available_at,
                        now,
                        claim.owner_id,
                        claim.change_id,
                    ),
                ).fetchone()
                if updated_row is None:
                    raise SelfChangeConflictError(
                        "self-change disappeared while planning failure was retained"
                    )
                updated = self._change(updated_row)
                self._insert_event(
                    updated.change_id,
                    event_type=(
                        "self_change.failed"
                        if terminal
                        else "self_change.planning_retry"
                    ),
                    state=next_state,
                    occurred_at=now,
                    reason_code=error_code,
                )
                return updated
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change planning failure conflicts with durable state"
            ) from error

    def approve(
        self,
        owner_id: RecordId,
        change_id: RecordId,
        *,
        proposal_digest: Sha256Digest,
        approval_update_id: int,
        now: datetime,
    ) -> SelfChange:
        try:
            with self._connection.transaction():
                existing = self._read(owner_id, change_id, for_update=True)
                if existing.approval_update_id == approval_update_id:
                    if existing.approved_digest == proposal_digest:
                        return existing
                    raise SelfChangeConflictError(
                        "Telegram update already identifies a different approval"
                    )
                if (
                    existing.state is not SelfChangeState.PROPOSAL_READY
                    or existing.proposal_digest != proposal_digest
                ):
                    raise SelfChangeConflictError(
                        "self-change proposal is not awaiting this exact approval"
                    )
                self._connection.execute(
                    """
                    UPDATE melloa.self_changes
                       SET state = 'approved',
                           approval_update_id = %s,
                           approved_digest = %s,
                           approved_at = %s,
                           available_at = %s,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE owner_id = %s AND change_id = %s
                    """,
                    (
                        approval_update_id,
                        proposal_digest,
                        now,
                        now,
                        now,
                        owner_id,
                        change_id,
                    ),
                )
                self._insert_event(
                    change_id,
                    event_type="self_change.approved",
                    state=SelfChangeState.APPROVED,
                    occurred_at=now,
                    telegram_update_id=approval_update_id,
                    proposal_digest=proposal_digest,
                )
                return self._read(owner_id, change_id, for_update=True)
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change approval conflicts with durable state"
            ) from error

    def cancel(
        self,
        owner_id: RecordId,
        change_id: RecordId,
        *,
        cancellation_update_id: int,
        now: datetime,
    ) -> SelfChange:
        try:
            with self._connection.transaction():
                existing = self._read(owner_id, change_id, for_update=True)
                if existing.cancelled_update_id == cancellation_update_id:
                    return existing
                if existing.state not in {
                    SelfChangeState.REQUESTED,
                    SelfChangeState.PLANNING,
                    SelfChangeState.PROPOSAL_READY,
                    SelfChangeState.APPROVED,
                }:
                    raise SelfChangeConflictError(
                        "self-change can no longer be cancelled"
                    )
                self._connection.execute(
                    """
                    UPDATE melloa.self_changes
                       SET state = 'cancelled',
                           available_at = %s,
                           lease_owner = NULL,
                           lease_expires_at = NULL,
                           cancelled_update_id = %s,
                           cancelled_at = %s,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE owner_id = %s AND change_id = %s
                    """,
                    (
                        now,
                        cancellation_update_id,
                        now,
                        now,
                        owner_id,
                        change_id,
                    ),
                )
                self._insert_event(
                    change_id,
                    event_type="self_change.cancelled",
                    state=SelfChangeState.CANCELLED,
                    occurred_at=now,
                    telegram_update_id=cancellation_update_id,
                )
                return self._read(owner_id, change_id, for_update=True)
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change cancellation conflicts with durable state"
            ) from error

    def claim_next_applying(
        self,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> SelfChange | None:
        if lease_expires_at <= now:
            raise ValueError("self-change application lease must expire in the future")
        try:
            with self._connection.transaction():
                self._fail_exhausted_applying(now)
                row = self._connection.execute(
                    sql.SQL("""
                    SELECT {}
                      FROM melloa.self_changes
                     WHERE attempt_count < max_attempts
                       AND (
                           (state = 'approved' AND available_at <= %s)
                           OR (state = 'applying' AND lease_expires_at <= %s)
                       )
                     ORDER BY available_at, requested_at, change_id
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                    """).format(_CHANGE_COLUMNS),
                    (now, now),
                ).fetchone()
                if row is None:
                    return None
                existing = self._change(row)
                if lease_expires_at <= existing.updated_at:
                    raise ValueError("self-change application lease predates durable state")
                claimed_row = self._connection.execute(
                    sql.SQL("""
                    UPDATE melloa.self_changes
                       SET state = 'applying',
                           attempt_count = attempt_count + 1,
                           lease_owner = %s,
                           lease_expires_at = %s,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE change_id = %s
                     RETURNING {}
                    """).format(_CHANGE_COLUMNS),
                    (lease_owner, lease_expires_at, now, existing.change_id),
                ).fetchone()
                if claimed_row is None:
                    raise SelfChangeConflictError(
                        "self-change disappeared while application was claimed"
                    )
                claimed = self._change(claimed_row)
                self._insert_event(
                    claimed.change_id,
                    event_type="self_change.applying_started",
                    state=SelfChangeState.APPLYING,
                    occurred_at=now,
                )
                return claimed
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change application claim conflicts with durable state"
            ) from error

    def record_candidate(
        self,
        claim: SelfChange,
        *,
        candidate_revision: GitRevision,
        now: datetime,
    ) -> SelfChange:
        try:
            with self._connection.transaction():
                existing = self._read(claim.owner_id, claim.change_id, for_update=True)
                self._require_active_claim(
                    existing,
                    claim,
                    SelfChangeState.APPLYING,
                    now,
                )
                if existing.candidate_revision not in {None, candidate_revision}:
                    raise SelfChangeConflictError(
                        "self-change already identifies a different candidate commit"
                    )
                if existing.candidate_revision == candidate_revision:
                    return existing
                row = self._connection.execute(
                    sql.SQL("""
                    UPDATE melloa.self_changes
                       SET candidate_revision = %s,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE owner_id = %s AND change_id = %s
                     RETURNING {}
                    """).format(_CHANGE_COLUMNS),
                    (
                        candidate_revision,
                        now,
                        claim.owner_id,
                        claim.change_id,
                    ),
                ).fetchone()
                if row is None:
                    raise SelfChangeConflictError(
                        "self-change disappeared while its candidate was retained"
                    )
                return self._change(row)
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change candidate conflicts with durable state"
            ) from error

    def record_applying_failure(
        self,
        claim: SelfChange,
        *,
        error_code: QualifiedName,
        retry_at: datetime,
        now: datetime,
    ) -> SelfChange:
        if retry_at <= now:
            raise ValueError("self-change application retry must be scheduled in the future")
        try:
            with self._connection.transaction():
                existing = self._read(claim.owner_id, claim.change_id, for_update=True)
                self._require_active_claim(
                    existing,
                    claim,
                    SelfChangeState.APPLYING,
                    now,
                )
                terminal = existing.attempt_count >= existing.max_attempts
                next_state = (
                    SelfChangeState.FAILED if terminal else SelfChangeState.APPROVED
                )
                available_at = now if terminal else retry_at
                failure_reason = error_code if terminal else None
                row = self._connection.execute(
                    sql.SQL("""
                    UPDATE melloa.self_changes
                       SET state = %s,
                           failure_reason = %s,
                           available_at = %s,
                           lease_owner = NULL,
                           lease_expires_at = NULL,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE owner_id = %s AND change_id = %s
                     RETURNING {}
                    """).format(_CHANGE_COLUMNS),
                    (
                        next_state.value,
                        failure_reason,
                        available_at,
                        now,
                        claim.owner_id,
                        claim.change_id,
                    ),
                ).fetchone()
                if row is None:
                    raise SelfChangeConflictError(
                        "self-change disappeared while application failure was retained"
                    )
                updated = self._change(row)
                self._insert_event(
                    updated.change_id,
                    event_type=(
                        "self_change.failed"
                        if terminal
                        else "self_change.applying_retry"
                    ),
                    state=next_state,
                    occurred_at=now,
                    reason_code=error_code,
                )
                return updated
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change application failure conflicts with durable state"
            ) from error

    def record_deployed(
        self,
        claim: SelfChange,
        *,
        candidate_revision: GitRevision,
        now: datetime,
    ) -> SelfChange:
        try:
            with self._connection.transaction():
                existing = self._read(claim.owner_id, claim.change_id, for_update=True)
                if existing.state is SelfChangeState.DEPLOYED:
                    if existing.candidate_revision == candidate_revision:
                        return existing
                    raise SelfChangeConflictError(
                        "self-change already records a different deployed commit"
                    )
                self._require_active_claim(
                    existing,
                    claim,
                    SelfChangeState.APPLYING,
                    now,
                )
                if existing.candidate_revision != candidate_revision:
                    raise SelfChangeConflictError(
                        "deployed commit does not match the approved candidate"
                    )
                row = self._connection.execute(
                    sql.SQL("""
                    UPDATE melloa.self_changes
                       SET state = 'deployed',
                           available_at = %s,
                           lease_owner = NULL,
                           lease_expires_at = NULL,
                           deployed_at = %s,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE owner_id = %s AND change_id = %s
                     RETURNING {}
                    """).format(_CHANGE_COLUMNS),
                    (
                        now,
                        now,
                        now,
                        claim.owner_id,
                        claim.change_id,
                    ),
                ).fetchone()
                if row is None:
                    raise SelfChangeConflictError(
                        "self-change disappeared while deployment was retained"
                    )
                deployed = self._change(row)
                self._insert_event(
                    deployed.change_id,
                    event_type="self_change.deployed",
                    state=SelfChangeState.DEPLOYED,
                    occurred_at=now,
                    revision=candidate_revision,
                )
                return deployed
        except _INTEGRITY_ERRORS as error:
            raise SelfChangeConflictError(
                "self-change deployment conflicts with durable state"
            ) from error

    def _read(
        self,
        owner_id: RecordId,
        change_id: RecordId,
        *,
        for_update: bool,
    ) -> SelfChange:
        suffix = sql.SQL("FOR UPDATE") if for_update else sql.SQL("")
        row = self._connection.execute(
            sql.SQL("""
            SELECT {}
              FROM melloa.self_changes
             WHERE owner_id = %s AND change_id = %s
             {}
            """).format(_CHANGE_COLUMNS, suffix),
            (owner_id, change_id),
        ).fetchone()
        if row is None:
            raise SelfChangeNotFoundError(f"self-change not found: {change_id}")
        return self._change(row)

    def _insert_event(
        self,
        change_id: RecordId,
        *,
        event_type: str,
        state: SelfChangeState,
        occurred_at: datetime,
        telegram_update_id: int | None = None,
        proposal_digest: Sha256Digest | None = None,
        revision: GitRevision | None = None,
        reason_code: QualifiedName | None = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO melloa.self_change_events (
                change_id, event_type, state, telegram_update_id,
                proposal_digest, revision, reason_code, occurred_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                change_id,
                event_type,
                state.value,
                telegram_update_id,
                proposal_digest,
                revision,
                reason_code,
                occurred_at,
            ),
        )

    def _fail_exhausted_planning(self, now: datetime) -> None:
        rows = self._connection.execute(
            sql.SQL("""
            SELECT {}
              FROM melloa.self_changes
             WHERE state = 'planning'
               AND lease_expires_at <= %s
               AND attempt_count >= max_attempts
             ORDER BY available_at, requested_at, change_id
             FOR UPDATE SKIP LOCKED
            """).format(_CHANGE_COLUMNS),
            (now,),
        ).fetchall()
        for row in rows:
            change = self._change(row)
            self._connection.execute(
                """
                UPDATE melloa.self_changes
                   SET state = 'failed',
                       failure_reason = 'self_change.planning_lease_exhausted',
                       available_at = %s,
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       updated_at = GREATEST(updated_at, %s)
                 WHERE change_id = %s
                """,
                (now, now, change.change_id),
            )
            self._insert_event(
                change.change_id,
                event_type="self_change.failed",
                state=SelfChangeState.FAILED,
                occurred_at=now,
                reason_code="self_change.planning_lease_exhausted",
            )

    def _fail_exhausted_applying(self, now: datetime) -> None:
        rows = self._connection.execute(
            sql.SQL("""
            SELECT {}
              FROM melloa.self_changes
             WHERE state = 'applying'
               AND lease_expires_at <= %s
               AND attempt_count >= max_attempts
             ORDER BY available_at, requested_at, change_id
             FOR UPDATE SKIP LOCKED
            """).format(_CHANGE_COLUMNS),
            (now,),
        ).fetchall()
        for row in rows:
            change = self._change(row)
            self._connection.execute(
                """
                UPDATE melloa.self_changes
                   SET state = 'failed',
                       failure_reason = 'self_change.application_lease_exhausted',
                       available_at = %s,
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       updated_at = GREATEST(updated_at, %s)
                 WHERE change_id = %s
                """,
                (now, now, change.change_id),
            )
            self._insert_event(
                change.change_id,
                event_type="self_change.failed",
                state=SelfChangeState.FAILED,
                occurred_at=now,
                reason_code="self_change.application_lease_exhausted",
            )

    @staticmethod
    def _require_active_claim(
        existing: SelfChange,
        claim: SelfChange,
        expected_state: SelfChangeState,
        now: datetime,
    ) -> None:
        if (
            claim.state is not expected_state
            or existing.state is not expected_state
            or existing.change_id != claim.change_id
            or existing.attempt_count != claim.attempt_count
            or existing.lease_owner != claim.lease_owner
            or existing.lease_expires_at != claim.lease_expires_at
            or existing.lease_expires_at is None
            or existing.lease_expires_at <= now
        ):
            raise SelfChangeConflictError("self-change work lease is stale")

    @staticmethod
    def _change(row: tuple[Any, ...]) -> SelfChange:
        return SelfChange(
            change_id=str(row[0]),
            owner_id=str(row[1]),
            request_text=str(row[2]),
            request_digest=str(row[3]),
            requested_update_id=int(row[4]),
            state=SelfChangeState(str(row[5])),
            base_revision=None if row[6] is None else str(row[6]),
            proposal_summary=None if row[7] is None else str(row[7]),
            proposal_patch=None if row[8] is None else str(row[8]),
            proposal_digest=None if row[9] is None else str(row[9]),
            approval_update_id=None if row[10] is None else int(row[10]),
            approved_digest=None if row[11] is None else str(row[11]),
            candidate_revision=None if row[12] is None else str(row[12]),
            failure_reason=None if row[13] is None else str(row[13]),
            attempt_count=int(row[14]),
            max_attempts=int(row[15]),
            available_at=cast(datetime, row[16]),
            lease_owner=None if row[17] is None else str(row[17]),
            lease_expires_at=None if row[18] is None else cast(datetime, row[18]),
            requested_at=cast(datetime, row[19]),
            updated_at=cast(datetime, row[20]),
            approved_at=None if row[21] is None else cast(datetime, row[21]),
            deployed_at=None if row[22] is None else cast(datetime, row[22]),
            cancelled_update_id=None if row[23] is None else int(row[23]),
            cancelled_at=None if row[24] is None else cast(datetime, row[24]),
            rolled_back_at=None if row[25] is None else cast(datetime, row[25]),
        )


__all__ = ["PostgresSelfChangeStore"]
