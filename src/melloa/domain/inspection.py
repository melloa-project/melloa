"""Owner-visible redacted model cost and external-disclosure activity."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import AwareDatetime, ContractModel, QualifiedName, RecordId
from melloa.domain.classification import Sensitivity
from melloa.domain.models import ModelRouteAttempt


class DisclosedMemoryReference(ContractModel):
    citation_id: RecordId
    assertion_id: RecordId
    sensitivity: Sensitivity


class ModelDisclosureInspection(ContractModel):
    retrieval_manifest_id: RecordId
    purpose: QualifiedName
    triggering_message_ids: tuple[RecordId, ...] = Field(min_length=1)
    memory_references: tuple[DisclosedMemoryReference, ...]
    external_attempts: tuple[ModelRouteAttempt, ...]

    @model_validator(mode="after")
    def validate_disclosure(self) -> ModelDisclosureInspection:
        citation_ids = tuple(reference.citation_id for reference in self.memory_references)
        assertion_ids = tuple(reference.assertion_id for reference in self.memory_references)
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("disclosed memory citation IDs must be unique")
        if len(set(assertion_ids)) != len(assertion_ids):
            raise ValueError("a memory assertion can be disclosed only once per model run")
        if any(not attempt.external_disclosure for attempt in self.external_attempts):
            raise ValueError("disclosure inspection cannot include local model attempts")
        return self


class ModelActivityEntry(ContractModel):
    turn_id: RecordId
    thread_id: RecordId
    result_id: RecordId
    request_id: RecordId
    route_id: QualifiedName
    provider_id: QualifiedName
    model_id: str = Field(min_length=1, max_length=256)
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    cost_gbp: Annotated[float, Field(ge=0.0)]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    external_disclosure: bool
    disclosure: ModelDisclosureInspection | None = None

    @model_validator(mode="after")
    def validate_entry(self) -> ModelActivityEntry:
        if self.completed_at < self.started_at:
            raise ValueError("model activity cannot complete before it starts")
        if self.external_disclosure != (self.disclosure is not None):
            raise ValueError("model activity disclosure detail does not match its route result")
        return self


class OwnerModelActivityReport(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    owner_id: RecordId
    window_start: AwareDatetime
    window_end: AwareDatetime
    generated_at: AwareDatetime
    total_runs: Annotated[int, Field(ge=0)]
    external_disclosure_runs: Annotated[int, Field(ge=0)]
    total_input_tokens: Annotated[int, Field(ge=0)]
    total_output_tokens: Annotated[int, Field(ge=0)]
    total_cost_gbp: Annotated[float, Field(ge=0.0)]
    external_cost_gbp: Annotated[float, Field(ge=0.0)]
    entries: tuple[ModelActivityEntry, ...]

    @model_validator(mode="after")
    def validate_report(self) -> OwnerModelActivityReport:
        if self.window_end <= self.window_start:
            raise ValueError("model activity window must end after it starts")
        if len({entry.result_id for entry in self.entries}) != len(self.entries):
            raise ValueError("model activity result IDs must be unique")
        if self.entries != tuple(
            sorted(
                self.entries,
                key=lambda entry: (entry.completed_at, entry.result_id),
            )
        ):
            raise ValueError("model activity entries must be in deterministic completion order")
        if any(
            not self.window_start <= entry.completed_at < self.window_end
            for entry in self.entries
        ):
            raise ValueError("model activity entry falls outside the report window")
        if (
            self.total_runs != len(self.entries)
            or self.external_disclosure_runs
            != sum(entry.external_disclosure for entry in self.entries)
            or self.total_input_tokens != sum(entry.input_tokens for entry in self.entries)
            or self.total_output_tokens != sum(entry.output_tokens for entry in self.entries)
            or not math.isclose(
                self.total_cost_gbp,
                math.fsum(entry.cost_gbp for entry in self.entries),
                abs_tol=1e-9,
            )
            or not math.isclose(
                self.external_cost_gbp,
                math.fsum(
                    entry.cost_gbp for entry in self.entries if entry.external_disclosure
                ),
                abs_tol=1e-9,
            )
        ):
            raise ValueError("model activity totals do not match its entries")
        return self
