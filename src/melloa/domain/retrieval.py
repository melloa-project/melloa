"""Policy-constrained retrieval manifests and memory citations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import (
    AwareDatetime,
    ContractModel,
    JsonObject,
    QualifiedName,
    RecordId,
    Sha256Digest,
)
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.events import Confidence
from melloa.domain.memory import AssertionStatus


class RetrievalMethod(StrEnum):
    EXACT_RELATIONAL = "exact_relational"
    FULL_TEXT_CANDIDATE = "full_text_candidate"
    VECTOR_CANDIDATE = "vector_candidate"


class MemoryCitation(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    citation_id: RecordId
    assertion_id: RecordId
    predicate: QualifiedName
    value: JsonObject
    epistemic_status: EpistemicStatus
    assertion_status: AssertionStatus
    confidence: Confidence
    source_authority: TrustLabel
    sensitivity: Sensitivity
    observed_at: AwareDatetime
    provenance_edge_ids: tuple[RecordId, ...]
    rank_score: Annotated[float, Field(ge=0.0, le=1.0)]
    rank_reasons: tuple[QualifiedName, ...] = Field(min_length=1)


class RetrievalManifest(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    manifest_id: RecordId
    requester_id: RecordId
    subject_id: RecordId
    purpose: QualifiedName
    query_hash: Sha256Digest
    allowed_sensitivities: frozenset[Sensitivity] = Field(min_length=1)
    methods: tuple[RetrievalMethod, ...] = Field(min_length=1)
    candidate_assertion_ids: tuple[RecordId, ...]
    citations: tuple[MemoryCitation, ...]
    excluded_assertion_ids: tuple[RecordId, ...]
    created_at: AwareDatetime
    external_disclosure: bool

    @model_validator(mode="after")
    def validate_manifest(self) -> RetrievalManifest:
        candidate_ids = set(self.candidate_assertion_ids)
        excluded_ids = set(self.excluded_assertion_ids)
        citation_ids = tuple(citation.citation_id for citation in self.citations)
        cited_assertion_ids = tuple(citation.assertion_id for citation in self.citations)
        if len(candidate_ids) != len(self.candidate_assertion_ids):
            raise ValueError("retrieval candidate assertion IDs must be unique")
        if len(excluded_ids) != len(self.excluded_assertion_ids):
            raise ValueError("retrieval excluded assertion IDs must be unique")
        if candidate_ids & excluded_ids:
            raise ValueError("retrieval candidates and exclusions must be disjoint")
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("retrieval citation IDs must be unique")
        if len(set(cited_assertion_ids)) != len(cited_assertion_ids):
            raise ValueError("an assertion can appear only once in a retrieval manifest")
        if not set(cited_assertion_ids) <= candidate_ids:
            raise ValueError("retrieval citations must come from recorded candidates")
        if excluded_ids & set(cited_assertion_ids):
            raise ValueError("an excluded assertion cannot also be cited")
        if any(
            citation.sensitivity not in self.allowed_sensitivities
            for citation in self.citations
        ):
            raise ValueError("retrieval citation exceeds the allowed sensitivity scope")
        if self.external_disclosure and any(
            citation.sensitivity is Sensitivity.DEVICE_ONLY for citation in self.citations
        ):
            raise ValueError("device-only memory cannot be externally disclosed")
        return self
