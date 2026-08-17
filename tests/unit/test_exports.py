from __future__ import annotations

import json
from datetime import timedelta
from itertools import count
from pathlib import Path

import pytest

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.application.exports import ExportBundleError, OwnerExportService, validate_bundle
from melloa.apps.synthetic import build_synthetic_runtime
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import ConversationMessage, DeliveryState, MessageKind, MessagePart
from melloa.domain.exports import (
    CanonicalExportManifest,
    CanonicalExportValidationReport,
    ExportFileEntry,
    ExportFileKind,
)
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload

_BOOTSTRAP_TOKEN = "synthetic-owner-bootstrap-token-value-0001"


def test_owner_export_writes_valid_schema_readable_bundle(tmp_path, fixed_time) -> None:
    runtime = _runtime(fixed_time, mode=GuardianMode.NO_ACTIONS)
    reply = runtime.conversation_service.post_owner_message(
        _owner(runtime.owner_id, fixed_time),
        thread_id=runtime.telegram_thread_id,
        text="What should I inspect before enabling a real provider?",
        idempotency_key="export-model-activity",
    )
    assert reply.turn is not None
    bundle_dir = tmp_path / "export"

    manifest = OwnerExportService(
        owner_id=runtime.owner_id,
        intelligence_id=runtime.intelligence_id,
        conversation=runtime.conversation_service,
        delivery=runtime.delivery_service,
        memory=runtime.memory_service,
        memory_repository=runtime.memory_store,
        retention=runtime.retention_service,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    ).write_bundle(bundle_dir, schema_root=_schema_root())

    report = validate_bundle(bundle_dir, clock=lambda: fixed_time)
    assert report.valid is True
    assert report.export_id == manifest.export_id
    assert report.record_counts["conversations/deliveries.jsonl"] == 0
    assert report.record_counts["conversations/threads.jsonl"] == 1
    assert report.record_counts["assertions/inspections.jsonl"] == 1
    assert report.record_counts["inspection/model-activity.jsonl"] == 1
    assert report.record_counts["inspection/retention.jsonl"] == 1
    assert (bundle_dir / "schemas/owner-export/manifest-v1.json").is_file()
    assert (bundle_dir / "schemas/inspection/owner-model-activity-v1.json").is_file()
    assert (bundle_dir / "schemas/retention/owner-report-v1.json").is_file()
    assert (bundle_dir / "schemas/conversation/delivery-work-status-v1.json").is_file()
    assert "export.preview-unencrypted" in manifest.limitations
    assert manifest.encrypted is False
    assert manifest.includes_sql_snapshot is False
    assert manifest.includes_blobs is False
    activity_records = [
        json.loads(line)
        for line in (bundle_dir / "inspection/model-activity.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    assert activity_records[0]["total_runs"] == 1
    assert activity_records[0]["total_cost_gbp"] == 0.0
    assert activity_records[0]["external_disclosure_runs"] == 0
    assert activity_records[0]["entries"][0]["turn_id"] == reply.turn.turn_id
    assert activity_records[0]["entries"][0]["route_id"] == "model.fake.deterministic"
    assert activity_records[0]["entries"][0]["external_disclosure"] is False


def test_owner_export_includes_redacted_delivery_status(
    tmp_path,
    fixed_time,
) -> None:
    runtime = _runtime(fixed_time, mode=GuardianMode.NORMAL)
    principal = _owner(runtime.owner_id, fixed_time)
    reply = runtime.conversation_service.post_owner_message(
        principal,
        thread_id=runtime.telegram_thread_id,
        text="Create a reply that can be delivered.",
        idempotency_key="export-delivery-message",
    )
    assert reply.output_message is not None
    submitted = runtime.delivery_service.enqueue_owner_delivery(
        principal,
        thread_id=runtime.telegram_thread_id,
        message_id=reply.output_message.message_id,
        client_adapter="client.fake",
        destination_ref="synthetic:owner",
        idempotency_key="export-delivery-work",
    )
    bundle_dir = tmp_path / "export"

    OwnerExportService(
        owner_id=runtime.owner_id,
        intelligence_id=runtime.intelligence_id,
        conversation=runtime.conversation_service,
        delivery=runtime.delivery_service,
        memory=runtime.memory_service,
        memory_repository=runtime.memory_store,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    ).write_bundle(bundle_dir, schema_root=_schema_root())

    report = validate_bundle(bundle_dir, clock=lambda: fixed_time)
    delivery_text = (bundle_dir / "conversations/deliveries.jsonl").read_text(
        encoding="utf-8"
    )
    records = [json.loads(line) for line in delivery_text.splitlines() if line]

    assert report.valid is True
    assert report.record_counts["conversations/deliveries.jsonl"] == 1
    assert records[0]["work_id"] == submitted.status.work_id
    assert records[0]["message_id"] == reply.output_message.message_id
    assert records[0]["state"] == "completed"
    assert records[0]["attempts"][0]["adapter_receipt"]["message_id"] == (
        reply.output_message.message_id
    )
    assert "Create a reply" not in delivery_text
    assert "No external model" not in delivery_text


def test_owner_export_includes_deleted_memory_tombstone_evidence(
    tmp_path,
    fixed_time,
) -> None:
    runtime = _runtime(fixed_time, mode=GuardianMode.NO_ACTIONS)
    runtime.memory_service.delete_content(
        AuthenticatedOwner(
            owner_id=runtime.owner_id,
            session_id="session_00000000000000000000000000000001",
            authentication_method="auth.owner-export-test",
            authenticated_at=fixed_time,
            reauthenticated_until=fixed_time + timedelta(minutes=5),
            expires_at=fixed_time + timedelta(minutes=30),
        ),
        runtime.seed_assertion_id,
    )
    bundle_dir = tmp_path / "export"

    OwnerExportService(
        owner_id=runtime.owner_id,
        intelligence_id=runtime.intelligence_id,
        conversation=runtime.conversation_service,
        memory=runtime.memory_service,
        memory_repository=runtime.memory_store,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    ).write_bundle(bundle_dir, schema_root=_schema_root())

    report = validate_bundle(bundle_dir, clock=lambda: fixed_time)
    records = [
        json.loads(line)
        for line in (bundle_dir / "assertions/inspections.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]

    assert report.valid is True
    assert report.record_counts["assertions/inspections.jsonl"] == 1
    assert records[0]["content_state"] == "deleted"
    assert "value" not in records[0]["assertion"]
    assert records[0]["deletion_tombstone"]["assertion_id"] == runtime.seed_assertion_id
    assert records[0]["deletion_tombstone"]["content_hash"].startswith("sha256:")
    assert records[0]["backup_expiry"]["state"] == "not-configured"


def test_import_validation_rejects_tampered_jsonl_record(tmp_path, fixed_time) -> None:
    runtime = _runtime(fixed_time)
    bundle_dir = tmp_path / "export"
    OwnerExportService(
        owner_id=runtime.owner_id,
        intelligence_id=runtime.intelligence_id,
        conversation=runtime.conversation_service,
        memory=runtime.memory_service,
        memory_repository=runtime.memory_store,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    ).write_bundle(bundle_dir, schema_root=_schema_root())

    messages_path = bundle_dir / "conversations/messages.jsonl"
    messages = [
        json.loads(line)
        for line in messages_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    messages.append(
        {
            "contract_version": "1.0.0",
            "message_id": "message_00000000000000000000000000000099",
            "thread_id": "thread_0000000000000000000000000000ffff",
        }
    )
    messages_path.write_text(
        "".join(json.dumps(message, sort_keys=True) + "\n" for message in messages),
        encoding="utf-8",
    )

    report = validate_bundle(bundle_dir, clock=lambda: fixed_time)
    assert report.valid is False
    assert any("checksum mismatch" in error for error in report.errors)
    assert any("does not match its schema model" in error for error in report.errors)


def test_export_refuses_non_empty_target_and_missing_schema_root(
    tmp_path,
    fixed_time,
) -> None:
    runtime = _runtime(fixed_time)
    target = tmp_path / "export"
    target.mkdir()
    (target / "existing").write_text("do not overwrite\n", encoding="utf-8")
    service = OwnerExportService(
        owner_id=runtime.owner_id,
        intelligence_id=runtime.intelligence_id,
        conversation=runtime.conversation_service,
        memory=runtime.memory_service,
        memory_repository=runtime.memory_store,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    )

    with pytest.raises(ExportBundleError, match="must be empty"):
        service.write_bundle(target, schema_root=_schema_root())

    file_target = tmp_path / "not-a-directory"
    file_target.write_text("not a directory\n", encoding="utf-8")
    with pytest.raises(ExportBundleError, match="must be a directory"):
        service.write_bundle(file_target, schema_root=_schema_root())

    empty_target = tmp_path / "second-export"
    with pytest.raises(ExportBundleError, match="required schema is missing"):
        service.write_bundle(empty_target, schema_root=tmp_path / "missing-schemas")


def test_import_validation_reports_missing_checksum_manifest_and_references(
    tmp_path,
    fixed_time,
) -> None:
    missing_report = validate_bundle(tmp_path / "missing", clock=lambda: fixed_time)
    assert missing_report.valid is False
    assert "checksums.sha256 is missing" in missing_report.errors[0]

    runtime = _runtime(fixed_time)
    bundle_dir = tmp_path / "export"
    OwnerExportService(
        owner_id=runtime.owner_id,
        intelligence_id=runtime.intelligence_id,
        conversation=runtime.conversation_service,
        memory=runtime.memory_service,
        memory_repository=runtime.memory_store,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    ).write_bundle(bundle_dir, schema_root=_schema_root())

    (bundle_dir / "conversations/turns.jsonl").unlink()
    deleted_report = validate_bundle(bundle_dir, clock=lambda: fixed_time)
    assert deleted_report.valid is False
    assert any("checksum references missing files" in error for error in deleted_report.errors)

    bundle_dir = tmp_path / "reference-export"
    OwnerExportService(
        owner_id=runtime.owner_id,
        intelligence_id=runtime.intelligence_id,
        conversation=runtime.conversation_service,
        memory=runtime.memory_service,
        memory_repository=runtime.memory_store,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    ).write_bundle(bundle_dir, schema_root=_schema_root())
    orphan = ConversationMessage(
        message_id="message_00000000000000000000000000000099",
        thread_id="thread_0000000000000000000000000000ffff",
        author_principal_id=runtime.owner_id,
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text="orphan"),),
        delivery_state=DeliveryState.DELIVERED,
        sensitivity=Sensitivity.PERSONAL,
        created_at=fixed_time,
        observed_at=fixed_time,
    )
    messages_path = bundle_dir / "conversations/messages.jsonl"
    with messages_path.open("ab") as handle:
        handle.write(orphan.model_dump_json().encode("utf-8") + b"\n")

    reference_report = validate_bundle(bundle_dir, clock=lambda: fixed_time)
    assert reference_report.valid is False
    assert any("message references missing thread" in error for error in reference_report.errors)

    bundle_dir = tmp_path / "activity-reference-export"
    OwnerExportService(
        owner_id=runtime.owner_id,
        intelligence_id=runtime.intelligence_id,
        conversation=runtime.conversation_service,
        memory=runtime.memory_service,
        memory_repository=runtime.memory_store,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    ).write_bundle(bundle_dir, schema_root=_schema_root())
    activity_path = bundle_dir / "inspection/model-activity.jsonl"
    activity_records = [
        json.loads(line)
        for line in activity_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    activity_records[0]["entries"] = (
        {
            "turn_id": "turn_0000000000000000000000000000ffff",
            "thread_id": runtime.telegram_thread_id,
            "result_id": "result_00000000000000000000000000000001",
            "request_id": "request_00000000000000000000000000000001",
            "route_id": "model.fake.deterministic",
            "provider_id": "provider.synthetic",
            "model_id": "deterministic-fixture-v1",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_gbp": 0.0,
            "started_at": fixed_time.isoformat(),
            "completed_at": fixed_time.isoformat(),
            "external_disclosure": False,
            "disclosure": None,
        },
    )
    activity_records[0]["total_runs"] = 1
    activity_records[0]["external_disclosure_runs"] = 0
    activity_records[0]["total_input_tokens"] = 0
    activity_records[0]["total_output_tokens"] = 0
    activity_records[0]["total_cost_gbp"] = 0.0
    activity_records[0]["external_cost_gbp"] = 0.0
    activity_records[0]["window_start"] = (fixed_time - timedelta(seconds=1)).isoformat()
    activity_records[0]["window_end"] = (fixed_time + timedelta(seconds=1)).isoformat()
    activity_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in activity_records),
        encoding="utf-8",
    )

    activity_reference_report = validate_bundle(bundle_dir, clock=lambda: fixed_time)

    assert activity_reference_report.valid is False
    assert any(
        "model activity references missing turn" in error
        for error in activity_reference_report.errors
    )


def test_import_validation_reports_malformed_checksum_file(tmp_path, fixed_time) -> None:
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "checksums.sha256").write_text("not a checksum\n", encoding="utf-8")
    malformed_report = validate_bundle(malformed, clock=lambda: fixed_time)
    assert malformed_report.valid is False
    assert "invalid line" in malformed_report.errors[0]

    duplicate = tmp_path / "duplicate"
    duplicate.mkdir()
    digest = "0" * 64
    duplicate.joinpath("checksums.sha256").write_text(
        f"{digest}  manifest.json\n{digest}  manifest.json\n",
        encoding="utf-8",
    )
    duplicate_report = validate_bundle(duplicate, clock=lambda: fixed_time)
    assert duplicate_report.valid is False
    assert "duplicate paths" in duplicate_report.errors[0]


def test_export_contracts_reject_misleading_or_unsafe_metadata(fixed_time) -> None:
    with pytest.raises(ValueError, match="data files require"):
        ExportFileEntry(
            path="conversations/messages.jsonl",
            kind=ExportFileKind.DATA,
            content_hash="sha256:" + "0" * 64,
            size_bytes=0,
        )
    with pytest.raises(ValueError, match="record count"):
        ExportFileEntry(
            path="conversations/messages.jsonl",
            kind=ExportFileKind.DATA,
            record_type="export.conversation-message",
            schema_path="schemas/conversation/message-v1.json",
            content_hash="sha256:" + "0" * 64,
            size_bytes=0,
        )
    with pytest.raises(ValueError, match="schema path must be relative"):
        ExportFileEntry(
            path="conversations/messages.jsonl",
            kind=ExportFileKind.DATA,
            record_type="export.conversation-message",
            schema_path="../schemas/message-v1.json",
            content_hash="sha256:" + "0" * 64,
            size_bytes=0,
            record_count=0,
        )
    with pytest.raises(ValueError, match="schema files cannot"):
        ExportFileEntry(
            path="schemas/conversation/message-v1.json",
            kind=ExportFileKind.SCHEMA,
            record_type="export.conversation-message",
            content_hash="sha256:" + "0" * 64,
            size_bytes=10,
        )
    with pytest.raises(ValueError, match="relative and contained"):
        ExportFileEntry(
            path="../secret",
            kind=ExportFileKind.SCHEMA,
            content_hash="sha256:" + "0" * 64,
            size_bytes=10,
        )

    entry = ExportFileEntry(
        path="conversations/messages.jsonl",
        kind=ExportFileKind.DATA,
        record_type="export.conversation-message",
        schema_path="schemas/conversation/message-v1.json",
        content_hash="sha256:" + "0" * 64,
        size_bytes=0,
        record_count=0,
    )
    with pytest.raises(ValueError, match="file paths must be unique"):
        CanonicalExportManifest(
            export_id="export_00000000000000000000000000000001",
            owner_id="owner_00000000000000000000000000000001",
            intelligence_id="intelligence_00000000000000000000000000000001",
            created_at=fixed_time,
            source_runtime="test",
            encrypted=False,
            includes_sql_snapshot=False,
            includes_blobs=False,
            files=(entry, entry),
        )
    with pytest.raises(ValueError, match="cannot claim encryption"):
        CanonicalExportManifest(
            export_id="export_00000000000000000000000000000001",
            owner_id="owner_00000000000000000000000000000001",
            intelligence_id="intelligence_00000000000000000000000000000001",
            created_at=fixed_time,
            source_runtime="test",
            encrypted=True,
            includes_sql_snapshot=False,
            includes_blobs=False,
            files=(entry,),
        )
    with pytest.raises(ValueError, match="valid export report cannot contain errors"):
        CanonicalExportValidationReport(
            validated_at=fixed_time,
            valid=True,
            files_checked=1,
            errors=("bad",),
        )
    with pytest.raises(ValueError, match="invalid export report must explain"):
        CanonicalExportValidationReport(
            validated_at=fixed_time,
            valid=False,
            files_checked=1,
        )


def _runtime(fixed_time, *, mode: GuardianMode = GuardianMode.READ_ONLY):
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=mode,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.export-test",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )
    return build_synthetic_runtime(
        guardian,
        _BOOTSTRAP_TOKEN,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    )


def _owner(owner_id: str, fixed_time) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=owner_id,
        session_id="session_00000000000000000000000000000001",
        authentication_method="auth.owner-export-test",
        authenticated_at=fixed_time,
        reauthenticated_until=fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )


def _fixed_ids():
    identifiers = count(1)

    def factory(prefix: str) -> str:
        return f"{prefix}_{next(identifiers):032x}"

    return factory


def _schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas"
