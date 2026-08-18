"""Canonical owner export writing and import-time validation."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64DecodeError
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from pydantic import BaseModel, ValidationError

from melloa.application.conversation import ConversationService
from melloa.application.delivery import DeliveryService
from melloa.application.memory import MemoryService
from melloa.application.retention import OwnerRetentionService
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import (
    RecordId,
    canonical_json_bytes,
    new_record_id,
    sha256_digest,
    utc_now,
)
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingStatus,
    ConversationThread,
    ConversationTurn,
    ConversationTurnInspection,
)
from melloa.domain.delivery import DeliveryWorkStatus
from melloa.domain.exports import (
    CanonicalExportManifest,
    CanonicalExportValidationReport,
    EncryptedExportPackageHeader,
    EncryptedExportPackageValidationReport,
    ExportFileEntry,
    ExportFileKind,
)
from melloa.domain.inspection import (
    DisclosedMemoryReference,
    ModelActivityEntry,
    ModelDisclosureInspection,
    OwnerModelActivityReport,
)
from melloa.domain.memory import MemoryInspection
from melloa.domain.retention import OwnerRetentionReport
from melloa.ports.memory import MemoryRepository
from melloa.release import CURRENT_RELEASE

DATA_SCHEMAS: dict[str, tuple[str, type[BaseModel], str]] = {
    "conversations/threads.jsonl": (
        "export.conversation-thread",
        ConversationThread,
        "schemas/conversation/thread-v1.json",
    ),
    "conversations/messages.jsonl": (
        "export.conversation-message",
        ConversationMessage,
        "schemas/conversation/message-v1.json",
    ),
    "conversations/turns.jsonl": (
        "export.conversation-turn",
        ConversationTurn,
        "schemas/conversation/turn-v1.json",
    ),
    "conversations/turn-inspections.jsonl": (
        "export.conversation-turn-inspection",
        ConversationTurnInspection,
        "schemas/conversation/turn-inspection-v1.json",
    ),
    "conversations/processing.jsonl": (
        "export.conversation-processing-status",
        ConversationProcessingStatus,
        "schemas/conversation/processing-status-v1.json",
    ),
    "conversations/deliveries.jsonl": (
        "export.delivery-work-status",
        DeliveryWorkStatus,
        "schemas/conversation/delivery-work-status-v1.json",
    ),
    "inspection/model-activity.jsonl": (
        "export.owner-model-activity-report",
        OwnerModelActivityReport,
        "schemas/inspection/owner-model-activity-v1.json",
    ),
    "inspection/retention.jsonl": (
        "export.owner-retention-report",
        OwnerRetentionReport,
        "schemas/retention/owner-report-v1.json",
    ),
    "assertions/inspections.jsonl": (
        "export.memory-inspection",
        MemoryInspection,
        "schemas/memory/inspection-v1.json",
    ),
}
SCHEMA_SOURCE_PATHS = tuple(
    sorted(
        {
            *(schema for _, _, schema in DATA_SCHEMAS.values()),
            "schemas/owner-export/manifest-v1.json",
            "schemas/owner-export/validation-report-v1.json",
        }
    )
)
_ENCRYPTED_PACKAGE_MAGIC = b"MELLOA-EXPORT-AESGCM-V1\n"
_HEADER_LENGTH_BYTES = 4
_PACKAGE_KEY_BYTES = 32
_PACKAGE_FORMAT_ID = "melloa.encrypted-owner-export-package"
_PACKAGE_FORMAT_VERSION = "1.0.0"
_INNER_FORMAT_ID = "melloa.canonical-owner-export"
_SCRYPT_SALT_BYTES = 16
_AES_GCM_NONCE_BYTES = 12
_AES_GCM_TAG_BYTES = 16
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1


class ExportBundleError(RuntimeError):
    """A canonical owner export could not be written or validated."""


class OwnerExportService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        intelligence_id: RecordId,
        conversation: ConversationService,
        memory: MemoryService,
        memory_repository: MemoryRepository,
        delivery: DeliveryService | None = None,
        retention: OwnerRetentionService | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
        source_runtime: str = CURRENT_RELEASE.runtime_identifier,
    ) -> None:
        self._owner_id = owner_id
        self._intelligence_id = intelligence_id
        self._conversation = conversation
        self._memory = memory
        self._memory_repository = memory_repository
        self._delivery = delivery
        self._retention = retention
        self._clock = clock
        self._id_factory = id_factory
        self._source_runtime = source_runtime

    def write_bundle(
        self,
        target_dir: Path,
        *,
        schema_root: Path,
        principal: AuthenticatedOwner | None = None,
    ) -> CanonicalExportManifest:
        target = _prepare_target_dir(target_dir)
        export_principal = principal or self._export_principal()
        if export_principal.owner_id != self._owner_id:
            raise ExportBundleError("authenticated principal does not own this export")
        rows = self._collect_rows(export_principal)
        entries: list[ExportFileEntry] = []

        for relative_path, records in rows.items():
            record_type, _model, schema_path = DATA_SCHEMAS[relative_path]
            entries.append(
                _write_jsonl(
                    target,
                    target / relative_path,
                    records,
                    record_type=record_type,
                    schema_path=schema_path,
                )
            )

        for schema_path in SCHEMA_SOURCE_PATHS:
            entries.append(_copy_schema(schema_root, target, schema_path))

        manifest = CanonicalExportManifest(
            export_id=self._id_factory("export"),
            owner_id=self._owner_id,
            intelligence_id=self._intelligence_id,
            created_at=self._clock(),
            source_runtime=self._source_runtime,
            encrypted=False,
            includes_sql_snapshot=False,
            includes_blobs=False,
            files=tuple(sorted(entries, key=lambda entry: entry.path)),
            limitations=(
                "export.preview-unencrypted",
                "export.sql-snapshot-not-included",
                "export.blobs-not-included",
                "export.telegram-control-state-not-included",
            ),
        )
        manifest_path = target / "manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
        _write_checksums(target)
        return manifest

    def write_validated_zip(
        self,
        archive_path: Path,
        *,
        schema_root: Path,
        principal: AuthenticatedOwner | None = None,
    ) -> CanonicalExportManifest:
        target = archive_path.resolve()
        if target.exists():
            raise ExportBundleError("export archive target already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.is_dir():
            raise ExportBundleError("export archive parent must be a directory")

        try:
            with tempfile.TemporaryDirectory(
                prefix=".melloa-export-",
                dir=target.parent,
            ) as staging_directory:
                bundle = Path(staging_directory) / "bundle"
                manifest = self.write_bundle(
                    bundle,
                    schema_root=schema_root,
                    principal=principal,
                )
                validation = validate_bundle(bundle, clock=self._clock)
                if not validation.valid or validation.export_id != manifest.export_id:
                    raise ExportBundleError("generated export bundle failed validation")
                with zipfile.ZipFile(
                    target,
                    mode="x",
                    compression=zipfile.ZIP_DEFLATED,
                ) as archive:
                    for path in sorted(bundle.rglob("*")):
                        if path.is_file():
                            archive.write(
                                path,
                                arcname=path.relative_to(bundle).as_posix(),
                            )
        except FileExistsError as error:
            raise ExportBundleError("export archive target already exists") from error
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return manifest

    def _collect_rows(
        self,
        principal: AuthenticatedOwner,
    ) -> dict[str, tuple[BaseModel, ...]]:
        threads = self._conversation.list_threads(principal)
        messages: list[ConversationMessage] = []
        turns: list[ConversationTurn] = []
        turn_inspections: list[ConversationTurnInspection] = []
        processing: list[ConversationProcessingStatus] = []
        deliveries: list[DeliveryWorkStatus] = []
        for thread in threads:
            thread_messages = self._conversation.list_messages(principal, thread.thread_id)
            messages.extend(thread_messages)
            thread_turns = self._conversation.list_turns(principal, thread.thread_id)
            turns.extend(thread_turns)
            processing.extend(
                self._conversation.list_processing(principal, thread.thread_id)
            )
            if self._delivery is not None:
                deliveries.extend(self._delivery.list_deliveries(principal, thread.thread_id))
            for turn in thread_turns:
                turn_inspections.append(
                    self._conversation.inspect_turn(
                        principal,
                        thread_id=thread.thread_id,
                        turn_id=turn.turn_id,
                    )
                )

        assertions = self._memory_repository.list_assertion_metadata(self._owner_id)
        inspections = tuple(
            self._memory.inspect(principal, assertion.assertion_id)
            for assertion in sorted(
                assertions,
                key=lambda assertion: (assertion.observed_at, assertion.assertion_id),
            )
        )
        sorted_threads: tuple[ConversationThread, ...] = tuple(
            sorted(threads, key=lambda thread: (thread.created_at, thread.thread_id))
        )
        sorted_messages: tuple[ConversationMessage, ...] = tuple(
            sorted(messages, key=lambda message: (message.created_at, message.message_id))
        )
        sorted_turns: tuple[ConversationTurn, ...] = tuple(
            sorted(turns, key=lambda turn: (turn.started_at, turn.turn_id))
        )
        sorted_turn_inspections: tuple[ConversationTurnInspection, ...] = tuple(
            sorted(
                turn_inspections,
                key=lambda inspection: (
                    inspection.turn.started_at,
                    inspection.turn.turn_id,
                ),
            )
        )
        sorted_processing: tuple[ConversationProcessingStatus, ...] = tuple(
            sorted(processing, key=lambda item: (item.available_at, item.work_id))
        )
        sorted_deliveries: tuple[DeliveryWorkStatus, ...] = tuple(
            sorted(deliveries, key=lambda item: (item.available_at, item.work_id))
        )
        model_activity = self._model_activity_report(sorted_turn_inspections)
        retention_report = (
            () if self._retention is None else (self._retention.report(principal),)
        )
        return {
            "conversations/threads.jsonl": sorted_threads,
            "conversations/messages.jsonl": sorted_messages,
            "conversations/turns.jsonl": sorted_turns,
            "conversations/turn-inspections.jsonl": sorted_turn_inspections,
            "conversations/processing.jsonl": sorted_processing,
            "conversations/deliveries.jsonl": sorted_deliveries,
            "inspection/model-activity.jsonl": (model_activity,),
            "inspection/retention.jsonl": retention_report,
            "assertions/inspections.jsonl": inspections,
        }

    def _model_activity_report(
        self,
        inspections: tuple[ConversationTurnInspection, ...],
    ) -> OwnerModelActivityReport:
        generated_at = self._clock()
        entries = tuple(
            sorted(
                (self._model_activity_entry(inspection) for inspection in inspections),
                key=lambda entry: (entry.completed_at, entry.result_id),
            )
        )
        if entries:
            window_start = min(entry.completed_at for entry in entries)
            window_end = max(entry.completed_at for entry in entries) + timedelta(
                microseconds=1
            )
        else:
            window_start = generated_at - timedelta(days=366)
            window_end = generated_at
        return OwnerModelActivityReport(
            owner_id=self._owner_id,
            window_start=window_start,
            window_end=window_end,
            generated_at=generated_at,
            total_runs=len(entries),
            external_disclosure_runs=sum(entry.external_disclosure for entry in entries),
            total_input_tokens=sum(entry.input_tokens for entry in entries),
            total_output_tokens=sum(entry.output_tokens for entry in entries),
            total_cost_gbp=sum(entry.cost_gbp for entry in entries),
            external_cost_gbp=sum(
                entry.cost_gbp for entry in entries if entry.external_disclosure
            ),
            entries=entries,
        )

    @staticmethod
    def _model_activity_entry(
        inspection: ConversationTurnInspection,
    ) -> ModelActivityEntry:
        result = inspection.model_result
        manifest = inspection.retrieval_manifest
        disclosure = None
        if result.external_disclosure:
            disclosure = ModelDisclosureInspection(
                retrieval_manifest_id=manifest.manifest_id,
                purpose=manifest.purpose,
                triggering_message_ids=inspection.turn.triggering_message_ids,
                memory_references=tuple(
                    DisclosedMemoryReference(
                        citation_id=citation.citation_id,
                        assertion_id=citation.assertion_id,
                        sensitivity=citation.sensitivity,
                    )
                    for citation in manifest.citations
                ),
                external_attempts=tuple(
                    attempt for attempt in result.attempts if attempt.external_disclosure
                ),
            )
        return ModelActivityEntry(
            turn_id=inspection.turn.turn_id,
            thread_id=inspection.turn.thread_id,
            result_id=result.result_id,
            request_id=result.request_id,
            route_id=result.route_id,
            provider_id=result.provider_id,
            model_id=result.model_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_gbp=result.cost_gbp,
            started_at=result.started_at,
            completed_at=result.completed_at,
            external_disclosure=result.external_disclosure,
            disclosure=disclosure,
        )

    def _export_principal(self) -> AuthenticatedOwner:
        now = self._clock()
        expires_at = now + timedelta(days=1)
        return AuthenticatedOwner(
            owner_id=self._owner_id,
            session_id=self._id_factory("session"),
            authentication_method="auth.owner-export-cli",
            authenticated_at=now,
            reauthenticated_until=expires_at,
            expires_at=expires_at,
        )


def validate_bundle(
    bundle_dir: Path,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> CanonicalExportValidationReport:
    errors: list[str] = []
    export_id: RecordId | None = None
    files_checked = 0
    record_counts: dict[str, int] = {}
    root = bundle_dir.resolve()
    try:
        expected_checksums = _read_checksums(root / "checksums.sha256")
    except ExportBundleError as error:
        return CanonicalExportValidationReport(
            validated_at=clock(),
            valid=False,
            files_checked=0,
            errors=(str(error),),
        )

    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    }
    expected_files = set(expected_checksums)
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        if missing:
            errors.append(f"checksum references missing files: {', '.join(missing)}")
        if extra:
            errors.append(f"files are missing checksums: {', '.join(extra)}")

    for relative_path, expected_digest in sorted(expected_checksums.items()):
        try:
            path = _contained_path(root, relative_path)
            digest = _file_sha256(path)
        except (ExportBundleError, OSError) as error:
            errors.append(str(error))
            continue
        files_checked += 1
        if digest != expected_digest:
            errors.append(f"checksum mismatch for {relative_path}")

    manifest: CanonicalExportManifest | None = None
    try:
        manifest = CanonicalExportManifest.model_validate_json(
            (root / "manifest.json").read_text(encoding="utf-8")
        )
        export_id = manifest.export_id
    except (OSError, ValidationError, json.JSONDecodeError) as error:
        errors.append(f"manifest is unreadable or invalid: {type(error).__name__}")

    if manifest is not None:
        manifest_paths = {entry.path for entry in manifest.files}
        if manifest_paths - actual_files:
            errors.append(
                "manifest references missing files: "
                + ", ".join(sorted(manifest_paths - actual_files))
            )
        for entry in manifest.files:
            manifest_digest = expected_checksums.get(entry.path)
            if manifest_digest is None:
                errors.append(f"manifest file lacks checksum: {entry.path}")
                continue
            if manifest_digest != entry.content_hash.removeprefix("sha256:"):
                errors.append(f"manifest hash does not match checksums: {entry.path}")
            try:
                size = (_contained_path(root, entry.path)).stat().st_size
            except (OSError, ExportBundleError):
                continue
            if size != entry.size_bytes:
                errors.append(f"manifest size does not match file: {entry.path}")
            if entry.kind is ExportFileKind.DATA:
                record_counts[entry.path] = _validate_jsonl(
                    root,
                    entry.path,
                    DATA_SCHEMAS.get(entry.path, (None, None, None))[1],
                    errors,
                )
                if entry.record_count != record_counts[entry.path]:
                    errors.append(f"manifest record count does not match file: {entry.path}")
        _validate_references(root, manifest, errors)

    return CanonicalExportValidationReport(
        export_id=export_id,
        validated_at=clock(),
        valid=not errors,
        files_checked=files_checked,
        record_counts=record_counts,
        errors=tuple(errors),
    )


def write_encrypted_package(
    bundle_dir: Path,
    package_path: Path,
    *,
    passphrase: str,
    clock: Callable[[], datetime] = utc_now,
) -> EncryptedExportPackageHeader:
    validation = validate_bundle(bundle_dir, clock=clock)
    if not validation.valid or validation.export_id is None:
        raise ExportBundleError("export bundle must validate before encrypted packaging")
    if not 16 <= len(passphrase) <= 4096:
        raise ExportBundleError("export package passphrase must contain 16 to 4096 characters")
    target = package_path.resolve()
    if target.exists():
        raise ExportBundleError("encrypted export package target already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.parent.is_dir():
        raise ExportBundleError("encrypted export package parent must be a directory")

    zip_payload = _zip_bundle_bytes(bundle_dir)
    salt = os.urandom(_SCRYPT_SALT_BYTES)
    nonce = os.urandom(_AES_GCM_NONCE_BYTES)
    header = EncryptedExportPackageHeader(
        created_at=clock(),
        inner_export_id=validation.export_id,
        scrypt_n=_SCRYPT_N,
        scrypt_r=_SCRYPT_R,
        scrypt_p=_SCRYPT_P,
        salt_b64=_b64_encode(salt),
        nonce_b64=_b64_encode(nonce),
        plaintext_zip_hash=sha256_digest(zip_payload),
        plaintext_zip_size_bytes=len(zip_payload),
        ciphertext_size_bytes=len(zip_payload) + _AES_GCM_TAG_BYTES,
    )
    header_bytes = canonical_json_bytes(header)
    key = _derive_package_key(passphrase, salt, header)
    ciphertext = AESGCM(key).encrypt(nonce, zip_payload, _package_aad(header_bytes))
    if len(ciphertext) != header.ciphertext_size_bytes:
        raise ExportBundleError("encrypted package ciphertext length was unexpected")
    try:
        with target.open("xb") as handle:
            handle.write(_ENCRYPTED_PACKAGE_MAGIC)
            handle.write(len(header_bytes).to_bytes(_HEADER_LENGTH_BYTES, "big"))
            handle.write(header_bytes)
            handle.write(ciphertext)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return header


def validate_encrypted_package(
    package_path: Path,
    *,
    passphrase: str,
    clock: Callable[[], datetime] = utc_now,
) -> EncryptedExportPackageValidationReport:
    errors: list[str] = []
    header: EncryptedExportPackageHeader | None = None
    bundle_validation: CanonicalExportValidationReport | None = None
    try:
        header, header_bytes, ciphertext = _read_encrypted_package(package_path)
        plaintext = _decrypt_package_payload(header, header_bytes, ciphertext, passphrase)
        if sha256_digest(plaintext) != header.plaintext_zip_hash:
            raise ExportBundleError("encrypted export package plaintext hash mismatch")
        if len(plaintext) != header.plaintext_zip_size_bytes:
            raise ExportBundleError("encrypted export package plaintext size mismatch")
        with tempfile.TemporaryDirectory(prefix=".melloa-export-validate-") as directory:
            bundle = Path(directory) / "bundle"
            _extract_zip_bytes(plaintext, bundle)
            bundle_validation = validate_bundle(bundle, clock=clock)
            if not bundle_validation.valid:
                errors.extend(bundle_validation.errors)
            if bundle_validation.export_id != header.inner_export_id:
                errors.append("encrypted package inner export ID does not match bundle")
    except InvalidTag:
        errors.append("encrypted export package authentication failed")
    except (ExportBundleError, OSError, ValueError, ValidationError, zipfile.BadZipFile) as error:
        errors.append(str(error))
    return EncryptedExportPackageValidationReport(
        package_header=header,
        bundle_validation=bundle_validation,
        validated_at=clock(),
        valid=not errors,
        errors=tuple(errors),
    )


def _prepare_target_dir(target_dir: Path) -> Path:
    target = target_dir.resolve()
    if target.exists() and not target.is_dir():
        raise ExportBundleError("export target must be a directory")
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ExportBundleError("export target directory must be empty")
    return target


def _write_jsonl(
    target: Path,
    path: Path,
    records: Iterable[BaseModel],
    *,
    record_type: str,
    schema_path: str,
) -> ExportFileEntry:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("wb") as handle:
        for record in records:
            handle.write(canonical_json_bytes(record) + b"\n")
            count += 1
    return _file_entry(
        target,
        path,
        kind=ExportFileKind.DATA,
        record_type=record_type,
        schema_path=schema_path,
        record_count=count,
    )


def _copy_schema(schema_root: Path, target: Path, schema_path: str) -> ExportFileEntry:
    source = schema_root / schema_path.removeprefix("schemas/")
    destination = target / schema_path
    if not source.is_file():
        raise ExportBundleError(f"required schema is missing: {schema_path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return _file_entry(target, destination, kind=ExportFileKind.SCHEMA)


def _file_entry(
    target: Path,
    path: Path,
    *,
    kind: ExportFileKind,
    record_type: str | None = None,
    schema_path: str | None = None,
    record_count: int | None = None,
) -> ExportFileEntry:
    relative_path = path.relative_to(target).as_posix()
    data = path.read_bytes()
    return ExportFileEntry(
        path=relative_path,
        kind=kind,
        record_type=record_type,
        schema_path=schema_path,
        content_hash=sha256_digest(data),
        size_bytes=len(data),
        record_count=record_count,
    )


def _write_checksums(target: Path) -> None:
    lines = []
    for path in sorted(target.rglob("*")):
        if path.is_file() and path.name != "checksums.sha256":
            relative = path.relative_to(target).as_posix()
            lines.append(f"{_file_sha256(path)}  {relative}\n")
    (target / "checksums.sha256").write_text("".join(lines), encoding="utf-8")


def _read_checksums(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ExportBundleError("checksums.sha256 is missing or unreadable") from error
    checksums: dict[str, str] = {}
    for line in lines:
        digest, separator, relative_path = line.partition("  ")
        if separator != "  " or len(digest) != 64:
            raise ExportBundleError("checksums.sha256 contains an invalid line")
        if relative_path in checksums:
            raise ExportBundleError("checksums.sha256 contains duplicate paths")
        checksums[relative_path] = digest
    return checksums


def _contained_path(root: Path, relative_path: str) -> Path:
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ExportBundleError(f"path escapes export bundle: {relative_path}")
    return path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_jsonl(
    root: Path,
    relative_path: str,
    model: type[BaseModel] | None,
    errors: list[str],
) -> int:
    if model is None:
        errors.append(f"unknown data file type: {relative_path}")
        return 0
    count = 0
    for line_number, line in enumerate(
        _contained_path(root, relative_path).read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        try:
            model.model_validate_json(line)
        except ValidationError:
            errors.append(f"{relative_path}:{line_number} does not match its schema model")
        count += 1
    return count


def _zip_bundle_bytes(bundle_dir: Path) -> bytes:
    root = bundle_dir.resolve()
    if not root.is_dir():
        raise ExportBundleError("export bundle directory is missing")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ExportBundleError("export bundle must not contain symbolic links")
            if not path.is_file():
                continue
            relative_path = path.relative_to(root).as_posix()
            ExportFileEntry(
                path=relative_path,
                kind=ExportFileKind.SCHEMA,
                content_hash=sha256_digest(path.read_bytes()),
                size_bytes=path.stat().st_size,
            )
            archive.write(path, arcname=relative_path)
    return buffer.getvalue()


def _extract_zip_bytes(payload: bytes, target_dir: Path) -> None:
    target = _prepare_target_dir(target_dir)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            destination = _contained_path(target, member.filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)


def _derive_package_key(
    passphrase: str,
    salt: bytes,
    header: EncryptedExportPackageHeader,
) -> bytes:
    if not 16 <= len(passphrase) <= 4096:
        raise ExportBundleError("export package passphrase must contain 16 to 4096 characters")
    if (header.scrypt_n, header.scrypt_r, header.scrypt_p) != (
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
    ):
        raise ExportBundleError(
            "encrypted export package key-derivation parameters are unsupported"
        )
    return Scrypt(
        salt=salt,
        length=_PACKAGE_KEY_BYTES,
        n=header.scrypt_n,
        r=header.scrypt_r,
        p=header.scrypt_p,
    ).derive(passphrase.encode("utf-8"))


def _read_encrypted_package(
    package_path: Path,
) -> tuple[EncryptedExportPackageHeader, bytes, bytes]:
    with package_path.resolve().open("rb") as handle:
        if handle.read(len(_ENCRYPTED_PACKAGE_MAGIC)) != _ENCRYPTED_PACKAGE_MAGIC:
            raise ExportBundleError("encrypted export package has an unknown format")
        raw_length = handle.read(_HEADER_LENGTH_BYTES)
        if len(raw_length) != _HEADER_LENGTH_BYTES:
            raise ExportBundleError("encrypted export package header is truncated")
        header_length = int.from_bytes(raw_length, "big")
        if not 1 <= header_length <= 16_384:
            raise ExportBundleError("encrypted export package header length is invalid")
        header_bytes = handle.read(header_length)
        if len(header_bytes) != header_length:
            raise ExportBundleError("encrypted export package header is truncated")
        header = EncryptedExportPackageHeader.model_validate_json(header_bytes)
        _validate_package_header(header)
        ciphertext = handle.read(header.ciphertext_size_bytes + 1)
    if len(ciphertext) != header.ciphertext_size_bytes:
        raise ExportBundleError("encrypted export package ciphertext size mismatch")
    return header, header_bytes, ciphertext


def _decrypt_package_payload(
    header: EncryptedExportPackageHeader,
    header_bytes: bytes,
    ciphertext: bytes,
    passphrase: str,
) -> bytes:
    salt, nonce = _validate_package_header(header)
    key = _derive_package_key(passphrase, salt, header)
    return AESGCM(key).decrypt(
        nonce,
        ciphertext,
        _package_aad(header_bytes),
    )


def _validate_package_header(
    header: EncryptedExportPackageHeader,
) -> tuple[bytes, bytes]:
    if (
        header.package_format_id != _PACKAGE_FORMAT_ID
        or header.package_format_version != _PACKAGE_FORMAT_VERSION
        or header.inner_format_id != _INNER_FORMAT_ID
    ):
        raise ExportBundleError("encrypted export package format is unsupported")
    if (header.scrypt_n, header.scrypt_r, header.scrypt_p) != (
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
    ):
        raise ExportBundleError(
            "encrypted export package key-derivation parameters are unsupported"
        )
    salt = _b64_decode(header.salt_b64)
    if len(salt) != _SCRYPT_SALT_BYTES:
        raise ExportBundleError("encrypted export package salt length is invalid")
    nonce = _b64_decode(header.nonce_b64)
    if len(nonce) != _AES_GCM_NONCE_BYTES:
        raise ExportBundleError("encrypted export package nonce length is invalid")
    if header.ciphertext_size_bytes != (
        header.plaintext_zip_size_bytes + _AES_GCM_TAG_BYTES
    ):
        raise ExportBundleError("encrypted export package ciphertext size is invalid")
    return salt, nonce


def _package_aad(header_bytes: bytes) -> bytes:
    return _ENCRYPTED_PACKAGE_MAGIC + header_bytes


def _b64_encode(value: bytes) -> str:
    return urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return urlsafe_b64decode(value + padding)
    except (Base64DecodeError, ValueError) as error:
        raise ExportBundleError("encrypted export package contains invalid base64") from error


def _load_jsonl(root: Path, relative_path: str) -> list[dict[str, Any]]:
    path = _contained_path(root, relative_path)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _validate_references(
    root: Path,
    manifest: CanonicalExportManifest,
    errors: list[str],
) -> None:
    try:
        threads = _load_jsonl(root, "conversations/threads.jsonl")
        messages = _load_jsonl(root, "conversations/messages.jsonl")
        turns = _load_jsonl(root, "conversations/turns.jsonl")
        inspections = _load_jsonl(root, "conversations/turn-inspections.jsonl")
        deliveries = _load_jsonl(root, "conversations/deliveries.jsonl")
        activity_reports = _load_jsonl(root, "inspection/model-activity.jsonl")
        retention_reports = _load_jsonl(root, "inspection/retention.jsonl")
        memories = _load_jsonl(root, "assertions/inspections.jsonl")
    except (OSError, json.JSONDecodeError, ExportBundleError):
        errors.append("export data cannot be loaded for referential integrity checks")
        return
    thread_ids = {thread["thread_id"] for thread in threads}
    message_ids = {message["message_id"] for message in messages}
    turn_ids = {turn["turn_id"] for turn in turns}
    memory_ids = {memory["assertion"]["assertion_id"] for memory in memories}
    for message in messages:
        if message["thread_id"] not in thread_ids:
            errors.append(f"message references missing thread: {message['message_id']}")
    for turn in turns:
        if turn["thread_id"] not in thread_ids:
            errors.append(f"turn references missing thread: {turn['turn_id']}")
        for message_id in (*turn["triggering_message_ids"], *turn["output_message_ids"]):
            if message_id not in message_ids:
                errors.append(f"turn references missing message: {turn['turn_id']}")
    for inspection in inspections:
        if inspection["turn"]["turn_id"] not in turn_ids:
            errors.append(
                "turn inspection references missing turn: "
                f"{inspection['turn']['turn_id']}"
            )
    for delivery in deliveries:
        if delivery["thread_id"] not in thread_ids:
            errors.append(f"delivery references missing thread: {delivery['work_id']}")
        if delivery["message_id"] not in message_ids:
            errors.append(f"delivery references missing message: {delivery['work_id']}")
    if len(retention_reports) > 1:
        errors.append("retention export contains multiple owner reports")
    for report in retention_reports:
        if report["owner_id"] != manifest.owner_id:
            errors.append("retention report owner does not match manifest")
        policy_ids = tuple(policy["policy_id"] for policy in report["policies"])
        inventory_ids = tuple(item["policy_id"] for item in report["inventory"])
        if inventory_ids != policy_ids:
            errors.append("retention inventory references different policies")
    for report in activity_reports:
        for entry in report["entries"]:
            if entry["thread_id"] not in thread_ids:
                errors.append(
                    f"model activity references missing thread: {entry['result_id']}"
                )
            if entry["turn_id"] not in turn_ids:
                errors.append(
                    f"model activity references missing turn: {entry['result_id']}"
                )
            disclosure = entry.get("disclosure")
            if disclosure is None:
                continue
            for message_id in disclosure["triggering_message_ids"]:
                if message_id not in message_ids:
                    errors.append(
                        "model disclosure references missing message: "
                        f"{entry['result_id']}"
                    )
            for reference in disclosure["memory_references"]:
                if reference["assertion_id"] not in memory_ids:
                    errors.append(
                        "model disclosure references missing memory: "
                        f"{entry['result_id']}"
                    )
    for memory in memories:
        assertion_id = memory["assertion"]["assertion_id"]
        if memory["current_state"]["assertion_id"] != assertion_id:
            errors.append(f"memory state references another assertion: {assertion_id}")
        for edge in memory["provenance_edges"]:
            if edge["from_id"] not in memory_ids and edge["to_id"] not in memory_ids:
                errors.append(f"provenance edge references missing memory: {edge['edge_id']}")
