"""Private owner API for conversation, data control, and Guardian status."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
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
from melloa.application.exports import (
    ExportBundleError,
    OwnerExportReadinessReport,
    OwnerExportService,
)
from melloa.application.routing import OwnerModelRouteService
from melloa.application.status import SystemStatus, read_system_status
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import QualifiedName, RecordId
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingState,
    ConversationProcessingStatus,
    ConversationThread,
    ConversationTurn,
    ConversationTurnInspection,
)
from melloa.domain.models import OwnerModelRouteReport
from melloa.ports.auth import (
    AuthenticationError,
    CsrfValidationError,
    OwnerSessionManager,
    RecentAuthenticationRequired,
)
from melloa.ports.conversation import ConversationConflictError, ConversationNotFoundError
from melloa.ports.guardian import GuardianStatusReader
from melloa.release import CURRENT_RELEASE

_SESSION_COOKIE = "__Host-melloa_session"
_CSRF_HEADER = "X-Melloa-CSRF"
_LOGGER = logging.getLogger(__name__)
AccessScope = Literal["loopback", "private-network", "unverified"]


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


class ConversationTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: tuple[ConversationMessage, ...]
    turns: tuple[ConversationTurn, ...]
    processing: tuple[ConversationProcessingStatus, ...]


class _ConversationReplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inbound_message: ConversationMessage
    output_message: ConversationMessage | None
    turn: ConversationTurn | None
    processing: ConversationProcessingStatus
    duplicate: bool


def _owner_sessions(request: Request) -> OwnerSessionManager:
    value = getattr(request.app.state, "owner_sessions", None)
    if value is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Owner access is unavailable.")
    return cast(OwnerSessionManager, value)


def _conversation(request: Request) -> ConversationService:
    value = getattr(request.app.state, "conversation_service", None)
    if value is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Conversation is unavailable.")
    return cast(ConversationService, value)


def _model_routes(request: Request) -> OwnerModelRouteService:
    value = getattr(request.app.state, "model_route_service", None)
    if value is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Model status is unavailable.")
    return cast(OwnerModelRouteService, value)


def _exports(request: Request) -> OwnerExportService:
    value = getattr(request.app.state, "export_service", None)
    if value is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Data export is unavailable.")
    return cast(OwnerExportService, value)


def _authenticated_owner(request: Request) -> AuthenticatedOwner:
    return _owner_sessions(request).verify(request.cookies.get(_SESSION_COOKIE, ""))


def _authenticated_owner_mutation(
    request: Request,
    csrf_token: Annotated[str | None, Header(alias=_CSRF_HEADER)] = None,
) -> AuthenticatedOwner:
    return _owner_sessions(request).verify(
        request.cookies.get(_SESSION_COOKIE, ""),
        csrf_token=csrf_token,
        require_csrf=True,
    )


def _authenticated_owner_sensitive_mutation(
    request: Request,
    csrf_token: Annotated[str | None, Header(alias=_CSRF_HEADER)] = None,
) -> AuthenticatedOwner:
    return _owner_sessions(request).verify(
        request.cookies.get(_SESSION_COOKIE, ""),
        csrf_token=csrf_token,
        require_csrf=True,
        require_recent=True,
    )


async def _run_conversation_worker(service: ConversationService, interval: float) -> None:
    while True:
        try:
            service.process_ready()
        except Exception:
            _LOGGER.warning("Conversation retry worker could not process due work.")
        await asyncio.sleep(interval)


def create_app(
    guardian_reader: GuardianStatusReader,
    owner_sessions: OwnerSessionManager | None = None,
    conversation_service: ConversationService | None = None,
    model_route_service: OwnerModelRouteService | None = None,
    export_service: OwnerExportService | None = None,
    *,
    secure_session_cookie: bool = True,
    run_conversation_worker: bool = False,
    conversation_worker_interval: float = 1.0,
    access_scope: AccessScope = "unverified",
) -> FastAPI:
    if conversation_worker_interval <= 0:
        raise ValueError("conversation worker interval must be positive")
    if run_conversation_worker and conversation_service is None:
        raise ValueError("conversation worker requires a configured conversation service")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        worker = (
            None
            if not run_conversation_worker or conversation_service is None
            else asyncio.create_task(
                _run_conversation_worker(conversation_service, conversation_worker_interval)
            )
        )
        try:
            yield
        finally:
            if worker is not None:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

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
    app.state.model_route_service = model_route_service
    app.state.export_service = export_service

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
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "code": "guardian_status_unverified",
                "message": (
                    "Independent protection could not be verified; authority remains disabled."
                ),
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
            message = "Fresh owner confirmation is required."
        else:
            response_status = status.HTTP_401_UNAUTHORIZED
            code = "owner_authentication_failed"
            message = "Owner authentication failed."
        return JSONResponse(
            status_code=response_status,
            content={"code": code, "message": message},
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
            content={"code": "conversation_conflict", "message": "Conversation state changed."},
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
                "message": "Independent protection currently prevents conversation writes.",
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
                "message": "Melli returned an invalid answer.",
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
                "code": "export_unavailable",
                "message": "Your data archive could not be built.",
            },
        )

    @app.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready", response_model=SystemStatus)
    async def readiness() -> SystemStatus:
        current = read_system_status(guardian_reader, access_scope=access_scope)
        if current.guardian.mode.value in {"stopped", "recovery"}:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Guardian intentionally prevents normal readiness.",
            )
        return current

    @app.get("/api/v1/system/status", response_model=SystemStatus)
    async def system_status() -> SystemStatus:
        return read_system_status(guardian_reader, access_scope=access_scope)

    @app.post("/api/v1/auth/session", response_model=_OwnerSessionResponse)
    async def login(
        request: Request,
        payload: _OwnerLoginRequest,
        response: Response,
    ) -> _OwnerSessionResponse:
        issued = _owner_sessions(request).issue(payload.credential.get_secret_value())
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
        return _OwnerSessionResponse(principal=issued.principal, csrf_token=issued.csrf_token)

    @app.get("/api/v1/auth/session", response_model=AuthenticatedOwner)
    async def current_session(
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> AuthenticatedOwner:
        return principal

    @app.get("/api/v1/auth/sessions", response_model=_OwnerSessionInventoryResponse)
    async def active_owner_sessions(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> _OwnerSessionInventoryResponse:
        return _OwnerSessionInventoryResponse(
            current_session_id=principal.session_id,
            sessions=_owner_sessions(request).active_sessions(),
        )

    @app.delete("/api/v1/auth/sessions/others", response_model=_OwnerSessionRevocationResponse)
    async def revoke_other_owner_sessions(
        request: Request,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> _OwnerSessionRevocationResponse:
        return _OwnerSessionRevocationResponse(
            revoked_count=_owner_sessions(request).revoke_other_sessions(principal.session_id)
        )

    @app.delete("/api/v1/auth/session", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        request: Request,
        _principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner_mutation)],
        response: Response,
    ) -> None:
        _owner_sessions(request).revoke(request.cookies.get(_SESSION_COOKIE, ""))
        response.delete_cookie(
            key=_SESSION_COOKIE,
            path="/",
            secure=secure_session_cookie,
            httponly=True,
            samesite="strict",
        )

    @app.get("/api/v1/model/status", response_model=OwnerModelRouteReport)
    async def model_status(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> OwnerModelRouteReport:
        return _model_routes(request).report(principal)

    @app.get("/api/v1/conversations", response_model=tuple[ConversationThread, ...])
    async def list_conversations(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> tuple[ConversationThread, ...]:
        return _conversation(request).list_threads(principal)

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
        return _conversation(request).create_thread(
            principal,
            title=payload.title,
            sensitivity=payload.sensitivity,
            retention_policy=payload.retention_policy,
        )

    @app.get(
        "/api/v1/conversations/{thread_id}/transcript",
        response_model=ConversationTranscript,
    )
    async def conversation_transcript(
        request: Request,
        thread_id: RecordId,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> ConversationTranscript:
        service = _conversation(request)
        return ConversationTranscript(
            messages=service.list_messages(principal, thread_id),
            turns=service.list_turns(principal, thread_id),
            processing=service.list_processing(principal, thread_id),
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
        return _conversation(request).inspect_turn(
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
        reply = _conversation(request).post_owner_message(
            principal,
            thread_id=thread_id,
            text=payload.text,
            idempotency_key=payload.idempotency_key,
        )
        if reply.processing.state is not ConversationProcessingState.COMPLETED:
            response.status_code = status.HTTP_202_ACCEPTED
        return _reply_response(reply)

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
        reply = _conversation(request).resume_owner_message(
            principal,
            thread_id=thread_id,
            message_id=message_id,
        )
        if reply.processing.state is not ConversationProcessingState.COMPLETED:
            response.status_code = status.HTTP_202_ACCEPTED
        return _reply_response(reply)

    @app.get("/api/v1/data-export", response_model=OwnerExportReadinessReport)
    async def export_readiness(
        request: Request,
        principal: Annotated[AuthenticatedOwner, Depends(_authenticated_owner)],
    ) -> OwnerExportReadinessReport:
        return _exports(request).readiness(principal)

    @app.post("/api/v1/data-export/archive")
    async def download_export(
        request: Request,
        principal: Annotated[
            AuthenticatedOwner,
            Depends(_authenticated_owner_sensitive_mutation),
        ],
    ) -> Response:
        archive = _exports(request).build_archive(principal)
        return Response(
            content=archive.content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{archive.filename}"'},
        )

    return app


def _reply_response(reply: ConversationReply) -> _ConversationReplyResponse:
    return _ConversationReplyResponse(
        inbound_message=reply.inbound_message,
        output_message=reply.output_message,
        turn=reply.turn,
        processing=reply.processing,
        duplicate=reply.duplicate,
    )


__all__ = ["AccessScope", "ConversationTranscript", "create_app"]
