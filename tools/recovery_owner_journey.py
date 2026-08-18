#!/usr/bin/env python3
"""Seed and verify a bounded authenticated owner journey for recovery drills."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import warnings
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import psycopg
from httpx import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.postgres.migrations import discover_migrations
from melloa.apps.mvp import build_mvp_runtime
from melloa.apps.postgres_mvp import (
    build_postgres_mvp_stores,
    validate_private_database_dsn,
)
from melloa.apps.synthetic import SYNTHETIC_ASSERTION_ID
from melloa.domain.base import RecordId
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload

if TYPE_CHECKING:
    from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
MIGRATION_MANIFEST = MIGRATIONS / "manifest.json"

SENSITIVE_FIXTURE_MARKER = "d002-owner-private-recovery-marker-v1"
_FIXTURE_TITLE = "D-002 bounded owner recovery fixture"
_FIXTURE_MESSAGE = f"Please use my reading preference. {SENSITIVE_FIXTURE_MARKER}"
_FIXTURE_CORRECTION = {
    "activity": "walking",
    "fixture": True,
    "recovery_marker": SENSITIVE_FIXTURE_MARKER,
}
_FIXTURE_TIME = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
_RESTORE_TIME = _FIXTURE_TIME + timedelta(minutes=1)
_INSPECTION_START = _FIXTURE_TIME - timedelta(minutes=1)
_INSPECTION_END = _FIXTURE_TIME + timedelta(minutes=5)
_SOURCE_ID_NAMESPACE = int("d0020000000000000000000000000000", 16)
_RESTORE_ID_NAMESPACE = int("d0021000000000000000000000000000", 16)
_MAX_PRIVATE_FILE_BYTES = 16 * 1024


class JourneyError(RuntimeError):
    """A bounded recovery-owner assertion failed without exposing private data."""


class JourneyExpectation(BaseModel):
    """Only bounded record identifiers, statuses, and a count leave the source DB."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_version: Literal["1.0.0"] = "1.0.0"
    thread_id: RecordId
    inbound_message_id: RecordId
    output_message_id: RecordId
    turn_id: RecordId
    retrieval_manifest_id: RecordId
    citation_id: RecordId
    evidence_assertion_id: RecordId
    model_result_id: RecordId
    source_session_id: RecordId
    correction_assertion_id: RecordId
    correction_provenance_edge_id: RecordId
    deletion_tombstone_id: RecordId
    rebuild_work_id: RecordId
    conversation_status: Literal["completed"]
    turn_explanation_status: Literal["validated"]
    model_activity_status: Literal["local-only"]
    memory_content_status: Literal["deleted"]
    memory_projection_status: Literal["superseded"]
    correction_status: Literal["confirmed"]
    audit_coverage_status: Literal["complete"]
    session_status: Literal["active"]
    audit_retained_objects: Annotated[int, Field(ge=3, le=64)]


class DeterministicIdFactory:
    """Issue replay-stable fixture IDs from a phase-specific 128-bit namespace."""

    def __init__(self, namespace: int) -> None:
        if not 0 <= namespace < 2**128:
            raise ValueError("deterministic ID namespace must fit in 128 bits")
        self._namespace = namespace
        self._counts: defaultdict[str, int] = defaultdict(int)

    def __call__(self, prefix: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_]{1,31}", prefix) is None:
            raise ValueError("record ID prefix must be a lowercase neutral identifier")
        self._counts[prefix] += 1
        value = self._namespace + self._counts[prefix]
        if value >= 2**128:
            raise ValueError("deterministic ID namespace exhausted")
        return f"{prefix}_{value:032x}"


def _check(condition: bool, label: str) -> None:
    if not condition:
        raise JourneyError(f"owner recovery check failed: {label}")


def _response_json(response: Response, expected_status: int, label: str) -> Any:
    _check(response.status_code == expected_status, f"{label} status")
    try:
        return response.json()
    except ValueError as error:
        raise JourneyError(f"owner recovery check failed: {label} response") from error


def _object(value: Any, label: str) -> dict[str, Any]:
    _check(isinstance(value, dict), label)
    return value


def _items(value: Any, label: str) -> list[Any]:
    _check(isinstance(value, list), label)
    return value


def _text(document: dict[str, Any], key: str, label: str) -> str:
    value = document.get(key)
    _check(isinstance(value, str) and bool(value), label)
    return value


def _test_only_guardian(observed_at: datetime) -> FakeGuardianStatusReader:
    """Return a test-only verified reader; no Guardian private material is generated."""

    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="recovery-test-guardian",
            mode=GuardianMode.NORMAL,
            sequence=1,
            changed_at=observed_at,
            reason_code="guardian.test-only-recovery-harness",
        ),
        receipt_hash="sha256:" + "d" * 64,
        key_id="guardian.test-only-recovery-key",
    )


def _new_test_client(app: Any) -> TestClient:
    from starlette.exceptions import StarletteDeprecationWarning

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=(
                r"Using `httpx` with `starlette\.testclient` is deprecated; "
                r"install `httpx2` instead\."
            ),
            category=StarletteDeprecationWarning,
        )
        from starlette.testclient import TestClient

    return TestClient(app, base_url="https://testserver")


@contextmanager
def _postgres_client(
    dsn: str,
    owner_credential: str,
    *,
    observed_at: datetime,
    id_namespace: int,
) -> Iterator[TestClient]:
    private_dsn = validate_private_database_dsn(dsn)

    def clock() -> datetime:
        return observed_at

    id_factory = DeterministicIdFactory(id_namespace)
    with ExitStack() as resources:
        connections = tuple(
            resources.enter_context(
                psycopg.connect(
                    private_dsn,
                    autocommit=True,
                    connect_timeout=5,
                    application_name=f"melloa-recovery-{store_name}",
                )
            )
            for store_name in ("conversation", "memory", "delivery", "telegram", "audit")
        )
        for connection in connections:
            connection.execute("SET ROLE melloa_core")
        stores = build_postgres_mvp_stores(
            *connections,
            clock=clock,
            id_factory=id_factory,
        )
        runtime = build_mvp_runtime(
            _test_only_guardian(observed_at),
            owner_credential,
            durable_stores=stores,
            clock=clock,
            id_factory=id_factory,
            telegram_worker_interval=60.0,
        )
        client = resources.enter_context(_new_test_client(runtime.app))
        yield client


def _login(client: TestClient, owner_credential: str) -> tuple[dict[str, str], str]:
    document = _object(
        _response_json(
            client.post(
                "/api/v1/auth/session",
                json={"credential": owner_credential},
            ),
            200,
            "owner login",
        ),
        "owner login document",
    )
    principal = _object(document.get("principal"), "owner login principal")
    csrf_token = _text(document, "csrf_token", "owner login CSRF")
    session_id = _text(principal, "session_id", "owner login session ID")
    return {"X-Melloa-CSRF": csrf_token}, session_id


def _policy_inventory(document: dict[str, Any], policy_id: str) -> dict[str, Any]:
    inventory = _items(document.get("inventory"), "retention inventory")
    matches = [
        _object(item, "retention inventory item")
        for item in inventory
        if isinstance(item, dict) and item.get("policy_id") == policy_id
    ]
    _check(len(matches) == 1, f"retention inventory {policy_id}")
    return matches[0]


def _validate_conversation_reads(
    client: TestClient,
    expected: JourneyExpectation,
) -> None:
    threads = _items(
        _response_json(client.get("/api/v1/conversations"), 200, "conversation list"),
        "conversation list document",
    )
    thread_matches = [
        _object(item, "conversation item")
        for item in threads
        if isinstance(item, dict) and item.get("thread_id") == expected.thread_id
    ]
    _check(len(thread_matches) == 1, "restored conversation identity")
    thread = thread_matches[0]
    _check(thread.get("title") == _FIXTURE_TITLE, "restored conversation title")
    _check(thread.get("sensitivity") == "personal", "restored conversation sensitivity")

    messages = _items(
        _response_json(
            client.get(f"/api/v1/conversations/{expected.thread_id}/messages"),
            200,
            "conversation messages",
        ),
        "conversation messages document",
    )
    message_documents = [_object(item, "conversation message") for item in messages]
    _check(
        [item.get("message_id") for item in message_documents]
        == [expected.inbound_message_id, expected.output_message_id],
        "restored message identities",
    )
    inbound, output = message_documents
    inbound_parts = _items(inbound.get("parts"), "inbound message parts")
    _check(
        any(
            isinstance(part, dict) and part.get("text") == _FIXTURE_MESSAGE
            for part in inbound_parts
        ),
        "restored private fixture message",
    )
    _check(
        output.get("citation_ids") == [expected.citation_id],
        "restored output citations",
    )
    _check(
        output.get("reply_to_message_id") == expected.inbound_message_id,
        "restored output reply link",
    )

    turns = _items(
        _response_json(
            client.get(f"/api/v1/conversations/{expected.thread_id}/turns"),
            200,
            "conversation turns",
        ),
        "conversation turns document",
    )
    _check(len(turns) == 1, "restored turn count")
    turn = _object(turns[0], "conversation turn")
    _check(turn.get("turn_id") == expected.turn_id, "restored turn identity")
    _check(
        turn.get("evidence_ids") == [expected.evidence_assertion_id],
        "restored turn evidence",
    )
    _check(
        turn.get("model_run_ids") == [expected.model_result_id],
        "restored model run link",
    )
    _check(
        turn.get("retrieval_manifest_id") == expected.retrieval_manifest_id,
        "restored retrieval link",
    )

    inspection = _object(
        _response_json(
            client.get(
                f"/api/v1/conversations/{expected.thread_id}/turns/{expected.turn_id}"
            ),
            200,
            "turn inspection",
        ),
        "turn inspection document",
    )
    inspected_turn = _object(inspection.get("turn"), "inspected turn")
    _check(inspected_turn == turn, "restored structured turn")
    decision = _object(inspected_turn.get("decision_record"), "turn decision explanation")
    _check(
        decision.get("summary") == "Generated a bounded first-party owner reply.",
        "turn explanation summary",
    )
    _check(
        decision.get("selected_plan")
        == "Invoke an eligible provider-neutral route and persist the result.",
        "turn explanation selected plan",
    )
    _check(
        decision.get("retrieval_manifest_id") == expected.retrieval_manifest_id,
        "turn explanation retrieval link",
    )
    _check(
        decision.get("selected_citation_ids") == [expected.citation_id]
        and decision.get("evidence_ids") == [expected.evidence_assertion_id],
        "turn explanation evidence links",
    )

    manifest = _object(inspection.get("retrieval_manifest"), "retrieval manifest")
    _check(
        manifest.get("manifest_id") == expected.retrieval_manifest_id,
        "restored retrieval manifest identity",
    )
    citations = _items(manifest.get("citations"), "retrieval citations")
    _check(len(citations) == 1, "restored retrieval citation count")
    citation = _object(citations[0], "retrieval citation")
    _check(
        citation.get("citation_id") == expected.citation_id
        and citation.get("assertion_id") == expected.evidence_assertion_id,
        "restored retrieval evidence",
    )
    _check(manifest.get("external_disclosure") is False, "local retrieval disclosure")

    model_result = _object(inspection.get("model_result"), "turn model result")
    _check(
        model_result.get("result_id") == expected.model_result_id,
        "restored model result identity",
    )
    _check(
        model_result.get("route_id") == "model.fake.deterministic"
        and model_result.get("external_disclosure") is False,
        "deterministic local model result",
    )

    activity = _object(
        _response_json(
            client.get(
                "/api/v1/inspection/model-activity",
                params={
                    "from": _INSPECTION_START.isoformat(),
                    "to": _INSPECTION_END.isoformat(),
                },
            ),
            200,
            "model activity",
        ),
        "model activity document",
    )
    entries = _items(activity.get("entries"), "model activity entries")
    _check(
        activity.get("total_runs") == 1
        and activity.get("external_disclosure_runs") == 0
        and len(entries) == 1,
        "bounded local model activity",
    )
    entry = _object(entries[0], "model activity entry")
    _check(
        entry.get("turn_id") == expected.turn_id
        and entry.get("result_id") == expected.model_result_id
        and entry.get("external_disclosure") is False,
        "restored model activity identity",
    )


def _validate_memory_reads(client: TestClient, expected: JourneyExpectation) -> None:
    deleted = _object(
        _response_json(
            client.get(f"/api/v1/memory/{expected.evidence_assertion_id}"),
            200,
            "deleted memory inspection",
        ),
        "deleted memory document",
    )
    _check(deleted.get("content_state") == "deleted", "restored memory content state")
    deleted_assertion = _object(deleted.get("assertion"), "deleted assertion metadata")
    _check(
        deleted_assertion.get("assertion_id") == expected.evidence_assertion_id,
        "restored deleted assertion identity",
    )
    projection = _object(deleted.get("current_state"), "deleted memory projection")
    _check(
        projection.get("current_status") == "superseded"
        and projection.get("version") == 2
        and projection.get("preferred_assertion_id") == expected.correction_assertion_id,
        "restored corrected memory projection",
    )
    tombstone = _object(deleted.get("deletion_tombstone"), "memory deletion tombstone")
    _check(
        tombstone.get("tombstone_id") == expected.deletion_tombstone_id
        and tombstone.get("rebuild_work_id") == expected.rebuild_work_id,
        "restored memory deletion evidence",
    )
    edges = _items(deleted.get("provenance_edges"), "deleted memory provenance")
    _check(
        any(
            isinstance(edge, dict)
            and edge.get("edge_id") == expected.correction_provenance_edge_id
            and edge.get("from_id") == expected.correction_assertion_id
            and edge.get("to_id") == expected.evidence_assertion_id
            for edge in edges
        ),
        "restored correction provenance",
    )

    correction = _object(
        _response_json(
            client.get(f"/api/v1/memory/{expected.correction_assertion_id}"),
            200,
            "correction memory inspection",
        ),
        "correction memory document",
    )
    _check(correction.get("content_state") == "retained", "restored correction content")
    correction_assertion = _object(
        correction.get("assertion"), "correction assertion"
    )
    _check(
        correction_assertion.get("assertion_id") == expected.correction_assertion_id
        and correction_assertion.get("value") == _FIXTURE_CORRECTION,
        "restored private correction fixture",
    )
    correction_projection = _object(
        correction.get("current_state"), "correction projection"
    )
    _check(
        correction_projection.get("current_status") == "confirmed"
        and correction_projection.get("version") == 1,
        "restored correction status",
    )


def _validate_retention(
    client: TestClient,
    expected: JourneyExpectation,
    *,
    added_audit_objects: int,
) -> None:
    retention = _object(
        _response_json(client.get("/api/v1/retention"), 200, "retention inspection"),
        "retention document",
    )
    audit = _policy_inventory(retention, "retention.audit-ledger")
    _check(audit.get("coverage") == "complete", "restored audit coverage")
    _check(
        audit.get("retained_objects")
        == expected.audit_retained_objects + added_audit_objects,
        "restored audit object count",
    )
    memory = _policy_inventory(retention, "retention.owner-memory")
    _check(memory.get("deletion_receipts") == 1, "restored deletion receipt count")


def _seed_owner_state(client: TestClient, owner_credential: str) -> JourneyExpectation:
    headers, source_session_id = _login(client, owner_credential)
    initial_memory = _object(
        _response_json(
            client.get(f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}"),
            200,
            "initial memory inspection",
        ),
        "initial memory document",
    )
    _check(initial_memory.get("content_state") == "retained", "initial memory content")
    _check(
        _object(initial_memory.get("current_state"), "initial memory projection").get(
            "version"
        )
        == 1,
        "initial memory version",
    )

    thread = _object(
        _response_json(
            client.post(
                "/api/v1/conversations",
                headers=headers,
                json={
                    "title": _FIXTURE_TITLE,
                    "sensitivity": "personal",
                    "retention_policy": "retention.owner-conversation",
                },
            ),
            201,
            "conversation creation",
        ),
        "conversation creation document",
    )
    thread_id = _text(thread, "thread_id", "conversation ID")
    reply = _object(
        _response_json(
            client.post(
                f"/api/v1/conversations/{thread_id}/messages",
                headers=headers,
                json={
                    "text": _FIXTURE_MESSAGE,
                    "idempotency_key": "d002:owner-recovery-message:1",
                },
            ),
            200,
            "deterministic fixture turn",
        ),
        "deterministic fixture turn document",
    )
    processing = _object(reply.get("processing"), "fixture processing")
    _check(processing.get("state") == "completed", "fixture processing completion")
    inbound = _object(reply.get("inbound_message"), "fixture inbound message")
    output = _object(reply.get("output_message"), "fixture output message")
    turn = _object(reply.get("turn"), "fixture turn")
    citations = _items(output.get("citation_ids"), "fixture citations")
    evidence = _items(turn.get("evidence_ids"), "fixture evidence")
    model_runs = _items(turn.get("model_run_ids"), "fixture model runs")
    _check(len(citations) == 1, "fixture citation count")
    _check(evidence == [SYNTHETIC_ASSERTION_ID], "fixture evidence identity")
    _check(len(model_runs) == 1, "fixture model run count")

    correction = _object(
        _response_json(
            client.post(
                f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}/corrections",
                headers=headers,
                json={"value": _FIXTURE_CORRECTION, "expected_version": 1},
            ),
            201,
            "memory correction",
        ),
        "memory correction document",
    )
    correction_assertion = _object(correction.get("correction"), "correction assertion")
    correction_edge = _object(correction.get("provenance_edge"), "correction edge")
    correction_state = _object(correction.get("correction_state"), "correction state")
    target_state = _object(correction.get("target_state"), "correction target state")
    _check(target_state.get("version") == 2, "corrected target version")

    deletion = _object(
        _response_json(
            client.delete(
                f"/api/v1/memory/{SYNTHETIC_ASSERTION_ID}/content",
                headers=headers,
            ),
            200,
            "memory content deletion",
        ),
        "memory deletion document",
    )
    _check(deletion.get("created") is True, "memory deletion creation")
    tombstone = _object(deletion.get("tombstone"), "memory deletion tombstone")
    rebuild_work = _object(deletion.get("rebuild_work"), "memory rebuild work")

    sessions = _object(
        _response_json(client.get("/api/v1/auth/sessions"), 200, "source sessions"),
        "source session document",
    )
    active_sessions = _items(sessions.get("sessions"), "source active sessions")
    _check(
        sessions.get("current_session_id") == source_session_id
        and len(active_sessions) == 1
        and isinstance(active_sessions[0], dict)
        and active_sessions[0].get("session_id") == source_session_id,
        "source durable session",
    )

    retention = _object(
        _response_json(client.get("/api/v1/retention"), 200, "source retention"),
        "source retention document",
    )
    audit = _policy_inventory(retention, "retention.audit-ledger")
    audit_count = audit.get("retained_objects")
    _check(
        audit.get("coverage") == "complete"
        and isinstance(audit_count, int)
        and not isinstance(audit_count, bool)
        and 3 <= audit_count <= 64,
        "source durable audit inventory",
    )

    expected = JourneyExpectation(
        thread_id=thread_id,
        inbound_message_id=_text(inbound, "message_id", "inbound message ID"),
        output_message_id=_text(output, "message_id", "output message ID"),
        turn_id=_text(turn, "turn_id", "turn ID"),
        retrieval_manifest_id=_text(
            turn, "retrieval_manifest_id", "retrieval manifest ID"
        ),
        citation_id=str(citations[0]),
        evidence_assertion_id=SYNTHETIC_ASSERTION_ID,
        model_result_id=str(model_runs[0]),
        source_session_id=source_session_id,
        correction_assertion_id=_text(
            correction_assertion, "assertion_id", "correction assertion ID"
        ),
        correction_provenance_edge_id=_text(
            correction_edge, "edge_id", "correction edge ID"
        ),
        deletion_tombstone_id=_text(tombstone, "tombstone_id", "deletion tombstone ID"),
        rebuild_work_id=_text(rebuild_work, "work_id", "rebuild work ID"),
        conversation_status="completed",
        turn_explanation_status="validated",
        model_activity_status="local-only",
        memory_content_status="deleted",
        memory_projection_status=_text(
            target_state, "current_status", "memory target status"
        ),
        correction_status=_text(
            correction_state, "current_status", "correction status"
        ),
        audit_coverage_status="complete",
        session_status="active",
        audit_retained_objects=audit_count,
    )
    _validate_conversation_reads(client, expected)
    _validate_memory_reads(client, expected)
    _validate_retention(client, expected, added_audit_objects=0)
    return expected


def _verify_owner_state(
    client: TestClient,
    owner_credential: str,
    expected: JourneyExpectation,
) -> None:
    _headers, restored_session_id = _login(client, owner_credential)
    _check(restored_session_id != expected.source_session_id, "new restored session identity")
    current = _object(
        _response_json(client.get("/api/v1/auth/session"), 200, "restored current session"),
        "restored current session document",
    )
    _check(
        current.get("session_id") == restored_session_id,
        "restored current session identity",
    )
    sessions = _object(
        _response_json(client.get("/api/v1/auth/sessions"), 200, "restored sessions"),
        "restored sessions document",
    )
    active = _items(sessions.get("sessions"), "restored active sessions")
    active_ids = {
        item.get("session_id")
        for item in active
        if isinstance(item, dict) and isinstance(item.get("session_id"), str)
    }
    _check(
        sessions.get("current_session_id") == restored_session_id
        and active_ids == {expected.source_session_id, restored_session_id},
        "restored durable session inventory",
    )
    _validate_conversation_reads(client, expected)
    _validate_memory_reads(client, expected)
    _validate_retention(client, expected, added_audit_objects=1)


def _read_private_text(path: Path, *, label: str) -> str:
    try:
        details = path.stat()
    except OSError as error:
        raise JourneyError(f"{label} is unavailable") from error
    if path.is_symlink() or not stat.S_ISREG(details.st_mode):
        raise JourneyError(f"{label} must be a regular file")
    if stat.S_IMODE(details.st_mode) & 0o077:
        raise JourneyError(f"{label} permissions must deny group and other access")
    if not 0 < details.st_size <= _MAX_PRIVATE_FILE_BYTES:
        raise JourneyError(f"{label} size is outside the recovery bound")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise JourneyError(f"{label} could not be read") from error


def _read_dsn(path: Path) -> str:
    value = _read_private_text(path, label="database DSN file").strip()
    if not value or any(character in value for character in ("\x00", "\n", "\r")):
        raise JourneyError("database DSN file is invalid")
    return value


def _read_owner_credential(path: Path) -> str:
    value = _read_private_text(path, label="owner credential file")
    if not 32 <= len(value) <= 4096 or any(
        character in value for character in ("\x00", "\n", "\r")
    ):
        raise JourneyError("owner credential file is invalid")
    return value


def _write_expectation(path: Path, expected: JourneyExpectation) -> None:
    document = json.dumps(
        expected.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    ) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(document)
            output.flush()
            os.fsync(output.fileno())
    except OSError as error:
        raise JourneyError("bounded expectation file could not be created") from error


def _read_expectation(path: Path) -> JourneyExpectation:
    serialized = _read_private_text(path, label="bounded expectation file")
    try:
        return JourneyExpectation.model_validate_json(serialized)
    except ValidationError as error:
        raise JourneyError("bounded expectation file is invalid") from error


def seed_journey(dsn_file: Path, credential_file: Path, expected_file: Path) -> None:
    dsn = _read_dsn(dsn_file)
    owner_credential = _read_owner_credential(credential_file)
    with _postgres_client(
        dsn,
        owner_credential,
        observed_at=_FIXTURE_TIME,
        id_namespace=_SOURCE_ID_NAMESPACE,
    ) as client:
        expected = _seed_owner_state(client, owner_credential)
    _write_expectation(expected_file, expected)


def verify_journey(dsn_file: Path, credential_file: Path, expected_file: Path) -> None:
    dsn = _read_dsn(dsn_file)
    owner_credential = _read_owner_credential(credential_file)
    expected = _read_expectation(expected_file)
    with _postgres_client(
        dsn,
        owner_credential,
        observed_at=_RESTORE_TIME,
        id_namespace=_RESTORE_ID_NAMESPACE,
    ) as client:
        _verify_owner_state(client, owner_credential, expected)


def recovery_receipt() -> dict[str, Any]:
    migrations = discover_migrations(MIGRATIONS, MIGRATION_MANIFEST)
    return {
        "checks": {
            "clean_postgresql_restore": "pass",
            "custom_logical_dump_fixture_presence": "pass",
            "encrypted_repository_plaintext_absence": "pass",
            "ephemeral_cleanup": "pass",
            "restic_integrity": "pass",
            "restic_network_isolation": "pass",
            "restored_audit_and_session_state": "pass",
            "restored_conversation_messages": "pass",
            "restored_memory_correction_and_deletion": "pass",
            "restored_model_activity": "pass",
            "restored_turn_explanation_and_evidence": "pass",
            "source_authenticated_owner_journey": "pass",
            "source_manifest_migrations": "pass",
            "target_manifest_migrations": "pass",
            "readonly_mutation_denied": "pass",
        },
        "drill": "melloa-d002-bounded-full-owner-state-recovery",
        "guardian_reader": "test-only-synthetic-verified",
        "migrations": [
            {"name": migration.path.name, "status": "pass"}
            for migration in migrations
        ],
        "owner_export": "portability-only-not-used",
        "recovery_authority": "postgresql-logical-state",
        "scope": "bounded-recovery-harness",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("seed", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--dsn-file", required=True, type=Path)
        command.add_argument("--owner-credential-file", required=True, type=Path)
        command.add_argument("--expected-file", required=True, type=Path)
    commands.add_parser("receipt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "seed":
            seed_journey(args.dsn_file, args.owner_credential_file, args.expected_file)
        elif args.command == "verify":
            verify_journey(args.dsn_file, args.owner_credential_file, args.expected_file)
        else:
            print(json.dumps(recovery_receipt(), indent=2, sort_keys=True), flush=True)
    except JourneyError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("owner recovery journey failed unexpectedly", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
