"""Exact, channel-neutral authorization contracts for outbound delivery."""

from __future__ import annotations

from decimal import Decimal
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
    canonical_json_bytes,
    sha256_digest,
)
from melloa.domain.conversation import ConversationMessage, DeliveryAttempt, DeliveryState
from melloa.domain.policy import (
    AuthorizationRequest,
    CanonicalAction,
    DecisionEffect,
    PolicyDecision,
    RiskLevel,
    SideEffect,
)


def conversation_message_hash(message: ConversationMessage) -> Sha256Digest:
    """Bind delivery authority to the complete canonical message document."""

    return sha256_digest(canonical_json_bytes(message))


def delivery_action_arguments(message: ConversationMessage) -> JsonObject:
    """Return the immutable message references included in an exact action hash."""

    return {
        "message_id": message.message_id,
        "thread_id": message.thread_id,
        "message_hash": conversation_message_hash(message),
    }


def canonical_delivery_action(
    message: ConversationMessage,
    *,
    client_adapter: QualifiedName,
    destination_ref: str,
    external_destination: str,
    purpose: str,
    estimated_cost_gbp: Decimal = Decimal("0"),
) -> CanonicalAction:
    """Build the only canonical action shape accepted by client adapters."""

    return CanonicalAction(
        capability_id=client_adapter,
        operation="messages.send",
        resource=destination_ref,
        purpose=purpose,
        arguments=delivery_action_arguments(message),
        risk=RiskLevel.R2_EXTERNAL_REPUTATIONAL,
        side_effects=(SideEffect.EXTERNAL_COMMUNICATION,),
        input_sensitivity=(message.sensitivity,),
        output_sensitivity=(message.sensitivity,),
        external_destinations=(external_destination,),
        estimated_cost_gbp=estimated_cost_gbp,
    )


class AuthorizedClientDelivery(ContractModel):
    """One adapter call bound to a complete deterministic policy decision."""

    contract_version: Literal["1.0.0"] = "1.0.0"
    message: ConversationMessage
    destination_ref: str = Field(min_length=1, max_length=512)
    attempt: Annotated[int, Field(ge=1)]
    idempotency_key: str = Field(min_length=1, max_length=256)
    authorization_request: AuthorizationRequest
    policy_decision: PolicyDecision
    authorized_at: AwareDatetime

    @model_validator(mode="after")
    def validate_exact_authority(self) -> AuthorizedClientDelivery:
        request = self.authorization_request
        decision = self.policy_decision
        action = request.action
        if decision.request_id != request.request_id:
            raise ValueError("policy decision does not belong to the authorization request")
        if decision.action_hash != request.action_hash:
            raise ValueError("policy decision does not authorize the exact action hash")
        if decision.effect is not DecisionEffect.ALLOW:
            raise ValueError("client delivery requires an allow decision")
        if request.requested_at > decision.decided_at:
            raise ValueError("policy decision cannot precede its authorization request")
        if decision.decided_at > self.authorized_at:
            raise ValueError("delivery cannot be assembled before its policy decision")
        if decision.expires_at is not None and decision.expires_at <= self.authorized_at:
            raise ValueError("delivery cannot use an expired policy decision")
        if action.operation != "messages.send":
            raise ValueError("client delivery requires the messages.send operation")
        if action.resource != self.destination_ref:
            raise ValueError("delivery destination does not match the authorized resource")
        if action.arguments != delivery_action_arguments(self.message):
            raise ValueError("delivery message does not match the exact authorized action")
        if action.risk is not RiskLevel.R2_EXTERNAL_REPUTATIONAL:
            raise ValueError("outbound client delivery must retain R2 risk classification")
        if action.side_effects != (SideEffect.EXTERNAL_COMMUNICATION,):
            raise ValueError("outbound client delivery must declare only external communication")
        expected_sensitivity = (self.message.sensitivity,)
        if (
            action.input_sensitivity != expected_sensitivity
            or action.output_sensitivity != expected_sensitivity
        ):
            raise ValueError("delivery sensitivity does not match the canonical message")
        return self


def validate_client_delivery(
    delivery: AuthorizedClientDelivery,
    *,
    expected_client_adapter: QualifiedName,
    now: AwareDatetime,
) -> None:
    """Fail closed when adapter identity, time, or exact authority no longer matches."""

    if delivery.authorization_request.action.capability_id != expected_client_adapter:
        raise ValueError("delivery authorization targets a different client adapter")
    if delivery.authorized_at > now:
        raise ValueError("delivery authorization is not active yet")
    expires_at = delivery.policy_decision.expires_at
    if expires_at is not None and expires_at <= now:
        raise ValueError("delivery policy decision has expired")


class DeliveryWorkState(StrEnum):
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    DEAD = "dead"
    CANCELLED = "cancelled"


class DeliveryWorkOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    DEAD = "dead"


class DeliveryExecutionReceipt(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    action_id: RecordId
    decision_id: RecordId
    action_hash: Sha256Digest
    capability_id: QualifiedName
    operation: QualifiedName
    delivery_id: RecordId
    executed_at: AwareDatetime
    result_summary: JsonObject = Field(default_factory=dict)


class DeliveryWorkAttempt(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    attempt_id: RecordId
    work_id: RecordId
    message_id: RecordId
    attempt: Annotated[int, Field(ge=1)]
    authorization_request_id: RecordId
    policy_decision_id: RecordId
    action_hash: Sha256Digest
    outcome: DeliveryWorkOutcome
    error_code: QualifiedName | None = None
    started_at: AwareDatetime
    completed_at: AwareDatetime
    retry_at: AwareDatetime | None = None
    adapter_receipt: DeliveryAttempt | None = None
    execution_receipt: DeliveryExecutionReceipt | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> DeliveryWorkAttempt:
        if self.completed_at < self.started_at:
            raise ValueError("delivery attempt cannot complete before it starts")
        if self.outcome is DeliveryWorkOutcome.SUCCEEDED:
            if self.error_code is not None or self.retry_at is not None:
                raise ValueError("successful delivery cannot carry failure metadata")
            if self.adapter_receipt is None or self.execution_receipt is None:
                raise ValueError("successful delivery requires adapter and execution receipts")
            if self.adapter_receipt.state not in {
                DeliveryState.SENT,
                DeliveryState.DELIVERED,
            }:
                raise ValueError("successful work requires a successful adapter receipt")
            if (
                self.adapter_receipt.message_id != self.message_id
                or self.adapter_receipt.attempt != self.attempt
            ):
                raise ValueError("adapter receipt does not match its delivery attempt")
            if (
                self.execution_receipt.delivery_id != self.adapter_receipt.delivery_id
                or self.execution_receipt.decision_id != self.policy_decision_id
                or self.execution_receipt.action_hash != self.action_hash
            ):
                raise ValueError("execution receipt does not match delivery authority")
            if (
                self.execution_receipt.capability_id
                != self.adapter_receipt.client_adapter
                or self.execution_receipt.operation != "messages.send"
            ):
                raise ValueError("execution receipt does not match the client adapter operation")
            if not (
                self.started_at
                <= self.adapter_receipt.attempted_at
                <= self.execution_receipt.executed_at
                <= self.completed_at
            ):
                raise ValueError("delivery receipt chronology is invalid")
        elif self.outcome is DeliveryWorkOutcome.RETRY_SCHEDULED:
            if self.error_code is None or self.retry_at is None:
                raise ValueError("scheduled delivery retry requires an error and retry time")
            if self.retry_at <= self.completed_at:
                raise ValueError("delivery retry must follow the failed attempt")
            if self.adapter_receipt is not None or self.execution_receipt is not None:
                raise ValueError("failed delivery cannot claim execution receipts")
        elif (
            self.error_code is None
            or self.retry_at is not None
            or self.adapter_receipt is not None
            or self.execution_receipt is not None
        ):
            raise ValueError("dead delivery requires one error without execution receipts")
        return self


class DeliveryWorkResumption(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    resumption_id: RecordId
    work_id: RecordId
    message_id: RecordId
    requested_by: RecordId
    requested_at: AwareDatetime
    prior_attempts: Annotated[int, Field(ge=1)]
    added_attempts: Annotated[int, Field(ge=1, le=100)]
    authorization_request: AuthorizationRequest
    policy_decision: PolicyDecision

    @model_validator(mode="after")
    def validate_resumption(self) -> DeliveryWorkResumption:
        _validate_policy_pair(
            self.authorization_request,
            self.policy_decision,
            authorized_at=self.requested_at,
        )
        return self


class OutboundDeliveryWork(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    work_id: RecordId
    thread_id: RecordId
    message_id: RecordId
    message_hash: Sha256Digest
    requested_by: RecordId
    client_adapter: QualifiedName
    destination_ref: str = Field(min_length=1, max_length=512)
    idempotency_key: str = Field(min_length=1, max_length=256)
    authorization_request: AuthorizationRequest
    policy_decision: PolicyDecision
    authorized_at: AwareDatetime
    created_at: AwareDatetime
    attempts: tuple[DeliveryWorkAttempt, ...] = ()
    resumptions: tuple[DeliveryWorkResumption, ...] = ()

    @model_validator(mode="after")
    def validate_history(self) -> OutboundDeliveryWork:
        _validate_policy_pair(
            self.authorization_request,
            self.policy_decision,
            authorized_at=self.authorized_at,
        )
        action = self.authorization_request.action
        if (
            action.capability_id != self.client_adapter
            or action.operation != "messages.send"
            or action.resource != self.destination_ref
            or action.arguments
            != {
                "message_id": self.message_id,
                "thread_id": self.thread_id,
                "message_hash": self.message_hash,
            }
        ):
            raise ValueError("delivery work does not match its exact canonical action")
        if self.authorized_at > self.created_at:
            raise ValueError("delivery work cannot be created before authorization")
        attempt_numbers = tuple(attempt.attempt for attempt in self.attempts)
        if attempt_numbers != tuple(sorted(set(attempt_numbers))):
            raise ValueError("delivery attempts must use unique increasing numbers")
        if any(
            attempt.work_id != self.work_id
            or attempt.message_id != self.message_id
            or attempt.action_hash != self.authorization_request.action_hash
            or (
                attempt.adapter_receipt is not None
                and (
                    attempt.adapter_receipt.client_adapter != self.client_adapter
                    or attempt.adapter_receipt.destination_ref != self.destination_ref
                )
            )
            for attempt in self.attempts
        ):
            raise ValueError("delivery attempts must belong to the same exact work")
        if len({item.resumption_id for item in self.resumptions}) != len(self.resumptions):
            raise ValueError("delivery resumption IDs must be unique")
        if self.resumptions != tuple(
            sorted(
                self.resumptions,
                key=lambda item: (item.requested_at, item.resumption_id),
            )
        ):
            raise ValueError("delivery resumptions must use deterministic time order")
        if any(
            item.work_id != self.work_id
            or item.message_id != self.message_id
            or item.authorization_request.action_hash != self.authorization_request.action_hash
            for item in self.resumptions
        ):
            raise ValueError("delivery resumptions must preserve the exact action hash")
        return self

    def current_authorization(
        self,
    ) -> tuple[AuthorizationRequest, PolicyDecision, AwareDatetime]:
        if self.resumptions:
            latest = self.resumptions[-1]
            return (
                latest.authorization_request,
                latest.policy_decision,
                latest.requested_at,
            )
        return self.authorization_request, self.policy_decision, self.authorized_at


class DeliveryWorkStatus(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    work_id: RecordId
    thread_id: RecordId
    message_id: RecordId
    client_adapter: QualifiedName
    destination_ref: str = Field(min_length=1, max_length=512)
    action_hash: Sha256Digest
    current_policy_decision_id: RecordId
    state: DeliveryWorkState
    attempt_count: Annotated[int, Field(ge=0)]
    max_attempts: Annotated[int, Field(ge=1)]
    available_at: AwareDatetime
    lease_expires_at: AwareDatetime | None = None
    last_error_code: QualifiedName | None = None
    completed_at: AwareDatetime | None = None
    attempts: tuple[DeliveryWorkAttempt, ...] = ()
    resumptions: tuple[DeliveryWorkResumption, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> DeliveryWorkStatus:
        if self.attempt_count > self.max_attempts:
            raise ValueError("delivery attempts cannot exceed the configured maximum")
        if self.attempts and self.attempt_count < self.attempts[-1].attempt:
            raise ValueError("delivery count cannot precede recorded attempt history")
        if any(
            attempt.work_id != self.work_id or attempt.message_id != self.message_id
            for attempt in self.attempts
        ):
            raise ValueError("delivery status contains another work item's attempts")
        if any(
            item.work_id != self.work_id or item.message_id != self.message_id
            for item in self.resumptions
        ):
            raise ValueError("delivery status contains another work item's resumptions")
        if (self.state is DeliveryWorkState.RUNNING) != (self.lease_expires_at is not None):
            raise ValueError("only running delivery work may hold a lease")
        latest = self.attempts[-1] if self.attempts else None
        if self.state is DeliveryWorkState.COMPLETED:
            if (
                latest is None
                or latest.outcome is not DeliveryWorkOutcome.SUCCEEDED
                or self.completed_at != latest.completed_at
                or self.last_error_code is not None
            ):
                raise ValueError("completed delivery requires a successful final attempt")
        elif self.completed_at is not None:
            raise ValueError("incomplete delivery cannot carry a completion time")
        if self.state is DeliveryWorkState.DEAD and (
            latest is None
            or latest.outcome is not DeliveryWorkOutcome.DEAD
            or self.last_error_code != latest.error_code
        ):
            raise ValueError("dead delivery requires a terminal final attempt")
        return self


def _validate_policy_pair(
    request: AuthorizationRequest,
    decision: PolicyDecision,
    *,
    authorized_at: AwareDatetime,
) -> None:
    if decision.request_id != request.request_id:
        raise ValueError("policy decision does not belong to its authorization request")
    if decision.action_hash != request.action_hash:
        raise ValueError("policy decision does not authorize the exact delivery action")
    if decision.effect is not DecisionEffect.ALLOW:
        raise ValueError("delivery work requires an allow decision")
    if request.requested_at > decision.decided_at or decision.decided_at > authorized_at:
        raise ValueError("delivery authorization chronology is invalid")
    if decision.expires_at is not None and decision.expires_at <= authorized_at:
        raise ValueError("delivery authorization is already expired")
