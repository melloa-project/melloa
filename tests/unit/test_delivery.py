from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from melloa.adapters.fakes.client import FakeClientAdapter
from melloa.domain.base import canonical_json_bytes
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import (
    ConversationMessage,
    DeliveryState,
    MessageKind,
    MessagePart,
)
from melloa.domain.delivery import (
    AuthorizedClientDelivery,
    canonical_delivery_action,
    conversation_message_hash,
)
from melloa.domain.guardian import GuardianMode
from melloa.domain.policy import (
    AuthorizationRequest,
    DecisionEffect,
    DeterministicPolicyEvaluator,
    PolicyContext,
    RiskLevel,
    SideEffect,
    action_hash,
)
from tests.conftest import record_id


def message(fixed_time, *, number: int = 1, text: str = "hello") -> ConversationMessage:
    return ConversationMessage(
        message_id=record_id("message", number),
        thread_id=record_id("thread", 1),
        author_principal_id=record_id("intelligence", 1),
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text=text),),
        delivery_state=DeliveryState.PENDING,
        sensitivity=Sensitivity.PERSONAL,
        created_at=fixed_time,
        observed_at=fixed_time,
    )


def authorized_delivery(
    fixed_time,
    canonical_message: ConversationMessage,
    *,
    idempotency_key: str = "delivery:synthetic:1",
    attempt: int = 1,
    authorization_number: int = 1,
    adapter_id: str = "client.fake",
    destination_ref: str = "synthetic:owner",
) -> AuthorizedClientDelivery:
    action = canonical_delivery_action(
        canonical_message,
        client_adapter=adapter_id,
        destination_ref=destination_ref,
        external_destination="synthetic:owner",
        purpose="conversation.owner_reply",
        estimated_cost_gbp=Decimal("0"),
    )
    request = AuthorizationRequest(
        request_id=record_id("request", authorization_number),
        proposal_id=record_id("proposal", authorization_number),
        principal_id=canonical_message.author_principal_id,
        action=action,
        action_hash=action_hash(action),
        guardian_sequence=1,
        requested_at=fixed_time,
    )
    decision = DeterministicPolicyEvaluator().evaluate(
        request,
        PolicyContext(
            guardian_mode=GuardianMode.NORMAL,
            guardian_sequence=1,
            granted_operations=frozenset({f"{adapter_id}/messages.send"}),
            approved_action_hashes=frozenset({request.action_hash}),
            remaining_daily_budget_gbp=Decimal("1"),
        ),
        decision_id=record_id("decision", authorization_number),
        decided_at=fixed_time,
    )
    return AuthorizedClientDelivery(
        message=canonical_message,
        destination_ref=destination_ref,
        attempt=attempt,
        idempotency_key=idempotency_key,
        authorization_request=request,
        policy_decision=decision,
        authorized_at=fixed_time,
    )


def test_authorized_delivery_binds_complete_message_and_exact_decision(fixed_time) -> None:
    canonical_message = message(fixed_time)
    delivery = authorized_delivery(fixed_time, canonical_message)

    assert delivery.policy_decision.effect is DecisionEffect.ALLOW
    assert delivery.authorization_request.action.arguments["message_hash"] == (
        conversation_message_hash(canonical_message)
    )

    document = delivery.model_dump(mode="json")
    document["policy_decision"]["action_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="exact action hash"):
        AuthorizedClientDelivery.model_validate_json(canonical_json_bytes(document))

    document = delivery.model_dump(mode="json")
    document["message"]["parts"][0]["text"] = "changed after authorization"
    with pytest.raises(ValidationError, match="exact authorized action"):
        AuthorizedClientDelivery.model_validate_json(canonical_json_bytes(document))


def test_authorized_delivery_rejects_non_allow_chronology_and_action_drift(
    fixed_time,
) -> None:
    delivery = authorized_delivery(fixed_time, message(fixed_time))

    with pytest.raises(ValidationError, match="allow decision"):
        AuthorizedClientDelivery(
            **delivery.model_dump(exclude={"policy_decision"}),
            policy_decision=delivery.policy_decision.model_copy(
                update={"effect": DecisionEffect.REQUIRE_APPROVAL}
            ),
        )

    with pytest.raises(ValidationError, match="does not belong"):
        AuthorizedClientDelivery(
            **delivery.model_dump(exclude={"policy_decision"}),
            policy_decision=delivery.policy_decision.model_copy(
                update={"request_id": record_id("request", 99)}
            ),
        )

    with pytest.raises(ValidationError, match="precede its authorization request"):
        AuthorizedClientDelivery(
            **delivery.model_dump(exclude={"authorization_request"}),
            authorization_request=delivery.authorization_request.model_copy(
                update={"requested_at": fixed_time + timedelta(seconds=1)}
            ),
        )

    with pytest.raises(ValidationError, match="assembled before"):
        AuthorizedClientDelivery(
            **delivery.model_dump(exclude={"authorized_at"}),
            authorized_at=fixed_time - timedelta(microseconds=1),
        )

    with pytest.raises(ValidationError, match="expired policy decision"):
        AuthorizedClientDelivery(
            **delivery.model_dump(exclude={"policy_decision", "authorized_at"}),
            policy_decision=delivery.policy_decision.model_copy(
                update={"expires_at": fixed_time + timedelta(seconds=1)}
            ),
            authorized_at=fixed_time + timedelta(seconds=1),
        )

    changed_action = delivery.authorization_request.action.model_copy(
        update={"risk": RiskLevel.R1_REVERSIBLE_INTERNAL}
    )
    changed_request = delivery.authorization_request.model_copy(
        update={"action": changed_action, "action_hash": action_hash(changed_action)}
    )
    changed_decision = delivery.policy_decision.model_copy(
        update={"action_hash": changed_request.action_hash}
    )
    with pytest.raises(ValidationError, match="R2 risk"):
        AuthorizedClientDelivery(
            **delivery.model_dump(
                exclude={"authorization_request", "policy_decision"}
            ),
            authorization_request=changed_request,
            policy_decision=changed_decision,
        )


@pytest.mark.parametrize(
    ("action_updates", "message_pattern"),
    [
        ({"operation": "messages.edit"}, "messages.send operation"),
        ({"resource": "synthetic:other"}, "authorized resource"),
        (
            {"side_effects": (SideEffect.EXTERNAL_WRITE,)},
            "only external communication",
        ),
        (
            {"input_sensitivity": (Sensitivity.INTERNAL,)},
            "canonical message",
        ),
    ],
)
def test_authorized_delivery_rejects_operation_resource_effect_and_sensitivity_drift(
    fixed_time,
    action_updates,
    message_pattern,
) -> None:
    delivery = authorized_delivery(fixed_time, message(fixed_time))
    changed_action = delivery.authorization_request.action.model_copy(update=action_updates)
    changed_request = delivery.authorization_request.model_copy(
        update={"action": changed_action, "action_hash": action_hash(changed_action)}
    )
    changed_decision = delivery.policy_decision.model_copy(
        update={"action_hash": changed_request.action_hash}
    )

    with pytest.raises(ValidationError, match=message_pattern):
        AuthorizedClientDelivery(
            **delivery.model_dump(
                exclude={"authorization_request", "policy_decision"}
            ),
            authorization_request=changed_request,
            policy_decision=changed_decision,
        )


def test_fake_client_deduplicates_transport_with_stable_external_receipt(fixed_time) -> None:
    canonical_message = message(fixed_time)
    delivery = authorized_delivery(fixed_time, canonical_message)
    adapter = FakeClientAdapter(clock=lambda: fixed_time)

    first = adapter.send(delivery)
    replay = adapter.send(delivery)
    retry = adapter.send(delivery.model_copy(update={"attempt": 2}))

    assert replay == first
    assert first.state is DeliveryState.DELIVERED
    assert first.adapter_metadata["deduplicated"] is False
    assert retry.adapter_metadata["deduplicated"] is True
    assert retry.adapter_metadata["external_receipt_id"] == (
        first.adapter_metadata["external_receipt_id"]
    )
    assert adapter.sent == [canonical_message]
    assert adapter.receive() == ()
    assert adapter.capabilities()["network"] is False
    assert adapter.capabilities()["idempotent_send"] is True
    assert adapter.health()["status"] == "healthy"


def test_fake_client_rejects_expired_wrong_adapter_and_idempotency_conflict(
    fixed_time,
) -> None:
    canonical_message = message(fixed_time)
    delivery = authorized_delivery(fixed_time, canonical_message)
    expiring_decision = delivery.policy_decision.model_copy(
        update={"expires_at": fixed_time + timedelta(seconds=1)}
    )
    expiring_delivery = delivery.model_copy(update={"policy_decision": expiring_decision})
    expired_adapter = FakeClientAdapter(clock=lambda: fixed_time + timedelta(seconds=2))
    with pytest.raises(ValueError, match="expired"):
        expired_adapter.send(expiring_delivery)

    wrong_adapter_delivery = authorized_delivery(
        fixed_time,
        canonical_message,
        adapter_id="client.other",
    )
    with pytest.raises(ValueError, match="different client adapter"):
        FakeClientAdapter(clock=lambda: fixed_time).send(wrong_adapter_delivery)

    with pytest.raises(ValueError, match="not active yet"):
        FakeClientAdapter(clock=lambda: fixed_time - timedelta(seconds=1)).send(delivery)

    with pytest.raises(ValueError, match="unconfigured synthetic destination"):
        FakeClientAdapter(
            destination_ref="synthetic:other",
            clock=lambda: fixed_time,
        ).send(delivery)

    adapter = FakeClientAdapter(clock=lambda: fixed_time)
    adapter.send(delivery)
    conflicting = authorized_delivery(
        fixed_time,
        message(fixed_time, number=2, text="different"),
        idempotency_key=delivery.idempotency_key,
        attempt=2,
        authorization_number=2,
    )
    with pytest.raises(ValueError, match="idempotency key"):
        adapter.send(conflicting)
