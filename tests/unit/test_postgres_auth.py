from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.adapters.postgres.auth import PostgresOwnerSessionManager
from melloa.ports.auth import (
    AuthenticationError,
    CsrfValidationError,
    OwnerSessionExpired,
    OwnerSessionMissing,
    RecentAuthenticationRequired,
)
from tests.conftest import record_id

_BOOTSTRAP_TOKEN = "postgres-owner-bootstrap-token-value-0001"


class _Result:
    def __init__(
        self,
        row: tuple[Any, ...] | None = None,
        *,
        rows: tuple[tuple[Any, ...], ...] = (),
    ) -> None:
        self._row = row
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> tuple[tuple[Any, ...], ...]:
        return self._rows


@dataclass
class _SessionDatabase:
    sessions: dict[bytes, tuple[Any, ...]] = field(default_factory=dict)
    session_ids: set[str] = field(default_factory=set)
    revoked_session_ids: set[str] = field(default_factory=set)


class _Connection:
    def __init__(self, database: _SessionDatabase) -> None:
        self.database = database

    def execute(self, statement: str, parameters: tuple[Any, ...]) -> _Result:
        if "INSERT INTO melloa.owner_sessions" in statement:
            session_digest = parameters[0]
            session_id = parameters[1]
            if session_digest in self.database.sessions or session_id in self.database.session_ids:
                return _Result(None)
            document = parameters[9]
            assert isinstance(document, Jsonb)
            self.database.sessions[session_digest] = (
                parameters[3],
                parameters[4],
                document.obj,
                session_id,
                parameters[2],
                parameters[6],
                parameters[8],
            )
            self.database.session_ids.add(session_id)
            return _Result((session_id,))
        if "SELECT session.document" in statement:
            owner_id, credential_digest, now = parameters
            active = tuple(
                sorted(
                    (
                        (stored[2], stored[5], stored[3])
                        for stored in self.database.sessions.values()
                        if stored[4] == owner_id
                        and stored[0] == credential_digest
                        and stored[6] > now
                        and stored[3] not in self.database.revoked_session_ids
                    ),
                    key=lambda row: (row[1], row[2]),
                    reverse=True,
                )
            )
            return _Result(rows=tuple((document,) for document, _at, _id in active))
        if "WHERE session.session_digest = %s" in statement:
            stored = self.database.sessions.get(parameters[0])
            if stored is None:
                return _Result(None)
            credential_digest, csrf_digest, document, session_id = stored[:4]
            revoked = session_id if session_id in self.database.revoked_session_ids else None
            return _Result((credential_digest, csrf_digest, document, revoked))
        if "'auth.owner-signout-other-sessions'" in statement:
            revoked_at, owner_id, credential_digest, current_session_id, now = parameters
            revoked_rows: list[tuple[Any, ...]] = []
            for stored in self.database.sessions.values():
                session_id = stored[3]
                if (
                    stored[4] == owner_id
                    and stored[0] == credential_digest
                    and session_id != current_session_id
                    and stored[6] > now
                    and session_id not in self.database.revoked_session_ids
                ):
                    self.database.revoked_session_ids.add(session_id)
                    revoked_rows.append((session_id, max(stored[5], revoked_at)))
            return _Result(rows=tuple(revoked_rows))
        if "INSERT INTO melloa.owner_session_revocations" in statement:
            session_digest = parameters[1]
            stored = self.database.sessions.get(session_digest)
            if stored is None or stored[3] in self.database.revoked_session_ids:
                return _Result(None)
            self.database.revoked_session_ids.add(stored[3])
            return _Result((stored[3], parameters[0]))
        if "cleanup_expired_owner_sessions" in statement:
            owner_id, before, limit = parameters
            expired = tuple(
                sorted(
                    (
                        (stored[6], stored[3], digest)
                        for digest, stored in self.database.sessions.items()
                        if stored[4] == owner_id and stored[6] <= before
                    ),
                    key=lambda row: (row[0], row[1]),
                )
            )[:limit]
            expired_session_ids = {session_id for _expires, session_id, _digest in expired}
            expired_revocations = len(
                self.database.revoked_session_ids.intersection(expired_session_ids)
            )
            self.database.revoked_session_ids.difference_update(expired_session_ids)
            for _expires, session_id, digest in expired:
                self.database.sessions.pop(digest, None)
                self.database.session_ids.discard(session_id)
            return _Result((len(expired), expired_revocations))
        raise AssertionError(f"unexpected SQL: {statement}")

    @contextmanager
    def transaction(self):
        sessions = dict(self.database.sessions)
        session_ids = set(self.database.session_ids)
        revoked_session_ids = set(self.database.revoked_session_ids)
        try:
            yield
        except Exception:
            self.database.sessions = sessions
            self.database.session_ids = session_ids
            self.database.revoked_session_ids = revoked_session_ids
            raise


class _FailingAuditStore(InMemoryEventAuditStore):
    def append_event(self, event, audit):
        raise RuntimeError("synthetic audit outage")


def test_postgres_owner_session_survives_restart_without_plaintext(fixed_time) -> None:
    database = _SessionDatabase()
    now = fixed_time
    tokens = iter(("csrf-token", "session-token"))
    audit_store = InMemoryEventAuditStore()
    manager = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        event_audit_store=audit_store,
        clock=lambda: now,
        token_factory=lambda: next(tokens),
        id_factory=lambda _prefix: record_id("session", 1),
    )

    with pytest.raises(AuthenticationError):
        manager.issue("wrong-owner-bootstrap-token-value")
    issued = manager.issue(_BOOTSTRAP_TOKEN)

    assert "session-token" not in repr(issued)
    assert "csrf-token" not in repr(issued)
    persisted = next(iter(database.sessions.items()))
    assert len(persisted[0]) == 32
    assert len(persisted[1][0]) == 32
    assert len(persisted[1][1]) == 32
    persisted_text = repr(persisted)
    assert _BOOTSTRAP_TOKEN not in persisted_text
    assert "session-token" not in persisted_text
    assert "csrf-token" not in persisted_text

    restarted = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        event_audit_store=audit_store,
        clock=lambda: now,
    )
    assert restarted.verify(issued.session_token) == issued.principal
    assert (
        restarted.verify(
            issued.session_token,
            csrf_token=issued.csrf_token,
            require_csrf=True,
            require_recent=True,
        )
        == issued.principal
    )
    with pytest.raises(CsrfValidationError):
        restarted.verify(
            issued.session_token,
            csrf_token="incorrect-csrf-token",
            require_csrf=True,
        )

    rotated = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        "rotated-owner-bootstrap-token-value-0002",
        clock=lambda: now,
    )
    with pytest.raises(AuthenticationError):
        rotated.verify(issued.session_token)

    now = fixed_time + timedelta(minutes=5)
    with pytest.raises(RecentAuthenticationRequired):
        restarted.verify(issued.session_token, require_recent=True)
    assert restarted.verify(issued.session_token) == issued.principal
    restarted.revoke(issued.session_token)
    restarted.revoke(issued.session_token)
    with pytest.raises(AuthenticationError):
        restarted.verify(issued.session_token)

    assert len(audit_store.events) == 2
    issued_event, revoked_event = audit_store.events
    assert issued_event.event_type == "auth.owner-session-issued.v1"
    assert issued_event.payload == {
        "authentication_method": "auth.local-opaque-token",
        "session_id": issued.principal.session_id,
        "state": "issued",
    }
    assert revoked_event.event_type == "auth.owner-session-revoked.v1"
    assert revoked_event.payload == {
        "authentication_method": "auth.local-opaque-token",
        "session_id": issued.principal.session_id,
        "state": "revoked",
    }
    audit_documents = tuple(
        event.model_dump_json() for event in audit_store.events
    ) + tuple(record.model_dump_json() for record in audit_store.audit_records)
    assert all(_BOOTSTRAP_TOKEN not in document for document in audit_documents)
    assert all("session-token" not in document for document in audit_documents)
    assert all("csrf-token" not in document for document in audit_documents)
    issued_audit, revoked_audit = audit_store.audit_records
    assert issued_audit.content.action == "auth.owner-session.issue"
    assert revoked_audit.content.action == "auth.owner-session.revoke"
    assert revoked_audit.previous_hash == issued_audit.record_hash


def test_postgres_owner_session_expiry_collision_and_validation(fixed_time) -> None:
    database = _SessionDatabase()
    now = fixed_time
    first_tokens = iter(("first-csrf", "shared-session"))
    first = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        clock=lambda: now,
        token_factory=lambda: next(first_tokens),
        id_factory=lambda _prefix: record_id("session", 1),
        session_ttl=timedelta(minutes=10),
        recent_auth_ttl=timedelta(minutes=2),
    ).issue(_BOOTSTRAP_TOKEN)

    retry_tokens = iter(("second-csrf", "shared-session", "unique-session"))
    session_ids = iter((record_id("session", 2), record_id("session", 3)))
    manager = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        clock=lambda: now,
        token_factory=lambda: next(retry_tokens),
        id_factory=lambda _prefix: next(session_ids),
        session_ttl=timedelta(minutes=10),
        recent_auth_ttl=timedelta(minutes=2),
    )
    second = manager.issue(_BOOTSTRAP_TOKEN)
    assert second.session_token == "unique-session"
    assert first.session_token == "shared-session"

    with pytest.raises(OwnerSessionMissing):
        manager.verify("unknown-session")
    manager.revoke("")
    now = fixed_time + timedelta(minutes=10)
    with pytest.raises(OwnerSessionExpired):
        manager.verify(second.session_token)

    with pytest.raises(RuntimeError, match="invalid opaque token"):
        PostgresOwnerSessionManager(
            _Connection(database),
            record_id("owner", 1),
            _BOOTSTRAP_TOKEN,
            token_factory=lambda: "",
        ).issue(_BOOTSTRAP_TOKEN)


def test_postgres_owner_session_cleanup_removes_expired_rows_and_revocations(
    fixed_time,
) -> None:
    database = _SessionDatabase()
    now = fixed_time
    tokens = iter(
        (
            "first-csrf",
            "first-session",
            "second-csrf",
            "second-session",
        )
    )
    session_ids = iter((record_id("session", 1), record_id("session", 2)))
    manager = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        clock=lambda: now,
        token_factory=lambda: next(tokens),
        id_factory=lambda _prefix: next(session_ids),
        session_ttl=timedelta(minutes=10),
    )
    first = manager.issue(_BOOTSTRAP_TOKEN)
    now = fixed_time + timedelta(seconds=1)
    second = manager.issue(_BOOTSTRAP_TOKEN)
    manager.revoke(first.session_token)

    now = fixed_time + timedelta(minutes=11)
    cleanup = manager.cleanup_expired_sessions(limit=1)

    assert cleanup.expired_sessions == 1
    assert cleanup.expired_revocations == 1
    assert first.principal.session_id not in database.session_ids
    assert first.principal.session_id not in database.revoked_session_ids
    assert second.principal.session_id in database.session_ids
    assert len(database.sessions) == 1

    cleanup = manager.cleanup_expired_sessions(limit=10)
    assert cleanup.expired_sessions == 1
    assert cleanup.expired_revocations == 0
    assert database.sessions == {}
    assert database.session_ids == set()
    assert database.revoked_session_ids == set()
    with pytest.raises(ValueError, match="session cleanup limit"):
        manager.cleanup_expired_sessions(limit=-1)
    with pytest.raises(ValueError, match="session cleanup limit"):
        manager.cleanup_expired_sessions(limit=10_001)


def test_postgres_owner_lists_and_audits_other_session_revocation(fixed_time) -> None:
    database = _SessionDatabase()
    now = fixed_time
    tokens = iter(
        (
            "first-csrf",
            "first-session",
            "second-csrf",
            "second-session",
        )
    )
    session_ids = iter((record_id("session", 1), record_id("session", 2)))
    audit_store = InMemoryEventAuditStore()
    manager = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        event_audit_store=audit_store,
        clock=lambda: now,
        token_factory=lambda: next(tokens),
        id_factory=lambda _prefix: next(session_ids),
    )
    first = manager.issue(_BOOTSTRAP_TOKEN)
    now = fixed_time + timedelta(seconds=1)
    second = manager.issue(_BOOTSTRAP_TOKEN)

    assert manager.active_sessions() == (second.principal, first.principal)
    assert PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        "rotated-owner-bootstrap-token-value-0002",
        clock=lambda: now,
    ).active_sessions() == ()
    assert manager.revoke_other_sessions(first.principal.session_id) == 1
    assert manager.active_sessions() == (first.principal,)
    assert manager.verify(first.session_token) == first.principal
    with pytest.raises(AuthenticationError):
        manager.verify(second.session_token)
    assert manager.revoke_other_sessions(first.principal.session_id) == 0

    assert tuple(event.event_type for event in audit_store.events) == (
        "auth.owner-session-issued.v1",
        "auth.owner-session-issued.v1",
        "auth.owner-session-revoked.v1",
    )
    revoked_event = audit_store.events[-1]
    assert revoked_event.payload == {
        "authentication_method": "auth.local-opaque-token",
        "session_id": second.principal.session_id,
        "state": "revoked",
    }
    audit_documents = tuple(
        event.model_dump_json() for event in audit_store.events
    ) + tuple(record.model_dump_json() for record in audit_store.audit_records)
    assert all("first-session" not in document for document in audit_documents)
    assert all("second-session" not in document for document in audit_documents)
    assert all("first-csrf" not in document for document in audit_documents)
    assert all("second-csrf" not in document for document in audit_documents)


def test_postgres_owner_session_rolls_back_when_audit_fails(fixed_time) -> None:
    database = _SessionDatabase()
    tokens = iter(("failed-csrf", "failed-session"))
    manager = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        event_audit_store=_FailingAuditStore(),
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
        id_factory=lambda _prefix: record_id("session", 4),
    )

    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        manager.issue(_BOOTSTRAP_TOKEN)
    assert database.sessions == {}

    persisted_tokens = iter(("persisted-csrf", "persisted-session"))
    persisted = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        token_factory=lambda: next(persisted_tokens),
        id_factory=lambda _prefix: record_id("session", 5),
    ).issue(_BOOTSTRAP_TOKEN)
    failing_revoke = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        event_audit_store=_FailingAuditStore(),
        clock=lambda: fixed_time + timedelta(seconds=1),
    )

    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        failing_revoke.revoke(persisted.session_token)
    assert database.revoked_session_ids == set()
    assert failing_revoke.verify(persisted.session_token) == persisted.principal

    other_tokens = iter(("other-csrf", "other-session"))
    other = PostgresOwnerSessionManager(
        _Connection(database),
        record_id("owner", 1),
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        token_factory=lambda: next(other_tokens),
        id_factory=lambda _prefix: record_id("session", 6),
    ).issue(_BOOTSTRAP_TOKEN)
    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        failing_revoke.revoke_other_sessions(persisted.principal.session_id)
    assert database.revoked_session_ids == set()
    assert failing_revoke.verify(other.session_token) == other.principal


@pytest.mark.parametrize(
    ("bootstrap_token", "session_ttl", "recent_auth_ttl"),
    [
        ("short", timedelta(minutes=1), timedelta(seconds=30)),
        (_BOOTSTRAP_TOKEN, timedelta(0), timedelta(seconds=30)),
        (_BOOTSTRAP_TOKEN, timedelta(minutes=1), timedelta(0)),
        (_BOOTSTRAP_TOKEN, timedelta(minutes=1), timedelta(minutes=2)),
    ],
)
def test_postgres_owner_session_rejects_invalid_configuration(
    bootstrap_token,
    session_ttl,
    recent_auth_ttl,
) -> None:
    with pytest.raises(ValueError):
        PostgresOwnerSessionManager(
            _Connection(_SessionDatabase()),
            record_id("owner", 1),
            bootstrap_token,
            session_ttl=session_ttl,
            recent_auth_ttl=recent_auth_ttl,
        )
