from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
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
from melloa.ports.delivery import DeliveryConflictError
from melloa.ports.memory import (
    AssertionCorrectionWrite,
    AssertionStateTransitionWrite,
    MemoryConflictError,
)
from tests.conftest import record_id


@pytest.fixture
def connection():
    dsn = os.environ.get("MELLOA_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("MELLOA_TEST_DATABASE_DSN is required for PostgreSQL integration tests")
    with psycopg.connect(dsn, autocommit=True) as database:
        yield database


@pytest.fixture(autouse=True)
def reset_append_tables(connection) -> None:
    connection.execute(
        """
        TRUNCATE
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
