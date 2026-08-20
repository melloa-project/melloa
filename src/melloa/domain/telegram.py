"""Durable state for the single-owner Telegram delivery loop."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import AwareDatetime, ContractModel, QualifiedName, RecordId
from melloa.domain.models import ModelRoute


class TelegramDeliveryKind(StrEnum):
    CONVERSATION = "conversation"
    MODEL_ROUTE = "model_route"
    STATUS = "status"


class TelegramDeliveryState(StrEnum):
    AWAITING_REPLY = "awaiting_reply"
    READY = "ready"
    RUNNING = "running"
    SENT = "sent"
    DEAD = "dead"


class TelegramOwnerChannel(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    owner_user_id: Annotated[int, Field(gt=0, le=(1 << 63) - 1)]
    owner_chat_id: Annotated[int, Field(gt=0, le=(1 << 63) - 1)]
    model_route: ModelRoute = ModelRoute.ECONOMY
    last_update_id: Annotated[int, Field(ge=0)] | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> TelegramOwnerChannel:
        if self.updated_at < self.created_at:
            raise ValueError("Telegram channel update cannot precede creation")
        return self


class TelegramDelivery(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    update_id: Annotated[int, Field(ge=0)]
    incoming_message_id: Annotated[int, Field(ge=0)]
    kind: TelegramDeliveryKind
    inbound_message_id: RecordId | None = None
    response_message_id: RecordId | None = None
    notice_code: QualifiedName | None = None
    state: TelegramDeliveryState
    sent_part_count: Annotated[int, Field(ge=0)] = 0
    telegram_message_ids: tuple[Annotated[int, Field(ge=0)], ...] = ()
    attempt_count: Annotated[int, Field(ge=0)] = 0
    max_attempts: Annotated[int, Field(ge=1, le=100)]
    available_at: AwareDatetime
    lease_owner: RecordId | None = None
    lease_expires_at: AwareDatetime | None = None
    last_error_code: QualifiedName | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    delivered_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_delivery(self) -> TelegramDelivery:
        if self.updated_at < self.created_at or self.available_at < self.created_at:
            raise ValueError("Telegram delivery timestamps are inconsistent")
        if self.attempt_count > self.max_attempts:
            raise ValueError("Telegram delivery attempts exceed their maximum")
        if self.sent_part_count != len(self.telegram_message_ids):
            raise ValueError("Telegram sent-part count must match its message IDs")
        if (self.state is TelegramDeliveryState.RUNNING) != (
            self.lease_owner is not None and self.lease_expires_at is not None
        ):
            raise ValueError("only a running Telegram delivery may hold a lease")
        if self.kind is TelegramDeliveryKind.CONVERSATION:
            if self.inbound_message_id is None:
                raise ValueError("conversation delivery requires its canonical inbound message")
            if self.state is TelegramDeliveryState.AWAITING_REPLY:
                if self.response_message_id is not None or self.notice_code is not None:
                    raise ValueError("awaiting conversation cannot already have a response")
            elif (self.response_message_id is None) == (self.notice_code is None):
                raise ValueError("conversation delivery requires one response source")
        elif self.kind is TelegramDeliveryKind.STATUS and any(
            value is not None
            for value in (
                self.inbound_message_id,
                self.response_message_id,
                self.notice_code,
            )
        ):
            raise ValueError("status delivery cannot reference conversation content")
        elif self.kind is TelegramDeliveryKind.MODEL_ROUTE:
            expected_notices = {
                "telegram.model_route.capable",
                "telegram.model_route.economy",
            }
            if (
                self.inbound_message_id is not None
                or self.response_message_id is not None
                or self.notice_code not in expected_notices
                or self.state is TelegramDeliveryState.AWAITING_REPLY
            ):
                raise ValueError("model-route delivery must contain one durable route notice")
        if self.state is TelegramDeliveryState.SENT:
            if self.delivered_at is None or not self.telegram_message_ids:
                raise ValueError("sent Telegram delivery requires delivery evidence")
        elif self.delivered_at is not None:
            raise ValueError("incomplete Telegram delivery cannot have a delivery time")
        return self


__all__ = [
    "TelegramDelivery",
    "TelegramDeliveryKind",
    "TelegramDeliveryState",
    "TelegramOwnerChannel",
]
