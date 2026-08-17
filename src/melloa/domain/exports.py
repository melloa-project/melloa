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


class EncryptedExportPackageHeader(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    package_format_id: QualifiedName = "melloa.encrypted-owner-export-package"
    package_format_version: SemanticVersion = "1.0.0"
    created_at: AwareDatetime
    inner_format_id: QualifiedName = "melloa.canonical-owner-export"
    inner_export_id: RecordId
    cipher: Literal["aes-256-gcm"] = "aes-256-gcm"
    kdf: Literal["scrypt"] = "scrypt"
    scrypt_n: Annotated[int, Field(ge=16384, le=1048576)]
    scrypt_r: Annotated[int, Field(ge=1, le=64)]
    scrypt_p: Annotated[int, Field(ge=1, le=16)]
    salt_b64: str = Field(min_length=22, max_length=64)
    nonce_b64: str = Field(min_length=16, max_length=32)
    plaintext_zip_hash: Sha256Digest
    plaintext_zip_size_bytes: Annotated[int, Field(gt=0)]
    ciphertext_size_bytes: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_package_header(self) -> EncryptedExportPackageHeader:
        if self.ciphertext_size_bytes <= self.plaintext_zip_size_bytes:
            raise ValueError("encrypted package ciphertext must include authentication tag")
        return self


class EncryptedExportPackageValidationReport(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    package_header: EncryptedExportPackageHeader | None = None
    bundle_validation: CanonicalExportValidationReport | None = None
    validated_at: AwareDatetime
    valid: bool
    errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_package_report(self) -> EncryptedExportPackageValidationReport:
        if self.valid:
            if self.errors:
                raise ValueError("valid encrypted export report cannot contain errors")
            if self.package_header is None or self.bundle_validation is None:
                raise ValueError("valid encrypted export report requires package and bundle data")
            if not self.bundle_validation.valid:
                raise ValueError("valid encrypted export report requires a valid bundle")
        elif not self.errors and (
            self.bundle_validation is None or self.bundle_validation.valid
        ):
            raise ValueError("invalid encrypted export report must explain at least one error")
        return self
