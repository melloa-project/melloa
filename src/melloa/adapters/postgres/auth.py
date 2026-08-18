"""Hashed PostgreSQL owner sessions with append-only revocation evidence."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal, TypeGuard

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError

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
        event_audit_store: EventAuditStore | None = None,
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
        self._event_audit_store = event_audit_store
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
            with self._connection.transaction():
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
                    self._append_session_audit(
                        session_id=principal.session_id,
                        occurred_at=principal.authenticated_at,
                        lifecycle="issued",
                    )
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
            raise OwnerSessionMissing("owner authentication failed")
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
            raise OwnerSessionMissing("owner authentication failed")
        try:
            credential_digest = bytes(row[0])
            csrf_digest = bytes(row[1])
            principal = self._validated_principal(row[2])
        except (TypeError, ValueError) as error:
            raise AuthenticationError("owner authentication failed") from error
        if (
            row[3] is not None
            or not hmac.compare_digest(credential_digest, self._bootstrap_digest)
        ):
            raise OwnerSessionMissing("owner authentication failed")
        now = self._clock()
        if now >= principal.expires_at:
            raise OwnerSessionExpired("owner authentication failed")
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
        with self._connection.transaction():
            revoked = self._connection.execute(
                """
                INSERT INTO melloa.owner_session_revocations (
                    session_id, revoked_at, reason_code
                )
                SELECT session_id, greatest(authenticated_at, %s), 'auth.owner-logout'
                  FROM melloa.owner_sessions
                 WHERE session_digest = %s AND owner_id = %s
                ON CONFLICT DO NOTHING
                RETURNING session_id, revoked_at
                """,
                (self._clock(), _digest(session_token), self._owner_id),
            ).fetchone()
            if revoked is not None:
                self._append_session_audit(
                    session_id=str(revoked[0]),
                    occurred_at=revoked[1],
                    lifecycle="revoked",
                )

    def active_sessions(self) -> tuple[AuthenticatedOwner, ...]:
        self.cleanup_expired_sessions()
        rows = self._connection.execute(
            """
            SELECT session.document
              FROM melloa.owner_sessions AS session
              LEFT JOIN melloa.owner_session_revocations AS revocation
                ON revocation.session_id = session.session_id
             WHERE session.owner_id = %s
               AND session.credential_digest = %s
               AND session.expires_at > %s
               AND revocation.session_id IS NULL
             ORDER BY session.authenticated_at DESC, session.session_id DESC
            """,
            (self._owner_id, self._bootstrap_digest, self._clock()),
        ).fetchall()
        try:
            return tuple(self._validated_principal(row[0]) for row in rows)
        except (TypeError, ValueError) as error:
            raise AuthenticationError("owner authentication failed") from error

    def revoke_other_sessions(self, current_session_id: RecordId) -> int:
        revoked_at = self._clock()
        with self._connection.transaction():
            rows = self._connection.execute(
                """
                WITH current_session AS MATERIALIZED (
                    SELECT session.session_id
                      FROM melloa.owner_sessions AS session
                     WHERE session.session_id = %s
                       AND session.owner_id = %s
                       AND session.credential_digest = %s
                       AND session.expires_at > %s
                       AND NOT EXISTS (
                           SELECT 1
                             FROM melloa.owner_session_revocations AS current_revocation
                            WHERE current_revocation.session_id = session.session_id
                       )
                ), revoked AS (
                    INSERT INTO melloa.owner_session_revocations (
                        session_id, revoked_at, reason_code
                    )
                    SELECT session.session_id,
                           greatest(session.authenticated_at, %s),
                           'auth.owner-signout-other-sessions'
                      FROM melloa.owner_sessions AS session
                      CROSS JOIN current_session
                      LEFT JOIN melloa.owner_session_revocations AS revocation
                        ON revocation.session_id = session.session_id
                     WHERE session.owner_id = %s
                       AND session.credential_digest = %s
                       AND session.session_id <> %s
                       AND session.expires_at > %s
                       AND revocation.session_id IS NULL
                    ON CONFLICT DO NOTHING
                    RETURNING session_id, revoked_at
                )
                SELECT revoked.session_id, revoked.revoked_at
                  FROM current_session
                  LEFT JOIN revoked ON true
                """,
                (
                    current_session_id,
                    self._owner_id,
                    self._bootstrap_digest,
                    revoked_at,
                    revoked_at,
                    self._owner_id,
                    self._bootstrap_digest,
                    current_session_id,
                    revoked_at,
                ),
            ).fetchall()
            if not rows:
                raise OwnerSessionMissing("owner authentication failed")
            revoked = tuple(row for row in rows if row[0] is not None)
            for session_id, session_revoked_at in revoked:
                self._append_session_audit(
                    session_id=str(session_id),
                    occurred_at=session_revoked_at,
                    lifecycle="revoked",
                )
        return len(revoked)

    def cleanup_expired_sessions(self, *, limit: int = 1000) -> OwnerSessionCleanupResult:
        if not 0 <= limit <= _MAXIMUM_CLEANUP_LIMIT:
            raise ValueError("session cleanup limit must be between 0 and 10000")
        if limit == 0:
            return OwnerSessionCleanupResult(expired_sessions=0, expired_revocations=0)
        row = self._connection.execute(
            """
            SELECT expired_sessions, expired_revocations
              FROM melloa.cleanup_expired_owner_sessions(%s, %s, %s)
            """,
            (self._owner_id, self._clock(), limit),
        ).fetchone()
        if row is None:
            return OwnerSessionCleanupResult(expired_sessions=0, expired_revocations=0)
        return OwnerSessionCleanupResult(
            expired_sessions=int(row[0]),
            expired_revocations=int(row[1]),
        )

    def _validated_principal(self, document: Any) -> AuthenticatedOwner:
        try:
            principal = AuthenticatedOwner.model_validate_json(canonical_json_bytes(document))
        except (TypeError, ValueError, ValidationError) as error:
            raise ValueError("invalid persisted owner session") from error
        if (
            principal.owner_id != self._owner_id
            or principal.authentication_method != _AUTHENTICATION_METHOD
        ):
            raise ValueError("persisted owner session authority mismatch")
        return principal

    def _append_session_audit(
        self,
        *,
        session_id: RecordId,
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
            "authentication_method": _AUTHENTICATION_METHOD,
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

    def _new_token(self) -> str:
        token = self._token_factory()
        if not self._valid_secret(token):
            raise RuntimeError("token factory returned an invalid opaque token")
        return token

    @staticmethod
    def _valid_secret(value: str | None) -> TypeGuard[str]:
        return value is not None and 1 <= len(value) <= _MAXIMUM_SECRET_LENGTH
