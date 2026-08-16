from __future__ import annotations

import pytest
from pydantic import ValidationError

from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.domain.classification import (
    EpistemicStatus,
    Sensitivity,
    TrustLabel,
    most_restrictive_sensitivity,
    sensitivity_scope,
)
from melloa.domain.memory import Assertion, AssertionStatus, ProvenanceEdge, ProvenanceRelation
from melloa.domain.retrieval import RetrievalManifest
from tests.conftest import record_id


def assertion(
    fixed_time,
    *,
    number: int,
    value: str,
    sensitivity=Sensitivity.PERSONAL,
    status=AssertionStatus.ACTIVE,
    authority=TrustLabel.MODEL_GENERATED,
    confidence=0.7,
) -> Assertion:
    return Assertion(
        assertion_id=record_id("assertion", number),
        subject_id=record_id("owner", 1),
        predicate="preference.review-topic",
        value={"topic": value},
        epistemic_status=EpistemicStatus.BELIEF,
        status=status,
        confidence=confidence,
        source_authority=authority,
        sensitivity=sensitivity,
        observed_at=fixed_time,
    )


def test_retrieval_filters_scope_and_ranks_provenance(fixed_time) -> None:
    owner_confirmed = assertion(
        fixed_time,
        number=1,
        value="finances",
        status=AssertionStatus.CONFIRMED,
        authority=TrustLabel.OWNER_AUTHORED,
        confidence=1.0,
    )
    model_claim = assertion(
        fixed_time,
        number=2,
        value="finances",
        authority=TrustLabel.MODEL_GENERATED,
        confidence=0.8,
    )
    device_only = assertion(
        fixed_time,
        number=3,
        value="finances",
        sensitivity=Sensitivity.DEVICE_ONLY,
    )
    disputed = assertion(
        fixed_time,
        number=4,
        value="finances",
        status=AssertionStatus.DISPUTED,
    )
    edge = ProvenanceEdge(
        edge_id=record_id("edge", 1),
        from_id=model_claim.assertion_id,
        to_id=owner_confirmed.assertion_id,
        relation=ProvenanceRelation.SUPPORTS,
        created_at=fixed_time,
        producer_id=record_id("intelligence", 1),
    )
    retriever = PolicyConstrainedRetriever(
        InMemoryMemoryRepository(
            (model_claim, device_only, owner_confirmed, disputed),
            (edge,),
        ),
        clock=lambda: fixed_time,
    )

    manifest = retriever.retrieve(
        requester_id=record_id("intelligence", 1),
        subject_id=record_id("owner", 1),
        query="What should I review about finances?",
        purpose="conversation.owner-reply",
        allowed_sensitivities=frozenset(
            {Sensitivity.PUBLIC, Sensitivity.INTERNAL, Sensitivity.PERSONAL}
        ),
    )

    assert tuple(citation.assertion_id for citation in manifest.citations) == (
        owner_confirmed.assertion_id,
        model_claim.assertion_id,
    )
    assert manifest.citations[0].source_authority is TrustLabel.OWNER_AUTHORED
    assert edge.edge_id in manifest.citations[0].provenance_edge_ids
    assert set(manifest.excluded_assertion_ids) == {
        device_only.assertion_id,
        disputed.assertion_id,
    }
    assert manifest.query_hash.startswith("sha256:")
    assert "What should I review about finances?" not in manifest.model_dump_json()


def test_retrieval_does_not_treat_unrelated_candidates_as_evidence(fixed_time) -> None:
    memory = assertion(fixed_time, number=1, value="finances")
    retriever = PolicyConstrainedRetriever(
        InMemoryMemoryRepository((memory,)),
        clock=lambda: fixed_time,
    )
    manifest = retriever.retrieve(
        requester_id=record_id("intelligence", 1),
        subject_id=record_id("owner", 1),
        query="gardening plans",
        purpose="conversation.owner-reply",
        allowed_sensitivities=frozenset(Sensitivity),
    )
    assert manifest.candidate_assertion_ids == ()
    assert manifest.citations == ()
    assert manifest.excluded_assertion_ids == (memory.assertion_id,)


def test_retrieval_manifest_rejects_device_only_external_disclosure(fixed_time) -> None:
    memory = assertion(
        fixed_time,
        number=1,
        value="private",
        sensitivity=Sensitivity.DEVICE_ONLY,
    )
    retriever = PolicyConstrainedRetriever(
        InMemoryMemoryRepository((memory,)),
        clock=lambda: fixed_time,
    )
    manifest = retriever.retrieve(
        requester_id=record_id("intelligence", 1),
        subject_id=record_id("owner", 1),
        query="private review-topic",
        purpose="conversation.owner-reply",
        allowed_sensitivities=frozenset(Sensitivity),
    )
    document = manifest.model_dump()
    document["external_disclosure"] = True
    with pytest.raises(ValidationError, match="device-only"):
        RetrievalManifest.model_validate(document)

    document = manifest.model_dump()
    document["excluded_assertion_ids"] = manifest.candidate_assertion_ids
    with pytest.raises(ValidationError, match="disjoint"):
        RetrievalManifest.model_validate(document)


def test_retrieval_rejects_invalid_limit(fixed_time) -> None:
    retriever = PolicyConstrainedRetriever(
        InMemoryMemoryRepository(),
        clock=lambda: fixed_time,
    )
    with pytest.raises(ValueError, match="limit"):
        retriever.retrieve(
            requester_id=record_id("intelligence", 1),
            subject_id=record_id("owner", 1),
            query="synthetic",
            purpose="conversation.owner-reply",
            allowed_sensitivities=frozenset(Sensitivity),
            limit=0,
        )


def test_sensitivity_scope_and_inheritance_are_conservative() -> None:
    assert sensitivity_scope(Sensitivity.PERSONAL) == frozenset(
        {Sensitivity.PUBLIC, Sensitivity.INTERNAL, Sensitivity.PERSONAL}
    )
    assert most_restrictive_sensitivity(
        (Sensitivity.PUBLIC, Sensitivity.SENSITIVE, Sensitivity.INTERNAL)
    ) is Sensitivity.SENSITIVE
    with pytest.raises(ValueError, match="at least one sensitivity"):
        most_restrictive_sensitivity(())
