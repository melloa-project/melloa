from __future__ import annotations

import io
import json
import zipfile
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime

from fastapi.testclient import TestClient

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.apps.runtime import build_runtime
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from tests.conftest import record_id

_OWNER_CREDENTIAL = "owner-export-test-credential-value-0001"


def _ids() -> Callable[[str], str]:
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return record_id(prefix, counts[prefix])

    return create


def _guardian(observed_at: datetime) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="export-test-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=observed_at,
            reason_code="guardian.test",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def test_authenticated_owner_downloads_small_provider_independent_archive(fixed_time) -> None:
    runtime = build_runtime(
        _guardian(fixed_time),
        _OWNER_CREDENTIAL,
        clock=lambda: fixed_time,
        id_factory=_ids(),
    )
    with TestClient(runtime.app, base_url="https://testserver") as client:
        assert client.get("/api/v1/data-export").status_code == 401
        login = client.post(
            "/api/v1/auth/session",
            json={"credential": _OWNER_CREDENTIAL},
        )
        csrf = login.json()["csrf_token"]
        headers = {"X-Melloa-CSRF": csrf}
        created = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={
                "title": "A private plan",
                "sensitivity": "personal",
            },
        )
        assert created.status_code == 201
        thread_id = created.json()["thread_id"]
        accepted = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=headers,
            json={
                "text": "Remember the context, not this credential.",
                "idempotency_key": "export-message-1",
            },
        )
        assert accepted.status_code == 202

        readiness = client.get("/api/v1/data-export")
        assert readiness.status_code == 200
        assert [item["group"] for item in readiness.json()["coverage"]] == [
            "conversations",
            "messages-and-answers",
            "memories",
        ]
        assert readiness.json()["encrypted"] is False

        response = client.post("/api/v1/data-export/archive", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "melloa-owner-export-" in response.headers["content-disposition"]
    assert _OWNER_CREDENTIAL.encode() not in response.content

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "conversations.json",
            "memories.json",
        }
        manifest = json.loads(archive.read("manifest.json"))
        conversations = json.loads(archive.read("conversations.json"))
        memories = json.loads(archive.read("memories.json"))

    assert manifest["format"] == "melloa-owner-export-v1"
    assert {item["path"] for item in manifest["files"]} == {
        "conversations.json",
        "memories.json",
    }
    assert conversations["conversations"][0]["thread"]["title"] == "A private plan"
    assert conversations["conversations"][0]["messages"][0]["parts"][0]["text"].startswith(
        "Remember the context"
    )
    assert memories == {"memories": []}
