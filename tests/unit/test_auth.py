from __future__ import annotations

from datetime import timedelta

import pytest

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
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
