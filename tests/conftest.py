from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from melloa.domain.audit import AuditContent
from melloa.domain.base import canonical_json_bytes, sha256_digest
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.events import (
    EventEnvelope,
    EventIntegrity,
    EventProducer,
    EventSource,
)
from melloa.domain.policy import (
    AuthorizationRequest,
    CanonicalAction,
    RiskLevel,
    SideEffect,
    action_hash,
)


def record_id(prefix: str, number: int) -> str:
    return f"{prefix}_{number:032x}"


@pytest.fixture
def fixed_time() -> datetime:
    return datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def event(fixed_time: datetime) -> EventEnvelope:
    payload = {"zone": "door", "direction": "in"}
    return EventEnvelope(
        event_id=record_id("event", 1),
        event_type="interpretation.person_entered.v1",
        schema_version="1.0.0",
        occurred_at=fixed_time,
        recorded_at=fixed_time,
        subject_ids=(record_id("subject", 1),),
        source=EventSource(
            capability_id="camera.synthetic-room",
            observation_ids=(record_id("observation", 1),),
            execution_id=record_id("execution", 1),
        ),
        producer=EventProducer(component="perception.synthetic", version="0.0.1"),
        epistemic_status=EpistemicStatus.INTERPRETATION,
        confidence=0.82,
        sensitivity=Sensitivity.HIGHLY_SENSITIVE,
        trust=TrustLabel.UNTRUSTED_SENSOR_DERIVED,
        retention_policy="retention.synthetic-short",
        payload=payload,
        integrity=EventIntegrity(payload_hash=sha256_digest(canonical_json_bytes(payload))),
    )


@pytest.fixture
def audit_content(fixed_time: datetime, event: EventEnvelope) -> AuditContent:
    return AuditContent(
        audit_id=record_id("audit", 1),
        event_type="audit.event_appended.v1",
        occurred_at=fixed_time,
        actor_id=record_id("intelligence", 1),
        action="events.append",
        object_ids=(event.event_id,),
        metadata={"synthetic": True},
    )


@pytest.fixture
def external_action() -> CanonicalAction:
    return CanonicalAction(
        capability_id="client.fake",
        operation="messages.send",
        resource="synthetic:owner",
        purpose="conversation.owner_reply",
        arguments={"text": "hello"},
        risk=RiskLevel.R2_EXTERNAL_REPUTATIONAL,
        side_effects=(SideEffect.EXTERNAL_COMMUNICATION,),
        input_sensitivity=(Sensitivity.PERSONAL,),
        output_sensitivity=(Sensitivity.PERSONAL,),
        external_destinations=("synthetic:owner",),
        estimated_cost_gbp=Decimal("0.001"),
    )


@pytest.fixture
def authorization_request(
    fixed_time: datetime,
    external_action: CanonicalAction,
) -> AuthorizationRequest:
    return AuthorizationRequest(
        request_id=record_id("request", 1),
        proposal_id=record_id("proposal", 1),
        principal_id=record_id("intelligence", 1),
        action=external_action,
        action_hash=action_hash(external_action),
        guardian_sequence=3,
        requested_at=fixed_time,
    )
