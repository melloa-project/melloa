"""One-time, exact-message discovery of the private Telegram owner ID."""

from __future__ import annotations

import argparse
import asyncio
import math
import re
import secrets
import stat
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from melloa.adapters.telegram import (
    TelegramAPIError,
    TelegramBotClient,
    TelegramBotIdentity,
    TelegramUpdate,
)

_MAX_TOKEN_FILE_BYTES = 512
_PAIRING_PAYLOAD_PREFIX = "melloa_"
_TOKEN_PATTERN = re.compile(r"^[0-9]{6,20}:[A-Za-z0-9_-]{30,128}$")


class TelegramPairingError(RuntimeError):
    """Redacted setup failure safe to show to the operator."""


def _read_bot_token(path: Path) -> str:
    try:
        metadata = path.lstat()
    except OSError:
        raise TelegramPairingError("the bot-token file is unavailable") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise TelegramPairingError("the bot token must be a regular file, not a symlink")
    if metadata.st_mode & 0o077:
        raise TelegramPairingError("the bot-token file must be owner-only (mode 0600 or 0400)")
    if not 1 <= metadata.st_size <= _MAX_TOKEN_FILE_BYTES:
        raise TelegramPairingError("the bot-token file has an invalid size")
    try:
        raw_token = path.read_bytes().rstrip(b"\n")
        token = raw_token.decode("ascii")
    except (OSError, UnicodeDecodeError):
        raise TelegramPairingError("the bot-token file could not be read safely") from None
    if b"\n" in raw_token or b"\r" in raw_token or _TOKEN_PATTERN.fullmatch(token) is None:
        raise TelegramPairingError("the bot token has an invalid format")
    return token


def _pairing_payload() -> str:
    payload = f"{_PAIRING_PAYLOAD_PREFIX}{secrets.token_urlsafe(24)}"
    if len(payload) > 64 or re.fullmatch(r"[A-Za-z0-9_-]+", payload) is None:
        raise AssertionError("generated Telegram pairing payload is invalid")
    return payload


def _matching_owner_id(
    update: TelegramUpdate,
    *,
    payload: str,
    bot_username: str | None,
) -> int | None:
    message = update.message
    if message is None or message.sender is None or message.text is None:
        return None
    commands = {f"/start {payload}"}
    if bot_username:
        commands.add(f"/start@{bot_username} {payload}")
    if (
        message.text.strip() not in commands
        or message.sender.is_bot
        or message.chat.type != "private"
        or message.sender.id != message.chat.id
    ):
        return None
    return message.sender.id


async def wait_for_telegram_owner(
    client: TelegramBotClient,
    *,
    payload: str,
    bot_username: str | None,
    wait_seconds: int,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Wait for the exact nonce in one-to-one chat and consume only through that update."""

    if not 1 <= wait_seconds <= 900:
        raise ValueError("Telegram pairing wait must be between 1 and 900 seconds")
    deadline = monotonic() + wait_seconds
    offset: int | None = None
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TelegramPairingError("timed out before the private pairing phrase arrived")
        updates = await client.get_updates(
            offset=offset,
            timeout_seconds=min(20, max(1, math.ceil(remaining))),
        )
        for update in updates:
            owner_id = _matching_owner_id(
                update,
                payload=payload,
                bot_username=bot_username,
            )
            if owner_id is None:
                continue
            # Confirm the pairing update so it cannot become the owner's first
            # conversation after activation. Later updates remain pending.
            await client.get_updates(offset=update.update_id + 1, timeout_seconds=1)
            return owner_id
        if updates:
            # Before an owner is bound, unrelated updates have no authority and
            # are deliberately discarded so a noisy public bot cannot starve pairing.
            offset = updates[-1].update_id + 1


def _wait_seconds(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if not 1 <= parsed <= 900:
        raise argparse.ArgumentTypeError("must be between 1 and 900")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Discover the numeric owner ID from one exact message in the bot's private chat. "
            "Only the owner ID is written to stdout."
        )
    )
    parser.add_argument("--bot-token-file", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=_wait_seconds, default=300)
    return parser


def _pairing_target(identity: TelegramBotIdentity) -> str:
    return f"@{identity.username}" if identity.username else f"bot ID {identity.id}"


async def _run_pairing(token: str, *, wait_seconds: int) -> int:
    client = TelegramBotClient(token)
    identity = await client.verify_long_polling()
    payload = _pairing_payload()
    print(
        f"Telegram {_pairing_target(identity)} is ready for long polling.\n"
        "Open its private chat and send exactly:\n\n"
        f"  /start {payload}\n\n"
        f"Waiting up to {wait_seconds} seconds…",
        file=sys.stderr,
        flush=True,
    )
    owner_id = await wait_for_telegram_owner(
        client,
        payload=payload,
        bot_username=identity.username,
        wait_seconds=wait_seconds,
    )
    print("Exact private owner chat verified.", file=sys.stderr, flush=True)
    return owner_id


def _api_failure_message(error: TelegramAPIError) -> str:
    messages = {
        "telegram.webhook_configured": (
            "the bot has a webhook configured; remove it before selecting long polling"
        ),
        "telegram.transport_failed": "Telegram could not be reached",
        "telegram.rate_limited": "Telegram rate-limited the pairing request; retry later",
        "telegram.api_rejected": "Telegram rejected the bot token or pairing request",
    }
    return messages.get(error.reason_code, "Telegram returned an invalid pairing response")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        token = _read_bot_token(args.bot_token_file)
        owner_id = asyncio.run(_run_pairing(token, wait_seconds=args.wait_seconds))
    except TelegramPairingError as error:
        print(f"Telegram pairing failed: {error}", file=sys.stderr)
        return 1
    except TelegramAPIError as error:
        print(f"Telegram pairing failed: {_api_failure_message(error)}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Telegram pairing cancelled.", file=sys.stderr)
        return 130
    print(owner_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
