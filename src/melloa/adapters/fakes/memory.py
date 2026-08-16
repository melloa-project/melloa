"""Thread-safe in-memory memory store for synthetic retrieval and corrections."""

from __future__ import annotations

from threading import RLock

from melloa.domain.base import JsonObject, RecordId, canonical_json_bytes, sha256_digest
from melloa.domain.memory import (
    Assertion,
    AssertionContentDeletionTombstone,
    AssertionCorrectionResult,
    AssertionDerivedRebuildWork,
    AssertionMetadata,
    AssertionStateChange,
    AssertionStateProjection,
    AssertionStateTransitionResult,
    AssertionStatus,
    ProvenanceEdge,
)
from melloa.ports.memory import (
    AssertionContentDeletionStoreResult,
    AssertionContentDeletionWrite,
    AssertionContentRetentionInventory,
    AssertionCorrectionWrite,
    AssertionStateTransitionWrite,
    MemoryConflictError,
    MemoryContentDeletedError,
    MemoryNotFoundError,
)

_ASSERTION_RETENTION_POLICY = "memory.assertion-owner-lifecycle"


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
        self._metadata = {
            assertion.assertion_id: self._metadata_from_assertion(assertion)
            for assertion in assertions
        }
        self._contents = {
            assertion.assertion_id: assertion.value for assertion in assertions
        }
        self._content_deletions: dict[RecordId, AssertionContentDeletionTombstone] = {}
        self._deletion_ids: set[RecordId] = set()
        self._rebuild_work: dict[RecordId, AssertionDerivedRebuildWork] = {}
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
            return self._get_assertion_unlocked(assertion_id)

    def get_assertion_metadata(self, assertion_id: RecordId) -> AssertionMetadata:
        with self._lock:
            metadata = self._metadata.get(assertion_id)
            if metadata is None:
                raise MemoryNotFoundError(f"assertion not found: {assertion_id}")
            return metadata

    def get_assertion_content_deletion(
        self,
        assertion_id: RecordId,
    ) -> AssertionContentDeletionTombstone | None:
        with self._lock:
            if assertion_id not in self._metadata:
                raise MemoryNotFoundError(f"assertion not found: {assertion_id}")
            return self._content_deletions.get(assertion_id)

    def list_assertions(self, subject_id: RecordId) -> tuple[Assertion, ...]:
        with self._lock:
            assertions = (
                self._get_assertion_unlocked(assertion.assertion_id).model_copy(
                    update={
                        "status": self._states[assertion.assertion_id].current_status,
                    }
                )
                for assertion in self._metadata.values()
                if assertion.subject_id == subject_id
                and assertion.assertion_id in self._contents
            )
            return tuple(
                sorted(
                    assertions,
                    key=lambda assertion: (assertion.observed_at, assertion.assertion_id),
                )
            )

    def list_assertion_metadata(self, subject_id: RecordId) -> tuple[AssertionMetadata, ...]:
        with self._lock:
            metadata = (
                assertion
                for assertion in self._metadata.values()
                if assertion.subject_id == subject_id
            )
            return tuple(
                sorted(
                    metadata,
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

    def assertion_content_retention_inventory(
        self,
        owner_id: RecordId,
    ) -> AssertionContentRetentionInventory:
        with self._lock:
            retained_assertion_ids = tuple(
                assertion_id
                for assertion_id, metadata in self._metadata.items()
                if metadata.subject_id == owner_id and assertion_id in self._contents
            )
            retained_bytes = sum(
                len(canonical_json_bytes(self._contents[assertion_id]))
                for assertion_id in retained_assertion_ids
            )
            retained_times = tuple(
                self._metadata[assertion_id].observed_at
                for assertion_id in retained_assertion_ids
            )
            return AssertionContentRetentionInventory(
                retained_objects=len(retained_assertion_ids),
                retained_bytes=retained_bytes,
                deletion_receipts=sum(
                    1
                    for tombstone in self._content_deletions.values()
                    if tombstone.owner_id == owner_id
                ),
                oldest_retained_at=min(retained_times) if retained_times else None,
            )

    def apply_correction(
        self,
        write: AssertionCorrectionWrite,
    ) -> AssertionCorrectionResult:
        with self._lock:
            correction = write.correction
            target_id = correction.correction_target_id
            if target_id is None:
                raise MemoryConflictError("correction does not identify a target assertion")
            target = self._get_assertion_unlocked(target_id)
            current_state = self._states[target_id]
            if current_state != write.expected_target_state:
                raise MemoryConflictError("assertion state changed before correction")
            if correction.assertion_id in self._metadata:
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

            self._metadata[correction.assertion_id] = self._metadata_from_assertion(correction)
            self._contents[correction.assertion_id] = correction.value
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
            assertion = self._get_assertion_unlocked(assertion_id)
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

    def delete_assertion_content(
        self,
        write: AssertionContentDeletionWrite,
    ) -> AssertionContentDeletionStoreResult:
        with self._lock:
            metadata = self._metadata.get(write.assertion_id)
            if metadata is None:
                raise MemoryNotFoundError(f"assertion not found: {write.assertion_id}")
            if (
                metadata.subject_id != write.owner_id
                or write.deleted_by_record_id != write.owner_id
            ):
                raise MemoryNotFoundError(f"assertion not found: {write.assertion_id}")
            existing = self._content_deletions.get(write.assertion_id)
            if existing is not None:
                return AssertionContentDeletionStoreResult(
                    tombstone=existing,
                    rebuild_work=self._rebuild_work[existing.rebuild_work_id],
                    created=False,
                )
            value = self._contents.get(write.assertion_id)
            if value is None:
                raise MemoryConflictError("assertion content is absent without deletion evidence")
            if write.tombstone_id in self._deletion_ids:
                raise MemoryConflictError("assertion content tombstone ID conflicts")
            if write.rebuild_work_id in self._rebuild_work:
                raise MemoryConflictError("assertion rebuild work ID conflicts")

            encoded = canonical_json_bytes(value)
            tombstone = AssertionContentDeletionTombstone(
                tombstone_id=write.tombstone_id,
                assertion_id=write.assertion_id,
                owner_id=write.owner_id,
                deleted_by_record_id=write.deleted_by_record_id,
                content_hash=sha256_digest(encoded),
                size_bytes=len(encoded),
                retention_policy=_ASSERTION_RETENTION_POLICY,
                retained_at=metadata.observed_at,
                deleted_at=write.deleted_at,
                reason_code=write.reason_code,
                rebuild_work_id=write.rebuild_work_id,
            )
            rebuild_work = AssertionDerivedRebuildWork(
                work_id=write.rebuild_work_id,
                assertion_id=write.assertion_id,
                tombstone_id=write.tombstone_id,
                requested_by_record_id=write.deleted_by_record_id,
                requested_at=write.deleted_at,
            )
            del self._contents[write.assertion_id]
            self._content_deletions[write.assertion_id] = tombstone
            self._deletion_ids.add(tombstone.tombstone_id)
            self._rebuild_work[rebuild_work.work_id] = rebuild_work
            return AssertionContentDeletionStoreResult(
                tombstone=tombstone,
                rebuild_work=rebuild_work,
                created=True,
            )

    def _get_assertion_unlocked(self, assertion_id: RecordId) -> Assertion:
        metadata = self._metadata.get(assertion_id)
        if metadata is None:
            raise MemoryNotFoundError(f"assertion not found: {assertion_id}")
        value = self._contents.get(assertion_id)
        if value is None:
            if assertion_id in self._content_deletions:
                raise MemoryContentDeletedError(f"assertion content deleted: {assertion_id}")
            raise MemoryNotFoundError(f"assertion content not found: {assertion_id}")
        return self._assertion_from_parts(metadata, value)

    @staticmethod
    def _metadata_from_assertion(assertion: Assertion) -> AssertionMetadata:
        return AssertionMetadata.model_validate(
            assertion.model_dump(mode="python", exclude={"value"})
        )

    @staticmethod
    def _assertion_from_parts(
        metadata: AssertionMetadata,
        value: JsonObject,
    ) -> Assertion:
        document = metadata.model_dump(mode="python")
        document["value"] = value
        return Assertion.model_validate(document)

    @staticmethod
    def _initial_state(assertion: AssertionMetadata) -> AssertionStateProjection:
        return AssertionStateProjection(
            assertion_id=assertion.assertion_id,
            current_status=assertion.status,
            changed_by_record_id=assertion.assertion_id,
            changed_at=assertion.observed_at,
            version=1,
        )

    @staticmethod
    def _initial_change(assertion: AssertionMetadata) -> AssertionStateChange:
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
