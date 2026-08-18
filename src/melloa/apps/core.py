"""Private Melloa API with verified Guardian and owner-authentication boundaries."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.background import BackgroundTask

from melloa.adapters.guardian.file import GuardianVerificationError
from melloa.application.conversation import (
    ConversationOwnershipError,
    ConversationReply,
    ConversationService,
    ConversationUnavailableError,
    InvalidModelOutputError,
)
from melloa.application.delivery import (
    DeliveryOwnershipError,
    DeliveryService,
    DeliverySubmission,
    DeliveryUnavailableError,
)
from melloa.application.exports import ExportBundleError, OwnerExportService
from melloa.application.inspection import (
    InspectionOwnershipError,
    InspectionWindowError,
    OwnerInspectionService,
)
from melloa.application.memory import (
    MemoryOwnershipError,
    MemoryService,
    MemoryUnavailableError,
)
from melloa.application.operations import OwnerOperationsService
from melloa.application.retention import (
    OwnerRetentionService,
    RetentionInspectionUnavailableError,
    RetentionOwnershipError,
)
from melloa.application.routing import ModelRouteOwnershipError, OwnerModelRouteService
from melloa.application.status import SystemStatus, read_system_status
from melloa.application.telegram import (
    TelegramAttachmentRetentionWorker,
    TelegramIngestionUnavailableError,
    TelegramPairingOwnershipError,
    TelegramPairingService,
    TelegramPairingUnavailableError,
    TelegramPollWorker,
    TelegramReplyDispatcher,
    TelegramRetentionUnavailableError,
)
from melloa.domain.audit import AuditContent
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import (
    JsonObject,
    QualifiedName,
    RecordId,
    canonical_json_bytes,
    new_record_id,
    sha256_digest,
    utc_now,
)
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingState,
    ConversationProcessingStatus,
    ConversationThread,
    ConversationTurn,
    ConversationTurnInspection,
)
from melloa.domain.delivery import DeliveryWorkState, DeliveryWorkStatus
from melloa.domain.events import EventEnvelope, EventIntegrity, EventProducer, EventSource
from melloa.domain.exports import CanonicalExportManifest
from melloa.domain.inspection import OwnerModelActivityReport, OwnerTimelineReport
from melloa.domain.memory import (
    AssertionContentDeletionResult,
    AssertionCorrectionResult,
    AssertionStateTransitionResult,
    MemoryInspection,
)
from melloa.domain.models import OwnerModelRouteReport
from melloa.domain.operations import (
    OwnerExportReadinessReport,
    OwnerHealthReport,
    OwnerMediaCatalog,
)
from melloa.domain.retention import OwnerRetentionReport
from melloa.domain.telegram import (
    TelegramChatId,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramUpdateId,
    TelegramUserId,
)
from melloa.ports.auth import (
    AuthenticationError,
    CsrfValidationError,
    OwnerSessionExpired,
    OwnerSessionManager,
    OwnerSessionMissing,
    RecentAuthenticationRequired,
)
from melloa.ports.client import ClientAdapter
from melloa.ports.conversation import ConversationConflictError, ConversationNotFoundError
from melloa.ports.delivery import DeliveryConflictError, DeliveryNotFoundError
from melloa.ports.guardian import GuardianStatusReader
from melloa.ports.memory import MemoryConflictError, MemoryNotFoundError
from melloa.ports.store import EventAuditStore
from melloa.ports.telegram import (
    TelegramPairingConflictError,
    TelegramPairingNotFoundError,
    TelegramPollingError,
)
from melloa.release import CURRENT_RELEASE

_SESSION_COOKIE = "__Host-melloa_session"
_CSRF_HEADER = "X-Melloa-CSRF"
_LOGGER = logging.getLogger(__name__)


class _OwnerLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential: SecretStr = Field(min_length=32, max_length=4096)


class _OwnerSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal: AuthenticatedOwner
    csrf_token: str = Field(min_length=1, max_length=4096)


class _OwnerSessionInventoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_session_id: RecordId
    sessions: tuple[AuthenticatedOwner, ...]


class _OwnerSessionRevocationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revoked_count: int = Field(ge=0)


class _CreateThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=256)
    sensitivity: Sensitivity
    retention_policy: QualifiedName


class _PostOwnerMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100_000)
    idempotency_key: str = Field(min_length=1, max_length=256)


class _CorrectMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: JsonObject
    expected_version: int = Field(gt=0)


class _ChangeMemoryStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)


class _ConversationReplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbound_message: ConversationMessage
    output_message: ConversationMessage | None
    turn: ConversationTurn | None
    processing: ConversationProcessingStatus
    duplicate: bool


class _EnqueueDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: RecordId
    client_adapter: QualifiedName
    destination_ref: str = Field(min_length=1, max_length=512)
    idempotency_key: str = Field(min_length=1, max_length=256)


class _DeliverySubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: DeliveryWorkStatus
    created: bool


class _TelegramPairingCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: RecordId
    update_id: TelegramUpdateId
    telegram_user_id: TelegramUserId
    telegram_chat_id: TelegramChatId
    observed_at: datetime
    expires_at: datetime

    @classmethod
    def from_candidate(
        cls,
        candidate: TelegramPairingCandidate,
    ) -> _TelegramPairingCandidateResponse:
        return cls(
            candidate_id=candidate.candidate_id,
            update_id=candidate.update_id,
            telegram_user_id=candidate.telegram_user_id,
            telegram_chat_id=candidate.telegram_chat_id,
            observed_at=candidate.observed_at,
            expires_at=candidate.expires_at,
        )


class _ConfirmTelegramPairingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_code: SecretStr = Field(min_length=20, max_length=128)


async def _run_periodic_worker(
    operation: Callable[[], Awaitable[object]],
    *,
    interval: float,
    failure_message: str,
    ignored_errors: tuple[type[Exception], ...] = (),
) -> None:
    while True:
        try:
            await operation()
        except Exception as error:
            if not isinstance(error, ignored_errors):
                _LOGGER.exception(failure_message)
        await asyncio.sleep(interval)


async def _run_periodic_sync_worker(
    operation: Callable[[], object],
    *,
    interval: float,
    failure_message: str,
    ignored_errors: tuple[type[Exception], ...] = (),
) -> None:
    await _run_periodic_worker(
        lambda: asyncio.to_thread(operation),
        interval=interval,
        failure_message=failure_message,
        ignored_errors=ignored_errors,
    )


async def _run_conversation_worker(
    service: ConversationService,
    *,
    interval: float,
) -> None:
    await _run_periodic_sync_worker(
        service.process_ready,
        interval=interval,
        failure_message="conversation reply worker cycle failed",
        ignored_errors=(ConversationUnavailableError,),
    )


async def _run_delivery_worker(
    service: DeliveryService,
    *,
    interval: float,
) -> None:
    await _run_periodic_sync_worker(
        service.process_ready,
        interval=interval,
        failure_message="outbound delivery worker cycle failed",
    )


async def _poll_and_dispatch_telegram(
    worker: TelegramPollWorker,
    reply_dispatcher: TelegramReplyDispatcher | None,
) -> None:
    try:
        cycle = await asyncio.to_thread(worker.poll_once)
        if reply_dispatcher is not None:
            reply_dispatcher.observe_poll_cycle(cycle)
    except (TelegramIngestionUnavailableError, TelegramPollingError):
        pass
    except Exception:
        _LOGGER.exception("Telegram poll worker cycle failed")
    if reply_dispatcher is not None:
        try:
            await asyncio.to_thread(reply_dispatcher.dispatch_ready)
        except ConversationUnavailableError:
            pass
        except Exception:
            _LOGGER.exception("Telegram reply dispatch cycle failed")


async def _run_telegram_worker(
    worker: TelegramPollWorker,
    *,
    interval: float,
    reply_dispatcher: TelegramReplyDispatcher | None = None,
) -> None:
    await _run_periodic_worker(
        lambda: _poll_and_dispatch_telegram(worker, reply_dispatcher),
        interval=interval,
        failure_message="Telegram worker cycle failed",
    )


async def _run_telegram_retention_worker(
    worker: TelegramAttachmentRetentionWorker,
    *,
    interval: float,
) -> None:
    await _run_periodic_sync_worker(
        worker.sweep_once,
        interval=interval,
        failure_message="Telegram attachment retention worker cycle failed",
        ignored_errors=(TelegramRetentionUnavailableError,),
    )


def _required_app_state(
    request: Request,
    attribute: str,
    unavailable_detail: str,
) -> object:
    value = cast(object | None, getattr(request.app.state, attribute, None))
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_detail,
        )
    return value


def _configured_sessions(request: Request) -> OwnerSessionManager:
    return cast(
        OwnerSessionManager,
        _required_app_state(
            request,
            "owner_sessions",
            "Owner authentication is not configured.",
        ),
    )


def _configured_conversation(request: Request) -> ConversationService:
    return cast(
        ConversationService,
        _required_app_state(
            request,
            "conversation_service",
            "Canonical conversation is not configured.",
        ),
    )


def _configured_memory(request: Request) -> MemoryService:
    return cast(
        MemoryService,
        _required_app_state(
            request,
            "memory_service",
            "Memory inspection and correction are not configured.",
        ),
    )


def _configured_delivery(request: Request) -> DeliveryService:
    return cast(
        DeliveryService,
        _required_app_state(
            request,
            "delivery_service",
            "Outbound delivery is not configured.",
        ),
    )


def _configured_inspection(request: Request) -> OwnerInspectionService:
    return cast(
        OwnerInspectionService,
        _required_app_state(
            request,
            "inspection_service",
            "Owner activity inspection is not configured.",
        ),
    )


def _configured_operations(request: Request) -> OwnerOperationsService:
    return cast(
        OwnerOperationsService,
        _required_app_state(
            request,
            "operations_service",
            "Owner health and media inspection are not configured.",
        ),
    )


def _configured_export(request: Request) -> tuple[OwnerExportService, Path]:
    export_service = cast(
        OwnerExportService,
        _required_app_state(
            request,
            "export_service",
            "Owner export download is not configured.",
        ),
    )
    schema_root = cast(
        Path,
        _required_app_state(
            request,
            "export_schema_root",
            "Owner export download is not configured.",
        ),
    )
    return export_service, schema_root


def _configured_retention(request: Request) -> OwnerRetentionService:
    return cast(
        OwnerRetentionService,
        _required_app_state(
            request,
            "retention_service",
            "Owner retention inspection is not configured.",
        ),
    )


def _configured_model_routes(request: Request) -> OwnerModelRouteService:
    return cast(
        OwnerModelRouteService,
        _required_app_state(
            request,
            "model_route_service",
            "Model route inspection is not configured.",
        ),
    )


def _configured_telegram_pairing(request: Request) -> TelegramPairingService:
    return cast(
        TelegramPairingService,
        _required_app_state(
            request,
            "telegram_pairing_service",
            "Telegram pairing is not configured.",
        ),
    )


def _create_export_workspace() -> Path:
    return Path(tempfile.mkdtemp(prefix="melloa-owner-export-"))


def _append_auth_security_audit(
    event_audit_store: EventAuditStore,
    *,
    owner_id: RecordId,
    occurred_at: datetime,
    id_factory: Callable[[str], str],
    event_type: QualifiedName,
    capability_id: QualifiedName,
    action: QualifiedName,
    actor_id: RecordId,
    payload: JsonObject,
) -> None:
    event_id = id_factory("event")
    audit_id = id_factory("audit")
    event = EventEnvelope(
        event_id=event_id,
        event_type=event_type,
        schema_version="1.0.0",
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        subject_ids=(owner_id,),
        source=EventSource(
            capability_id=capability_id,
            execution_id=event_id,
        ),
        producer=EventProducer(
            component="auth.private-core",
            version=CURRENT_RELEASE.package_version,
        ),
        epistemic_status=EpistemicStatus.OBSERVATION,
        sensitivity=Sensitivity.INTERNAL,
        trust=TrustLabel.TRUSTED_SYSTEM,
        retention_policy="retention.audit-ledger",
        correlation_id=event_id,
        payload=payload,
        integrity=EventIntegrity(
            payload_hash=sha256_digest(canonical_json_bytes(payload))
        ),
    )
    audit = AuditContent(
        audit_id=audit_id,
        event_type="audit.event-appended.v1",
        occurred_at=occurred_at,
        actor_id=actor_id,
        action=action,
        object_ids=(event_id,),
        metadata={
            "event_id": event_id,
            "reason_code": payload["reason_code"],
            "result": payload["result"],
        },
    )
    event_audit_store.append_event(event, audit)


def _append_owner_export_preview_audit(
    event_audit_store: EventAuditStore,
    *,
    owner_id: RecordId,
    principal: AuthenticatedOwner,
    manifest: CanonicalExportManifest,
    occurred_at: datetime,
    id_factory: Callable[[str], str],
) -> None:
    data_file_count = sum(1 for entry in manifest.files if entry.record_count is not None)
    exported_record_count = sum(
        entry.record_count for entry in manifest.files if entry.record_count is not None
    )
    payload: JsonObject = {
        "export_id": manifest.export_id,
        "format_id": manifest.format_id,
        "format_version": manifest.format_version,
        "encrypted": manifest.encrypted,
        "includes_sql_snapshot": manifest.includes_sql_snapshot,
        "includes_blobs": manifest.includes_blobs,
        "file_count": len(manifest.files),
        "data_file_count": data_file_count,
        "exported_record_count": exported_record_count,
        "limitation_ids": tuple(manifest.limitations),
        "limitation_count": len(manifest.limitations),
        "reason_code": "export.owner-preview.generated",
        "result": "generated",
    }
    event_id = id_factory("event")
    audit_id = id_factory("audit")
    event = EventEnvelope(
        event_id=event_id,
        event_type="export.owner-preview-generated.v1",
        schema_version="1.0.0",
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        subject_ids=(owner_id, manifest.export_id),
        source=EventSource(
            capability_id="export.owner-preview",
            execution_id=event_id,
        ),
        producer=EventProducer(
            component="export.private-core",
            version=CURRENT_RELEASE.package_version,
        ),
        epistemic_status=EpistemicStatus.OBSERVATION,
        sensitivity=Sensitivity.INTERNAL,
        trust=TrustLabel.TRUSTED_SYSTEM,
        retention_policy="retention.audit-ledger",
        correlation_id=event_id,
        payload=payload,
        integrity=EventIntegrity(
            payload_hash=sha256_digest(canonical_json_bytes(payload))
        ),
    )
    audit = AuditContent(
        audit_id=audit_id,
        event_type="audit.event-appended.v1",
        occurred_at=occurred_at,
        actor_id=principal.owner_id,
        action="export.owner-preview.generate",
        object_ids=(event_id, manifest.export_id),
        metadata={
            "event_id": event_id,
            "export_id": manifest.export_id,
            "format_id": manifest.format_id,
            "reason_code": payload["reason_code"],
            "result": payload["result"],
            "file_count": payload["file_count"],
            "data_file_count": data_file_count,
            "exported_record_count": exported_record_count,
            "limitation_count": payload["limitation_count"],
        },
    )
    event_audit_store.append_event(event, audit)


def _append_owner_delivery_audit(
    request: Request,
    *,
    principal: AuthenticatedOwner,
    operation: Literal["enqueue", "resume"],
    result: Literal["accepted", "denied"],
    reason_code: QualifiedName,
    thread_id: RecordId,
    message_id: RecordId | None = None,
    work_id: RecordId | None = None,
    client_adapter: QualifiedName | None = None,
    delivery: DeliveryWorkStatus | None = None,
    created: bool | None = None,
) -> None:
    event_audit_store: EventAuditStore | None = request.app.state.event_audit_store
    owner_id: RecordId | None = request.app.state.owner_id
    if event_audit_store is None or owner_id is None:
        return
    occurred_at = request.app.state.security_event_clock()
    id_factory: Callable[[str], str] = request.app.state.security_event_id_factory
    event_id = id_factory("event")
    audit_id = id_factory("audit")
    payload: JsonObject = {
        "operation": operation,
        "reason_code": reason_code,
        "result": result,
        "thread_id": thread_id,
    }
    subject_ids: list[RecordId] = [owner_id, thread_id]
    object_ids: list[RecordId] = [event_id, thread_id]
    if message_id is not None:
        payload["message_id"] = message_id
        subject_ids.append(message_id)
        object_ids.append(message_id)
    if work_id is not None:
        payload["work_id"] = work_id
        subject_ids.append(work_id)
        object_ids.append(work_id)
    if client_adapter is not None:
        payload["client_adapter"] = client_adapter
    if created is not None:
        payload["created"] = created
    decision_id = None
    if delivery is not None:
        decision_id = delivery.current_policy_decision_id
        payload.update(
            {
                "attempt_count": delivery.attempt_count,
                "delivery_state": delivery.state.value,
                "max_attempts": delivery.max_attempts,
                "policy_decision_id": delivery.current_policy_decision_id,
                "resumption_count": len(delivery.resumptions),
            }
        )
    event = EventEnvelope(
        event_id=event_id,
        event_type=f"delivery.owner-{operation}-{result}.v1",
        schema_version="1.0.0",
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        subject_ids=tuple(dict.fromkeys(subject_ids)),
        source=EventSource(
            capability_id="delivery.owner-outbound",
            execution_id=event_id,
        ),
        producer=EventProducer(
            component="delivery.private-core",
            version=CURRENT_RELEASE.package_version,
        ),
        epistemic_status=EpistemicStatus.OBSERVATION,
        sensitivity=Sensitivity.INTERNAL,
        trust=TrustLabel.TRUSTED_SYSTEM,
        retention_policy="retention.audit-ledger",
        correlation_id=event_id,
        payload=payload,
        integrity=EventIntegrity(
            payload_hash=sha256_digest(canonical_json_bytes(payload))
        ),
    )
    audit = AuditContent(
        audit_id=audit_id,
        event_type="audit.event-appended.v1",
        occurred_at=occurred_at,
        actor_id=principal.owner_id,
        action=f"delivery.owner-{operation}.{result}",
        object_ids=tuple(dict.fromkeys(object_ids)),
        decision_id=decision_id,
        metadata={
            "event_id": event_id,
            "operation": operation,
            "reason_code": reason_code,
            "result": result,
        },
    )
    event_audit_store.append_event(event, audit)


def _append_owner_conversation_audit(
    request: Request,
    *,
    principal: AuthenticatedOwner,
    operation: Literal["accept", "resume"],
    result: Literal["accepted", "denied"],
    reason_code: QualifiedName,
    thread_id: RecordId,
    message_id: RecordId | None = None,
    reply: ConversationReply | None = None,
) -> None:
    event_audit_store: EventAuditStore | None = request.app.state.event_audit_store
    owner_id: RecordId | None = request.app.state.owner_id
    if event_audit_store is None or owner_id is None:
        return
    occurred_at = request.app.state.security_event_clock()
    id_factory: Callable[[str], str] = request.app.state.security_event_id_factory
    event_id = id_factory("event")
    audit_id = id_factory("audit")
    payload: JsonObject = {
        "operation": operation,
        "reason_code": reason_code,
        "result": result,
        "thread_id": thread_id,
    }
    subject_ids: list[RecordId] = [owner_id, thread_id]
    object_ids: list[RecordId] = [event_id, thread_id]
    effective_message_id = message_id
    if reply is not None:
        effective_message_id = reply.inbound_message.message_id
        payload.update(
            {
                "attempt_count": reply.processing.attempt_count,
                "duplicate": reply.duplicate,
                "max_attempts": reply.processing.max_attempts,
                "processing_state": reply.processing.state.value,
                "resumption_count": len(reply.processing.resumptions),
                "work_id": reply.processing.work_id,
            }
        )
        object_ids.append(reply.processing.work_id)
        subject_ids.append(reply.processing.work_id)
        if reply.output_message is not None:
            payload["output_message_id"] = reply.output_message.message_id
            object_ids.append(reply.output_message.message_id)
            subject_ids.append(reply.output_message.message_id)
        if reply.turn is not None:
            payload["turn_id"] = reply.turn.turn_id
            object_ids.append(reply.turn.turn_id)
            subject_ids.append(reply.turn.turn_id)
    if effective_message_id is not None:
        payload["message_id"] = effective_message_id
        object_ids.append(effective_message_id)
        subject_ids.append(effective_message_id)
    event = EventEnvelope(
        event_id=event_id,
        event_type=f"conversation.owner-message-{operation}-{result}.v1",
        schema_version="1.0.0",
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        subject_ids=tuple(dict.fromkeys(subject_ids)),
        source=EventSource(
            capability_id="conversation.owner-canonical",
            execution_id=event_id,
        ),
        producer=EventProducer(
            component="conversation.private-core",
            version=CURRENT_RELEASE.package_version,
        ),
        epistemic_status=EpistemicStatus.OBSERVATION,
        sensitivity=Sensitivity.INTERNAL,
        trust=TrustLabel.TRUSTED_SYSTEM,
        retention_policy="retention.audit-ledger",
        correlation_id=event_id,
        payload=payload,
        integrity=EventIntegrity(
            payload_hash=sha256_digest(canonical_json_bytes(payload))
        ),
    )
    audit = AuditContent(
        audit_id=audit_id,
        event_type="audit.event-appended.v1",
        occurred_at=occurred_at,
        actor_id=principal.owner_id,
        action=f"conversation.owner-message-{operation}.{result}",
        object_ids=tuple(dict.fromkeys(object_ids)),
        metadata={
            "event_id": event_id,
            "operation": operation,
            "reason_code": reason_code,
            "result": result,
        },
    )
    event_audit_store.append_event(event, audit)


def _append_failed_login_audit(
    event_audit_store: EventAuditStore,
    *,
    owner_id: RecordId,
    occurred_at: datetime,
    id_factory: Callable[[str], str],
) -> None:
    payload: JsonObject = {
        "authentication_method": "auth.local-opaque-token",
        "reason_code": "auth.owner-credential.invalid",
        "result": "denied",
        "session_issued": False,
    }
    _append_auth_security_audit(
        event_audit_store,
        owner_id=owner_id,
        occurred_at=occurred_at,
        id_factory=id_factory,
        event_type="auth.owner-login-denied.v1",
        capability_id="auth.owner-login",
        action="auth.owner-login.deny",
        actor_id=_unauthenticated_actor_id(owner_id),
        payload=payload,
    )


def _append_owner_mutation_denial_audit(
    event_audit_store: EventAuditStore,
    *,
    owner_id: RecordId,
    occurred_at: datetime,
    id_factory: Callable[[str], str],
    boundary: str,
    reason_code: QualifiedName,
) -> None:
    payload: JsonObject = {
        "boundary": boundary,
        "mutation_authorized": False,
        "reason_code": reason_code,
        "result": "denied",
    }
    _append_auth_security_audit(
        event_audit_store,
        owner_id=owner_id,
        occurred_at=occurred_at,
        id_factory=id_factory,
        event_type="auth.owner-mutation-denied.v1",
        capability_id="auth.owner-mutation-boundary",
        action="auth.owner-mutation.deny",
        actor_id=_derived_auth_actor_id(owner_id, "session-boundary-request"),
        payload=payload,
    )


def _append_owner_session_denial_audit(
    event_audit_store: EventAuditStore,
    *,
    owner_id: RecordId,
    occurred_at: datetime,
    id_factory: Callable[[str], str],
    reason_code: QualifiedName,
) -> None:
    payload: JsonObject = {
        "boundary": "owner-session",
        "reason_code": reason_code,
        "request_authenticated": False,
        "result": "denied",
        "session_verified": False,
    }
    _append_auth_security_audit(
        event_audit_store,
        owner_id=owner_id,
        occurred_at=occurred_at,
        id_factory=id_factory,
        event_type="auth.owner-session-denied.v1",
        capability_id="auth.owner-session",
        action="auth.owner-session.deny",
        actor_id=_unauthenticated_actor_id(owner_id),
        payload=payload,
    )


def _should_skip_session_denial_audit(request: Request) -> bool:
    return request.method == "GET" and request.url.path == "/api/v1/auth/session"


def _append_auth_denial_audit_from_error(
    request: Request,
    error: AuthenticationError,
) -> None:
    event_audit_store: EventAuditStore | None = request.app.state.event_audit_store
    owner_id: RecordId | None = request.app.state.owner_id
    if event_audit_store is None or owner_id is None:
        return
    if isinstance(error, CsrfValidationError):
        boundary = "csrf"
        reason_code = "auth.csrf.invalid"
    elif isinstance(error, RecentAuthenticationRequired):
        boundary = "recent-auth"
        reason_code = "auth.recent-auth.required"
    elif isinstance(error, OwnerSessionExpired):
        if _should_skip_session_denial_audit(request):
            return
        _append_owner_session_denial_audit(
            event_audit_store,
            owner_id=owner_id,
            occurred_at=request.app.state.security_event_clock(),
            id_factory=request.app.state.security_event_id_factory,
            reason_code="auth.owner-session.expired",
        )
        return
    elif isinstance(error, OwnerSessionMissing):
        if _should_skip_session_denial_audit(request):
            return
        _append_owner_session_denial_audit(
            event_audit_store,
            owner_id=owner_id,
            occurred_at=request.app.state.security_event_clock(),
            id_factory=request.app.state.security_event_id_factory,
            reason_code="auth.owner-session.missing",
        )
        return
    else:
        return
    _append_owner_mutation_denial_audit(
        event_audit_store,
        owner_id=owner_id,
        occurred_at=request.app.state.security_event_clock(),
        id_factory=request.app.state.security_event_id_factory,
        boundary=boundary,
        reason_code=reason_code,
    )


def _unauthenticated_actor_id(owner_id: RecordId) -> RecordId:
    return _derived_auth_actor_id(owner_id, "unauthenticated-request")


def _derived_auth_actor_id(owner_id: RecordId, actor: str) -> RecordId:
    digest = sha256_digest(
        canonical_json_bytes(
            {
                "actor": actor,
                "owner_id": owner_id,
            }
        )
    ).removeprefix("sha256:")
    return f"actor_{digest[:32]}"


def _authenticated_owner(request: Request) -> AuthenticatedOwner:
    session_token = request.cookies.get(_SESSION_COOKIE, "")
    return _configured_sessions(request).verify(session_token)


def _authenticated_owner_mutation(
    request: Request,
    csrf_token: Annotated[str | None, Header(alias=_CSRF_HEADER)] = None,
) -> AuthenticatedOwner:
    session_token = request.cookies.get(_SESSION_COOKIE, "")
    return _configured_sessions(request).verify(
        session_token,
        csrf_token=csrf_token,
        require_csrf=True,
    )


def _authenticated_owner_sensitive_mutation(
    request: Request,
    csrf_token: Annotated[str | None, Header(alias=_CSRF_HEADER)] = None,
) -> AuthenticatedOwner:
    session_token = request.cookies.get(_SESSION_COOKIE, "")
    return _configured_sessions(request).verify(
        session_token,
        csrf_token=csrf_token,
        require_csrf=True,
        require_recent=True,
    )


def create_app(
    guardian_reader: GuardianStatusReader,
    owner_sessions: OwnerSessionManager | None = None,
    conversation_service: ConversationService | None = None,
    memory_service: MemoryService | None = None,
    inspection_service: OwnerInspectionService | None = None,
    operations_service: OwnerOperationsService | None = None,
    delivery_service: DeliveryService | None = None,
    telegram_worker: TelegramPollWorker | None = None,
    telegram_pairing_service: TelegramPairingService | None = None,
    telegram_retention_worker: TelegramAttachmentRetentionWorker | None = None,
    telegram_reply_dispatcher: TelegramReplyDispatcher | None = None,
    telegram_delivery_adapter: ClientAdapter | None = None,
    retention_service: OwnerRetentionService | None = None,
    model_route_service: OwnerModelRouteService | None = None,
    *,
    owner_id: RecordId | None = None,
    event_audit_store: EventAuditStore | None = None,
    security_event_clock: Callable[[], datetime] = utc_now,
    security_event_id_factory: Callable[[str], str] = new_record_id,
    export_service: OwnerExportService | None = None,
    export_schema_root: Path | None = None,
    secure_session_cookie: bool = True,
    run_conversation_worker: bool = False,
    conversation_worker_interval: float = 1.0,
    run_delivery_worker: bool = False,
    delivery_worker_interval: float = 1.0,
    run_telegram_worker: bool = False,
    telegram_worker_interval: float = 1.0,
    run_telegram_retention_worker: bool = False,
    telegram_retention_worker_interval: float = 60.0,
    telegram_state_persistence: str = "process-only-preview",
) -> FastAPI:
    if conversation_worker_interval <= 0:
        raise ValueError("conversation worker interval must be positive")
    if delivery_worker_interval <= 0:
        raise ValueError("delivery worker interval must be positive")
    if telegram_worker_interval <= 0:
        raise ValueError("Telegram worker interval must be positive")
    if telegram_retention_worker_interval <= 0:
        raise ValueError("Telegram retention worker interval must be positive")
    if telegram_state_persistence not in {"process-only-preview", "postgresql"}:
        raise ValueError("Telegram state persistence mode is not supported")
    if (export_service is None) != (export_schema_root is None):
        raise ValueError("export service and schema root must be configured together")
    if run_conversation_worker and conversation_service is None:
        raise ValueError("conversation worker requires a configured conversation service")
    if run_delivery_worker and delivery_service is None:
        raise ValueError("delivery worker requires a configured delivery service")
    if run_telegram_worker and telegram_worker is None:
        raise ValueError("Telegram worker requires a configured poll worker")
    if run_telegram_retention_worker and telegram_retention_worker is None:
        raise ValueError("Telegram retention worker requires a configured retention worker")
    if event_audit_store is not None and owner_id is None:
        raise ValueError("owner ID is required for authentication audit events")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        worker_tasks: list[asyncio.Task[None]] = []
        if run_conversation_worker and conversation_service is not None:
            worker_tasks.append(
                asyncio.create_task(
                    _run_conversation_worker(
                        conversation_service,
                        interval=conversation_worker_interval,
                    )
                )
            )
        if run_delivery_worker and delivery_service is not None:
            worker_tasks.append(
                asyncio.create_task(
                    _run_delivery_worker(
                        delivery_service,
                        interval=delivery_worker_interval,
                    )
                )
            )
        if run_telegram_worker and telegram_worker is not None:
            worker_tasks.append(
                asyncio.create_task(
                    _run_telegram_worker(
                        telegram_worker,
                        interval=telegram_worker_interval,
                        reply_dispatcher=telegram_reply_dispatcher,
                    )
                )
            )
        if run_telegram_retention_worker and telegram_retention_worker is not None:
            worker_tasks.append(
                asyncio.create_task(
                    _run_telegram_retention_worker(
                        telegram_retention_worker,
                        interval=telegram_retention_worker_interval,
                    )
                )
            )
        try:
            yield
        finally:
            for worker_task in worker_tasks:
                worker_task.cancel()
            for worker_task in worker_tasks:
                with suppress(asyncio.CancelledError):
                    await worker_task

    app = FastAPI(
        title="Melloa private core",
        version=CURRENT_RELEASE.package_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.owner_sessions = owner_sessions
    app.state.conversation_service = conversation_service
    app.state.memory_service = memory_service
    app.state.inspection_service = inspection_service
    app.state.operations_service = operations_service
    app.state.export_service = export_service
    app.state.export_schema_root = export_schema_root
    app.state.retention_service = retention_service
    app.state.model_route_service = model_route_service
    app.state.delivery_service = delivery_service
    app.state.owner_id = owner_id
    app.state.event_audit_store = event_audit_store
    app.state.security_event_clock = security_event_clock
    app.state.security_event_id_factory = security_event_id_factory
    app.state.telegram_worker = telegram_worker
    app.state.telegram_pairing_service = telegram_pairing_service
    app.state.telegram_retention_worker = telegram_retention_worker
    app.state.telegram_reply_dispatcher = telegram_reply_dispatcher
    app.state.telegram_delivery_adapter = telegram_delivery_adapter
    app.state.telegram_state_persistence = telegram_state_persistence

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(GuardianVerificationError)
    async def guardian_unavailable(
        _request: Request,
        _error: GuardianVerificationError,
    ) -> JSONResponse:
        message = "Guardian status is unavailable or unauthentic; authority remains disabled."
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "guardian_status_unverified",
                "message": message,
            },
        )

    @app.exception_handler(AuthenticationError)
    async def authentication_failed(
        request: Request,
        error: AuthenticationError,
    ) -> JSONResponse:
        if isinstance(error, CsrfValidationError):
            response_status = status.HTTP_403_FORBIDDEN
            code = "csrf_validation_failed"
            message = "The browser action could not be authenticated."
        elif isinstance(error, RecentAuthenticationRequired):
            response_status = status.HTTP_403_FORBIDDEN
            code = "recent_authentication_required"
            message = "Recent owner authentication is required."
        else:
            response_status = status.HTTP_401_UNAUTHORIZED
            code = "owner_authentication_failed"
            message = "Owner authentication failed."
        _append_auth_denial_audit_from_error(request, error)
        return JSONResponse(
            status_code=response_status,
            content={"code": code, "message": message},
        )

    @app.exception_handler(TelegramPairingNotFoundError)
    @app.exception_handler(TelegramPairingOwnershipError)
    async def telegram_pairing_not_found(
        _request: Request,
        _error: TelegramPairingNotFoundError | TelegramPairingOwnershipError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "telegram_pairing_not_found",
                "message": "Telegram pairing record not found.",
            },
        )

    @app.exception_handler(TelegramPairingConflictError)
    async def telegram_pairing_conflict(
        _request: Request,
        _error: TelegramPairingConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "telegram_pairing_conflict",
                "message": "Telegram pairing state conflicts with this request.",
            },
        )

    @app.exception_handler(TelegramPairingUnavailableError)
    async def telegram_pairing_unavailable(
        _request: Request,
        _error: TelegramPairingUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "telegram_pairing_unavailable",
                "message": "Guardian or runtime state does not permit Telegram pairing.",
            },
        )

    @app.exception_handler(ConversationNotFoundError)
    @app.exception_handler(ConversationOwnershipError)
    async def conversation_not_found(
        _request: Request,
        _error: ConversationNotFoundError | ConversationOwnershipError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": "conversation_not_found", "message": "Conversation not found."},
        )

    @app.exception_handler(ConversationConflictError)
    async def conversation_conflict(
        _request: Request,
        _error: ConversationConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "conversation_conflict",
                "message": "Canonical conversation data conflicts with an existing record.",
            },
        )

    @app.exception_handler(ConversationUnavailableError)
    async def conversation_unavailable(
        _request: Request,
        _error: ConversationUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "conversation_write_unavailable",
                "message": "Guardian or runtime state does not permit conversation writes.",
            },
        )

    @app.exception_handler(DeliveryNotFoundError)
    @app.exception_handler(DeliveryOwnershipError)
    async def delivery_not_found(
        _request: Request,
        _error: DeliveryNotFoundError | DeliveryOwnershipError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": "delivery_not_found", "message": "Delivery not found."},
        )

    @app.exception_handler(DeliveryConflictError)
    async def delivery_conflict(
        _request: Request,
        _error: DeliveryConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "delivery_conflict",
                "message": "Outbound delivery conflicts with an existing record.",
            },
        )

    @app.exception_handler(DeliveryUnavailableError)
    async def delivery_unavailable(
        _request: Request,
        _error: DeliveryUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "delivery_unavailable",
                "message": "Outbound delivery is unavailable.",
            },
        )

    @app.exception_handler(InvalidModelOutputError)
    async def invalid_model_output(
        _request: Request,
        _error: InvalidModelOutputError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "code": "invalid_model_output",
                "message": "The model response was rejected and was not persisted as a reply.",
            },
        )

    @app.exception_handler(MemoryNotFoundError)
    @app.exception_handler(MemoryOwnershipError)
    async def memory_not_found(
        _request: Request,
        _error: MemoryNotFoundError | MemoryOwnershipError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"code": "memory_not_found", "message": "Memory record not found."},
        )

    @app.exception_handler(MemoryConflictError)
    async def memory_conflict(
        _request: Request,
        _error: MemoryConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "code": "memory_conflict",
                "message": "Memory state changed or conflicts with an immutable record.",
            },
        )

    @app.exception_handler(MemoryUnavailableError)
    async def memory_unavailable(
        _request: Request,
        _error: MemoryUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "memory_write_unavailable",
                "message": "Guardian or runtime state does not permit memory writes.",
            },
        )

    @app.exception_handler(InspectionOwnershipError)
    async def inspection_not_found(
        _request: Request,
        _error: InspectionOwnershipError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "inspection_not_found",
                "message": "Owner activity inspection not found.",
            },
        )

    @app.exception_handler(InspectionWindowError)
    async def invalid_inspection_window(
        _request: Request,
        _error: InspectionWindowError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "code": "invalid_inspection_window",
                "message": "The requested inspection window is invalid.",
            },
        )

    @app.exception_handler(RetentionOwnershipError)
    async def retention_not_found(
        _request: Request,
        _error: RetentionOwnershipError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "retention_report_not_found",
                "message": "Retention report not found.",
            },
        )

    @app.exception_handler(RetentionInspectionUnavailableError)
    async def retention_unavailable(
        _request: Request,
        _error: RetentionInspectionUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "retention_inspection_unavailable",
                "message": "Owner retention inspection is unavailable.",
            },
        )

    @app.exception_handler(ModelRouteOwnershipError)
    async def model_routes_not_found(
        _request: Request,
        _error: ModelRouteOwnershipError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "code": "model_routes_not_found",
                "message": "Model route report not found.",
            },
        )

    @app.exception_handler(ExportBundleError)
    async def export_unavailable(
        _request: Request,
        _error: ExportBundleError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "export_preview_unavailable",
                "message": "The owner export preview could not be generated and validated.",
            },
        )

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready", response_model=SystemStatus)
    async def readiness() -> SystemStatus:
        system_status = read_system_status(guardian_reader)
        if system_status.guardian.mode.value in {"stopped", "recovery"}:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Guardian mode intentionally prevents normal readiness.",
            )
        return system_status

    @app.get("/api/v1/system/status", response_model=SystemStatus)
    async def system_status() -> SystemStatus:
        return read_system_status(guardian_reader)

    @app.post("/api/v1/auth/session", response_model=_OwnerSessionResponse)
    async def login(
        request: Request,
        payload: _OwnerLoginRequest,
        response: Response,
    ) -> _OwnerSessionResponse:
        try:
            issued = _configured_sessions(request).issue(
                payload.credential.get_secret_value()
            )
        except AuthenticationError:
            if event_audit_store is not None and owner_id is not None:
                _append_failed_login_audit(
                    event_audit_store,
                    owner_id=owner_id,
                    occurred_at=security_event_clock(),
                    id_factory=security_event_id_factory,
                )
            raise
        maximum_age = int(
            (issued.principal.expires_at - issued.principal.authenticated_at).total_seconds()
        )
        response.set_cookie(
            key=_SESSION_COOKIE,
            value=issued.session_token,
            max_age=maximum_age,
            path="/",
            secure=secure_session_cookie,
            httponly=True,
            samesite="strict",
        )
        return _OwnerSessionResponse(
            principal=issued.principal,
            csrf_token=issued.csrf_token,
        )

    @app.get("/api/v1/auth/session", response_model=AuthenticatedOwner)
    async def current_session(
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> AuthenticatedOwner:
        return principal

    @app.get(
        "/api/v1/auth/sessions",
        response_model=_OwnerSessionInventoryResponse,
    )
    async def active_owner_sessions(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> _OwnerSessionInventoryResponse:
        return _OwnerSessionInventoryResponse(
            current_session_id=principal.session_id,
            sessions=_configured_sessions(request).active_sessions(),
        )

    @app.delete(
        "/api/v1/auth/sessions/others",
        response_model=_OwnerSessionRevocationResponse,
    )
    async def revoke_other_owner_sessions(
        request: Request,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> _OwnerSessionRevocationResponse:
        return _OwnerSessionRevocationResponse(
            revoked_count=_configured_sessions(request).revoke_other_sessions(
                principal.session_id
            )
        )

    @app.delete("/api/v1/auth/session", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        request: Request,
        _principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner_mutation)],
        response: Response,
    ) -> None:
        _configured_sessions(request).revoke(request.cookies.get(_SESSION_COOKIE, ""))
        response.delete_cookie(
            key=_SESSION_COOKIE,
            path="/",
            secure=secure_session_cookie,
            httponly=True,
            samesite="strict",
        )

    @app.get(
        "/api/v1/integrations/telegram/status",
        response_model=JsonObject,
    )
    async def inspect_telegram_status(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> JsonObject:
        pairing_service = _configured_telegram_pairing(request)
        pairing_service.inspect_active_pairing(principal)
        worker: TelegramPollWorker | None = request.app.state.telegram_worker
        dispatcher: TelegramReplyDispatcher | None = (
            request.app.state.telegram_reply_dispatcher
        )
        adapter: ClientAdapter | None = request.app.state.telegram_delivery_adapter
        state_persistence = str(request.app.state.telegram_state_persistence)
        limitations = [
            "text-only outbound replies",
            "attachments rejected before fetch",
            "ambiguous external sends are not automatically retried",
            "pairing challenge sends are not transactionally deduplicated",
        ]
        if state_persistence != "postgresql":
            limitations.append("pairing, offsets, and ingestion receipts are process-local")
        return {
            "configured": worker is not None,
            "adapter_id": pairing_service.adapter_id,
            "state_persistence": state_persistence,
            "polling": None if worker is None else worker.health(),
            "replies": None if dispatcher is None else dispatcher.health(),
            "delivery": None if adapter is None else adapter.health(),
            "capabilities": None if adapter is None else adapter.capabilities(),
            "limitations": limitations,
        }

    @app.get(
        "/api/v1/integrations/telegram/pairing/candidates",
        response_model=tuple[_TelegramPairingCandidateResponse, ...],
    )
    async def list_telegram_pairing_candidates(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> tuple[_TelegramPairingCandidateResponse, ...]:
        candidates = _configured_telegram_pairing(request).pending_candidates(principal)
        return tuple(
            _TelegramPairingCandidateResponse.from_candidate(candidate)
            for candidate in candidates
        )

    @app.get(
        "/api/v1/integrations/telegram/pairing",
        response_model=TelegramOwnerPairing | None,
    )
    async def inspect_telegram_pairing(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> TelegramOwnerPairing | None:
        return _configured_telegram_pairing(request).inspect_active_pairing(principal)

    @app.post(
        "/api/v1/integrations/telegram/pairing/candidates/{candidate_id}/confirm",
        response_model=TelegramOwnerPairing,
    )
    async def confirm_telegram_pairing(
        request: Request,
        candidate_id: RecordId,
        payload: _ConfirmTelegramPairingRequest,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> TelegramOwnerPairing:
        return _configured_telegram_pairing(request).confirm(
            principal,
            candidate_id,
            payload.confirmation_code.get_secret_value(),
        )

    @app.post(
        "/api/v1/integrations/telegram/pairing/{pairing_id}/revoke",
        response_model=TelegramOwnerPairing,
    )
    async def revoke_telegram_pairing(
        request: Request,
        pairing_id: RecordId,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> TelegramOwnerPairing:
        return _configured_telegram_pairing(request).revoke(principal, pairing_id)

    @app.get("/api/v1/conversations", response_model=tuple[ConversationThread, ...])
    async def list_conversations(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> tuple[ConversationThread, ...]:
        return _configured_conversation(request).list_threads(principal)

    @app.post(
        "/api/v1/conversations",
        response_model=ConversationThread,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_conversation(
        request: Request,
        payload: _CreateThreadRequest,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner_mutation)],
    ) -> ConversationThread:
        return _configured_conversation(request).create_thread(
            principal,
            title=payload.title,
            sensitivity=payload.sensitivity,
            retention_policy=payload.retention_policy,
        )

    @app.get(
        "/api/v1/conversations/{thread_id}/messages",
        response_model=tuple[ConversationMessage, ...],
    )
    async def list_conversation_messages(
        request: Request,
        thread_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> tuple[ConversationMessage, ...]:
        return _configured_conversation(request).list_messages(principal, thread_id)

    @app.get(
        "/api/v1/conversations/{thread_id}/turns",
        response_model=tuple[ConversationTurn, ...],
    )
    async def list_conversation_turns(
        request: Request,
        thread_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> tuple[ConversationTurn, ...]:
        return _configured_conversation(request).list_turns(principal, thread_id)

    @app.get(
        "/api/v1/conversations/{thread_id}/processing",
        response_model=tuple[ConversationProcessingStatus, ...],
    )
    async def list_conversation_processing(
        request: Request,
        thread_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> tuple[ConversationProcessingStatus, ...]:
        return _configured_conversation(request).list_processing(principal, thread_id)

    @app.get(
        "/api/v1/conversations/{thread_id}/messages/{message_id}/processing",
        response_model=ConversationProcessingStatus,
    )
    async def inspect_conversation_processing(
        request: Request,
        thread_id: RecordId,
        message_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> ConversationProcessingStatus:
        return _configured_conversation(request).inspect_processing(
            principal,
            thread_id=thread_id,
            message_id=message_id,
        )

    @app.get(
        "/api/v1/conversations/{thread_id}/turns/{turn_id}",
        response_model=ConversationTurnInspection,
    )
    async def inspect_conversation_turn(
        request: Request,
        thread_id: RecordId,
        turn_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> ConversationTurnInspection:
        return _configured_conversation(request).inspect_turn(
            principal,
            thread_id=thread_id,
            turn_id=turn_id,
        )

    @app.post(
        "/api/v1/conversations/{thread_id}/messages",
        response_model=_ConversationReplyResponse,
    )
    async def post_conversation_message(
        request: Request,
        response: Response,
        thread_id: RecordId,
        payload: _PostOwnerMessageRequest,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner_mutation)],
    ) -> _ConversationReplyResponse:
        try:
            reply: ConversationReply = _configured_conversation(
                request
            ).post_owner_message(
                principal,
                thread_id=thread_id,
                text=payload.text,
                idempotency_key=payload.idempotency_key,
            )
        except HTTPException:
            _append_owner_conversation_audit(
                request,
                principal=principal,
                operation="accept",
                result="denied",
                reason_code="conversation.service_unconfigured",
                thread_id=thread_id,
            )
            raise
        except ConversationUnavailableError:
            _append_owner_conversation_audit(
                request,
                principal=principal,
                operation="accept",
                result="denied",
                reason_code="conversation.write_unavailable",
                thread_id=thread_id,
            )
            raise
        except ConversationConflictError:
            _append_owner_conversation_audit(
                request,
                principal=principal,
                operation="accept",
                result="denied",
                reason_code="conversation.conflict",
                thread_id=thread_id,
            )
            raise
        except (ConversationNotFoundError, ConversationOwnershipError):
            _append_owner_conversation_audit(
                request,
                principal=principal,
                operation="accept",
                result="denied",
                reason_code="conversation.not_found",
                thread_id=thread_id,
            )
            raise
        _append_owner_conversation_audit(
            request,
            principal=principal,
            operation="accept",
            result="accepted",
            reason_code="conversation.owner_message_accept.accepted",
            thread_id=thread_id,
            reply=reply,
        )
        if reply.processing.state is not ConversationProcessingState.COMPLETED:
            response.status_code = status.HTTP_202_ACCEPTED
        return _ConversationReplyResponse(
            inbound_message=reply.inbound_message,
            output_message=reply.output_message,
            turn=reply.turn,
            processing=reply.processing,
            duplicate=reply.duplicate,
        )

    @app.post(
        "/api/v1/conversations/{thread_id}/messages/{message_id}/resume",
        response_model=_ConversationReplyResponse,
    )
    async def resume_conversation_message(
        request: Request,
        response: Response,
        thread_id: RecordId,
        message_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner_mutation)],
    ) -> _ConversationReplyResponse:
        try:
            reply = _configured_conversation(request).resume_owner_message(
                principal,
                thread_id=thread_id,
                message_id=message_id,
            )
        except HTTPException:
            _append_owner_conversation_audit(
                request,
                principal=principal,
                operation="resume",
                result="denied",
                reason_code="conversation.service_unconfigured",
                thread_id=thread_id,
                message_id=message_id,
            )
            raise
        except ConversationUnavailableError:
            _append_owner_conversation_audit(
                request,
                principal=principal,
                operation="resume",
                result="denied",
                reason_code="conversation.write_unavailable",
                thread_id=thread_id,
                message_id=message_id,
            )
            raise
        except ConversationConflictError:
            _append_owner_conversation_audit(
                request,
                principal=principal,
                operation="resume",
                result="denied",
                reason_code="conversation.conflict",
                thread_id=thread_id,
                message_id=message_id,
            )
            raise
        except (ConversationNotFoundError, ConversationOwnershipError):
            _append_owner_conversation_audit(
                request,
                principal=principal,
                operation="resume",
                result="denied",
                reason_code="conversation.not_found",
                thread_id=thread_id,
                message_id=message_id,
            )
            raise
        _append_owner_conversation_audit(
            request,
            principal=principal,
            operation="resume",
            result="accepted",
            reason_code="conversation.owner_message_resume.accepted",
            thread_id=thread_id,
            reply=reply,
        )
        if reply.processing.state is not ConversationProcessingState.COMPLETED:
            response.status_code = status.HTTP_202_ACCEPTED
        return _ConversationReplyResponse(
            inbound_message=reply.inbound_message,
            output_message=reply.output_message,
            turn=reply.turn,
            processing=reply.processing,
            duplicate=reply.duplicate,
        )

    @app.get(
        "/api/v1/conversations/{thread_id}/deliveries",
        response_model=tuple[DeliveryWorkStatus, ...],
    )
    async def list_conversation_deliveries(
        request: Request,
        thread_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> tuple[DeliveryWorkStatus, ...]:
        return _configured_delivery(request).list_deliveries(principal, thread_id)

    @app.post(
        "/api/v1/conversations/{thread_id}/deliveries",
        response_model=_DeliverySubmissionResponse,
    )
    async def enqueue_conversation_delivery(
        request: Request,
        response: Response,
        thread_id: RecordId,
        payload: _EnqueueDeliveryRequest,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> _DeliverySubmissionResponse:
        try:
            submission: DeliverySubmission = _configured_delivery(
                request
            ).enqueue_owner_delivery(
                principal,
                thread_id=thread_id,
                message_id=payload.message_id,
                client_adapter=payload.client_adapter,
                destination_ref=payload.destination_ref,
                idempotency_key=payload.idempotency_key,
            )
        except HTTPException:
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="enqueue",
                result="denied",
                reason_code="delivery.service_unconfigured",
                thread_id=thread_id,
                message_id=payload.message_id,
                client_adapter=payload.client_adapter,
            )
            raise
        except DeliveryUnavailableError as error:
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="enqueue",
                result="denied",
                reason_code=error.reason_code,
                thread_id=thread_id,
                message_id=payload.message_id,
                client_adapter=payload.client_adapter,
            )
            raise
        except DeliveryConflictError:
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="enqueue",
                result="denied",
                reason_code="delivery.conflict",
                thread_id=thread_id,
                message_id=payload.message_id,
                client_adapter=payload.client_adapter,
            )
            raise
        except (ConversationNotFoundError, ConversationOwnershipError):
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="enqueue",
                result="denied",
                reason_code="delivery.conversation_not_found",
                thread_id=thread_id,
                message_id=payload.message_id,
                client_adapter=payload.client_adapter,
            )
            raise
        except DeliveryOwnershipError:
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="enqueue",
                result="denied",
                reason_code="delivery.not_found",
                thread_id=thread_id,
                message_id=payload.message_id,
                client_adapter=payload.client_adapter,
            )
            raise
        _append_owner_delivery_audit(
            request,
            principal=principal,
            operation="enqueue",
            result="accepted",
            reason_code="delivery.owner_enqueue.accepted",
            thread_id=thread_id,
            message_id=submission.status.message_id,
            work_id=submission.status.work_id,
            client_adapter=submission.status.client_adapter,
            delivery=submission.status,
            created=submission.created,
        )
        if submission.status.state is not DeliveryWorkState.COMPLETED:
            response.status_code = status.HTTP_202_ACCEPTED
        return _DeliverySubmissionResponse(
            delivery=submission.status,
            created=submission.created,
        )

    @app.get(
        "/api/v1/conversations/{thread_id}/deliveries/{work_id}",
        response_model=DeliveryWorkStatus,
    )
    async def inspect_conversation_delivery(
        request: Request,
        thread_id: RecordId,
        work_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> DeliveryWorkStatus:
        return _configured_delivery(request).inspect_delivery(
            principal,
            thread_id=thread_id,
            work_id=work_id,
        )

    @app.post(
        "/api/v1/conversations/{thread_id}/deliveries/{work_id}/resume",
        response_model=DeliveryWorkStatus,
    )
    async def resume_conversation_delivery(
        request: Request,
        response: Response,
        thread_id: RecordId,
        work_id: RecordId,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> DeliveryWorkStatus:
        try:
            delivery = _configured_delivery(request).resume_delivery(
                principal,
                thread_id=thread_id,
                work_id=work_id,
            )
        except HTTPException:
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="resume",
                result="denied",
                reason_code="delivery.service_unconfigured",
                thread_id=thread_id,
                work_id=work_id,
            )
            raise
        except DeliveryUnavailableError as error:
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="resume",
                result="denied",
                reason_code=error.reason_code,
                thread_id=thread_id,
                work_id=work_id,
            )
            raise
        except DeliveryConflictError:
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="resume",
                result="denied",
                reason_code="delivery.conflict",
                thread_id=thread_id,
                work_id=work_id,
            )
            raise
        except (DeliveryNotFoundError, DeliveryOwnershipError):
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="resume",
                result="denied",
                reason_code="delivery.not_found",
                thread_id=thread_id,
                work_id=work_id,
            )
            raise
        except (ConversationNotFoundError, ConversationOwnershipError):
            _append_owner_delivery_audit(
                request,
                principal=principal,
                operation="resume",
                result="denied",
                reason_code="delivery.conversation_not_found",
                thread_id=thread_id,
                work_id=work_id,
            )
            raise
        _append_owner_delivery_audit(
            request,
            principal=principal,
            operation="resume",
            result="accepted",
            reason_code="delivery.owner_resume.accepted",
            thread_id=thread_id,
            message_id=delivery.message_id,
            work_id=delivery.work_id,
            client_adapter=delivery.client_adapter,
            delivery=delivery,
        )
        if delivery.state is not DeliveryWorkState.COMPLETED:
            response.status_code = status.HTTP_202_ACCEPTED
        return delivery

    @app.get("/api/v1/memory/{assertion_id}", response_model=MemoryInspection)
    async def inspect_memory(
        request: Request,
        assertion_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> MemoryInspection:
        return _configured_memory(request).inspect(principal, assertion_id)

    @app.delete(
        "/api/v1/memory/{assertion_id}/content",
        response_model=AssertionContentDeletionResult,
    )
    async def delete_memory_content(
        request: Request,
        assertion_id: RecordId,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> AssertionContentDeletionResult:
        return _configured_memory(request).delete_content(principal, assertion_id)

    @app.post(
        "/api/v1/memory/{assertion_id}/corrections",
        response_model=AssertionCorrectionResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def correct_memory(
        request: Request,
        assertion_id: RecordId,
        payload: _CorrectMemoryRequest,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> AssertionCorrectionResult:
        return _configured_memory(request).correct(
            principal,
            assertion_id,
            value=payload.value,
            expected_version=payload.expected_version,
        )

    @app.post(
        "/api/v1/memory/{assertion_id}/disputes",
        response_model=AssertionStateTransitionResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def dispute_memory(
        request: Request,
        assertion_id: RecordId,
        payload: _ChangeMemoryStateRequest,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> AssertionStateTransitionResult:
        return _configured_memory(request).dispute(
            principal,
            assertion_id,
            expected_version=payload.expected_version,
        )

    @app.post(
        "/api/v1/memory/{assertion_id}/retractions",
        response_model=AssertionStateTransitionResult,
        status_code=status.HTTP_201_CREATED,
    )
    async def retract_memory(
        request: Request,
        assertion_id: RecordId,
        payload: _ChangeMemoryStateRequest,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> AssertionStateTransitionResult:
        return _configured_memory(request).retract(
            principal,
            assertion_id,
            expected_version=payload.expected_version,
        )

    @app.get(
        "/api/v1/inspection/model-activity",
        response_model=OwnerModelActivityReport,
    )
    async def inspect_model_activity(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
        window_start: Annotated[datetime | None, Query(alias="from")] = None,
        window_end: Annotated[datetime | None, Query(alias="to")] = None,
    ) -> OwnerModelActivityReport:
        return _configured_inspection(request).model_activity(
            principal,
            window_start=window_start,
            window_end=window_end,
        )

    @app.get(
        "/api/v1/inspection/timeline",
        response_model=OwnerTimelineReport,
    )
    async def inspect_owner_timeline(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
        window_start: Annotated[datetime | None, Query(alias="from")] = None,
        window_end: Annotated[datetime | None, Query(alias="to")] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> OwnerTimelineReport:
        return _configured_inspection(request).timeline(
            principal,
            window_start=window_start,
            window_end=window_end,
            limit=limit,
        )

    @app.get(
        "/api/v1/providers/routes",
        response_model=OwnerModelRouteReport,
    )
    def inspect_model_routes(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> OwnerModelRouteReport:
        return _configured_model_routes(request).report(principal)

    @app.get(
        "/api/v1/inspection/health",
        response_model=OwnerHealthReport,
    )
    async def inspect_health(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> OwnerHealthReport:
        return _configured_operations(request).health(principal)

    @app.get(
        "/api/v1/inspection/media",
        response_model=OwnerMediaCatalog,
    )
    async def inspect_media(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> OwnerMediaCatalog:
        return _configured_operations(request).media(principal)

    @app.get(
        "/api/v1/inspection/export",
        response_model=OwnerExportReadinessReport,
    )
    async def inspect_export_readiness(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> OwnerExportReadinessReport:
        return _configured_operations(request).export_readiness(principal)

    @app.post("/api/v1/exports/preview", response_class=FileResponse)
    async def download_export_preview(
        request: Request,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> Response:
        export_service, schema_root = _configured_export(request)
        workspace = _create_export_workspace()
        archive_path = workspace / "owner-export.zip"
        try:
            manifest = export_service.write_validated_zip(
                archive_path,
                schema_root=schema_root,
                principal=principal,
            )
            event_audit_store: EventAuditStore | None = (
                request.app.state.event_audit_store
            )
            owner_id: RecordId | None = request.app.state.owner_id
            if event_audit_store is not None and owner_id is not None:
                _append_owner_export_preview_audit(
                    event_audit_store,
                    owner_id=owner_id,
                    principal=principal,
                    manifest=manifest,
                    occurred_at=request.app.state.security_event_clock(),
                    id_factory=request.app.state.security_event_id_factory,
                )
            return FileResponse(
                path=archive_path,
                media_type="application/zip",
                filename=f"melloa-owner-export-{manifest.export_id}.zip",
                background=BackgroundTask(
                    shutil.rmtree,
                    workspace,
                    ignore_errors=True,
                ),
            )
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

    @app.get(
        "/api/v1/retention",
        response_model=OwnerRetentionReport,
    )
    async def inspect_retention(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> OwnerRetentionReport:
        return _configured_retention(request).report(principal)

    return app
