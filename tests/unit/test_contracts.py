from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from melloa.domain.audit import AuditRecord, audit_record_hash
from melloa.domain.base import canonical_json_bytes, new_record_id, sha256_digest
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.events import EventEnvelope
from melloa.domain.identity import (
    NameHistoryEntry,
    OwnerIdentity,
    PersistentIntelligenceIdentity,
)
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
from tests.conftest import record_id


def test_event_requires_confidence_and_matching_payload_hash(event: EventEnvelope) -> None:
    document = event.model_dump()
    document["confidence"] = None
    with pytest.raises(ValidationError, match="require confidence"):
        EventEnvelope.model_validate(document)

    document = event.model_dump()
    document["payload"] = {"zone": "window"}
    with pytest.raises(ValidationError, match="payload hash"):
        EventEnvelope.model_validate(document)


def test_identity_keeps_display_name_in_history(fixed_time) -> None:
    owner = OwnerIdentity(owner_id=record_id("owner", 1), created_at=fixed_time)
    intelligence = PersistentIntelligenceIdentity(
        intelligence_id=record_id("intelligence", 1),
        owner_id=owner.owner_id,
        created_at=fixed_time,
        role="Primary persistent personal intelligence",
        naming_history=(
            NameHistoryEntry(
                display_name="Melli",
                valid_from=fixed_time,
                chosen_by=owner.owner_id,
            ),
        ),
    )
    assert intelligence.intelligence_id != intelligence.naming_history[0].display_name

    with pytest.raises(ValidationError, match=r"at least 1 item|exactly one current"):
        PersistentIntelligenceIdentity.model_validate(
            {
                **intelligence.model_dump(),
                "naming_history": (),
            }
        )


def test_corrections_append_without_relabeling_the_original(fixed_time) -> None:
    original = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=record_id("owner", 1),
        predicate="activity.sleeping",
        value={"state": True},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.61,
        source_authority=TrustLabel.MODEL_GENERATED,
        sensitivity=Sensitivity.SENSITIVE,
        observed_at=fixed_time,
    )
    correction = Assertion(
        assertion_id=record_id("assertion", 2),
        subject_id=original.subject_id,
        predicate="activity.reading",
        value={"state": True},
        epistemic_status=EpistemicStatus.CORRECTION,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.SENSITIVE,
        observed_at=fixed_time + timedelta(minutes=2),
        correction_target_id=original.assertion_id,
    )
    edge = ProvenanceEdge(
        edge_id=record_id("edge", 1),
        from_id=correction.assertion_id,
        to_id=original.assertion_id,
        relation=ProvenanceRelation.CORRECTS,
        created_at=correction.observed_at,
        producer_id=record_id("owner", 1),
    )
    assert original.status is AssertionStatus.ACTIVE
    assert correction.correction_target_id == original.assertion_id
    assert edge.relation is ProvenanceRelation.CORRECTS


def test_owner_confirmed_claim_requires_owner_authority(fixed_time) -> None:
    with pytest.raises(ValidationError, match="owner authority"):
        Assertion(
            assertion_id=record_id("assertion", 1),
            subject_id=record_id("owner", 1),
            predicate="preference.example",
            value={"value": "x"},
            epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
            status=AssertionStatus.CONFIRMED,
            confidence=1.0,
            source_authority=TrustLabel.MODEL_GENERATED,
            sensitivity=Sensitivity.PERSONAL,
            observed_at=fixed_time,
        )


def test_assertion_and_provenance_semantics_reject_invalid_links(fixed_time) -> None:
    base = {
        "assertion_id": record_id("assertion", 1),
        "subject_id": record_id("owner", 1),
        "predicate": "activity.current",
        "value": {"activity": "sleeping"},
        "status": AssertionStatus.ACTIVE,
        "confidence": 0.61,
        "source_authority": TrustLabel.MODEL_GENERATED,
        "sensitivity": Sensitivity.SENSITIVE,
        "observed_at": fixed_time,
    }
    with pytest.raises(ValidationError, match="validity must end"):
        Assertion(
            **base,
            epistemic_status=EpistemicStatus.BELIEF,
            valid_from=fixed_time,
            valid_to=fixed_time,
        )
    with pytest.raises(ValidationError, match="corrections require"):
        Assertion(**base, epistemic_status=EpistemicStatus.CORRECTION)
    with pytest.raises(ValidationError, match="only corrections"):
        Assertion(
            **base,
            epistemic_status=EpistemicStatus.BELIEF,
            correction_target_id=record_id("assertion", 2),
        )
    with pytest.raises(ValidationError, match="cannot point to the same"):
        ProvenanceEdge(
            edge_id=record_id("edge", 1),
            from_id=record_id("assertion", 1),
            to_id=record_id("assertion", 1),
            relation=ProvenanceRelation.CORRECTS,
            created_at=fixed_time,
            producer_id=record_id("owner", 1),
        )


def test_assertion_state_contracts_reject_inconsistent_transitions(fixed_time) -> None:
    assertion_id = record_id("assertion", 1)
    common_projection = {
        "assertion_id": assertion_id,
        "changed_by_record_id": record_id("assertion", 2),
        "changed_at": fixed_time,
        "version": 2,
    }
    with pytest.raises(ValidationError, match="cannot supersede itself"):
        AssertionStateProjection(
            **common_projection,
            current_status=AssertionStatus.SUPERSEDED,
            preferred_assertion_id=assertion_id,
        )
    with pytest.raises(ValidationError, match="require a preferred"):
        AssertionStateProjection(
            **common_projection,
            current_status=AssertionStatus.SUPERSEDED,
        )

    common_change = {
        "change_id": record_id("state_change", 2),
        "assertion_id": assertion_id,
        "new_status": AssertionStatus.ACTIVE,
        "changed_by_record_id": record_id("assertion", 2),
        "reason": "assertion.test-transition",
        "changed_at": fixed_time,
    }
    with pytest.raises(ValidationError, match="only an initial"):
        AssertionStateChange(**common_change, previous_status=None, version=2)
    with pytest.raises(ValidationError, match="cannot prefer itself"):
        AssertionStateChange(
            **common_change,
            previous_status=AssertionStatus.PROVISIONAL,
            preferred_assertion_id=assertion_id,
            version=2,
        )
    with pytest.raises(ValidationError, match="requires a preferred"):
        AssertionStateChange(
            **{
                **common_change,
                "new_status": AssertionStatus.SUPERSEDED,
            },
            previous_status=AssertionStatus.ACTIVE,
            version=2,
        )


def test_correction_result_and_inspection_require_consistent_links(fixed_time) -> None:
    original = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=record_id("owner", 1),
        predicate="activity.current",
        value={"activity": "sleeping"},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.61,
        source_authority=TrustLabel.MODEL_GENERATED,
        sensitivity=Sensitivity.SENSITIVE,
        observed_at=fixed_time,
    )
    correction = Assertion(
        assertion_id=record_id("assertion", 2),
        subject_id=original.subject_id,
        predicate=original.predicate,
        value={"activity": "reading"},
        epistemic_status=EpistemicStatus.CORRECTION,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=original.sensitivity,
        observed_at=fixed_time,
        correction_target_id=original.assertion_id,
    )
    edge = ProvenanceEdge(
        edge_id=record_id("edge", 1),
        from_id=correction.assertion_id,
        to_id=original.assertion_id,
        relation=ProvenanceRelation.CORRECTS,
        created_at=fixed_time,
        producer_id=original.subject_id,
    )
    target_state = AssertionStateProjection(
        assertion_id=original.assertion_id,
        current_status=AssertionStatus.SUPERSEDED,
        preferred_assertion_id=correction.assertion_id,
        changed_by_record_id=correction.assertion_id,
        changed_at=fixed_time,
        version=2,
    )
    correction_state = AssertionStateProjection(
        assertion_id=correction.assertion_id,
        current_status=AssertionStatus.CONFIRMED,
        changed_by_record_id=correction.assertion_id,
        changed_at=fixed_time,
        version=1,
    )
    initial_change = AssertionStateChange(
        change_id=record_id("state_change", 1),
        assertion_id=original.assertion_id,
        previous_status=None,
        new_status=AssertionStatus.ACTIVE,
        changed_by_record_id=original.assertion_id,
        reason="assertion.initialized",
        changed_at=fixed_time,
        version=1,
    )
    target_change = AssertionStateChange(
        change_id=record_id("state_change", 2),
        assertion_id=original.assertion_id,
        previous_status=AssertionStatus.ACTIVE,
        new_status=AssertionStatus.SUPERSEDED,
        preferred_assertion_id=correction.assertion_id,
        changed_by_record_id=correction.assertion_id,
        reason="assertion.owner-corrected",
        changed_at=fixed_time,
        version=2,
    )
    valid_result = {
        "correction": correction,
        "provenance_edge": edge,
        "target_state": target_state,
        "correction_state": correction_state,
        "target_change": target_change,
    }
    assert AssertionCorrectionResult(**valid_result).target_state == target_state

    with pytest.raises(ValidationError, match="requires a correction"):
        AssertionCorrectionResult(**{**valid_result, "correction": original})
    with pytest.raises(ValidationError, match="provenance does not match"):
        AssertionCorrectionResult(
            **{
                **valid_result,
                "provenance_edge": ProvenanceEdge(
                    **{
                        **edge.model_dump(),
                        "relation": ProvenanceRelation.SUPPORTS,
                    }
                ),
            }
        )
    with pytest.raises(ValidationError, match="target correction state"):
        AssertionCorrectionResult(
            **{
                **valid_result,
                "target_state": AssertionStateProjection(
                    **{
                        **target_state.model_dump(),
                        "version": 3,
                    }
                ),
            }
        )
    with pytest.raises(ValidationError, match="correction projection"):
        AssertionCorrectionResult(
            **{
                **valid_result,
                "correction_state": AssertionStateProjection(
                    **{
                        **correction_state.model_dump(),
                        "assertion_id": record_id("assertion", 3),
                    }
                ),
            }
        )

    valid_inspection = {
        "assertion": original,
        "current_state": target_state,
        "provenance_edges": (edge,),
        "state_changes": (initial_change, target_change),
    }
    assert MemoryInspection(**valid_inspection).current_state == target_state
    with pytest.raises(ValidationError, match="projection does not match"):
        MemoryInspection(**{**valid_inspection, "current_state": correction_state})
    with pytest.raises(ValidationError, match="unrelated provenance"):
        MemoryInspection(
            **{
                **valid_inspection,
                "provenance_edges": (
                    ProvenanceEdge(
                        edge_id=record_id("edge", 2),
                        from_id=record_id("assertion", 3),
                        to_id=record_id("event", 1),
                        relation=ProvenanceRelation.DERIVED_FROM,
                        created_at=fixed_time,
                        producer_id=record_id("intelligence", 1),
                    ),
                ),
            }
        )
    with pytest.raises(ValidationError, match="unrelated state history"):
        MemoryInspection(
            **{
                **valid_inspection,
                "state_changes": (
                    AssertionStateChange(
                        **{
                            **initial_change.model_dump(),
                            "assertion_id": record_id("assertion", 3),
                        }
                    ),
                ),
            }
        )
    with pytest.raises(ValidationError, match="history does not match"):
        MemoryInspection(**{**valid_inspection, "state_changes": (initial_change,)})


def test_assertion_state_transition_result_requires_matching_history(fixed_time) -> None:
    assertion = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=record_id("owner", 1),
        predicate="activity.current",
        value={"activity": "sleeping"},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.61,
        source_authority=TrustLabel.MODEL_GENERATED,
        sensitivity=Sensitivity.SENSITIVE,
        observed_at=fixed_time,
    )
    state = AssertionStateProjection(
        assertion_id=assertion.assertion_id,
        current_status=AssertionStatus.DISPUTED,
        changed_by_record_id=assertion.subject_id,
        changed_at=fixed_time + timedelta(minutes=1),
        version=2,
    )
    change = AssertionStateChange(
        change_id=record_id("state_change", 2),
        assertion_id=assertion.assertion_id,
        previous_status=AssertionStatus.ACTIVE,
        new_status=AssertionStatus.DISPUTED,
        changed_by_record_id=assertion.subject_id,
        reason="assertion.owner-disputed",
        changed_at=state.changed_at,
        version=2,
    )
    assert AssertionStateTransitionResult(
        assertion=assertion,
        current_state=state,
        state_change=change,
    ).current_state == state

    with pytest.raises(ValidationError, match="another assertion"):
        AssertionStateTransitionResult(
            assertion=assertion,
            current_state=AssertionStateProjection(
                **{
                    **state.model_dump(),
                    "assertion_id": record_id("assertion", 2),
                }
            ),
            state_change=change,
        )
    with pytest.raises(ValidationError, match="cannot represent initialization"):
        AssertionStateTransitionResult(
            assertion=assertion,
            current_state=AssertionStateProjection(
                assertion_id=assertion.assertion_id,
                current_status=AssertionStatus.ACTIVE,
                changed_by_record_id=assertion.assertion_id,
                changed_at=fixed_time,
                version=1,
            ),
            state_change=AssertionStateChange(
                change_id=record_id("state_change", 1),
                assertion_id=assertion.assertion_id,
                previous_status=None,
                new_status=AssertionStatus.ACTIVE,
                changed_by_record_id=assertion.assertion_id,
                reason="assertion.initialized",
                changed_at=fixed_time,
                version=1,
            ),
        )
    with pytest.raises(ValidationError, match="result is inconsistent"):
        AssertionStateTransitionResult(
            assertion=assertion,
            current_state=state,
            state_change=AssertionStateChange(
                **{
                    **change.model_dump(),
                    "changed_at": fixed_time + timedelta(minutes=2),
                }
            ),
        )


def test_audit_record_hash_covers_predecessor(audit_content) -> None:
    record_hash = audit_record_hash(audit_content, None)
    record = AuditRecord(content=audit_content, record_hash=record_hash)
    assert record.record_hash == record_hash

    with pytest.raises(ValidationError, match="audit record hash"):
        AuditRecord(
            content=audit_content,
            previous_hash="sha256:" + "1" * 64,
            record_hash=record_hash,
        )


def test_canonical_json_is_stable_and_rejects_bad_id_prefix() -> None:
    assert canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    assert sha256_digest(b"x").startswith("sha256:")
    with pytest.raises(ValueError, match="prefix"):
        new_record_id("Melli")
