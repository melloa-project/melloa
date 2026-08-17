"""Owner-visible redacted model cost and external-disclosure activity."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import AwareDatetime, ContractModel, JsonObject, QualifiedName, RecordId
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


class OwnerTimelineEvent(ContractModel):
    event_id: RecordId
    kind: QualifiedName
    occurred_at: AwareDatetime
    source: QualifiedName
    summary: str = Field(min_length=1, max_length=256)
    thread_id: RecordId | None = None
    message_id: RecordId | None = None
    turn_id: RecordId | None = None
    work_id: RecordId | None = None
    status: QualifiedName | None = None
    sensitivity: Sensitivity | None = None
    references: tuple[RecordId, ...] = ()
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event(self) -> OwnerTimelineEvent:
        if len(set(self.references)) != len(self.references):
            raise ValueError("timeline event references must be unique")
        if not (
            self.thread_id is not None
            or self.message_id is not None
            or self.turn_id is not None
            or self.work_id is not None
            or self.references
        ):
            raise ValueError("timeline events must reference canonical owner records")
        return self


class OwnerTimelineReport(ContractModel):
    contract_version: Literal["1.1.0"] = "1.1.0"
    owner_id: RecordId
    window_start: AwareDatetime
    window_end: AwareDatetime
    generated_at: AwareDatetime
    total_events: Annotated[int, Field(ge=0)]
    matching_events: Annotated[int, Field(ge=0)]
    truncated: bool
    coverage: tuple[QualifiedName, ...] = Field(min_length=1)
    limitations: tuple[QualifiedName, ...]
    entries: tuple[OwnerTimelineEvent, ...]

    @model_validator(mode="after")
    def validate_report(self) -> OwnerTimelineReport:
        if self.window_end <= self.window_start:
            raise ValueError("timeline window must end after it starts")
        if self.total_events != len(self.entries):
            raise ValueError("timeline total does not match its entries")
        if self.matching_events < self.total_events:
            raise ValueError("timeline matching total cannot be below returned entries")
        if self.truncated != (self.matching_events > self.total_events):
            raise ValueError("timeline truncation state does not match event totals")
        event_ids = tuple(entry.event_id for entry in self.entries)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("timeline event IDs must be unique")
        if self.entries != tuple(
            sorted(
                self.entries,
                key=lambda entry: (entry.occurred_at, entry.event_id),
                reverse=True,
            )
        ):
            raise ValueError("timeline entries must use deterministic newest-first order")
        if any(
            not self.window_start <= entry.occurred_at < self.window_end
            for entry in self.entries
        ):
            raise ValueError("timeline event falls outside the report window")
        if self.coverage != tuple(sorted(self.coverage)):
            raise ValueError("timeline coverage must use deterministic order")
        if len(set(self.coverage)) != len(self.coverage):
            raise ValueError("timeline coverage values must be unique")
        if self.limitations != tuple(sorted(self.limitations)):
            raise ValueError("timeline limitations must use deterministic order")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("timeline limitations must be unique")
        return self
