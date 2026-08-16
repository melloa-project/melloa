"""Explicit process-local M1 runtime for private development and acceptance drills."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.client import FakeClientAdapter
from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.delivery import InMemoryDeliveryStore
from melloa.adapters.fakes.memory import InMemoryMemoryRepository
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.fakes.operations import InMemoryOperationsReader
from melloa.adapters.fakes.telegram import (
    DeterministicTelegramPairingCodeIssuer,
    FakeTelegramPairingChallengePublisher,
    FakeTelegramUpdateSource,
    InMemoryTelegramPairingStateStore,
    InMemoryTelegramPollStateStore,
    RejectingTelegramAttachmentBackend,
)
from melloa.application.conversation import ConversationService
from melloa.application.delivery import ClientDeliveryRoute, DeliveryService
from melloa.application.inspection import OwnerInspectionService
from melloa.application.memory import MemoryService
from melloa.application.operations import OwnerOperationsService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.application.routing import DeterministicModelRouter, ModelRouteBinding
from melloa.application.telegram import (
    TelegramIngestionService,
    TelegramPairingService,
    TelegramPollWorker,
)
from melloa.apps.core import create_app
from melloa.domain.base import JsonObject, QualifiedName, RecordId, new_record_id, utc_now
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.conversation import ConversationThread
from melloa.domain.memory import Assertion, AssertionStatus
from melloa.domain.models import ModelRouteRequest, ProcessingLocation, RegisteredModelRoute
from melloa.domain.operations import (
    ComponentHealth,
    HealthCategory,
    HealthState,
    MediaSourceStatus,
)
from melloa.ports.guardian import GuardianStatusReader

SYNTHETIC_OWNER_ID: RecordId = "owner_00000000000000000000000000000001"
SYNTHETIC_INTELLIGENCE_ID: RecordId = "intelligence_00000000000000000000000000000001"
SYNTHETIC_ASSERTION_ID: RecordId = "assertion_00000000000000000000000000000001"
SYNTHETIC_TELEGRAM_THREAD_ID: RecordId = "thread_00000000000000000000000000000002"
SYNTHETIC_TELEGRAM_ADAPTER_ID: QualifiedName = "client.telegram.synthetic"


@dataclass(frozen=True)
class SyntheticRuntime:
    app: FastAPI
    owner_id: RecordId
    intelligence_id: RecordId
    seed_assertion_id: RecordId
    telegram_thread_id: RecordId
    telegram_source: FakeTelegramUpdateSource
    telegram_poll_state_store: InMemoryTelegramPollStateStore
    telegram_pairing_service: TelegramPairingService
    telegram_challenge_publisher: FakeTelegramPairingChallengePublisher
    telegram_attachment_backend: RejectingTelegramAttachmentBackend
    telegram_worker: TelegramPollWorker


def build_synthetic_runtime(
    guardian_reader: GuardianStatusReader,
    bootstrap_token: str,
    *,
    clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[str], str] = new_record_id,
    telegram_worker_interval: float = 1.0,
) -> SyntheticRuntime:
    """Compose an in-memory runtime that performs no provider or channel network calls."""

    seeded_at = clock()
    assertion = Assertion(
        assertion_id=SYNTHETIC_ASSERTION_ID,
        subject_id=SYNTHETIC_OWNER_ID,
        predicate="owner.preference.synthetic-activity",
        value={
            "activity": "reading",
            "fixture": True,
            "note": "Synthetic process-local acceptance record.",
        },
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=seeded_at,
    )
    memory_store = InMemoryMemoryRepository((assertion,))
    conversation_store = InMemoryConversationStore(id_factory=id_factory)
    conversation_store.create_thread(
        ConversationThread(
            thread_id=SYNTHETIC_TELEGRAM_THREAD_ID,
            owner_id=SYNTHETIC_OWNER_ID,
            intelligence_id=SYNTHETIC_INTELLIGENCE_ID,
            title="Synthetic Telegram intake",
            sensitivity=Sensitivity.PERSONAL,
            retention_policy="retention.owner-conversation",
            created_at=seeded_at,
            updated_at=seeded_at,
        )
    )
    model_backend = FakeModelGateway(
        _synthetic_conversation_response,
        clock=clock,
        id_factory=id_factory,
    )
    model_router = DeterministicModelRouter(
        (
            ModelRouteBinding(
                route=RegisteredModelRoute(
                    route_id="model.fake.deterministic",
                    provider_id="provider.synthetic",
                    model_id="deterministic-fixture-v1",
                    processing_location=ProcessingLocation.DEVICE,
                    supported_modalities=frozenset({"text"}),
                    quality_profiles=frozenset({"quality.conversation-synthetic"}),
                    allowed_sensitivities=frozenset(Sensitivity),
                    provider_retention_policies=frozenset({"retention.no-training"}),
                    max_input_tokens=4_096,
                    max_output_tokens=1_024,
                    estimated_max_cost_gbp=0.0,
                    reliability=1.0,
                    priority=0,
                    external_disclosure=False,
                ),
                backend=model_backend,
            ),
        ),
        clock=clock,
    )
    sessions = InMemoryOwnerSessionManager(
        SYNTHETIC_OWNER_ID,
        bootstrap_token,
        clock=clock,
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
        runtime_version="melloa-core/0.1.0-synthetic",
    )
    telegram_source = FakeTelegramUpdateSource(adapter_id=SYNTHETIC_TELEGRAM_ADAPTER_ID)
    telegram_poll_state_store = InMemoryTelegramPollStateStore(
        adapter_id=SYNTHETIC_TELEGRAM_ADAPTER_ID,
        clock=lambda: seeded_at,
    )
    telegram_challenge_publisher = FakeTelegramPairingChallengePublisher()
    telegram_attachment_backend = RejectingTelegramAttachmentBackend(
        owner_id=SYNTHETIC_OWNER_ID,
        clock=clock,
    )
    telegram_pairing_service = TelegramPairingService(
        owner_id=SYNTHETIC_OWNER_ID,
        adapter_id=SYNTHETIC_TELEGRAM_ADAPTER_ID,
        store=InMemoryTelegramPairingStateStore(),
        code_issuer=DeterministicTelegramPairingCodeIssuer(),
        challenge_publisher=telegram_challenge_publisher,
        guardian_reader=guardian_reader,
        clock=clock,
        id_factory=id_factory,
    )
    telegram_ingestion = TelegramIngestionService(
        owner_id=SYNTHETIC_OWNER_ID,
        thread_id=SYNTHETIC_TELEGRAM_THREAD_ID,
        adapter_id=SYNTHETIC_TELEGRAM_ADAPTER_ID,
        pairing_service=telegram_pairing_service,
        attachment_backend=telegram_attachment_backend,
        conversation_store=conversation_store,
        poll_state_store=telegram_poll_state_store,
        guardian_reader=guardian_reader,
        clock=clock,
        id_factory=id_factory,
    )
    telegram_worker = TelegramPollWorker(
        adapter_id=SYNTHETIC_TELEGRAM_ADAPTER_ID,
        source=telegram_source,
        poll_state_store=telegram_poll_state_store,
        ingestion_service=telegram_ingestion,
        guardian_reader=guardian_reader,
        timeout_seconds=1,
        batch_limit=25,
        clock=clock,
    )
    memory = MemoryService(
        owner_id=SYNTHETIC_OWNER_ID,
        store=memory_store,
        guardian_reader=guardian_reader,
        clock=clock,
        id_factory=id_factory,
    )
    delivery_adapter = FakeClientAdapter(
        adapter_id="client.fake",
        destination_ref="synthetic:owner",
        clock=clock,
        id_factory=id_factory,
    )
    delivery = DeliveryService(
        owner_id=SYNTHETIC_OWNER_ID,
        intelligence_id=SYNTHETIC_INTELLIGENCE_ID,
        conversation_store=conversation_store,
        delivery_store=InMemoryDeliveryStore(id_factory=id_factory),
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
        clock=clock,
        id_factory=id_factory,
    )
    inspection = OwnerInspectionService(
        owner_id=SYNTHETIC_OWNER_ID,
        conversation_store=conversation_store,
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
                    summary="Synthetic private core is serving authenticated requests.",
                    version="0.1.0-synthetic",
                ),
                ComponentHealth(
                    component_id="worker.synthetic-reply",
                    category=HealthCategory.WORKER,
                    state=HealthState.HEALTHY,
                    required=True,
                    observed_at=seeded_at,
                    summary="Process-local worker resumes due canonical reply work.",
                ),
                ComponentHealth(
                    component_id="worker.synthetic-delivery",
                    category=HealthCategory.WORKER,
                    state=HealthState.HEALTHY,
                    required=True,
                    observed_at=seeded_at,
                    summary="Process-local worker resumes due exact-authority delivery work.",
                ),
                ComponentHealth(
                    component_id="database.not-configured",
                    category=HealthCategory.DATABASE,
                    state=HealthState.DISABLED,
                    required=False,
                    observed_at=seeded_at,
                    summary="PostgreSQL is not used by the process-local acceptance runtime.",
                ),
                ComponentHealth(
                    component_id="queue.process-memory",
                    category=HealthCategory.QUEUE,
                    state=HealthState.DEGRADED,
                    required=True,
                    observed_at=seeded_at,
                    summary="Retry state is process-local and is discarded on restart.",
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
                    component_id="storage.process-memory",
                    category=HealthCategory.STORAGE,
                    state=HealthState.DEGRADED,
                    required=True,
                    observed_at=seeded_at,
                    summary="State is process-local and is discarded on restart.",
                ),
                ComponentHealth(
                    component_id="backup.not-configured",
                    category=HealthCategory.BACKUP,
                    state=HealthState.DISABLED,
                    required=False,
                    observed_at=seeded_at,
                    summary="No backup is configured for intentionally ephemeral fixture data.",
                ),
                ComponentHealth(
                    component_id="deployment.synthetic-process",
                    category=HealthCategory.DEPLOYMENT,
                    state=HealthState.HEALTHY,
                    required=False,
                    observed_at=seeded_at,
                    summary="Explicit synthetic acceptance mode is active.",
                    version="0.1.0-synthetic",
                ),
            ),
            component_readers=(lambda: _synthetic_telegram_component(telegram_worker, clock),),
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
        clock=clock,
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
            run_conversation_worker=True,
            run_delivery_worker=True,
            run_telegram_worker=True,
            telegram_worker_interval=telegram_worker_interval,
        ),
        owner_id=SYNTHETIC_OWNER_ID,
        intelligence_id=SYNTHETIC_INTELLIGENCE_ID,
        seed_assertion_id=SYNTHETIC_ASSERTION_ID,
        telegram_thread_id=SYNTHETIC_TELEGRAM_THREAD_ID,
        telegram_source=telegram_source,
        telegram_poll_state_store=telegram_poll_state_store,
        telegram_pairing_service=telegram_pairing_service,
        telegram_challenge_publisher=telegram_challenge_publisher,
        telegram_attachment_backend=telegram_attachment_backend,
        telegram_worker=telegram_worker,
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
