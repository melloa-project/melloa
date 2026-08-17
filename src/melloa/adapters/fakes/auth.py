"""Synthetic opaque-token owner sessions for tests and private development drills."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeGuard

from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId, new_record_id, utc_now
from melloa.ports.auth import (
    AuthenticationError,
    CsrfValidationError,
    IssuedOwnerSession,
    OwnerSessionExpired,
    OwnerSessionMissing,
    RecentAuthenticationRequired,
)

_MAXIMUM_SECRET_LENGTH = 4096


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
            self._sessions.pop(_digest(session_token), None)

    def active_sessions(self) -> tuple[AuthenticatedOwner, ...]:
        now = self._clock()
        for session_digest, record in tuple(self._sessions.items()):
            if now >= record.principal.expires_at:
                self._sessions.pop(session_digest, None)
        return tuple(
            sorted(
                (record.principal for record in self._sessions.values()),
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
            self._sessions.pop(session_digest, None)
        return len(revoked_digests)

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
