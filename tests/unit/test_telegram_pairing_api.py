from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from melloa.adapters.fakes.auth import InMemoryOwnerSessionManager
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.telegram import (
    DeterministicTelegramPairingCodeIssuer,
    FakeTelegramPairingChallengePublisher,
    InMemoryTelegramPairingStateStore,
)
from melloa.application.telegram import TelegramPairingService
from melloa.apps.core import create_app
from melloa.domain.base import sha256_digest
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.telegram import (
    TelegramChatType,
    TelegramInboundMessage,
    TelegramInboundUpdate,
)
from tests.conftest import record_id

_ADAPTER_ID = "client.telegram.synthetic"
_BOOTSTRAP_TOKEN = "synthetic-owner-bootstrap-token-value-0001"
_OWNER_ID = record_id("owner", 1)


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def sequential_id_factory():
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return record_id(prefix, counts[prefix])

    return create


def guardian(fixed_time: datetime, mode: GuardianMode = GuardianMode.NO_ACTIONS):
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=mode,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic-telegram-pairing-api",
        ),
        receipt_hash="sha256:" + "5" * 64,
    )


def start_update(fixed_time: datetime, update_id: int = 1) -> TelegramInboundUpdate:
    return TelegramInboundUpdate(
        update_id=update_id,
        message=TelegramInboundMessage(
            telegram_message_id=update_id + 1,
            sender_user_id=1001,
            chat_id=1001,
            chat_type=TelegramChatType.PRIVATE,
            sent_at=fixed_time,
            text="/start",
        ),
        received_at=fixed_time,
        raw_size_bytes=128,
        source_payload_hash=sha256_digest(f"pairing-start:{update_id}".encode()),
    )


def pairing_fixture(
    fixed_time: datetime,
    clock: MutableClock,
    *,
    mode: GuardianMode = GuardianMode.NO_ACTIONS,
):
    guardian_reader = guardian(fixed_time, mode)
    publisher = FakeTelegramPairingChallengePublisher()
    service = TelegramPairingService(
        owner_id=_OWNER_ID,
        adapter_id=_ADAPTER_ID,
        store=InMemoryTelegramPairingStateStore(),
        code_issuer=DeterministicTelegramPairingCodeIssuer(),
        challenge_publisher=publisher,
        guardian_reader=guardian_reader,
        clock=clock,
        id_factory=sequential_id_factory(),
    )
    candidate = service.begin_candidate(start_update(fixed_time))
    challenge = publisher.challenge_for(candidate.candidate_id)
    sessions = InMemoryOwnerSessionManager(
        _OWNER_ID,
        _BOOTSTRAP_TOKEN,
        clock=clock,
        token_factory=iter(("session-token", "csrf-token")).__next__,
    )
    app = create_app(
        guardian_reader,
        sessions,
        telegram_pairing_service=service,
    )
    return app, service, candidate, challenge


def test_pairing_api_is_private_redacted_recent_auth_and_csrf_bound(fixed_time) -> None:
    clock = MutableClock(fixed_time)
    app, _service, candidate, challenge = pairing_fixture(fixed_time, clock)
    client = TestClient(app, base_url="https://testserver")
    candidates_path = "/api/v1/integrations/telegram/pairing/candidates"
    confirm_path = f"{candidates_path}/{candidate.candidate_id}/confirm"

    assert client.get(candidates_path).status_code == 401
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    assert login.status_code == 200
    csrf_headers = {"X-Melloa-CSRF": login.json()["csrf_token"]}

    candidates = client.get(candidates_path)
    assert candidates.status_code == 200
    assert candidates.json() == [
        {
            "candidate_id": candidate.candidate_id,
            "update_id": candidate.update_id,
            "telegram_user_id": candidate.telegram_user_id,
            "telegram_chat_id": candidate.telegram_chat_id,
            "observed_at": candidate.observed_at.isoformat().replace("+00:00", "Z"),
            "expires_at": candidate.expires_at.isoformat().replace("+00:00", "Z"),
        }
    ]
    serialized = candidates.text
    assert candidate.confirmation_code_hash not in serialized
    assert challenge.confirmation_code not in serialized

    assert client.post(
        confirm_path,
        json={"confirmation_code": challenge.confirmation_code},
    ).status_code == 403
    assert client.post(
        confirm_path,
        headers=csrf_headers,
        json={"confirmation_code": "short"},
    ).status_code == 422
    conflict = client.post(
        confirm_path,
        headers=csrf_headers,
        json={"confirmation_code": "wrong-code-with-enough-length"},
    )
    assert conflict.status_code == 409
    assert conflict.json() == {
        "code": "telegram_pairing_conflict",
        "message": "Telegram pairing state conflicts with this request.",
    }

    confirmed = client.post(
        confirm_path,
        headers=csrf_headers,
        json={"confirmation_code": challenge.confirmation_code},
    )
    assert confirmed.status_code == 200
    pairing = confirmed.json()
    assert pairing["owner_id"] == _OWNER_ID
    assert pairing["confirmed_by_owner_id"] == _OWNER_ID
    assert client.get(candidates_path).json() == []
    assert client.get("/api/v1/integrations/telegram/pairing").json() == pairing

    revoke_path = (
        f"/api/v1/integrations/telegram/pairing/{pairing['pairing_id']}/revoke"
    )
    assert client.post(revoke_path).status_code == 403
    revoked = client.post(revoke_path, headers=csrf_headers)
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] == fixed_time.isoformat().replace("+00:00", "Z")
    assert client.get("/api/v1/integrations/telegram/pairing").json() is None

    unknown = client.post(
        f"{candidates_path}/{record_id('tgcandidate', 99)}/confirm",
        headers=csrf_headers,
        json={"confirmation_code": challenge.confirmation_code},
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "telegram_pairing_not_found"


def test_pairing_api_rejects_expired_recent_auth_before_confirmation(fixed_time) -> None:
    clock = MutableClock(fixed_time)
    app, _service, candidate, challenge = pairing_fixture(fixed_time, clock)
    client = TestClient(app, base_url="https://testserver")
    login = client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    )
    headers = {"X-Melloa-CSRF": login.json()["csrf_token"]}
    clock.now = fixed_time + timedelta(minutes=5)

    response = client.post(
        "/api/v1/integrations/telegram/pairing/candidates/"
        f"{candidate.candidate_id}/confirm",
        headers=headers,
        json={"confirmation_code": challenge.confirmation_code},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "recent_authentication_required"
    assert client.get("/api/v1/integrations/telegram/pairing/candidates").status_code == 200


def test_pairing_api_fails_closed_when_service_is_absent(fixed_time) -> None:
    clock = MutableClock(fixed_time)
    sessions = InMemoryOwnerSessionManager(
        _OWNER_ID,
        _BOOTSTRAP_TOKEN,
        clock=clock,
        token_factory=iter(("session-token", "csrf-token")).__next__,
    )
    client = TestClient(
        create_app(guardian(fixed_time), sessions),
        base_url="https://testserver",
    )
    assert client.post(
        "/api/v1/auth/session",
        json={"credential": _BOOTSTRAP_TOKEN},
    ).status_code == 200

    unavailable = client.get("/api/v1/integrations/telegram/pairing/candidates")

    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == "Telegram pairing is not configured."
