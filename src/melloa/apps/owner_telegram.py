"""Persistent exact-owner Telegram conversation and delivery loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from melloa.adapters.telegram import (
    TelegramAPIError,
    TelegramBotClient,
    TelegramOwnerConfig,
    TelegramUpdate,
)
from melloa.application.conversation import ConversationService, ConversationUnavailableError
from melloa.application.self_change import OwnerSelfChangeService
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId, new_record_id, utc_now
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import ConversationProcessingState, MessageKind
from melloa.domain.models import ModelRoute
from melloa.domain.telegram import TelegramDelivery, TelegramDeliveryKind
from melloa.ports.conversation import ConversationNotFoundError, ConversationStore
from melloa.ports.telegram import TelegramStateConflictError, TelegramStore

TELEGRAM_THREAD_ID: RecordId = "thread_00000000000000000000000000000001"
_TELEGRAM_SESSION_ID: RecordId = "session_00000000000000000000000000000002"
_TELEGRAM_SOURCE = "client.telegram"
_LOGGER = logging.getLogger(__name__)
_CHUNK_SIZE = 4_000
_STATUS_LIMIT = 4_096
_CHANGE_UNAVAILABLE = "Source-change controls are unavailable in this runtime."
_NOTICE_TEXT = {
    "telegram.model_route.capable": (
        "Model route: capable. New messages use the capable model. If it is unavailable, "
        "Melli will report the failure instead of silently sending your message elsewhere."
    ),
    "telegram.model_route.economy": (
        "Model route: economy. New messages use the cheaper or open model. If it is "
        "unavailable, Melli will report the failure instead of silently changing routes."
    ),
    "telegram.notice.reply_failed": (
        "I couldn't complete that reply after retrying. Send the message again when /status "
        "shows the model is available."
    ),
    "telegram.notice.reply_cancelled": (
        "That reply was cancelled before it completed. Please send the message again."
    ),
    "telegram.notice.reply_missing": (
        "I couldn't recover the completed reply for that message. Please send it again."
    ),
}


class OwnerTelegramService:
    """Connect one durable Melli conversation to one exact private Telegram chat."""

    def __init__(
        self,
        *,
        config: TelegramOwnerConfig,
        client: TelegramBotClient,
        store: TelegramStore,
        conversation: ConversationService,
        conversation_store: ConversationStore,
        owner_id: RecordId,
        intelligence_id: RecordId,
        status_text: Callable[[], str],
        self_change_controls: OwnerSelfChangeService | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
        max_delivery_attempts: int = 8,
        delivery_lease: timedelta = timedelta(seconds=45),
        error_delay: float = 5.0,
    ) -> None:
        if not 1 <= max_delivery_attempts <= 100:
            raise ValueError("Telegram delivery attempts must be between 1 and 100")
        if delivery_lease <= timedelta(0):
            raise ValueError("Telegram delivery lease must be positive")
        if error_delay <= 0:
            raise ValueError("Telegram error delay must be positive")
        self._config = config
        self._client = client
        self._store = store
        self._conversation = conversation
        self._conversation_store = conversation_store
        self._owner_id = owner_id
        self._intelligence_id = intelligence_id
        self._status_text = status_text
        self._self_change_controls = self_change_controls
        self._clock = clock
        self._id_factory = id_factory
        self._max_delivery_attempts = max_delivery_attempts
        self._delivery_lease = delivery_lease
        self._error_delay = error_delay

    async def initialize(self) -> None:
        await self._client.verify_long_polling()
        await asyncio.to_thread(self._bind_owner_channel)

    async def run_forever(self) -> None:
        initialized = False
        while True:
            try:
                if not initialized:
                    await self.initialize()
                    initialized = True
                await self.poll_once()
                continue
            except asyncio.CancelledError:
                raise
            except TelegramAPIError as error:
                _LOGGER.warning("Telegram owner loop paused: %s", error.reason_code)
            except Exception as error:
                _LOGGER.warning(
                    "Telegram owner loop paused after an internal %s failure.",
                    type(error).__name__,
                )
            await asyncio.sleep(self._error_delay)

    async def poll_once(self) -> None:
        await self._process_ready_conversation_work()
        await asyncio.to_thread(self._reconcile_conversation_deliveries)
        await self._deliver_ready()

        channel = await asyncio.to_thread(self._store.owner_channel)
        offset = None if channel.last_update_id is None else channel.last_update_id + 1
        updates = await self._client.get_updates(
            offset=offset,
            timeout_seconds=self._config.poll_timeout_seconds,
        )
        for update in updates:
            await asyncio.to_thread(self._accept_update, update)

        await asyncio.to_thread(self._reconcile_conversation_deliveries)
        await self._deliver_ready()

    def _bind_owner_channel(self) -> None:
        self._store.bind_owner_channel(
            owner_user_id=self._config.owner_user_id,
            owner_chat_id=self._config.owner_chat_id,
            initial_model_route=ModelRoute.ECONOMY,
            now=self._clock(),
        )

    def _accept_update(self, update: TelegramUpdate) -> None:
        message = update.message
        if not self._is_exact_owner_message(update):
            self._store.advance_update(update.update_id, now=self._clock())
            return
        if message is None or message.text is None:
            self._store.advance_update(update.update_id, now=self._clock())
            return
        text = message.text.strip()
        if text == "/change" or text.startswith("/change "):
            control_text = (
                _CHANGE_UNAVAILABLE
                if self._self_change_controls is None
                else self._self_change_controls.handle(text, update_id=update.update_id)
            )
            self._store.accept_control_update(
                update_id=update.update_id,
                incoming_message_id=message.message_id,
                control_text=control_text,
                now=self._clock(),
                max_attempts=self._max_delivery_attempts,
            )
            return
        if text == "/status":
            self._store.accept_status_update(
                update_id=update.update_id,
                incoming_message_id=message.message_id,
                now=self._clock(),
                max_attempts=self._max_delivery_attempts,
            )
            return
        if text == "/model" or text.startswith("/model "):
            selected_route = {
                "/model capable": ModelRoute.CAPABLE,
                "/model economy": ModelRoute.ECONOMY,
            }.get(text)
            self._store.accept_model_route_update(
                update_id=update.update_id,
                incoming_message_id=message.message_id,
                model_route=selected_route,
                now=self._clock(),
                max_attempts=self._max_delivery_attempts,
            )
            return

        channel = self._store.owner_channel()
        model_route = channel.model_route
        conversation_text = message.text
        if text.startswith("/think ") and text.removeprefix("/think ").strip():
            model_route = ModelRoute.CAPABLE
            conversation_text = text.removeprefix("/think ").strip()

        principal = self._principal()
        self._conversation.ensure_channel_thread(
            principal,
            thread_id=TELEGRAM_THREAD_ID,
            title="Melli",
            sensitivity=Sensitivity.PERSONAL,
        )
        reply = self._conversation.post_owner_message(
            principal,
            thread_id=TELEGRAM_THREAD_ID,
            text=conversation_text,
            idempotency_key=f"telegram:update:{update.update_id}",
            source_client=_TELEGRAM_SOURCE,
            model_route=model_route,
        )
        delivery = self._store.accept_conversation_update(
            update_id=update.update_id,
            incoming_message_id=message.message_id,
            inbound_message_id=reply.inbound_message.message_id,
            now=self._clock(),
            max_attempts=self._max_delivery_attempts,
        )
        if reply.output_message is not None:
            self._store.mark_conversation_ready(
                delivery.update_id,
                response_message_id=reply.output_message.message_id,
                now=self._clock(),
            )
        elif reply.processing.state in {
            ConversationProcessingState.DEAD,
            ConversationProcessingState.CANCELLED,
        }:
            self._mark_processing_notice(delivery, reply.processing.state)

    def _reconcile_conversation_deliveries(self) -> None:
        for delivery in self._store.awaiting_conversation_deliveries(limit=100):
            if delivery.inbound_message_id is None:
                raise TelegramStateConflictError(
                    "awaiting Telegram conversation lost its inbound message"
                )
            completed = self._conversation_store.completed_turn_for_trigger(
                delivery.inbound_message_id
            )
            if completed is not None:
                self._store.mark_conversation_ready(
                    delivery.update_id,
                    response_message_id=completed.output_message.message_id,
                    now=self._clock(),
                )
                continue
            try:
                processing = self._conversation_store.reply_processing(
                    delivery.inbound_message_id
                )
            except ConversationNotFoundError:
                self._store.mark_conversation_notice_ready(
                    delivery.update_id,
                    notice_code="telegram.notice.reply_missing",
                    now=self._clock(),
                )
                continue
            if processing.state in {
                ConversationProcessingState.DEAD,
                ConversationProcessingState.CANCELLED,
            }:
                self._mark_processing_notice(delivery, processing.state)

    async def _process_ready_conversation_work(self) -> None:
        try:
            await asyncio.to_thread(self._conversation.process_ready, limit=10)
        except ConversationUnavailableError:
            return

    async def _deliver_ready(self, *, limit: int = 20) -> None:
        if not 1 <= limit <= 100:
            raise ValueError("Telegram delivery limit must be between 1 and 100")
        for _ in range(limit):
            now = self._clock()
            claim = await asyncio.to_thread(
                self._store.claim_next_delivery,
                lease_owner=self._id_factory("worker"),
                now=now,
                lease_expires_at=now + self._delivery_lease,
            )
            if claim is None:
                return
            try:
                parts = self._delivery_parts(claim)
                if claim.sent_part_count > len(parts):
                    raise TelegramStateConflictError(
                        "Telegram delivery recorded more parts than its response"
                    )
                for part in parts[claim.sent_part_count :]:
                    telegram_message_id = await self._client.send_text(
                        chat_id=self._config.owner_chat_id,
                        text=part,
                        reply_to_message_id=claim.incoming_message_id,
                    )
                    claim = await asyncio.to_thread(
                        self._store.record_delivery_part,
                        claim,
                        telegram_message_id=telegram_message_id,
                        now=self._clock(),
                    )
                await asyncio.to_thread(
                    self._store.complete_delivery,
                    claim,
                    now=self._clock(),
                )
            except TelegramAPIError as error:
                failure_time = self._clock()
                retry_seconds = max(
                    error.retry_after_seconds or 0,
                    min(300, 2 ** min(claim.attempt_count, 8)),
                )
                await asyncio.to_thread(
                    self._store.record_delivery_failure,
                    claim,
                    error_code=error.reason_code,
                    retry_at=failure_time + timedelta(seconds=retry_seconds),
                    now=failure_time,
                )

    def _delivery_parts(self, delivery: TelegramDelivery) -> tuple[str, ...]:
        if delivery.kind is TelegramDeliveryKind.STATUS:
            try:
                status = self._status_text().strip()
            except Exception:
                status = "Melli status is temporarily unavailable."
            if not status or len(status) > _STATUS_LIMIT:
                status = "Melli status is temporarily unavailable."
            return (status,)
        if delivery.kind is TelegramDeliveryKind.CONTROL:
            if delivery.control_text is None:
                raise TelegramStateConflictError("Telegram control response is missing")
            return _split_text(delivery.control_text)
        if delivery.notice_code is not None:
            try:
                return (_NOTICE_TEXT[delivery.notice_code],)
            except KeyError as error:
                raise TelegramStateConflictError(
                    "Telegram delivery has an unknown notice"
                ) from error
        if delivery.response_message_id is None:
            raise TelegramStateConflictError("Telegram conversation has no response")
        message = self._conversation_store.get_message(delivery.response_message_id)
        if (
            message.thread_id != TELEGRAM_THREAD_ID
            or message.author_principal_id != self._intelligence_id
            or message.source_client != _TELEGRAM_SOURCE
            or len(message.parts) != 1
            or message.parts[0].kind is not MessageKind.TEXT
        ):
            raise TelegramStateConflictError(
                "Telegram response escaped its canonical conversation"
            )
        return _split_text(message.parts[0].text)

    def _mark_processing_notice(
        self,
        delivery: TelegramDelivery,
        state: ConversationProcessingState,
    ) -> None:
        notice_code = (
            "telegram.notice.reply_cancelled"
            if state is ConversationProcessingState.CANCELLED
            else "telegram.notice.reply_failed"
        )
        self._store.mark_conversation_notice_ready(
            delivery.update_id,
            notice_code=notice_code,
            now=self._clock(),
        )

    def _principal(self) -> AuthenticatedOwner:
        now = self._clock()
        return AuthenticatedOwner(
            owner_id=self._owner_id,
            session_id=_TELEGRAM_SESSION_ID,
            authentication_method="auth.telegram-owner-binding",
            authenticated_at=now,
            reauthenticated_until=now + timedelta(minutes=5),
            expires_at=now + timedelta(hours=1),
        )

    def _is_exact_owner_message(self, update: TelegramUpdate) -> bool:
        message = update.message
        return bool(
            message is not None
            and message.sender is not None
            and not message.sender.is_bot
            and message.sender.id == self._config.owner_user_id
            and message.chat.type == "private"
            and message.chat.id == self._config.owner_chat_id
        )


def _split_text(text: str) -> tuple[str, ...]:
    if not text:
        raise ValueError("Telegram response cannot be empty")
    return tuple(text[offset : offset + _CHUNK_SIZE] for offset in range(0, len(text), _CHUNK_SIZE))


__all__ = ["TELEGRAM_THREAD_ID", "OwnerTelegramService"]
