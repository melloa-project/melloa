"""Owner-scoped retention and deletion evidence contracts."""

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


class RetentionMode(StrEnum):
    AUTOMATIC_EXPIRY = "automatic-expiry"
    OWNER_LIFECYCLE = "owner-lifecycle"
    FIXED_WINDOW = "fixed-window"
    APPEND_ONLY = "append-only"
    SOURCE_CONTROLLED = "source-controlled"


class RetentionDeletionScope(StrEnum):
    RAW_OBJECT = "raw-object"
    SOURCE_INTEGRATION = "source-integration"
    TIME_RANGE = "time-range"
    MEMORY_CLAIM = "memory-claim"
    FULL_EXPORT_AND_DELETE = "full-export-and-delete"


class RetentionDeletionControl(StrEnum):
    OWNER_REQUEST = "owner-request"
    AUTOMATIC_ONLY = "automatic-only"
    RESTRICTED = "restricted"
    NOT_IMPLEMENTED = "not-implemented"


class RetentionExternalCopyState(StrEnum):
    NONE = "none"
    SOURCE_CONTROLLED = "source-controlled"
    PROVIDER_CONTROLLED = "provider-controlled"
    UNKNOWN = "unknown"


class RetentionInventoryCoverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class BackupExpiryState(StrEnum):
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not-configured"
    UNKNOWN = "unknown"


class RetentionDurationBounds(ContractModel):
    minimum_seconds: Annotated[int, Field(ge=1)]
    default_seconds: Annotated[int, Field(ge=1)]
    maximum_seconds: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_bounds(self) -> RetentionDurationBounds:
        if not self.minimum_seconds <= self.default_seconds <= self.maximum_seconds:
            raise ValueError("retention duration must satisfy minimum <= default <= maximum")
        return self


class RetentionPolicyStatus(ContractModel):
    policy_id: QualifiedName
    data_category: QualifiedName
    summary: str = Field(min_length=1, max_length=512)
    mode: RetentionMode
    duration_bounds: RetentionDurationBounds | None = None
    automatic_expiry: bool
    deletion_control: RetentionDeletionControl
    owner_deletion_scopes: tuple[RetentionDeletionScope, ...] = ()
    tombstone_retained: bool
    derived_rebuild_required: bool
    external_copy_state: RetentionExternalCopyState
    status_reason: QualifiedName

    @model_validator(mode="after")
    def validate_policy(self) -> RetentionPolicyStatus:
        if self.owner_deletion_scopes != tuple(
            sorted(self.owner_deletion_scopes, key=lambda scope: scope.value)
        ):
            raise ValueError("owner deletion scopes must use deterministic order")
        if len(set(self.owner_deletion_scopes)) != len(self.owner_deletion_scopes):
            raise ValueError("owner deletion scopes must be unique")
        automatically_bounded_modes = {
            RetentionMode.AUTOMATIC_EXPIRY,
            RetentionMode.FIXED_WINDOW,
        }
        if self.mode in automatically_bounded_modes and not self.automatic_expiry:
            raise ValueError("automatic or fixed-window retention must expire automatically")
        if self.automatic_expiry and self.mode not in automatically_bounded_modes:
            raise ValueError("automatic expiry requires an automatic or fixed-window mode")
        if self.automatic_expiry and self.duration_bounds is None:
            raise ValueError("automatic expiry requires bounded retention duration")
        if self.mode is RetentionMode.APPEND_ONLY and (
            self.automatic_expiry
            or self.deletion_control is RetentionDeletionControl.OWNER_REQUEST
        ):
            raise ValueError("append-only retention cannot expose ordinary deletion")
        if self.deletion_control is RetentionDeletionControl.OWNER_REQUEST:
            if not self.owner_deletion_scopes:
                raise ValueError("owner-request deletion requires at least one scope")
        elif self.owner_deletion_scopes:
            raise ValueError("owner deletion scopes require owner-request control")
        if self.deletion_control is RetentionDeletionControl.AUTOMATIC_ONLY:
            if not self.automatic_expiry:
                raise ValueError("automatic-only deletion requires automatic expiry")
        return self


class RetentionInventoryStatus(ContractModel):
    policy_id: QualifiedName
    coverage: RetentionInventoryCoverage
    retained_objects: Annotated[int, Field(ge=0)] | None = None
    retained_bytes: Annotated[int, Field(ge=0)] | None = None
    overdue_objects: Annotated[int, Field(ge=0)] | None = None
    pending_deletions: Annotated[int, Field(ge=0)] | None = None
    deletion_receipts: Annotated[int, Field(ge=0)] | None = None
    oldest_retained_at: AwareDatetime | None = None
    next_expiry_at: AwareDatetime | None = None
    status_reason: QualifiedName

    @model_validator(mode="after")
    def validate_inventory(self) -> RetentionInventoryStatus:
        counts = (
            self.retained_objects,
            self.retained_bytes,
            self.overdue_objects,
            self.pending_deletions,
            self.deletion_receipts,
        )
        if self.coverage is RetentionInventoryCoverage.COMPLETE and any(
            count is None for count in counts
        ):
            raise ValueError("complete retention inventory requires every count")
        if self.coverage is RetentionInventoryCoverage.UNAVAILABLE and (
            any(count is not None for count in counts)
            or self.oldest_retained_at is not None
            or self.next_expiry_at is not None
        ):
            raise ValueError("unavailable retention inventory cannot claim measurements")
        if self.coverage is RetentionInventoryCoverage.PARTIAL and all(
            count is None for count in counts
        ):
            raise ValueError("partial retention inventory requires a measured count")
        if self.retained_objects is not None:
            if self.overdue_objects is not None and (
                self.overdue_objects > self.retained_objects
            ):
                raise ValueError("overdue retention objects cannot exceed retained objects")
            if self.pending_deletions is not None and (
                self.pending_deletions > self.retained_objects
            ):
                raise ValueError("pending deletions cannot exceed retained objects")
            if self.retained_objects == 0 and (
                self.oldest_retained_at is not None or self.next_expiry_at is not None
            ):
                raise ValueError("empty retention inventory cannot have object timestamps")
            if (
                self.coverage is RetentionInventoryCoverage.COMPLETE
                and self.retained_objects > 0
                and self.oldest_retained_at is None
            ):
                raise ValueError("complete non-empty inventory requires oldest retention time")
        return self


class BackupExpiryDisclosure(ContractModel):
    state: BackupExpiryState
    status_reason: QualifiedName
    maximum_retention_seconds: Annotated[int, Field(ge=1)] | None = None
    latest_snapshot_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_backup(self) -> BackupExpiryDisclosure:
        if self.state is BackupExpiryState.CONFIGURED:
            if self.maximum_retention_seconds is None:
                raise ValueError("configured backup expiry requires a maximum retention")
        elif self.maximum_retention_seconds is not None or self.latest_snapshot_at is not None:
            raise ValueError("unconfigured or unknown backup expiry cannot claim a horizon")
        return self


class OwnerRetentionReport(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    owner_id: RecordId
    generated_at: AwareDatetime
    policies: tuple[RetentionPolicyStatus, ...] = Field(min_length=1)
    inventory: tuple[RetentionInventoryStatus, ...] = Field(min_length=1)
    backup_expiry: BackupExpiryDisclosure

    @model_validator(mode="after")
    def validate_report(self) -> OwnerRetentionReport:
        policy_ids = tuple(policy.policy_id for policy in self.policies)
        inventory_ids = tuple(item.policy_id for item in self.inventory)
        if len(set(policy_ids)) != len(policy_ids):
            raise ValueError("retention policy IDs must be unique")
        if self.policies != tuple(sorted(self.policies, key=lambda policy: policy.policy_id)):
            raise ValueError("retention policies must use deterministic ID order")
        if self.inventory != tuple(
            sorted(self.inventory, key=lambda item: item.policy_id)
        ):
            raise ValueError("retention inventory must use deterministic policy order")
        if inventory_ids != policy_ids:
            raise ValueError("retention inventory must cover every reported policy exactly once")
        return self


class RetentionDeletionReceipt(ContractModel):
    """A content-free tombstone proving one retained object was deleted."""

    contract_version: Literal["1.0.0"] = "1.0.0"
    receipt_id: RecordId
    owner_id: RecordId
    object_id: RecordId
    object_type: QualifiedName
    content_hash: Sha256Digest
    size_bytes: Annotated[int, Field(ge=0)]
    retention_policy: QualifiedName
    retained_at: AwareDatetime
    expires_at: AwareDatetime
    deleted_at: AwareDatetime
    reason_code: QualifiedName

    @model_validator(mode="after")
    def validate_chronology(self) -> RetentionDeletionReceipt:
        if self.expires_at <= self.retained_at:
            raise ValueError("retention expiry must follow initial retention")
        if self.deleted_at < self.expires_at:
            raise ValueError("retention deletion cannot precede scheduled expiry")
        return self
