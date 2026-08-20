"""Client- and channel-neutral conversation contracts."""

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
)
from melloa.domain.classification import Sensitivity
from melloa.domain.models import ModelInvocationTarget, ModelResult, ProcessingLocation
from melloa.domain.retrieval import RetrievalManifest


class ThreadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    CLOSED = "closed"


class MessageKind(StrEnum):
    TEXT = "text"


class ConversationProcessingState(StrEnum):
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    DEAD = "dead"
    CANCELLED = "cancelled"


class ConversationProcessingOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    DEAD = "dead"


class ConversationThread(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    thread_id: RecordId
    owner_id: RecordId
    intelligence_id: RecordId
    title: str = Field(min_length=1, max_length=256)
    status: ThreadStatus = ThreadStatus.ACTIVE
    sensitivity: Sensitivity
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> ConversationThread:
        if self.updated_at < self.created_at:
            raise ValueError("thread updated_at cannot precede created_at")
        return self


class ConversationDeletionReceipt(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    deletion_id: RecordId
    thread_id: RecordId
    owner_id: RecordId
    deleted_at: AwareDatetime
    active_data_deleted: Literal[True] = True
    backup_expiry_state: Literal["unknown"] = "unknown"


class MessagePart(ContractModel):
    kind: MessageKind
    text: str = Field(min_length=1, max_length=100_000)


class ConversationMessage(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    message_id: RecordId
    thread_id: RecordId
    author_principal_id: RecordId
    source_client: QualifiedName
    parts: tuple[MessagePart, ...] = Field(min_length=1)
    reply_to_message_id: RecordId | None = None
    corrects_message_id: RecordId | None = None
    citation_ids: tuple[RecordId, ...] = ()
    sensitivity: Sensitivity
    created_at: AwareDatetime
    observed_at: AwareDatetime


class ConversationTurn(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    turn_id: RecordId
    thread_id: RecordId
    triggering_message_ids: tuple[RecordId, ...] = Field(min_length=1)
    retrieval_manifest_id: RecordId | None = None
    evidence_ids: tuple[RecordId, ...] = ()
    model_run_ids: tuple[RecordId, ...] = ()
    output_message_ids: tuple[RecordId, ...] = ()
    decision_record: JsonObject
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None


class ConversationTurnInspection(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    turn: ConversationTurn
    retrieval_manifest: RetrievalManifest
    model_result: ModelResult
    output_message: ConversationMessage


class ConversationProcessingModelResult(ContractModel):
    result_id: RecordId
    request_id: RecordId
    provider_id: QualifiedName
    model_id: str = Field(min_length=1, max_length=256)
    processing_location: ProcessingLocation
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    cost_gbp: Annotated[float, Field(ge=0.0)]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    external_disclosure: bool

    @model_validator(mode="after")
    def validate_result(self) -> ConversationProcessingModelResult:
        if self.completed_at < self.started_at:
            raise ValueError("processing result cannot complete before it starts")
        return self


class ConversationProcessingAttempt(ContractModel):
    attempt_id: RecordId
    work_id: RecordId
    message_id: RecordId
    attempt: Annotated[int, Field(ge=1)]
    request_id: RecordId | None = None
    outcome: ConversationProcessingOutcome
    error_code: QualifiedName | None = None
    started_at: AwareDatetime
    completed_at: AwareDatetime
    retry_at: AwareDatetime | None = None
    retrieval_manifest_id: RecordId | None = None
    model_result_summary: ConversationProcessingModelResult | None = None
    failed_model_target: ModelInvocationTarget | None = None
    disclosed_memory_ids: tuple[RecordId, ...] = ()
    disclosed_history_message_ids: tuple[RecordId, ...] = ()
    external_disclosure: bool = False

    @model_validator(mode="after")
    def validate_attempt(self) -> ConversationProcessingAttempt:
        if self.completed_at < self.started_at:
            raise ValueError("conversation processing cannot complete before it starts")
        if len(set(self.disclosed_memory_ids)) != len(self.disclosed_memory_ids):
            raise ValueError("disclosed memory IDs must be unique")
        if len(set(self.disclosed_history_message_ids)) != len(
            self.disclosed_history_message_ids
        ):
            raise ValueError("disclosed history message IDs must be unique")
        if self.model_result_summary is not None:
            if self.request_id != self.model_result_summary.request_id:
                raise ValueError("processing request does not match its model result")
        if self.failed_model_target is not None:
            if (
                self.model_result_summary is not None
                or self.outcome is ConversationProcessingOutcome.SUCCEEDED
            ):
                raise ValueError("successful model results cannot carry a failed target")
            if self.external_disclosure != (
                self.failed_model_target.processing_location
                is ProcessingLocation.APPROVED_PROVIDER
            ):
                raise ValueError("processing disclosure does not match the failed target")
        if (
            self.model_result_summary is not None
            and self.external_disclosure
            != self.model_result_summary.external_disclosure
        ):
            raise ValueError("processing disclosure does not match the model result")
        if self.external_disclosure and self.retrieval_manifest_id is None:
            raise ValueError("external processing requires a retrieval manifest")
        if not self.external_disclosure and (
            self.disclosed_memory_ids or self.disclosed_history_message_ids
        ):
            raise ValueError("local processing cannot claim disclosed context")
        if self.outcome is ConversationProcessingOutcome.SUCCEEDED:
            if (
                self.error_code is not None
                or self.retry_at is not None
                or self.model_result_summary is None
            ):
                raise ValueError("successful processing cannot carry failure metadata")
        elif self.outcome is ConversationProcessingOutcome.RETRY_SCHEDULED:
            if self.error_code is None or self.retry_at is None:
                raise ValueError("scheduled retries require an error and retry time")
            if self.retry_at <= self.completed_at:
                raise ValueError("processing retry must follow the failed attempt")
        elif self.error_code is None or self.retry_at is not None:
            raise ValueError("dead processing requires an error without a retry time")
        return self


class ConversationProcessingResumption(ContractModel):
    resumption_id: RecordId
    work_id: RecordId
    message_id: RecordId
    requested_by: RecordId
    requested_at: AwareDatetime
    prior_attempts: Annotated[int, Field(ge=1)]
    added_attempts: Annotated[int, Field(ge=1, le=100)]


class ConversationReplyWork(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    work_id: RecordId
    thread_id: RecordId
    message_id: RecordId
    created_at: AwareDatetime
    attempts: tuple[ConversationProcessingAttempt, ...] = ()
    resumptions: tuple[ConversationProcessingResumption, ...] = ()

    @model_validator(mode="after")
    def validate_history(self) -> ConversationReplyWork:
        attempt_numbers = tuple(attempt.attempt for attempt in self.attempts)
        if attempt_numbers != tuple(sorted(set(attempt_numbers))):
            raise ValueError("processing attempts must use unique increasing numbers")
        if any(
            attempt.work_id != self.work_id or attempt.message_id != self.message_id
            for attempt in self.attempts
        ):
            raise ValueError("processing attempts must belong to their reply work")
        if len({resumption.resumption_id for resumption in self.resumptions}) != len(
            self.resumptions
        ):
            raise ValueError("processing resumption IDs must be unique")
        if any(
            resumption.work_id != self.work_id
            or resumption.message_id != self.message_id
            for resumption in self.resumptions
        ):
            raise ValueError("processing resumptions must belong to their reply work")
        if self.resumptions != tuple(
            sorted(
                self.resumptions,
                key=lambda resumption: (
                    resumption.requested_at,
                    resumption.resumption_id,
                ),
            )
        ):
            raise ValueError("processing resumptions must use deterministic time order")
        return self


class ConversationProcessingStatus(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    work_id: RecordId
    thread_id: RecordId
    message_id: RecordId
    state: ConversationProcessingState
    attempt_count: Annotated[int, Field(ge=0)]
    max_attempts: Annotated[int, Field(ge=1)]
    available_at: AwareDatetime
    lease_expires_at: AwareDatetime | None = None
    last_error_code: QualifiedName | None = None
    completed_at: AwareDatetime | None = None
    attempts: tuple[ConversationProcessingAttempt, ...] = ()
    resumptions: tuple[ConversationProcessingResumption, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> ConversationProcessingStatus:
        if self.attempt_count > self.max_attempts:
            raise ValueError("processing attempts cannot exceed the configured maximum")
        if self.attempts and self.attempt_count < self.attempts[-1].attempt:
            raise ValueError("processing count cannot precede recorded attempt history")
        if any(
            attempt.work_id != self.work_id or attempt.message_id != self.message_id
            for attempt in self.attempts
        ):
            raise ValueError("processing status contains another work item's attempts")
        if any(
            resumption.work_id != self.work_id
            or resumption.message_id != self.message_id
            for resumption in self.resumptions
        ):
            raise ValueError("processing status contains another work item's resumptions")
        if (self.state is ConversationProcessingState.RUNNING) != (
            self.lease_expires_at is not None
        ):
            raise ValueError("only running processing may hold a lease")
        latest = self.attempts[-1] if self.attempts else None
        if self.state is ConversationProcessingState.COMPLETED:
            if (
                latest is None
                or latest.outcome is not ConversationProcessingOutcome.SUCCEEDED
                or self.completed_at != latest.completed_at
                or self.last_error_code is not None
            ):
                raise ValueError("completed processing requires a successful final attempt")
        elif self.completed_at is not None:
            raise ValueError("incomplete processing cannot carry a completion time")
        if self.state is ConversationProcessingState.DEAD and (
            latest is None
            or latest.outcome is not ConversationProcessingOutcome.DEAD
            or self.last_error_code != latest.error_code
        ):
            raise ValueError("dead processing requires a terminal final attempt")
        return self


def processing_model_result(result: ModelResult) -> ConversationProcessingModelResult:
    return ConversationProcessingModelResult(
        result_id=result.result_id,
        request_id=result.request_id,
        provider_id=result.provider_id,
        model_id=result.model_id,
        processing_location=result.processing_location,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_gbp=result.cost_gbp,
        started_at=result.started_at,
        completed_at=result.completed_at,
        external_disclosure=result.external_disclosure,
    )
