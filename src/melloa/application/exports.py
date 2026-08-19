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
from melloa.ports.memory import MemoryStore


class ExportBundleError(RuntimeError):
    """The owner archive could not be assembled or validated."""


ExportGroup = Literal["conversations", "messages-and-answers", "memories"]
_EXPORT_GROUPS: tuple[ExportGroup, ...] = (
    "conversations",
    "messages-and-answers",
    "memories",
)


class ExportCoverageItem(ContractModel):
    group: ExportGroup
    included: bool = True


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
            coverage=tuple(ExportCoverageItem(group=group) for group in _EXPORT_GROUPS),
            validation_checks=(
                {"check": "archive-structure", "performed_before_download": True},
                {"check": "content-hashes", "performed_before_download": True},
            ),
            limitations=(
                "The browser archive is not encrypted.",
                "Authentication secrets and provider credentials are never included.",
            ),
        )

    def build_archive(self, principal: AuthenticatedOwner) -> OwnerExportArchive:
        self._require_owner(principal)
        export_id = self._id_factory("export")
        generated_at = self._clock()
        threads = self._conversation.list_threads(principal)
        conversations = [
            {
                "thread": thread.model_dump(mode="json"),
                "messages": [
                    message.model_dump(mode="json")
                    for message in self._conversation.list_messages(principal, thread.thread_id)
                ],
                "turns": [
                    turn.model_dump(mode="json")
                    for turn in self._conversation.list_turns(principal, thread.thread_id)
                ],
            }
            for thread in threads
        ]
        memories = [
            memory.model_dump(mode="json")
            for memory in self._memory.list_assertions(principal.owner_id)
        ]
        payloads = {
            "conversations.json": canonical_json_bytes({"conversations": conversations}),
            "memories.json": canonical_json_bytes({"memories": memories}),
        }
        manifest = {
            "format": "melloa-owner-export-v1",
            "export_id": export_id,
            "generated_at": generated_at.isoformat(),
            "owner_id": principal.owner_id,
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
