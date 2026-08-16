"""Deterministic provenance-ranked retrieval; candidate similarity is never evidence."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime

from melloa.domain.base import (
    RecordId,
    canonical_json_bytes,
    new_record_id,
    sha256_digest,
    utc_now,
)
from melloa.domain.classification import Sensitivity, TrustLabel
from melloa.domain.memory import Assertion, AssertionStatus, ProvenanceEdge
from melloa.domain.retrieval import MemoryCitation, RetrievalManifest, RetrievalMethod
from melloa.ports.memory import MemoryRepository

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]+")
_RETRIEVABLE_STATUSES = {
    AssertionStatus.PROVISIONAL,
    AssertionStatus.ACTIVE,
    AssertionStatus.CONFIRMED,
}
_AUTHORITY_WEIGHT = {
    TrustLabel.OWNER_AUTHORED: 1.0,
    TrustLabel.SIGNED_SYSTEM_ARTIFACT: 0.9,
    TrustLabel.TRUSTED_SYSTEM: 0.85,
    TrustLabel.TRUSTED_CAPABILITY_METADATA: 0.75,
    TrustLabel.MODEL_GENERATED: 0.45,
    TrustLabel.UNTRUSTED_SENSOR_DERIVED: 0.35,
    TrustLabel.UNTRUSTED_EXTERNAL: 0.25,
    TrustLabel.GENERATED_CODE: 0.2,
}
_STATUS_WEIGHT = {
    AssertionStatus.CONFIRMED: 1.0,
    AssertionStatus.ACTIVE: 0.75,
    AssertionStatus.PROVISIONAL: 0.35,
}


class PolicyConstrainedRetriever:
    def __init__(
        self,
        repository: MemoryRepository,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._id_factory = id_factory

    def retrieve(
        self,
        *,
        requester_id: RecordId,
        subject_id: RecordId,
        query: str,
        purpose: str,
        allowed_sensitivities: frozenset[Sensitivity],
        limit: int = 5,
    ) -> RetrievalManifest:
        if not 1 <= limit <= 100:
            raise ValueError("retrieval limit must be between 1 and 100")
        query_tokens = frozenset(_TOKEN_RE.findall(query.casefold()))
        assertions = self._repository.list_assertions(subject_id)
        ranked: list[tuple[float, Assertion]] = []
        excluded: list[RecordId] = []
        for assertion in assertions:
            if (
                assertion.sensitivity not in allowed_sensitivities
                or assertion.status not in _RETRIEVABLE_STATUSES
            ):
                excluded.append(assertion.assertion_id)
                continue
            assertion_tokens = self._tokens_for_assertion(assertion)
            overlap = query_tokens & assertion_tokens
            if not query_tokens or not overlap:
                excluded.append(assertion.assertion_id)
                continue
            overlap_ratio = len(overlap) / len(query_tokens)
            score = min(
                1.0,
                0.35 * overlap_ratio
                + 0.3 * assertion.confidence
                + 0.2 * _AUTHORITY_WEIGHT[assertion.source_authority]
                + 0.15 * _STATUS_WEIGHT[assertion.status],
            )
            ranked.append((round(score, 6), assertion))

        ranked.sort(
            key=lambda item: (
                -item[0],
                -item[1].observed_at.timestamp(),
                item[1].assertion_id,
            )
        )
        candidate_ids = tuple(assertion.assertion_id for _score, assertion in ranked)
        selected = ranked[:limit]
        selected_ids = frozenset(assertion.assertion_id for _score, assertion in selected)
        edges = self._repository.list_provenance_edges(selected_ids)
        citations = tuple(
            self._citation(assertion, score, edges)
            for score, assertion in selected
        )
        methods: tuple[RetrievalMethod, ...] = (RetrievalMethod.EXACT_RELATIONAL,)
        if query_tokens:
            methods += (RetrievalMethod.FULL_TEXT_CANDIDATE,)
        return RetrievalManifest(
            manifest_id=self._id_factory("retrieval_manifest"),
            requester_id=requester_id,
            subject_id=subject_id,
            purpose=purpose,
            query_hash=sha256_digest(query.encode("utf-8")),
            allowed_sensitivities=allowed_sensitivities,
            methods=methods,
            candidate_assertion_ids=candidate_ids,
            citations=citations,
            excluded_assertion_ids=tuple(sorted(set(excluded))),
            created_at=self._clock(),
            external_disclosure=False,
        )

    def _citation(
        self,
        assertion: Assertion,
        score: float,
        edges: tuple[ProvenanceEdge, ...],
    ) -> MemoryCitation:
        provenance_ids = tuple(
            edge.edge_id
            for edge in edges
            if edge.from_id == assertion.assertion_id or edge.to_id == assertion.assertion_id
        )
        return MemoryCitation(
            citation_id=self._id_factory("citation"),
            assertion_id=assertion.assertion_id,
            predicate=assertion.predicate,
            value=assertion.value,
            epistemic_status=assertion.epistemic_status,
            assertion_status=assertion.status,
            confidence=assertion.confidence,
            source_authority=assertion.source_authority,
            sensitivity=assertion.sensitivity,
            observed_at=assertion.observed_at,
            provenance_edge_ids=provenance_ids,
            rank_score=score,
            rank_reasons=(
                "rank.query-overlap",
                "rank.provenance-authority",
                "rank.confirmation-status",
                "rank.confidence",
                "rank.recency-tiebreak",
            ),
        )

    @staticmethod
    def _tokens_for_assertion(assertion: Assertion) -> frozenset[str]:
        text = f"{assertion.predicate} {canonical_json_bytes(assertion.value).decode('utf-8')}"
        return frozenset(_TOKEN_RE.findall(text.casefold()))
