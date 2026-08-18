"""Authenticated real-route journey using a test-only loopback protocol fixture.

The fixture proves Melloa's actual OpenAI-compatible HTTP boundary. Its canned
text is test evidence only and must never be presented as a real Melli example.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from fastapi.testclient import TestClient

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.models.openai_compatible import OpenAICompatibleRouteConfig
from melloa.apps.mvp import build_mvp_runtime
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload

_MODEL_ID = "qwen-test-only"
_OWNER_CREDENTIAL = "owner-bootstrap-credential-for-real-route-smoke"
_FIXTURE_REPLY = "Test-only protocol fixture response."


@dataclass
class _ProtocolState:
    lock: threading.RLock = field(default_factory=threading.RLock)
    completion_requests: list[dict[str, Any]] = field(default_factory=list)
    fail_next_completion: bool = False

    def record_completion(self, payload: dict[str, Any]) -> bool:
        with self.lock:
            self.completion_requests.append(payload)
            should_fail = self.fail_next_completion
            self.fail_next_completion = False
            return should_fail

    def fail_once(self) -> None:
        with self.lock:
            self.fail_next_completion = True

    def requests(self) -> tuple[dict[str, Any], ...]:
        with self.lock:
            return tuple(self.completion_requests)


def _handler(state: _ProtocolState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/v1/models":
                self.send_error(404)
                return
            self._send_json(
                {
                    "object": "list",
                    "data": [{"id": _MODEL_ID, "object": "model"}],
                }
            )

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            document = json.loads(self.rfile.read(content_length))
            assert isinstance(document, dict)
            should_fail = state.record_completion(document)
            content = (
                "not a structured completion"
                if should_fail
                else json.dumps({"text": _FIXTURE_REPLY, "citation_ids": []})
            )
            self._send_json(
                {
                    "choices": [{"message": {"content": content}}],
                    "usage": {"prompt_tokens": 37, "completion_tokens": 9},
                }
            )

        def _send_json(self, document: dict[str, Any]) -> None:
            body = json.dumps(document).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


@contextmanager
def _test_only_model_endpoint() -> Iterator[tuple[str, _ProtocolState]]:
    state = _ProtocolState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _create_thread(client: TestClient, csrf: str) -> str:
    response = client.post(
        "/api/v1/conversations",
        headers={"X-Melloa-CSRF": csrf},
        json={
            "title": "Real route proof",
            "sensitivity": "personal",
            "retention_policy": "retention.owner-conversation",
        },
    )
    assert response.status_code == 201
    return str(response.json()["thread_id"])


def _send_message(client: TestClient, csrf: str, thread_id: str, number: int):
    return client.post(
        f"/api/v1/conversations/{thread_id}/messages",
        headers={"X-Melloa-CSRF": csrf},
        json={
            "text": "Help me choose one concrete next step.",
            "idempotency_key": f"browser:real-route-smoke:{number}",
        },
    )


def test_authenticated_owner_uses_real_http_route_and_sees_honest_fallback(
    fixed_time,
) -> None:
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="test-only-guardian",
            mode=GuardianMode.OFFLINE,
            sequence=2,
            changed_at=fixed_time,
            reason_code="guardian.test-only-real-route-smoke",
            previous_receipt_hash="sha256:" + "0" * 64,
        ),
        receipt_hash="sha256:" + "1" * 64,
    )

    with _test_only_model_endpoint() as (base_url, protocol):
        config = OpenAICompatibleRouteConfig(
            route_id="model.local.test-only",
            display_name="Test-only loopback model fixture",
            provider_id="provider.test-only-loopback",
            model_id=_MODEL_ID,
            base_url=base_url,
            processing_location="device",
            reliability=1.0,
        )
        runtime = build_mvp_runtime(
            guardian,
            _OWNER_CREDENTIAL,
            route_configs=(config,),
            clock=lambda: fixed_time,
        )

        with TestClient(runtime.app, base_url="https://testserver") as client:
            assert client.get("/api/v1/providers/routes").status_code == 401
            login = client.post(
                "/api/v1/auth/session",
                json={"credential": _OWNER_CREDENTIAL},
            )
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]

            route_report = client.get("/api/v1/providers/routes")
            assert route_report.status_code == 200
            routes = {item["route_id"]: item for item in route_report.json()["routes"]}
            real_route = routes[config.route_id]
            assert real_route["model_id"] == _MODEL_ID
            assert real_route["processing_location"] == "device"
            assert real_route["external_disclosure"] is False
            assert real_route["health"] == {
                "state": "healthy",
                "checked_at": fixed_time.isoformat().replace("+00:00", "Z"),
                "latency_ms": real_route["health"]["latency_ms"],
                "reason_code": "model.endpoint_ready",
            }
            assert "model.fake.deterministic" in routes

            thread_id = _create_thread(client, csrf)
            real_reply = _send_message(client, csrf, thread_id, 1)
            assert real_reply.status_code == 200
            assert real_reply.json()["output_message"]["parts"][0]["text"] == _FIXTURE_REPLY
            real_turn_id = real_reply.json()["turn"]["turn_id"]
            real_inspection = client.get(
                f"/api/v1/conversations/{thread_id}/turns/{real_turn_id}"
            ).json()
            real_result = real_inspection["model_result"]
            assert real_result["route_id"] == config.route_id
            assert real_result["provider_id"] == config.provider_id
            assert real_result["model_id"] == _MODEL_ID
            assert real_result["input_tokens"] == 37
            assert real_result["output_tokens"] == 9
            assert real_result["cost_gbp"] == 0.0
            assert real_result["external_disclosure"] is False
            assert [attempt["route_id"] for attempt in real_result["attempts"]] == [
                config.route_id
            ]
            assert real_inspection["retrieval_manifest"]["manifest_id"] == (
                real_inspection["turn"]["retrieval_manifest_id"]
            )

            protocol.fail_once()
            fallback_reply = _send_message(client, csrf, thread_id, 2)
            assert fallback_reply.status_code == 200
            fallback_text = fallback_reply.json()["output_message"]["parts"][0]["text"]
            assert fallback_text.startswith("Synthetic local reply.")
            assert _FIXTURE_REPLY not in fallback_text
            fallback_turn_id = fallback_reply.json()["turn"]["turn_id"]
            fallback_result = client.get(
                f"/api/v1/conversations/{thread_id}/turns/{fallback_turn_id}"
            ).json()["model_result"]
            assert fallback_result["route_id"] == "model.fake.deterministic"
            assert [attempt["route_id"] for attempt in fallback_result["attempts"]] == [
                config.route_id,
                "model.fake.deterministic",
            ]
            assert [attempt["outcome"] for attempt in fallback_result["attempts"]] == [
                "failed",
                "succeeded",
            ]
            assert fallback_result["external_disclosure"] is False

        requests = protocol.requests()
        assert len(requests) == 2
        assert all(request["model"] == _MODEL_ID for request in requests)
        assert all(request["response_format"] == {"type": "json_object"} for request in requests)
        assert all(request["messages"][0]["role"] == "system" for request in requests)
        assert all(request["messages"][1]["role"] == "user" for request in requests)
