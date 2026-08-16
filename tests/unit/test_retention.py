from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from melloa.domain.base import sha256_digest
from melloa.domain.retention import RetentionDeletionReceipt
from tests.conftest import record_id


def deletion_receipt(fixed_time) -> RetentionDeletionReceipt:
    return RetentionDeletionReceipt(
        receipt_id=record_id("deletion", 1),
        owner_id=record_id("owner", 1),
        object_id=record_id("quarantine", 1),
        object_type="object.telegram-quarantine-blob",
        content_hash=sha256_digest(b"deleted synthetic content"),
        size_bytes=25,
        retention_policy="retention.telegram-quarantine",
        retained_at=fixed_time,
        expires_at=fixed_time + timedelta(hours=1),
        deleted_at=fixed_time + timedelta(hours=1),
        reason_code="retention.expired",
    )


def test_deletion_receipt_is_content_free_owner_scoped_evidence(fixed_time) -> None:
    receipt = deletion_receipt(fixed_time)

    assert receipt.owner_id == record_id("owner", 1)
    assert receipt.deleted_at == receipt.expires_at
    document = receipt.model_dump(mode="json")
    assert "content" not in document
    assert document["content_hash"] == sha256_digest(b"deleted synthetic content")


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": "retained_at"},
        {"deleted_at": "before_expiry"},
    ],
)
def test_deletion_receipt_rejects_impossible_chronology(
    fixed_time,
    changes: dict[str, str],
) -> None:
    receipt = deletion_receipt(fixed_time)
    document = receipt.model_dump()
    if changes.get("expires_at") == "retained_at":
        document["expires_at"] = receipt.retained_at
    if changes.get("deleted_at") == "before_expiry":
        document["deleted_at"] = receipt.expires_at - timedelta(microseconds=1)

    with pytest.raises(ValidationError, match="retention"):
        RetentionDeletionReceipt(**document)
