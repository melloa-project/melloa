from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from melloa.adapters.telegram import (
    TelegramAPIError,
    TelegramBotClient,
    TelegramOwnerConfig,
)

_TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456"


def _response(document: object, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def test_owner_config_requires_exact_positive_numeric_bindings() -> None:
    config = TelegramOwnerConfig(owner_user_id=1234, owner_chat_id=5678)
    assert config.poll_timeout_seconds == 20

    with pytest.raises(ValidationError):
        TelegramOwnerConfig(owner_user_id=0, owner_chat_id=5678)
    with pytest.raises(ValidationError):
        TelegramOwnerConfig.model_validate(
            {"owner_user_id": "1234", "owner_chat_id": 5678},
            strict=True,
        )


def test_preflight_requires_bot_identity_and_no_webhook() -> None:
    methods: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.url.path.rsplit("/", 1)[-1])
        if request.url.path.endswith("/getMe"):
            return _response(
                {
                    "ok": True,
                    "result": {"id": 99, "is_bot": True, "username": "melli_test_bot"},
                }
            )
        return _response({"ok": True, "result": {"url": ""}})

    client = TelegramBotClient(_TOKEN, transport=httpx.MockTransport(respond))

    identity = asyncio.run(client.verify_long_polling())

    assert identity.id == 99
    assert identity.username == "melli_test_bot"
    assert methods == ["getMe", "getWebhookInfo"]


def test_preflight_rejects_existing_webhook_without_mutating_it() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getMe"):
            return _response({"ok": True, "result": {"id": 99, "is_bot": True}})
        return _response(
            {"ok": True, "result": {"url": "https://example.invalid/melloa"}}
        )

    client = TelegramBotClient(_TOKEN, transport=httpx.MockTransport(respond))

    with pytest.raises(TelegramAPIError, match=r"telegram\.webhook_configured"):
        asyncio.run(client.verify_long_polling())


def test_poll_requests_only_messages_after_durable_offset() -> None:
    captured: dict[str, object] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _response(
            {
                "ok": True,
                "result": [
                    {
                        "update_id": 41,
                        "message": {
                            "message_id": 7,
                            "from": {"id": 1234, "is_bot": False, "first_name": "Owner"},
                            "chat": {"id": 5678, "type": "private", "first_name": "Owner"},
                            "date": 1_777_000_000,
                            "text": "Hello Melli",
                        },
                    }
                ],
            }
        )

    client = TelegramBotClient(_TOKEN, transport=httpx.MockTransport(respond))

    updates = asyncio.run(client.get_updates(offset=41, timeout_seconds=20))

    assert updates[0].message is not None
    assert updates[0].message.sender is not None
    assert updates[0].message.sender.id == 1234
    assert updates[0].message.text == "Hello Melli"
    assert captured == {
        "allowed_updates": ["message"],
        "limit": 100,
        "offset": 41,
        "timeout": 20,
    }


def test_send_protects_content_and_disables_link_previews() -> None:
    captured: dict[str, object] = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _response({"ok": True, "result": {"message_id": 808}})

    client = TelegramBotClient(_TOKEN, transport=httpx.MockTransport(respond))

    message_id = asyncio.run(
        client.send_text(
            chat_id=5678,
            text="Private reply",
            reply_to_message_id=707,
        )
    )

    assert message_id == 808
    assert captured == {
        "chat_id": 5678,
        "link_preview_options": {"is_disabled": True},
        "protect_content": True,
        "reply_parameters": {
            "allow_sending_without_reply": True,
            "message_id": 707,
        },
        "text": "Private reply",
    }


def test_errors_never_include_token_or_remote_description() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "ok": False,
                "error_code": 429,
                "description": f"secret URL contains {_TOKEN}",
                "parameters": {"retry_after": 17},
            },
            status_code=429,
        )

    client = TelegramBotClient(_TOKEN, transport=httpx.MockTransport(respond))

    with pytest.raises(TelegramAPIError) as raised:
        asyncio.run(client.get_updates(offset=None, timeout_seconds=1))

    assert raised.value.reason_code == "telegram.rate_limited"
    assert raised.value.retry_after_seconds == 17
    assert _TOKEN not in str(raised.value)
    assert "secret URL" not in str(raised.value)


def test_token_format_is_rejected_before_any_request() -> None:
    with pytest.raises(ValueError, match="invalid format"):
        TelegramBotClient("not-a-token")
