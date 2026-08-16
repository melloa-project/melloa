"""Authenticated owner inspection of redacted health and media metadata."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from melloa.application.inspection import InspectionOwnershipError
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import RecordId, utc_now
from melloa.domain.operations import (
    ExportCoverageItem,
    OwnerExportReadinessReport,
    OwnerHealthReport,
    OwnerMediaCatalog,
    aggregate_health_state,
)
from melloa.ports.operations import OperationsInspectionReader


class OwnerOperationsService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        reader: OperationsInspectionReader,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._owner_id = owner_id
        self._reader = reader
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
