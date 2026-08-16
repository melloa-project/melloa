"""Authenticated owner inspection of redacted health and media metadata."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from melloa.application.conversation import ConversationService
from melloa.application.inspection import InspectionOwnershipError
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId, utc_now
from melloa.domain.operations import (
    ExportCoverageItem,
    ExportValidationCheck,
    OwnerExportReadinessReport,
    OwnerHealthReport,
    OwnerMediaCatalog,
    aggregate_health_state,
)
from melloa.ports.memory import MemoryRepository
from melloa.ports.operations import OperationsInspectionReader


class OwnerOperationsService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        reader: OperationsInspectionReader,
        conversation: ConversationService | None = None,
        memory_repository: MemoryRepository | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._owner_id = owner_id
        self._reader = reader
        self._conversation = conversation
        self._memory_repository = memory_repository
        self._clock = clock

    def health(self, principal: AuthenticatedOwner) -> OwnerHealthReport:
        self._require_owner(principal)
        components = tuple(
            sorted(
                self._reader.component_health(),
                key=lambda component: (component.category.value, component.component_id),
            )
        )
        return OwnerHealthReport(
            owner_id=self._owner_id,
            generated_at=self._clock(),
            overall_state=aggregate_health_state(components),
            components=components,
        )

    def media(self, principal: AuthenticatedOwner) -> OwnerMediaCatalog:
        self._require_owner(principal)
        sources = tuple(
            sorted(
                self._reader.media_sources(self._owner_id),
                key=lambda source: source.capability_id,
            )
        )
        items = tuple(
            sorted(
                self._reader.media_items(self._owner_id),
                key=lambda item: (item.captured_from, item.media_id),
            )
        )
        return OwnerMediaCatalog(
            owner_id=self._owner_id,
            generated_at=self._clock(),
            capture_enabled=any(source.capture_enabled for source in sources),
            sources=sources,
            items=items,
        )

    def export_readiness(
        self,
        principal: AuthenticatedOwner,
    ) -> OwnerExportReadinessReport:
        self._require_owner(principal)
        counts = self._export_counts(principal)
        return OwnerExportReadinessReport(
            owner_id=self._owner_id,
            generated_at=self._clock(),
            cli_command=(
                "melloa export-mvp --status <guardian-status.json> "
                "--public-key <guardian-public.pem> "
                "--owner-credential-file <owner-credential> "
                "--output-dir <export-dir>"
            ),
            validation_command="melloa import-validate --bundle-dir <export-dir>",
            encrypted=False,
            includes_sql_snapshot=False,
            includes_blobs=False,
            coverage=(
                ExportCoverageItem(
                    group_id="export.assertion-inspections",
                    included=True,
                    estimated_records=counts["assertion_inspections"],
                    artifact_path="assertions/inspections.jsonl",
                    summary=(
                        "Memory inspection rows, including deleted-content tombstone "
                        "and rebuild-work evidence without deleted assertion values."
                    ),
                    status_reason="export.coverage.memory-inspection",
                ),
                ExportCoverageItem(
                    group_id="export.blobs",
                    included=False,
                    artifact_path=None,
                    summary="Attachment, media, and object-store blobs are not exported.",
                    status_reason="export.coverage.blobs-not-included",
                ),
                ExportCoverageItem(
                    group_id="export.conversation-records",
                    included=True,
                    estimated_records=counts["conversation_records"],
                    artifact_path="conversations/*.jsonl",
                    summary=(
                        "Canonical threads, messages, turns, turn inspections, and "
                        "processing status records."
                    ),
                    status_reason="export.coverage.conversation-jsonl",
                ),
                ExportCoverageItem(
                    group_id="export.logical-sql",
                    included=False,
                    artifact_path=None,
                    summary=(
                        "Logical PostgreSQL snapshots and migration import execution "
                        "remain pending."
                    ),
                    status_reason="export.coverage.sql-snapshot-not-included",
                ),
                ExportCoverageItem(
                    group_id="export.model-activity",
                    included=True,
                    estimated_records=counts["model_activity_entries"],
                    artifact_path="inspection/model-activity.jsonl",
                    summary=(
                        "Redacted route, model, token, cost, timing, disclosure, "
                        "triggering-message, and disclosed-memory evidence."
                    ),
                    status_reason="export.coverage.model-activity",
                ),
                ExportCoverageItem(
                    group_id="export.schemas-checksums",
                    included=True,
                    estimated_records=counts["validation_artifacts"],
                    artifact_path="schemas/**, manifest.json, checksums.sha256",
                    summary="Copied JSON Schemas, canonical manifest, and SHA-256 checksums.",
                    status_reason="export.coverage.validation-artifacts",
                ),
                ExportCoverageItem(
                    group_id="export.telegram-control-state",
                    included=False,
                    artifact_path=None,
                    summary=(
                        "Telegram pairing, poll cursor, and control state are not "
                        "exported yet."
                    ),
                    status_reason="export.coverage.telegram-control-state-not-included",
                ),
            ),
            validation_checks=(
                ExportValidationCheck(
                    check_id="export.validation.checksums",
                    implemented=True,
                    summary=(
                        "Every bundled file is verified against checksums.sha256 "
                        "before records are trusted."
                    ),
                    status_reason="export.validation.checksum-verification",
                ),
                ExportValidationCheck(
                    check_id="export.validation.references",
                    implemented=True,
                    summary=(
                        "Conversation, turn, and model-activity records receive "
                        "basic referential-integrity checks inside the bundle."
                    ),
                    status_reason="export.validation.basic-references",
                ),
                ExportValidationCheck(
                    check_id="export.validation.restore-execution",
                    implemented=False,
                    summary=(
                        "Validation is a dry run and does not import into a database "
                        "or execute migrations."
                    ),
                    status_reason="export.validation.restore-execution-pending",
                ),
                ExportValidationCheck(
                    check_id="export.validation.schemas",
                    implemented=True,
                    summary=(
                        "JSONL data records are parsed through the bundled versioned "
                        "contract models."
                    ),
                    status_reason="export.validation.schema-models",
                ),
            ),
            limitations=(
                "export.blobs-not-included",
                "export.preview-unencrypted",
                "export.sql-snapshot-not-included",
                "export.telegram-control-state-not-included",
            ),
        )

    def _require_owner(self, principal: AuthenticatedOwner) -> None:
        if principal.owner_id != self._owner_id:
            raise InspectionOwnershipError(
                "authenticated principal does not own this runtime"
            )

    def _export_counts(self, principal: AuthenticatedOwner) -> dict[str, int]:
        conversation = self._conversation
        memory_repository = self._memory_repository
        threads = conversation.list_threads(principal) if conversation is not None else ()
        message_count = 0
        turn_count = 0
        processing_count = 0
        for thread in threads:
            if conversation is None:
                continue
            message_count += len(conversation.list_messages(principal, thread.thread_id))
            thread_turns = conversation.list_turns(principal, thread.thread_id)
            turn_count += len(thread_turns)
            processing_count += len(conversation.list_processing(principal, thread.thread_id))
        assertion_count = (
            len(memory_repository.list_assertion_metadata(self._owner_id))
            if memory_repository is not None
            else 0
        )
        return {
            "assertion_inspections": assertion_count,
            "conversation_records": (
                len(threads) + message_count + turn_count + turn_count + processing_count
            ),
            "model_activity_entries": turn_count,
            "validation_artifacts": 11,
        }
