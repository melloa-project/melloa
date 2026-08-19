from __future__ import annotations

import io
import json
import os
import zipfile
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.postgres.memory import PostgresMemoryRepository
from melloa.apps.runtime import OWNER_ID, build_runtime
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import Assertion, AssertionStatus

_OWNER_CREDENTIAL = "postgres-owner-test-credential-value-0001"
_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _ids() -> Callable[[str], str]:
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return f"{prefix}_{counts[prefix]:032x}"

    return create


def _guardian() -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="postgres-test-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=_NOW,
            reason_code="guardian.test",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def _connect(dsn: str) -> psycopg.Connection[tuple[object, ...]]:
    connection: psycopg.Connection[tuple[object, ...]] = psycopg.connect(
        dsn,
        autocommit=True,
    )
    connection.execute("SET ROLE melloa_core")
    return connection


def test_owner_history_session_memory_and_export_survive_restart() -> None:
    dsn = os.environ["MELLOA_TEST_DATABASE_DSN"]
    id_factory = _ids()

    with _connect(dsn) as first_connection:
        first_runtime = build_runtime(
            _guardian(),
            _OWNER_CREDENTIAL,
            database_connection=first_connection,
            clock=lambda: _NOW,
            id_factory=id_factory,
            secure_session_cookie=False,
            access_scope="loopback",
        )
        with TestClient(first_runtime.app) as first_client:
            login = first_client.post(
                "/api/v1/auth/session",
                json={"credential": _OWNER_CREDENTIAL},
            )
            assert login.status_code == 200
            csrf = login.json()["csrf_token"]
            session_cookie = first_client.cookies["__Host-melloa_session"]
            headers = {"X-Melloa-CSRF": csrf}

            created = first_client.post(
                "/api/v1/conversations",
                headers=headers,
                json={
                    "title": "Durable owner context",
                    "sensitivity": "personal",
                    "retention_policy": "retention.owner-conversation",
                },
            )
            assert created.status_code == 201
            thread_id = created.json()["thread_id"]
            accepted = first_client.post(
                f"/api/v1/conversations/{thread_id}/messages",
                headers=headers,
                json={
                    "text": "This must survive a process restart.",
                    "idempotency_key": "postgres-message-1",
                },
            )
            assert accepted.status_code == 202

        assertion = Assertion(
            assertion_id=id_factory("assertion"),
            subject_id=OWNER_ID,
            predicate="preference.test",
            value={"statement": "Use durable context."},
            epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
            status=AssertionStatus.CONFIRMED,
            confidence=1.0,
            source_authority=TrustLabel.OWNER_AUTHORED,
            sensitivity=Sensitivity.PERSONAL,
            observed_at=_NOW,
        )
        first_connection.execute(
            "SELECT melloa.append_assertion(%s, %s, %s, %s)",
            (
                Jsonb(assertion.model_dump(mode="json")),
                "memory.assertion-owner-lifecycle",
                _NOW,
                None,
            ),
        )

    with _connect(dsn) as second_connection:
        second_runtime = build_runtime(
            _guardian(),
            _OWNER_CREDENTIAL,
            database_connection=second_connection,
            clock=lambda: _NOW,
            id_factory=id_factory,
            secure_session_cookie=False,
            access_scope="loopback",
        )
        with TestClient(second_runtime.app) as second_client:
            second_client.cookies.set("__Host-melloa_session", session_cookie)
            current = second_client.get("/api/v1/auth/session")
            assert current.status_code == 200
            assert current.json()["owner_id"] == OWNER_ID

            transcript = second_client.get(
                f"/api/v1/conversations/{thread_id}/transcript"
            )
            assert transcript.status_code == 200
            assert transcript.json()["messages"][0]["parts"][0]["text"] == (
                "This must survive a process restart."
            )

            archive = second_client.post(
                "/api/v1/data-export/archive",
                headers={"X-Melloa-CSRF": csrf},
            )
            assert archive.status_code == 200

        memories = PostgresMemoryRepository(second_connection).list_assertions(OWNER_ID)
        assert memories == (assertion,)
        audit_count = second_connection.execute(
            "SELECT count(*) FROM melloa.audit_events"
        ).fetchone()
        assert audit_count is not None and audit_count[0] >= 1

    with zipfile.ZipFile(io.BytesIO(archive.content)) as exported:
        conversations = json.loads(exported.read("conversations.json"))
        memories_document = json.loads(exported.read("memories.json"))
    assert conversations["conversations"][0]["thread"]["title"] == "Durable owner context"
    assert memories_document["memories"][0]["value"] == {
        "statement": "Use durable context."
    }
