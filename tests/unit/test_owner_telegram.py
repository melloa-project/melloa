from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock

from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.telegram import (
    TelegramAPIError,
    TelegramBotIdentity,
    TelegramOwnerConfig,
    TelegramUpdate,
)
from melloa.application.conversation import ConversationService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.owner_telegram import TELEGRAM_THREAD_ID, OwnerTelegramService
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.models import ModelRoute
from melloa.domain.telegram import (
    TelegramDelivery,
    TelegramDeliveryKind,
    TelegramDeliveryState,
    TelegramOwnerChannel,
)
from tests.conftest import record_id

_OWNER_USER_ID = 1_234_567
_OWNER_CHAT_ID = 7_654_321


class FakeTelegramClient:
    def __init__(self, batches: list[tuple[TelegramUpdate, ...]] | None = None) -> None:
        self.batches = [] if batches is None else batches
        self.polls: list[tuple[int | None, int]] = []
        self.sent: list[dict[str, object]] = []
        self.send_error: TelegramAPIError | None = None
        self.verified = False

    async def verify_long_polling(self) -> TelegramBotIdentity:
        self.verified = True
        return TelegramBotIdentity(id=99, is_bot=True, username="melli_test_bot")

    async def get_updates(
        self,
        *,
        offset: int | None,
        timeout_seconds: int,
    ) -> tuple[TelegramUpdate, ...]:
        self.polls.append((offset, timeout_seconds))
        return () if not self.batches else self.batches.pop(0)

    async def send_text(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> int:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        return 800 + len(self.sent)


def _conversation(
    fixed_time: datetime,
    *,
    response_text: str = "Synthetic Telegram reply.",
) -> tuple[ConversationService, InMemoryConversationStore, FakeModelGateway]:
    owner_id = record_id("owner", 1)
    store = InMemoryConversationStore()
    model = FakeModelGateway(
        {"text": response_text, "citation_ids": []},
        clock=lambda: fixed_time,
    )
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="telegram-test-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.test",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    service = ConversationService(
        owner_id=owner_id,
        intelligence_id=record_id("intelligence", 1),
        store=store,
        model_gateway=model,
        retriever=PolicyConstrainedRetriever(
            InMemoryMemoryRepository(()),
            clock=lambda: fixed_time,
        ),
        guardian_reader=guardian,
        clock=lambda: fixed_time,
    )
    return service, store, model


def _service(
    fixed_time: datetime,
    *,
    telegram_store: Mock,
    client: FakeTelegramClient,
    response_text: str = "Synthetic Telegram reply.",
    status_text: str = "Melli status\nOverall: healthy",
) -> tuple[OwnerTelegramService, InMemoryConversationStore, FakeModelGateway]:
    conversation, conversation_store, model = _conversation(
        fixed_time,
        response_text=response_text,
    )
    telegram_store.owner_channel.return_value = _channel(
        fixed_time,
        last_update_id=None,
    )
    service = OwnerTelegramService(
        config=TelegramOwnerConfig(
            owner_user_id=_OWNER_USER_ID,
            owner_chat_id=_OWNER_CHAT_ID,
            poll_timeout_seconds=3,
        ),
        client=client,  # type: ignore[arg-type]
        store=telegram_store,
        conversation=conversation,
        conversation_store=conversation_store,
        owner_id=record_id("owner", 1),
        intelligence_id=record_id("intelligence", 1),
        status_text=lambda: status_text,
        clock=lambda: fixed_time,
        id_factory=lambda prefix: record_id(prefix, 90),
    )
    return service, conversation_store, model


def _update(
    update_id: int,
    *,
    text: str | None,
    user_id: int = _OWNER_USER_ID,
    chat_id: int = _OWNER_CHAT_ID,
    chat_type: str = "private",
) -> TelegramUpdate:
    return TelegramUpdate.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id + 100,
                "from": {"id": user_id, "is_bot": False},
                "chat": {"id": chat_id, "type": chat_type},
                "date": 1_777_000_000,
                "text": text,
            },
        },
        strict=True,
    )


def _channel(
    fixed_time: datetime,
    *,
    last_update_id: int | None,
    model_route: ModelRoute = ModelRoute.ECONOMY,
) -> TelegramOwnerChannel:
    return TelegramOwnerChannel(
        owner_user_id=_OWNER_USER_ID,
        owner_chat_id=_OWNER_CHAT_ID,
        model_route=model_route,
        last_update_id=last_update_id,
        created_at=fixed_time,
        updated_at=fixed_time,
    )


def _delivery(
    fixed_time: datetime,
    *,
    update_id: int,
    kind: TelegramDeliveryKind,
    state: TelegramDeliveryState,
    inbound_message_id: str | None = None,
    response_message_id: str | None = None,
    notice_code: str | None = None,
    sent_ids: tuple[int, ...] = (),
    attempt_count: int = 0,
) -> TelegramDelivery:
    running = state is TelegramDeliveryState.RUNNING
    return TelegramDelivery(
        update_id=update_id,
        incoming_message_id=update_id + 100,
        kind=kind,
        inbound_message_id=inbound_message_id,
        response_message_id=response_message_id,
        notice_code=notice_code,
        state=state,
        sent_part_count=len(sent_ids),
        telegram_message_ids=sent_ids,
        attempt_count=attempt_count,
        max_attempts=8,
        available_at=fixed_time,
        lease_owner=record_id("worker", 90) if running else None,
        lease_expires_at=fixed_time + timedelta(seconds=45) if running else None,
        created_at=fixed_time,
        updated_at=fixed_time,
    )


def test_only_exact_owner_private_chat_enters_one_canonical_conversation(fixed_time) -> None:
    telegram_store = Mock()
    client = FakeTelegramClient()
    service, conversation_store, model = _service(
        fixed_time,
        telegram_store=telegram_store,
        client=client,
    )

    def accept(**kwargs):
        return _delivery(
            fixed_time,
            update_id=kwargs["update_id"],
            kind=TelegramDeliveryKind.CONVERSATION,
            state=TelegramDeliveryState.AWAITING_REPLY,
            inbound_message_id=kwargs["inbound_message_id"],
        )

    telegram_store.accept_conversation_update.side_effect = accept

    service._accept_update(_update(10, text="Hello Melli"))
    service._accept_update(_update(11, text="Wrong sender", user_id=999))
    service._accept_update(_update(12, text="Wrong chat", chat_id=999))
    service._accept_update(_update(13, text="Wrong chat type", chat_type="group"))
    service._accept_update(_update(10, text="Hello Melli"))

    messages = conversation_store.list_messages(TELEGRAM_THREAD_ID)
    assert [message.parts[0].text for message in messages] == [
        "Hello Melli",
        "Synthetic Telegram reply.",
    ]
    assert all(message.source_client == "client.telegram" for message in messages)
    assert len(model.requests) == 1
    assert model.requests[0].route is ModelRoute.ECONOMY
    assert telegram_store.advance_update.call_count == 3
    assert telegram_store.accept_conversation_update.call_count == 2
    assert telegram_store.mark_conversation_ready.call_count == 2


def test_model_route_commands_do_not_enter_conversation(fixed_time) -> None:
    telegram_store = Mock()
    client = FakeTelegramClient()
    service, conversation_store, model = _service(
        fixed_time,
        telegram_store=telegram_store,
        client=client,
    )
    capable_notice = _delivery(
        fixed_time,
        update_id=20,
        kind=TelegramDeliveryKind.MODEL_ROUTE,
        state=TelegramDeliveryState.READY,
        notice_code="telegram.model_route.capable",
    )
    telegram_store.accept_model_route_update.return_value = capable_notice

    service._accept_update(_update(20, text="/model capable"))

    telegram_store.accept_model_route_update.assert_called_once_with(
        update_id=20,
        incoming_message_id=120,
        model_route=ModelRoute.CAPABLE,
        now=fixed_time,
        max_attempts=8,
    )
    assert conversation_store.list_threads(record_id("owner", 1)) == ()
    assert model.requests == []
    assert "Model route: capable" in service._delivery_parts(capable_notice)[0]
    assert "silently" in service._delivery_parts(capable_notice)[0]


def test_think_uses_capable_once_without_changing_saved_route(fixed_time) -> None:
    telegram_store = Mock()
    client = FakeTelegramClient()
    service, conversation_store, model = _service(
        fixed_time,
        telegram_store=telegram_store,
        client=client,
    )

    def accept(**kwargs):
        return _delivery(
            fixed_time,
            update_id=kwargs["update_id"],
            kind=TelegramDeliveryKind.CONVERSATION,
            state=TelegramDeliveryState.AWAITING_REPLY,
            inbound_message_id=kwargs["inbound_message_id"],
        )

    telegram_store.accept_conversation_update.side_effect = accept

    service._accept_update(_update(21, text="/think  Consider this carefully"))

    messages = conversation_store.list_messages(TELEGRAM_THREAD_ID)
    assert messages[0].parts[0].text == "Consider this carefully"
    assert messages[0].model_route is ModelRoute.CAPABLE
    assert model.requests[0].route is ModelRoute.CAPABLE
    assert telegram_store.owner_channel.return_value.model_route is ModelRoute.ECONOMY


def test_poll_uses_durable_offset_and_status_never_enters_conversation(fixed_time) -> None:
    telegram_store = Mock()
    client = FakeTelegramClient([(_update(41, text="/status"),)])
    service, conversation_store, _model = _service(
        fixed_time,
        telegram_store=telegram_store,
        client=client,
    )
    status_ready = _delivery(
        fixed_time,
        update_id=41,
        kind=TelegramDeliveryKind.STATUS,
        state=TelegramDeliveryState.READY,
    )
    status_claim = _delivery(
        fixed_time,
        update_id=41,
        kind=TelegramDeliveryKind.STATUS,
        state=TelegramDeliveryState.RUNNING,
        attempt_count=1,
    )
    status_sent_part = _delivery(
        fixed_time,
        update_id=41,
        kind=TelegramDeliveryKind.STATUS,
        state=TelegramDeliveryState.RUNNING,
        sent_ids=(801,),
        attempt_count=1,
    )
    telegram_store.owner_channel.return_value = _channel(fixed_time, last_update_id=40)
    telegram_store.awaiting_conversation_deliveries.return_value = ()
    telegram_store.accept_status_update.return_value = status_ready
    telegram_store.claim_next_delivery.side_effect = [None, status_claim, None]
    telegram_store.record_delivery_part.return_value = status_sent_part

    asyncio.run(service.initialize())
    asyncio.run(service.poll_once())

    assert client.verified is True
    assert client.polls == [(41, 3)]
    assert client.sent == [
        {
            "chat_id": _OWNER_CHAT_ID,
            "text": "Melli status\nOverall: healthy",
            "reply_to_message_id": 141,
        }
    ]
    assert conversation_store.list_threads(record_id("owner", 1)) == ()
    telegram_store.bind_owner_channel.assert_called_once()
    telegram_store.accept_status_update.assert_called_once()
    telegram_store.complete_delivery.assert_called_once_with(
        status_sent_part,
        now=fixed_time,
    )


def test_completed_conversation_is_reconciled_after_acceptance_restart(fixed_time) -> None:
    telegram_store = Mock()
    client = FakeTelegramClient()
    service, conversation_store, _model = _service(
        fixed_time,
        telegram_store=telegram_store,
        client=client,
    )

    def accept(**kwargs):
        return _delivery(
            fixed_time,
            update_id=kwargs["update_id"],
            kind=TelegramDeliveryKind.CONVERSATION,
            state=TelegramDeliveryState.AWAITING_REPLY,
            inbound_message_id=kwargs["inbound_message_id"],
        )

    telegram_store.accept_conversation_update.side_effect = accept
    service._accept_update(_update(50, text="Please survive a restart"))
    messages = conversation_store.list_messages(TELEGRAM_THREAD_ID)
    awaiting = _delivery(
        fixed_time,
        update_id=50,
        kind=TelegramDeliveryKind.CONVERSATION,
        state=TelegramDeliveryState.AWAITING_REPLY,
        inbound_message_id=messages[0].message_id,
    )
    telegram_store.awaiting_conversation_deliveries.return_value = (awaiting,)
    telegram_store.mark_conversation_ready.reset_mock()

    service._reconcile_conversation_deliveries()

    telegram_store.mark_conversation_ready.assert_called_once_with(
        50,
        response_message_id=messages[1].message_id,
        now=fixed_time,
    )


def test_partial_multichunk_reply_resumes_without_resending_recorded_part(fixed_time) -> None:
    telegram_store = Mock()
    client = FakeTelegramClient()
    service, conversation_store, _model = _service(
        fixed_time,
        telegram_store=telegram_store,
        client=client,
        response_text="A" * 4_010,
    )

    def accept(**kwargs):
        return _delivery(
            fixed_time,
            update_id=kwargs["update_id"],
            kind=TelegramDeliveryKind.CONVERSATION,
            state=TelegramDeliveryState.AWAITING_REPLY,
            inbound_message_id=kwargs["inbound_message_id"],
        )

    telegram_store.accept_conversation_update.side_effect = accept
    service._accept_update(_update(60, text="Give me the long answer"))
    messages = conversation_store.list_messages(TELEGRAM_THREAD_ID)
    claim = _delivery(
        fixed_time,
        update_id=60,
        kind=TelegramDeliveryKind.CONVERSATION,
        state=TelegramDeliveryState.RUNNING,
        inbound_message_id=messages[0].message_id,
        response_message_id=messages[1].message_id,
        sent_ids=(700,),
        attempt_count=2,
    )
    sent_part = _delivery(
        fixed_time,
        update_id=60,
        kind=TelegramDeliveryKind.CONVERSATION,
        state=TelegramDeliveryState.RUNNING,
        inbound_message_id=messages[0].message_id,
        response_message_id=messages[1].message_id,
        sent_ids=(700, 801),
        attempt_count=2,
    )
    telegram_store.claim_next_delivery.side_effect = [claim, None]
    telegram_store.record_delivery_part.return_value = sent_part

    asyncio.run(service._deliver_ready())

    assert client.sent == [
        {
            "chat_id": _OWNER_CHAT_ID,
            "text": "A" * 10,
            "reply_to_message_id": 160,
        }
    ]
    telegram_store.complete_delivery.assert_called_once_with(sent_part, now=fixed_time)


def test_rate_limit_schedules_redacted_durable_retry(fixed_time) -> None:
    telegram_store = Mock()
    client = FakeTelegramClient()
    client.send_error = TelegramAPIError(
        "telegram.rate_limited",
        retry_after_seconds=17,
    )
    service, _conversation_store, _model = _service(
        fixed_time,
        telegram_store=telegram_store,
        client=client,
    )
    claim = _delivery(
        fixed_time,
        update_id=70,
        kind=TelegramDeliveryKind.STATUS,
        state=TelegramDeliveryState.RUNNING,
        attempt_count=1,
    )
    telegram_store.claim_next_delivery.side_effect = [claim, None]

    asyncio.run(service._deliver_ready())

    telegram_store.record_delivery_failure.assert_called_once_with(
        claim,
        error_code="telegram.rate_limited",
        retry_at=fixed_time + timedelta(seconds=17),
        now=fixed_time,
    )
    telegram_store.complete_delivery.assert_not_called()
