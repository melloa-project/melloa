from __future__ import annotations

from argparse import Namespace
from datetime import timedelta

import pytest

from melloa.adapters.postgres.mvp import _parse_document, validate_private_database_dsn
from melloa.adapters.postgres.telegram import (
    PostgresTelegramPairingStateStore,
    PostgresTelegramPollStateStore,
)
from melloa.apps import postgres_mvp
from melloa.apps.synthetic import (
    SYNTHETIC_INTELLIGENCE_ID,
    SYNTHETIC_OWNER_ID,
    synthetic_seed_assertion,
)
from melloa.domain.identity import OwnerIdentity
from melloa.domain.telegram import (
    TelegramChatType,
    TelegramInboundMessage,
    TelegramInboundUpdate,
    TelegramIngestionReceipt,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramPollState,
    TelegramUpdateDisposition,
    telegram_update_fingerprint,
)


@pytest.mark.parametrize(
    "dsn",
    [
        "dbname=melloa",
        "host=/run/postgresql dbname=melloa",
        "host=localhost dbname=melloa",
        "host=127.0.0.1 dbname=melloa",
        "host=10.20.30.40 dbname=melloa",
        "host=100.64.1.2 dbname=melloa",
        "host=fd00::1 dbname=melloa",
        "hostaddr=192.168.1.10 dbname=melloa",
    ],
)
def test_private_database_dsn_accepts_only_explicit_private_targets(dsn: str) -> None:
    assert validate_private_database_dsn(dsn) == dsn


@pytest.mark.parametrize(
    "dsn",
    [
        "service=owner-database",
        "host=db.example.com dbname=melloa",
        "host=8.8.8.8 dbname=melloa",
        "host=0.0.0.0 dbname=melloa",
        "hostaddr=2001:4860:4860::8888 dbname=melloa",
    ],
)
def test_private_database_dsn_rejects_opaque_or_public_targets(dsn: str) -> None:
    with pytest.raises(ValueError, match=r"database|public"):
        validate_private_database_dsn(dsn)


def test_postgres_mvp_assembly_adds_explicit_partial_persistence_status(
    monkeypatch,
    fixed_time,
) -> None:
    conversation_store = object()
    memory_store = object()
    delivery_store = object()
    event_audit_store = object()
    telegram_pairing_store = object()
    telegram_poll_state_store = object()

    def health_reader():
        return None

    captured: dict[str, object] = {}

    def build(*connections, **kwargs):
        captured.update(connections=connections, **kwargs)
        return Namespace(
            seeded_at=fixed_time,
            conversation_store=conversation_store,
            memory_store=memory_store,
            delivery_store=delivery_store,
            event_audit_store=event_audit_store,
            telegram_pairing_store=telegram_pairing_store,
            telegram_poll_state_store=telegram_poll_state_store,
            database_health_reader=health_reader,
        )

    monkeypatch.setattr(postgres_mvp, "build_postgres_mvp_store_bundle", build)
    connections = (object(), object(), object(), object(), object())
    stores = postgres_mvp.build_postgres_mvp_stores(
        *connections,
        clock=lambda: fixed_time,
        id_factory=lambda prefix: f"{prefix}_test",
    )

    assert captured["connections"] == connections
    assert captured["owner_id"] == SYNTHETIC_OWNER_ID
    assert captured["intelligence_id"] == SYNTHETIC_INTELLIGENCE_ID
    assert captured["assertion_factory"] is synthetic_seed_assertion
    assert stores.seeded_at == fixed_time
    assert stores.conversation_store is conversation_store
    assert stores.memory_store is memory_store
    assert stores.delivery_store is delivery_store
    assert stores.event_audit_store is event_audit_store
    assert stores.telegram_pairing_store is telegram_pairing_store
    assert stores.telegram_poll_state_store is telegram_poll_state_store
    assert stores.database_health_reader is health_reader
    assert stores.status.mode == "postgresql-partial-preview"
    assert any("conversations" in item for item in stores.status.durable_state)
    assert any("Telegram" in item for item in stores.status.durable_state)
    assert any("audit" in item for item in stores.status.durable_state)
    assert any("not yet assembled" in item for item in stores.status.ephemeral_state)
    assert "authentication sessions" in stores.status.ephemeral_state


def test_postgres_mvp_jsonb_documents_round_trip_through_strict_contracts(
    fixed_time,
) -> None:
    owner = OwnerIdentity(owner_id=SYNTHETIC_OWNER_ID, created_at=fixed_time)
    assert _parse_document(OwnerIdentity, owner.model_dump(mode="json")) == owner

    candidate = TelegramPairingCandidate(
        candidate_id="candidate_11111111111111111111111111111111",
        owner_id=SYNTHETIC_OWNER_ID,
        update_id=1,
        telegram_user_id=42,
        telegram_chat_id=42,
        confirmation_code_hash="sha256:" + "1" * 64,
        observed_at=fixed_time,
        expires_at=fixed_time + timedelta(minutes=5),
    )
    pairing = TelegramOwnerPairing(
        pairing_id="pairing_11111111111111111111111111111111",
        candidate_id=candidate.candidate_id,
        owner_id=SYNTHETIC_OWNER_ID,
        telegram_user_id=42,
        telegram_chat_id=42,
        confirmed_by_owner_id=SYNTHETIC_OWNER_ID,
        confirmed_at=fixed_time + timedelta(seconds=1),
    )
    update = TelegramInboundUpdate(
        update_id=2,
        message=TelegramInboundMessage(
            telegram_message_id=2,
            sender_user_id=42,
            chat_id=42,
            chat_type=TelegramChatType.PRIVATE,
            sent_at=fixed_time + timedelta(seconds=1),
            text="Persist this update.",
        ),
        received_at=fixed_time + timedelta(seconds=2),
        raw_size_bytes=128,
        source_payload_hash="sha256:" + "2" * 64,
    )
    receipt = TelegramIngestionReceipt(
        receipt_id="telegramreceipt_11111111111111111111111111111111",
        adapter_id="client.telegram.synthetic",
        update_id=update.update_id,
        update_fingerprint=telegram_update_fingerprint(update),
        disposition=TelegramUpdateDisposition.INGESTED,
        recorded_at=fixed_time + timedelta(seconds=2),
        canonical_message_id="message_11111111111111111111111111111111",
        pairing_id=pairing.pairing_id,
    )
    state = TelegramPollState(
        adapter_id="client.telegram.synthetic",
        next_offset=3,
        revision=1,
        last_update_id=update.update_id,
        last_receipt_id=receipt.receipt_id,
        updated_at=fixed_time + timedelta(seconds=2),
    )

    assert PostgresTelegramPairingStateStore._parse_candidate(
        candidate.model_dump(mode="json")
    ) == candidate
    assert PostgresTelegramPairingStateStore._parse_pairing_row(
        (pairing.model_dump(mode="json"), None)
    ) == pairing
    assert PostgresTelegramPollStateStore._parse_update(
        update.model_dump(mode="json")
    ) == update
    assert PostgresTelegramPollStateStore._parse_receipt(
        receipt.model_dump(mode="json")
    ) == receipt
    assert PostgresTelegramPollStateStore._parse_state(
        state.model_dump(mode="json")
    ) == state
