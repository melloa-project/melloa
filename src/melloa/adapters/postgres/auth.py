"""Hashed PostgreSQL owner sessions with append-only revocation evidence."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, TypeGuard

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId, canonical_json_bytes, new_record_id, utc_now
from melloa.ports.auth import (
    AuthenticationError,
    CsrfValidationError,
    IssuedOwnerSession,
    RecentAuthenticationRequired,
)

_MAXIMUM_SECRET_LENGTH = 4096
_AUTHENTICATION_METHOD = "auth.local-opaque-token"


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _secure_token() -> str:
    return secrets.token_urlsafe(32)


class PostgresOwnerSessionManager:
    def __init__(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        owner_id: RecordId,
        bootstrap_token: str,
        *,
        clock: Callable[[], datetime] = utc_now,
        token_factory: Callable[[], str] = _secure_token,
        id_factory: Callable[[str], str] = new_record_id,
        session_ttl: timedelta = timedelta(minutes=30),
        recent_auth_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if not 32 <= len(bootstrap_token) <= _MAXIMUM_SECRET_LENGTH:
            raise ValueError("bootstrap token must contain between 32 and 4096 characters")
        if session_ttl <= timedelta(0):
            raise ValueError("session TTL must be positive")
        if not timedelta(0) < recent_auth_ttl <= session_ttl:
            raise ValueError("recent-authentication TTL must be positive and within session TTL")
        self._connection = connection
        self._owner_id = owner_id
        self._bootstrap_digest = _digest(bootstrap_token)
        self._clock = clock
        self._token_factory = token_factory
        self._id_factory = id_factory
        self._session_ttl = session_ttl
        self._recent_auth_ttl = recent_auth_ttl

    def issue(self, credential: str) -> IssuedOwnerSession:
        if not self._valid_secret(credential) or not hmac.compare_digest(
            _digest(credential), self._bootstrap_digest
        ):
            raise AuthenticationError("owner authentication failed")
        authenticated_at = self._clock()
        csrf_token = self._new_token()
        csrf_digest = _digest(csrf_token)
        for _attempt in range(8):
            session_token = self._new_token()
            principal = AuthenticatedOwner(
                owner_id=self._owner_id,
                session_id=self._id_factory("session"),
                authentication_method=_AUTHENTICATION_METHOD,
                authenticated_at=authenticated_at,
                reauthenticated_until=authenticated_at + self._recent_auth_ttl,
                expires_at=authenticated_at + self._session_ttl,
            )
            inserted = self._connection.execute(
                """
                INSERT INTO melloa.owner_sessions (
                    session_digest, session_id, owner_id, credential_digest,
                    csrf_digest, authentication_method, authenticated_at,
                    reauthenticated_until, expires_at, document
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING session_id
                """,
                (
                    _digest(session_token),
                    principal.session_id,
                    principal.owner_id,
                    self._bootstrap_digest,
                    csrf_digest,
                    principal.authentication_method,
                    principal.authenticated_at,
                    principal.reauthenticated_until,
                    principal.expires_at,
                    Jsonb(principal.model_dump(mode="json")),
                ),
            ).fetchone()
            if inserted is not None:
                return IssuedOwnerSession(
                    principal=principal,
                    session_token=session_token,
                    csrf_token=csrf_token,
                )
        raise RuntimeError("could not generate a unique owner session")

    def verify(
        self,
        session_token: str,
        *,
        csrf_token: str | None = None,
        require_csrf: bool = False,
        require_recent: bool = False,
    ) -> AuthenticatedOwner:
        if not self._valid_secret(session_token):
            raise AuthenticationError("owner authentication failed")
        row = self._connection.execute(
            """
            SELECT session.credential_digest, session.csrf_digest, session.document,
                   revocation.session_id
              FROM melloa.owner_sessions AS session
              LEFT JOIN melloa.owner_session_revocations AS revocation
                ON revocation.session_id = session.session_id
             WHERE session.session_digest = %s
            """,
            (_digest(session_token),),
        ).fetchone()
        if row is None:
            raise AuthenticationError("owner authentication failed")
        try:
            credential_digest = bytes(row[0])
            csrf_digest = bytes(row[1])
            principal = AuthenticatedOwner.model_validate_json(canonical_json_bytes(row[2]))
        except (TypeError, ValueError, ValidationError) as error:
            raise AuthenticationError("owner authentication failed") from error
        if (
            row[3] is not None
            or principal.owner_id != self._owner_id
            or principal.authentication_method != _AUTHENTICATION_METHOD
            or not hmac.compare_digest(credential_digest, self._bootstrap_digest)
        ):
            raise AuthenticationError("owner authentication failed")
        now = self._clock()
        if now >= principal.expires_at:
            raise AuthenticationError("owner authentication failed")
        if require_csrf:
            if not self._valid_secret(csrf_token) or not hmac.compare_digest(
                _digest(csrf_token), csrf_digest
            ):
                raise CsrfValidationError("browser action failed CSRF validation")
        if require_recent and now >= principal.reauthenticated_until:
            raise RecentAuthenticationRequired("recent owner authentication required")
        return principal

    def revoke(self, session_token: str) -> None:
        if not self._valid_secret(session_token):
            return
        self._connection.execute(
            """
            INSERT INTO melloa.owner_session_revocations (
                session_id, revoked_at, reason_code
            )
            SELECT session_id, greatest(authenticated_at, %s), 'auth.owner-logout'
              FROM melloa.owner_sessions
             WHERE session_digest = %s
            ON CONFLICT DO NOTHING
            """,
            (self._clock(), _digest(session_token)),
        )

    def _new_token(self) -> str:
        token = self._token_factory()
        if not self._valid_secret(token):
            raise RuntimeError("token factory returned an invalid opaque token")
        return token

    @staticmethod
    def _valid_secret(value: str | None) -> TypeGuard[str]:
        return value is not None and 1 <= len(value) <= _MAXIMUM_SECRET_LENGTH
