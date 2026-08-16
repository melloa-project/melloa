"""Owner-visible operational health and retained-media metadata contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import (
    AwareDatetime,
    ContractModel,
    QualifiedName,
    RecordId,
    Sha256Digest,
)
from melloa.domain.classification import Sensitivity
from melloa.domain.events import Confidence


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class HealthCategory(StrEnum):
    APPLICATION = "application"
    WORKER = "worker"
    DATABASE = "database"
    QUEUE = "queue"
    PROVIDER = "provider"
    CAMERA = "camera"
    STORAGE = "storage"
    BACKUP = "backup"
    DEPLOYMENT = "deployment"


class ComponentHealth(ContractModel):
    component_id: QualifiedName
    category: HealthCategory
    state: HealthState
    required: bool
    observed_at: AwareDatetime
    summary: str = Field(min_length=1, max_length=512)
    version: str | None = Field(default=None, min_length=1, max_length=128)


class OwnerHealthReport(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    owner_id: RecordId
    generated_at: AwareDatetime
    overall_state: HealthState
    components: tuple[ComponentHealth, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_report(self) -> OwnerHealthReport:
        component_ids = tuple(component.component_id for component in self.components)
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("health component IDs must be unique")
        if self.components != tuple(
            sorted(
                self.components,
                key=lambda component: (component.category.value, component.component_id),
            )
        ):
            raise ValueError("health components must use deterministic category/ID order")
        if self.overall_state is not aggregate_health_state(self.components):
            raise ValueError("overall health does not match component health")
        return self


class MissingMediaInterval(ContractModel):
    started_at: AwareDatetime
    ended_at: AwareDatetime
    reason_code: QualifiedName

    @model_validator(mode="after")
    def validate_interval(self) -> MissingMediaInterval:
        if self.ended_at <= self.started_at:
            raise ValueError("missing-media interval must end after it starts")
        return self


class MediaSourceStatus(ContractModel):
    capability_id: QualifiedName
    installed: bool
    capture_enabled: bool
    health_state: HealthState
    observed_at: AwareDatetime
    status_reason: QualifiedName
    last_capture_at: AwareDatetime | None = None
    missing_intervals: tuple[MissingMediaInterval, ...] = ()

    @model_validator(mode="after")
    def validate_source(self) -> MediaSourceStatus:
        if not self.installed and (
            self.capture_enabled
            or self.health_state is not HealthState.DISABLED
            or self.last_capture_at is not None
            or self.missing_intervals
        ):
            raise ValueError("uninstalled media sources must be disabled and have no captures")
        if self.capture_enabled and self.health_state is HealthState.DISABLED:
            raise ValueError("enabled media capture cannot report disabled health")
        if self.last_capture_at is not None and self.last_capture_at > self.observed_at:
            raise ValueError("last media capture cannot follow the source observation time")
        if self.missing_intervals != tuple(
            sorted(self.missing_intervals, key=lambda interval: interval.started_at)
        ):
            raise ValueError("missing-media intervals must use chronological order")
        for previous, current in zip(
            self.missing_intervals,
            self.missing_intervals[1:],
            strict=False,
        ):
            if current.started_at < previous.ended_at:
                raise ValueError("missing-media intervals cannot overlap")
        return self


class MediaRetentionState(StrEnum):
    RETAINED = "retained"
    DELETION_PENDING = "deletion_pending"
    DELETED = "deleted"
    EXPIRED = "expired"


class MediaItemMetadata(ContractModel):
    media_id: RecordId
    owner_id: RecordId
    source_capability_id: QualifiedName
    event_id: RecordId
    media_type: Annotated[str, Field(pattern=r"^[a-z0-9.+-]+/[a-z0-9.+-]+$")]
    content_hash: Sha256Digest
    sensitivity: Sensitivity
    captured_from: AwareDatetime
    captured_to: AwareDatetime
    interpretation_confidence: Confidence | None = None
    retention_policy: QualifiedName
    retained_at: AwareDatetime
    expires_at: AwareDatetime
    size_bytes: Annotated[int, Field(ge=0)]
    retention_state: MediaRetentionState
    disclosure_record_ids: tuple[RecordId, ...] = ()

    @model_validator(mode="after")
    def validate_metadata(self) -> MediaItemMetadata:
        if self.captured_to < self.captured_from:
            raise ValueError("media capture end cannot precede its start")
        if self.retained_at < self.captured_to:
            raise ValueError("media cannot be retained before capture completes")
        if self.expires_at <= self.retained_at:
            raise ValueError("media expiry must follow retention time")
        if len(set(self.disclosure_record_ids)) != len(self.disclosure_record_ids):
            raise ValueError("media disclosure record IDs must be unique")
        return self


class OwnerMediaCatalog(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    owner_id: RecordId
    generated_at: AwareDatetime
    capture_enabled: bool
    content_endpoint_available: Literal[False] = False
    sources: tuple[MediaSourceStatus, ...]
    items: tuple[MediaItemMetadata, ...]

    @model_validator(mode="after")
    def validate_catalog(self) -> OwnerMediaCatalog:
        source_ids = tuple(source.capability_id for source in self.sources)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("media source capability IDs must be unique")
        if self.sources != tuple(sorted(self.sources, key=lambda source: source.capability_id)):
            raise ValueError("media sources must use deterministic capability order")
        if self.capture_enabled != any(source.capture_enabled for source in self.sources):
            raise ValueError("catalog capture state does not match its sources")
        media_ids = tuple(item.media_id for item in self.items)
        if len(set(media_ids)) != len(media_ids):
            raise ValueError("media IDs must be unique")
        if self.items != tuple(
            sorted(self.items, key=lambda item: (item.captured_from, item.media_id))
        ):
            raise ValueError("media items must use deterministic capture/ID order")
        if any(item.owner_id != self.owner_id for item in self.items):
            raise ValueError("media catalog cannot contain another owner's records")
        if any(item.source_capability_id not in source_ids for item in self.items):
            raise ValueError("media item references an unknown source capability")
        return self


class ExportCoverageItem(ContractModel):
    group_id: QualifiedName
    included: bool
    estimated_records: Annotated[int, Field(ge=0)] | None = None
    artifact_path: str | None = Field(default=None, min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=512)
    status_reason: QualifiedName

    @model_validator(mode="after")
    def validate_item(self) -> ExportCoverageItem:
        if not self.included and self.estimated_records is not None:
            raise ValueError("excluded export groups cannot report record estimates")
        if self.artifact_path is None:
            return self
        if self.artifact_path.startswith("/") or ".." in self.artifact_path.split("/"):
            raise ValueError("export artifact paths must be relative and contained")
        return self


class OwnerExportReadinessReport(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    owner_id: RecordId
    generated_at: AwareDatetime
    format_id: QualifiedName = "melloa.canonical-owner-export"
    cli_command: str = Field(min_length=1, max_length=512)
    validation_command: str = Field(min_length=1, max_length=256)
    encrypted: bool
    includes_sql_snapshot: bool
    includes_blobs: bool
    coverage: tuple[ExportCoverageItem, ...] = Field(min_length=1)
    limitations: tuple[QualifiedName, ...]

    @model_validator(mode="after")
    def validate_report(self) -> OwnerExportReadinessReport:
        group_ids = tuple(item.group_id for item in self.coverage)
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("export coverage groups must be unique")
        if self.coverage != tuple(sorted(self.coverage, key=lambda item: item.group_id)):
            raise ValueError("export coverage must use deterministic group order")
        if not any(item.included for item in self.coverage):
            raise ValueError("export readiness must include at least one covered group")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("export limitations must be unique")
        if self.limitations != tuple(sorted(self.limitations)):
            raise ValueError("export limitations must use deterministic order")
        if not self.encrypted and "export.preview-unencrypted" not in self.limitations:
            raise ValueError("unencrypted exports must disclose the preview limitation")
        if not self.includes_sql_snapshot and (
            "export.sql-snapshot-not-included" not in self.limitations
        ):
            raise ValueError("exports without SQL snapshots must disclose that limitation")
        if not self.includes_blobs and "export.blobs-not-included" not in self.limitations:
            raise ValueError("exports without blobs must disclose that limitation")
        return self


def aggregate_health_state(components: tuple[ComponentHealth, ...]) -> HealthState:
    if any(
        component.required and component.state is HealthState.UNAVAILABLE
        for component in components
    ):
        return HealthState.UNAVAILABLE
    if any(
        component.state in {HealthState.DEGRADED, HealthState.UNAVAILABLE}
        for component in components
    ):
        return HealthState.DEGRADED
    if any(component.state is HealthState.HEALTHY for component in components):
        return HealthState.HEALTHY
    return HealthState.DISABLED
