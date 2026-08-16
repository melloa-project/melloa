from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from melloa.adapters.fakes.telegram import (
    FakeTelegramUpdateSource,
    InMemoryTelegramPollStateStore,
)
from melloa.domain.base import sha256_digest
from melloa.domain.telegram import (
    MAX_TELEGRAM_UPDATE_BYTES,
    TelegramAttachmentDisposition,
    TelegramAttachmentIntakeRequest,
    TelegramAttachmentKind,
    TelegramAttachmentReceipt,
    TelegramAttachmentReference,
    TelegramChatType,
    TelegramInboundMessage,
    TelegramInboundUpdate,
    TelegramIngestionReceipt,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramPollRequest,
    TelegramPollState,
    TelegramUpdateDisposition,
    TelegramUpdateKind,
    telegram_update_fingerprint,
    validate_paired_telegram_update,
    validate_telegram_ingestion_receipt,
    validate_telegram_pairing_candidate,
    validate_telegram_pairing_confirmation,
)
from melloa.ports.telegram import (
    TelegramPollConflictError,
    TransientTelegramPollingError,
)
from tests.conftest import record_id

ADAPTER_ID = "client.telegram.synthetic"


def attachment(number: int) -> TelegramAttachmentReference:
    return TelegramAttachmentReference(
        kind=TelegramAttachmentKind.DOCUMENT,
        file_id=f"synthetic-file-{number}",
        file_unique_id=f"synthetic-unique-{number}",
        declared_size_bytes=128,
        media_type="text/plain",
        file_name=f"attachment-{number}.txt",
    )


def update(
    fixed_time,
    update_id: int,
    *,
    sender_user_id: int = 1001,
    chat_id: int = 1001,
    chat_type: TelegramChatType = TelegramChatType.PRIVATE,
    text: str | None = "hello",
    attachments: tuple[TelegramAttachmentReference, ...] = (),
) -> TelegramInboundUpdate:
    observed_at = fixed_time + timedelta(seconds=update_id)
    return TelegramInboundUpdate(
        update_id=update_id,
        message=TelegramInboundMessage(
            telegram_message_id=update_id + 1,
            sender_user_id=sender_user_id,
            chat_id=chat_id,
            chat_type=chat_type,
            sent_at=observed_at,
            text=text,
            attachments=attachments,
        ),
        received_at=observed_at,
        raw_size_bytes=256,
        source_payload_hash=sha256_digest(f"raw-update-{update_id}".encode()),
    )


def rejected_receipt(
    inbound: TelegramInboundUpdate,
    number: int,
    *,
    adapter_id: str = ADAPTER_ID,
) -> TelegramIngestionReceipt:
    return TelegramIngestionReceipt(
        receipt_id=record_id("tgreceipt", number),
        adapter_id=adapter_id,
        update_id=inbound.update_id,
        update_fingerprint=telegram_update_fingerprint(inbound),
        disposition=TelegramUpdateDisposition.REJECTED,
        recorded_at=inbound.received_at,
        reason_code="telegram.synthetic.rejected",
        attachment_receipts=tuple(
            TelegramAttachmentReceipt(
                file_unique_id=item.file_unique_id,
                disposition=TelegramAttachmentDisposition.REJECTED,
                recorded_at=inbound.received_at,
                reason_code="telegram.attachment.rejected",
            )
            for item in inbound.message.attachments
        ),
    )


def pairing_candidate(
    fixed_time,
    inbound: TelegramInboundUpdate,
    *,
    user_id: int | None = None,
) -> TelegramPairingCandidate:
    return TelegramPairingCandidate(
        candidate_id=record_id("tgcandidate", 1),
        owner_id=record_id("owner", 1),
        update_id=inbound.update_id,
        telegram_user_id=user_id or inbound.message.sender_user_id,
        telegram_chat_id=inbound.message.chat_id,
        confirmation_code_hash=sha256_digest(b"synthetic-one-time-code"),
        observed_at=inbound.received_at,
        expires_at=inbound.received_at + timedelta(minutes=5),
    )


def confirmed_pairing(
    candidate: TelegramPairingCandidate,
    *,
    confirmed_at=None,
    revoked_at=None,
) -> TelegramOwnerPairing:
    return TelegramOwnerPairing(
        pairing_id=record_id("tgpairing", 1),
        candidate_id=candidate.candidate_id,
        owner_id=candidate.owner_id,
        telegram_user_id=candidate.telegram_user_id,
        telegram_chat_id=candidate.telegram_chat_id,
        confirmed_by_owner_id=candidate.owner_id,
        confirmed_at=confirmed_at or candidate.observed_at + timedelta(minutes=1),
        revoked_at=revoked_at,
    )


def test_pairing_binds_one_local_owner_to_exact_private_start_and_chat(fixed_time) -> None:
    start = update(fixed_time, 1, text="/start")
    candidate = pairing_candidate(fixed_time, start)
    validate_telegram_pairing_candidate(start, candidate)

    pairing = confirmed_pairing(candidate)
    validate_telegram_pairing_confirmation(candidate, pairing)
    owner_message = update(
        fixed_time + timedelta(minutes=2),
        2,
        sender_user_id=pairing.telegram_user_id,
        chat_id=pairing.telegram_chat_id,
    )
    validate_paired_telegram_update(pairing, owner_message)

    assert candidate.confirmation_code_hash != "synthetic-one-time-code"
    assert pairing.owner_id == record_id("owner", 1)


def test_pairing_rejects_group_mismatch_expiry_old_updates_and_revocation(
    fixed_time,
) -> None:
    start = update(fixed_time, 1, text="/start")
    candidate = pairing_candidate(fixed_time, start)
    pairing = confirmed_pairing(candidate)

    group_start = update(
        fixed_time,
        2,
        chat_id=-1001,
        chat_type=TelegramChatType.GROUP,
        text="/start",
    )
    with pytest.raises(ValueError, match="private chat"):
        validate_telegram_pairing_candidate(group_start, candidate)
    with pytest.raises(ValueError, match="text-only /start"):
        validate_telegram_pairing_candidate(update(fixed_time, 3), candidate)
    with pytest.raises(ValueError, match="source update"):
        validate_telegram_pairing_candidate(
            start,
            pairing_candidate(fixed_time, start, user_id=2002),
        )

    expired = confirmed_pairing(candidate, confirmed_at=candidate.expires_at)
    with pytest.raises(ValueError, match="candidate lifetime"):
        validate_telegram_pairing_confirmation(candidate, expired)
    with pytest.raises(ValueError, match="does not match"):
        validate_telegram_pairing_confirmation(
            candidate,
            TelegramOwnerPairing(
                **{
                    **pairing.model_dump(),
                    "telegram_chat_id": 2002,
                }
            ),
        )

    with pytest.raises(ValueError, match="exact paired"):
        validate_paired_telegram_update(
            pairing,
            update(fixed_time + timedelta(minutes=2), 4, sender_user_id=2002),
        )
    with pytest.raises(ValueError, match="private chat"):
        validate_paired_telegram_update(pairing, group_start)
    with pytest.raises(ValueError, match="predates"):
        validate_paired_telegram_update(pairing, update(fixed_time, 5))
    revoked = confirmed_pairing(
        candidate,
        revoked_at=pairing.confirmed_at + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="revoked"):
        validate_paired_telegram_update(
            revoked,
            update(fixed_time + timedelta(minutes=2), 6),
        )

    with pytest.raises(ValidationError, match="exact owner"):
        TelegramOwnerPairing(
            **{
                **pairing.model_dump(),
                "confirmed_by_owner_id": record_id("owner", 2),
            }
        )
    with pytest.raises(ValidationError, match="revoked before"):
        TelegramOwnerPairing(
            **{
                **pairing.model_dump(),
                "revoked_at": pairing.confirmed_at - timedelta(seconds=1),
            }
        )
    with pytest.raises(ValidationError, match="expire after"):
        TelegramPairingCandidate(
            **{
                **candidate.model_dump(),
                "expires_at": candidate.observed_at,
            }
        )


def test_update_contract_rejects_malformed_oversized_or_ambiguous_messages(
    fixed_time,
) -> None:
    valid = update(fixed_time, 1, attachments=(attachment(1),))
    assert valid.raw_size_bytes == 256

    with pytest.raises(ValidationError, match="less than or equal"):
        TelegramInboundUpdate(
            **{
                **valid.model_dump(),
                "raw_size_bytes": MAX_TELEGRAM_UPDATE_BYTES + 1,
            }
        )
    with pytest.raises(ValidationError, match="cannot arrive before"):
        TelegramInboundUpdate(
            **{
                **valid.model_dump(),
                "received_at": valid.message.sent_at - timedelta(seconds=1),
            }
        )
    with pytest.raises(ValidationError, match="text or attachment"):
        TelegramInboundMessage(
            telegram_message_id=1,
            sender_user_id=1001,
            chat_id=1001,
            chat_type=TelegramChatType.PRIVATE,
            sent_at=fixed_time,
        )
    with pytest.raises(ValidationError, match="cannot be zero"):
        TelegramInboundMessage(
            telegram_message_id=1,
            sender_user_id=1001,
            chat_id=0,
            chat_type=TelegramChatType.PRIVATE,
            sent_at=fixed_time,
            text="hello",
        )
    with pytest.raises(ValidationError, match="must be unique"):
        TelegramInboundMessage(
            telegram_message_id=1,
            sender_user_id=1001,
            chat_id=1001,
            chat_type=TelegramChatType.PRIVATE,
            sent_at=fixed_time,
            attachments=(attachment(1), attachment(1)),
        )


def test_attachment_receipts_never_expose_unquarantined_content(fixed_time) -> None:
    rejected = TelegramAttachmentReceipt(
        file_unique_id="synthetic-unique-1",
        disposition=TelegramAttachmentDisposition.REJECTED,
        recorded_at=fixed_time,
        reason_code="telegram.attachment.unsupported",
    )
    quarantined = TelegramAttachmentReceipt(
        file_unique_id="synthetic-unique-2",
        disposition=TelegramAttachmentDisposition.QUARANTINED,
        recorded_at=fixed_time,
        quarantine_blob_id=record_id("blob", 1),
        content_hash=sha256_digest(b"synthetic quarantined bytes"),
        size_bytes=27,
        media_type="text/plain",
    )
    assert rejected.disposition is TelegramAttachmentDisposition.REJECTED
    assert quarantined.disposition is TelegramAttachmentDisposition.QUARANTINED

    with pytest.raises(ValidationError, match="only a reason"):
        TelegramAttachmentReceipt(
            **{
                **rejected.model_dump(),
                "content_hash": sha256_digest(b"not allowed"),
            }
        )
    with pytest.raises(ValidationError, match="complete blob"):
        TelegramAttachmentReceipt(
            file_unique_id="synthetic-unique-3",
            disposition=TelegramAttachmentDisposition.QUARANTINED,
            recorded_at=fixed_time,
            quarantine_blob_id=record_id("blob", 2),
        )


def test_ingestion_receipt_matches_update_and_accounts_for_all_attachments(
    fixed_time,
) -> None:
    inbound = update(
        fixed_time,
        1,
        attachments=(attachment(1), attachment(2)),
    )
    receipts = (
        TelegramAttachmentReceipt(
            file_unique_id="synthetic-unique-1",
            disposition=TelegramAttachmentDisposition.REJECTED,
            recorded_at=inbound.received_at,
            reason_code="telegram.attachment.unsupported",
        ),
        TelegramAttachmentReceipt(
            file_unique_id="synthetic-unique-2",
            disposition=TelegramAttachmentDisposition.QUARANTINED,
            recorded_at=inbound.received_at,
            quarantine_blob_id=record_id("blob", 1),
            content_hash=sha256_digest(b"synthetic quarantined bytes"),
            size_bytes=27,
            media_type="text/plain",
        ),
    )
    receipt = TelegramIngestionReceipt(
        receipt_id=record_id("tgreceipt", 1),
        adapter_id=ADAPTER_ID,
        update_id=inbound.update_id,
        update_fingerprint=telegram_update_fingerprint(inbound),
        disposition=TelegramUpdateDisposition.INGESTED,
        recorded_at=inbound.received_at,
        canonical_message_id=record_id("message", 1),
        attachment_receipts=receipts,
    )
    validate_telegram_ingestion_receipt(inbound, receipt)

    with pytest.raises(ValueError, match="every attachment"):
        validate_telegram_ingestion_receipt(
            inbound,
            TelegramIngestionReceipt(
                **{
                    **receipt.model_dump(),
                    "attachment_receipts": receipts[:1],
                }
            ),
        )
    with pytest.raises(ValueError, match="in order"):
        validate_telegram_ingestion_receipt(
            inbound,
            TelegramIngestionReceipt(
                **{
                    **receipt.model_dump(),
                    "attachment_receipts": tuple(reversed(receipts)),
                }
            ),
        )
    with pytest.raises(ValueError, match="does not match"):
        validate_telegram_ingestion_receipt(
            inbound,
            TelegramIngestionReceipt(
                **{
                    **receipt.model_dump(),
                    "update_fingerprint": sha256_digest(b"wrong"),
                }
            ),
        )
    with pytest.raises(ValueError, match="predates its update"):
        validate_telegram_ingestion_receipt(
            inbound,
            TelegramIngestionReceipt(
                **{
                    **receipt.model_dump(),
                    "recorded_at": inbound.received_at - timedelta(seconds=1),
                }
            ),
        )
    invalid_chronology = TelegramAttachmentReceipt(
        **{
            **receipts[0].model_dump(),
            "recorded_at": inbound.received_at - timedelta(seconds=1),
        }
    )
    with pytest.raises(ValueError, match="chronology"):
        validate_telegram_ingestion_receipt(
            inbound,
            TelegramIngestionReceipt(
                **{
                    **receipt.model_dump(),
                    "attachment_receipts": (invalid_chronology, receipts[1]),
                }
            ),
        )
    with pytest.raises(ValidationError, match="canonical message"):
        TelegramIngestionReceipt(
            **{
                **receipt.model_dump(),
                "canonical_message_id": None,
            }
        )
    with pytest.raises(ValidationError, match="must be unique"):
        TelegramIngestionReceipt(
            **{
                **receipt.model_dump(),
                "attachment_receipts": (receipts[0], receipts[0]),
            }
        )

    rejected = rejected_receipt(inbound, 2)
    validate_telegram_ingestion_receipt(inbound, rejected)
    with pytest.raises(ValueError, match="cannot fetch attachments"):
        validate_telegram_ingestion_receipt(
            inbound,
            TelegramIngestionReceipt(
                **{
                    **rejected.model_dump(),
                    "attachment_receipts": receipts,
                }
            ),
        )


def test_pairing_and_attachment_only_outcomes_fail_closed(fixed_time) -> None:
    start = update(fixed_time, 1, text="/start")
    candidate_receipt = TelegramIngestionReceipt(
        receipt_id=record_id("tgreceipt", 1),
        adapter_id=ADAPTER_ID,
        update_id=start.update_id,
        update_fingerprint=telegram_update_fingerprint(start),
        disposition=TelegramUpdateDisposition.PAIRING_CANDIDATE,
        recorded_at=start.received_at,
        pairing_candidate_id=record_id("tgcandidate", 1),
    )
    validate_telegram_ingestion_receipt(start, candidate_receipt)
    ordinary = update(fixed_time, 1)
    with pytest.raises(ValueError, match="text-only /start"):
        validate_telegram_ingestion_receipt(
            ordinary,
            TelegramIngestionReceipt(
                **{
                    **candidate_receipt.model_dump(),
                    "update_fingerprint": telegram_update_fingerprint(ordinary),
                }
            ),
        )

    attachment_only = update(
        fixed_time,
        2,
        text=None,
        attachments=(attachment(1),),
    )
    rejected_attachment = TelegramAttachmentReceipt(
        file_unique_id="synthetic-unique-1",
        disposition=TelegramAttachmentDisposition.REJECTED,
        recorded_at=attachment_only.received_at,
        reason_code="telegram.attachment.unsupported",
    )
    unusable = TelegramIngestionReceipt(
        receipt_id=record_id("tgreceipt", 2),
        adapter_id=ADAPTER_ID,
        update_id=attachment_only.update_id,
        update_fingerprint=telegram_update_fingerprint(attachment_only),
        disposition=TelegramUpdateDisposition.INGESTED,
        recorded_at=attachment_only.received_at,
        canonical_message_id=record_id("message", 1),
        attachment_receipts=(rejected_attachment,),
    )
    with pytest.raises(ValueError, match="usable quarantined"):
        validate_telegram_ingestion_receipt(attachment_only, unusable)


def test_poll_request_requires_positive_long_poll_and_message_only() -> None:
    request = TelegramPollRequest(
        adapter_id=ADAPTER_ID,
        offset=0,
        timeout_seconds=30,
        limit=10,
    )
    assert request.allowed_updates == (TelegramUpdateKind.MESSAGE,)
    with pytest.raises(ValidationError, match="greater than or equal"):
        TelegramPollRequest(
            adapter_id=ADAPTER_ID,
            offset=0,
            timeout_seconds=0,
        )
    with pytest.raises(ValidationError, match="at most 1 item"):
        TelegramPollRequest(
            adapter_id=ADAPTER_ID,
            offset=0,
            timeout_seconds=30,
            allowed_updates=(TelegramUpdateKind.MESSAGE, TelegramUpdateKind.MESSAGE),
        )


def test_fake_source_is_ordered_replayable_and_survives_outage(fixed_time) -> None:
    update_five = update(fixed_time, 5)
    update_seven = update(fixed_time, 7)
    source = FakeTelegramUpdateSource(
        (update_seven, update_five),
        failure_codes=("telegram.synthetic.unavailable",),
    )
    request = TelegramPollRequest(
        adapter_id=ADAPTER_ID,
        offset=0,
        timeout_seconds=30,
        limit=1,
    )
    assert source.health()["status"] == "degraded"
    with pytest.raises(TransientTelegramPollingError) as failure:
        source.poll(request)
    assert failure.value.reason_code == "telegram.synthetic.unavailable"
    assert failure.value.retryable is True
    assert source.poll(request) == (update_five,)
    assert source.poll(request) == (update_five,)
    assert source.health()["network"] is False

    after_five = TelegramPollRequest(
        adapter_id=ADAPTER_ID,
        offset=6,
        timeout_seconds=30,
    )
    assert source.poll(after_five) == (update_seven,)
    source.add_update(update_five)
    with pytest.raises(TelegramPollConflictError, match="different content"):
        source.add_update(update(fixed_time, 5, text="changed"))
    with pytest.raises(TelegramPollConflictError, match="identity mismatch"):
        source.poll(
            TelegramPollRequest(
                adapter_id="client.telegram.other",
                offset=0,
                timeout_seconds=30,
            )
        )


def test_poll_state_advances_only_after_receipt_and_rejects_conflicts(fixed_time) -> None:
    clock_values = iter((fixed_time,))
    store = InMemoryTelegramPollStateStore(clock=lambda: next(clock_values))
    initial = store.read_state(ADAPTER_ID)
    assert initial.next_offset == 0
    assert initial.revision == 0
    assert store.get_receipt(ADAPTER_ID, 5) is None
    assert store.get_update(ADAPTER_ID, 5) is None

    update_five = update(fixed_time, 5)
    receipt_five = rejected_receipt(update_five, 1)
    advanced = store.commit_ingestion(update_five, receipt_five, expected_revision=0)
    assert advanced.next_offset == 6
    assert advanced.revision == 1
    assert store.get_receipt(ADAPTER_ID, 5) == receipt_five
    assert store.get_update(ADAPTER_ID, 5) == update_five
    assert (
        store.commit_ingestion(update_five, receipt_five, expected_revision=0)
        == advanced
    )

    update_seven = update(fixed_time, 7)
    receipt_seven = rejected_receipt(update_seven, 2)
    final = store.commit_ingestion(update_seven, receipt_seven, expected_revision=1)
    assert final.next_offset == 8
    assert final.revision == 2

    with pytest.raises(TelegramPollConflictError, match="revision is stale"):
        update_nine = update(fixed_time, 9)
        store.commit_ingestion(
            update_nine,
            rejected_receipt(update_nine, 3),
            expected_revision=1,
        )
    with pytest.raises(TelegramPollConflictError, match="cannot move backwards"):
        update_six = update(fixed_time, 6)
        store.commit_ingestion(
            update_six,
            rejected_receipt(update_six, 4),
            expected_revision=2,
        )
    conflicting = TelegramIngestionReceipt(
        **{
            **receipt_five.model_dump(),
            "receipt_id": record_id("tgreceipt", 5),
        }
    )
    with pytest.raises(TelegramPollConflictError, match="immutable ingestion data"):
        store.commit_ingestion(update_five, conflicting, expected_revision=2)
    with pytest.raises(TelegramPollConflictError, match="immutable ingestion data"):
        store.commit_ingestion(
            update(fixed_time, 5, text="changed"),
            receipt_five,
            expected_revision=2,
        )
    with pytest.raises(TelegramPollConflictError, match="not configured"):
        store.read_state("client.telegram.other")
    with pytest.raises(TelegramPollConflictError, match="not configured"):
        store.get_receipt("client.telegram.other", 5)
    with pytest.raises(TelegramPollConflictError, match="not configured"):
        store.get_update("client.telegram.other", 5)
    with pytest.raises(TelegramPollConflictError, match="not configured"):
        update_ten = update(fixed_time, 10)
        store.commit_ingestion(
            update_ten,
            rejected_receipt(update_ten, 6, adapter_id="client.telegram.other"),
            expected_revision=2,
        )


def test_poll_state_contract_rejects_false_initial_or_advanced_history(fixed_time) -> None:
    with pytest.raises(ValidationError, match="cannot claim processed"):
        TelegramPollState(
            adapter_id=ADAPTER_ID,
            next_offset=1,
            updated_at=fixed_time,
        )

    future_store = InMemoryTelegramPollStateStore(
        clock=lambda: fixed_time + timedelta(minutes=1)
    )
    inbound = update(fixed_time, 1)
    with pytest.raises(TelegramPollConflictError, match="predates poll state"):
        future_store.commit_ingestion(
            inbound,
            rejected_receipt(inbound, 1),
            expected_revision=0,
        )


def test_generated_telegram_schemas_validate_serialized_contracts(fixed_time) -> None:
    inbound = update(fixed_time, 1, text="/start")
    candidate = pairing_candidate(fixed_time, inbound)
    pairing = confirmed_pairing(candidate)
    attachment_receipt = TelegramAttachmentReceipt(
        file_unique_id="synthetic-unique-1",
        disposition=TelegramAttachmentDisposition.REJECTED,
        recorded_at=inbound.received_at,
        reason_code="telegram.attachment.unsupported",
    )
    attachment_request = TelegramAttachmentIntakeRequest(
        adapter_id=ADAPTER_ID,
        update_id=inbound.update_id,
        update_fingerprint=telegram_update_fingerprint(inbound),
        received_at=inbound.received_at,
        attachments=(attachment(1),),
    )
    ingestion_receipt = TelegramIngestionReceipt(
        receipt_id=record_id("tgreceipt", 1),
        adapter_id=ADAPTER_ID,
        update_id=inbound.update_id,
        update_fingerprint=telegram_update_fingerprint(inbound),
        disposition=TelegramUpdateDisposition.PAIRING_CANDIDATE,
        recorded_at=inbound.received_at,
        pairing_candidate_id=candidate.candidate_id,
    )
    poll_request = TelegramPollRequest(
        adapter_id=ADAPTER_ID,
        offset=0,
        timeout_seconds=30,
    )
    poll_state = TelegramPollState(adapter_id=ADAPTER_ID, updated_at=fixed_time)
    contracts = {
        "attachment-intake-request-v1.json": attachment_request,
        "attachment-receipt-v1.json": attachment_receipt,
        "inbound-update-v1.json": inbound,
        "ingestion-receipt-v1.json": ingestion_receipt,
        "owner-pairing-v1.json": pairing,
        "pairing-candidate-v1.json": candidate,
        "poll-request-v1.json": poll_request,
        "poll-state-v1.json": poll_state,
    }
    schema_root = Path(__file__).resolve().parents[2] / "schemas" / "telegram"
    for file_name, contract in contracts.items():
        schema = json.loads((schema_root / file_name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(contract.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="requires its last receipt"):
        TelegramPollState(
            adapter_id=ADAPTER_ID,
            next_offset=2,
            revision=1,
            updated_at=fixed_time,
        )
    with pytest.raises(ValidationError, match="must follow"):
        TelegramPollState(
            adapter_id=ADAPTER_ID,
            next_offset=3,
            revision=1,
            last_update_id=1,
            last_receipt_id=record_id("tgreceipt", 1),
            updated_at=fixed_time,
        )
