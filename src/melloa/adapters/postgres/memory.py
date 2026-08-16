"""PostgreSQL memory adapter for retrieval, inspection, and atomic corrections."""

from __future__ import annotations

from typing import Any, cast

import psycopg
from psycopg.errors import CheckViolation, NoDataFound, SerializationFailure, UniqueViolation
from psycopg.types.json import Jsonb

from melloa.domain.base import JsonObject, RecordId, canonical_json_bytes
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
    ProvenanceRelation,
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


class PostgresMemoryRepository:
    def __init__(self, connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        self._connection = connection

    def get_assertion(self, assertion_id: RecordId) -> Assertion:
        row = self._connection.execute(
            """
            SELECT assertion.document, content.value
              FROM melloa.assertions AS assertion
              LEFT JOIN melloa.assertion_contents AS content
                ON content.assertion_id = assertion.assertion_id
             WHERE assertion.assertion_id = %s
            """,
            (assertion_id,),
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError(f"assertion not found: {assertion_id}")
        if row[1] is None:
            if self.get_assertion_content_deletion(assertion_id) is not None:
                raise MemoryContentDeletedError(
                    f"assertion content deleted: {assertion_id}"
                )
            raise MemoryNotFoundError(f"assertion content not found: {assertion_id}")
        return self._parse_assertion(row[0], row[1])

    def get_assertion_metadata(self, assertion_id: RecordId) -> AssertionMetadata:
        row = self._connection.execute(
            "SELECT document FROM melloa.assertions WHERE assertion_id = %s",
            (assertion_id,),
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError(f"assertion not found: {assertion_id}")
        return self._parse_metadata(row[0])

    def get_assertion_content_deletion(
        self,
        assertion_id: RecordId,
    ) -> AssertionContentDeletionTombstone | None:
        self.get_assertion_metadata(assertion_id)
        row = self._connection.execute(
            """
            SELECT document
              FROM melloa.assertion_content_deletions
             WHERE assertion_id = %s
            """,
            (assertion_id,),
        ).fetchone()
        if row is None:
            return None
        return self._parse_deletion(row[0])

    def list_assertions(self, subject_id: RecordId) -> tuple[Assertion, ...]:
        rows = self._connection.execute(
            """
            SELECT assertion.document, content.value, current.current_status
              FROM melloa.assertions AS assertion
              JOIN melloa.assertion_contents AS content
                ON content.assertion_id = assertion.assertion_id
              LEFT JOIN melloa.assertion_current_state AS current
                ON current.assertion_id = assertion.assertion_id
             WHERE assertion.subject_id = %s
             ORDER BY assertion.observed_at, assertion.assertion_id
            """,
            (subject_id,),
        ).fetchall()
        assertions: list[Assertion] = []
        for document, value, current_status in rows:
            projected = self._assertion_document(document, value)
            if current_status is not None:
                projected["status"] = str(current_status)
            assertions.append(
                Assertion.model_validate_json(canonical_json_bytes(projected))
            )
        return tuple(assertions)

    def list_assertion_metadata(self, subject_id: RecordId) -> tuple[AssertionMetadata, ...]:
        rows = self._connection.execute(
            """
            SELECT document
              FROM melloa.assertions
             WHERE subject_id = %s
             ORDER BY observed_at, assertion_id
            """,
            (subject_id,),
        ).fetchall()
        return tuple(self._parse_metadata(row[0]) for row in rows)

    def list_provenance_edges(
        self,
        record_ids: frozenset[RecordId],
    ) -> tuple[ProvenanceEdge, ...]:
        if not record_ids:
            return ()
        identifiers = list(record_ids)
        rows = self._connection.execute(
            """
            SELECT edge_id, from_id, to_id, relation, created_at, producer_id, metadata
              FROM melloa.provenance_edges
             WHERE from_id = ANY(%s::text[])
                OR to_id = ANY(%s::text[])
             ORDER BY created_at, edge_id
            """,
            (identifiers, identifiers),
        ).fetchall()
        return tuple(
            ProvenanceEdge(
                edge_id=str(edge_id),
                from_id=str(from_id),
                to_id=str(to_id),
                relation=ProvenanceRelation(str(relation)),
                created_at=created_at,
                producer_id=str(producer_id),
                metadata=cast(JsonObject, metadata),
            )
            for edge_id, from_id, to_id, relation, created_at, producer_id, metadata in rows
        )

    def get_assertion_state(self, assertion_id: RecordId) -> AssertionStateProjection:
        row = self._connection.execute(
            "SELECT document FROM melloa.assertion_current_state WHERE assertion_id = %s",
            (assertion_id,),
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError(f"assertion state not found: {assertion_id}")
        return self._parse_state(row[0])

    def list_assertion_state_changes(
        self,
        assertion_id: RecordId,
    ) -> tuple[AssertionStateChange, ...]:
        rows = self._connection.execute(
            """
            SELECT document
              FROM melloa.assertion_state_changes
             WHERE assertion_id = %s
             ORDER BY version
            """,
            (assertion_id,),
        ).fetchall()
        if not rows:
            if self._connection.execute(
                "SELECT 1 FROM melloa.assertions WHERE assertion_id = %s",
                (assertion_id,),
            ).fetchone() is None:
                raise MemoryNotFoundError(
                    f"assertion state history not found: {assertion_id}"
                )
        return tuple(self._parse_change(row[0]) for row in rows)

    def assertion_content_retention_inventory(
        self,
        owner_id: RecordId,
    ) -> AssertionContentRetentionInventory:
        row = self._connection.execute(
            """
            WITH retained AS (
                SELECT content.size_bytes, content.retained_at
                  FROM melloa.assertions AS assertion
                  JOIN melloa.assertion_contents AS content
                    ON content.assertion_id = assertion.assertion_id
                 WHERE assertion.subject_id = %s
            ),
            deleted AS (
                SELECT tombstone_id
                  FROM melloa.assertion_content_deletions
                 WHERE owner_id = %s
            )
            SELECT (SELECT count(*) FROM retained),
                   COALESCE((SELECT sum(size_bytes) FROM retained), 0),
                   (SELECT min(retained_at) FROM retained),
                   (SELECT count(*) FROM deleted)
            """,
            (owner_id, owner_id),
        ).fetchone()
        if row is None:
            return AssertionContentRetentionInventory(
                retained_objects=0,
                retained_bytes=0,
                deletion_receipts=0,
                oldest_retained_at=None,
            )
        return AssertionContentRetentionInventory(
            retained_objects=int(row[0]),
            retained_bytes=int(row[1]),
            oldest_retained_at=row[2],
            deletion_receipts=int(row[3]),
        )

    def apply_correction(
        self,
        write: AssertionCorrectionWrite,
    ) -> AssertionCorrectionResult:
        try:
            with self._connection.transaction():
                correction = write.correction
                target_id = correction.correction_target_id
                if target_id is None:
                    raise MemoryConflictError("correction does not identify a target assertion")
                target = self.get_assertion(target_id)
                current_state = self.get_assertion_state(target_id)
                if current_state != write.expected_target_state:
                    raise MemoryConflictError("assertion state changed before correction")
                self._validate_transition(write, target, current_state)
                correction_state = self._initial_state(correction)
                result = AssertionCorrectionResult(
                    correction=correction,
                    provenance_edge=write.provenance_edge,
                    target_state=write.target_state,
                    correction_state=correction_state,
                    target_change=write.target_change,
                )
                self._insert_assertion(correction)
                self._insert_provenance_edge(write.provenance_edge)
                self._persist_state_transition(
                    write.expected_target_state,
                    write.target_state,
                    write.target_change,
                )
                if (
                    self.get_assertion_state(target_id) != write.target_state
                    or self.get_assertion_state(correction.assertion_id) != correction_state
                    or self.list_assertion_state_changes(target_id)[-1]
                    != write.target_change
                ):
                    raise MemoryConflictError("persisted correction state does not match its write")
                return result
        except (SerializationFailure, UniqueViolation) as error:
            raise MemoryConflictError("correction conflicts with durable memory state") from error

    def apply_state_transition(
        self,
        write: AssertionStateTransitionWrite,
    ) -> AssertionStateTransitionResult:
        try:
            with self._connection.transaction():
                assertion = self.get_assertion(write.expected_state.assertion_id)
                current_state = self.get_assertion_state(assertion.assertion_id)
                if current_state != write.expected_state:
                    raise MemoryConflictError("assertion state changed before transition")
                self._validate_state_transition(
                    write.expected_state,
                    write.state,
                    write.change,
                )
                result = AssertionStateTransitionResult(
                    assertion=assertion,
                    current_state=write.state,
                    state_change=write.change,
                )
                self._persist_state_transition(
                    write.expected_state,
                    write.state,
                    write.change,
                )
                if (
                    self.get_assertion_state(assertion.assertion_id) != write.state
                    or self.list_assertion_state_changes(assertion.assertion_id)[-1]
                    != write.change
                ):
                    raise MemoryConflictError(
                        "persisted assertion state does not match its transition"
                    )
                return result
        except (SerializationFailure, UniqueViolation) as error:
            raise MemoryConflictError("transition conflicts with durable memory state") from error

    def delete_assertion_content(
        self,
        write: AssertionContentDeletionWrite,
    ) -> AssertionContentDeletionStoreResult:
        try:
            with self._connection.transaction():
                row = self._connection.execute(
                    """
                    SELECT tombstone_document, rebuild_work_document, created
                      FROM melloa.delete_assertion_content(
                        %(assertion_id)s,
                        %(owner_id)s,
                        %(tombstone_id)s,
                        %(rebuild_work_id)s,
                        %(deleted_by_record_id)s,
                        %(deleted_at)s,
                        %(reason_code)s
                      )
                    """,
                    {
                        "assertion_id": write.assertion_id,
                        "owner_id": write.owner_id,
                        "tombstone_id": write.tombstone_id,
                        "rebuild_work_id": write.rebuild_work_id,
                        "deleted_by_record_id": write.deleted_by_record_id,
                        "deleted_at": write.deleted_at,
                        "reason_code": write.reason_code,
                    },
                ).fetchone()
                if row is None:
                    raise MemoryConflictError("assertion content deletion returned no result")
                return AssertionContentDeletionStoreResult(
                    tombstone=self._parse_deletion(row[0]),
                    rebuild_work=self._parse_rebuild_work(row[1]),
                    created=bool(row[2]),
                )
        except NoDataFound as error:
            raise MemoryNotFoundError(f"assertion not found: {write.assertion_id}") from error
        except (CheckViolation, SerializationFailure, UniqueViolation) as error:
            raise MemoryConflictError(
                "assertion content deletion conflicts with durable memory state"
            ) from error

    def _insert_assertion(self, assertion: Assertion) -> None:
        self._connection.execute(
            """
            SELECT melloa.append_assertion(
                %(document)s::jsonb,
                %(retention_policy)s::text,
                %(retained_at)s::timestamptz,
                %(expires_at)s::timestamptz
            )
            """,
            {
                "document": Jsonb(assertion.model_dump(mode="json")),
                "retention_policy": _ASSERTION_RETENTION_POLICY,
                "retained_at": assertion.observed_at,
                "expires_at": None,
            },
        )

    def _insert_provenance_edge(self, edge: ProvenanceEdge) -> None:
        self._connection.execute(
            """
            INSERT INTO melloa.provenance_edges (
                edge_id, from_id, to_id, relation, producer_id, created_at, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                edge.edge_id,
                edge.from_id,
                edge.to_id,
                edge.relation.value,
                edge.producer_id,
                edge.created_at,
                Jsonb(edge.metadata),
            ),
        )

    def _persist_state_transition(
        self,
        expected: AssertionStateProjection,
        state: AssertionStateProjection,
        change: AssertionStateChange,
    ) -> None:
        self._connection.execute(
            """
            SELECT melloa.transition_assertion_state(
                %(change_id)s, %(assertion_id)s, %(expected_version)s,
                %(previous_status)s, %(new_status)s, %(preferred_assertion_id)s,
                %(changed_by_record_id)s, %(reason)s, %(changed_at)s,
                %(projection_document)s, %(change_document)s
            )
            """,
            {
                "change_id": change.change_id,
                "assertion_id": state.assertion_id,
                "expected_version": expected.version,
                "previous_status": expected.current_status.value,
                "new_status": state.current_status.value,
                "preferred_assertion_id": state.preferred_assertion_id,
                "changed_by_record_id": state.changed_by_record_id,
                "reason": change.reason,
                "changed_at": state.changed_at,
                "projection_document": Jsonb(state.model_dump(mode="json")),
                "change_document": Jsonb(change.model_dump(mode="json")),
            },
        )

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
        PostgresMemoryRepository._validate_state_transition(
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

    @staticmethod
    def _assertion_document(document: object, value: object) -> JsonObject:
        if not isinstance(document, dict):
            raise ValueError("persisted assertion document is not an object")
        if "value" in document:
            raise ValueError("persisted assertion metadata contains content")
        if not isinstance(value, dict):
            raise ValueError("persisted assertion content is not an object")
        combined = cast(JsonObject, document.copy())
        combined["value"] = cast(JsonObject, value)
        return combined

    @classmethod
    def _parse_assertion(cls, document: object, value: object) -> Assertion:
        return Assertion.model_validate_json(
            canonical_json_bytes(cls._assertion_document(document, value))
        )

    @staticmethod
    def _parse_metadata(document: object) -> AssertionMetadata:
        if not isinstance(document, dict):
            raise ValueError("persisted assertion metadata document is not an object")
        if "value" in document:
            raise ValueError("persisted assertion metadata contains content")
        return AssertionMetadata.model_validate_json(
            canonical_json_bytes(cast(JsonObject, document))
        )

    @staticmethod
    def _parse_state(document: object) -> AssertionStateProjection:
        if not isinstance(document, dict):
            raise ValueError("persisted assertion state document is not an object")
        return AssertionStateProjection.model_validate_json(
            canonical_json_bytes(cast(JsonObject, document))
        )

    @staticmethod
    def _parse_change(document: object) -> AssertionStateChange:
        if not isinstance(document, dict):
            raise ValueError("persisted assertion state change document is not an object")
        return AssertionStateChange.model_validate_json(
            canonical_json_bytes(cast(JsonObject, document))
        )

    @staticmethod
    def _parse_deletion(document: object) -> AssertionContentDeletionTombstone:
        if not isinstance(document, dict):
            raise ValueError("persisted assertion deletion document is not an object")
        return AssertionContentDeletionTombstone.model_validate_json(
            canonical_json_bytes(cast(JsonObject, document))
        )

    @staticmethod
    def _parse_rebuild_work(document: object) -> AssertionDerivedRebuildWork:
        if not isinstance(document, dict):
            raise ValueError("persisted assertion rebuild document is not an object")
        return AssertionDerivedRebuildWork.model_validate_json(
            canonical_json_bytes(cast(JsonObject, document))
        )
