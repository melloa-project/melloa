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

ADAPTER_ID = "client.telegram.synthetic"


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
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=1_024,
        max_quarantine_bytes=2_048,
        clock=lambda: fixed_time + timedelta(seconds=1),
    )


def test_rejecting_backend_never_fetches_and_returns_exact_replay(fixed_time) -> None:
    backend = RejectingTelegramAttachmentBackend(
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
            allowed_kinds=frozenset(),
            allowed_media_types=frozenset(),
            max_attachment_bytes=5,
            max_quarantine_bytes=4,
        )


def test_intake_contract_rejects_duplicate_or_reordered_outcomes(fixed_time) -> None:
    first = attachment(1)
    second = attachment(2)
    with pytest.raises(ValidationError, match="references must be unique"):
        intake_request(fixed_time, (first, first))

    request = intake_request(fixed_time, (first, second))
    backend = RejectingTelegramAttachmentBackend(clock=lambda: fixed_time)
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
