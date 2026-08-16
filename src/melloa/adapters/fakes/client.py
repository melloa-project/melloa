"""In-memory client adapter with exact authorization and transport deduplication."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from melloa.domain.base import (
    JsonObject,
    QualifiedName,
    canonical_json_bytes,
    new_record_id,
    sha256_digest,
    utc_now,
)
from melloa.domain.conversation import ConversationMessage, DeliveryAttempt, DeliveryState
from melloa.domain.delivery import AuthorizedClientDelivery, validate_client_delivery
from melloa.ports.client import TransientClientDeliveryError


class FakeClientAdapter:
    def __init__(
        self,
        inbound: tuple[ConversationMessage, ...] = (),
        *,
        adapter_id: QualifiedName = "client.fake",
        destination_ref: str = "synthetic:owner",
        failure_codes: tuple[QualifiedName, ...] = (),
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._inbound = list(inbound)
        self._adapter_id = adapter_id
        self._destination_ref = destination_ref
        self._clock = clock
        self._id_factory = id_factory
        self._failure_codes = list(failure_codes)
        self._sent_by_key: dict[str, tuple[str, str]] = {}
        self._attempts: dict[tuple[str, int], tuple[str, DeliveryAttempt]] = {}
        self.sent: list[ConversationMessage] = []

    def receive(self) -> tuple[ConversationMessage, ...]:
        messages = tuple(self._inbound)
        self._inbound.clear()
        return messages

    def send(self, delivery: AuthorizedClientDelivery) -> DeliveryAttempt:
        now = self._clock()
        validate_client_delivery(
            delivery,
            expected_client_adapter=self._adapter_id,
            now=now,
        )
        if delivery.destination_ref != self._destination_ref:
            raise ValueError("delivery targets an unconfigured synthetic destination")
        if self._failure_codes:
            raise TransientClientDeliveryError(self._failure_codes.pop(0))
        fingerprint = sha256_digest(
            canonical_json_bytes(
                {
                    "message": delivery.message.model_dump(mode="json"),
                    "destination_ref": delivery.destination_ref,
                    "action_hash": delivery.authorization_request.action_hash,
                }
            )
        )
        attempt_key = (delivery.idempotency_key, delivery.attempt)
        existing_attempt = self._attempts.get(attempt_key)
        if existing_attempt is not None:
            existing_fingerprint, receipt = existing_attempt
            if existing_fingerprint != fingerprint:
                raise ValueError("delivery attempt idempotency key was reused with other content")
            return receipt

        existing_delivery = self._sent_by_key.get(delivery.idempotency_key)
        deduplicated = existing_delivery is not None
        if existing_delivery is None:
            external_receipt_id = self._id_factory("clientreceipt")
            self._sent_by_key[delivery.idempotency_key] = (
                fingerprint,
                external_receipt_id,
            )
            self.sent.append(delivery.message)
        else:
            existing_fingerprint, external_receipt_id = existing_delivery
            if existing_fingerprint != fingerprint:
                raise ValueError("delivery idempotency key was reused with other content")

        receipt = DeliveryAttempt(
            delivery_id=self._id_factory("delivery"),
            message_id=delivery.message.message_id,
            client_adapter=self._adapter_id,
            destination_ref=delivery.destination_ref,
            attempt=delivery.attempt,
            state=DeliveryState.DELIVERED,
            attempted_at=now,
            adapter_metadata={
                "action_hash": delivery.authorization_request.action_hash,
                "authorization_id": delivery.policy_decision.decision_id,
                "deduplicated": deduplicated,
                "external_receipt_id": external_receipt_id,
            },
        )
        self._attempts[attempt_key] = (fingerprint, receipt)
        return receipt

    def capabilities(self) -> JsonObject:
        return {
            "transport": "synthetic",
            "network": False,
            "attachments": False,
            "idempotent_send": True,
        }

    def health(self) -> JsonObject:
        return {
            "status": "healthy",
            "queued_inbound": len(self._inbound),
            "planned_failures": len(self._failure_codes),
        }
