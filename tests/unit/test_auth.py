from __future__ import annotations

from datetime import timedelta

import pytest

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.store import InMemoryEventAuditStore
from melloa.ports.auth import (
    AuthenticationError,
    CsrfValidationError,
    RecentAuthenticationRequired,
)
from tests.conftest import record_id


def test_owner_session_hides_tokens_and_enforces_csrf(fixed_time) -> None:
    tokens = iter(("session-token", "csrf-token"))
    manager = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )

    issued = manager.issue("synthetic-bootstrap-token-value-0001")

    assert "session-token" not in repr(issued)
    assert "csrf-token" not in repr(issued)
    assert issued.principal.owner_id == record_id("owner", 1)
    assert manager.verify("session-token") == issued.principal
    assert (
        manager.verify("session-token", csrf_token="csrf-token", require_csrf=True)
        == issued.principal
    )
    with pytest.raises(CsrfValidationError):
        manager.verify("session-token", csrf_token="wrong", require_csrf=True)


def test_owner_session_issue_and_revoke_append_content_free_audit(fixed_time) -> None:
    tokens = iter(("session-token", "csrf-token"))
    audit_store = InMemoryEventAuditStore()
    manager = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        event_audit_store=audit_store,
        clock=lambda: fixed_time,
        token_factory=lambda: next(tokens),
    )

    issued = manager.issue("synthetic-bootstrap-token-value-0001")
    manager.revoke(issued.session_token)
    manager.revoke(issued.session_token)

    assert tuple(event.event_type for event in audit_store.events) == (
        "auth.owner-session-issued.v1",
        "auth.owner-session-revoked.v1",
    )
    assert [event.payload for event in audit_store.events] == [
        {
            "authentication_method": "auth.synthetic-opaque-token",
            "session_id": issued.principal.session_id,
            "state": "issued",
        },
        {
            "authentication_method": "auth.synthetic-opaque-token",
            "session_id": issued.principal.session_id,
            "state": "revoked",
        },
    ]
    audit_documents = tuple(
        event.model_dump_json() for event in audit_store.events
    ) + tuple(record.model_dump_json() for record in audit_store.audit_records)
    assert all(
        "synthetic-bootstrap-token-value-0001" not in document
        for document in audit_documents
    )
    assert all("session-token" not in document for document in audit_documents)
    assert all("csrf-token" not in document for document in audit_documents)
    issued_audit, revoked_audit = audit_store.audit_records
    assert issued_audit.content.action == "auth.owner-session.issue"
    assert revoked_audit.content.action == "auth.owner-session.revoke"
    assert revoked_audit.previous_hash == issued_audit.record_hash


def test_owner_session_rejects_bad_credentials_expiry_and_revocation(fixed_time) -> None:
    now = fixed_time
    tokens = iter(("session-token", "csrf-token"))
    manager = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: now,
        token_factory=lambda: next(tokens),
        session_ttl=timedelta(minutes=10),
        recent_auth_ttl=timedelta(minutes=2),
    )

    with pytest.raises(AuthenticationError):
        manager.issue("incorrect-bootstrap-token-value")
    issued = manager.issue("synthetic-bootstrap-token-value-0001")
    now = fixed_time + timedelta(minutes=2)
    with pytest.raises(RecentAuthenticationRequired):
        manager.verify(issued.session_token, require_recent=True)
    assert manager.verify(issued.session_token).owner_id == record_id("owner", 1)
    manager.revoke(issued.session_token)
    with pytest.raises(AuthenticationError):
        manager.verify(issued.session_token)

    tokens = iter(("second-session-token", "second-csrf-token"))
    issued = manager.issue("synthetic-bootstrap-token-value-0001")
    now = fixed_time + timedelta(minutes=12)
    with pytest.raises(AuthenticationError):
        manager.verify(issued.session_token)


def test_owner_session_cleanup_removes_expired_sessions(fixed_time) -> None:
    now = fixed_time
    tokens = iter(
        (
            "first-session-token",
            "first-csrf-token",
            "second-session-token",
            "second-csrf-token",
        )
    )
    manager = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: now,
        token_factory=lambda: next(tokens),
        session_ttl=timedelta(minutes=10),
    )
    first = manager.issue("synthetic-bootstrap-token-value-0001")
    now = fixed_time + timedelta(seconds=1)
    second = manager.issue("synthetic-bootstrap-token-value-0001")

    now = fixed_time + timedelta(minutes=10)
    cleanup = manager.cleanup_expired_sessions(limit=1)

    assert cleanup.expired_sessions == 1
    assert cleanup.expired_revocations == 0
    assert manager.verify(second.session_token) == second.principal
    with pytest.raises(AuthenticationError):
        manager.verify(first.session_token)

    now = fixed_time + timedelta(minutes=11)
    assert manager.active_sessions() == ()
    with pytest.raises(ValueError, match="session cleanup limit"):
        manager.cleanup_expired_sessions(limit=-1)
    with pytest.raises(ValueError, match="session cleanup limit"):
        manager.cleanup_expired_sessions(limit=10_001)


def test_owner_can_list_and_revoke_other_active_sessions(fixed_time) -> None:
    now = fixed_time
    tokens = iter(
        (
            "first-session-token",
            "first-csrf-token",
            "second-session-token",
            "second-csrf-token",
        )
    )
    manager = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        clock=lambda: now,
        token_factory=lambda: next(tokens),
        session_ttl=timedelta(minutes=10),
    )
    first = manager.issue("synthetic-bootstrap-token-value-0001")
    now = fixed_time + timedelta(seconds=1)
    second = manager.issue("synthetic-bootstrap-token-value-0001")

    assert manager.active_sessions() == (second.principal, first.principal)
    assert manager.revoke_other_sessions(first.principal.session_id) == 1
    assert manager.active_sessions() == (first.principal,)
    assert manager.verify(first.session_token) == first.principal
    with pytest.raises(AuthenticationError):
        manager.verify(second.session_token)
    assert manager.revoke_other_sessions(first.principal.session_id) == 0

    now = fixed_time + timedelta(minutes=10)
    assert manager.active_sessions() == ()
    with pytest.raises(AuthenticationError):
        manager.revoke_other_sessions(first.principal.session_id)


def test_owner_session_bulk_revoke_appends_content_free_audit(fixed_time) -> None:
    now = fixed_time
    tokens = iter(
        (
            "first-session-token",
            "first-csrf-token",
            "second-session-token",
            "second-csrf-token",
        )
    )
    audit_store = InMemoryEventAuditStore()
    manager = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        event_audit_store=audit_store,
        clock=lambda: now,
        token_factory=lambda: next(tokens),
    )
    first = manager.issue("synthetic-bootstrap-token-value-0001")
    now = fixed_time + timedelta(seconds=1)
    second = manager.issue("synthetic-bootstrap-token-value-0001")

    assert manager.revoke_other_sessions(first.principal.session_id) == 1

    assert tuple(event.event_type for event in audit_store.events) == (
        "auth.owner-session-issued.v1",
        "auth.owner-session-issued.v1",
        "auth.owner-session-revoked.v1",
    )
    revoked_event = audit_store.events[-1]
    assert revoked_event.payload == {
        "authentication_method": "auth.synthetic-opaque-token",
        "session_id": second.principal.session_id,
        "state": "revoked",
    }
    audit_documents = tuple(
        event.model_dump_json() for event in audit_store.events
    ) + tuple(record.model_dump_json() for record in audit_store.audit_records)
    assert all("first-session-token" not in document for document in audit_documents)
    assert all("second-session-token" not in document for document in audit_documents)
    assert all("first-csrf-token" not in document for document in audit_documents)
    assert all("second-csrf-token" not in document for document in audit_documents)


def test_owner_session_audit_failure_leaves_in_memory_source_state(
    fixed_time,
) -> None:
    issue_tokens = iter(("issue-session-token", "issue-csrf-token"))
    issue_manager = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        event_audit_store=_ControllableAuditStore(fail_next=True),
        clock=lambda: fixed_time,
        token_factory=lambda: next(issue_tokens),
    )

    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        issue_manager.issue("synthetic-bootstrap-token-value-0001")
    assert issue_manager.active_sessions() == ()

    revoke_tokens = iter(("session-token", "csrf-token"))
    revoke_audit_store = _ControllableAuditStore()
    revoke_manager = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        event_audit_store=revoke_audit_store,
        clock=lambda: fixed_time,
        token_factory=lambda: next(revoke_tokens),
    )
    issued = revoke_manager.issue("synthetic-bootstrap-token-value-0001")
    revoke_audit_store.fail_next = True

    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        revoke_manager.revoke(issued.session_token)
    assert revoke_manager.verify(issued.session_token) == issued.principal

    bulk_audit_store = _ControllableAuditStore()
    bulk_tokens = iter(
        (
            "first-session-token",
            "first-csrf-token",
            "second-session-token",
            "second-csrf-token",
        )
    )
    bulk_manager = InMemoryOwnerSessionManager(
        record_id("owner", 1),
        "synthetic-bootstrap-token-value-0001",
        event_audit_store=bulk_audit_store,
        clock=lambda: fixed_time,
        token_factory=lambda: next(bulk_tokens),
    )
    first = bulk_manager.issue("synthetic-bootstrap-token-value-0001")
    second = bulk_manager.issue("synthetic-bootstrap-token-value-0001")
    bulk_audit_store.fail_next = True

    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        bulk_manager.revoke_other_sessions(first.principal.session_id)
    assert bulk_manager.verify(first.session_token) == first.principal
    assert bulk_manager.verify(second.session_token) == second.principal


@pytest.mark.parametrize(
    ("session_ttl", "recent_ttl"),
    [
        (timedelta(0), timedelta(minutes=1)),
        (timedelta(minutes=1), timedelta(0)),
        (timedelta(minutes=1), timedelta(minutes=2)),
    ],
)
def test_owner_session_rejects_invalid_ttls(session_ttl, recent_ttl) -> None:
    with pytest.raises(ValueError):
        InMemoryOwnerSessionManager(
            record_id("owner", 1),
            "synthetic-bootstrap-token-value-0001",
            session_ttl=session_ttl,
            recent_auth_ttl=recent_ttl,
        )


class _ControllableAuditStore(InMemoryEventAuditStore):
    def __init__(self, *, fail_next: bool = False) -> None:
        super().__init__()
        self.fail_next = fail_next

    def append_event(self, event, audit):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("synthetic audit outage")
        return super().append_event(event, audit)
