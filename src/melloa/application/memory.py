"""Authenticated owner memory inspection and append-only correction use cases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import JsonObject, RecordId, new_record_id, utc_now
from melloa.domain.classification import EpistemicStatus, TrustLabel
from melloa.domain.guardian import GuardianMode
from melloa.domain.memory import (
    Assertion,
    AssertionCorrectionResult,
    AssertionStateChange,
    AssertionStateProjection,
    AssertionStateTransitionResult,
    AssertionStatus,
    MemoryInspection,
    ProvenanceEdge,
    ProvenanceRelation,
)
from melloa.ports.auth import RecentAuthenticationRequired
from melloa.ports.guardian import GuardianStatusReader
from melloa.ports.memory import (
    AssertionCorrectionWrite,
    AssertionStateTransitionWrite,
    MemoryConflictError,
    MemoryStore,
)


class MemoryOwnershipError(PermissionError):
    """An authenticated owner attempted to access another subject's memory."""


class MemoryUnavailableError(RuntimeError):
    """Guardian mode or runtime state forbids a memory write."""


class MemoryService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        store: MemoryStore,
        guardian_reader: GuardianStatusReader,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._owner_id = owner_id
        self._store = store
        self._guardian_reader = guardian_reader
        self._clock = clock
        self._id_factory = id_factory

    def inspect(
        self,
        principal: AuthenticatedOwner,
        assertion_id: RecordId,
    ) -> MemoryInspection:
        assertion = self._owned_assertion(principal, assertion_id)
        return MemoryInspection(
            assertion=assertion,
            current_state=self._store.get_assertion_state(assertion_id),
            provenance_edges=self._store.list_provenance_edges(frozenset({assertion_id})),
            state_changes=self._store.list_assertion_state_changes(assertion_id),
        )

    def correct(
        self,
        principal: AuthenticatedOwner,
        assertion_id: RecordId,
        *,
        value: JsonObject,
        expected_version: int,
    ) -> AssertionCorrectionResult:
        now = self._clock()
        self._require_recent_authentication(principal, now)
        target = self._owned_assertion(principal, assertion_id)
        self._require_write_mode()
        expected_state = self._store.get_assertion_state(assertion_id)
        if expected_state.version != expected_version:
            raise MemoryConflictError("assertion state changed before correction")
        correction = Assertion(
            assertion_id=self._id_factory("assertion"),
            subject_id=target.subject_id,
            predicate=target.predicate,
            value=value,
            epistemic_status=EpistemicStatus.CORRECTION,
            status=AssertionStatus.CONFIRMED,
            confidence=1.0,
            source_authority=TrustLabel.OWNER_AUTHORED,
            sensitivity=target.sensitivity,
            observed_at=now,
            valid_from=target.valid_from,
            valid_to=target.valid_to,
            correction_target_id=target.assertion_id,
        )
        provenance_edge = ProvenanceEdge(
            edge_id=self._id_factory("edge"),
            from_id=correction.assertion_id,
            to_id=target.assertion_id,
            relation=ProvenanceRelation.CORRECTS,
            created_at=now,
            producer_id=principal.owner_id,
        )
        target_state = AssertionStateProjection(
            assertion_id=target.assertion_id,
            current_status=AssertionStatus.SUPERSEDED,
            preferred_assertion_id=correction.assertion_id,
            changed_by_record_id=correction.assertion_id,
            changed_at=now,
            version=expected_state.version + 1,
        )
        target_change = AssertionStateChange(
            change_id=self._id_factory("state_change"),
            assertion_id=target.assertion_id,
            previous_status=expected_state.current_status,
            new_status=target_state.current_status,
            preferred_assertion_id=correction.assertion_id,
            changed_by_record_id=correction.assertion_id,
            reason="assertion.owner-corrected",
            changed_at=now,
            version=target_state.version,
        )
        return self._store.apply_correction(
            AssertionCorrectionWrite(
                correction=correction,
                provenance_edge=provenance_edge,
                expected_target_state=expected_state,
                target_state=target_state,
                target_change=target_change,
            )
        )

    def dispute(
        self,
        principal: AuthenticatedOwner,
        assertion_id: RecordId,
        *,
        expected_version: int,
    ) -> AssertionStateTransitionResult:
        return self._transition(
            principal,
            assertion_id,
            expected_version=expected_version,
            status=AssertionStatus.DISPUTED,
            reason="assertion.owner-disputed",
        )

    def retract(
        self,
        principal: AuthenticatedOwner,
        assertion_id: RecordId,
        *,
        expected_version: int,
    ) -> AssertionStateTransitionResult:
        return self._transition(
            principal,
            assertion_id,
            expected_version=expected_version,
            status=AssertionStatus.RETRACTED,
            reason="assertion.owner-retracted",
        )

    def _transition(
        self,
        principal: AuthenticatedOwner,
        assertion_id: RecordId,
        *,
        expected_version: int,
        status: AssertionStatus,
        reason: str,
    ) -> AssertionStateTransitionResult:
        now = self._clock()
        self._require_recent_authentication(principal, now)
        self._owned_assertion(principal, assertion_id)
        self._require_write_mode()
        expected_state = self._store.get_assertion_state(assertion_id)
        if expected_state.version != expected_version:
            raise MemoryConflictError("assertion state changed before transition")
        if expected_state.current_status in {
            status,
            AssertionStatus.SUPERSEDED,
            AssertionStatus.RETRACTED,
        }:
            raise MemoryConflictError("assertion state does not permit this transition")
        state = AssertionStateProjection(
            assertion_id=assertion_id,
            current_status=status,
            changed_by_record_id=principal.owner_id,
            changed_at=now,
            version=expected_state.version + 1,
        )
        change = AssertionStateChange(
            change_id=self._id_factory("state_change"),
            assertion_id=assertion_id,
            previous_status=expected_state.current_status,
            new_status=status,
            changed_by_record_id=principal.owner_id,
            reason=reason,
            changed_at=now,
            version=state.version,
        )
        return self._store.apply_state_transition(
            AssertionStateTransitionWrite(
                expected_state=expected_state,
                state=state,
                change=change,
            )
        )

    def _owned_assertion(
        self,
        principal: AuthenticatedOwner,
        assertion_id: RecordId,
    ) -> Assertion:
        self._require_owner(principal)
        assertion = self._store.get_assertion(assertion_id)
        if assertion.subject_id != principal.owner_id:
            raise MemoryOwnershipError("authenticated principal does not own this memory")
        return assertion

    def _require_owner(self, principal: AuthenticatedOwner) -> None:
        if principal.owner_id != self._owner_id:
            raise MemoryOwnershipError("authenticated principal does not own this runtime")

    @staticmethod
    def _require_recent_authentication(
        principal: AuthenticatedOwner,
        now: datetime,
    ) -> None:
        if now >= principal.reauthenticated_until:
            raise RecentAuthenticationRequired("recent owner authentication required")

    def _require_write_mode(self) -> GuardianMode:
        mode = self._guardian_reader.read_status().payload.mode
        if mode in {GuardianMode.READ_ONLY, GuardianMode.STOPPED, GuardianMode.RECOVERY}:
            raise MemoryUnavailableError(
                f"Guardian mode does not permit memory writes: {mode.value}"
            )
        return mode
