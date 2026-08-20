from __future__ import annotations

import json
import stat

import pytest

from tools import recovery_owner_journey as recovery


def test_recovery_expectation_contains_only_record_ids_and_is_private(tmp_path) -> None:
    expectation = recovery.JourneyExpectation(
        thread_id="thread_00000000000000000000000000000001",
        message_id="message_00000000000000000000000000000001",
        session_id="session_00000000000000000000000000000001",
        assertion_id="assertion_00000000000000000000000000000001",
        telegram_update_id=9_001,
    )
    path = tmp_path / "expectation.json"

    recovery._write_expectation(path, expectation)

    assert recovery._read_expectation(path) == expectation
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert recovery.SENSITIVE_FIXTURE_MARKER not in path.read_text(encoding="utf-8")


def test_recovery_receipt_tracks_only_current_migrations() -> None:
    receipt = recovery.recovery_receipt()

    assert [item["name"] for item in receipt["migrations"]] == [
        "0001_m0_foundation.sql",
        "0002_m1_conversation_retrieval.sql",
        "0003_m1_projection_trigger_privilege.sql",
        "0004_m1_assertion_state_history.sql",
        "0006_m1_assertion_content_boundary.sql",
        "0008_m1_assertion_content_deletion.sql",
        "0009_m1_owner_sessions.sql",
        "0010_m1_owner_session_retention_cleanup.sql",
        "0011_owner_conversation_deletion.sql",
        "0012_owner_telegram_channel.sql",
        "0013_owner_model_routes.sql",
        "0014_backup_sequence_privileges.sql",
        "0015_owner_self_changes.sql",
    ]
    assert set(receipt["checks"].values()) == {"pass"}
    assert recovery.SENSITIVE_FIXTURE_MARKER not in json.dumps(receipt)


def test_deterministic_restore_ids_are_prefix_scoped() -> None:
    ids = recovery.DeterministicIdFactory(100)

    assert ids("thread") == "thread_00000000000000000000000000000065"
    assert ids("thread") == "thread_00000000000000000000000000000066"
    assert ids("message") == "message_00000000000000000000000000000065"
    with pytest.raises(ValueError, match="prefix"):
        ids("Invalid")
