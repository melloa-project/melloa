"""Deterministic policy requests, decisions, and deny-first evaluator."""

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
from melloa.domain.classification import Sensitivity
from melloa.domain.guardian import GuardianMode

Money = Annotated[Decimal, Field(ge=Decimal("0"), decimal_places=6, max_digits=18)]


class RiskLevel(StrEnum):
    R0_READ_ONLY_LOCAL = "r0_read_only_local"
    R1_REVERSIBLE_INTERNAL = "r1_reversible_internal"
    R2_EXTERNAL_REPUTATIONAL = "r2_external_reputational"
    R3_DESTRUCTIVE_PRIVILEGED = "r3_destructive_privileged"
    R4_IRREVERSIBLE_HIGH_CONSEQUENCE = "r4_irreversible_high_consequence"


class SideEffect(StrEnum):
    INTERNAL_WRITE = "internal_write"
    LOCAL_FILE_WRITE = "local_file_write"
    EXTERNAL_READ = "external_read"
    EXTERNAL_COMMUNICATION = "external_communication"
    EXTERNAL_WRITE = "external_write"
    DATA_DELETION = "data_deletion"
    CREDENTIAL_USE = "credential_use"
    CREDENTIAL_REVEAL = "credential_reveal"
    HOST_CODE_EXECUTION = "host_code_execution"
    GUARDIAN_CONTROL = "guardian_control"
    GOVERNANCE_CHANGE = "governance_change"
    AUDIT_DELETION = "audit_deletion"


class CanonicalAction(ContractModel):
    capability_id: QualifiedName
    operation: QualifiedName
    resource: str = Field(min_length=1, max_length=512)
    purpose: str = Field(min_length=1, max_length=256)
    arguments: JsonObject
    risk: RiskLevel
    side_effects: tuple[SideEffect, ...]
    input_sensitivity: tuple[Sensitivity, ...] = ()
    output_sensitivity: tuple[Sensitivity, ...] = ()
    external_destinations: tuple[str, ...] = ()
    estimated_cost_gbp: Money = Decimal("0")

    @model_validator(mode="after")
    def require_consistent_risk(self) -> CanonicalAction:
        if self.risk is RiskLevel.R0_READ_ONLY_LOCAL and self.side_effects:
            raise ValueError("R0 actions cannot declare side effects")
        external_effects = {
            SideEffect.EXTERNAL_READ,
            SideEffect.EXTERNAL_COMMUNICATION,
            SideEffect.EXTERNAL_WRITE,
        }
        if external_effects.intersection(self.side_effects) and not self.external_destinations:
            raise ValueError("external side effects require an explicit destination")
        if self.external_destinations and not external_effects.intersection(self.side_effects):
            raise ValueError("external destinations require an external side effect")
        return self


def action_hash(action: CanonicalAction) -> str:
    """Hash the complete normalized action that an approval authorizes."""

    return sha256_digest(canonical_json_bytes(action))


class AuthorizationRequest(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    request_id: RecordId
    proposal_id: RecordId
    principal_id: RecordId
    delegated_execution_id: RecordId | None = None
    action: CanonicalAction
    action_hash: Sha256Digest
    guardian_sequence: Annotated[int, Field(ge=1)]
    requested_at: AwareDatetime

    @model_validator(mode="after")
    def verify_action_hash(self) -> AuthorizationRequest:
        if self.action_hash != action_hash(self.action):
            raise ValueError("action_hash does not match the canonical action")
        return self


class DecisionEffect(StrEnum):
    DENY = "deny"
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"


class PolicyDecision(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    decision_id: RecordId
    request_id: RecordId
    action_hash: Sha256Digest
    effect: DecisionEffect
    constraints: JsonObject = Field(default_factory=dict)
    obligations: tuple[QualifiedName, ...] = ()
    policy_version: str = Field(min_length=1, max_length=128)
    reason_codes: tuple[QualifiedName, ...] = Field(min_length=1)
    decided_at: AwareDatetime
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_expiry(self) -> PolicyDecision:
        if self.expires_at is not None and self.expires_at <= self.decided_at:
            raise ValueError("decision expiry must follow decision time")
        return self


class PolicyContext(ContractModel):
    guardian_mode: GuardianMode
    guardian_sequence: Annotated[int, Field(ge=1)]
    granted_operations: frozenset[str] = frozenset()
    approved_action_hashes: frozenset[str] = frozenset()
    remaining_daily_budget_gbp: Money = Decimal("0")


class DeterministicPolicyEvaluator:
    """Small M0 evaluator whose absence or ambiguity always reduces authority."""

    _PROHIBITED_EFFECTS = frozenset(
        {
            SideEffect.AUDIT_DELETION,
            SideEffect.CREDENTIAL_REVEAL,
            SideEffect.GOVERNANCE_CHANGE,
            SideEffect.GUARDIAN_CONTROL,
            SideEffect.HOST_CODE_EXECUTION,
        }
    )

    def __init__(self, policy_version: str = "m0-deny-first-v1") -> None:
        self._policy_version = policy_version

    def evaluate(
        self,
        request: AuthorizationRequest,
        context: PolicyContext,
        *,
        decision_id: str,
        decided_at: AwareDatetime,
    ) -> PolicyDecision:
        reasons: list[str] = []
        effect = DecisionEffect.DENY
        operation_key = f"{request.action.capability_id}/{request.action.operation}"

        if context.guardian_sequence != request.guardian_sequence:
            reasons.append("guardian.sequence_mismatch")
        elif context.guardian_mode in {
            GuardianMode.STOPPED,
            GuardianMode.RECOVERY,
        }:
            reasons.append(f"guardian.{context.guardian_mode.value}")
        elif self._PROHIBITED_EFFECTS.intersection(request.action.side_effects):
            reasons.append("platform.prohibited_side_effect")
        elif Sensitivity.DEVICE_ONLY in request.action.input_sensitivity and (
            request.action.external_destinations
        ):
            reasons.append("privacy.device_only_egress")
        elif context.guardian_mode is GuardianMode.READ_ONLY and request.action.side_effects:
            reasons.append("guardian.read_only")
        elif context.guardian_mode is GuardianMode.NO_ACTIONS and request.action.side_effects:
            reasons.append("guardian.no_actions")
        elif context.guardian_mode is GuardianMode.OFFLINE and request.action.external_destinations:
            reasons.append("guardian.offline")
        elif operation_key not in context.granted_operations:
            reasons.append("grant.missing")
        elif request.action.estimated_cost_gbp > context.remaining_daily_budget_gbp:
            reasons.append("budget.daily_exceeded")
        elif request.action.risk is RiskLevel.R4_IRREVERSIBLE_HIGH_CONSEQUENCE:
            reasons.append("risk.r4_unsupported")
        elif request.action_hash in context.approved_action_hashes:
            effect = DecisionEffect.ALLOW
            reasons.append("approval.exact_action_match")
        elif request.action.risk in {
            RiskLevel.R2_EXTERNAL_REPUTATIONAL,
            RiskLevel.R3_DESTRUCTIVE_PRIVILEGED,
        }:
            effect = DecisionEffect.REQUIRE_APPROVAL
            reasons.append("approval.exact_action_required")
        else:
            effect = DecisionEffect.ALLOW
            reasons.append("policy.explicit_grant")

        obligations: tuple[str, ...] = ()
        if effect is DecisionEffect.ALLOW and request.action.side_effects:
            obligations = ("audit.side_effect_receipt",)

        return PolicyDecision(
            decision_id=decision_id,
            request_id=request.request_id,
            action_hash=request.action_hash,
            effect=effect,
            obligations=obligations,
            policy_version=self._policy_version,
            reason_codes=tuple(reasons),
            decided_at=decided_at,
        )
