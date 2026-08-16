from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from fastapi.testclient import TestClient

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.telegram import TelegramBotApiConfig
from melloa.apps.mvp import build_mvp_runtime
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload

_TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_ABCDEFGH"


@dataclass
class _BotApiState:
    lock: threading.RLock = field(default_factory=threading.RLock)
    updates: list[dict[str, Any]] = field(default_factory=list)
    sent_messages: list[dict[str, Any]] = field(default_factory=list)

    def add_update(self, update: dict[str, Any]) -> None:
        with self.lock:
            self.updates.append(update)

    def poll(self, offset: int, limit: int) -> list[dict[str, Any]]:
        with self.lock:
            return [item for item in self.updates if item["update_id"] >= offset][:limit]

    def send(self, payload: dict[str, Any]) -> int:
        with self.lock:
            self.sent_messages.append(payload)
            return 100 + len(self.sent_messages)

    def sent(self) -> tuple[dict[str, Any], ...]:
        with self.lock:
            return tuple(self.sent_messages)


def _handler(state: _BotApiState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length))
            method = self.path.rsplit("/", 1)[-1]
            if self.path != f"/bot{_TOKEN}/{method}":
                self.send_error(404)
                return
            if method == "getUpdates":
                result: object = state.poll(
                    int(payload["offset"]),
                    int(payload["limit"]),
                )
            elif method == "sendMessage":
                message_id = state.send(payload)
                result = {
                    "message_id": message_id,
                    "chat": {"id": payload["chat_id"], "type": "private"},
                    "date": int(time.time()),
                    "text": payload["text"],
                }
            else:
                self.send_error(404)
                return
            body = json.dumps({"ok": True, "result": result}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


@contextmanager
def _mock_bot_api() -> Iterator[tuple[str, _BotApiState]]:
    state = _BotApiState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _wait_for(probe, *, timeout: float = 8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("timed out waiting for Telegram MVP state")


def _message(update_id: int, text: str) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 50 + update_id,
            "from": {"id": 1001, "is_bot": False, "first_name": "Owner"},
            "chat": {"id": 1001, "type": "private", "first_name": "Owner"},
            "date": int(time.time()),
            "text": text,
        },
    }


def test_mocked_bot_api_completes_pairing_conversation_and_reply(
    fixed_time,
    tmp_path,
) -> None:
    token_path = tmp_path / "telegram-token"
    token_path.write_text(_TOKEN, encoding="utf-8")
    token_path.chmod(0o600)
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.telegram-smoke",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    owner_credential = "owner-bootstrap-credential-for-telegram-smoke"

    with _mock_bot_api() as (api_base_url, bot):
        bot.add_update(_message(1, "/start"))
        runtime = build_mvp_runtime(
            guardian,
            owner_credential,
            telegram_config=TelegramBotApiConfig(
                token_file=token_path,
                api_base_url=api_base_url,
            ),
            telegram_worker_interval=0.01,
        )
        with TestClient(runtime.app, base_url="https://testserver") as client:
            login = client.post(
                "/api/v1/auth/session",
                json={"credential": owner_credential},
            )
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]

            candidates = _wait_for(
                lambda: client.get(
                    "/api/v1/integrations/telegram/pairing/candidates"
                ).json()
                or None
            )
            challenge = _wait_for(lambda: bot.sent() or None)[0]
            code_match = re.search(r"Confirmation code: ([A-Za-z0-9_-]+)", challenge["text"])
            assert code_match is not None
            confirmed = client.post(
                "/api/v1/integrations/telegram/pairing/candidates/"
                f"{candidates[0]['candidate_id']}/confirm",
                headers={"X-Melloa-CSRF": csrf},
                json={"confirmation_code": code_match.group(1)},
            )
            assert confirmed.status_code == 200

            time.sleep(1.05)
            bot.add_update(_message(2, "Reply through the canonical model gateway."))

            sent = _wait_for(lambda: bot.sent() if len(bot.sent()) >= 2 else None)
            assert sent[1]["chat_id"] == 1001
            assert str(sent[1]["text"]).startswith("Synthetic local reply.")

            messages = client.get(
                f"/api/v1/conversations/{runtime.telegram_thread_id}/messages"
            )
            assert messages.status_code == 200
            telegram_messages = messages.json()
            assert telegram_messages[-2]["source_client"] == "client.telegram.bot-api"
            assert telegram_messages[-1]["reply_to_message_id"] == telegram_messages[-2][
                "message_id"
            ]

            deliveries = client.get(
                f"/api/v1/conversations/{runtime.telegram_thread_id}/deliveries"
            )
            assert deliveries.status_code == 200
            assert deliveries.json()[0]["state"] == "completed"
            assert deliveries.json()[0]["client_adapter"] == "client.telegram.bot-api"
            assert deliveries.json()[0]["destination_ref"].startswith(
                "telegram:pairing:tgpairing_"
            )

            status = client.get("/api/v1/integrations/telegram/status")
            assert status.status_code == 200
            channel = status.json()
            assert channel["configured"] is True
            assert channel["polling"]["source"]["network"] is True
            assert channel["replies"]["deliveries_submitted"] == 1
            assert _TOKEN not in status.text
