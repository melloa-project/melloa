"""Canonical owner export contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from melloa.domain.base import (
    AwareDatetime,
    ContractModel,
    QualifiedName,
    RecordId,
    SemanticVersion,
    Sha256Digest,
)


class ExportFileKind(StrEnum):
    DATA = "data"
    SCHEMA = "schema"


class ExportFileEntry(ContractModel):
    path: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9._/-]+$")
    kind: ExportFileKind
    record_type: QualifiedName | None = None
    schema_path: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    content_hash: Sha256Digest
    size_bytes: Annotated[int, Field(ge=0)]
    record_count: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def validate_file_entry(self) -> ExportFileEntry:
        if self.path.startswith("/") or "/../" in f"/{self.path}/":
            raise ValueError("export file path must be relative and contained")
        if self.schema_path is not None and (
            self.schema_path.startswith("/") or "/../" in f"/{self.schema_path}/"
        ):
            raise ValueError("export schema path must be relative and contained")
        if self.kind is ExportFileKind.DATA:
            if self.record_type is None or self.schema_path is None:
                raise ValueError("data files require record type and schema path")
            if self.record_count is None:
                raise ValueError("data files require record count")
        elif self.record_type is not None or self.record_count is not None:
            raise ValueError("schema files cannot declare data records")
        return self


class CanonicalExportManifest(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    export_id: RecordId
    format_id: QualifiedName = "melloa.canonical-owner-export"
    format_version: SemanticVersion = "1.0.0"
    owner_id: RecordId
    intelligence_id: RecordId
    created_at: AwareDatetime
    source_runtime: str = Field(min_length=1, max_length=256)
    encrypted: bool
    includes_sql_snapshot: bool
    includes_blobs: bool
    files: tuple[ExportFileEntry, ...] = Field(min_length=1)
    limitations: tuple[QualifiedName, ...] = ()

    @model_validator(mode="after")
    def validate_manifest(self) -> CanonicalExportManifest:
        paths = tuple(entry.path for entry in self.files)
        if len(set(paths)) != len(paths):
            raise ValueError("export manifest file paths must be unique")
        if self.encrypted:
            raise ValueError("unencrypted preview contract cannot claim encryption")
        return self


class CanonicalExportValidationReport(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    export_id: RecordId | None = None
    validated_at: AwareDatetime
    valid: bool
    files_checked: Annotated[int, Field(ge=0)]
    record_counts: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_report(self) -> CanonicalExportValidationReport:
        if self.valid and self.errors:
            raise ValueError("valid export report cannot contain errors")
        if not self.valid and not self.errors:
            raise ValueError("invalid export report must explain at least one error")
        return self
