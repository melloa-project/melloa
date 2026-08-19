"""Small provider-independent owner export for conversations and memories."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from melloa.application.conversation import ConversationService
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import (
    ContractModel,
    JsonObject,
    RecordId,
    canonical_json_bytes,
    new_record_id,
    utc_now,
)
from melloa.ports.memory import MemoryContentDeletedError, MemoryStore


class ExportBundleError(RuntimeError):
    """The owner archive could not be assembled or validated."""


ExportGroup = Literal[
    "conversation-history",
    "answer-provenance",
    "memory-history",
    "conversation-deletion-receipts",
    "account-and-security-history",
    "system-events-and-audit-history",
]
_EXPORT_COVERAGE: tuple[tuple[ExportGroup, str, bool], ...] = (
    ("conversation-history", "Active conversations, messages, and answers", True),
    ("answer-provenance", "Reply attempts and context behind completed answers", True),
    ("memory-history", "Retained memories, corrections, and change history", True),
    ("conversation-deletion-receipts", "Conversation deletion receipts", False),
    ("account-and-security-history", "Account and signed-in browser history", False),
    ("system-events-and-audit-history", "Internal system and audit history", False),
)


class ExportCoverageItem(ContractModel):
    group: ExportGroup
    label: str
    included: bool


class OwnerExportReadinessReport(ContractModel):
    encrypted: Literal[False] = False
    coverage: tuple[ExportCoverageItem, ...]
    validation_checks: tuple[JsonObject, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class OwnerExportArchive:
    filename: str
    content: bytes


class OwnerExportService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        conversation: ConversationService,
        memory: MemoryStore,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        self._owner_id = owner_id
        self._conversation = conversation
        self._memory = memory
        self._clock = clock
        self._id_factory = id_factory

    def readiness(self, principal: AuthenticatedOwner) -> OwnerExportReadinessReport:
        self._require_owner(principal)
        return OwnerExportReadinessReport(
            coverage=tuple(
                ExportCoverageItem(group=group, label=label, included=included)
                for group, label, included in _EXPORT_COVERAGE
            ),
            validation_checks=(
                {"check": "archive-structure", "performed_before_download": True},
                {"check": "content-hashes", "performed_before_download": True},
            ),
            limitations=(
                "The browser archive is not encrypted.",
                "Deleted conversation content cannot be reconstructed; its deletion receipts "
                "are not included.",
                "A deleted memory value may remain in a conversation's completed-answer "
                "provenance if that answer used it.",
                "Failed reply attempts include recorded outcome and disclosure summaries, not "
                "full failed answer payloads.",
                "Login sessions, credentials, model connection secrets, system events, and audit "
                "records are not included.",
                "Backups are separate and may retain older data according to their independently "
                "configured expiry.",
            ),
        )

    def build_archive(self, principal: AuthenticatedOwner) -> OwnerExportArchive:
        self._require_owner(principal)
        readiness = self.readiness(principal)
        export_id = self._id_factory("export")
        generated_at = self._clock()
        threads = self._conversation.list_threads(principal)
        conversations = []
        for thread in threads:
            turns = self._conversation.list_turns(principal, thread.thread_id)
            conversations.append({
                "thread": thread.model_dump(mode="json"),
                "messages": [
                    message.model_dump(mode="json")
                    for message in self._conversation.list_messages(principal, thread.thread_id)
                ],
                "turns": [turn.model_dump(mode="json") for turn in turns],
                "processing": [
                    processing.model_dump(mode="json")
                    for processing in self._conversation.list_processing(
                        principal,
                        thread.thread_id,
                    )
                ],
                "answer_provenance": [
                    self._conversation.inspect_turn(
                        principal,
                        thread_id=thread.thread_id,
                        turn_id=turn.turn_id,
                    ).model_dump(mode="json")
                    for turn in turns
                ],
            })
        memories = self._memory_history(principal.owner_id)
        payloads = {
            "conversations.json": canonical_json_bytes({"conversations": conversations}),
            "memories.json": canonical_json_bytes(memories),
        }
        manifest = {
            "format": "melloa-owner-export-v2",
            "export_id": export_id,
            "generated_at": generated_at.isoformat(),
            "owner_id": principal.owner_id,
            "encrypted": readiness.encrypted,
            "coverage": [
                item.model_dump(mode="json") for item in readiness.coverage
            ],
            "limitations": list(readiness.limitations),
            "files": [
                {
                    "path": path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content),
                }
                for path, content in sorted(payloads.items())
            ],
        }
        files = {"manifest.json": canonical_json_bytes(manifest), **payloads}
        content = _write_zip(files)
        _validate_zip(content, files)
        return OwnerExportArchive(
            filename=f"melloa-owner-export-{export_id}.zip",
            content=content,
        )

    def _memory_history(self, owner_id: RecordId) -> JsonObject:
        metadata_items = self._memory.list_assertion_metadata(owner_id)
        assertion_ids = frozenset(item.assertion_id for item in metadata_items)
        assertions: list[JsonObject] = []
        for metadata in metadata_items:
            deletion = None
            try:
                assertion_document = self._memory.get_assertion(
                    metadata.assertion_id
                ).model_dump(mode="json")
                content_state = "retained"
            except MemoryContentDeletedError:
                assertion_document = metadata.model_dump(mode="json")
                content_state = "deleted"
                deletion = self._memory.get_assertion_content_deletion(
                    metadata.assertion_id
                )
                if deletion is None:
                    raise ExportBundleError(
                        "deleted memory content is missing its deletion evidence"
                    ) from None
            assertions.append(
                {
                    "content_state": content_state,
                    "assertion": assertion_document,
                    "current_state": self._memory.get_assertion_state(
                        metadata.assertion_id
                    ).model_dump(mode="json"),
                    "state_changes": [
                        change.model_dump(mode="json")
                        for change in self._memory.list_assertion_state_changes(
                            metadata.assertion_id
                        )
                    ],
                    "deletion_tombstone": (
                        None if deletion is None else deletion.model_dump(mode="json")
                    ),
                }
            )
        return {
            "assertions": assertions,
            "provenance_edges": [
                edge.model_dump(mode="json")
                for edge in self._memory.list_provenance_edges(assertion_ids)
            ],
        }

    def _require_owner(self, principal: AuthenticatedOwner) -> None:
        if principal.owner_id != self._owner_id:
            raise PermissionError("authenticated principal does not own this export")


def _write_zip(files: dict[str, bytes]) -> bytes:
    target = io.BytesIO()
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, content in sorted(files.items()):
                info = zipfile.ZipInfo(path)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, content)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise ExportBundleError("owner export could not be written") from error
    return target.getvalue()


def _validate_zip(content: bytes, expected: dict[str, bytes]) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
            if archive.testzip() is not None or set(archive.namelist()) != set(expected):
                raise ExportBundleError("owner export archive structure is invalid")
            for path, source in expected.items():
                stored = archive.read(path)
                if stored != source:
                    raise ExportBundleError("owner export content changed during assembly")
                json.loads(stored)
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        raise ExportBundleError("owner export validation failed") from error


__all__ = [
    "ExportBundleError",
    "ExportCoverageItem",
    "OwnerExportArchive",
    "OwnerExportReadinessReport",
    "OwnerExportService",
]
