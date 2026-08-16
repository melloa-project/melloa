from __future__ import annotations

from argparse import Namespace

import pytest

from melloa.adapters.postgres.mvp import validate_private_database_dsn
from melloa.apps import postgres_mvp
from melloa.apps.synthetic import (
    SYNTHETIC_INTELLIGENCE_ID,
    SYNTHETIC_OWNER_ID,
    synthetic_seed_assertion,
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
            telegram_pairing_store=telegram_pairing_store,
            telegram_poll_state_store=telegram_poll_state_store,
            database_health_reader=health_reader,
        )

    monkeypatch.setattr(postgres_mvp, "build_postgres_mvp_store_bundle", build)
    connections = (object(), object(), object(), object())
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
    assert stores.telegram_pairing_store is telegram_pairing_store
    assert stores.telegram_poll_state_store is telegram_poll_state_store
    assert stores.database_health_reader is health_reader
    assert stores.status.mode == "postgresql-partial-preview"
    assert any("conversations" in item for item in stores.status.durable_state)
    assert any("Telegram" in item for item in stores.status.durable_state)
    assert "authentication sessions" in stores.status.ephemeral_state
