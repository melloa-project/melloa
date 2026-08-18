"""Synthetic opaque-token owner sessions for tests and private development drills."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, TypeGuard

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
from melloa.domain.events import EventEnvelope, EventIntegrity, EventProducer, EventSource
from melloa.ports.auth import (
    AuthenticationError,
    CsrfValidationError,
    IssuedOwnerSession,
    OwnerSessionCleanupResult,
    OwnerSessionExpired,
    OwnerSessionMissing,
    RecentAuthenticationRequired,
)
from melloa.ports.store import EventAuditStore
from melloa.release import CURRENT_RELEASE

_MAXIMUM_SECRET_LENGTH = 4096
_MAXIMUM_CLEANUP_LIMIT = 10_000


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _secure_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class _SessionRecord:
    principal: AuthenticatedOwner
    csrf_digest: bytes


class InMemoryOwnerSessionManager:
    """Fail-closed reference adapter; deployment auth remains owner-selected."""

    def __init__(
        self,
        owner_id: RecordId,
        bootstrap_token: str,
        *,
        event_audit_store: EventAuditStore | None = None,
        clock: Callable[[], datetime] = utc_now,
        token_factory: Callable[[], str] = _secure_token,
        session_ttl: timedelta = timedelta(minutes=30),
        recent_auth_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if not 32 <= len(bootstrap_token) <= _MAXIMUM_SECRET_LENGTH:
            raise ValueError("bootstrap token must contain between 32 and 4096 characters")
        if session_ttl <= timedelta(0):
            raise ValueError("session TTL must be positive")
        if not timedelta(0) < recent_auth_ttl <= session_ttl:
            raise ValueError("recent-authentication TTL must be positive and within session TTL")
        self._owner_id = owner_id
        self._bootstrap_digest = _digest(bootstrap_token)
        self._event_audit_store = event_audit_store
        self._clock = clock
        self._token_factory = token_factory
        self._session_ttl = session_ttl
        self._recent_auth_ttl = recent_auth_ttl
        self._sessions: dict[bytes, _SessionRecord] = {}

    def issue(self, credential: str) -> IssuedOwnerSession:
        if not self._valid_secret(credential) or not hmac.compare_digest(
            _digest(credential), self._bootstrap_digest
        ):
            raise AuthenticationError("owner authentication failed")
        authenticated_at = self._clock()
        session_token = self._new_unique_session_token()
        csrf_token = self._new_token()
        principal = AuthenticatedOwner(
            owner_id=self._owner_id,
            session_id=new_record_id("session"),
            authentication_method="auth.synthetic-opaque-token",
            authenticated_at=authenticated_at,
            reauthenticated_until=authenticated_at + self._recent_auth_ttl,
            expires_at=authenticated_at + self._session_ttl,
        )
        self._append_session_audit(
            session_id=principal.session_id,
            authentication_method=principal.authentication_method,
            occurred_at=principal.authenticated_at,
            lifecycle="issued",
        )
        self._sessions[_digest(session_token)] = _SessionRecord(
            principal=principal,
            csrf_digest=_digest(csrf_token),
        )
        return IssuedOwnerSession(
            principal=principal,
            session_token=session_token,
            csrf_token=csrf_token,
        )

    def verify(
        self,
        session_token: str,
        *,
        csrf_token: str | None = None,
        require_csrf: bool = False,
        require_recent: bool = False,
    ) -> AuthenticatedOwner:
        if not self._valid_secret(session_token):
            raise OwnerSessionMissing("owner authentication failed")
        session_digest = _digest(session_token)
        record = self._sessions.get(session_digest)
        if record is None:
            raise OwnerSessionMissing("owner authentication failed")
        now = self._clock()
        if now >= record.principal.expires_at:
            self._sessions.pop(session_digest, None)
            raise OwnerSessionExpired("owner authentication failed")
        if require_csrf:
            if not self._valid_secret(csrf_token) or not hmac.compare_digest(
                _digest(csrf_token), record.csrf_digest
            ):
                raise CsrfValidationError("browser action failed CSRF validation")
        if require_recent and now >= record.principal.reauthenticated_until:
            raise RecentAuthenticationRequired("recent owner authentication required")
        return record.principal

    def revoke(self, session_token: str) -> None:
        if self._valid_secret(session_token):
            session_digest = _digest(session_token)
            record = self._sessions.get(session_digest)
            if record is None:
                return
            self._append_session_audit(
                session_id=record.principal.session_id,
                authentication_method=record.principal.authentication_method,
                occurred_at=max(record.principal.authenticated_at, self._clock()),
                lifecycle="revoked",
            )
            self._sessions.pop(session_digest, None)

    def active_sessions(self) -> tuple[AuthenticatedOwner, ...]:
        self.cleanup_expired_sessions()
        now = self._clock()
        return tuple(
            sorted(
                (
                    record.principal
                    for record in self._sessions.values()
                    if now < record.principal.expires_at
                ),
                key=lambda principal: (principal.authenticated_at, principal.session_id),
                reverse=True,
            )
        )

    def revoke_other_sessions(self, current_session_id: RecordId) -> int:
        active_session_ids = {
            principal.session_id for principal in self.active_sessions()
        }
        if current_session_id not in active_session_ids:
            raise OwnerSessionMissing("owner authentication failed")
        revoked_digests = tuple(
            session_digest
            for session_digest, record in self._sessions.items()
            if record.principal.session_id != current_session_id
        )
        for session_digest in revoked_digests:
            principal = self._sessions[session_digest].principal
            self._append_session_audit(
                session_id=principal.session_id,
                authentication_method=principal.authentication_method,
                occurred_at=max(principal.authenticated_at, self._clock()),
                lifecycle="revoked",
            )
        for session_digest in revoked_digests:
            self._sessions.pop(session_digest, None)
        return len(revoked_digests)

    def cleanup_expired_sessions(self, *, limit: int = 1000) -> OwnerSessionCleanupResult:
        if not 0 <= limit <= _MAXIMUM_CLEANUP_LIMIT:
            raise ValueError("session cleanup limit must be between 0 and 10000")
        if limit == 0:
            return OwnerSessionCleanupResult(expired_sessions=0)
        now = self._clock()
        expired_digests = tuple(
            session_digest
            for session_digest, record in self._sessions.items()
            if now >= record.principal.expires_at
        )[:limit]
        for session_digest in expired_digests:
            self._sessions.pop(session_digest, None)
        return OwnerSessionCleanupResult(expired_sessions=len(expired_digests))

    def _append_session_audit(
        self,
        *,
        session_id: RecordId,
        authentication_method: QualifiedName,
        occurred_at: datetime,
        lifecycle: Literal["issued", "revoked"],
    ) -> None:
        event_audit_store = self._event_audit_store
        if event_audit_store is None:
            return
        if lifecycle == "issued":
            event_type: QualifiedName = "auth.owner-session-issued.v1"
            action: QualifiedName = "auth.owner-session.issue"
        else:
            event_type = "auth.owner-session-revoked.v1"
            action = "auth.owner-session.revoke"
        payload: JsonObject = {
            "authentication_method": authentication_method,
            "session_id": session_id,
            "state": lifecycle,
        }
        event = EventEnvelope(
            event_id=self._derived_audit_id("event", session_id, event_type),
            event_type=event_type,
            schema_version="1.0.0",
            occurred_at=occurred_at,
            recorded_at=occurred_at,
            subject_ids=(self._owner_id,),
            source=EventSource(
                capability_id="auth.owner-session",
                execution_id=session_id,
            ),
            producer=EventProducer(
                component="auth.owner-session-manager",
                version=CURRENT_RELEASE.package_version,
            ),
            epistemic_status=EpistemicStatus.OBSERVATION,
            sensitivity=Sensitivity.PERSONAL,
            trust=TrustLabel.TRUSTED_SYSTEM,
            retention_policy="retention.audit-ledger",
            correlation_id=session_id,
            payload=payload,
            integrity=EventIntegrity(
                payload_hash=sha256_digest(canonical_json_bytes(payload))
            ),
        )
        audit = AuditContent(
            audit_id=self._derived_audit_id("audit", session_id, action),
            event_type="audit.event-appended.v1",
            occurred_at=occurred_at,
            actor_id=self._owner_id,
            action=action,
            object_ids=(session_id,),
            metadata={
                "event_id": event.event_id,
                "result": lifecycle,
            },
        )
        event_audit_store.append_event(event, audit)

    @staticmethod
    def _derived_audit_id(
        prefix: str,
        session_id: RecordId,
        purpose: QualifiedName,
    ) -> str:
        digest = sha256_digest(
            canonical_json_bytes(
                {
                    "prefix": prefix,
                    "purpose": purpose,
                    "session_id": session_id,
                }
            )
        ).removeprefix("sha256:")
        return f"{prefix}_{digest[:32]}"

    def _new_unique_session_token(self) -> str:
        for _attempt in range(8):
            token = self._new_token()
            if _digest(token) not in self._sessions:
                return token
        raise RuntimeError("could not generate a unique session token")

    def _new_token(self) -> str:
        token = self._token_factory()
        if not self._valid_secret(token):
            raise RuntimeError("token factory returned an invalid opaque token")
        return token

    @staticmethod
    def _valid_secret(value: str | None) -> TypeGuard[str]:
        return value is not None and 1 <= len(value) <= _MAXIMUM_SECRET_LENGTH
