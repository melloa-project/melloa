from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from melloa.adapters.telegram import (
    EphemeralTelegramPairingCodeIssuer,
    TelegramBotApiClientAdapter,
    TelegramBotApiConfig,
    TelegramBotApiPairingChallengePublisher,
    TelegramBotApiPairingCodeIssuer,
    TelegramBotApiUpdateSource,
)
from melloa.domain.base import sha256_digest
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import (
    ConversationMessage,
    DeliveryState,
    MessageKind,
    MessagePart,
)
from melloa.domain.delivery import AuthorizedClientDelivery, canonical_delivery_action
from melloa.domain.guardian import GuardianMode
from melloa.domain.policy import (
    AuthorizationRequest,
    DeterministicPolicyEvaluator,
    PolicyContext,
    action_hash,
)
from melloa.domain.telegram import (
    TelegramAttachmentKind,
    TelegramChatType,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramPollRequest,
    telegram_pairing_destination,
)
from melloa.ports.client import PermanentClientDeliveryError
from melloa.ports.telegram import (
    PermanentTelegramPollingError,
    TelegramPairingChallenge,
    TransientTelegramPollingError,
)
from tests.conftest import record_id

_ADAPTER_ID = "client.telegram.bot-api"
_TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFGH"


def token_file(tmp_path):
    path = tmp_path / "telegram-token"
    path.write_text(_TOKEN, encoding="utf-8")
    path.chmod(0o600)
    return path


def config(tmp_path) -> TelegramBotApiConfig:
    return TelegramBotApiConfig(
        token_file=token_file(tmp_path),
        api_base_url="http://127.0.0.1:9876",
    )


def pairing(fixed_time) -> TelegramOwnerPairing:
    return TelegramOwnerPairing(
        pairing_id=record_id("tgpairing", 1),
        candidate_id=record_id("tgcandidate", 1),
        owner_id=record_id("owner", 1),
        telegram_user_id=1001,
        telegram_chat_id=1001,
        confirmed_by_owner_id=record_id("owner", 1),
        confirmed_at=fixed_time - timedelta(minutes=1),
    )


def authorized_delivery(fixed_time, owner_pairing) -> AuthorizedClientDelivery:
    message = ConversationMessage(
        message_id=record_id("message", 1),
        thread_id=record_id("thread", 1),
        author_principal_id=record_id("intelligence", 1),
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text="A bounded reply."),),
        reply_to_message_id=record_id("message", 2),
        delivery_state=DeliveryState.DELIVERED,
        sensitivity=Sensitivity.PERSONAL,
        created_at=fixed_time,
        observed_at=fixed_time,
    )
    destination_ref = telegram_pairing_destination(owner_pairing.pairing_id)
    action = canonical_delivery_action(
        message,
        client_adapter=_ADAPTER_ID,
        destination_ref=destination_ref,
        external_destination="https://api.telegram.org",
        purpose="conversation.owner_initiated_reply",
    )
    request = AuthorizationRequest(
        request_id=record_id("request", 1),
        proposal_id=record_id("proposal", 1),
        principal_id=message.author_principal_id,
        action=action,
        action_hash=action_hash(action),
        guardian_sequence=1,
        requested_at=fixed_time,
    )
    decision = DeterministicPolicyEvaluator().evaluate(
        request,
        PolicyContext(
            guardian_mode=GuardianMode.NORMAL,
            guardian_sequence=1,
            granted_operations=frozenset({_ADAPTER_ID + "/messages.send"}),
            approved_action_hashes=frozenset({request.action_hash}),
            remaining_daily_budget_gbp=Decimal("1"),
        ),
        decision_id=record_id("decision", 1),
        decided_at=fixed_time,
    )
    return AuthorizedClientDelivery(
        message=message,
        destination_ref=destination_ref,
        attempt=1,
        idempotency_key="telegram:reply:message-1",
        authorization_request=request,
        policy_decision=decision,
        authorized_at=fixed_time,
    )


def test_config_requires_private_endpoint_and_exact_owner_only_token_file(
    tmp_path,
) -> None:
    with pytest.raises(ValidationError, match="private literal IP"):
        TelegramBotApiConfig(
            token_file=token_file(tmp_path),
            api_base_url="https://example.com",
        )
    with pytest.raises(ValidationError, match="canonical HTTPS origin"):
        TelegramBotApiConfig(
            token_file=token_file(tmp_path),
            api_base_url="http://api.telegram.org",
        )

    unsafe = token_file(tmp_path)
    unsafe.chmod(0o640)
    with pytest.raises(ValueError, match="exactly 0600"):
        TelegramBotApiUpdateSource(
            TelegramBotApiConfig(
                token_file=unsafe,
                api_base_url="http://127.0.0.1:9876",
            ),
            transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
        )


@pytest.mark.parametrize(
    ("api_base_url", "message"),
    [
        ("not-a-url", "HTTP or HTTPS"),
        ("http://owner:secret@127.0.0.1:9876", "cannot contain credentials"),
        ("https://api.telegram.org/custom", "canonical HTTPS origin"),
        ("http://169.254.1.1:9876", "private literal IP"),
    ],
)
def test_config_rejects_ambiguous_or_credential_bearing_origins(
    tmp_path,
    api_base_url: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        TelegramBotApiConfig(
            token_file=token_file(tmp_path),
            api_base_url=api_base_url,
        )


def test_token_and_pairing_secret_inputs_fail_closed(tmp_path) -> None:
    directory = tmp_path / "token-directory"
    directory.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        TelegramBotApiUpdateSource(
            TelegramBotApiConfig(
                token_file=directory,
                api_base_url="http://127.0.0.1:9876",
            )
        )

    oversized = tmp_path / "oversized-token"
    oversized.write_bytes(b"1:" + b"a" * 511)
    oversized.chmod(0o600)
    with pytest.raises(ValueError, match="too large"):
        TelegramBotApiUpdateSource(
            TelegramBotApiConfig(
                token_file=oversized,
                api_base_url="http://127.0.0.1:9876",
            )
        )

    implausible = tmp_path / "implausible-token"
    implausible.write_text("x" * 40, encoding="utf-8")
    implausible.chmod(0o600)
    with pytest.raises(ValueError, match="plausible token"):
        TelegramBotApiUpdateSource(
            TelegramBotApiConfig(
                token_file=implausible,
                api_base_url="http://127.0.0.1:9876",
            )
        )

    with pytest.raises(ValueError, match="at least 32 bytes"):
        EphemeralTelegramPairingCodeIssuer(secret=b"short")


def test_update_source_normalizes_text_and_rejectable_attachment_metadata(
    fixed_time,
    tmp_path,
) -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert request.url.path == f"/bot{_TOKEN}/getUpdates"
        timestamp = int(fixed_time.timestamp())
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {
                        "update_id": 10,
                        "message": {
                            "message_id": 50,
                            "from": {"id": 1001},
                            "chat": {"id": 1001, "type": "private"},
                            "date": timestamp,
                            "text": "/start",
                        },
                    },
                    {
                        "update_id": 11,
                        "message": {
                            "message_id": 51,
                            "from": {"id": 1001},
                            "chat": {"id": 1001, "type": "private"},
                            "date": timestamp,
                            "caption": "Keep the caption only.",
                            "photo": [
                                {
                                    "file_id": "small",
                                    "file_unique_id": "photo-small",
                                    "file_size": 10,
                                },
                                {
                                    "file_id": "large",
                                    "file_unique_id": "photo-large",
                                    "file_size": 20,
                                },
                            ],
                        },
                    },
                    {
                        "update_id": 12,
                        "message": {
                            "message_id": 52,
                            "from": {"id": 1001},
                            "chat": {"id": 1001, "type": "private"},
                            "date": timestamp,
                            "location": {"latitude": 1.0, "longitude": 2.0},
                        },
                    },
                ],
            },
        )

    source = TelegramBotApiUpdateSource(
        config(tmp_path),
        transport=httpx.MockTransport(handler),
        clock=lambda: fixed_time,
    )
    updates = source.poll(
        TelegramPollRequest(
            adapter_id=_ADAPTER_ID,
            offset=10,
            timeout_seconds=30,
            limit=25,
        )
    )

    assert tuple(update.update_id for update in updates) == (10, 11, 12)
    assert updates[0].message.chat_type is TelegramChatType.PRIVATE
    assert updates[0].message.text == "/start"
    assert updates[1].message.text == "Keep the caption only."
    assert updates[1].message.attachments[0].kind is TelegramAttachmentKind.PHOTO
    assert updates[1].message.attachments[0].file_id == "large"
    assert updates[2].message.text is None
    assert updates[2].message.attachments[0].kind is TelegramAttachmentKind.UNSUPPORTED
    assert requests == [
        {
            "offset": 10,
            "timeout": 30,
            "limit": 25,
            "allowed_updates": ["message"],
        }
    ]
    health = source.health()
    assert health["status"] == "healthy"
    assert _TOKEN not in json.dumps(health)


def test_poll_errors_are_redacted_and_classified_without_token_urls(tmp_path) -> None:
    def unauthorized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"ok": False, "error_code": 401, "description": _TOKEN},
        )

    request = TelegramPollRequest(
        adapter_id=_ADAPTER_ID,
        offset=0,
        timeout_seconds=1,
    )
    source = TelegramBotApiUpdateSource(
        config(tmp_path),
        transport=httpx.MockTransport(unauthorized),
    )
    with pytest.raises(PermanentTelegramPollingError) as captured:
        source.poll(request)
    assert captured.value.reason_code == "telegram.api.unauthorized"
    assert _TOKEN not in str(captured.value)
    assert _TOKEN not in repr(captured.value.__cause__)

    unavailable = TelegramBotApiUpdateSource(
        config(tmp_path),
        transport=httpx.MockTransport(lambda _request: httpx.Response(503, json={})),
    )
    with pytest.raises(TransientTelegramPollingError) as transient:
        unavailable.poll(request)
    assert transient.value.reason_code == "telegram.api.upstream_unavailable"


@pytest.mark.parametrize(
    ("status_code", "content", "error_type", "reason_code"),
    [
        (200, b"", PermanentTelegramPollingError, "telegram.api.invalid_response"),
        (
            200,
            b"not-json",
            PermanentTelegramPollingError,
            "telegram.api.invalid_response",
        ),
        (200, b"[]", PermanentTelegramPollingError, "telegram.api.invalid_response"),
        (
            200,
            b'{"ok": true}',
            PermanentTelegramPollingError,
            "telegram.api.invalid_response",
        ),
        (
            200,
            b'{"ok": false, "error_code": 429}',
            TransientTelegramPollingError,
            "telegram.api.rate_limited",
        ),
        (
            200,
            b'{"ok": false, "error_code": 400}',
            PermanentTelegramPollingError,
            "telegram.api.request_rejected",
        ),
        (
            400,
            b'{"ok": false, "error_code": 400}',
            PermanentTelegramPollingError,
            "telegram.api.request_rejected",
        ),
        (
            200,
            b"x" * 2_000_001,
            PermanentTelegramPollingError,
            "telegram.api.response_too_large",
        ),
    ],
)
def test_poll_rejects_malformed_rate_limited_and_oversized_responses(
    tmp_path,
    status_code: int,
    content: bytes,
    error_type: type[Exception],
    reason_code: str,
) -> None:
    source = TelegramBotApiUpdateSource(
        config(tmp_path),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status_code, content=content)
        ),
    )
    request = TelegramPollRequest(
        adapter_id=_ADAPTER_ID,
        offset=0,
        timeout_seconds=1,
    )

    with pytest.raises(error_type) as captured:
        source.poll(request)

    assert captured.value.reason_code == reason_code
    assert _TOKEN not in repr(captured.value.__cause__)


@pytest.mark.parametrize(
    ("transport_error", "reason_code"),
    [
        (httpx.ConnectError, "telegram.api.connection_failed"),
        (httpx.ReadTimeout, "telegram.api.outcome_unknown"),
        (httpx.ProxyError, "telegram.api.transport_failed"),
    ],
)
def test_poll_redacts_transport_exception_details(
    tmp_path,
    transport_error: type[httpx.HTTPError],
    reason_code: str,
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise transport_error(_TOKEN, request=request)

    source = TelegramBotApiUpdateSource(
        config(tmp_path),
        transport=httpx.MockTransport(fail),
    )
    request = TelegramPollRequest(
        adapter_id=_ADAPTER_ID,
        offset=0,
        timeout_seconds=1,
    )

    with pytest.raises(TransientTelegramPollingError) as captured:
        source.poll(request)

    assert captured.value.reason_code == reason_code
    assert _TOKEN not in str(captured.value)
    assert _TOKEN not in repr(captured.value.__cause__)


def test_pairing_code_and_challenge_publication_are_replay_stable(
    fixed_time,
    tmp_path,
) -> None:
    issuer = EphemeralTelegramPairingCodeIssuer(secret=b"a" * 32)
    candidate_id = record_id("tgcandidate", 1)
    code = issuer.issue(candidate_id)
    assert code == issuer.issue(candidate_id)
    assert len(code) >= 20
    durable_code = TelegramBotApiPairingCodeIssuer(config(tmp_path)).issue(candidate_id)
    assert durable_code == TelegramBotApiPairingCodeIssuer(config(tmp_path)).issue(candidate_id)
    assert _TOKEN not in durable_code
    candidate = TelegramPairingCandidate(
        candidate_id=candidate_id,
        owner_id=record_id("owner", 1),
        update_id=10,
        telegram_user_id=1001,
        telegram_chat_id=1001,
        confirmation_code_hash=sha256_digest(code.encode()),
        observed_at=fixed_time,
        expires_at=fixed_time + timedelta(minutes=10),
    )
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 70, "chat": {"id": 1001}},
            },
        )

    publisher = TelegramBotApiPairingChallengePublisher(
        config(tmp_path),
        transport=httpx.MockTransport(handler),
        clock=lambda: fixed_time,
    )
    challenge = TelegramPairingChallenge(candidate=candidate, confirmation_code=code)
    publisher.publish(challenge)
    publisher.publish(challenge)

    assert len(calls) == 1
    assert calls[0]["chat_id"] == 1001
    assert code in str(calls[0]["text"])


def test_client_adapter_sends_once_and_never_retries_an_ambiguous_outcome(
    fixed_time,
    tmp_path,
) -> None:
    owner_pairing = pairing(fixed_time)
    delivery = authorized_delivery(fixed_time, owner_pairing)
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {"message_id": 80, "chat": {"id": 1001}},
            },
        )

    adapter = TelegramBotApiClientAdapter(
        config(tmp_path),
        lambda pairing_id: owner_pairing
        if pairing_id == owner_pairing.pairing_id
        else pytest.fail("unexpected pairing"),
        transport=httpx.MockTransport(handler),
        clock=lambda: fixed_time,
        id_factory=lambda prefix: record_id(prefix, 1),
    )
    first = adapter.send(delivery)
    replay = adapter.send(delivery)
    retry = adapter.send(delivery.model_copy(update={"attempt": 2}))

    assert first == replay
    assert first.state is DeliveryState.SENT
    assert retry.adapter_metadata["deduplicated"] is True
    assert calls == [{"chat_id": 1001, "text": "A bounded reply."}]
    assert adapter.capabilities()["ambiguous_send_retries"] is False

    ambiguous = TelegramBotApiClientAdapter(
        config(tmp_path),
        lambda _pairing_id: owner_pairing,
        transport=httpx.MockTransport(lambda _request: httpx.Response(503, json={})),
        clock=lambda: fixed_time,
    )
    with pytest.raises(PermanentClientDeliveryError) as captured:
        ambiguous.send(delivery)
    assert captured.value.reason_code == "telegram.delivery.outcome_unknown"
    assert captured.value.retryable is False
