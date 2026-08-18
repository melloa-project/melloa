from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from melloa.apps.mvp import build_mvp_runtime
from tools import recovery_owner_journey as recovery

_OWNER_CREDENTIAL = "d002-unit-owner-credential-value-0001"


def test_authenticated_owner_journey_is_bounded_and_reverifiable(tmp_path: Path) -> None:
    id_factory = recovery.DeterministicIdFactory(
        int("d0022000000000000000000000000000", 16)
    )
    runtime = build_mvp_runtime(
        recovery._test_only_guardian(recovery._FIXTURE_TIME),
        _OWNER_CREDENTIAL,
        clock=lambda: recovery._FIXTURE_TIME,
        id_factory=id_factory,
        telegram_worker_interval=60.0,
    )

    with recovery._new_test_client(runtime.app) as client:
        expected = recovery._seed_owner_state(client, _OWNER_CREDENTIAL)
        recovery._verify_owner_state(client, _OWNER_CREDENTIAL, expected)

    expectation_path = tmp_path / "expected-owner-state.json"
    recovery._write_expectation(expectation_path, expected)
    assert recovery._read_expectation(expectation_path) == expected
    assert stat.S_IMODE(expectation_path.stat().st_mode) == 0o600

    serialized = expectation_path.read_text(encoding="utf-8")
    assert recovery.SENSITIVE_FIXTURE_MARKER not in serialized
    for forbidden in (
        "credential",
        "csrf",
        "dsn",
        "dump",
        "message_text",
        "session_token",
        "sha256:",
    ):
        assert forbidden not in serialized.casefold()


def test_deterministic_id_factory_is_phase_scoped() -> None:
    first = recovery.DeterministicIdFactory(100)
    second = recovery.DeterministicIdFactory(200)

    assert first("thread") == "thread_00000000000000000000000000000065"
    assert first("thread") == "thread_00000000000000000000000000000066"
    assert first("message") == "message_00000000000000000000000000000065"
    assert second("thread") == "thread_000000000000000000000000000000c9"
    with pytest.raises(ValueError, match="prefix"):
        first("Invalid")


def test_receipt_lists_every_manifest_migration_without_private_values() -> None:
    receipt = recovery.recovery_receipt()

    assert [item["name"] for item in receipt["migrations"]] == [
        "0001_m0_foundation.sql",
        "0002_m1_conversation_retrieval.sql",
        "0003_m1_projection_trigger_privilege.sql",
        "0004_m1_assertion_state_history.sql",
        "0005_m1_outbound_delivery.sql",
        "0006_m1_assertion_content_boundary.sql",
        "0007_m1_telegram_durable_state.sql",
        "0008_m1_assertion_content_deletion.sql",
        "0009_m1_owner_sessions.sql",
        "0010_m1_owner_session_retention_cleanup.sql",
    ]
    assert all(item["status"] == "pass" for item in receipt["migrations"])
    assert set(receipt["checks"].values()) == {"pass"}
    assert receipt["checks"]["ephemeral_cleanup"] == "pass"
    assert receipt["recovery_authority"] == "postgresql-logical-state"
    assert receipt["owner_export"] == "portability-only-not-used"

    serialized = json.dumps(receipt, sort_keys=True).casefold()
    assert recovery.SENSITIVE_FIXTURE_MARKER not in serialized
    for forbidden in (
        "credential",
        "csrf",
        "dsn",
        "message_text",
        "session_token",
        "sha256:",
    ):
        assert forbidden not in serialized
