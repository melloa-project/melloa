from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from melloa.adapters.telegram import (
    TelegramBotClient,
    TelegramUpdate,
)
from melloa.apps.telegram_pairing import (
    TelegramPairingError,
    _matching_owner_id,
    _prepare_pairing_client,
    _read_bot_token,
    wait_for_telegram_owner,
)

_TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456"


def _response(result: object) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps({"ok": True, "result": result}).encode(),
        headers={"Content-Type": "application/json"},
    )


def _update(
    update_id: int,
    *,
    sender_id: int,
    chat_id: int,
    chat_type: str,
    text: str,
) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "from": {"id": sender_id, "is_bot": False},
            "chat": {"id": chat_id, "type": chat_type},
            "date": 1_777_000_000,
            "text": text,
        },
    }


def test_pairing_accepts_only_exact_private_self_chat_and_acknowledges_it() -> None:
    payloads: list[dict[str, object]] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        if payload.get("offset") == 43:
            return _response([])
        return _response(
            [
                _update(
                    40,
                    sender_id=111,
                    chat_id=111,
                    chat_type="private",
                    text="/start melloa_wrong",
                ),
                _update(
                    41,
                    sender_id=222,
                    chat_id=-333,
                    chat_type="group",
                    text="/start melloa_exact",
                ),
                _update(
                    42,
                    sender_id=5678,
                    chat_id=5678,
                    chat_type="private",
                    text="/start melloa_exact",
                ),
            ]
        )

    client = TelegramBotClient(_TOKEN, transport=httpx.MockTransport(respond))

    owner_id = asyncio.run(
        wait_for_telegram_owner(
            client,
            payload="melloa_exact",
            bot_username="melli_bot",
            wait_seconds=10,
        )
    )

    assert owner_id == 5678
    assert payloads[-1]["offset"] == 43


def test_pairing_advances_past_untrusted_backlog() -> None:
    offsets: list[int | None] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        offset = payload.get("offset")
        assert offset is None or isinstance(offset, int)
        offsets.append(offset)
        if offset is None:
            return _response(
                [
                    _update(
                        80,
                        sender_id=999,
                        chat_id=999,
                        chat_type="private",
                        text="noise",
                    )
                ]
            )
        if offset == 81:
            return _response(
                [
                    _update(
                        81,
                        sender_id=1234,
                        chat_id=1234,
                        chat_type="private",
                        text="/start@melli_bot melloa_exact",
                    )
                ]
            )
        return _response([])

    client = TelegramBotClient(_TOKEN, transport=httpx.MockTransport(respond))

    owner_id = asyncio.run(
        wait_for_telegram_owner(
            client,
            payload="melloa_exact",
            bot_username="melli_bot",
            wait_seconds=10,
        )
    )

    assert owner_id == 1234
    assert offsets == [None, 81, 82]


def test_matching_owner_rejects_different_private_sender_and_chat() -> None:
    update = TelegramUpdate.model_validate(
        _update(
            1,
            sender_id=1234,
            chat_id=5678,
            chat_type="private",
            text="/start melloa_exact",
        )
    )

    assert (
        _matching_owner_id(update, payload="melloa_exact", bot_username="melli_bot")
        is None
    )


def test_pairing_setup_removes_existing_webhook_once(capsys: pytest.CaptureFixture[str]) -> None:
    methods: list[str] = []
    payloads: list[dict[str, object]] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        methods.append(method)
        payloads.append(json.loads(request.content))
        if method == "getMe":
            return _response({"id": 99, "is_bot": True, "username": "melli_bot"})
        if method == "getWebhookInfo":
            webhook_url = (
                "https://example.invalid/melloa"
                if methods.count("getWebhookInfo") == 1
                else ""
            )
            return _response({"url": webhook_url})
        if method == "deleteWebhook":
            return _response(True)
        raise AssertionError(f"unexpected Telegram method {method}")

    client = TelegramBotClient(_TOKEN, transport=httpx.MockTransport(respond))

    identity = asyncio.run(_prepare_pairing_client(client))

    assert identity.username == "melli_bot"
    assert methods == ["getMe", "getWebhookInfo", "deleteWebhook", "getMe", "getWebhookInfo"]
    assert payloads[2] == {"drop_pending_updates": True}
    assert "removing it for this dedicated long-polling setup" in capsys.readouterr().err


def test_bot_token_file_must_be_private_regular_and_well_formed(tmp_path: Path) -> None:
    token_file = tmp_path / "telegram-token"
    token_file.write_text(f"{_TOKEN}\n", encoding="ascii")
    token_file.chmod(0o600)
    assert _read_bot_token(token_file) == _TOKEN

    token_file.chmod(0o644)
    with pytest.raises(TelegramPairingError, match="owner-only"):
        _read_bot_token(token_file)

    token_file.unlink()
    token_file.symlink_to(tmp_path / "missing")
    with pytest.raises(TelegramPairingError, match="regular file"):
        _read_bot_token(token_file)
