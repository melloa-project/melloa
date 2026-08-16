"""Private Melloa API with verified Guardian and owner-authentication boundaries."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

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
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import JsonObject, QualifiedName, RecordId
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingState,
    ConversationProcessingStatus,
    ConversationThread,
    ConversationTurn,
    ConversationTurnInspection,
)
from melloa.domain.delivery import DeliveryWorkState, DeliveryWorkStatus
from melloa.domain.inspection import OwnerModelActivityReport
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
    OwnerSessionManager,
    RecentAuthenticationRequired,
)
from melloa.ports.client import ClientAdapter
from melloa.ports.conversation import ConversationConflictError, ConversationNotFoundError
from melloa.ports.delivery import DeliveryConflictError, DeliveryNotFoundError
from melloa.ports.guardian import GuardianStatusReader
from melloa.ports.memory import MemoryConflictError, MemoryNotFoundError
from melloa.ports.telegram import (
    TelegramPairingConflictError,
    TelegramPairingNotFoundError,
    TelegramPollingError,
)

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


async def _run_conversation_worker(
    service: ConversationService,
    *,
    interval: float,
) -> None:
    while True:
        try:
            await asyncio.to_thread(service.process_ready)
        except ConversationUnavailableError:
            pass
        except Exception:
            _LOGGER.exception("conversation reply worker cycle failed")
        await asyncio.sleep(interval)


async def _run_delivery_worker(
    service: DeliveryService,
    *,
    interval: float,
) -> None:
    while True:
        try:
            await asyncio.to_thread(service.process_ready)
        except Exception:
            _LOGGER.exception("outbound delivery worker cycle failed")
        await asyncio.sleep(interval)


async def _run_telegram_worker(
    worker: TelegramPollWorker,
    *,
    interval: float,
    reply_dispatcher: TelegramReplyDispatcher | None = None,
) -> None:
    while True:
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
        await asyncio.sleep(interval)


async def _run_telegram_retention_worker(
    worker: TelegramAttachmentRetentionWorker,
    *,
    interval: float,
) -> None:
    while True:
        try:
            await asyncio.to_thread(worker.sweep_once)
        except TelegramRetentionUnavailableError:
            pass
        except Exception:
            _LOGGER.exception("Telegram attachment retention worker cycle failed")
        await asyncio.sleep(interval)


def _configured_sessions(request: Request) -> OwnerSessionManager:
    owner_sessions: OwnerSessionManager | None = request.app.state.owner_sessions
    if owner_sessions is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Owner authentication is not configured.",
        )
    return owner_sessions


def _configured_conversation(request: Request) -> ConversationService:
    conversation_service: ConversationService | None = request.app.state.conversation_service
    if conversation_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Canonical conversation is not configured.",
        )
    return conversation_service


def _configured_memory(request: Request) -> MemoryService:
    memory_service: MemoryService | None = request.app.state.memory_service
    if memory_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory inspection and correction are not configured.",
        )
    return memory_service


def _configured_delivery(request: Request) -> DeliveryService:
    delivery_service: DeliveryService | None = request.app.state.delivery_service
    if delivery_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Outbound delivery is not configured.",
        )
    return delivery_service


def _configured_inspection(request: Request) -> OwnerInspectionService:
    inspection_service: OwnerInspectionService | None = request.app.state.inspection_service
    if inspection_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Owner activity inspection is not configured.",
        )
    return inspection_service


def _configured_operations(request: Request) -> OwnerOperationsService:
    operations_service: OwnerOperationsService | None = request.app.state.operations_service
    if operations_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Owner health and media inspection are not configured.",
        )
    return operations_service


def _configured_retention(request: Request) -> OwnerRetentionService:
    retention_service: OwnerRetentionService | None = request.app.state.retention_service
    if retention_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Owner retention inspection is not configured.",
        )
    return retention_service


def _configured_model_routes(request: Request) -> OwnerModelRouteService:
    model_route_service: OwnerModelRouteService | None = request.app.state.model_route_service
    if model_route_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model route inspection is not configured.",
        )
    return model_route_service


def _configured_telegram_pairing(request: Request) -> TelegramPairingService:
    pairing_service: TelegramPairingService | None = request.app.state.telegram_pairing_service
    if pairing_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram pairing is not configured.",
        )
    return pairing_service


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
    if run_conversation_worker and conversation_service is None:
        raise ValueError("conversation worker requires a configured conversation service")
    if run_delivery_worker and delivery_service is None:
        raise ValueError("delivery worker requires a configured delivery service")
    if run_telegram_worker and telegram_worker is None:
        raise ValueError("Telegram worker requires a configured poll worker")
    if run_telegram_retention_worker and telegram_retention_worker is None:
        raise ValueError("Telegram retention worker requires a configured retention worker")

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
        version="0.1.0",
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
    app.state.retention_service = retention_service
    app.state.model_route_service = model_route_service
    app.state.delivery_service = delivery_service
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
        _request: Request,
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
        issued = _configured_sessions(request).issue(payload.credential.get_secret_value())
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
        reply: ConversationReply = _configured_conversation(request).post_owner_message(
            principal,
            thread_id=thread_id,
            text=payload.text,
            idempotency_key=payload.idempotency_key,
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
        reply = _configured_conversation(request).resume_owner_message(
            principal,
            thread_id=thread_id,
            message_id=message_id,
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
        submission: DeliverySubmission = _configured_delivery(request).enqueue_owner_delivery(
            principal,
            thread_id=thread_id,
            message_id=payload.message_id,
            client_adapter=payload.client_adapter,
            destination_ref=payload.destination_ref,
            idempotency_key=payload.idempotency_key,
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
        delivery = _configured_delivery(request).resume_delivery(
            principal,
            thread_id=thread_id,
            work_id=work_id,
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
