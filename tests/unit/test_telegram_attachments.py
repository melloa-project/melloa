from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from melloa.adapters.fakes.telegram import (
    InMemoryTelegramAttachmentQuarantine,
    RejectingTelegramAttachmentBackend,
    SyntheticTelegramAttachmentPayload,
)
from melloa.domain.base import sha256_digest
from melloa.domain.telegram import (
    TelegramAttachmentDisposition,
    TelegramAttachmentIntakeRequest,
    TelegramAttachmentKind,
    TelegramAttachmentReceipt,
    TelegramAttachmentReference,
    validate_telegram_attachment_receipts,
)
from melloa.ports.telegram import (
    TelegramAttachmentConflictError,
    TransientTelegramAttachmentError,
)
from tests.conftest import record_id

ADAPTER_ID = "client.telegram.synthetic"
OWNER_ID = "owner_00000000000000000000000000000001"


def attachment(
    number: int,
    *,
    kind: TelegramAttachmentKind = TelegramAttachmentKind.DOCUMENT,
    declared_size_bytes: int | None = 4,
    media_type: str | None = "text/plain",
) -> TelegramAttachmentReference:
    return TelegramAttachmentReference(
        kind=kind,
        file_id=f"synthetic-file-{number}",
        file_unique_id=f"synthetic-unique-{number}",
        declared_size_bytes=declared_size_bytes,
        media_type=media_type,
        file_name=f"attachment-{number}.txt",
    )


def intake_request(
    fixed_time,
    attachments: tuple[TelegramAttachmentReference, ...],
    *,
    update_id: int = 10,
) -> TelegramAttachmentIntakeRequest:
    return TelegramAttachmentIntakeRequest(
        adapter_id=ADAPTER_ID,
        update_id=update_id,
        update_fingerprint=sha256_digest(f"telegram-update-{update_id}".encode()),
        received_at=fixed_time,
        attachments=attachments,
    )


def quarantine_backend(fixed_time, payloads):
    return InMemoryTelegramAttachmentQuarantine(
        payloads,
        owner_id=OWNER_ID,
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=1_024,
        max_quarantine_bytes=2_048,
        clock=lambda: fixed_time + timedelta(seconds=1),
    )


def test_rejecting_backend_never_fetches_and_returns_exact_replay(fixed_time) -> None:
    backend = RejectingTelegramAttachmentBackend(
        owner_id=OWNER_ID,
        clock=lambda: fixed_time + timedelta(seconds=1)
    )
    request = intake_request(fixed_time, (attachment(1), attachment(2)))

    receipts = backend.handle(request)

    assert tuple(item.disposition for item in receipts) == (
        TelegramAttachmentDisposition.REJECTED,
        TelegramAttachmentDisposition.REJECTED,
    )
    assert all(
        item.reason_code == "telegram.attachment.unsupported"
        and item.quarantine_blob_id is None
        and item.content_hash is None
        for item in receipts
    )
    assert backend.handle(request) == receipts
    assert backend.requests == [request, request]

    changed = request.model_copy(
        update={"update_fingerprint": sha256_digest(b"changed-update")}
    )
    with pytest.raises(TelegramAttachmentConflictError, match="changed across replay"):
        backend.handle(changed)


def test_quarantine_is_bounded_content_addressed_and_idempotent(fixed_time) -> None:
    payload = SyntheticTelegramAttachmentPayload(
        content=b"safe",
        media_type="text/plain",
    )
    backend = quarantine_backend(
        fixed_time,
        {
            "synthetic-unique-1": payload,
            "synthetic-unique-2": payload,
        },
    )
    first = intake_request(
        fixed_time,
        (
            attachment(1, media_type="Text/Plain; charset=utf-8"),
            attachment(2),
        ),
    )

    receipts = backend.handle(first)

    assert tuple(item.disposition for item in receipts) == (
        TelegramAttachmentDisposition.QUARANTINED,
        TelegramAttachmentDisposition.QUARANTINED,
    )
    assert receipts[0].quarantine_blob_id == receipts[1].quarantine_blob_id
    assert receipts[0].content_hash == sha256_digest(b"safe")
    assert receipts[0].size_bytes == 4
    assert receipts[0].media_type == "text/plain"
    assert backend.stored_blob_ids == (receipts[0].quarantine_blob_id,)
    assert backend.has_blob(receipts[0].quarantine_blob_id)
    assert backend.fetched_file_unique_ids == [
        "synthetic-unique-1",
        "synthetic-unique-2",
    ]

    assert backend.handle(first) == receipts
    assert backend.fetched_file_unique_ids == [
        "synthetic-unique-1",
        "synthetic-unique-2",
    ]


def test_metadata_policy_rejects_before_any_synthetic_fetch(fixed_time) -> None:
    references = (
        attachment(1, kind=TelegramAttachmentKind.PHOTO),
        attachment(2, declared_size_bytes=1_025),
        attachment(3, media_type="application/x-msdownload"),
        attachment(4, declared_size_bytes=None),
        attachment(5, media_type=None),
    )
    backend = quarantine_backend(
        fixed_time,
        {
            item.file_unique_id: SyntheticTelegramAttachmentPayload(
                content=b"safe",
                media_type="text/plain",
            )
            for item in references
        },
    )

    receipts = backend.handle(intake_request(fixed_time, references))

    assert tuple(item.reason_code for item in receipts) == (
        "telegram.attachment.kind_denied",
        "telegram.attachment.declared_size_exceeded",
        "telegram.attachment.media_type_denied",
        "telegram.attachment.size_unknown",
        "telegram.attachment.media_type_unknown",
    )
    assert backend.fetched_file_unique_ids == []
    assert backend.stored_blob_ids == ()


def test_post_fetch_mismatch_rejects_and_missing_payload_is_retryable(fixed_time) -> None:
    mismatched = quarantine_backend(
        fixed_time,
        {
            "synthetic-unique-1": SyntheticTelegramAttachmentPayload(
                content=b"wrong",
                media_type="text/plain",
            )
        },
    )
    request = intake_request(fixed_time, (attachment(1),))

    receipts = mismatched.handle(request)

    assert receipts[0].disposition is TelegramAttachmentDisposition.REJECTED
    assert receipts[0].reason_code == "telegram.attachment.size_mismatch"
    assert mismatched.fetched_file_unique_ids == ["synthetic-unique-1"]
    assert mismatched.stored_blob_ids == ()

    missing = quarantine_backend(fixed_time, {})
    with pytest.raises(TransientTelegramAttachmentError) as failure:
        missing.handle(request)
    assert failure.value.reason_code == "telegram.attachment.fetch_unavailable"
    assert failure.value.retryable is True
    assert missing.stored_blob_ids == ()


def test_quarantine_enforces_a_hard_deduplicated_byte_quota(fixed_time) -> None:
    backend = InMemoryTelegramAttachmentQuarantine(
        {
            "synthetic-unique-1": SyntheticTelegramAttachmentPayload(
                content=b"safe",
                media_type="text/plain",
            ),
            "synthetic-unique-2": SyntheticTelegramAttachmentPayload(
                content=b"more",
                media_type="text/plain",
            ),
        },
        owner_id=OWNER_ID,
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=4,
        max_quarantine_bytes=4,
        clock=lambda: fixed_time,
    )

    receipts = backend.handle(
        intake_request(fixed_time, (attachment(1), attachment(2)))
    )

    assert receipts[0].disposition is TelegramAttachmentDisposition.QUARANTINED
    assert receipts[1].disposition is TelegramAttachmentDisposition.REJECTED
    assert receipts[1].reason_code == "telegram.attachment.quarantine_quota_exceeded"
    assert len(backend.stored_blob_ids) == 1

    with pytest.raises(ValueError, match="quota must cover one attachment"):
        InMemoryTelegramAttachmentQuarantine(
            {},
            owner_id=OWNER_ID,
            allowed_kinds=frozenset(),
            allowed_media_types=frozenset(),
            max_attachment_bytes=5,
            max_quarantine_bytes=4,
        )


def test_quarantine_expiry_emits_tombstone_and_reclaims_hard_quota(fixed_time) -> None:
    deletion_ids = iter((record_id("deletion", 1),))
    backend = InMemoryTelegramAttachmentQuarantine(
        {
            "synthetic-unique-1": SyntheticTelegramAttachmentPayload(
                content=b"safe",
                media_type="text/plain",
            ),
            "synthetic-unique-2": SyntheticTelegramAttachmentPayload(
                content=b"more",
                media_type="text/plain",
            ),
        },
        owner_id=OWNER_ID,
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=4,
        max_quarantine_bytes=4,
        retention_ttl=timedelta(hours=1),
        clock=lambda: fixed_time,
        id_factory=lambda _prefix: next(deletion_ids),
    )
    first_request = intake_request(fixed_time, (attachment(1),))
    first_receipts = backend.handle(first_request)
    blob_id = first_receipts[0].quarantine_blob_id
    assert blob_id is not None
    expires_at = fixed_time + timedelta(hours=1)

    assert backend.owner_id == OWNER_ID
    assert backend.retention_deadline(blob_id) == expires_at
    assert backend.sweep_expired(
        as_of=expires_at - timedelta(microseconds=1)
    ) == ()

    deleted = backend.sweep_expired(as_of=expires_at)

    assert len(deleted) == 1
    receipt = deleted[0]
    assert receipt.receipt_id == record_id("deletion", 1)
    assert receipt.owner_id == OWNER_ID
    assert receipt.object_id == blob_id
    assert receipt.object_type == "object.telegram-quarantine-blob"
    assert receipt.content_hash == sha256_digest(b"safe")
    assert receipt.size_bytes == 4
    assert receipt.retention_policy == "retention.telegram-quarantine"
    assert receipt.retained_at == fixed_time
    assert receipt.expires_at == expires_at
    assert receipt.deleted_at == expires_at
    assert receipt.reason_code == "retention.expired"
    assert backend.stored_blob_ids == ()
    assert backend.deletion_receipts == deleted
    assert backend.sweep_expired(as_of=expires_at) == ()

    second_request = intake_request(
        fixed_time + timedelta(hours=2),
        (attachment(2),),
        update_id=11,
    )
    second_receipts = backend.handle(second_request)

    assert second_receipts[0].disposition is TelegramAttachmentDisposition.QUARANTINED
    assert len(backend.stored_blob_ids) == 1
    assert backend.handle(first_request) == first_receipts
    assert backend.fetched_file_unique_ids == [
        "synthetic-unique-1",
        "synthetic-unique-2",
    ]


def test_quarantine_sweep_is_bounded_deterministic_and_atomic(fixed_time) -> None:
    deletion_ids = iter(
        (
            record_id("deletion", 1),
            record_id("deletion", 2),
            record_id("deletion", 3),
        )
    )
    payloads = {
        f"synthetic-unique-{number}": SyntheticTelegramAttachmentPayload(
            content=bytes([96 + number]) * 4,
            media_type="text/plain",
        )
        for number in range(1, 4)
    }
    backend = InMemoryTelegramAttachmentQuarantine(
        payloads,
        owner_id=OWNER_ID,
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=4,
        max_quarantine_bytes=12,
        retention_ttl=timedelta(hours=1),
        clock=lambda: fixed_time,
        id_factory=lambda _prefix: next(deletion_ids),
    )
    backend.handle(
        intake_request(fixed_time, tuple(attachment(number) for number in range(1, 4)))
    )
    stored = backend.stored_blob_ids

    first_batch = backend.sweep_expired(
        as_of=fixed_time + timedelta(hours=1),
        limit=2,
    )

    assert tuple(item.object_id for item in first_batch) == stored[:2]
    assert backend.stored_blob_ids == stored[2:]
    second_batch = backend.sweep_expired(
        as_of=fixed_time + timedelta(hours=1),
        limit=2,
    )
    assert tuple(item.object_id for item in second_batch) == stored[2:]
    assert backend.stored_blob_ids == ()

    duplicate_id = record_id("deletion", 9)
    conflicting = InMemoryTelegramAttachmentQuarantine(
        payloads,
        owner_id=OWNER_ID,
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=4,
        max_quarantine_bytes=12,
        retention_ttl=timedelta(hours=1),
        clock=lambda: fixed_time,
        id_factory=lambda _prefix: duplicate_id,
    )
    conflicting.handle(
        intake_request(fixed_time, (attachment(1), attachment(2)))
    )
    before = conflicting.stored_blob_ids

    with pytest.raises(TelegramAttachmentConflictError, match="deletion receipt"):
        conflicting.sweep_expired(as_of=fixed_time + timedelta(hours=1), limit=2)

    assert conflicting.stored_blob_ids == before
    assert conflicting.deletion_receipts == ()


def test_deduplicated_blob_retention_extends_for_a_new_exact_reference(fixed_time) -> None:
    payload = SyntheticTelegramAttachmentPayload(content=b"safe", media_type="text/plain")
    backend = InMemoryTelegramAttachmentQuarantine(
        {
            "synthetic-unique-1": payload,
            "synthetic-unique-2": payload,
        },
        owner_id=OWNER_ID,
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=4,
        max_quarantine_bytes=4,
        retention_ttl=timedelta(hours=1),
        clock=lambda: fixed_time,
        id_factory=lambda _prefix: record_id("deletion", 21),
    )
    first = backend.handle(intake_request(fixed_time, (attachment(1),)))
    blob_id = first[0].quarantine_blob_id
    assert blob_id is not None
    second_received_at = fixed_time + timedelta(minutes=30)

    second = backend.handle(
        intake_request(second_received_at, (attachment(2),), update_id=11)
    )

    assert second[0].quarantine_blob_id == blob_id
    extended_expiry = second_received_at + timedelta(hours=1)
    assert backend.retention_deadline(blob_id) == extended_expiry
    assert backend.sweep_expired(as_of=fixed_time + timedelta(hours=1)) == ()
    assert backend.has_blob(blob_id)
    assert len(backend.sweep_expired(as_of=extended_expiry)) == 1
    assert not backend.has_blob(blob_id)


def test_quarantine_rejects_unbounded_or_ambiguous_retention_sweeps(fixed_time) -> None:
    for retention_ttl in (timedelta(minutes=59), timedelta(days=7, seconds=1)):
        with pytest.raises(ValueError, match="between one hour and seven days"):
            InMemoryTelegramAttachmentQuarantine(
                {},
                owner_id=OWNER_ID,
                allowed_kinds=frozenset(),
                allowed_media_types=frozenset(),
                max_attachment_bytes=1,
                max_quarantine_bytes=1,
                retention_ttl=retention_ttl,
            )

    backend = quarantine_backend(fixed_time, {})
    with pytest.raises(ValueError, match="timezone-aware"):
        backend.sweep_expired(as_of=fixed_time.replace(tzinfo=None))
    for limit in (0, 1_001):
        with pytest.raises(ValueError, match="sweep limit"):
            backend.sweep_expired(as_of=fixed_time, limit=limit)
    with pytest.raises(LookupError, match="not found"):
        backend.retention_deadline(record_id("quarantine", 999))


def test_intake_contract_rejects_duplicate_or_reordered_outcomes(fixed_time) -> None:
    first = attachment(1)
    second = attachment(2)
    with pytest.raises(ValidationError, match="references must be unique"):
        intake_request(fixed_time, (first, first))

    request = intake_request(fixed_time, (first, second))
    backend = RejectingTelegramAttachmentBackend(
        owner_id=OWNER_ID,
        clock=lambda: fixed_time,
    )
    receipts = backend.handle(request)
    with pytest.raises(ValueError, match="preserve every reference in order"):
        validate_telegram_attachment_receipts(request, tuple(reversed(receipts)))

    predating = TelegramAttachmentReceipt(
        **{
            **receipts[0].model_dump(),
            "recorded_at": fixed_time - timedelta(microseconds=1),
        }
    )
    with pytest.raises(ValueError, match="predates its update"):
        validate_telegram_attachment_receipts(request, (predating, receipts[1]))
