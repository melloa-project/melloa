"""Thread-safe in-memory memory store for synthetic retrieval and corrections."""

from __future__ import annotations

from threading import RLock

from melloa.domain.base import RecordId, sha256_digest
from melloa.domain.memory import (
    Assertion,
    AssertionCorrectionResult,
    AssertionStateChange,
    AssertionStateProjection,
    AssertionStateTransitionResult,
    AssertionStatus,
    ProvenanceEdge,
)
from melloa.ports.memory import (
    AssertionCorrectionWrite,
    AssertionStateTransitionWrite,
    MemoryConflictError,
    MemoryNotFoundError,
)


class InMemoryMemoryRepository:
    def __init__(
        self,
        assertions: tuple[Assertion, ...] = (),
        provenance_edges: tuple[ProvenanceEdge, ...] = (),
    ) -> None:
        if len({assertion.assertion_id for assertion in assertions}) != len(assertions):
            raise ValueError("assertion IDs must be unique")
        if len({edge.edge_id for edge in provenance_edges}) != len(provenance_edges):
            raise ValueError("provenance edge IDs must be unique")
        self._lock = RLock()
        self._assertions = {assertion.assertion_id: assertion for assertion in assertions}
        self._edges = {edge.edge_id: edge for edge in provenance_edges}
        self._states = {
            assertion.assertion_id: self._initial_state(assertion)
            for assertion in assertions
        }
        initial_changes = {
            assertion.assertion_id: self._initial_change(assertion)
            for assertion in assertions
        }
        self._state_changes = {
            assertion_id: [change]
            for assertion_id, change in initial_changes.items()
        }
        self._change_ids = {
            change.change_id for change in initial_changes.values()
        }
        if len(self._change_ids) != len(initial_changes):
            raise ValueError("initial assertion state change IDs must be unique")

    def get_assertion(self, assertion_id: RecordId) -> Assertion:
        with self._lock:
            assertion = self._assertions.get(assertion_id)
            if assertion is None:
                raise MemoryNotFoundError(f"assertion not found: {assertion_id}")
            return assertion

    def list_assertions(self, subject_id: RecordId) -> tuple[Assertion, ...]:
        with self._lock:
            assertions = (
                assertion.model_copy(
                    update={
                        "status": self._states[assertion.assertion_id].current_status,
                    }
                )
                for assertion in self._assertions.values()
                if assertion.subject_id == subject_id
            )
            return tuple(
                sorted(
                    assertions,
                    key=lambda assertion: (assertion.observed_at, assertion.assertion_id),
                )
            )

    def list_provenance_edges(
        self,
        record_ids: frozenset[RecordId],
    ) -> tuple[ProvenanceEdge, ...]:
        with self._lock:
            edges = (
                edge
                for edge in self._edges.values()
                if edge.from_id in record_ids or edge.to_id in record_ids
            )
            return tuple(sorted(edges, key=lambda edge: (edge.created_at, edge.edge_id)))

    def get_assertion_state(self, assertion_id: RecordId) -> AssertionStateProjection:
        with self._lock:
            state = self._states.get(assertion_id)
            if state is None:
                raise MemoryNotFoundError(f"assertion state not found: {assertion_id}")
            return state

    def list_assertion_state_changes(
        self,
        assertion_id: RecordId,
    ) -> tuple[AssertionStateChange, ...]:
        with self._lock:
            changes = self._state_changes.get(assertion_id)
            if changes is None:
                raise MemoryNotFoundError(f"assertion state history not found: {assertion_id}")
            return tuple(changes)

    def apply_correction(
        self,
        write: AssertionCorrectionWrite,
    ) -> AssertionCorrectionResult:
        with self._lock:
            correction = write.correction
            target_id = correction.correction_target_id
            if target_id is None:
                raise MemoryConflictError("correction does not identify a target assertion")
            target = self._assertions.get(target_id)
            if target is None:
                raise MemoryNotFoundError(f"correction target not found: {target_id}")
            current_state = self._states[target_id]
            if current_state != write.expected_target_state:
                raise MemoryConflictError("assertion state changed before correction")
            if correction.assertion_id in self._assertions:
                raise MemoryConflictError(
                    f"assertion ID conflicts with immutable data: {correction.assertion_id}"
                )
            if write.provenance_edge.edge_id in self._edges:
                raise MemoryConflictError(
                    "provenance edge ID conflicts with immutable data: "
                    f"{write.provenance_edge.edge_id}"
                )
            correction_state = self._initial_state(correction)
            correction_change = self._initial_change(correction)
            if (
                write.target_change.change_id in self._change_ids
                or correction_change.change_id in self._change_ids
            ):
                raise MemoryConflictError("assertion state change ID conflicts with immutable data")
            self._validate_transition(write, target, current_state)
            result = AssertionCorrectionResult(
                correction=correction,
                provenance_edge=write.provenance_edge,
                target_state=write.target_state,
                correction_state=correction_state,
                target_change=write.target_change,
            )

            self._assertions[correction.assertion_id] = correction
            self._edges[write.provenance_edge.edge_id] = write.provenance_edge
            self._states[target_id] = write.target_state
            self._states[correction.assertion_id] = correction_state
            self._state_changes[target_id].append(write.target_change)
            self._state_changes[correction.assertion_id] = [correction_change]
            self._change_ids.update(
                (write.target_change.change_id, correction_change.change_id)
            )
            return result

    def apply_state_transition(
        self,
        write: AssertionStateTransitionWrite,
    ) -> AssertionStateTransitionResult:
        with self._lock:
            assertion_id = write.expected_state.assertion_id
            assertion = self._assertions.get(assertion_id)
            if assertion is None:
                raise MemoryNotFoundError(f"assertion not found: {assertion_id}")
            current_state = self._states[assertion_id]
            if current_state != write.expected_state:
                raise MemoryConflictError("assertion state changed before transition")
            if write.change.change_id in self._change_ids:
                raise MemoryConflictError("assertion state change ID conflicts with immutable data")
            self._validate_state_transition(write.expected_state, write.state, write.change)
            result = AssertionStateTransitionResult(
                assertion=assertion,
                current_state=write.state,
                state_change=write.change,
            )
            self._states[assertion_id] = write.state
            self._state_changes[assertion_id].append(write.change)
            self._change_ids.add(write.change.change_id)
            return result

    @staticmethod
    def _initial_state(assertion: Assertion) -> AssertionStateProjection:
        return AssertionStateProjection(
            assertion_id=assertion.assertion_id,
            current_status=assertion.status,
            changed_by_record_id=assertion.assertion_id,
            changed_at=assertion.observed_at,
            version=1,
        )

    @staticmethod
    def _initial_change(assertion: Assertion) -> AssertionStateChange:
        digest = sha256_digest(f"{assertion.assertion_id}:initial".encode())
        return AssertionStateChange(
            change_id=f"state_change_{digest.removeprefix('sha256:')[:32]}",
            assertion_id=assertion.assertion_id,
            previous_status=None,
            new_status=assertion.status,
            changed_by_record_id=assertion.assertion_id,
            reason="assertion.initialized",
            changed_at=assertion.observed_at,
            version=1,
        )

    @staticmethod
    def _validate_transition(
        write: AssertionCorrectionWrite,
        target: Assertion,
        current_state: AssertionStateProjection,
    ) -> None:
        correction = write.correction
        target_state = write.target_state
        change = write.target_change
        if (
            correction.subject_id != target.subject_id
            or correction.predicate != target.predicate
            or correction.valid_from != target.valid_from
            or correction.valid_to != target.valid_to
            or correction.sensitivity is not target.sensitivity
        ):
            raise MemoryConflictError("correction does not preserve the target assertion scope")
        InMemoryMemoryRepository._validate_state_transition(
            current_state,
            target_state,
            change,
        )
        if (
            target_state.current_status is not AssertionStatus.SUPERSEDED
            or target_state.preferred_assertion_id != correction.assertion_id
            or target_state.changed_by_record_id != correction.assertion_id
        ):
            raise MemoryConflictError("correction state transition is inconsistent")

    @staticmethod
    def _validate_state_transition(
        expected: AssertionStateProjection,
        state: AssertionStateProjection,
        change: AssertionStateChange,
    ) -> None:
        if (
            state.assertion_id != expected.assertion_id
            or state.version != expected.version + 1
            or change.assertion_id != expected.assertion_id
            or change.previous_status is not expected.current_status
            or change.new_status is not state.current_status
            or change.preferred_assertion_id != state.preferred_assertion_id
            or change.changed_by_record_id != state.changed_by_record_id
            or change.changed_at != state.changed_at
            or change.version != state.version
        ):
            raise MemoryConflictError("assertion state transition is inconsistent")
