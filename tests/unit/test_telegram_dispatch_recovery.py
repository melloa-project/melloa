from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from melloa.adapters.fakes.client import FakeClientAdapter
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.application.telegram import TelegramReplyDispatcher
from melloa.apps.synthetic import (
    SYNTHETIC_OWNER_ID,
    SYNTHETIC_TELEGRAM_ADAPTER_ID,
    build_synthetic_runtime,
)
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import sha256_digest
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.telegram import (
    TelegramChatType,
    TelegramInboundMessage,
    TelegramInboundUpdate,
    telegram_pairing_destination,
)
from tests.conftest import record_id


def _id_factory():
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return record_id(prefix, counts[prefix])

    return create


def _update(now: datetime, update_id: int, text: str) -> TelegramInboundUpdate:
    return TelegramInboundUpdate(
        update_id=update_id,
        message=TelegramInboundMessage(
            telegram_message_id=update_id,
            sender_user_id=1001,
            chat_id=1001,
            chat_type=TelegramChatType.PRIVATE,
            sent_at=now,
            text=text,
        ),
        received_at=now,
        raw_size_bytes=128,
        source_payload_hash=sha256_digest(f"telegram-recovery:{update_id}:{text}".encode()),
    )


def test_dispatcher_recovers_ingested_reply_after_poll_observation_is_lost(fixed_time) -> None:
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.telegram-dispatch-recovery",
        ),
        receipt_hash="sha256:" + "8" * 64,
    )
    expected_pairing_id = record_id("tgpairing", 1)
    runtime = build_synthetic_runtime(
        guardian,
        "synthetic-owner-bootstrap-token-value-0001",
        clock=lambda: fixed_time,
        id_factory=_id_factory(),
        telegram_delivery_adapter_factory=lambda _pairing_service: FakeClientAdapter(
            adapter_id=SYNTHETIC_TELEGRAM_ADAPTER_ID,
            destination_ref=telegram_pairing_destination(expected_pairing_id),
            clock=lambda: fixed_time,
            id_factory=_id_factory(),
        ),
    )
    runtime.telegram_source.add_update(_update(fixed_time, 1, "/start"))
    start_cycle = runtime.telegram_worker.poll_once()
    candidate_id = start_cycle.outcomes[0].receipt.pairing_candidate_id
    assert candidate_id is not None
    challenge = runtime.telegram_challenge_publisher.challenge_for(candidate_id)
    principal = AuthenticatedOwner(
        owner_id=SYNTHETIC_OWNER_ID,
        session_id=record_id("session", 1),
        authentication_method="auth.owner-bootstrap",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(hours=1),
    )
    pairing = runtime.telegram_pairing_service.confirm(
        principal,
        candidate_id,
        challenge.confirmation_code,
    )
    assert pairing.pairing_id == expected_pairing_id

    runtime.telegram_source.add_update(_update(fixed_time, 2, "Recover this reply."))
    text_cycle = runtime.telegram_worker.poll_once()
    trigger = text_cycle.outcomes[0].canonical_message
    assert trigger is not None
    runtime.app.state.conversation_service.process_ready()

    dispatcher = runtime.telegram_reply_dispatcher
    assert isinstance(dispatcher, TelegramReplyDispatcher)
    submitted = dispatcher.dispatch_ready()

    assert len(submitted) == 1
    assert submitted[0].destination_ref == telegram_pairing_destination(pairing.pairing_id)
    assert dispatcher.dispatch_ready() == ()
    assert dispatcher.health()["recovery_after_update_id"] == 2
