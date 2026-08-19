"""Composition for one owner, one Melli, and one optional capable model."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
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
    OpenAICompatibleModelGateway,
    OpenAICompatibleRouteConfig,
)
from melloa.adapters.postgres.auth import PostgresOwnerSessionManager
from melloa.adapters.postgres.conversation import PostgresConversationStore
from melloa.adapters.postgres.memory import PostgresMemoryRepository
from melloa.adapters.postgres.store import PostgresEventAuditStore
from melloa.application.conversation import ConversationRoutePolicy, ConversationService
from melloa.application.exports import OwnerExportService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.application.routing import (
    DeterministicModelRouter,
    ModelRouteBinding,
    OwnerModelRouteService,
)
from melloa.apps.core import AccessScope, create_app
from melloa.domain.base import (
    QualifiedName,
    RecordId,
    canonical_json_bytes,
    new_record_id,
    utc_now,
)
from melloa.domain.identity import NameHistoryEntry, OwnerIdentity, PersistentIntelligenceIdentity
from melloa.domain.models import ModelRouteKind
from melloa.ports.auth import OwnerSessionManager
from melloa.ports.conversation import ConversationStore
from melloa.ports.guardian import GuardianStatusReader
from melloa.ports.memory import MemoryStore
from melloa.ports.store import EventAuditStore
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
    model_route_ids: tuple[QualifiedName, ...]
    persistence: str


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


def build_runtime(
    guardian_reader: GuardianStatusReader,
    bootstrap_token: str,
    model_config: OpenAICompatibleRouteConfig | None = None,
    *,
    database_connection: psycopg.Connection[tuple[Any, ...]] | None = None,
    clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[str], str] = new_record_id,
    secure_session_cookie: bool = True,
    access_scope: AccessScope = "unverified",
) -> MelloaRuntime:
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
        persistence = "postgresql"

    bindings: tuple[ModelRouteBinding, ...] = ()
    if model_config is not None:
        bindings = (
            ModelRouteBinding(
                route=model_config.registered_route(),
                backend=OpenAICompatibleModelGateway(
                    model_config,
                    clock=clock,
                    id_factory=id_factory,
                ),
                display_name=model_config.display_name,
                route_kind=ModelRouteKind.OPENAI_COMPATIBLE,
                timeout_ms=model_config.timeout_ms,
            ),
        )
    router = DeterministicModelRouter(bindings, clock=clock)
    route_policy = ConversationRoutePolicy(
        minimum_quality_profile="quality.conversation",
        latency_deadline_ms=30_000 if model_config is None else model_config.timeout_ms,
        max_input_tokens=4_096 if model_config is None else model_config.max_input_tokens,
        max_output_tokens=1_024 if model_config is None else model_config.max_output_tokens,
        cost_ceiling_gbp=(
            0.0 if model_config is None else model_config.estimated_max_cost_gbp
        ),
        provider_retention_policy="retention.no-training",
        minimum_reliability=0.0,
        fallback_route_ids=() if model_config is None else (model_config.route_id,),
        prompt_version="conversation-response-v1",
    )
    conversation = ConversationService(
        owner_id=OWNER_ID,
        intelligence_id=MELLI_ID,
        store=conversation_store,
        model_gateway=router,
        retriever=PolicyConstrainedRetriever(
            memory_store,
            clock=clock,
            id_factory=id_factory,
        ),
        guardian_reader=guardian_reader,
        clock=clock,
        id_factory=id_factory,
        runtime_version=CURRENT_RELEASE.runtime_identifier,
        route_policy=route_policy,
    )
    model_routes = OwnerModelRouteService(owner_id=OWNER_ID, router=router, clock=clock)
    exports = OwnerExportService(
        owner_id=OWNER_ID,
        conversation=conversation,
        memory=memory_store,
        clock=clock,
        id_factory=id_factory,
    )
    return MelloaRuntime(
        app=create_app(
            guardian_reader,
            sessions,
            conversation,
            model_routes,
            exports,
            secure_session_cookie=secure_session_cookie,
            run_conversation_worker=True,
            access_scope=access_scope,
        ),
        owner_id=OWNER_ID,
        intelligence_id=MELLI_ID,
        conversation_service=conversation,
        conversation_store=conversation_store,
        memory_store=memory_store,
        owner_sessions=sessions,
        event_audit_store=event_audit_store,
        model_route_ids=tuple(binding.route.route_id for binding in bindings),
        persistence=persistence,
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
