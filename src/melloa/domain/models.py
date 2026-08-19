"""Contracts for the one configured conversation model."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import AwareDatetime, ContractModel, JsonObject, QualifiedName, RecordId
from melloa.domain.classification import Sensitivity


class ProcessingLocation(StrEnum):
    DEVICE = "device"
    PRIVATE_NETWORK = "private_network"
    APPROVED_PROVIDER = "approved_provider"


class ModelHealthState(StrEnum):
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"


class ConversationModelOutput(ContractModel):
    text: str = Field(min_length=1, max_length=100_000)
    citation_ids: tuple[RecordId, ...] = ()

    @model_validator(mode="after")
    def validate_citations(self) -> ConversationModelOutput:
        if len(set(self.citation_ids)) != len(self.citation_ids):
            raise ValueError("conversation citation IDs must be unique")
        return self


class ModelGatewayHealth(ContractModel):
    state: ModelHealthState
    checked_at: AwareDatetime
    latency_ms: Annotated[int | None, Field(default=None, ge=0)]
    reason_code: QualifiedName


class ModelRequest(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    request_id: RecordId
    sensitivity: Sensitivity
    allowed_processing_locations: frozenset[ProcessingLocation]
    latency_deadline_ms: Annotated[int, Field(gt=0, le=3_600_000)]
    max_input_tokens: Annotated[int, Field(gt=0)]
    max_output_tokens: Annotated[int, Field(gt=0)]
    cost_ceiling_gbp: Annotated[float, Field(ge=0.0)]
    prompt_version: str = Field(min_length=1, max_length=128)
    input: JsonObject


class ModelResult(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    result_id: RecordId
    request_id: RecordId
    provider_id: QualifiedName
    model_id: str = Field(min_length=1, max_length=256)
    processing_location: ProcessingLocation
    output: JsonObject
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    cost_gbp: Annotated[float, Field(ge=0.0)]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    external_disclosure: bool

    @model_validator(mode="after")
    def validate_result(self) -> ModelResult:
        if self.completed_at < self.started_at:
            raise ValueError("model result cannot complete before it starts")
        if self.external_disclosure != (
            self.processing_location is ProcessingLocation.APPROVED_PROVIDER
        ):
            raise ValueError("model disclosure must match its processing location")
        return self
