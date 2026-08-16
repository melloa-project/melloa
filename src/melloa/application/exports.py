"""Canonical owner export writing and import-time validation."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from melloa.application.conversation import ConversationService
from melloa.application.memory import MemoryService
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
from melloa.domain.exports import (
    CanonicalExportManifest,
    CanonicalExportValidationReport,
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
from melloa.ports.memory import MemoryRepository

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
    "inspection/model-activity.jsonl": (
        "export.owner-model-activity-report",
        OwnerModelActivityReport,
        "schemas/inspection/owner-model-activity-v1.json",
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
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
        source_runtime: str = "melloa-core/0.1.0-export-preview",
    ) -> None:
        self._owner_id = owner_id
        self._intelligence_id = intelligence_id
        self._conversation = conversation
        self._memory = memory
        self._memory_repository = memory_repository
        self._clock = clock
        self._id_factory = id_factory
        self._source_runtime = source_runtime

    def write_bundle(
        self,
        target_dir: Path,
        *,
        schema_root: Path,
    ) -> CanonicalExportManifest:
        target = _prepare_target_dir(target_dir)
        principal = self._export_principal()
        rows = self._collect_rows(principal)
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

    def _collect_rows(
        self,
        principal: AuthenticatedOwner,
    ) -> dict[str, tuple[BaseModel, ...]]:
        threads = self._conversation.list_threads(principal)
        messages: list[ConversationMessage] = []
        turns: list[ConversationTurn] = []
        turn_inspections: list[ConversationTurnInspection] = []
        processing: list[ConversationProcessingStatus] = []
        for thread in threads:
            thread_messages = self._conversation.list_messages(principal, thread.thread_id)
            messages.extend(thread_messages)
            thread_turns = self._conversation.list_turns(principal, thread.thread_id)
            turns.extend(thread_turns)
            processing.extend(
                self._conversation.list_processing(principal, thread.thread_id)
            )
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
        model_activity = self._model_activity_report(sorted_turn_inspections)
        return {
            "conversations/threads.jsonl": sorted_threads,
            "conversations/messages.jsonl": sorted_messages,
            "conversations/turns.jsonl": sorted_turns,
            "conversations/turn-inspections.jsonl": sorted_turn_inspections,
            "conversations/processing.jsonl": sorted_processing,
            "inspection/model-activity.jsonl": (model_activity,),
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
        _validate_references(root, errors)

    return CanonicalExportValidationReport(
        export_id=export_id,
        validated_at=clock(),
        valid=not errors,
        files_checked=files_checked,
        record_counts=record_counts,
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


def _load_jsonl(root: Path, relative_path: str) -> list[dict[str, Any]]:
    path = _contained_path(root, relative_path)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _validate_references(root: Path, errors: list[str]) -> None:
    try:
        threads = _load_jsonl(root, "conversations/threads.jsonl")
        messages = _load_jsonl(root, "conversations/messages.jsonl")
        turns = _load_jsonl(root, "conversations/turns.jsonl")
        inspections = _load_jsonl(root, "conversations/turn-inspections.jsonl")
        activity_reports = _load_jsonl(root, "inspection/model-activity.jsonl")
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
