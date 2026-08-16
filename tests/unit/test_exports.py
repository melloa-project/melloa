from __future__ import annotations

import json
from itertools import count
from pathlib import Path

import pytest

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.application.exports import ExportBundleError, OwnerExportService, validate_bundle
from melloa.apps.synthetic import build_synthetic_runtime
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
    runtime = _runtime(fixed_time)
    bundle_dir = tmp_path / "export"

    manifest = OwnerExportService(
        owner_id=runtime.owner_id,
        intelligence_id=runtime.intelligence_id,
        conversation=runtime.conversation_service,
        memory=runtime.memory_service,
        memory_repository=runtime.memory_store,
        clock=lambda: fixed_time,
        id_factory=_fixed_ids(),
    ).write_bundle(bundle_dir, schema_root=_schema_root())

    report = validate_bundle(bundle_dir, clock=lambda: fixed_time)
    assert report.valid is True
    assert report.export_id == manifest.export_id
    assert report.record_counts["conversations/threads.jsonl"] == 1
    assert report.record_counts["assertions/inspections.jsonl"] == 1
    assert (bundle_dir / "schemas/owner-export/manifest-v1.json").is_file()
    assert "export.preview-unencrypted" in manifest.limitations
    assert manifest.encrypted is False
    assert manifest.includes_sql_snapshot is False
    assert manifest.includes_blobs is False


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


def _runtime(fixed_time):
    guardian = FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=GuardianMode.READ_ONLY,
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


def _fixed_ids():
    identifiers = count(1)

    def factory(prefix: str) -> str:
        return f"{prefix}_{next(identifiers):032x}"

    return factory


def _schema_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas"
