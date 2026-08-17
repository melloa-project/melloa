"""Application-authentication port for the single owner principal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId


class AuthenticationError(RuntimeError):
    """Credentials or a session failed authentication without revealing why."""


class OwnerSessionMissing(AuthenticationError):
    """A request did not present a known, valid owner session."""


class OwnerSessionExpired(AuthenticationError):
    """A known owner session was presented after its expiry."""


class CsrfValidationError(AuthenticationError):
    """A browser mutation lacked the session-bound CSRF proof."""


class RecentAuthenticationRequired(AuthenticationError):
    """A high-impact operation requires a fresh owner authentication."""


@dataclass(frozen=True)
class IssuedOwnerSession:
    principal: AuthenticatedOwner
    session_token: str = field(repr=False)
    csrf_token: str = field(repr=False)


@dataclass(frozen=True)
class OwnerSessionCleanupResult:
    expired_sessions: int
    expired_revocations: int = 0


class OwnerSessionManager(Protocol):
    def issue(self, credential: str) -> IssuedOwnerSession:
        """Authenticate one owner credential and issue a short-lived browser session."""

    def verify(
        self,
        session_token: str,
        *,
        csrf_token: str | None = None,
        require_csrf: bool = False,
        require_recent: bool = False,
    ) -> AuthenticatedOwner:
        """Verify an opaque session and optional browser-action constraints."""

    def revoke(self, session_token: str) -> None:
        """Revoke an opaque owner session without disclosing whether it existed."""

    def active_sessions(self) -> tuple[AuthenticatedOwner, ...]:
        """List unexpired, unrevoked sessions for the configured owner credential."""

    def revoke_other_sessions(self, current_session_id: RecordId) -> int:
        """Revoke every active session except the authenticated current session."""

    def cleanup_expired_sessions(self, *, limit: int = 1000) -> OwnerSessionCleanupResult:
        """Remove bounded expired session state while preserving append audit records."""
