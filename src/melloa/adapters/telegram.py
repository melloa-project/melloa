"""Bounded Telegram Bot API transport for one private owner channel."""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Annotated, Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, ValidationError

_MAX_RESPONSE_BYTES = 2_000_000
_TELEGRAM_TEXT_LIMIT = 4_096
_TOKEN_PATTERN = re.compile(r"^[0-9]{6,20}:[A-Za-z0-9_-]{30,128}$")


class TelegramOwnerConfig(BaseModel):
    """Non-secret binding to one exact Telegram user and private chat."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    owner_user_id: Annotated[int, Field(gt=0, le=(1 << 63) - 1)]
    owner_chat_id: Annotated[int, Field(gt=0, le=(1 << 63) - 1)]
    poll_timeout_seconds: Annotated[int, Field(ge=1, le=50)] = 20


class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    id: Annotated[int, Field(gt=0)]
    is_bot: bool
    username: str | None = None


class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    id: int
    type: str


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    message_id: Annotated[int, Field(ge=0)]
    sender: TelegramUser | None = Field(default=None, alias="from")
    chat: TelegramChat
    date: Annotated[int, Field(ge=0)]
    text: str | None = None


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    update_id: Annotated[int, Field(ge=0)]
    message: TelegramMessage | None = None


class TelegramBotIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    id: Annotated[int, Field(gt=0)]
    is_bot: bool
    username: str | None = None


class TelegramAPIError(RuntimeError):
    """Redacted Telegram failure safe for ordinary logs."""

    def __init__(self, reason_code: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.retry_after_seconds = retry_after_seconds


class TelegramBotClient:
    """Small async client that never exposes the bot token in an error message."""

    def __init__(
        self,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        api_origin: str = "https://api.telegram.org",
    ) -> None:
        if _TOKEN_PATTERN.fullmatch(token) is None:
            raise ValueError("Telegram bot token has an invalid format")
        if api_origin != "https://api.telegram.org":
            raise ValueError("Telegram Bot API origin is fixed")
        self._token = SecretStr(token)
        self._transport = transport
        self._api_origin = api_origin

    async def verify_long_polling(self) -> TelegramBotIdentity:
        identity_document = await self._request("getMe", {})
        try:
            identity = TelegramBotIdentity.model_validate(identity_document)
        except ValidationError as error:
            raise TelegramAPIError("telegram.identity_invalid") from error
        if not identity.is_bot:
            raise TelegramAPIError("telegram.identity_not_bot")

        webhook = await self._request("getWebhookInfo", {})
        if not isinstance(webhook, dict) or not isinstance(webhook.get("url"), str):
            raise TelegramAPIError("telegram.webhook_status_invalid")
        if webhook["url"]:
            raise TelegramAPIError("telegram.webhook_configured")
        return identity

    async def verify_private_chat(self, chat_id: int) -> TelegramChat:
        if chat_id <= 0:
            raise ValueError("Telegram private chat ID must be positive")
        chat_document = await self._request("getChat", {"chat_id": chat_id})
        try:
            chat = TelegramChat.model_validate(chat_document)
        except ValidationError as error:
            raise TelegramAPIError("telegram.owner_chat_invalid") from error
        if chat.id != chat_id or chat.type != "private":
            raise TelegramAPIError("telegram.owner_chat_invalid")
        return chat

    async def get_updates(
        self,
        *,
        offset: int | None,
        timeout_seconds: int,
    ) -> tuple[TelegramUpdate, ...]:
        if offset is not None and offset < 0:
            raise ValueError("Telegram update offset cannot be negative")
        if not 1 <= timeout_seconds <= 50:
            raise ValueError("Telegram poll timeout must be between 1 and 50 seconds")
        payload: dict[str, object] = {
            "timeout": timeout_seconds,
            "limit": 100,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = await self._request(
            "getUpdates",
            payload,
            timeout_seconds=timeout_seconds + 5,
        )
        try:
            updates = TypeAdapter(list[TelegramUpdate]).validate_python(result, strict=True)
        except ValidationError as error:
            raise TelegramAPIError("telegram.updates_invalid") from error
        if any(
            previous.update_id >= current.update_id
            for previous, current in pairwise(updates)
        ):
            raise TelegramAPIError("telegram.updates_out_of_order")
        return tuple(updates)

    async def send_text(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> int:
        if chat_id <= 0:
            raise ValueError("Telegram private chat ID must be positive")
        if not 1 <= len(text) <= _TELEGRAM_TEXT_LIMIT:
            raise ValueError("Telegram text must contain between 1 and 4096 characters")
        if reply_to_message_id is not None and reply_to_message_id < 0:
            raise ValueError("Telegram reply message ID cannot be negative")
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": text,
            "protect_content": True,
            "link_preview_options": {"is_disabled": True},
        }
        if reply_to_message_id is not None:
            payload["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
        result = await self._request(
            "sendMessage",
            payload,
        )
        if not isinstance(result, dict):
            raise TelegramAPIError("telegram.send_result_invalid")
        message_id = result.get("message_id")
        if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id < 0:
            raise TelegramAPIError("telegram.send_result_invalid")
        return message_id

    async def _request(
        self,
        method: str,
        payload: dict[str, object],
        *,
        timeout_seconds: int = 10,
    ) -> Any:
        token = self._token.get_secret_value()
        endpoint = f"{self._api_origin}/bot{token}/{method}"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5)),
                follow_redirects=False,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.post(
                    endpoint,
                    headers={"Accept": "application/json"},
                    json=payload,
                )
        except Exception:
            raise TelegramAPIError("telegram.transport_failed") from None
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise TelegramAPIError("telegram.response_too_large")
        try:
            document = response.json()
        except ValueError:
            raise TelegramAPIError("telegram.response_invalid") from None
        if not isinstance(document, dict):
            raise TelegramAPIError("telegram.response_invalid")
        if response.status_code >= 400 or document.get("ok") is not True:
            retry_after = _retry_after(document)
            reason = (
                "telegram.rate_limited"
                if response.status_code == 429
                else "telegram.api_rejected"
            )
            raise TelegramAPIError(reason, retry_after_seconds=retry_after)
        if "result" not in document:
            raise TelegramAPIError("telegram.response_invalid")
        return document["result"]


def _retry_after(document: dict[str, object]) -> int | None:
    parameters = document.get("parameters")
    if not isinstance(parameters, dict):
        return None
    value = parameters.get("retry_after")
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 86_400:
        return None
    return value


__all__ = [
    "TelegramAPIError",
    "TelegramBotClient",
    "TelegramBotIdentity",
    "TelegramMessage",
    "TelegramOwnerConfig",
    "TelegramUpdate",
]
