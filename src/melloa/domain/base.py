"""Shared value types and canonical serialization for durable contracts."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

RecordId = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9_]{1,31}_[0-9a-f]{32}$", min_length=35, max_length=65),
]
QualifiedName = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9_.-]{1,127}$", min_length=2, max_length=128),
]
SemanticVersion = Annotated[
    str,
    Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$",
        max_length=64,
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
NonEmptyText = Annotated[str, Field(min_length=1, max_length=4096)]
JsonObject = dict[str, Any]


class ContractModel(BaseModel):
    """Strict, immutable base for versioned wire and persistence contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def new_record_id(prefix: str) -> str:
    """Create an opaque record identifier without encoding display names."""

    if re.fullmatch(r"[a-z][a-z0-9_]{1,31}", prefix) is None:
        raise ValueError("record ID prefix must be a lowercase neutral identifier")
    return f"{prefix}_{uuid.uuid4().hex}"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def canonical_json_bytes(value: BaseModel | JsonObject) -> bytes:
    """Serialize JSON deterministically for hashes and exact approvals."""

    if isinstance(value, BaseModel):
        document = value.model_dump(mode="json")
    else:
        document = value
    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_digest(value: bytes) -> str:
    """Return a tagged SHA-256 digest."""

    return f"sha256:{hashlib.sha256(value).hexdigest()}"


__all__ = [
    "AwareDatetime",
    "ContractModel",
    "JsonObject",
    "NonEmptyText",
    "QualifiedName",
    "RecordId",
    "SemanticVersion",
    "Sha256Digest",
    "canonical_json_bytes",
    "new_record_id",
    "sha256_digest",
    "utc_now",
]
