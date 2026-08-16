"""Serialized PostgreSQL stores and canonical seed bootstrap for the MVP."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from threading import RLock
from typing import Any, cast

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from melloa.adapters.postgres.conversation import PostgresConversationStore
from melloa.adapters.postgres.delivery import PostgresDeliveryStore
from melloa.adapters.postgres.memory import PostgresMemoryRepository
from melloa.adapters.postgres.telegram import (
    PostgresTelegramPairingStateStore,
    PostgresTelegramPollStateStore,
)
from melloa.domain.base import (
    ContractModel,
    QualifiedName,
    RecordId,
    canonical_json_bytes,
    new_record_id,
    utc_now,
)
from melloa.domain.identity import (
    NameHistoryEntry,
    OwnerIdentity,
    PersistentIntelligenceIdentity,
)
from melloa.domain.memory import Assertion
from melloa.domain.operations import ComponentHealth, HealthCategory, HealthState
from melloa.ports.conversation import ConversationStore
from melloa.ports.delivery import DeliveryStore
from melloa.ports.memory import MemoryNotFoundError, MemoryStore
from melloa.ports.telegram import (
    TelegramPairingStateStore,
    TelegramPollConflictError,
    TelegramPollStateStore,
)

_BOOTSTRAP_LOCK_ID = 4_601_083_133_223


class PostgresMvpBootstrapError(RuntimeError):
    """The configured database conflicts with the canonical MVP seed records."""


@dataclass(frozen=True)
class PostgresMvpStores:
    seeded_at: datetime
    conversation_store: ConversationStore
    memory_store: MemoryStore
    delivery_store: DeliveryStore
    telegram_pairing_store: TelegramPairingStateStore
    telegram_poll_state_store: TelegramPollStateStore
    database_health_reader: Callable[[], ComponentHealth]


class _SerializedPort:
    def __init__(self, port: object, lock: RLock) -> None:
        self._port = port
        self._lock = lock

    def __getattr__(self, name: str) -> object:
        attribute = getattr(self._port, name)
        if not callable(attribute):
            return attribute

        @wraps(attribute)
        def serialized(*args: object, **kwargs: object) -> object:
            with self._lock:
                return attribute(*args, **kwargs)

        return serialized


def _serialized[Port](port: Port, lock: RLock) -> Port:
    return cast(Port, _SerializedPort(port, lock))


def validate_private_database_dsn(dsn: str) -> str:
    """Reject opaque or publicly routed PostgreSQL targets without exposing the DSN."""

    parameters = conninfo_to_dict(dsn)
    if parameters.get("service"):
        raise ValueError("database service indirection is not supported by the MVP runtime")
    host = str(parameters.get("host", ""))
    hostaddr = str(parameters.get("hostaddr", ""))
    if host:
        _validate_database_targets(host, allow_unix_socket=True)
    if hostaddr:
        _validate_database_targets(hostaddr, allow_unix_socket=False)
    return dsn


def _validate_database_targets(value: str, *, allow_unix_socket: bool) -> None:
    for target in value.split(","):
        if not target:
            raise ValueError("database target must not be empty")
        if allow_unix_socket and target.startswith("/"):
            continue
        if target == "localhost":
            continue
        try:
            address = ipaddress.ip_address(target)
        except ValueError as error:
            raise ValueError(
                "database host must be localhost, an absolute Unix socket, or a private literal IP"
            ) from error
        tailscale_range = ipaddress.ip_network("100.64.0.0/10")
        is_tailscale = isinstance(address, ipaddress.IPv4Address) and address in tailscale_range
        if address.is_unspecified or address.is_global or address.is_multicast:
            raise ValueError("public or unspecified database targets are forbidden")
        if not (address.is_loopback or address.is_private or address.is_link_local or is_tailscale):
            raise ValueError("database target must remain on a private network")


def build_postgres_mvp_store_bundle(
    conversation_connection: psycopg.Connection[tuple[Any, ...]],
    memory_connection: psycopg.Connection[tuple[Any, ...]],
    delivery_connection: psycopg.Connection[tuple[Any, ...]],
    telegram_connection: psycopg.Connection[tuple[Any, ...]],
    *,
    owner_id: RecordId,
    intelligence_id: RecordId,
    telegram_adapter_id: QualifiedName,
    assertion_factory: Callable[[datetime], Assertion],
    clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[str], str] = new_record_id,
) -> PostgresMvpStores:
    seeded_at = _ensure_mvp_bootstrap(
        memory_connection,
        owner_id=owner_id,
        intelligence_id=intelligence_id,
        assertion_factory=assertion_factory,
        seeded_at=clock(),
    )
    conversation_lock = RLock()
    memory_lock = RLock()
    delivery_lock = RLock()
    telegram_lock = RLock()
    connections = (
        (conversation_connection, conversation_lock),
        (memory_connection, memory_lock),
        (delivery_connection, delivery_lock),
        (telegram_connection, telegram_lock),
    )

    def database_health() -> ComponentHealth:
        try:
            versions: list[str] = []
            for connection, lock in connections:
                with lock:
                    row = connection.execute(
                        "SELECT current_setting('server_version')"
                    ).fetchone()
                if row is None:
                    raise psycopg.InterfaceError("database health query returned no row")
                versions.append(str(row[0]))
        except psycopg.Error:
            return ComponentHealth(
                component_id="database.postgresql-mvp",
                category=HealthCategory.DATABASE,
                state=HealthState.UNAVAILABLE,
                required=True,
                observed_at=clock(),
                summary="PostgreSQL health is unavailable; connection details remain redacted.",
            )
        version = versions[0] if len(set(versions)) == 1 else "mixed"
        return ComponentHealth(
            component_id="database.postgresql-mvp",
            category=HealthCategory.DATABASE,
            state=HealthState.HEALTHY,
            required=True,
            observed_at=clock(),
            summary=(
                "Private PostgreSQL backs canonical MVP stores, Telegram control state, "
                "and durable work queues."
            ),
            version=version,
        )

    conversation_store = _serialized(
        PostgresConversationStore(conversation_connection, id_factory=id_factory),
        conversation_lock,
    )
    memory_store = _serialized(PostgresMemoryRepository(memory_connection), memory_lock)
    delivery_store = _serialized(
        PostgresDeliveryStore(delivery_connection, id_factory=id_factory),
        delivery_lock,
    )
    telegram_pairing_store = _serialized(
        PostgresTelegramPairingStateStore(telegram_connection),
        telegram_lock,
    )
    try:
        telegram_poll_state_store = _serialized(
            PostgresTelegramPollStateStore(
                telegram_connection,
                adapter_id=telegram_adapter_id,
                initialized_at=seeded_at,
            ),
            telegram_lock,
        )
    except (TelegramPollConflictError, ValidationError, ValueError) as error:
        raise PostgresMvpBootstrapError(
            "database contains incompatible Telegram MVP state"
        ) from error
    return PostgresMvpStores(
        seeded_at=seeded_at,
        conversation_store=cast(ConversationStore, conversation_store),
        memory_store=cast(MemoryStore, memory_store),
        delivery_store=cast(DeliveryStore, delivery_store),
        telegram_pairing_store=cast(TelegramPairingStateStore, telegram_pairing_store),
        telegram_poll_state_store=cast(TelegramPollStateStore, telegram_poll_state_store),
        database_health_reader=database_health,
    )


def _ensure_mvp_bootstrap(
    connection: psycopg.Connection[tuple[Any, ...]],
    *,
    owner_id: RecordId,
    intelligence_id: RecordId,
    assertion_factory: Callable[[datetime], Assertion],
    seeded_at: datetime,
) -> datetime:
    try:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (_BOOTSTRAP_LOCK_ID,))
            owner = _ensure_owner(connection, owner_id=owner_id, seeded_at=seeded_at)
            intelligence = PersistentIntelligenceIdentity(
                intelligence_id=intelligence_id,
                owner_id=owner.owner_id,
                created_at=owner.created_at,
                role="Primary persistent personal intelligence",
                naming_history=(
                    NameHistoryEntry(
                        display_name="Melli",
                        valid_from=owner.created_at,
                        chosen_by=owner.owner_id,
                    ),
                ),
            )
            _ensure_intelligence(connection, intelligence)
            _ensure_name(
                connection,
                intelligence_id=intelligence_id,
                name=intelligence.naming_history[0],
            )
            _ensure_assertion(
                connection,
                assertion_factory=assertion_factory,
                seeded_at=owner.created_at,
            )
            return owner.created_at
    except (MemoryNotFoundError, ValidationError, ValueError) as error:
        raise PostgresMvpBootstrapError(
            "database contains incompatible canonical MVP bootstrap data"
        ) from error


def _ensure_owner(
    connection: psycopg.Connection[tuple[Any, ...]],
    *,
    owner_id: RecordId,
    seeded_at: datetime,
) -> OwnerIdentity:
    row = connection.execute(
        "SELECT document FROM melloa.owners WHERE owner_id = %s",
        (owner_id,),
    ).fetchone()
    if row is None:
        owner = OwnerIdentity(owner_id=owner_id, created_at=seeded_at)
        connection.execute(
            """
            INSERT INTO melloa.owners (
                owner_id, contract_version, status, created_at, document
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                owner.owner_id,
                owner.contract_version,
                owner.status.value,
                owner.created_at,
                Jsonb(owner.model_dump(mode="json")),
            ),
        )
        return owner
    owner = _parse_document(OwnerIdentity, row[0])
    expected = OwnerIdentity(owner_id=owner_id, created_at=owner.created_at)
    if owner != expected:
        raise PostgresMvpBootstrapError("canonical MVP owner identity conflicts")
    return owner


def _ensure_intelligence(
    connection: psycopg.Connection[tuple[Any, ...]],
    intelligence: PersistentIntelligenceIdentity,
) -> None:
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
    row = connection.execute(
        "SELECT document FROM melloa.persistent_intelligences WHERE intelligence_id = %s",
        (intelligence.intelligence_id,),
    ).fetchone()
    if row is None or _parse_document(PersistentIntelligenceIdentity, row[0]) != intelligence:
        raise PostgresMvpBootstrapError("canonical MVP intelligence identity conflicts")


def _ensure_name(
    connection: psycopg.Connection[tuple[Any, ...]],
    *,
    intelligence_id: RecordId,
    name: NameHistoryEntry,
) -> None:
    rows = connection.execute(
        """
        SELECT display_name, chosen_by, valid_from, valid_to
          FROM melloa.intelligence_names
         WHERE intelligence_id = %s
         ORDER BY valid_from, name_id
        """,
        (intelligence_id,),
    ).fetchall()
    if not rows:
        connection.execute(
            """
            INSERT INTO melloa.intelligence_names (
                intelligence_id, display_name, chosen_by, valid_from, valid_to
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                intelligence_id,
                name.display_name,
                name.chosen_by,
                name.valid_from,
                name.valid_to,
            ),
        )
        return
    persisted = tuple(
        NameHistoryEntry(
            display_name=str(display_name),
            chosen_by=str(chosen_by),
            valid_from=valid_from,
            valid_to=valid_to,
        )
        for display_name, chosen_by, valid_from, valid_to in rows
    )
    if persisted != (name,):
        raise PostgresMvpBootstrapError("canonical MVP naming history conflicts")


def _ensure_assertion(
    connection: psycopg.Connection[tuple[Any, ...]],
    *,
    assertion_factory: Callable[[datetime], Assertion],
    seeded_at: datetime,
) -> None:
    assertion = assertion_factory(seeded_at)
    repository = PostgresMemoryRepository(connection)
    try:
        persisted = repository.get_assertion(assertion.assertion_id)
    except MemoryNotFoundError:
        connection.execute(
            """
            SELECT melloa.append_assertion(
                %(document)s::jsonb,
                'memory.assertion-owner-lifecycle'::text,
                %(retained_at)s::timestamptz,
                NULL::timestamptz
            )
            """,
            {
                "document": Jsonb(assertion.model_dump(mode="json")),
                "retained_at": assertion.observed_at,
            },
        )
        return
    if persisted != assertion:
        raise PostgresMvpBootstrapError("canonical MVP seed assertion conflicts")


def _parse_document[Model: ContractModel](model: type[Model], document: object) -> Model:
    if not isinstance(document, dict):
        raise PostgresMvpBootstrapError("canonical identity document is not an object")
    return model.model_validate_json(canonical_json_bytes(document))
