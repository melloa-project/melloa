from __future__ import annotations

import io
import json
import os
import zipfile
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.models.openai_compatible import OpenAICompatibleModelConfig
from melloa.adapters.models.routed import ModelRouteConfigs
from melloa.adapters.postgres.conversation import PostgresConversationStore
from melloa.adapters.postgres.memory import PostgresMemoryRepository
from melloa.adapters.postgres.self_change import PostgresSelfChangeStore
from melloa.adapters.postgres.telegram import PostgresTelegramStore
from melloa.adapters.telegram import TelegramOwnerConfig, TelegramUpdate
from melloa.application.conversation import ConversationService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.runtime import MELLI_ID, OWNER_ID, build_runtime
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import JsonObject
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import Assertion, AssertionStatus
from melloa.domain.models import ModelRequest, ModelRoute, ProcessingLocation
from melloa.domain.self_change import SelfChange, SelfChangeState, self_change_request_digest
from melloa.ports.model import ModelInvocationError
from melloa.ports.self_change import SelfChangeConflictError
from melloa.ports.telegram import TelegramStateConflictError

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
                route=ModelRoute.ECONOMY,
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
            "route": "economy",
        },)


def test_self_change_queue_and_exact_approval_survive_restart() -> None:
    dsn = os.environ["MELLOA_TEST_DATABASE_DSN"]
    requested_at = _NOW + timedelta(days=1)
    request_text = "Add one bounded behavior from this explicit owner request."
    change = SelfChange(
        change_id="change_00000000000000000000000000000c01",
        owner_id=OWNER_ID,
        request_text=request_text,
        request_digest=self_change_request_digest(request_text),
        requested_update_id=501,
        state=SelfChangeState.REQUESTED,
        available_at=requested_at,
        requested_at=requested_at,
        updated_at=requested_at,
    )
    with _connect(dsn) as first_connection:
        build_runtime(
            _guardian(),
            _OWNER_CREDENTIAL,
            database_connection=first_connection,
            clock=lambda: requested_at,
        )
        changes = PostgresSelfChangeStore(first_connection)
        created = changes.create(change)
        replay = changes.create(
            change.model_copy(
                update={
                    "change_id": "change_00000000000000000000000000000cff",
                    "available_at": requested_at + timedelta(seconds=1),
                    "requested_at": requested_at + timedelta(seconds=1),
                    "updated_at": requested_at + timedelta(seconds=1),
                }
            )
        )
        assert replay == created
        claim = changes.claim_next_planning(
            lease_owner="worker_00000000000000000000000000000c01",
            now=requested_at + timedelta(seconds=1),
            lease_expires_at=requested_at + timedelta(seconds=11),
        )
        assert claim is not None
        retry = changes.record_planning_failure(
            claim,
            error_code="self_change.coding_agent_unavailable",
            retry_at=requested_at + timedelta(seconds=6),
            now=requested_at + timedelta(seconds=2),
        )
        assert retry.state is SelfChangeState.REQUESTED
        assert retry.attempt_count == 1

    with _connect(dsn) as second_connection:
        changes = PostgresSelfChangeStore(second_connection)
        assert (
            changes.claim_next_planning(
                lease_owner="worker_00000000000000000000000000000c02",
                now=requested_at + timedelta(seconds=5),
                lease_expires_at=requested_at + timedelta(seconds=15),
            )
            is None
        )
        claim = changes.claim_next_planning(
            lease_owner="worker_00000000000000000000000000000c02",
            now=requested_at + timedelta(seconds=7),
            lease_expires_at=requested_at + timedelta(seconds=17),
        )
        assert claim is not None
        assert claim.attempt_count == 2
        proposal = changes.record_proposal(
            claim,
            base_revision="a" * 40,
            summary="Add one bounded owner-approved behavior.",
            patch="diff --git a/example b/example\n+owner approved\n",
            now=requested_at + timedelta(seconds=8),
        )
        assert proposal.proposal_digest is not None
        approved = changes.approve(
            OWNER_ID,
            change.change_id,
            proposal_digest=proposal.proposal_digest,
            approval_update_id=502,
            now=requested_at + timedelta(seconds=9),
        )
        assert approved.state is SelfChangeState.APPROVED
        assert (
            changes.approve(
                OWNER_ID,
                change.change_id,
                proposal_digest=proposal.proposal_digest,
                approval_update_id=502,
                now=requested_at + timedelta(seconds=10),
            )
            == approved
        )
        applying = changes.claim_next_applying(
            lease_owner="worker_00000000000000000000000000000c03",
            now=requested_at + timedelta(seconds=10),
            lease_expires_at=requested_at + timedelta(seconds=20),
        )
        assert applying is not None
        assert applying.attempt_count == 1
        applying = changes.record_candidate(
            applying,
            candidate_revision="b" * 40,
            now=requested_at + timedelta(seconds=11),
        )
        retry_apply = changes.record_applying_failure(
            applying,
            error_code="self_change.release_temporarily_unavailable",
            retry_at=requested_at + timedelta(seconds=14),
            now=requested_at + timedelta(seconds=12),
        )
        assert retry_apply.state is SelfChangeState.APPROVED
        assert retry_apply.candidate_revision == "b" * 40
        applying = changes.claim_next_applying(
            lease_owner="worker_00000000000000000000000000000c04",
            now=requested_at + timedelta(seconds=15),
            lease_expires_at=requested_at + timedelta(seconds=25),
        )
        assert applying is not None
        assert applying.attempt_count == 2
        applying = changes.record_candidate(
            applying,
            candidate_revision="b" * 40,
            now=requested_at + timedelta(seconds=16),
        )
        deployed = changes.record_deployed(
            applying,
            candidate_revision="b" * 40,
            now=requested_at + timedelta(seconds=17),
        )
        assert deployed.state is SelfChangeState.DEPLOYED

        cancelled_request = request_text + " Cancel it."
        cancelled = changes.create(
            SelfChange(
                change_id="change_00000000000000000000000000000c02",
                owner_id=OWNER_ID,
                request_text=cancelled_request,
                request_digest=self_change_request_digest(cancelled_request),
                requested_update_id=503,
                state=SelfChangeState.REQUESTED,
                available_at=requested_at + timedelta(seconds=10),
                requested_at=requested_at + timedelta(seconds=10),
                updated_at=requested_at + timedelta(seconds=10),
            )
        )
        cancelled = changes.cancel(
            OWNER_ID,
            cancelled.change_id,
            cancellation_update_id=504,
            now=requested_at + timedelta(seconds=11),
        )
        assert cancelled.state is SelfChangeState.CANCELLED

    with _connect(dsn) as third_connection:
        changes = PostgresSelfChangeStore(third_connection)
        retained = changes.get(OWNER_ID, change.change_id)
        assert retained.state is SelfChangeState.DEPLOYED
        assert retained.proposal_digest == retained.approved_digest
        event_types = [
            str(row[0])
            for row in third_connection.execute(
                """
                SELECT event_type
                  FROM melloa.self_change_events
                 WHERE change_id = %s
                 ORDER BY event_sequence
                """,
                (change.change_id,),
            ).fetchall()
        ]
        assert event_types == [
            "self_change.requested",
            "self_change.planning_started",
            "self_change.planning_retry",
            "self_change.planning_started",
            "self_change.proposal_ready",
            "self_change.approved",
            "self_change.applying_started",
            "self_change.applying_retry",
            "self_change.applying_started",
            "self_change.deployed",
        ]
        with pytest.raises(psycopg.Error, match="permission denied"):
            third_connection.execute(
                "UPDATE melloa.self_change_events SET state = 'failed' WHERE change_id = %s",
                (change.change_id,),
            )
        third_connection.execute("RESET ROLE")
        with pytest.raises(psycopg.Error, match="append-only"):
            third_connection.execute(
                "UPDATE melloa.self_change_events SET state = 'failed' WHERE change_id = %s",
                (change.change_id,),
            )
        third_connection.execute("SET ROLE melloa_core")

        with pytest.raises(SelfChangeConflictError):
            changes.approve(
                OWNER_ID,
                change.change_id,
                proposal_digest=retained.proposal_digest,
                approval_update_id=505,
                now=requested_at + timedelta(seconds=27),
            )


def test_telegram_cursor_and_partial_delivery_survive_restart() -> None:
    dsn = os.environ["MELLOA_TEST_DATABASE_DSN"]
    inbound_message_id = "message_00000000000000000000000000000a01"
    response_message_id = "message_00000000000000000000000000000a02"
    first_lease_owner = "worker_00000000000000000000000000000a01"
    second_lease_owner = "worker_00000000000000000000000000000a02"

    with _connect(dsn) as first_connection:
        store = PostgresTelegramStore(first_connection)
        channel = store.bind_owner_channel(
            owner_user_id=1_234_567,
            owner_chat_id=7_654_321,
            initial_model_route=ModelRoute.ECONOMY,
            now=_NOW,
        )
        assert channel.last_update_id is None
        accepted = store.accept_conversation_update(
            update_id=101,
            incoming_message_id=51,
            inbound_message_id=inbound_message_id,
            now=_NOW,
            max_attempts=3,
        )
        assert accepted.state.value == "awaiting_reply"
        ready = store.mark_conversation_ready(
            101,
            response_message_id=response_message_id,
            now=_NOW + timedelta(seconds=1),
        )
        assert ready.state.value == "ready"
        claimed = store.claim_next_delivery(
            lease_owner=first_lease_owner,
            now=_NOW + timedelta(seconds=2),
            lease_expires_at=_NOW + timedelta(seconds=12),
        )
        assert claimed is not None
        partial = store.record_delivery_part(
            claimed,
            telegram_message_id=901,
            now=_NOW + timedelta(seconds=3),
        )
        assert partial.sent_part_count == 1

    with _connect(dsn) as second_connection:
        store = PostgresTelegramStore(second_connection)
        channel = store.bind_owner_channel(
            owner_user_id=1_234_567,
            owner_chat_id=7_654_321,
            initial_model_route=ModelRoute.CAPABLE,
            now=_NOW + timedelta(seconds=4),
        )
        assert channel.last_update_id == 101
        assert channel.model_route is ModelRoute.ECONOMY
        replay = store.accept_conversation_update(
            update_id=101,
            incoming_message_id=51,
            inbound_message_id=inbound_message_id,
            now=_NOW + timedelta(seconds=4),
            max_attempts=3,
        )
        assert replay.sent_part_count == 1
        assert (
            store.claim_next_delivery(
                lease_owner=second_lease_owner,
                now=_NOW + timedelta(seconds=11),
                lease_expires_at=_NOW + timedelta(seconds=21),
            )
            is None
        )
        resumed = store.claim_next_delivery(
            lease_owner=second_lease_owner,
            now=_NOW + timedelta(seconds=13),
            lease_expires_at=_NOW + timedelta(seconds=23),
        )
        assert resumed is not None
        assert resumed.attempt_count == 2
        assert resumed.telegram_message_ids == (901,)
        complete_part = store.record_delivery_part(
            resumed,
            telegram_message_id=902,
            now=_NOW + timedelta(seconds=14),
        )
        completed = store.complete_delivery(
            complete_part,
            now=_NOW + timedelta(seconds=15),
        )
        assert completed.state.value == "sent"
        assert completed.telegram_message_ids == (901, 902)
        assert store.delivery_summary().sent == 1

        with pytest.raises(TelegramStateConflictError, match="durable binding"):
            store.bind_owner_channel(
                owner_user_id=111,
                owner_chat_id=222,
                initial_model_route=ModelRoute.ECONOMY,
                now=_NOW + timedelta(seconds=16),
            )
        route_delivery = store.accept_model_route_update(
            update_id=102,
            incoming_message_id=52,
            model_route=ModelRoute.CAPABLE,
            now=_NOW + timedelta(seconds=17),
            max_attempts=3,
        )
        assert route_delivery.notice_code == "telegram.model_route.capable"

    with _connect(dsn) as third_connection:
        store = PostgresTelegramStore(third_connection)
        channel = store.bind_owner_channel(
            owner_user_id=1_234_567,
            owner_chat_id=7_654_321,
            initial_model_route=ModelRoute.ECONOMY,
            now=_NOW + timedelta(seconds=18),
        )
        assert channel.last_update_id == 102
        assert channel.model_route is ModelRoute.CAPABLE
        replay = store.accept_model_route_update(
            update_id=102,
            incoming_message_id=52,
            model_route=ModelRoute.CAPABLE,
            now=_NOW + timedelta(seconds=19),
            max_attempts=3,
        )
        assert replay.notice_code == "telegram.model_route.capable"
        current = store.accept_model_route_update(
            update_id=103,
            incoming_message_id=53,
            model_route=None,
            now=_NOW + timedelta(seconds=20),
            max_attempts=3,
        )
        assert current.notice_code == "telegram.model_route.capable"
        assert store.owner_channel().model_route is ModelRoute.CAPABLE
        control = store.accept_control_update(
            update_id=104,
            incoming_message_id=54,
            control_text="Exact durable self-change response.",
            now=_NOW + timedelta(seconds=21),
            max_attempts=3,
        )
        assert control.control_text == "Exact durable self-change response."

    with _connect(dsn) as fourth_connection:
        store = PostgresTelegramStore(fourth_connection)
        channel = store.bind_owner_channel(
            owner_user_id=1_234_567,
            owner_chat_id=7_654_321,
            initial_model_route=ModelRoute.ECONOMY,
            now=_NOW + timedelta(seconds=22),
        )
        assert channel.last_update_id == 104
        replay = store.accept_control_update(
            update_id=104,
            incoming_message_id=54,
            control_text="Exact durable self-change response.",
            now=_NOW + timedelta(seconds=23),
            max_attempts=3,
        )
        assert replay.control_text == "Exact durable self-change response."
        with pytest.raises(TelegramStateConflictError, match="identity conflicts"):
            store.accept_control_update(
                update_id=104,
                incoming_message_id=54,
                control_text="Changed response must not replace the durable one.",
                now=_NOW + timedelta(seconds=24),
                max_attempts=3,
            )


def test_runtime_composes_persistent_owner_telegram_service() -> None:
    dsn = os.environ["MELLOA_TEST_DATABASE_DSN"]
    with _connect(dsn) as connection:
        runtime = build_runtime(
            _guardian(),
            _OWNER_CREDENTIAL,
            model_routes=ModelRouteConfigs(
                capable=OpenAICompatibleModelConfig(
                    display_name="Integration capable model",
                    provider_id="provider.integration-local",
                    model_id="integration-capable-v1",
                    base_url="http://127.0.0.1:11434/v1",
                ),
                economy=OpenAICompatibleModelConfig(
                    display_name="Integration economy model",
                    provider_id="provider.integration-local",
                    model_id="integration-economy-v1",
                    base_url="http://127.0.0.1:11434/v1",
                ),
            ),
            database_connection=connection,
            telegram_config=TelegramOwnerConfig(
                owner_user_id=1_234_567,
                owner_chat_id=7_654_321,
            ),
            telegram_bot_token="123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456",
        )
        assert runtime.owner_telegram is not None
        runtime.owner_telegram._bind_owner_channel()
        runtime.owner_telegram._accept_update(
            TelegramUpdate.model_validate(
                {
                    "update_id": 700,
                    "message": {
                        "message_id": 800,
                        "from": {"id": 1_234_567, "is_bot": False},
                        "chat": {"id": 7_654_321, "type": "private"},
                        "date": 1_777_000_000,
                        "text": "/change propose Add one bounded integration behavior.",
                    },
                },
                strict=True,
            )
        )
        change_row = connection.execute(
            """
            SELECT state, request_text
              FROM melloa.self_changes
             WHERE requested_update_id = 700
            """
        ).fetchone()
        assert change_row == ("requested", "Add one bounded integration behavior.")
        control_row = connection.execute(
            """
            SELECT delivery_kind, control_text
              FROM melloa.telegram_deliveries
             WHERE update_id = 700
            """
        ).fetchone()
        assert control_row is not None
        assert control_row[0] == "control"
        assert "no commit, push, or deployment is authorized" in str(control_row[1])

    assert runtime.persistence == "postgresql"
    assert runtime.model_id is None
    assert runtime.model_routes is not None
    assert runtime.owner_telegram is not None
    assert runtime.owner_self_changes is not None
    assert runtime.self_change_store is not None
