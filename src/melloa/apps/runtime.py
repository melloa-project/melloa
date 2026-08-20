"""Composition for one owner, one Melli, and one optional capable model."""

from __future__ import annotations

import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, cast

import psycopg
from fastapi import FastAPI
from psycopg.types.json import Jsonb

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.adapters.models.openai_compatible import (
    OpenAICompatibleModelConfig,
    OpenAICompatibleModelGateway,
)
from melloa.adapters.models.routed import ModelRouteConfigs, RoutedModelGateway
from melloa.adapters.postgres.auth import PostgresOwnerSessionManager
from melloa.adapters.postgres.conversation import PostgresConversationStore
from melloa.adapters.postgres.memory import PostgresMemoryRepository
from melloa.adapters.postgres.self_change import PostgresSelfChangeStore
from melloa.adapters.postgres.store import PostgresEventAuditStore
from melloa.adapters.postgres.telegram import PostgresTelegramStore
from melloa.adapters.telegram import TelegramBotClient, TelegramOwnerConfig
from melloa.application.conversation import ConversationModelLimits, ConversationService
from melloa.application.exports import OwnerExportService
from melloa.application.owner_status import OwnerModelRoutes, OwnerStatusReporter
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.application.self_change import OwnerSelfChangeService
from melloa.apps.core import AccessScope, create_app
from melloa.apps.owner_telegram import TELEGRAM_THREAD_ID, OwnerTelegramService
from melloa.domain.base import (
    RecordId,
    canonical_json_bytes,
    new_record_id,
    utc_now,
)
from melloa.domain.identity import NameHistoryEntry, OwnerIdentity, PersistentIntelligenceIdentity
from melloa.ports.auth import OwnerSessionManager
from melloa.ports.conversation import ConversationStore
from melloa.ports.guardian import GuardianStatusReader
from melloa.ports.memory import MemoryStore
from melloa.ports.self_change import SelfChangeStore
from melloa.ports.store import EventAuditStore
from melloa.ports.telegram import TelegramStore
from melloa.release import CURRENT_RELEASE

OWNER_ID: RecordId = "owner_00000000000000000000000000000001"
MELLI_ID: RecordId = "intelligence_00000000000000000000000000000001"


@dataclass(frozen=True)
class MelloaRuntime:
    app: FastAPI
    owner_id: RecordId
    intelligence_id: RecordId
    conversation_service: ConversationService
    conversation_store: ConversationStore
    memory_store: MemoryStore
    owner_sessions: OwnerSessionManager
    event_audit_store: EventAuditStore
    model_id: str | None
    model_routes: ModelRouteConfigs | None
    persistence: str
    owner_telegram: OwnerTelegramService | None
    owner_self_changes: OwnerSelfChangeService | None
    self_change_store: SelfChangeStore | None


class _LockedPort:
    def __init__(self, port: object, lock: RLock) -> None:
        self._port = port
        self._lock = lock

    def __getattr__(self, name: str) -> object:
        attribute = getattr(self._port, name)
        if not callable(attribute):
            return attribute

        @wraps(attribute)
        def locked(*args: object, **kwargs: object) -> object:
            with self._lock:
                return attribute(*args, **kwargs)

        return locked


def _terminate_for_supervised_restart() -> None:
    os.kill(os.getpid(), signal.SIGTERM)


def build_runtime(
    guardian_reader: GuardianStatusReader,
    bootstrap_token: str,
    model_config: OpenAICompatibleModelConfig | None = None,
    *,
    model_routes: ModelRouteConfigs | None = None,
    database_connection: psycopg.Connection[tuple[Any, ...]] | None = None,
    clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[str], str] = new_record_id,
    secure_session_cookie: bool = True,
    access_scope: AccessScope = "unverified",
    telegram_config: TelegramOwnerConfig | None = None,
    telegram_bot_token: str | None = None,
    backup_status_file: Path | None = None,
    background_activation: Callable[[], bool] | None = None,
    runtime_failure_handler: Callable[[], None] = _terminate_for_supervised_restart,
    runtime_watchdog_interval: float = 5.0,
) -> MelloaRuntime:
    if model_config is not None and model_routes is not None:
        raise ValueError("single-model and routed-model configuration cannot be combined")
    if (telegram_config is None) != (telegram_bot_token is None):
        raise ValueError("Telegram owner config and bot token must be supplied together")
    if telegram_config is not None and database_connection is None:
        raise ValueError("Telegram owner service requires PostgreSQL persistence")
    if telegram_config is not None and model_routes is None:
        raise ValueError("Telegram owner service requires capable and economy model routes")

    database_lock: RLock | None = None
    self_change_store: SelfChangeStore | None = None
    owner_self_changes: OwnerSelfChangeService | None = None
    if database_connection is None:
        event_audit_store: EventAuditStore = InMemoryEventAuditStore()
        conversation_store: ConversationStore = InMemoryConversationStore(id_factory=id_factory)
        memory_store: MemoryStore = InMemoryMemoryRepository(())
        sessions: OwnerSessionManager = InMemoryOwnerSessionManager(
            OWNER_ID,
            bootstrap_token,
            event_audit_store=event_audit_store,
            clock=clock,
        )
        persistence = "process-only"
    else:
        _ensure_postgres_identities(database_connection, clock())
        database_lock = RLock()
        event_audit_store = cast(
            EventAuditStore,
            _LockedPort(PostgresEventAuditStore(database_connection), database_lock),
        )
        conversation_store = cast(
            ConversationStore,
            _LockedPort(
                PostgresConversationStore(database_connection, id_factory=id_factory),
                database_lock,
            ),
        )
        memory_store = cast(
            MemoryStore,
            _LockedPort(PostgresMemoryRepository(database_connection), database_lock),
        )
        sessions = cast(
            OwnerSessionManager,
            _LockedPort(
                PostgresOwnerSessionManager(
                    database_connection,
                    OWNER_ID,
                    bootstrap_token,
                    event_audit_store=event_audit_store,
                    clock=clock,
                    id_factory=id_factory,
                ),
                database_lock,
            ),
        )
        self_change_store = cast(
            SelfChangeStore,
            _LockedPort(PostgresSelfChangeStore(database_connection), database_lock),
        )
        owner_self_changes = OwnerSelfChangeService(
            owner_id=OWNER_ID,
            store=self_change_store,
            clock=clock,
            id_factory=id_factory,
        )
        persistence = "postgresql"

    model_gateway: OpenAICompatibleModelGateway | RoutedModelGateway | None
    routed_model_gateway: RoutedModelGateway | None = None
    if model_routes is not None:
        routed_model_gateway = RoutedModelGateway(
            capable=OpenAICompatibleModelGateway(
                model_routes.capable,
                clock=clock,
                id_factory=id_factory,
            ),
            economy=OpenAICompatibleModelGateway(
                model_routes.economy,
                clock=clock,
                id_factory=id_factory,
            ),
            clock=clock,
        )
        model_gateway = routed_model_gateway
    elif model_config is not None:
        model_gateway = OpenAICompatibleModelGateway(
            model_config,
            clock=clock,
            id_factory=id_factory,
        )
    else:
        model_gateway = None
    model_limits = _conversation_model_limits(model_config, model_routes)
    conversation = ConversationService(
        owner_id=OWNER_ID,
        intelligence_id=MELLI_ID,
        store=conversation_store,
        model_gateway=model_gateway,
        retriever=PolicyConstrainedRetriever(
            memory_store,
            clock=clock,
            id_factory=id_factory,
        ),
        guardian_reader=guardian_reader,
        clock=clock,
        id_factory=id_factory,
        runtime_version=CURRENT_RELEASE.runtime_identifier,
        model_limits=model_limits,
    )
    exports = OwnerExportService(
        owner_id=OWNER_ID,
        conversation=conversation,
        memory=memory_store,
        clock=clock,
        id_factory=id_factory,
    )
    owner_telegram: OwnerTelegramService | None = None
    if telegram_config is not None and telegram_bot_token is not None:
        if (
            database_connection is None
            or database_lock is None
            or model_gateway is None
            or model_routes is None
            or routed_model_gateway is None
        ):
            raise ValueError("Telegram owner service dependencies are unavailable")
        telegram_store = cast(
            TelegramStore,
            _LockedPort(PostgresTelegramStore(database_connection), database_lock),
        )
        status_reporter = OwnerStatusReporter(
            guardian_reader=guardian_reader,
            conversation_store=conversation_store,
            telegram_store=telegram_store,
            thread_id=TELEGRAM_THREAD_ID,
            model_id=None,
            model_health=None,
            model_routes=OwnerModelRoutes(
                capable_model_id=model_routes.capable.model_id,
                economy_model_id=model_routes.economy.model_id,
                health=routed_model_gateway.route_health,
                selected=lambda: telegram_store.owner_channel().model_route,
            ),
            backup_status_file=backup_status_file,
            clock=clock,
        )
        owner_telegram = OwnerTelegramService(
            config=telegram_config,
            client=TelegramBotClient(telegram_bot_token),
            store=telegram_store,
            conversation=conversation,
            conversation_store=conversation_store,
            owner_id=OWNER_ID,
            intelligence_id=MELLI_ID,
            status_text=status_reporter.render,
            self_change_controls=owner_self_changes,
            clock=clock,
            id_factory=id_factory,
        )

    def database_health() -> None:
        if database_connection is None or database_lock is None:
            return
        with database_lock:
            row = database_connection.execute("SELECT 1").fetchone()
        if row != (1,):
            raise RuntimeError("PostgreSQL health probe returned an unexpected result")

    return MelloaRuntime(
        app=create_app(
            guardian_reader,
            sessions,
            conversation,
            exports,
            model_health=None if model_gateway is None else model_gateway.health,
            secure_session_cookie=secure_session_cookie,
            run_conversation_worker=True,
            owner_telegram_worker=(
                None if owner_telegram is None else owner_telegram.run_forever
            ),
            background_activation=background_activation,
            runtime_health=None if database_connection is None else database_health,
            runtime_failure_handler=(
                None if database_connection is None else runtime_failure_handler
            ),
            runtime_watchdog_interval=runtime_watchdog_interval,
            access_scope=access_scope,
        ),
        owner_id=OWNER_ID,
        intelligence_id=MELLI_ID,
        conversation_service=conversation,
        conversation_store=conversation_store,
        memory_store=memory_store,
        owner_sessions=sessions,
        event_audit_store=event_audit_store,
        model_id=None if model_config is None else model_config.model_id,
        model_routes=model_routes,
        persistence=persistence,
        owner_telegram=owner_telegram,
        owner_self_changes=owner_self_changes,
        self_change_store=self_change_store,
    )


def _conversation_model_limits(
    model_config: OpenAICompatibleModelConfig | None,
    model_routes: ModelRouteConfigs | None,
) -> ConversationModelLimits:
    configs = (
        ()
        if model_config is None and model_routes is None
        else (model_config,)
        if model_config is not None
        else (model_routes.capable, model_routes.economy)
        if model_routes is not None
        else ()
    )
    if not configs:
        return ConversationModelLimits(prompt_version="conversation-response-v2")
    return ConversationModelLimits(
        latency_deadline_ms=max(config.timeout_ms for config in configs),
        max_input_tokens=min(config.max_input_tokens for config in configs),
        max_output_tokens=min(config.max_output_tokens for config in configs),
        cost_ceiling_gbp=max(config.estimated_max_cost_gbp for config in configs),
        prompt_version="conversation-response-v2",
    )


def _ensure_postgres_identities(
    connection: psycopg.Connection[tuple[Any, ...]],
    created_at: datetime,
) -> None:
    owner = OwnerIdentity(owner_id=OWNER_ID, created_at=created_at)
    intelligence = PersistentIntelligenceIdentity(
        intelligence_id=MELLI_ID,
        owner_id=OWNER_ID,
        created_at=created_at,
        role="Primary persistent personal intelligence",
        naming_history=(
            NameHistoryEntry(
                display_name="Melli",
                valid_from=created_at,
                chosen_by=OWNER_ID,
            ),
        ),
    )
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (4_601_083_133_223,))
        connection.execute(
            """
            INSERT INTO melloa.owners (
                owner_id, contract_version, status, created_at, document
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (owner_id) DO NOTHING
            """,
            (
                owner.owner_id,
                owner.contract_version,
                owner.status.value,
                owner.created_at,
                Jsonb(owner.model_dump(mode="json")),
            ),
        )
        owner_row = connection.execute(
            "SELECT document FROM melloa.owners WHERE owner_id = %s",
            (OWNER_ID,),
        ).fetchone()
        if (
            owner_row is None
            or OwnerIdentity.model_validate_json(canonical_json_bytes(owner_row[0])).owner_id
            != OWNER_ID
        ):
            raise ValueError("database owner identity conflicts with this runtime")

        connection.execute(
            """
            INSERT INTO melloa.persistent_intelligences (
                intelligence_id, owner_id, contract_version, role_description,
                status, created_at, document
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (intelligence_id) DO NOTHING
            """,
            (
                intelligence.intelligence_id,
                intelligence.owner_id,
                intelligence.contract_version,
                intelligence.role,
                intelligence.status.value,
                intelligence.created_at,
                Jsonb(intelligence.model_dump(mode="json")),
            ),
        )
        intelligence_row = connection.execute(
            "SELECT document FROM melloa.persistent_intelligences WHERE intelligence_id = %s",
            (MELLI_ID,),
        ).fetchone()
        if (
            intelligence_row is None
            or PersistentIntelligenceIdentity.model_validate_json(
                canonical_json_bytes(intelligence_row[0])
            ).intelligence_id
            != MELLI_ID
        ):
            raise ValueError("database Melli identity conflicts with this runtime")

        current_name = connection.execute(
            """
            SELECT display_name
              FROM melloa.intelligence_names
             WHERE intelligence_id = %s AND valid_to IS NULL
            """,
            (MELLI_ID,),
        ).fetchone()
        if current_name is None:
            name = intelligence.naming_history[0]
            connection.execute(
                """
                INSERT INTO melloa.intelligence_names (
                    intelligence_id, display_name, chosen_by, valid_from, valid_to
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (MELLI_ID, name.display_name, name.chosen_by, name.valid_from, name.valid_to),
            )
        elif current_name[0] != "Melli":
            raise ValueError("database current intelligence name conflicts with Melli")


__all__ = ["MELLI_ID", "OWNER_ID", "MelloaRuntime", "build_runtime"]
