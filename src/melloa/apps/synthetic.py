"""Explicit M1 runtime assembly with synthetic defaults and injectable durable stores."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.client import FakeClientAdapter
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.delivery import InMemoryDeliveryStore
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.fakes.operations import InMemoryOperationsReader
from melloa.adapters.fakes.retention import (
    AuditBackedRetentionReader,
    ConversationBackedRetentionReader,
    DeliveryBackedRetentionReader,
    InMemoryRetentionReader,
    MemoryBackedRetentionReader,
    TelegramQuarantineBackedRetentionReader,
)
from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.adapters.fakes.telegram import (
    DeterministicTelegramPairingCodeIssuer,
    FakeTelegramPairingChallengePublisher,
    FakeTelegramUpdateSource,
    InMemoryTelegramPairingStateStore,
    InMemoryTelegramPollStateStore,
    RejectingTelegramAttachmentBackend,
)
from melloa.application.conversation import ConversationRoutePolicy, ConversationService
from melloa.application.delivery import ClientDeliveryRoute, DeliveryService
from melloa.application.exports import OwnerExportService
from melloa.application.inspection import OwnerInspectionService
from melloa.application.memory import MemoryService
from melloa.application.operations import OwnerOperationsService
from melloa.application.retention import OwnerRetentionService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.application.routing import (
    DeterministicModelRouter,
    ModelRouteBinding,
    OwnerModelRouteService,
)
from melloa.application.telegram import (
    TelegramAttachmentRetentionWorker,
    TelegramDeliveryRouteResolver,
    TelegramIngestionService,
    TelegramPairingService,
    TelegramPollWorker,
    TelegramReplyDispatcher,
)
from melloa.apps.core import create_app
from melloa.domain.base import JsonObject, QualifiedName, RecordId, new_record_id, utc_now
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.conversation import ConversationThread
from melloa.domain.memory import Assertion, AssertionMetadata, AssertionStatus
from melloa.domain.models import (
    ModelRouteKind,
    ModelRouteRequest,
    ProcessingLocation,
    RegisteredModelRoute,
)
from melloa.domain.operations import (
    ComponentHealth,
    HealthCategory,
    HealthState,
    MediaSourceStatus,
)
from melloa.domain.retention import (
    BackupExpiryDisclosure,
    BackupExpiryState,
    RetentionDeletionControl,
    RetentionDeletionScope,
    RetentionDurationBounds,
    RetentionExternalCopyState,
    RetentionInventoryCoverage,
    RetentionInventoryStatus,
    RetentionMode,
    RetentionPolicyStatus,
)
from melloa.ports.auth import OwnerSessionManager
from melloa.ports.client import ClientAdapter
from melloa.ports.conversation import ConversationNotFoundError, ConversationStore
from melloa.ports.delivery import DeliveryStore
from melloa.ports.guardian import GuardianStatusReader
from melloa.ports.memory import MemoryNotFoundError, MemoryStore
from melloa.ports.store import EventAuditStore
from melloa.ports.telegram import (
    TelegramPairingChallengePublisher,
    TelegramPairingCodeIssuer,
    TelegramPairingStateStore,
    TelegramPollStateStore,
    TelegramUpdateSource,
)

SYNTHETIC_OWNER_ID: RecordId = "owner_00000000000000000000000000000001"
SYNTHETIC_INTELLIGENCE_ID: RecordId = "intelligence_00000000000000000000000000000001"
SYNTHETIC_ASSERTION_ID: RecordId = "assertion_00000000000000000000000000000001"
SYNTHETIC_TELEGRAM_THREAD_ID: RecordId = "thread_00000000000000000000000000000002"
SYNTHETIC_TELEGRAM_ADAPTER_ID: QualifiedName = "client.telegram.synthetic"
_SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas"


@dataclass(frozen=True)
class RuntimePersistenceStatus:
    mode: str
    durable_state: tuple[str, ...]
    ephemeral_state: tuple[str, ...]


@dataclass(frozen=True)
class DurableRuntimeStores:
    seeded_at: datetime
    conversation_store: ConversationStore
    memory_store: MemoryStore
    delivery_store: DeliveryStore
    database_health_reader: Callable[[], ComponentHealth]
    status: RuntimePersistenceStatus
    event_audit_store: EventAuditStore | None = None
    owner_session_factory: Callable[[str], OwnerSessionManager] | None = None
    telegram_pairing_store: TelegramPairingStateStore | None = None
    telegram_poll_state_store: TelegramPollStateStore | None = None


@dataclass(frozen=True)
class SyntheticRuntime:
    app: FastAPI
    owner_id: RecordId
    intelligence_id: RecordId
    seed_assertion_id: RecordId
    telegram_thread_id: RecordId
    telegram_source: TelegramUpdateSource
    telegram_poll_state_store: TelegramPollStateStore
    telegram_pairing_service: TelegramPairingService
    telegram_challenge_publisher: TelegramPairingChallengePublisher
    telegram_attachment_backend: RejectingTelegramAttachmentBackend
    telegram_retention_worker: TelegramAttachmentRetentionWorker
    telegram_worker: TelegramPollWorker
    telegram_delivery_adapter: ClientAdapter | None
    telegram_reply_dispatcher: TelegramReplyDispatcher | None
    delivery_service: DeliveryService
    delivery_store: DeliveryStore
    event_audit_store: EventAuditStore
    conversation_service: ConversationService
    memory_service: MemoryService
    memory_store: MemoryStore
    retention_service: OwnerRetentionService
    export_service: OwnerExportService
    model_route_ids: tuple[QualifiedName, ...]
    persistence: RuntimePersistenceStatus


def synthetic_seed_assertion(seeded_at: datetime) -> Assertion:
    return Assertion(
        assertion_id=SYNTHETIC_ASSERTION_ID,
        subject_id=SYNTHETIC_OWNER_ID,
        predicate="owner.preference.synthetic-activity",
        value={
            "activity": "reading",
            "fixture": True,
            "note": "Synthetic acceptance record; never owner data.",
        },
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=seeded_at,
    )


def build_synthetic_runtime(
    guardian_reader: GuardianStatusReader,
    bootstrap_token: str,
    *,
    clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[str], str] = new_record_id,
    telegram_worker_interval: float = 1.0,
    telegram_retention_worker_interval: float = 60.0,
    configured_model_bindings: tuple[ModelRouteBinding, ...] = (),
    conversation_route_policy: ConversationRoutePolicy | None = None,
    runtime_version: str = "melloa-core/0.1.0-synthetic",
    telegram_adapter_id: QualifiedName = SYNTHETIC_TELEGRAM_ADAPTER_ID,
    telegram_source: TelegramUpdateSource | None = None,
    telegram_challenge_publisher: TelegramPairingChallengePublisher | None = None,
    telegram_code_issuer: TelegramPairingCodeIssuer | None = None,
    telegram_delivery_adapter_factory: (
        Callable[[TelegramPairingService], ClientAdapter] | None
    ) = None,
    telegram_external_destination: str = "synthetic:owner",
    telegram_maximum_sensitivity: Sensitivity = Sensitivity.PERSONAL,
    telegram_poll_timeout_seconds: int = 1,
    telegram_thread_title: str = "Synthetic Telegram intake",
    durable_stores: DurableRuntimeStores | None = None,
) -> SyntheticRuntime:
    """Compose the MVP runtime with explicit injectable provider, channel, and store ports."""

    seeded_at = clock() if durable_stores is None else durable_stores.seeded_at
    assertion = synthetic_seed_assertion(seeded_at)
    if durable_stores is None:
        memory_store: MemoryStore = InMemoryMemoryRepository((assertion,))
        conversation_store: ConversationStore = InMemoryConversationStore(
            id_factory=id_factory
        )
        delivery_store: DeliveryStore = InMemoryDeliveryStore(id_factory=id_factory)
        persistence = RuntimePersistenceStatus(
            mode="process-only-preview",
            durable_state=(),
            ephemeral_state=(
                "authentication sessions",
                "canonical conversations and model provenance",
                "memory assertions and corrections",
                "reply and delivery retry state",
                "Telegram pairing, offsets, and attachment quarantine",
            ),
        )
    else:
        memory_store = durable_stores.memory_store
        conversation_store = durable_stores.conversation_store
        delivery_store = durable_stores.delivery_store
        persistence = durable_stores.status
        _ensure_runtime_seed_assertion(memory_store, assertion)
    _ensure_runtime_thread(
        conversation_store,
        ConversationThread(
            thread_id=SYNTHETIC_TELEGRAM_THREAD_ID,
            owner_id=SYNTHETIC_OWNER_ID,
            intelligence_id=SYNTHETIC_INTELLIGENCE_ID,
            title=telegram_thread_title,
            sensitivity=Sensitivity.PERSONAL,
            retention_policy="retention.owner-conversation",
            created_at=seeded_at,
            updated_at=seeded_at,
        ),
    )
    event_audit_store: EventAuditStore = (
        InMemoryEventAuditStore()
        if durable_stores is None or durable_stores.event_audit_store is None
        else durable_stores.event_audit_store
    )
    model_backend = FakeModelGateway(
        _synthetic_conversation_response,
        clock=clock,
        id_factory=id_factory,
    )
    synthetic_binding = ModelRouteBinding(
        route=RegisteredModelRoute(
            route_id="model.fake.deterministic",
            provider_id="provider.synthetic",
            model_id="deterministic-fixture-v1",
            processing_location=ProcessingLocation.DEVICE,
            supported_modalities=frozenset({"text"}),
            quality_profiles=frozenset(
                {"quality.conversation", "quality.conversation-synthetic"}
            ),
            allowed_sensitivities=frozenset(Sensitivity),
            provider_retention_policies=frozenset({"retention.no-training"}),
            max_input_tokens=4_096,
            max_output_tokens=1_024,
            estimated_max_cost_gbp=0.0,
            reliability=1.0,
            priority=10_000,
            external_disclosure=False,
        ),
        backend=model_backend,
        display_name="Deterministic synthetic fixture",
        route_kind=ModelRouteKind.SYNTHETIC,
        timeout_ms=1_000,
    )
    model_router = DeterministicModelRouter(
        (
            *configured_model_bindings,
            synthetic_binding,
        ),
        clock=clock,
    )
    model_routes = OwnerModelRouteService(
        owner_id=SYNTHETIC_OWNER_ID,
        router=model_router,
        clock=clock,
    )
    sessions = (
        InMemoryOwnerSessionManager(
            SYNTHETIC_OWNER_ID,
            bootstrap_token,
            event_audit_store=event_audit_store,
            clock=clock,
        )
        if durable_stores is None or durable_stores.owner_session_factory is None
        else durable_stores.owner_session_factory(bootstrap_token)
    )
    conversation = ConversationService(
        owner_id=SYNTHETIC_OWNER_ID,
        intelligence_id=SYNTHETIC_INTELLIGENCE_ID,
        store=conversation_store,
        model_gateway=model_router,
        retriever=PolicyConstrainedRetriever(
            memory_store,
            clock=clock,
            id_factory=id_factory,
        ),
        guardian_reader=guardian_reader,
        clock=clock,
        id_factory=id_factory,
        runtime_version=runtime_version,
        route_policy=conversation_route_policy,
    )
    resolved_telegram_source = telegram_source or FakeTelegramUpdateSource(
        adapter_id=telegram_adapter_id
    )
    telegram_poll_state_store = (
        None if durable_stores is None else durable_stores.telegram_poll_state_store
    ) or InMemoryTelegramPollStateStore(
        adapter_id=telegram_adapter_id,
        clock=lambda: seeded_at,
    )
    resolved_challenge_publisher = (
        telegram_challenge_publisher or FakeTelegramPairingChallengePublisher()
    )
    telegram_attachment_backend = RejectingTelegramAttachmentBackend(
        owner_id=SYNTHETIC_OWNER_ID,
        clock=clock,
    )
    telegram_pairing_service = TelegramPairingService(
        owner_id=SYNTHETIC_OWNER_ID,
        adapter_id=telegram_adapter_id,
        store=(
            None if durable_stores is None else durable_stores.telegram_pairing_store
        )
        or InMemoryTelegramPairingStateStore(),
        code_issuer=telegram_code_issuer or DeterministicTelegramPairingCodeIssuer(),
        challenge_publisher=resolved_challenge_publisher,
        guardian_reader=guardian_reader,
        event_audit_store=event_audit_store,
        clock=clock,
        id_factory=id_factory,
    )
    telegram_ingestion = TelegramIngestionService(
        owner_id=SYNTHETIC_OWNER_ID,
        thread_id=SYNTHETIC_TELEGRAM_THREAD_ID,
        adapter_id=telegram_adapter_id,
        pairing_service=telegram_pairing_service,
        attachment_backend=telegram_attachment_backend,
        conversation_store=conversation_store,
        poll_state_store=telegram_poll_state_store,
        guardian_reader=guardian_reader,
        clock=clock,
        id_factory=id_factory,
    )
    telegram_worker = TelegramPollWorker(
        adapter_id=telegram_adapter_id,
        source=resolved_telegram_source,
        poll_state_store=telegram_poll_state_store,
        ingestion_service=telegram_ingestion,
        guardian_reader=guardian_reader,
        timeout_seconds=telegram_poll_timeout_seconds,
        batch_limit=25,
        clock=clock,
    )
    telegram_retention_worker = TelegramAttachmentRetentionWorker(
        backend=telegram_attachment_backend,
        guardian_reader=guardian_reader,
        clock=clock,
    )
    backup_expiry = BackupExpiryDisclosure(
        state=BackupExpiryState.NOT_CONFIGURED,
        status_reason="retention.backup.not_configured",
    )
    memory = MemoryService(
        owner_id=SYNTHETIC_OWNER_ID,
        store=memory_store,
        guardian_reader=guardian_reader,
        backup_expiry=backup_expiry,
        event_audit_store=event_audit_store,
        clock=clock,
        id_factory=id_factory,
    )
    delivery_adapter = FakeClientAdapter(
        adapter_id="client.fake",
        destination_ref="synthetic:owner",
        clock=clock,
        id_factory=id_factory,
    )
    telegram_delivery_adapter = (
        None
        if telegram_delivery_adapter_factory is None
        else telegram_delivery_adapter_factory(telegram_pairing_service)
    )
    telegram_route_resolvers = (
        ()
        if telegram_delivery_adapter is None
        else (
            TelegramDeliveryRouteResolver(
                adapter_id=telegram_adapter_id,
                pairing_service=telegram_pairing_service,
                adapter=telegram_delivery_adapter,
                external_destination=telegram_external_destination,
                maximum_sensitivity=telegram_maximum_sensitivity,
            ),
        )
    )
    delivery = DeliveryService(
        owner_id=SYNTHETIC_OWNER_ID,
        intelligence_id=SYNTHETIC_INTELLIGENCE_ID,
        conversation_store=conversation_store,
        delivery_store=delivery_store,
        routes=(
            ClientDeliveryRoute(
                adapter_id="client.fake",
                destination_ref="synthetic:owner",
                external_destination="synthetic:owner",
                purpose="conversation.owner_delivery",
                adapter=delivery_adapter,
                allowed_sensitivities=frozenset(Sensitivity),
            ),
        ),
        guardian_reader=guardian_reader,
        route_resolvers=telegram_route_resolvers,
        clock=clock,
        id_factory=id_factory,
    )
    telegram_reply_dispatcher = (
        None
        if telegram_delivery_adapter is None
        else TelegramReplyDispatcher(
            owner_id=SYNTHETIC_OWNER_ID,
            thread_id=SYNTHETIC_TELEGRAM_THREAD_ID,
            adapter_id=telegram_adapter_id,
            conversation_store=conversation_store,
            delivery_service=delivery,
            delivery_store=delivery_store,
            receipt_store=telegram_poll_state_store,
        )
    )
    retention = OwnerRetentionService(
        owner_id=SYNTHETIC_OWNER_ID,
        reader=AuditBackedRetentionReader(
            ConversationBackedRetentionReader(
                DeliveryBackedRetentionReader(
                    MemoryBackedRetentionReader(
                        TelegramQuarantineBackedRetentionReader(
                            InMemoryRetentionReader(
                                SYNTHETIC_OWNER_ID,
                                policies=_synthetic_retention_policies(),
                                inventory=_synthetic_retention_inventory(),
                                backup_expiry=backup_expiry,
                            ),
                            telegram_attachment_backend,
                        ),
                        memory_store,
                    ),
                    delivery_store,
                ),
                conversation_store,
            ),
            SYNTHETIC_OWNER_ID,
            event_audit_store,
        ),
        clock=clock,
    )
    inspection = OwnerInspectionService(
        owner_id=SYNTHETIC_OWNER_ID,
        conversation_store=conversation_store,
        delivery=delivery,
        event_audit_store=event_audit_store,
        clock=clock,
    )
    operations = OwnerOperationsService(
        owner_id=SYNTHETIC_OWNER_ID,
        reader=InMemoryOperationsReader(
            SYNTHETIC_OWNER_ID,
            components=(
                ComponentHealth(
                    component_id="application.melloa-core",
                    category=HealthCategory.APPLICATION,
                    state=HealthState.HEALTHY,
                    required=True,
                    observed_at=seeded_at,
                    summary="Private Melloa core is serving authenticated owner requests.",
                    version=runtime_version,
                ),
                ComponentHealth(
                    component_id="worker.synthetic-reply",
                    category=HealthCategory.WORKER,
                    state=HealthState.HEALTHY,
                    required=True,
                    observed_at=seeded_at,
                    summary="Runtime worker resumes due canonical reply work.",
                ),
                ComponentHealth(
                    component_id="worker.synthetic-delivery",
                    category=HealthCategory.WORKER,
                    state=HealthState.HEALTHY,
                    required=True,
                    observed_at=seeded_at,
                    summary="Runtime worker resumes due exact-authority delivery work.",
                ),
                *_runtime_persistence_components(
                    seeded_at,
                    durable=durable_stores is not None,
                ),
                ComponentHealth(
                    component_id="provider.synthetic-device",
                    category=HealthCategory.PROVIDER,
                    state=HealthState.HEALTHY,
                    required=True,
                    observed_at=seeded_at,
                    summary="Deterministic device-local model route; no provider network calls.",
                    version="1.0.0",
                ),
                ComponentHealth(
                    component_id="camera.not-configured",
                    category=HealthCategory.CAMERA,
                    state=HealthState.DISABLED,
                    required=False,
                    observed_at=seeded_at,
                    summary="Camera capture remains disabled until its later milestone.",
                ),
                ComponentHealth(
                    component_id="deployment.synthetic-process",
                    category=HealthCategory.DEPLOYMENT,
                    state=HealthState.HEALTHY,
                    required=False,
                    observed_at=seeded_at,
                    summary="Explicit synthetic acceptance mode is active.",
                    version=runtime_version,
                ),
            ),
            component_readers=(
                *(
                    ()
                    if durable_stores is None
                    else (durable_stores.database_health_reader,)
                ),
                lambda: _synthetic_telegram_component(telegram_worker, clock),
                lambda: _synthetic_retention_component(
                    telegram_retention_worker,
                    clock,
                ),
            ),
            media_sources=(
                MediaSourceStatus(
                    capability_id="camera.synthetic-disabled",
                    installed=False,
                    capture_enabled=False,
                    health_state=HealthState.DISABLED,
                    observed_at=seeded_at,
                    status_reason="camera.not-configured",
                ),
            ),
        ),
        conversation=conversation,
        delivery=delivery,
        retention=retention,
        memory_repository=memory_store,
        clock=clock,
    )
    export = OwnerExportService(
        owner_id=SYNTHETIC_OWNER_ID,
        intelligence_id=SYNTHETIC_INTELLIGENCE_ID,
        conversation=conversation,
        delivery=delivery,
        memory=memory,
        memory_repository=memory_store,
        retention=retention,
        clock=clock,
        id_factory=id_factory,
        source_runtime=f"melloa-mvp/{persistence.mode}",
    )
    return SyntheticRuntime(
        app=create_app(
            guardian_reader,
            sessions,
            conversation,
            memory,
            inspection,
            operations,
            delivery,
            telegram_worker,
            telegram_pairing_service,
            telegram_retention_worker,
            telegram_reply_dispatcher,
            telegram_delivery_adapter,
            retention_service=retention,
            model_route_service=model_routes,
            owner_id=SYNTHETIC_OWNER_ID,
            event_audit_store=event_audit_store,
            security_event_clock=clock,
            security_event_id_factory=id_factory,
            export_service=export,
            export_schema_root=_SCHEMA_ROOT,
            run_conversation_worker=True,
            run_delivery_worker=True,
            run_telegram_worker=True,
            telegram_worker_interval=telegram_worker_interval,
            run_telegram_retention_worker=True,
            telegram_retention_worker_interval=telegram_retention_worker_interval,
            telegram_state_persistence=(
                "postgresql"
                if persistence.mode == "postgresql-partial-preview"
                else "process-only-preview"
            ),
        ),
        owner_id=SYNTHETIC_OWNER_ID,
        intelligence_id=SYNTHETIC_INTELLIGENCE_ID,
        seed_assertion_id=SYNTHETIC_ASSERTION_ID,
        telegram_thread_id=SYNTHETIC_TELEGRAM_THREAD_ID,
        telegram_source=resolved_telegram_source,
        telegram_poll_state_store=telegram_poll_state_store,
        telegram_pairing_service=telegram_pairing_service,
        telegram_challenge_publisher=resolved_challenge_publisher,
        telegram_attachment_backend=telegram_attachment_backend,
        telegram_retention_worker=telegram_retention_worker,
        telegram_worker=telegram_worker,
        telegram_delivery_adapter=telegram_delivery_adapter,
        telegram_reply_dispatcher=telegram_reply_dispatcher,
        delivery_service=delivery,
        delivery_store=delivery_store,
        event_audit_store=event_audit_store,
        conversation_service=conversation,
        memory_service=memory,
        memory_store=memory_store,
        retention_service=retention,
        export_service=export,
        model_route_ids=tuple(
            binding.route.route_id
            for binding in (*configured_model_bindings, synthetic_binding)
        ),
        persistence=persistence,
    )


def _ensure_runtime_thread(
    conversation_store: ConversationStore,
    expected: ConversationThread,
) -> None:
    try:
        existing = conversation_store.get_thread(expected.thread_id)
    except ConversationNotFoundError:
        conversation_store.create_thread(expected)
        return
    if existing.model_copy(update={"updated_at": expected.updated_at}) != expected:
        raise ValueError("runtime Telegram thread conflicts with canonical data")


def _ensure_runtime_seed_assertion(
    memory_store: MemoryStore,
    expected: Assertion,
) -> None:
    conflict_message = "durable runtime seed assertion conflicts with canonical data"
    expected_metadata = AssertionMetadata.model_validate(
        expected.model_dump(mode="python", exclude={"value"})
    )
    try:
        persisted_metadata = memory_store.get_assertion_metadata(expected.assertion_id)
    except MemoryNotFoundError as error:
        raise ValueError(conflict_message) from error
    if persisted_metadata != expected_metadata:
        raise ValueError(conflict_message)
    try:
        deletion = memory_store.get_assertion_content_deletion(expected.assertion_id)
    except MemoryNotFoundError as error:
        raise ValueError(conflict_message) from error
    if deletion is not None:
        return
    try:
        persisted = memory_store.get_assertion(expected.assertion_id)
    except MemoryNotFoundError as error:
        raise ValueError(conflict_message) from error
    if persisted != expected:
        raise ValueError(conflict_message)


def _runtime_persistence_components(
    observed_at: datetime,
    *,
    durable: bool,
) -> tuple[ComponentHealth, ...]:
    if not durable:
        return (
            ComponentHealth(
                component_id="database.not-configured",
                category=HealthCategory.DATABASE,
                state=HealthState.DISABLED,
                required=False,
                observed_at=observed_at,
                summary="PostgreSQL is not used by the process-local acceptance runtime.",
            ),
            ComponentHealth(
                component_id="queue.process-memory",
                category=HealthCategory.QUEUE,
                state=HealthState.DEGRADED,
                required=True,
                observed_at=observed_at,
                summary="Retry state is process-local and is discarded on restart.",
            ),
            ComponentHealth(
                component_id="storage.process-memory",
                category=HealthCategory.STORAGE,
                state=HealthState.DEGRADED,
                required=True,
                observed_at=observed_at,
                summary="Application state is process-local and is discarded on restart.",
            ),
            ComponentHealth(
                component_id="backup.not-configured",
                category=HealthCategory.BACKUP,
                state=HealthState.DISABLED,
                required=False,
                observed_at=observed_at,
                summary="No backup is configured for intentionally ephemeral fixture data.",
            ),
        )
    return (
        ComponentHealth(
            component_id="queue.postgresql-durable",
            category=HealthCategory.QUEUE,
            state=HealthState.HEALTHY,
            required=True,
            observed_at=observed_at,
            summary=(
                "Reply and outbound-delivery leases, retries, and resumptions survive core restart."
            ),
        ),
        ComponentHealth(
            component_id="storage.postgresql-canonical",
            category=HealthCategory.STORAGE,
            state=HealthState.HEALTHY,
            required=True,
            observed_at=observed_at,
            summary=(
                "Canonical conversations, turn/model provenance, memory corrections, "
                "delivery records, and Telegram control state survive core restart."
            ),
        ),
        ComponentHealth(
            component_id="storage.process-local-control-state",
            category=HealthCategory.STORAGE,
            state=HealthState.DEGRADED,
            required=False,
            observed_at=observed_at,
            summary=(
                "Owner sessions, provider health observations, Telegram challenge-send "
                "observation, and attachment quarantine bytes remain process-local."
            ),
        ),
        ComponentHealth(
            component_id="backup.not-configured",
            category=HealthCategory.BACKUP,
            state=HealthState.DISABLED,
            required=False,
            observed_at=observed_at,
            summary=(
                "PostgreSQL restart durability is enabled, but no backup or restore path is "
                "configured."
            ),
        ),
    )


def _synthetic_retention_policies() -> tuple[RetentionPolicyStatus, ...]:
    return (
        RetentionPolicyStatus(
            policy_id="retention.audit-ledger",
            data_category="data.audit-ledger",
            summary="Security and action evidence is append-oriented and deletion-restricted.",
            mode=RetentionMode.APPEND_ONLY,
            automatic_expiry=False,
            deletion_control=RetentionDeletionControl.RESTRICTED,
            tombstone_retained=True,
            derived_rebuild_required=False,
            external_copy_state=RetentionExternalCopyState.NONE,
            status_reason="retention.audit.restricted",
        ),
        RetentionPolicyStatus(
            policy_id="retention.owner-conversation",
            data_category="data.canonical-conversation",
            summary=(
                "Canonical conversation records are inventory-backed; deletion is not "
                "assembled yet."
            ),
            mode=RetentionMode.OWNER_LIFECYCLE,
            automatic_expiry=False,
            deletion_control=RetentionDeletionControl.NOT_IMPLEMENTED,
            tombstone_retained=True,
            derived_rebuild_required=True,
            external_copy_state=RetentionExternalCopyState.SOURCE_CONTROLLED,
            status_reason="retention.owner_conversation.inventory_available",
        ),
        RetentionPolicyStatus(
            policy_id="retention.owner-memory",
            data_category="data.memory-assertion",
            summary=(
                "Memory assertions keep metadata and provenance; retained values can be "
                "deleted by owner request."
            ),
            mode=RetentionMode.OWNER_LIFECYCLE,
            automatic_expiry=False,
            deletion_control=RetentionDeletionControl.OWNER_REQUEST,
            owner_deletion_scopes=(RetentionDeletionScope.MEMORY_CLAIM,),
            tombstone_retained=True,
            derived_rebuild_required=True,
            external_copy_state=RetentionExternalCopyState.PROVIDER_CONTROLLED,
            status_reason="retention.owner_memory.content_deletion_available",
        ),
        RetentionPolicyStatus(
            policy_id="retention.owner-delivery",
            data_category="data.owner-delivery",
            summary=(
                "Outbound delivery work and append-only delivery history are "
                "inventory-backed; deletion is not assembled yet."
            ),
            mode=RetentionMode.OWNER_LIFECYCLE,
            automatic_expiry=False,
            deletion_control=RetentionDeletionControl.NOT_IMPLEMENTED,
            tombstone_retained=True,
            derived_rebuild_required=True,
            external_copy_state=RetentionExternalCopyState.SOURCE_CONTROLLED,
            status_reason="retention.owner_delivery.inventory_available",
        ),
        RetentionPolicyStatus(
            policy_id="retention.telegram-quarantine",
            data_category="data.telegram-quarantine",
            summary="Quarantined attachment bytes expire automatically under a hard local bound.",
            mode=RetentionMode.AUTOMATIC_EXPIRY,
            duration_bounds=RetentionDurationBounds(
                minimum_seconds=3_600,
                default_seconds=86_400,
                maximum_seconds=604_800,
            ),
            automatic_expiry=True,
            deletion_control=RetentionDeletionControl.AUTOMATIC_ONLY,
            tombstone_retained=True,
            derived_rebuild_required=False,
            external_copy_state=RetentionExternalCopyState.SOURCE_CONTROLLED,
            status_reason="retention.telegram_quarantine.automatic",
        ),
    )


def _synthetic_retention_inventory() -> tuple[RetentionInventoryStatus, ...]:
    unavailable = {
        "retention.audit-ledger": "retention.inventory.audit_not_assembled",
        "retention.owner-conversation": "retention.inventory.not_assembled",
        "retention.owner-delivery": "retention.inventory.not_assembled",
        "retention.owner-memory": "retention.inventory.not_assembled",
    }
    unavailable_inventory = tuple(
        RetentionInventoryStatus(
            policy_id=policy_id,
            coverage=RetentionInventoryCoverage.UNAVAILABLE,
            status_reason=status_reason,
        )
        for policy_id, status_reason in unavailable.items()
    )
    return (
        *unavailable_inventory,
        RetentionInventoryStatus(
            policy_id="retention.telegram-quarantine",
            coverage=RetentionInventoryCoverage.COMPLETE,
            retained_objects=0,
            retained_bytes=0,
            overdue_objects=0,
            pending_deletions=0,
            deletion_receipts=0,
            status_reason="retention.inventory.empty",
        ),
    )


def _synthetic_telegram_component(
    worker: TelegramPollWorker,
    clock: Callable[[], datetime],
) -> ComponentHealth:
    health = worker.health()
    state = health["state"]
    if state == "healthy":
        health_state = HealthState.HEALTHY
        summary = "Bounded synthetic Telegram polling is healthy and performs no network calls."
    elif state == "disabled":
        health_state = HealthState.DISABLED
        summary = "Optional synthetic Telegram polling is suspended by Guardian mode."
    else:
        health_state = HealthState.DEGRADED
        summary = "Optional synthetic Telegram polling reports a redacted cycle failure."
    return ComponentHealth(
        component_id="worker.synthetic-telegram",
        category=HealthCategory.WORKER,
        state=health_state,
        required=False,
        observed_at=clock(),
        summary=summary,
    )


def _synthetic_retention_component(
    worker: TelegramAttachmentRetentionWorker,
    clock: Callable[[], datetime],
) -> ComponentHealth:
    health = worker.health()
    state = health["state"]
    if state == "healthy":
        health_state = HealthState.HEALTHY
        summary = "Bounded local quarantine expiry is healthy and performs no network calls."
    elif state == "disabled":
        health_state = HealthState.DISABLED
        summary = "Quarantine expiry is suspended by Guardian mode."
    else:
        health_state = HealthState.DEGRADED
        summary = "Quarantine expiry reports a redacted cycle failure."
    return ComponentHealth(
        component_id="worker.synthetic-retention",
        category=HealthCategory.WORKER,
        state=health_state,
        required=False,
        observed_at=clock(),
        summary=summary,
    )


def _synthetic_conversation_response(request: ModelRouteRequest) -> JsonObject:
    raw_citations = request.input.get("memory_citations", [])
    citation_ids: list[str] = []
    if isinstance(raw_citations, list):
        for citation in raw_citations:
            if not isinstance(citation, dict):
                continue
            citation_id = citation.get("citation_id")
            if isinstance(citation_id, str):
                citation_ids.append(citation_id)
    return {
        "text": (
            "Synthetic local reply. No external model, provider, or channel was called. "
            f"The deterministic retriever supplied {len(citation_ids)} citation(s)."
        ),
        "citation_ids": citation_ids,
    }
