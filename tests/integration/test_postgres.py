from __future__ import annotations

import io
import json
import os
import zipfile
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.postgres.conversation import PostgresConversationStore
from melloa.adapters.postgres.memory import PostgresMemoryRepository
from melloa.application.conversation import ConversationService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.runtime import MELLI_ID, OWNER_ID, build_runtime
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import JsonObject
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import Assertion, AssertionStatus
from melloa.domain.models import ModelRequest, ProcessingLocation
from melloa.ports.model import ModelInvocationError

_OWNER_CREDENTIAL = "postgres-owner-test-credential-value-0001"
_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def _ids(start: int = 0) -> Callable[[str], str]:
    counts: defaultdict[str, int] = defaultdict(lambda: start)

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
            original_message_id = accepted.json()["inbound_message"]["message_id"]
            corrected = first_client.post(
                f"/api/v1/conversations/{thread_id}/messages/"
                f"{original_message_id}/correction",
                headers=headers,
                json={
                    "text": "This correction must survive a process restart.",
                    "idempotency_key": "postgres-message-correction-1",
                },
            )
            assert corrected.status_code == 202
            corrected_message_id = corrected.json()["inbound_message"]["message_id"]
            assert corrected.json()["inbound_message"]["corrects_message_id"] == (
                original_message_id
            )

        original_work_state = first_connection.execute(
            """
            SELECT state
              FROM melloa.jobs_outbox
             WHERE work_type = 'conversation.owner_reply'
               AND payload ->> 'message_id' = %s
            """,
            (original_message_id,),
        ).fetchone()
        assert original_work_state == ("cancelled",)

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
            transcript_messages = transcript.json()["messages"]
            assert [message["parts"][0]["text"] for message in transcript_messages] == [
                "This must survive a process restart.",
                "This correction must survive a process restart.",
            ]
            assert transcript_messages[1]["message_id"] == corrected_message_id
            assert transcript_messages[1]["corrects_message_id"] == original_message_id

            archive = second_client.post(
                "/api/v1/data-export/archive",
                headers={"X-Melloa-CSRF": csrf},
            )
            assert archive.status_code == 200

            deleted = second_client.delete(
                f"/api/v1/conversations/{thread_id}",
                headers={"X-Melloa-CSRF": csrf},
            )
            assert deleted.status_code == 200
            assert deleted.json()["active_data_deleted"] is True
            assert (
                second_client.get(
                    f"/api/v1/conversations/{thread_id}/transcript"
                ).status_code
                == 404
            )
            archive_after_deletion = second_client.post(
                "/api/v1/data-export/archive",
                headers={"X-Melloa-CSRF": csrf},
            )
            assert archive_after_deletion.status_code == 200

        memories = PostgresMemoryRepository(second_connection).list_assertions(OWNER_ID)
        assert memories == (assertion,)
        audit_count = second_connection.execute(
            "SELECT count(*) FROM melloa.audit_events"
        ).fetchone()
        assert audit_count is not None and audit_count[0] >= 1
        active_conversation_count = second_connection.execute(
            "SELECT count(*) FROM melloa.conversation_threads WHERE thread_id = %s",
            (thread_id,),
        ).fetchone()
        assert active_conversation_count == (0,)
        active_message_count = second_connection.execute(
            "SELECT count(*) FROM melloa.conversation_messages WHERE thread_id = %s",
            (thread_id,),
        ).fetchone()
        assert active_message_count == (0,)
        deletion_count = second_connection.execute(
            "SELECT count(*) FROM melloa.conversation_deletions WHERE thread_id = %s",
            (thread_id,),
        ).fetchone()
        assert deletion_count == (1,)
        cancelled_work_count = second_connection.execute(
            """
            SELECT count(*)
              FROM melloa.jobs_outbox
             WHERE work_type = 'conversation.owner_reply'
               AND payload ->> 'thread_id' = %s
               AND state = 'cancelled'
            """,
            (thread_id,),
        ).fetchone()
        assert cancelled_work_count == (2,)

    with zipfile.ZipFile(io.BytesIO(archive.content)) as exported:
        conversations = json.loads(exported.read("conversations.json"))
        memories_document = json.loads(exported.read("memories.json"))
    assert conversations["conversations"][0]["thread"]["title"] == "Durable owner context"
    assert conversations["conversations"][0]["messages"][1]["corrects_message_id"] == (
        original_message_id
    )
    assert memories_document["assertions"][0]["assertion"]["value"] == {
        "statement": "Use durable context."
    }
    assert memories_document["assertions"][0]["current_state"]["version"] == 1
    with zipfile.ZipFile(io.BytesIO(archive_after_deletion.content)) as exported:
        conversations_after_deletion = json.loads(exported.read("conversations.json"))
    assert conversations_after_deletion["conversations"] == []


def test_failed_external_destination_and_disclosed_memory_survive_restart() -> None:
    dsn = os.environ["MELLOA_TEST_DATABASE_DSN"]
    id_factory = _ids(100)

    with _connect(dsn) as first_connection:
        runtime = build_runtime(
            _guardian(),
            _OWNER_CREDENTIAL,
            database_connection=first_connection,
            clock=lambda: _NOW,
            id_factory=id_factory,
            secure_session_cookie=False,
            access_scope="loopback",
        )
        memory = Assertion(
            assertion_id=id_factory("assertion"),
            subject_id=OWNER_ID,
            predicate="preference.failed-external-test",
            value={"statement": "Use this durable context."},
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
                Jsonb(memory.model_dump(mode="json")),
                "memory.assertion-owner-lifecycle",
                _NOW,
                None,
            ),
        )

        def fail_external(_request: ModelRequest) -> JsonObject:
            raise ModelInvocationError(
                provider_id="provider.postgres-approved",
                model_id="durable-external-v1",
                processing_location=ProcessingLocation.APPROVED_PROVIDER,
            )

        service = ConversationService(
            owner_id=OWNER_ID,
            intelligence_id=MELLI_ID,
            store=runtime.conversation_store,
            model_gateway=FakeModelGateway(
                fail_external,
                clock=lambda: _NOW,
                id_factory=id_factory,
            ),
            retriever=PolicyConstrainedRetriever(
                runtime.memory_store,
                clock=lambda: _NOW,
                id_factory=id_factory,
            ),
            guardian_reader=_guardian(),
            clock=lambda: _NOW,
            id_factory=id_factory,
            max_processing_attempts=1,
        )
        principal = AuthenticatedOwner(
            owner_id=OWNER_ID,
            session_id=id_factory("session"),
            authentication_method="auth.synthetic-opaque-token",
            authenticated_at=_NOW,
            reauthenticated_until=_NOW + timedelta(minutes=5),
            expires_at=_NOW + timedelta(minutes=30),
        )
        thread = service.create_thread(
            principal,
            title="Durable external failure",
            sensitivity=Sensitivity.PERSONAL,
        )
        reply = service.post_owner_message(
            principal,
            thread_id=thread.thread_id,
            text="Use this durable context with the model.",
            idempotency_key="postgres-failed-external",
        )
        message_id = reply.inbound_message.message_id
        assert reply.processing.state.value == "dead"

    with _connect(dsn) as second_connection:
        store = PostgresConversationStore(second_connection, id_factory=_ids(200))
        processing = store.reply_processing(message_id)
        attempt = processing.attempts[0]
        assert attempt.failed_model_target is not None
        assert attempt.failed_model_target.provider_id == "provider.postgres-approved"
        assert attempt.failed_model_target.model_id == "durable-external-v1"
        assert (
            attempt.failed_model_target.processing_location
            is ProcessingLocation.APPROVED_PROVIDER
        )
        assert memory.assertion_id in attempt.disclosed_memory_ids
        assert attempt.retrieval_manifest_id is not None
        assert store.get_retrieval_manifest(
            attempt.retrieval_manifest_id
        ).external_disclosure is True

        stored_target = second_connection.execute(
            """
            SELECT payload -> 'attempts' -> 0 -> 'failed_model_target'
              FROM melloa.jobs_outbox
             WHERE work_type = 'conversation.owner_reply'
               AND payload ->> 'message_id' = %s
            """,
            (message_id,),
        ).fetchone()
        assert stored_target == ({
            "provider_id": "provider.postgres-approved",
            "model_id": "durable-external-v1",
            "processing_location": "approved_provider",
        },)
