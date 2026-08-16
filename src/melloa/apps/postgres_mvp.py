"""Optional PostgreSQL store assembly for the owner-facing MVP."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg

from melloa.adapters.postgres.mvp import (
    PostgresMvpBootstrapError,
    build_postgres_mvp_store_bundle,
    validate_private_database_dsn,
)
from melloa.apps.synthetic import (
    SYNTHETIC_INTELLIGENCE_ID,
    SYNTHETIC_OWNER_ID,
    SYNTHETIC_TELEGRAM_ADAPTER_ID,
    DurableRuntimeStores,
    RuntimePersistenceStatus,
    synthetic_seed_assertion,
)
from melloa.domain.base import QualifiedName, new_record_id, utc_now

__all__ = (
    "PostgresMvpBootstrapError",
    "build_postgres_mvp_stores",
    "validate_private_database_dsn",
)


def build_postgres_mvp_stores(
    conversation_connection: psycopg.Connection[tuple[Any, ...]],
    memory_connection: psycopg.Connection[tuple[Any, ...]],
    delivery_connection: psycopg.Connection[tuple[Any, ...]],
    telegram_connection: psycopg.Connection[tuple[Any, ...]],
    audit_connection: psycopg.Connection[tuple[Any, ...]],
    *,
    telegram_adapter_id: QualifiedName = SYNTHETIC_TELEGRAM_ADAPTER_ID,
    clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[str], str] = new_record_id,
) -> DurableRuntimeStores:
    stores = build_postgres_mvp_store_bundle(
        conversation_connection,
        memory_connection,
        delivery_connection,
        telegram_connection,
        audit_connection,
        owner_id=SYNTHETIC_OWNER_ID,
        intelligence_id=SYNTHETIC_INTELLIGENCE_ID,
        telegram_adapter_id=telegram_adapter_id,
        assertion_factory=synthetic_seed_assertion,
        clock=clock,
        id_factory=id_factory,
    )
    return DurableRuntimeStores(
        seeded_at=stores.seeded_at,
        conversation_store=stores.conversation_store,
        memory_store=stores.memory_store,
        delivery_store=stores.delivery_store,
        event_audit_store=stores.event_audit_store,
        telegram_pairing_store=stores.telegram_pairing_store,
        telegram_poll_state_store=stores.telegram_poll_state_store,
        database_health_reader=stores.database_health_reader,
        status=RuntimePersistenceStatus(
            mode="postgresql-partial-preview",
            durable_state=(
                "canonical conversations, turns, retrieval manifests, and model provenance",
                "memory assertions, corrections, and state history",
                "reply and delivery work, retries, resumptions, and receipts",
                "Telegram pairing authority, normalized intake, offsets, and reply dispatch",
                "audit append records for assembled audit-emitting owner actions",
            ),
            ephemeral_state=(
                "authentication sessions",
                "Telegram challenge-send observation and attachment quarantine bytes",
                "provider health observations",
                "event/audit emission for actions not yet assembled",
            ),
        ),
    )
