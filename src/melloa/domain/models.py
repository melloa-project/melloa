"""Provider-neutral model-routing and result contracts."""

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


class ModelAttemptOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ConversationModelOutput(ContractModel):
    text: str = Field(min_length=1, max_length=100_000)
    citation_ids: tuple[RecordId, ...] = ()

    @model_validator(mode="after")
    def validate_citations(self) -> ConversationModelOutput:
        if len(set(self.citation_ids)) != len(self.citation_ids):
            raise ValueError("conversation citation IDs must be unique")
        return self


class RegisteredModelRoute(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    route_id: QualifiedName
    provider_id: QualifiedName
    model_id: str = Field(min_length=1, max_length=256)
    processing_location: ProcessingLocation
    supported_modalities: frozenset[QualifiedName] = Field(min_length=1)
    quality_profiles: frozenset[QualifiedName] = Field(min_length=1)
    allowed_sensitivities: frozenset[Sensitivity] = Field(min_length=1)
    provider_retention_policies: frozenset[QualifiedName] = Field(min_length=1)
    max_input_tokens: Annotated[int, Field(gt=0)]
    max_output_tokens: Annotated[int, Field(gt=0)]
    estimated_max_cost_gbp: Annotated[float, Field(ge=0.0)]
    reliability: Annotated[float, Field(ge=0.0, le=1.0)]
    priority: Annotated[int, Field(ge=0)]
    external_disclosure: bool

    @model_validator(mode="after")
    def validate_location_disclosure(self) -> RegisteredModelRoute:
        if self.processing_location is ProcessingLocation.DEVICE and self.external_disclosure:
            raise ValueError("device routes cannot claim external disclosure")
        if (
            self.processing_location is ProcessingLocation.APPROVED_PROVIDER
            and not self.external_disclosure
        ):
            raise ValueError("approved-provider routes must record external disclosure")
        return self


class ModelRouteRequest(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    request_id: RecordId
    task_type: QualifiedName
    required_modalities: tuple[QualifiedName, ...]
    minimum_quality_profile: QualifiedName
    sensitivity: Sensitivity
    allowed_processing_locations: frozenset[ProcessingLocation]
    latency_deadline_ms: Annotated[int, Field(gt=0, le=3_600_000)]
    max_input_tokens: Annotated[int, Field(gt=0)]
    max_output_tokens: Annotated[int, Field(gt=0)]
    cost_ceiling_gbp: Annotated[float, Field(ge=0.0)]
    provider_retention_policy: QualifiedName
    minimum_reliability: Annotated[float, Field(ge=0.0, le=1.0)]
    fallback_route_ids: tuple[QualifiedName, ...]
    output_schema_id: QualifiedName
    prompt_version: str = Field(min_length=1, max_length=128)
    input: JsonObject

    @model_validator(mode="after")
    def validate_fallbacks(self) -> ModelRouteRequest:
        if len(set(self.fallback_route_ids)) != len(self.fallback_route_ids):
            raise ValueError("fallback route IDs must be unique")
        return self


class ModelRouteAttempt(ContractModel):
    route_id: QualifiedName
    provider_id: QualifiedName
    model_id: str = Field(min_length=1, max_length=256)
    processing_location: ProcessingLocation
    outcome: ModelAttemptOutcome
    started_at: AwareDatetime
    completed_at: AwareDatetime
    external_disclosure: bool
    error_code: QualifiedName | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> ModelRouteAttempt:
        if self.completed_at < self.started_at:
            raise ValueError("model route attempt cannot complete before it starts")
        if self.outcome is ModelAttemptOutcome.SUCCEEDED and self.error_code is not None:
            raise ValueError("successful model attempt cannot have an error code")
        if self.outcome is ModelAttemptOutcome.FAILED and self.error_code is None:
            raise ValueError("failed model attempt requires an error code")
        return self


class ModelResult(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    result_id: RecordId
    request_id: RecordId
    route_id: QualifiedName
    provider_id: QualifiedName
    model_id: str = Field(min_length=1, max_length=256)
    output: JsonObject
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    cost_gbp: Annotated[float, Field(ge=0.0)]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    external_disclosure: bool
    attempts: tuple[ModelRouteAttempt, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> ModelResult:
        if self.completed_at < self.started_at:
            raise ValueError("model result cannot complete before it starts")
        if self.attempts:
            successful = tuple(
                attempt
                for attempt in self.attempts
                if attempt.outcome is ModelAttemptOutcome.SUCCEEDED
            )
            if len(successful) != 1 or successful[0] != self.attempts[-1]:
                raise ValueError("model result requires exactly one final successful attempt")
            final = successful[0]
            if (final.route_id, final.provider_id, final.model_id) != (
                self.route_id,
                self.provider_id,
                self.model_id,
            ):
                raise ValueError("final attempt does not match the model result route")
            if self.external_disclosure != any(
                attempt.external_disclosure for attempt in self.attempts
            ):
                raise ValueError("model result disclosure must include every route attempt")
        return self
