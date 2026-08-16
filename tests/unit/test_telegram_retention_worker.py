from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.telegram import (
    InMemoryTelegramAttachmentQuarantine,
    RejectingTelegramAttachmentBackend,
    SyntheticTelegramAttachmentPayload,
)
from melloa.application.telegram import (
    TelegramAttachmentRetentionWorker,
    TelegramRetentionUnavailableError,
)
from melloa.domain.base import sha256_digest
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.retention import RetentionDeletionReceipt
from melloa.domain.telegram import (
    TelegramAttachmentIntakeRequest,
    TelegramAttachmentKind,
    TelegramAttachmentReference,
)
from melloa.ports.telegram import TelegramAttachmentConflictError
from tests.conftest import record_id

OWNER_ID = record_id("owner", 1)
ADAPTER_ID = "client.telegram.synthetic"


def guardian(fixed_time: datetime, mode: GuardianMode) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=mode,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.retention-test",
        ),
        receipt_hash="sha256:" + "7" * 64,
    )


def intake_request(fixed_time: datetime) -> TelegramAttachmentIntakeRequest:
    return TelegramAttachmentIntakeRequest(
        adapter_id=ADAPTER_ID,
        update_id=10,
        update_fingerprint=sha256_digest(b"retention-worker-update"),
        received_at=fixed_time,
        attachments=(
            TelegramAttachmentReference(
                kind=TelegramAttachmentKind.DOCUMENT,
                file_id="synthetic-file-1",
                file_unique_id="synthetic-unique-1",
                declared_size_bytes=4,
                media_type="text/plain",
                file_name="retention.txt",
            ),
        ),
    )


def quarantine(fixed_time: datetime) -> InMemoryTelegramAttachmentQuarantine:
    return InMemoryTelegramAttachmentQuarantine(
        {
            "synthetic-unique-1": SyntheticTelegramAttachmentPayload(
                content=b"safe",
                media_type="text/plain",
            )
        },
        owner_id=OWNER_ID,
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=4,
        max_quarantine_bytes=4,
        retention_ttl=timedelta(hours=1),
        clock=lambda: fixed_time,
        id_factory=lambda _prefix: record_id("deletion", 1),
    )


@pytest.mark.parametrize("mode", [GuardianMode.NORMAL, GuardianMode.OFFLINE])
def test_retention_worker_deletes_due_blob_locally_in_permitted_modes(
    fixed_time: datetime,
    mode: GuardianMode,
) -> None:
    backend = quarantine(fixed_time)
    intake = backend.handle(intake_request(fixed_time))
    blob_id = intake[0].quarantine_blob_id
    content_hash = intake[0].content_hash
    worker = TelegramAttachmentRetentionWorker(
        backend=backend,
        guardian_reader=guardian(fixed_time, mode),
        batch_limit=1,
        clock=lambda: fixed_time + timedelta(hours=1),
    )

    cycle = worker.sweep_once()

    assert cycle.swept_at == fixed_time + timedelta(hours=1)
    assert len(cycle.deletion_receipts) == 1
    assert cycle.deletion_receipts[0].object_id == blob_id
    assert backend.stored_blob_ids == ()
    health = worker.health()
    assert health["state"] == "healthy"
    assert health["cycles"] == 1
    assert health["deletions"] == 1
    health_json = json.dumps(health)
    assert blob_id not in health_json
    assert content_hash not in health_json
    assert OWNER_ID not in health_json


@pytest.mark.parametrize(
    "mode",
    [
        GuardianMode.NO_ACTIONS,
        GuardianMode.READ_ONLY,
        GuardianMode.STOPPED,
        GuardianMode.RECOVERY,
    ],
)
def test_retention_worker_denies_destructive_sweep_before_backend_access(
    fixed_time: datetime,
    mode: GuardianMode,
) -> None:
    backend = RejectingTelegramAttachmentBackend(
        owner_id=OWNER_ID,
        clock=lambda: fixed_time,
    )
    worker = TelegramAttachmentRetentionWorker(
        backend=backend,
        guardian_reader=guardian(fixed_time, mode),
        clock=lambda: fixed_time,
    )

    with pytest.raises(TelegramRetentionUnavailableError, match=mode.value):
        worker.sweep_once()

    assert backend.sweeps == []
    health = worker.health()
    assert health["state"] == "disabled"
    assert health["reason_code"] == f"guardian.{mode.value.replace('-', '_')}"
    assert health["cycles"] == 0


class FailingRetentionBackend:
    owner_id = OWNER_ID

    def __init__(self) -> None:
        self.calls: list[tuple[datetime, int]] = []

    def sweep_expired(
        self,
        *,
        as_of: datetime,
        limit: int = 100,
    ) -> tuple[RetentionDeletionReceipt, ...]:
        self.calls.append((as_of, limit))
        raise RuntimeError("private synthetic backend detail")


def test_retention_worker_redacts_backend_failure_from_health(fixed_time: datetime) -> None:
    backend = FailingRetentionBackend()
    worker = TelegramAttachmentRetentionWorker(
        backend=backend,
        guardian_reader=guardian(fixed_time, GuardianMode.NORMAL),
        batch_limit=7,
        clock=lambda: fixed_time,
    )

    with pytest.raises(RuntimeError, match="private synthetic"):
        worker.sweep_once()

    assert backend.calls == [(fixed_time, 7)]
    health = worker.health()
    assert health["state"] == "degraded"
    assert health["reason_code"] == "retention.worker.cycle_failed"
    assert health["last_error_code"] == "retention.worker.cycle_failed"
    assert "private synthetic" not in json.dumps(health)


class StaticRetentionBackend:
    owner_id = OWNER_ID

    def __init__(self, receipts: tuple[RetentionDeletionReceipt, ...]) -> None:
        self.receipts = receipts

    def sweep_expired(
        self,
        *,
        as_of: datetime,
        limit: int = 100,
    ) -> tuple[RetentionDeletionReceipt, ...]:
        return self.receipts


def deletion_receipt(
    fixed_time: datetime,
    number: int,
    *,
    owner_id: str = OWNER_ID,
) -> RetentionDeletionReceipt:
    return RetentionDeletionReceipt(
        receipt_id=record_id("deletion", number),
        owner_id=owner_id,
        object_id=record_id("quarantine", number),
        object_type="object.telegram-quarantine-blob",
        content_hash=sha256_digest(f"deleted-{number}".encode()),
        size_bytes=4,
        retention_policy="retention.telegram-quarantine",
        retained_at=fixed_time,
        expires_at=fixed_time + timedelta(hours=1),
        deleted_at=fixed_time + timedelta(hours=1),
        reason_code="retention.expired",
    )


@pytest.mark.parametrize("violation", ["limit", "duplicate", "owner"])
def test_retention_worker_rejects_malformed_backend_receipts(
    fixed_time: datetime,
    violation: str,
) -> None:
    first = deletion_receipt(fixed_time, 1)
    if violation == "limit":
        receipts = (first, deletion_receipt(fixed_time, 2))
        batch_limit = 1
    elif violation == "duplicate":
        receipts = (first, first)
        batch_limit = 2
    else:
        receipts = (deletion_receipt(fixed_time, 2, owner_id=record_id("owner", 2)),)
        batch_limit = 2
    worker = TelegramAttachmentRetentionWorker(
        backend=StaticRetentionBackend(receipts),
        guardian_reader=guardian(fixed_time, GuardianMode.NORMAL),
        batch_limit=batch_limit,
        clock=lambda: fixed_time + timedelta(hours=1),
    )

    with pytest.raises(TelegramAttachmentConflictError):
        worker.sweep_once()

    assert worker.health()["state"] == "degraded"


def test_retention_worker_requires_a_bounded_batch(fixed_time: datetime) -> None:
    backend = RejectingTelegramAttachmentBackend(
        owner_id=OWNER_ID,
        clock=lambda: fixed_time,
    )
    for batch_limit in (0, 1_001):
        with pytest.raises(ValueError, match="batch limit"):
            TelegramAttachmentRetentionWorker(
                backend=backend,
                guardian_reader=guardian(fixed_time, GuardianMode.NORMAL),
                batch_limit=batch_limit,
            )
