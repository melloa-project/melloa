from __future__ import annotations

import os
from contextlib import ExitStack
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.model import FakeModelGateway
from melloa.adapters.postgres.conversation import PostgresConversationStore
from melloa.adapters.postgres.delivery import PostgresDeliveryStore
from melloa.adapters.postgres.memory import PostgresMemoryRepository
from melloa.adapters.postgres.migrations import apply_migrations, discover_migrations
from melloa.adapters.postgres.store import EventConflictError, PostgresEventAuditStore
from melloa.application.conversation import ConversationService
from melloa.application.inspection import OwnerInspectionService
from melloa.application.memory import MemoryService
from melloa.application.retrieval import PolicyConstrainedRetriever
from melloa.apps.mvp import build_mvp_runtime
from melloa.apps.postgres_mvp import build_postgres_mvp_stores
from melloa.apps.synthetic import (
    SYNTHETIC_ASSERTION_ID,
    SYNTHETIC_OWNER_ID,
    SYNTHETIC_TELEGRAM_ADAPTER_ID,
)
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import canonical_json_bytes, sha256_digest
from melloa.domain.classification import EpistemicStatus, Sensitivity, TrustLabel
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationThread,
    DeliveryAttempt,
    DeliveryState,
    MessageKind,
    MessagePart,
)
from melloa.domain.delivery import (
    DeliveryExecutionReceipt,
    DeliveryWorkAttempt,
    DeliveryWorkOutcome,
    DeliveryWorkResumption,
    DeliveryWorkState,
    OutboundDeliveryWork,
    canonical_delivery_action,
    conversation_message_hash,
)
from melloa.domain.events import EventEnvelope
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.memory import (
    Assertion,
    AssertionStateChange,
    AssertionStateProjection,
    AssertionStatus,
    ProvenanceEdge,
    ProvenanceRelation,
)
from melloa.domain.policy import (
    AuthorizationRequest,
    DeterministicPolicyEvaluator,
    PolicyContext,
    PolicyDecision,
    action_hash,
)
from melloa.domain.telegram import (
    TelegramChatType,
    TelegramInboundMessage,
    TelegramInboundUpdate,
)
from melloa.ports.delivery import DeliveryConflictError
from melloa.ports.memory import (
    AssertionCorrectionWrite,
    AssertionStateTransitionWrite,
    MemoryConflictError,
    MemoryContentDeletedError,
)
from tests.conftest import record_id


@pytest.fixture
def database_dsn():
    dsn = os.environ.get("MELLOA_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("MELLOA_TEST_DATABASE_DSN is required for PostgreSQL integration tests")
    return dsn


@pytest.fixture
def connection(database_dsn):
    with psycopg.connect(database_dsn, autocommit=True) as database:
        yield database


@pytest.fixture(autouse=True)
def reset_append_tables(connection) -> None:
    connection.execute(
        """
        TRUNCATE
            melloa.assertion_derived_rebuild_work,
            melloa.assertion_content_deletions,
            melloa.telegram_poll_states,
            melloa.telegram_ingestion_receipts,
            melloa.telegram_inbound_updates,
            melloa.telegram_active_pairings,
            melloa.telegram_pairing_revocations,
            melloa.telegram_owner_pairings,
            melloa.telegram_pairing_candidates,
            melloa.audit_events,
            melloa.canonical_events,
            melloa.provenance_edges,
            melloa.assertions,
            melloa.retrieval_manifests,
            melloa.model_runs,
            melloa.jobs_outbox,
            melloa.policy_decisions,
            melloa.conversation_threads,
            melloa.owners
        RESTART IDENTITY CASCADE
        """
    )


def _insert_assertion(connection, assertion: Assertion) -> None:
    connection.execute(
        """
        SELECT melloa.append_assertion(
            %(document)s::jsonb,
            'memory.assertion-owner-lifecycle'::text,
            %(retained_at)s::timestamptz,
            NULL::timestamptz
        )
        """,
        {
            "document": Jsonb(assertion.model_dump(mode="json")),
            "retained_at": assertion.observed_at,
        },
    )


def _delivery_authorization(
    message: ConversationMessage,
    at: datetime,
    *,
    number: int,
) -> tuple[AuthorizationRequest, PolicyDecision]:
    action = canonical_delivery_action(
        message,
        client_adapter="client.fake",
        destination_ref="synthetic:owner",
        external_destination="synthetic:owner",
        purpose="conversation.owner_delivery",
        estimated_cost_gbp=Decimal("0"),
    )
    request = AuthorizationRequest(
        request_id=record_id("request", number),
        proposal_id=record_id("proposal", number),
        principal_id=message.author_principal_id,
        action=action,
        action_hash=action_hash(action),
        guardian_sequence=1,
        requested_at=at,
    )
    decision = DeterministicPolicyEvaluator().evaluate(
        request,
        PolicyContext(
            guardian_mode=GuardianMode.NORMAL,
            guardian_sequence=1,
            granted_operations=frozenset({"client.fake/messages.send"}),
            approved_action_hashes=frozenset({request.action_hash}),
            remaining_daily_budget_gbp=Decimal("1"),
        ),
        decision_id=record_id("decision", number),
        decided_at=at,
    )
    return request, decision


def _insert_delivery_fixture(
    connection,
    fixed_time: datetime,
) -> tuple[ConversationThread, ConversationMessage, OutboundDeliveryWork]:
    owner_id = record_id("owner", 1)
    intelligence_id = record_id("intelligence", 1)
    connection.execute(
        """
        INSERT INTO melloa.owners (
            owner_id, contract_version, status, created_at, document
        ) VALUES (%s, '1.0.0', 'active', %s, %s)
        """,
        (
            owner_id,
            fixed_time,
            Jsonb(
                {
                    "contract_version": "1.0.0",
                    "owner_id": owner_id,
                    "created_at": fixed_time.isoformat().replace("+00:00", "Z"),
                    "status": "active",
                }
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO melloa.persistent_intelligences (
            intelligence_id, owner_id, contract_version, role_description,
            status, created_at, document
        ) VALUES (%s, %s, '1.0.0', %s, 'active', %s, %s)
        """,
        (
            intelligence_id,
            owner_id,
            "Synthetic persistent intelligence",
            fixed_time,
            Jsonb(
                {
                    "contract_version": "1.0.0",
                    "intelligence_id": intelligence_id,
                    "owner_id": owner_id,
                    "created_at": fixed_time.isoformat().replace("+00:00", "Z"),
                    "role": "Synthetic persistent intelligence",
                    "status": "active",
                    "naming_history": [],
                }
            ),
        ),
    )
    thread = ConversationThread(
        thread_id=record_id("thread", 1),
        owner_id=owner_id,
        intelligence_id=intelligence_id,
        title="Durable outbound delivery",
        sensitivity=Sensitivity.PERSONAL,
        retention_policy="retention.owner-conversation",
        created_at=fixed_time,
        updated_at=fixed_time,
    )
    message = ConversationMessage(
        message_id=record_id("message", 1),
        thread_id=thread.thread_id,
        author_principal_id=intelligence_id,
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text="Synthetic durable delivery."),),
        delivery_state=DeliveryState.PENDING,
        sensitivity=Sensitivity.PERSONAL,
        created_at=fixed_time,
        observed_at=fixed_time,
    )
    connection.execute(
        """
        INSERT INTO melloa.conversation_threads (
            thread_id, owner_id, intelligence_id, title, status, sensitivity,
            retention_policy, created_at, updated_at, document
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            thread.thread_id,
            thread.owner_id,
            thread.intelligence_id,
            thread.title,
            thread.status.value,
            thread.sensitivity.value,
            thread.retention_policy,
            thread.created_at,
            thread.updated_at,
            Jsonb(thread.model_dump(mode="json")),
        ),
    )
    connection.execute(
        """
        INSERT INTO melloa.conversation_messages (
            message_id, thread_id, author_principal_id, source_client,
            sensitivity, created_at, observed_at, document
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            message.message_id,
            message.thread_id,
            message.author_principal_id,
            message.source_client,
            message.sensitivity.value,
            message.created_at,
            message.observed_at,
            Jsonb(message.model_dump(mode="json")),
        ),
    )
    request, decision = _delivery_authorization(message, fixed_time, number=1)
    work = OutboundDeliveryWork(
        work_id=record_id("deliverywork", 1),
        thread_id=thread.thread_id,
        message_id=message.message_id,
        message_hash=conversation_message_hash(message),
        requested_by=owner_id,
        client_adapter="client.fake",
        destination_ref="synthetic:owner",
        idempotency_key="postgres:delivery:1",
        authorization_request=request,
        policy_decision=decision,
        authorized_at=fixed_time,
        created_at=fixed_time,
    )
    return thread, message, work


def _successful_delivery_attempt(
    work: OutboundDeliveryWork,
    *,
    attempt: int,
    started_at: datetime,
    receipt_number: int,
) -> DeliveryWorkAttempt:
    completed_at = started_at + timedelta(milliseconds=1)
    request, decision, _authorized_at = work.current_authorization()
    adapter_receipt = DeliveryAttempt(
        delivery_id=record_id("delivery", receipt_number),
        message_id=work.message_id,
        client_adapter=work.client_adapter,
        destination_ref=work.destination_ref,
        attempt=attempt,
        state=DeliveryState.DELIVERED,
        attempted_at=completed_at,
    )
    execution_receipt = DeliveryExecutionReceipt(
        action_id=record_id("action", receipt_number),
        decision_id=decision.decision_id,
        action_hash=request.action_hash,
        capability_id=work.client_adapter,
        operation="messages.send",
        delivery_id=adapter_receipt.delivery_id,
        executed_at=completed_at,
        result_summary={"delivery_state": "delivered"},
    )
    return DeliveryWorkAttempt(
        attempt_id=record_id("deliveryattempt", attempt),
        work_id=work.work_id,
        message_id=work.message_id,
        attempt=attempt,
        authorization_request_id=request.request_id,
        policy_decision_id=decision.decision_id,
        action_hash=request.action_hash,
        outcome=DeliveryWorkOutcome.SUCCEEDED,
        started_at=started_at,
        completed_at=completed_at,
        adapter_receipt=adapter_receipt,
        execution_receipt=execution_receipt,
    )


def _delivery_resumption(
    work: OutboundDeliveryWork,
    message: ConversationMessage,
    *,
    requested_at: datetime,
    prior_attempts: int,
    added_attempts: int,
) -> DeliveryWorkResumption:
    request, decision = _delivery_authorization(message, requested_at, number=2)
    return DeliveryWorkResumption(
        resumption_id=record_id("deliveryresume", 1),
        work_id=work.work_id,
        message_id=work.message_id,
        requested_by=work.requested_by,
        requested_at=requested_at,
        prior_attempts=prior_attempts,
        added_attempts=added_attempts,
        authorization_request=request,
        policy_decision=decision,
    )


def test_atomic_event_audit_append_is_idempotent(connection, event, audit_content) -> None:
    store = PostgresEventAuditStore(connection)
    record = store.append_event(event, audit_content)
    assert record is not None
    assert record.previous_hash is None
    assert store.append_event(event, audit_content) is None

    event_count = connection.execute(
        "SELECT count(*) FROM melloa.canonical_events WHERE event_id = %s",
        (event.event_id,),
    ).fetchone()[0]
    audit_count = connection.execute(
        "SELECT count(*) FROM melloa.audit_events WHERE audit_id = %s",
        (audit_content.audit_id,),
    ).fetchone()[0]
    assert event_count == 1
    assert audit_count == 1


def test_immutable_event_id_cannot_change_content(connection, event, audit_content) -> None:
    store = PostgresEventAuditStore(connection)
    store.append_event(event, audit_content)
    changed_payload = {"zone": "window", "direction": "in"}
    changed_document = event.model_dump()
    changed_document["payload"] = changed_payload
    changed_document["integrity"]["payload_hash"] = sha256_digest(
        canonical_json_bytes(changed_payload)
    )
    changed_event = EventEnvelope.model_validate(changed_document)
    with pytest.raises(EventConflictError):
        store.append_event(changed_event, audit_content)

    with pytest.raises(psycopg.Error):
        connection.execute(
            "UPDATE melloa.canonical_events SET event_type = 'tampered.v1' WHERE event_id = %s",
            (event.event_id,),
        )


def test_database_enforces_audit_predecessor(connection) -> None:
    with pytest.raises(psycopg.Error, match="predecessor"):
        connection.execute(
            """
            INSERT INTO melloa.audit_events (
                audit_id, event_type, occurred_at, actor_id, action_name,
                previous_hash, record_hash, document
            ) VALUES (
                'audit_ffffffffffffffffffffffffffffffff',
                'audit.invalid.v1', now(),
                'owner_ffffffffffffffffffffffffffffffff',
                'audit.invalid',
                'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
                'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '{}'::jsonb
            )
            """
        )


def test_runtime_roles_are_narrow(connection) -> None:
    connection.execute("SET ROLE melloa_readonly")
    try:
        connection.execute("SELECT count(*) FROM melloa.canonical_events").fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                INSERT INTO melloa.canonical_events (
                    event_id, event_type, schema_version, occurred_at, recorded_at,
                    epistemic_status, sensitivity, trust_label, payload_hash, document
                ) VALUES (
                    'event_ffffffffffffffffffffffffffffffff', 'observation.denied.v1', '1.0.0',
                    now(), now(), 'observation', 'internal', 'trusted_system',
                    'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
                    '{}'::jsonb
                )
                """
            )
    finally:
        connection.execute("RESET ROLE")

    connection.execute("SET ROLE melloa_backup")
    try:
        connection.execute("SELECT count(*) FROM melloa.assertion_contents").fetchone()
    finally:
        connection.execute("RESET ROLE")


def test_assertion_content_migration_backfills_legacy_documents(
    connection,
    fixed_time,
) -> None:
    database_name = f"melloa_assertion_upgrade_{os.getpid()}"
    database = sql.Identifier(database_name)
    connection.execute(
        sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(database)
    )
    connection.execute(sql.SQL("CREATE DATABASE {}").format(database))
    try:
        migration_root = Path(__file__).resolve().parents[2] / "migrations"
        migrations = discover_migrations(
            migration_root,
            migration_root / "manifest.json",
        )
        dsn = make_conninfo(connection.info.dsn, dbname=database_name)
        with psycopg.connect(dsn, autocommit=True) as upgrade_connection:
            apply_migrations(upgrade_connection, migrations[:5])
            legacy = Assertion(
                assertion_id=record_id("assertion", 90),
                subject_id=record_id("owner", 90),
                predicate="preference.synthetic",
                value={"topic": "migration rehearsal"},
                epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
                status=AssertionStatus.CONFIRMED,
                confidence=1.0,
                source_authority=TrustLabel.OWNER_AUTHORED,
                sensitivity=Sensitivity.PERSONAL,
                observed_at=fixed_time,
            )
            upgrade_connection.execute(
                """
                INSERT INTO melloa.assertions (
                    assertion_id, subject_id, predicate, epistemic_status,
                    assertion_status, confidence, sensitivity, source_authority,
                    observed_at, valid_from, valid_to, correction_target_id, document
                ) VALUES (
                    %(assertion_id)s, %(subject_id)s, %(predicate)s,
                    %(epistemic_status)s, %(assertion_status)s, %(confidence)s,
                    %(sensitivity)s, %(source_authority)s, %(observed_at)s,
                    NULL, NULL, NULL, %(document)s
                )
                """,
                {
                    "assertion_id": legacy.assertion_id,
                    "subject_id": legacy.subject_id,
                    "predicate": legacy.predicate,
                    "epistemic_status": legacy.epistemic_status.value,
                    "assertion_status": legacy.status.value,
                    "confidence": legacy.confidence,
                    "sensitivity": legacy.sensitivity.value,
                    "source_authority": legacy.source_authority.value,
                    "observed_at": legacy.observed_at,
                    "document": Jsonb(legacy.model_dump(mode="json")),
                },
            )

            status = apply_migrations(upgrade_connection, migrations)
            assert status.pending == ()
            metadata, value, content_hash, size_bytes, policy, retained_at, expires_at = (
                upgrade_connection.execute(
                    """
                    SELECT assertion.document, content.value, content.content_hash,
                           content.size_bytes, content.retention_policy,
                           content.retained_at, content.expires_at
                      FROM melloa.assertions AS assertion
                      JOIN melloa.assertion_contents AS content USING (assertion_id)
                     WHERE assertion.assertion_id = %s
                    """,
                    (legacy.assertion_id,),
                ).fetchone()
            )
            assert metadata == legacy.model_dump(mode="json", exclude={"value"})
            assert value == legacy.value
            assert content_hash.startswith("sha256:") and len(content_hash) == 71
            assert size_bytes > 0
            assert policy == "memory.assertion-owner-lifecycle"
            assert retained_at == legacy.observed_at
            assert expires_at is None
            assert PostgresMemoryRepository(upgrade_connection).get_assertion(
                legacy.assertion_id
            ) == legacy
    finally:
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(database)
        )


def test_m1_manifest_is_append_only_and_assertion_state_is_a_projection(connection) -> None:
    assertion = Assertion(
        assertion_id="assertion_11111111111111111111111111111111",
        subject_id="owner_11111111111111111111111111111111",
        predicate="preference.synthetic",
        value={"preference": "synthetic"},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.8,
        sensitivity=Sensitivity.PERSONAL,
        source_authority=TrustLabel.MODEL_GENERATED,
        observed_at=datetime.fromisoformat("2026-08-16T12:00:00+00:00"),
    )
    assertion_id = assertion.assertion_id
    _insert_assertion(connection, assertion)
    state = connection.execute(
        """
        SELECT current_status, preferred_assertion_id, version
          FROM melloa.assertion_current_state
         WHERE assertion_id = %s
        """,
        (assertion_id,),
    ).fetchone()
    assert state == ("active", None, 1)
    metadata, value, content_hash, size_bytes, retention_policy = connection.execute(
        """
        SELECT assertion.document, content.value, content.content_hash,
               content.size_bytes, content.retention_policy
          FROM melloa.assertions AS assertion
          JOIN melloa.assertion_contents AS content USING (assertion_id)
         WHERE assertion.assertion_id = %s
        """,
        (assertion_id,),
    ).fetchone()
    assert metadata == assertion.model_dump(mode="json", exclude={"value"})
    assert value == assertion.value
    assert content_hash.startswith("sha256:") and len(content_hash) == 71
    assert size_bytes > 0
    assert retention_policy == "memory.assertion-owner-lifecycle"
    initial_change = connection.execute(
        """
        SELECT previous_status, new_status, reason, version
          FROM melloa.assertion_state_changes
         WHERE assertion_id = %s
        """,
        (assertion_id,),
    ).fetchone()
    assert initial_change == (None, "active", "assertion.initialized", 1)

    change_id = "state_change_11111111111111111111111111111111"
    changed_by_id = "correction_11111111111111111111111111111111"
    projection_document = {
        "contract_version": "1.0.0",
        "assertion_id": assertion_id,
        "current_status": "disputed",
        "preferred_assertion_id": None,
        "changed_by_record_id": changed_by_id,
        "changed_at": "2026-08-16T12:01:00Z",
        "version": 2,
    }
    change_document = {
        "contract_version": "1.0.0",
        "change_id": change_id,
        "assertion_id": assertion_id,
        "previous_status": "active",
        "new_status": "disputed",
        "preferred_assertion_id": None,
        "changed_by_record_id": changed_by_id,
        "reason": "owner.disputed",
        "changed_at": "2026-08-16T12:01:00Z",
        "version": 2,
    }
    connection.execute("SET ROLE melloa_core")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO melloa.assertions (assertion_id) VALUES (%s)",
                ("assertion_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "UPDATE melloa.assertion_contents SET value = '{}'::jsonb "
                "WHERE assertion_id = %s",
                (assertion_id,),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "DELETE FROM melloa.assertion_contents WHERE assertion_id = %s",
                (assertion_id,),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE melloa.assertion_current_state
                   SET current_status = 'disputed'
                 WHERE assertion_id = %s
                """,
                (assertion_id,),
            )
        connection.execute(
            """
            SELECT melloa.transition_assertion_state(
                %(change_id)s,
                %(assertion_id)s,
                1,
                'active',
                'disputed',
                NULL,
                %(changed_by_id)s,
                'owner.disputed',
                '2026-08-16T12:01:00Z',
                %(projection_document)s,
                %(change_document)s
            )
            """,
            {
                "change_id": change_id,
                "assertion_id": assertion_id,
                "changed_by_id": changed_by_id,
                "projection_document": Jsonb(projection_document),
                "change_document": Jsonb(change_document),
            },
        )
    finally:
        connection.execute("RESET ROLE")
    transitioned = connection.execute(
        """
        SELECT current_status, changed_by_record_id, version
          FROM melloa.assertion_current_state
         WHERE assertion_id = %s
        """,
        (assertion_id,),
    ).fetchone()
    assert transitioned == ("disputed", changed_by_id, 2)
    assert connection.execute(
        "SELECT count(*) FROM melloa.assertion_state_changes WHERE assertion_id = %s",
        (assertion_id,),
    ).fetchone()[0] == 2
    with pytest.raises(psycopg.Error, match="append-only"):
        connection.execute(
            "UPDATE melloa.assertions SET assertion_status = 'disputed' WHERE assertion_id = %s",
            (assertion_id,),
        )

    manifest_id = "retrieval_manifest_22222222222222222222222222222222"
    connection.execute(
        """
        INSERT INTO melloa.retrieval_manifests (
            manifest_id, requester_id, subject_id, purpose, query_hash,
            external_disclosure, created_at, document
        ) VALUES (
            %s,
            'intelligence_22222222222222222222222222222222',
            'owner_22222222222222222222222222222222',
            'conversation.owner-reply',
            'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            false,
            '2026-08-16T12:00:00Z',
            '{}'::jsonb
        )
        """,
        (manifest_id,),
    )
    with pytest.raises(psycopg.Error, match="append-only"):
        connection.execute(
            """
            UPDATE melloa.retrieval_manifests
               SET external_disclosure = true
             WHERE manifest_id = %s
            """,
            (manifest_id,),
        )

    worker_assertion = Assertion(
        assertion_id="assertion_33333333333333333333333333333333",
        subject_id="owner_33333333333333333333333333333333",
        predicate="observation.synthetic",
        value={"observation": "synthetic"},
        epistemic_status=EpistemicStatus.OBSERVATION,
        status=AssertionStatus.PROVISIONAL,
        confidence=0.5,
        sensitivity=Sensitivity.INTERNAL,
        source_authority=TrustLabel.TRUSTED_SYSTEM,
        observed_at=datetime.fromisoformat("2026-08-16T12:00:00+00:00"),
    )
    worker_assertion_id = worker_assertion.assertion_id
    connection.execute("SET ROLE melloa_worker")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO melloa.assertions (assertion_id) VALUES (%s)",
                (worker_assertion_id,),
            )
        _insert_assertion(connection, worker_assertion)
    finally:
        connection.execute("RESET ROLE")
    worker_state = connection.execute(
        """
        SELECT current_status, version
          FROM melloa.assertion_current_state
         WHERE assertion_id = %s
        """,
        (worker_assertion_id,),
    ).fetchone()
    assert worker_state == ("provisional", 1)
    worker_history = connection.execute(
        """
        SELECT new_status, reason, version
          FROM melloa.assertion_state_changes
         WHERE assertion_id = %s
        """,
        (worker_assertion_id,),
    ).fetchone()
    assert worker_history == ("provisional", "assertion.initialized", 1)
    assert connection.execute(
        "SELECT count(*) FROM melloa.assertion_contents WHERE assertion_id = %s",
        (worker_assertion_id,),
    ).fetchone()[0] == 1


def test_postgres_memory_correction_is_atomic_durable_and_version_checked(
    connection,
    fixed_time,
) -> None:
    owner_id = record_id("owner", 1)
    original = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=owner_id,
        predicate="activity.current",
        value={"activity": "sleeping"},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.61,
        source_authority=TrustLabel.MODEL_GENERATED,
        sensitivity=Sensitivity.SENSITIVE,
        observed_at=fixed_time,
        valid_from=fixed_time - timedelta(hours=1),
        valid_to=fixed_time + timedelta(hours=1),
    )
    _insert_assertion(connection, original)
    repository = PostgresMemoryRepository(connection)
    initial_state = repository.get_assertion_state(original.assertion_id)
    correction_time = fixed_time + timedelta(minutes=1)
    identifiers = {
        "assertion": record_id("assertion", 2),
        "edge": record_id("edge", 1),
        "state_change": record_id("state_change", 2),
    }
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="synthetic-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    service = MemoryService(
        owner_id=owner_id,
        store=repository,
        guardian_reader=guardian,
        clock=lambda: correction_time,
        id_factory=identifiers.__getitem__,
    )
    principal = AuthenticatedOwner(
        owner_id=owner_id,
        session_id=record_id("session", 1),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )

    connection.execute("SET ROLE melloa_core")
    try:
        result = service.correct(
            principal,
            original.assertion_id,
            value={"activity": "reading"},
            expected_version=1,
        )
        durable = PostgresMemoryRepository(connection)
        assert durable.get_assertion(original.assertion_id) == original
        assert durable.get_assertion(result.correction.assertion_id) == result.correction
        assert durable.get_assertion_state(original.assertion_id) == result.target_state
        assert durable.get_assertion_state(result.correction.assertion_id) == (
            result.correction_state
        )
        target_history = durable.list_assertion_state_changes(original.assertion_id)
        assert target_history[0].version == 1
        assert target_history == (target_history[0], result.target_change)
        assert durable.list_provenance_edges(
            frozenset({original.assertion_id})
        ) == (result.provenance_edge,)
        projected = {
            assertion.assertion_id: assertion
            for assertion in durable.list_assertions(owner_id)
        }
        assert projected[original.assertion_id].status is AssertionStatus.SUPERSEDED
        assert projected[result.correction.assertion_id].status is AssertionStatus.CONFIRMED

        stale_correction = Assertion(
            assertion_id=record_id("assertion", 3),
            subject_id=original.subject_id,
            predicate=original.predicate,
            value={"activity": "walking"},
            epistemic_status=EpistemicStatus.CORRECTION,
            status=AssertionStatus.CONFIRMED,
            confidence=1.0,
            source_authority=TrustLabel.OWNER_AUTHORED,
            sensitivity=original.sensitivity,
            observed_at=correction_time + timedelta(minutes=1),
            valid_from=original.valid_from,
            valid_to=original.valid_to,
            correction_target_id=original.assertion_id,
        )
        stale_state = AssertionStateProjection(
            assertion_id=original.assertion_id,
            current_status=AssertionStatus.SUPERSEDED,
            preferred_assertion_id=stale_correction.assertion_id,
            changed_by_record_id=stale_correction.assertion_id,
            changed_at=stale_correction.observed_at,
            version=2,
        )
        stale_change = AssertionStateChange(
            change_id=record_id("state_change", 3),
            assertion_id=original.assertion_id,
            previous_status=initial_state.current_status,
            new_status=stale_state.current_status,
            preferred_assertion_id=stale_correction.assertion_id,
            changed_by_record_id=stale_correction.assertion_id,
            reason="assertion.owner-corrected",
            changed_at=stale_correction.observed_at,
            version=2,
        )
        stale_write = AssertionCorrectionWrite(
            correction=stale_correction,
            provenance_edge=ProvenanceEdge(
                edge_id=record_id("edge", 2),
                from_id=stale_correction.assertion_id,
                to_id=original.assertion_id,
                relation=ProvenanceRelation.CORRECTS,
                created_at=stale_correction.observed_at,
                producer_id=owner_id,
            ),
            expected_target_state=initial_state,
            target_state=stale_state,
            target_change=stale_change,
        )
        with pytest.raises(MemoryConflictError, match="changed before correction"):
            durable.apply_correction(stale_write)
        duplicate_time = stale_correction.observed_at + timedelta(minutes=1)
        duplicate_state = AssertionStateProjection(
            assertion_id=original.assertion_id,
            current_status=AssertionStatus.SUPERSEDED,
            preferred_assertion_id=result.correction.assertion_id,
            changed_by_record_id=result.correction.assertion_id,
            changed_at=duplicate_time,
            version=3,
        )
        duplicate_change = AssertionStateChange(
            change_id=record_id("state_change", 4),
            assertion_id=original.assertion_id,
            previous_status=AssertionStatus.SUPERSEDED,
            new_status=AssertionStatus.SUPERSEDED,
            preferred_assertion_id=result.correction.assertion_id,
            changed_by_record_id=result.correction.assertion_id,
            reason="assertion.owner-corrected",
            changed_at=duplicate_time,
            version=3,
        )
        with pytest.raises(MemoryConflictError, match="durable memory state"):
            durable.apply_correction(
                AssertionCorrectionWrite(
                    correction=result.correction,
                    provenance_edge=result.provenance_edge,
                    expected_target_state=result.target_state,
                    target_state=duplicate_state,
                    target_change=duplicate_change,
                )
            )
    finally:
        connection.execute("RESET ROLE")

    counts = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM melloa.assertions),
            (SELECT count(*) FROM melloa.assertion_contents),
            (SELECT count(*) FROM melloa.provenance_edges),
            (SELECT count(*) FROM melloa.assertion_current_state),
            (SELECT count(*) FROM melloa.assertion_state_changes)
        """
    ).fetchone()
    assert counts == (2, 2, 1, 2, 3)


def test_postgres_memory_dispute_and_retraction_history_is_durable(
    connection,
    fixed_time,
) -> None:
    owner_id = record_id("owner", 1)
    original = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=owner_id,
        predicate="activity.current",
        value={"activity": "sleeping"},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.61,
        source_authority=TrustLabel.MODEL_GENERATED,
        sensitivity=Sensitivity.SENSITIVE,
        observed_at=fixed_time,
    )
    _insert_assertion(connection, original)
    repository = PostgresMemoryRepository(connection)
    initial_state = repository.get_assertion_state(original.assertion_id)
    now = [fixed_time + timedelta(minutes=1)]
    change_ids = iter((record_id("state_change", 2), record_id("state_change", 3)))
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="synthetic-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    service = MemoryService(
        owner_id=owner_id,
        store=repository,
        guardian_reader=guardian,
        clock=lambda: now[0],
        id_factory=lambda prefix: next(change_ids) if prefix == "state_change" else "",
    )
    principal = AuthenticatedOwner(
        owner_id=owner_id,
        session_id=record_id("session", 1),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )

    connection.execute("SET ROLE melloa_core")
    try:
        dispute = service.dispute(
            principal,
            original.assertion_id,
            expected_version=1,
        )
        now[0] = fixed_time + timedelta(minutes=2)
        retraction = service.retract(
            principal,
            original.assertion_id,
            expected_version=2,
        )
        durable = PostgresMemoryRepository(connection)
        assert durable.get_assertion(original.assertion_id) == original
        assert durable.get_assertion_state(original.assertion_id) == (
            retraction.current_state
        )
        history = durable.list_assertion_state_changes(original.assertion_id)
        assert tuple(change.new_status for change in history) == (
            AssertionStatus.ACTIVE,
            AssertionStatus.DISPUTED,
            AssertionStatus.RETRACTED,
        )
        assert history[1:] == (dispute.state_change, retraction.state_change)
        assert durable.list_assertions(owner_id)[0].status is AssertionStatus.RETRACTED
        with pytest.raises(MemoryConflictError, match="changed before transition"):
            durable.apply_state_transition(
                AssertionStateTransitionWrite(
                    expected_state=initial_state,
                    state=dispute.current_state,
                    change=dispute.state_change,
                )
            )
    finally:
        connection.execute("RESET ROLE")

    counts = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM melloa.assertions),
            (SELECT count(*) FROM melloa.assertion_contents),
            (SELECT count(*) FROM melloa.assertion_current_state),
            (SELECT count(*) FROM melloa.assertion_state_changes)
        """
    ).fetchone()
    assert counts == (1, 1, 1, 3)


def test_postgres_memory_content_deletion_is_durable_and_role_bounded(
    connection,
    fixed_time,
) -> None:
    owner_id = record_id("owner", 1)
    original = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=owner_id,
        predicate="activity.current",
        value={"activity": "sleeping"},
        epistemic_status=EpistemicStatus.BELIEF,
        status=AssertionStatus.ACTIVE,
        confidence=0.61,
        source_authority=TrustLabel.MODEL_GENERATED,
        sensitivity=Sensitivity.SENSITIVE,
        observed_at=fixed_time,
    )
    evidence = ProvenanceEdge(
        edge_id=record_id("edge", 1),
        from_id=original.assertion_id,
        to_id=record_id("event", 1),
        relation=ProvenanceRelation.DERIVED_FROM,
        created_at=fixed_time,
        producer_id=record_id("intelligence", 1),
    )
    _insert_assertion(connection, original)
    connection.execute(
        """
        INSERT INTO melloa.provenance_edges (
            edge_id, from_id, to_id, relation, producer_id, created_at, metadata
        ) VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb)
        """,
        (
            evidence.edge_id,
            evidence.from_id,
            evidence.to_id,
            evidence.relation.value,
            evidence.producer_id,
            evidence.created_at,
        ),
    )
    before_hash = connection.execute(
        """
        SELECT content_hash
          FROM melloa.assertion_contents
         WHERE assertion_id = %s
        """,
        (original.assertion_id,),
    ).fetchone()[0]
    deleted_at = fixed_time + timedelta(minutes=2)
    ids = iter((record_id("deletion", 1), record_id("work", 1)))
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="synthetic-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    service = MemoryService(
        owner_id=owner_id,
        store=PostgresMemoryRepository(connection),
        guardian_reader=guardian,
        clock=lambda: deleted_at,
        id_factory=lambda _prefix: next(ids),
    )
    principal = AuthenticatedOwner(
        owner_id=owner_id,
        session_id=record_id("session", 1),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )

    connection.execute("SET ROLE melloa_core")
    try:
        before_inventory = PostgresMemoryRepository(
            connection
        ).assertion_content_retention_inventory(owner_id)
        assert before_inventory.retained_objects == 1
        assert before_inventory.retained_bytes > 0
        assert before_inventory.deletion_receipts == 0
        assert before_inventory.oldest_retained_at == fixed_time

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "DELETE FROM melloa.assertion_contents WHERE assertion_id = %s",
                (original.assertion_id,),
            )

        result = service.delete_content(principal, original.assertion_id)
        durable = PostgresMemoryRepository(connection)
        assert result.created is True
        assert result.assertion.assertion_id == original.assertion_id
        assert result.tombstone.assertion_id == original.assertion_id
        assert result.tombstone.owner_id == owner_id
        assert result.tombstone.content_hash == before_hash
        assert result.tombstone.deleted_at == deleted_at
        assert result.tombstone.reason_code == "memory.assertion-content-owner-deleted"
        assert result.rebuild_work.work_id == result.tombstone.rebuild_work_id
        assert result.rebuild_work.tombstone_id == result.tombstone.tombstone_id
        assert durable.get_assertion_content_deletion(original.assertion_id) == (
            result.tombstone
        )
        with pytest.raises(MemoryContentDeletedError):
            durable.get_assertion(original.assertion_id)
        assert durable.list_assertions(owner_id) == ()
        after_inventory = durable.assertion_content_retention_inventory(owner_id)
        assert after_inventory.retained_objects == 0
        assert after_inventory.retained_bytes == 0
        assert after_inventory.deletion_receipts == 1
        assert after_inventory.oldest_retained_at is None

        inspection = service.inspect(principal, original.assertion_id)
        assert inspection.deletion_tombstone == result.tombstone
        assert inspection.provenance_edges == (evidence,)
        assert inspection.state_changes[0].reason == "assertion.initialized"

        repeated = service.delete_content(principal, original.assertion_id)
        assert repeated.created is False
        assert repeated.tombstone == result.tombstone
        assert repeated.rebuild_work == result.rebuild_work
        with pytest.raises(MemoryContentDeletedError):
            service.correct(
                principal,
                original.assertion_id,
                value={"activity": "reading"},
                expected_version=1,
            )
    finally:
        connection.execute("RESET ROLE")

    counts = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM melloa.assertions),
            (SELECT count(*) FROM melloa.assertion_contents),
            (SELECT count(*) FROM melloa.assertion_content_deletions),
            (SELECT count(*) FROM melloa.assertion_derived_rebuild_work),
            (SELECT count(*) FROM melloa.assertion_current_state),
            (SELECT count(*) FROM melloa.assertion_state_changes)
        """
    ).fetchone()
    assert counts == (1, 0, 1, 1, 1, 1)


def test_postgres_conversation_completion_is_atomic_cited_and_idempotent(
    connection,
    fixed_time,
) -> None:
    owner_id = record_id("owner", 1)
    intelligence_id = record_id("intelligence", 1)
    owner_document = {
        "contract_version": "1.0.0",
        "owner_id": owner_id,
        "created_at": fixed_time.isoformat().replace("+00:00", "Z"),
        "status": "active",
    }
    intelligence_document = {
        "contract_version": "1.0.0",
        "intelligence_id": intelligence_id,
        "owner_id": owner_id,
        "created_at": fixed_time.isoformat().replace("+00:00", "Z"),
        "role": "Synthetic persistent intelligence",
        "status": "active",
        "naming_history": [
            {
                "display_name": "Synthetic Melli",
                "valid_from": fixed_time.isoformat().replace("+00:00", "Z"),
                "valid_to": None,
                "chosen_by": owner_id,
            }
        ],
    }
    connection.execute(
        """
        INSERT INTO melloa.owners (
            owner_id, contract_version, status, created_at, document
        ) VALUES (%s, '1.0.0', 'active', %s, %s)
        """,
        (owner_id, fixed_time, Jsonb(owner_document)),
    )
    connection.execute(
        """
        INSERT INTO melloa.persistent_intelligences (
            intelligence_id, owner_id, contract_version, role_description,
            status, created_at, document
        ) VALUES (%s, %s, '1.0.0', %s, 'active', %s, %s)
        """,
        (
            intelligence_id,
            owner_id,
            "Synthetic persistent intelligence",
            fixed_time,
            Jsonb(intelligence_document),
        ),
    )
    memory = Assertion(
        assertion_id=record_id("assertion", 1),
        subject_id=owner_id,
        predicate="preference.review-topic",
        value={"topic": "finances"},
        epistemic_status=EpistemicStatus.OWNER_CONFIRMED,
        status=AssertionStatus.CONFIRMED,
        confidence=1.0,
        source_authority=TrustLabel.OWNER_AUTHORED,
        sensitivity=Sensitivity.PERSONAL,
        observed_at=fixed_time,
    )
    _insert_assertion(connection, memory)

    repository = PostgresMemoryRepository(connection)
    store = PostgresConversationStore(connection)

    def cited_response(request):
        assert request.input["memory_citations"][0]["assertion_id"] == memory.assertion_id
        return {
            "text": "Review the confirmed finance topic.",
            "citation_ids": [],
        }

    model = FakeModelGateway(
        cited_response,
        clock=lambda: fixed_time,
        external_disclosure=True,
    )
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="synthetic-guardian",
            mode=GuardianMode.NO_ACTIONS,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    service = ConversationService(
        owner_id=owner_id,
        intelligence_id=intelligence_id,
        store=store,
        model_gateway=model,
        retriever=PolicyConstrainedRetriever(repository, clock=lambda: fixed_time),
        guardian_reader=guardian,
        clock=lambda: fixed_time,
    )
    principal = AuthenticatedOwner(
        owner_id=owner_id,
        session_id=record_id("session", 1),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )

    connection.execute("SET ROLE melloa_core")
    try:
        thread = service.create_thread(
            principal,
            title="Durable cited conversation",
            sensitivity=Sensitivity.PERSONAL,
            retention_policy="retention.owner-conversation",
        )
        reply = service.post_owner_message(
            principal,
            thread_id=thread.thread_id,
            text="What should I review about finances?",
            idempotency_key="postgres:message:1",
        )
        duplicate = service.post_owner_message(
            principal,
            thread_id=thread.thread_id,
            text="What should I review about finances?",
            idempotency_key="postgres:message:1",
        )
        assert duplicate.duplicate is True
        assert duplicate.output_message == reply.output_message
        assert len(model.requests) == 1

        durable = PostgresConversationStore(connection)
        assert durable.reply_processing(reply.inbound_message.message_id).state.value == (
            "completed"
        )
        assert durable.list_messages(thread.thread_id) == (
            reply.inbound_message,
            reply.output_message,
        )
        assert durable.list_turns(thread.thread_id) == (reply.turn,)
        completed = durable.completed_turn_for_trigger(reply.inbound_message.message_id)
        assert completed is not None
        assert completed.output_message == reply.output_message
        assert completed.retrieval_manifest.external_disclosure is True
        assert completed.turn.evidence_ids == ()
        activity = OwnerInspectionService(
            owner_id=owner_id,
            conversation_store=durable,
            clock=lambda: fixed_time + timedelta(minutes=1),
        ).model_activity(
            principal,
            window_start=fixed_time - timedelta(minutes=1),
            window_end=fixed_time + timedelta(minutes=1),
        )
        assert activity.total_runs == 1
        assert activity.external_disclosure_runs == 1
        assert activity.entries[0].disclosure is not None
        assert tuple(
            reference.assertion_id
            for reference in activity.entries[0].disclosure.memory_references
        ) == (memory.assertion_id,)
        durable.complete_turn(completed)
    finally:
        connection.execute("RESET ROLE")

    counts = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM melloa.conversation_threads),
            (SELECT count(*) FROM melloa.conversation_messages),
            (SELECT count(*) FROM melloa.conversation_turns),
            (SELECT count(*) FROM melloa.conversation_inbound_idempotency),
            (SELECT count(*) FROM melloa.conversation_turn_triggers),
            (SELECT count(*) FROM melloa.model_runs),
            (SELECT count(*) FROM melloa.retrieval_manifests),
            (SELECT count(*) FROM melloa.model_disclosures),
            (SELECT count(*) FROM melloa.jobs_outbox)
        """
    ).fetchone()
    assert counts == (1, 2, 1, 1, 1, 1, 1, 1, 1)
    disclosure = connection.execute(
        "SELECT evidence_ids, document FROM melloa.model_disclosures"
    ).fetchone()
    assert disclosure[0] == [memory.assertion_id]
    assert disclosure[1]["disclosed_evidence_ids"] == [memory.assertion_id]
    assert disclosure[1]["output_evidence_ids"] == []

    changed_at = fixed_time + timedelta(minutes=1)
    changed_by = record_id("correction", 1)
    disputed_state = AssertionStateProjection(
        assertion_id=memory.assertion_id,
        current_status=AssertionStatus.DISPUTED,
        changed_by_record_id=changed_by,
        changed_at=changed_at,
        version=2,
    )
    disputed_change = AssertionStateChange(
        change_id=record_id("state_change", 99),
        assertion_id=memory.assertion_id,
        previous_status=AssertionStatus.CONFIRMED,
        new_status=AssertionStatus.DISPUTED,
        changed_by_record_id=changed_by,
        reason="assertion.disputed",
        changed_at=changed_at,
        version=2,
    )
    connection.execute(
        """
        SELECT melloa.transition_assertion_state(
            %(change_id)s, %(assertion_id)s, 1, 'confirmed', 'disputed', NULL,
            %(changed_by)s, %(reason)s, %(changed_at)s,
            %(projection_document)s, %(change_document)s
        )
        """,
        {
            "change_id": disputed_change.change_id,
            "assertion_id": memory.assertion_id,
            "changed_by": changed_by,
            "reason": disputed_change.reason,
            "changed_at": changed_at,
            "projection_document": Jsonb(disputed_state.model_dump(mode="json")),
            "change_document": Jsonb(disputed_change.model_dump(mode="json")),
        },
    )
    projected = repository.list_assertions(owner_id)
    assert projected[0].status is AssertionStatus.DISPUTED
    after_correction = PolicyConstrainedRetriever(
        repository,
        clock=lambda: fixed_time,
    ).retrieve(
        requester_id=intelligence_id,
        subject_id=owner_id,
        query="finances",
        purpose="conversation.owner-reply",
        allowed_sensitivities=frozenset(
            {Sensitivity.PUBLIC, Sensitivity.INTERNAL, Sensitivity.PERSONAL}
        ),
    )
    assert after_correction.citations == ()
    assert after_correction.excluded_assertion_ids == (memory.assertion_id,)


def test_postgres_outbound_completion_is_atomic_idempotent_and_role_scoped(
    connection,
    fixed_time,
) -> None:
    thread, message, work = _insert_delivery_fixture(connection, fixed_time)
    store = PostgresDeliveryStore(connection)

    connection.execute("SET ROLE melloa_core")
    try:
        enqueued = store.enqueue(work, max_attempts=2)
        duplicate = store.enqueue(work, max_attempts=2)
        assert enqueued.created is True
        assert duplicate.created is False
        assert duplicate.status == enqueued.status
    finally:
        connection.execute("RESET ROLE")

    connection.execute("SET ROLE melloa_worker")
    try:
        claim = store.claim_work(
            work.work_id,
            lease_owner=record_id("deliveryworker", 1),
            now=fixed_time,
            lease_expires_at=fixed_time + timedelta(seconds=5),
        )
        assert claim is not None
    finally:
        connection.execute("RESET ROLE")

    planned = _successful_delivery_attempt(
        claim.work,
        attempt=claim.attempt,
        started_at=fixed_time,
        receipt_number=1,
    )
    _request, conflicting_decision = _delivery_authorization(
        message,
        fixed_time,
        number=99,
    )
    connection.execute(
        """
        INSERT INTO melloa.policy_decisions (
            decision_id, request_id, action_hash, effect, policy_version,
            reason_codes, decided_at, expires_at, document
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            conflicting_decision.decision_id,
            conflicting_decision.request_id,
            conflicting_decision.action_hash,
            conflicting_decision.effect.value,
            conflicting_decision.policy_version,
            list(conflicting_decision.reason_codes),
            conflicting_decision.decided_at,
            conflicting_decision.expires_at,
            Jsonb(conflicting_decision.model_dump(mode="json")),
        ),
    )
    assert planned.execution_receipt is not None
    connection.execute(
        """
        INSERT INTO melloa.executed_actions (
            action_id, decision_id, action_hash, capability_id, operation,
            executed_at, result_document
        ) VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb)
        """,
        (
            planned.execution_receipt.action_id,
            conflicting_decision.decision_id,
            conflicting_decision.action_hash,
            "client.conflict",
            "messages.send",
            fixed_time,
        ),
    )

    connection.execute("SET ROLE melloa_worker")
    try:
        with pytest.raises(DeliveryConflictError, match="execution receipt"):
            store.complete(claim, planned)
    finally:
        connection.execute("RESET ROLE")

    rolled_back = connection.execute(
        """
        SELECT
            (SELECT state FROM melloa.jobs_outbox WHERE work_id = %s),
            (SELECT count(*) FROM melloa.delivery_attempts WHERE outbound_work_id = %s),
            (SELECT count(*) FROM melloa.delivery_work_attempts WHERE work_id = %s),
            (SELECT count(*) FROM melloa.executed_actions WHERE outbound_work_id = %s)
        """,
        (work.work_id, work.work_id, work.work_id, work.work_id),
    ).fetchone()
    assert rolled_back == ("running", 0, 0, 0)

    successful = _successful_delivery_attempt(
        claim.work,
        attempt=claim.attempt,
        started_at=fixed_time,
        receipt_number=2,
    )
    connection.execute("SET ROLE melloa_worker")
    try:
        completed = store.complete(claim, successful)
        assert store.complete(claim, successful) == completed
    finally:
        connection.execute("RESET ROLE")

    assert completed.state is DeliveryWorkState.COMPLETED
    assert completed.attempt_count == 1
    assert store.status(work.work_id) == completed
    assert store.list_status(thread.thread_id) == (completed,)
    assert store.find_by_message(message.message_id) == (completed,)
    persisted = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM melloa.outbound_deliveries WHERE work_id = %s),
            (SELECT count(*) FROM melloa.delivery_attempts WHERE outbound_work_id = %s),
            (SELECT count(*) FROM melloa.delivery_work_attempts WHERE work_id = %s),
            (SELECT count(*) FROM melloa.executed_actions WHERE outbound_work_id = %s),
            (SELECT payload ->> 'work_id' FROM melloa.jobs_outbox WHERE work_id = %s)
        """,
        (work.work_id, work.work_id, work.work_id, work.work_id, work.work_id),
    ).fetchone()
    assert persisted == (1, 1, 1, 1, work.work_id)
    with pytest.raises(psycopg.Error, match="append-only"):
        connection.execute(
            """
            UPDATE melloa.delivery_work_attempts
               SET error_code = 'tampered'
             WHERE work_id = %s
            """,
            (work.work_id,),
        )

    connection.execute("SET ROLE melloa_readonly")
    try:
        assert store.status(work.work_id) == completed
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE melloa.outbound_deliveries
                   SET destination_ref = 'other'
                 WHERE work_id = %s
                """,
                (work.work_id,),
            )
    finally:
        connection.execute("RESET ROLE")


def test_postgres_outbound_lease_expiry_requires_core_reauthorization(
    connection,
    fixed_time,
) -> None:
    _thread, message, work = _insert_delivery_fixture(connection, fixed_time)
    store = PostgresDeliveryStore(
        connection,
        id_factory=lambda prefix: record_id(prefix, 90),
    )

    connection.execute("SET ROLE melloa_core")
    try:
        store.enqueue(work, max_attempts=1)
    finally:
        connection.execute("RESET ROLE")

    connection.execute("SET ROLE melloa_worker")
    try:
        first_claim = store.claim_work(
            work.work_id,
            lease_owner=record_id("deliveryworker", 1),
            now=fixed_time,
            lease_expires_at=fixed_time + timedelta(seconds=1),
        )
        assert first_claim is not None
        assert store.claim_next_work(
            lease_owner=record_id("deliveryworker", 2),
            now=fixed_time + timedelta(seconds=2),
            lease_expires_at=fixed_time + timedelta(seconds=3),
        ) is None
        dead = store.status(work.work_id)
    finally:
        connection.execute("RESET ROLE")

    assert dead.state is DeliveryWorkState.DEAD
    assert dead.attempts[0].error_code == "delivery.lease_expired"
    resume_at = fixed_time + timedelta(seconds=2)
    resumption = _delivery_resumption(
        work,
        message,
        requested_at=resume_at,
        prior_attempts=1,
        added_attempts=2,
    )

    connection.execute("SET ROLE melloa_worker")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            store.resume(
                work.work_id,
                resumption,
                available_at=resume_at,
                added_attempts=2,
            )
    finally:
        connection.execute("RESET ROLE")
    assert store.status(work.work_id) == dead

    connection.execute("SET ROLE melloa_core")
    try:
        resumed = store.resume(
            work.work_id,
            resumption,
            available_at=resume_at,
            added_attempts=2,
        )
    finally:
        connection.execute("RESET ROLE")
    assert resumed.state is DeliveryWorkState.READY
    assert resumed.max_attempts == 3
    assert resumed.current_policy_decision_id == resumption.policy_decision.decision_id

    connection.execute("SET ROLE melloa_worker")
    try:
        second_claim = store.claim_work(
            work.work_id,
            lease_owner=record_id("deliveryworker", 2),
            now=resume_at,
            lease_expires_at=resume_at + timedelta(seconds=1),
        )
        assert second_claim is not None
        successful = _successful_delivery_attempt(
            second_claim.work,
            attempt=second_claim.attempt,
            started_at=resume_at,
            receipt_number=3,
        )
        completed = store.complete(second_claim, successful)
    finally:
        connection.execute("RESET ROLE")

    assert completed.state is DeliveryWorkState.COMPLETED
    assert tuple(attempt.outcome for attempt in completed.attempts) == (
        DeliveryWorkOutcome.DEAD,
        DeliveryWorkOutcome.SUCCEEDED,
    )
    counts = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM melloa.policy_decisions),
            (SELECT count(*) FROM melloa.delivery_work_resumptions WHERE work_id = %s),
            (SELECT count(*) FROM melloa.delivery_work_attempts WHERE work_id = %s)
        """,
        (work.work_id, work.work_id),
    ).fetchone()
    assert counts == (2, 1, 2)


def test_postgres_mvp_state_survives_core_restart(database_dsn, fixed_time) -> None:
    bootstrap_token = "durable-owner-bootstrap-token-value-0001"
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.postgres-mvp-restart",
        ),
        receipt_hash="sha256:" + "9" * 64,
    )

    with ExitStack() as first_run:
        first_connections = tuple(
            first_run.enter_context(psycopg.connect(database_dsn, autocommit=True))
            for _ in range(4)
        )
        for database in first_connections:
            database.execute("SET ROLE melloa_core")
        first_stores = build_postgres_mvp_stores(
            *first_connections,
            clock=lambda: fixed_time,
        )
        first_runtime = build_mvp_runtime(
            guardian,
            bootstrap_token,
            durable_stores=first_stores,
            clock=lambda: fixed_time,
        )
        first_client = first_run.enter_context(
            TestClient(first_runtime.app, base_url="https://testserver")
        )
        login = first_client.post(
            "/api/v1/auth/session",
            json={"credential": bootstrap_token},
        )
        assert login.status_code == 200
        headers = {"X-Melloa-CSRF": login.json()["csrf_token"]}
        thread = first_client.post(
            "/api/v1/conversations",
            headers=headers,
            json={
                "title": "Restart durability",
                "sensitivity": "personal",
                "retention_policy": "retention.owner-conversation",
            },
        )
        assert thread.status_code == 201
        thread_id = thread.json()["thread_id"]
        reply = first_client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=headers,
            json={
                "text": "Preserve this canonical turn across restart.",
                "idempotency_key": "postgres-mvp:restart-message:1",
            },
        )
        assert reply.status_code == 200
        assert reply.json()["processing"]["state"] == "completed"
        inbound_message_id = reply.json()["inbound_message"]["message_id"]
        output_message_id = reply.json()["output_message"]["message_id"]
        turn_id = reply.json()["turn"]["turn_id"]
        delivery = first_client.post(
            f"/api/v1/conversations/{thread_id}/deliveries",
            headers=headers,
            json={
                "message_id": output_message_id,
                "client_adapter": "client.fake",
                "destination_ref": "synthetic:owner",
                "idempotency_key": "postgres-mvp:restart-delivery:1",
            },
        )
        assert delivery.status_code == 200
        assert delivery.json()["delivery"]["state"] == "completed"
        work_id = delivery.json()["delivery"]["work_id"]
        correction = first_client.post(
            f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}/corrections",
            headers=headers,
            json={
                "value": {"activity": "walking", "fixture": True},
                "expected_version": 1,
            },
        )
        assert correction.status_code == 201

    with ExitStack() as second_run:
        second_connections = tuple(
            second_run.enter_context(psycopg.connect(database_dsn, autocommit=True))
            for _ in range(4)
        )
        for database in second_connections:
            database.execute("SET ROLE melloa_core")
        second_stores = build_postgres_mvp_stores(
            *second_connections,
            clock=lambda: fixed_time + timedelta(seconds=1),
        )
        second_runtime = build_mvp_runtime(
            guardian,
            bootstrap_token,
            durable_stores=second_stores,
            clock=lambda: fixed_time + timedelta(seconds=1),
        )
        second_client = second_run.enter_context(
            TestClient(second_runtime.app, base_url="https://testserver")
        )
        assert second_client.get("/api/v1/conversations").status_code == 401
        login = second_client.post(
            "/api/v1/auth/session",
            json={"credential": bootstrap_token},
        )
        assert login.status_code == 200
        headers = {"X-Melloa-CSRF": login.json()["csrf_token"]}

        threads = second_client.get("/api/v1/conversations")
        assert threads.status_code == 200
        assert any(candidate["thread_id"] == thread_id for candidate in threads.json())
        messages = second_client.get(f"/api/v1/conversations/{thread_id}/messages")
        assert [message["message_id"] for message in messages.json()] == [
            inbound_message_id,
            output_message_id,
        ]
        turns = second_client.get(f"/api/v1/conversations/{thread_id}/turns")
        assert [turn["turn_id"] for turn in turns.json()] == [turn_id]
        activity = second_client.get("/api/v1/inspection/model-activity")
        assert activity.status_code == 200
        assert activity.json()["total_runs"] == 1
        assert activity.json()["entries"][0]["turn_id"] == turn_id
        duplicate = second_client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=headers,
            json={
                "text": "Preserve this canonical turn across restart.",
                "idempotency_key": "postgres-mvp:restart-message:1",
            },
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate"] is True
        assert duplicate.json()["turn"]["turn_id"] == turn_id
        deliveries = second_client.get(
            f"/api/v1/conversations/{thread_id}/deliveries"
        )
        assert deliveries.status_code == 200
        assert [item["work_id"] for item in deliveries.json()] == [work_id]
        memory = second_client.get(f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}")
        assert memory.status_code == 200
        assert memory.json()["current_state"]["version"] == 2
        assert memory.json()["current_state"]["current_status"] == "superseded"
        health = second_client.get("/api/v1/inspection/health")
        assert health.status_code == 200
        components = {
            component["component_id"]: component for component in health.json()["components"]
        }
        assert components["database.postgresql-mvp"]["state"] == "healthy"
        assert components["storage.process-local-control-state"]["state"] == "degraded"


def _telegram_update(
    observed_at: datetime,
    update_id: int,
    text: str,
) -> TelegramInboundUpdate:
    return TelegramInboundUpdate(
        update_id=update_id,
        message=TelegramInboundMessage(
            telegram_message_id=update_id,
            sender_user_id=1001,
            chat_id=1001,
            chat_type=TelegramChatType.PRIVATE,
            sent_at=observed_at,
            text=text,
        ),
        received_at=observed_at,
        raw_size_bytes=128,
        source_payload_hash=sha256_digest(
            f"postgres-telegram:{update_id}:{text}".encode()
        ),
    )


def _telegram_principal(observed_at: datetime, number: int) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=SYNTHETIC_OWNER_ID,
        session_id=record_id("session", number),
        authentication_method="auth.owner-bootstrap",
        authenticated_at=observed_at,
        reauthenticated_until=observed_at + timedelta(minutes=5),
        expires_at=observed_at + timedelta(hours=1),
    )


def test_postgres_telegram_state_survives_core_restarts(database_dsn, fixed_time) -> None:
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.postgres-telegram-restart",
        ),
        receipt_hash="sha256:" + "8" * 64,
    )

    with ExitStack() as first_run:
        connections = tuple(
            first_run.enter_context(psycopg.connect(database_dsn, autocommit=True))
            for _ in range(4)
        )
        for database in connections:
            database.execute("SET ROLE melloa_core")
        stores = build_postgres_mvp_stores(*connections, clock=lambda: fixed_time)
        runtime = build_mvp_runtime(
            guardian,
            "durable-owner-bootstrap-token-value-0001",
            durable_stores=stores,
            clock=lambda: fixed_time,
        )
        runtime.telegram_source.add_update(_telegram_update(fixed_time, 1, "/start"))
        start_cycle = runtime.telegram_worker.poll_once()
        candidate_id = start_cycle.outcomes[0].receipt.pairing_candidate_id
        assert candidate_id is not None
        challenge = runtime.telegram_challenge_publisher.challenge_for(candidate_id)
        pairing = runtime.telegram_pairing_service.confirm(
            _telegram_principal(fixed_time, 1),
            candidate_id,
            challenge.confirmation_code,
        )

        runtime.telegram_source.add_update(
            _telegram_update(fixed_time, 2, "Preserve this Telegram turn.")
        )
        text_cycle = runtime.telegram_worker.poll_once()
        canonical = text_cycle.outcomes[0].canonical_message
        assert canonical is not None
        processed = runtime.app.state.conversation_service.process_ready()
        assert len(processed) == 1
        completed = stores.conversation_store.completed_turn_for_trigger(canonical.message_id)
        assert completed is not None
        output_message_id = completed.output_message.message_id
        assert stores.telegram_poll_state_store.read_state(
            SYNTHETIC_TELEGRAM_ADAPTER_ID
        ).next_offset == 3

    second_time = fixed_time + timedelta(seconds=1)
    with ExitStack() as second_run:
        connections = tuple(
            second_run.enter_context(psycopg.connect(database_dsn, autocommit=True))
            for _ in range(4)
        )
        for database in connections:
            database.execute("SET ROLE melloa_core")
        stores = build_postgres_mvp_stores(*connections, clock=lambda: second_time)
        runtime = build_mvp_runtime(
            guardian,
            "durable-owner-bootstrap-token-value-0001",
            durable_stores=stores,
            clock=lambda: second_time,
        )

        assert runtime.telegram_pairing_service.pairing_for_ingestion() == pairing
        state = stores.telegram_poll_state_store.read_state(SYNTHETIC_TELEGRAM_ADAPTER_ID)
        assert state.next_offset == 3
        assert state.revision == 2
        assert stores.telegram_poll_state_store.get_update(
            SYNTHETIC_TELEGRAM_ADAPTER_ID,
            2,
        ) == _telegram_update(fixed_time, 2, "Preserve this Telegram turn.")
        receipt = stores.telegram_poll_state_store.get_receipt(
            SYNTHETIC_TELEGRAM_ADAPTER_ID,
            2,
        )
        assert receipt is not None
        assert stores.telegram_poll_state_store.list_ingested_receipts(
            SYNTHETIC_TELEGRAM_ADAPTER_ID
        ) == (receipt,)
        completed = stores.conversation_store.completed_turn_for_trigger(canonical.message_id)
        assert completed is not None
        assert completed.output_message.message_id == output_message_id
        revoked = runtime.telegram_pairing_service.revoke(
            _telegram_principal(second_time, 2),
            pairing.pairing_id,
        )
        assert revoked.revoked_at == second_time

    third_time = fixed_time + timedelta(seconds=2)
    with ExitStack() as third_run:
        connections = tuple(
            third_run.enter_context(psycopg.connect(database_dsn, autocommit=True))
            for _ in range(4)
        )
        for database in connections:
            database.execute("SET ROLE melloa_core")
        stores = build_postgres_mvp_stores(*connections, clock=lambda: third_time)
        runtime = build_mvp_runtime(
            guardian,
            "durable-owner-bootstrap-token-value-0001",
            durable_stores=stores,
            clock=lambda: third_time,
        )

        assert runtime.telegram_pairing_service.pairing_for_ingestion() is None
        persisted = stores.telegram_pairing_store.get_pairing(
            SYNTHETIC_TELEGRAM_ADAPTER_ID,
            pairing.pairing_id,
        )
        assert persisted.revoked_at == second_time
        assert stores.telegram_poll_state_store.read_state(
            SYNTHETIC_TELEGRAM_ADAPTER_ID
        ).next_offset == 3
