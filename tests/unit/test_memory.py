from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.application.memory import (
    MemoryOwnershipError,
    MemoryService,
    MemoryUnavailableError,
)
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import (
    Assertion,
    AssertionContentState,
    AssertionMetadata,
    AssertionStatus,
    ProvenanceEdge,
    ProvenanceRelation,
)
from melloa.domain.retention import BackupExpiryDisclosure, BackupExpiryState
from melloa.ports.auth import RecentAuthenticationRequired
from melloa.ports.memory import (
    MemoryConflictError,
    MemoryContentDeletedError,
    MemoryNotFoundError,
)
from tests.conftest import record_id


class _FailFirstAuditStore(InMemoryEventAuditStore):
    def __init__(self) -> None:
        super().__init__()
        self._failed = False

    def append_event(self, event, audit):
        if not self._failed:
            self._failed = True
            raise RuntimeError("synthetic audit outage")
        return super().append_event(event, audit)


def _assertion(
    fixed_time: datetime,
    *,
    assertion_id: RecordId | None = None,
    subject_id: RecordId | None = None,
) -> Assertion:
    return Assertion(
        assertion_id=assertion_id or record_id("assertion", 1),
        subject_id=subject_id or record_id("owner", 1),
        predicate="activity.current",
        value={"activity": "sleeping"},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.61,
        source_authority=TrustLabel.MODEL_GENERATED,
        sensitivity=Sensitivity.SENSITIVE,
        observed_at=fixed_time,
        valid_from=fixed_time - timedelta(hours=1),
        valid_to=fixed_time + timedelta(hours=1),
    )


def _principal(
    fixed_time: datetime,
    *,
    owner_id: RecordId | None = None,
    recent_for: timedelta = timedelta(minutes=5),
) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=owner_id or record_id("owner", 1),
        session_id=record_id("session", 1),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + recent_for,
        expires_at=fixed_time + timedelta(minutes=30),
    )


def _guardian(
    fixed_time: datetime,
    mode: GuardianMode = GuardianMode.NO_ACTIONS,
) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="synthetic-guardian",
            mode=mode,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def _id_factory(**identifiers: RecordId) -> Callable[[str], str]:
    def create(prefix: str) -> str:
        return identifiers[prefix]

    return create


def test_memory_service_appends_correction_without_mutating_original(fixed_time) -> None:
    original = _assertion(fixed_time)
    repository = InMemoryMemoryRepository((original,))
    correction_time = fixed_time + timedelta(minutes=2)
    service = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        clock=lambda: correction_time,
        id_factory=_id_factory(
            assertion=record_id("assertion", 2),
            edge=record_id("edge", 1),
            state_change=record_id("state_change", 2),
        ),
    )
    principal = _principal(fixed_time)

    initial = service.inspect(principal, original.assertion_id)
    assert initial.content_state is AssertionContentState.RETAINED
    assert initial.assertion == original
    assert initial.current_state.current_status is AssertionStatus.ACTIVE
    assert initial.current_state.version == 1
    assert initial.state_changes[0].reason == "assertion.initialized"

    result = service.correct(
        principal,
        original.assertion_id,
        value={"activity": "reading"},
        expected_version=1,
    )

    assert repository.get_assertion(original.assertion_id) == original
    assert result.correction.subject_id == original.subject_id
    assert result.correction.predicate == original.predicate
    assert result.correction.valid_from == original.valid_from
    assert result.correction.valid_to == original.valid_to
    assert result.correction.value == {"activity": "reading"}
    assert result.correction.epistemic_status is EpistemicStatus.CORRECTION
    assert result.correction.status is AssertionStatus.CONFIRMED
    assert result.correction.confidence == 1.0
    assert result.correction.source_authority is TrustLabel.OWNER_AUTHORED
    assert result.provenance_edge.relation is ProvenanceRelation.CORRECTS
    assert result.provenance_edge.producer_id == principal.owner_id
    assert result.target_state.current_status is AssertionStatus.SUPERSEDED
    assert result.target_state.preferred_assertion_id == result.correction.assertion_id
    assert result.target_state.version == 2
    assert result.correction_state.current_status is AssertionStatus.CONFIRMED
    assert result.correction_state.version == 1

    projected = {
        assertion.assertion_id: assertion
        for assertion in repository.list_assertions(original.subject_id)
    }
    assert projected[original.assertion_id].status is AssertionStatus.SUPERSEDED
    assert projected[result.correction.assertion_id].status is AssertionStatus.CONFIRMED
    inspection = service.inspect(principal, original.assertion_id)
    assert inspection.current_state == result.target_state
    assert inspection.state_changes[-1] == result.target_change
    assert inspection.provenance_edges == (result.provenance_edge,)
    correction_inspection = service.inspect(principal, result.correction.assertion_id)
    assert correction_inspection.assertion == result.correction
    assert correction_inspection.current_state == result.correction_state
    assert correction_inspection.provenance_edges == (result.provenance_edge,)


def test_memory_correction_rejects_stale_version_without_partial_write(fixed_time) -> None:
    original = _assertion(fixed_time)
    conflicting_edge = ProvenanceEdge(
        edge_id=record_id("edge", 1),
        from_id=original.assertion_id,
        to_id=record_id("event", 1),
        relation=ProvenanceRelation.DERIVED_FROM,
        created_at=fixed_time,
        producer_id=record_id("intelligence", 1),
    )
    repository = InMemoryMemoryRepository((original,), (conflicting_edge,))
    service = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        clock=lambda: fixed_time + timedelta(minutes=1),
        id_factory=_id_factory(
            assertion=record_id("assertion", 2),
            edge=conflicting_edge.edge_id,
            state_change=record_id("state_change", 2),
        ),
    )

    with pytest.raises(MemoryConflictError, match="edge ID"):
        service.correct(
            _principal(fixed_time),
            original.assertion_id,
            value={"activity": "reading"},
            expected_version=1,
        )

    assert repository.list_assertions(original.subject_id) == (original,)
    assert repository.get_assertion_state(original.assertion_id).version == 1
    assert len(repository.list_assertion_state_changes(original.assertion_id)) == 1
    with pytest.raises(MemoryNotFoundError):
        repository.get_assertion(record_id("assertion", 2))

    successful = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        clock=lambda: fixed_time + timedelta(minutes=2),
        id_factory=_id_factory(
            assertion=record_id("assertion", 3),
            edge=record_id("edge", 2),
            state_change=record_id("state_change", 3),
        ),
    )
    successful.correct(
        _principal(fixed_time),
        original.assertion_id,
        value={"activity": "reading"},
        expected_version=1,
    )
    with pytest.raises(MemoryConflictError, match="changed before correction"):
        successful.correct(
            _principal(fixed_time),
            original.assertion_id,
            value={"activity": "walking"},
            expected_version=1,
        )
    assert len(repository.list_assertions(original.subject_id)) == 2
    assert repository.get_assertion_state(original.assertion_id).version == 2
    assert len(repository.list_assertion_state_changes(original.assertion_id)) == 2


def test_memory_service_enforces_owner_recent_auth_and_guardian(fixed_time) -> None:
    original = _assertion(fixed_time)
    repository = InMemoryMemoryRepository((original,))
    identifiers = _id_factory(
        assertion=record_id("assertion", 2),
        edge=record_id("edge", 1),
        state_change=record_id("state_change", 2),
    )
    service = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        clock=lambda: fixed_time + timedelta(minutes=5),
        id_factory=identifiers,
    )

    with pytest.raises(RecentAuthenticationRequired):
        service.correct(
            _principal(fixed_time),
            original.assertion_id,
            value={"activity": "reading"},
            expected_version=1,
        )
    with pytest.raises(RecentAuthenticationRequired):
        service.delete_content(_principal(fixed_time), original.assertion_id)
    with pytest.raises(MemoryOwnershipError):
        service.inspect(
            _principal(fixed_time, owner_id=record_id("owner", 2)),
            original.assertion_id,
        )

    foreign = _assertion(
        fixed_time,
        assertion_id=record_id("assertion", 2),
        subject_id=record_id("owner", 2),
    )
    foreign_service = MemoryService(
        owner_id=original.subject_id,
        store=InMemoryMemoryRepository((foreign,)),
        guardian_reader=_guardian(fixed_time),
        clock=lambda: fixed_time,
        id_factory=identifiers,
    )
    with pytest.raises(MemoryOwnershipError):
        foreign_service.inspect(_principal(fixed_time), foreign.assertion_id)
    with pytest.raises(MemoryOwnershipError):
        foreign_service.delete_content(_principal(fixed_time), foreign.assertion_id)

    read_only = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time, GuardianMode.READ_ONLY),
        clock=lambda: fixed_time + timedelta(minutes=1),
        id_factory=identifiers,
    )
    with pytest.raises(MemoryUnavailableError, match="read-only"):
        read_only.correct(
            _principal(fixed_time),
            original.assertion_id,
            value={"activity": "reading"},
            expected_version=1,
        )
    with pytest.raises(MemoryUnavailableError, match="read-only"):
        read_only.delete_content(_principal(fixed_time), original.assertion_id)
    assert repository.get_assertion(original.assertion_id) == original
    assert repository.get_assertion_state(original.assertion_id).version == 1


def test_memory_service_appends_dispute_and_retraction_history(fixed_time) -> None:
    original = _assertion(fixed_time)
    repository = InMemoryMemoryRepository((original,))
    principal = _principal(fixed_time)
    disputed_at = fixed_time + timedelta(minutes=1)
    dispute = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        clock=lambda: disputed_at,
        id_factory=_id_factory(state_change=record_id("state_change", 2)),
    ).dispute(
        principal,
        original.assertion_id,
        expected_version=1,
    )

    assert dispute.assertion == original
    assert repository.get_assertion(original.assertion_id) == original
    assert dispute.current_state.current_status is AssertionStatus.DISPUTED
    assert dispute.current_state.changed_by_record_id == principal.owner_id
    assert dispute.current_state.version == 2
    assert dispute.state_change.previous_status is AssertionStatus.ACTIVE
    assert dispute.state_change.reason == "assertion.owner-disputed"
    assert repository.list_assertions(original.subject_id)[0].status is (
        AssertionStatus.DISPUTED
    )
    assert repository.list_assertion_state_changes(original.assertion_id)[-1] == (
        dispute.state_change
    )

    with pytest.raises(MemoryConflictError, match="does not permit"):
        MemoryService(
            owner_id=original.subject_id,
            store=repository,
            guardian_reader=_guardian(fixed_time),
            clock=lambda: disputed_at,
            id_factory=_id_factory(state_change=record_id("state_change", 3)),
        ).dispute(
            principal,
            original.assertion_id,
            expected_version=2,
        )

    duplicate_change = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        clock=lambda: fixed_time + timedelta(minutes=2),
        id_factory=_id_factory(state_change=dispute.state_change.change_id),
    )
    with pytest.raises(MemoryConflictError, match="change ID"):
        duplicate_change.retract(
            principal,
            original.assertion_id,
            expected_version=2,
        )
    assert repository.get_assertion_state(original.assertion_id) == dispute.current_state
    assert len(repository.list_assertion_state_changes(original.assertion_id)) == 2

    retracted_at = fixed_time + timedelta(minutes=3)
    retraction = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        clock=lambda: retracted_at,
        id_factory=_id_factory(state_change=record_id("state_change", 3)),
    ).retract(
        principal,
        original.assertion_id,
        expected_version=2,
    )
    assert retraction.current_state.current_status is AssertionStatus.RETRACTED
    assert retraction.current_state.version == 3
    assert retraction.state_change.previous_status is AssertionStatus.DISPUTED
    assert retraction.state_change.reason == "assertion.owner-retracted"
    assert len(repository.list_assertion_state_changes(original.assertion_id)) == 3
    with pytest.raises(MemoryConflictError, match="does not permit"):
        MemoryService(
            owner_id=original.subject_id,
            store=repository,
            guardian_reader=_guardian(fixed_time),
            clock=lambda: retracted_at,
            id_factory=_id_factory(state_change=record_id("state_change", 4)),
        ).dispute(
            principal,
            original.assertion_id,
            expected_version=3,
        )


def test_memory_service_deletes_only_content_and_preserves_inspection(fixed_time) -> None:
    original = _assertion(fixed_time)
    evidence = ProvenanceEdge(
        edge_id=record_id("edge", 1),
        from_id=original.assertion_id,
        to_id=record_id("event", 1),
        relation=ProvenanceRelation.DERIVED_FROM,
        created_at=fixed_time,
        producer_id=record_id("intelligence", 1),
    )
    repository = InMemoryMemoryRepository((original,), (evidence,))
    backup_expiry = BackupExpiryDisclosure(
        state=BackupExpiryState.NOT_CONFIGURED,
        status_reason="retention.backup.not_configured",
    )
    deleted_at = fixed_time + timedelta(minutes=2)
    service = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        backup_expiry=backup_expiry,
        clock=lambda: deleted_at,
        id_factory=_id_factory(
            deletion=record_id("deletion", 1),
            work=record_id("work", 1),
        ),
    )
    principal = _principal(fixed_time)

    result = service.delete_content(principal, original.assertion_id)

    assert result.created is True
    assert type(result.assertion) is AssertionMetadata
    assert result.assertion.assertion_id == original.assertion_id
    assert "value" not in result.assertion.model_dump()
    assert result.current_state.current_status is AssertionStatus.ACTIVE
    assert result.tombstone.owner_id == principal.owner_id
    assert result.tombstone.deleted_by_record_id == principal.owner_id
    assert result.tombstone.deleted_at == deleted_at
    assert result.tombstone.reason_code == "memory.assertion-content-owner-deleted"
    assert result.tombstone.size_bytes > 0
    assert result.tombstone.rebuild_work_id == result.rebuild_work.work_id
    assert result.rebuild_work.tombstone_id == result.tombstone.tombstone_id
    assert result.backup_expiry == backup_expiry
    with pytest.raises(MemoryContentDeletedError):
        repository.get_assertion(original.assertion_id)
    assert repository.list_assertions(original.subject_id) == ()

    inspection = service.inspect(principal, original.assertion_id)
    assert inspection.content_state is AssertionContentState.DELETED
    assert type(inspection.assertion) is AssertionMetadata
    assert "value" not in inspection.assertion.model_dump()
    assert inspection.deletion_tombstone == result.tombstone
    assert inspection.backup_expiry == backup_expiry
    assert inspection.current_state == result.current_state
    assert inspection.provenance_edges == (evidence,)
    assert inspection.state_changes[0].reason == "assertion.initialized"

    repeated = service.delete_content(principal, original.assertion_id)
    assert repeated.created is False
    assert repeated.tombstone == result.tombstone
    assert repeated.rebuild_work == result.rebuild_work
    with pytest.raises(MemoryContentDeletedError):
        service.retract(principal, original.assertion_id, expected_version=1)
    with pytest.raises(MemoryContentDeletedError):
        service.correct(
            principal,
            original.assertion_id,
            value={"activity": "reading"},
            expected_version=1,
        )


def test_memory_service_audits_owner_content_deletion_without_content(
    fixed_time,
) -> None:
    original = _assertion(fixed_time)
    repository = InMemoryMemoryRepository((original,))
    audit_store = InMemoryEventAuditStore()
    deleted_at = fixed_time + timedelta(minutes=2)
    service = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        event_audit_store=audit_store,
        clock=lambda: deleted_at,
        id_factory=_id_factory(
            deletion=record_id("deletion", 1),
            work=record_id("work", 1),
            event=record_id("event", 1),
            audit=record_id("audit", 1),
        ),
    )
    principal = _principal(fixed_time)

    result = service.delete_content(principal, original.assertion_id)

    assert result.created is True
    assert len(audit_store.events) == 1
    assert len(audit_store.audit_records) == 1
    event = audit_store.events[0]
    assert event.event_type == "memory.assertion-content-deleted.v1"
    assert event.subject_ids == (original.subject_id,)
    assert event.payload == {
        "assertion_id": original.assertion_id,
        "backup_expiry_state": "unknown",
        "content_state": "deleted",
        "reason_code": "memory.assertion-content-owner-deleted",
        "rebuild_work_id": result.rebuild_work.work_id,
        "retained_size_bytes": result.tombstone.size_bytes,
        "sensitivity": original.sensitivity.value,
        "tombstone_id": result.tombstone.tombstone_id,
    }
    assert "value" not in event.model_dump(mode="json")
    assert "content_hash" not in event.model_dump_json()
    audit = audit_store.audit_records[0].content
    assert audit.actor_id == principal.owner_id
    assert audit.action == "memory.assertion-content.delete"
    assert audit.object_ids == (
        original.assertion_id,
        result.tombstone.tombstone_id,
        result.rebuild_work.work_id,
    )

    repeated = service.delete_content(principal, original.assertion_id)

    assert repeated.created is False
    assert len(audit_store.events) == 1
    assert len(audit_store.audit_records) == 1


def test_memory_service_retries_audit_after_deletion_replay(
    fixed_time,
) -> None:
    original = _assertion(fixed_time)
    repository = InMemoryMemoryRepository((original,))
    audit_store = _FailFirstAuditStore()
    deleted_at = fixed_time + timedelta(minutes=2)
    service = MemoryService(
        owner_id=original.subject_id,
        store=repository,
        guardian_reader=_guardian(fixed_time),
        event_audit_store=audit_store,
        clock=lambda: deleted_at,
        id_factory=_id_factory(
            deletion=record_id("deletion", 1),
            work=record_id("work", 1),
        ),
    )
    principal = _principal(fixed_time)

    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        service.delete_content(principal, original.assertion_id)

    with pytest.raises(MemoryContentDeletedError):
        repository.get_assertion(original.assertion_id)

    replay = service.delete_content(principal, original.assertion_id)

    assert replay.created is False
    assert len(audit_store.events) == 1
    assert len(audit_store.audit_records) == 1
    event = audit_store.events[0]
    assert event.correlation_id == replay.tombstone.tombstone_id
    assert event.occurred_at == replay.tombstone.deleted_at
    audit = audit_store.audit_records[0].content
    assert audit.occurred_at == replay.tombstone.deleted_at
    assert audit.object_ids == (
        original.assertion_id,
        replay.tombstone.tombstone_id,
        replay.rebuild_work.work_id,
    )


def test_memory_repository_missing_records_fail_closed(fixed_time) -> None:
    repository = InMemoryMemoryRepository((_assertion(fixed_time),))
    missing = record_id("assertion", 99)
    with pytest.raises(MemoryNotFoundError):
        repository.get_assertion_state(missing)
    with pytest.raises(MemoryNotFoundError):
        repository.list_assertion_state_changes(missing)
    with pytest.raises(MemoryNotFoundError):
        repository.get_assertion_metadata(missing)
    with pytest.raises(MemoryNotFoundError):
        repository.get_assertion_content_deletion(missing)
