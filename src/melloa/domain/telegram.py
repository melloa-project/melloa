"""Strict contracts for the optional secondary Telegram adapter."""

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
    canonical_json_bytes,
    sha256_digest,
)

MAX_TELEGRAM_INTEGER = (1 << 52) - 1
MAX_TELEGRAM_UPDATE_BYTES = 262_144

TelegramUpdateId = Annotated[int, Field(ge=0, le=MAX_TELEGRAM_INTEGER)]
TelegramOffset = Annotated[int, Field(ge=0, le=MAX_TELEGRAM_INTEGER + 1)]
TelegramUserId = Annotated[int, Field(ge=1, le=MAX_TELEGRAM_INTEGER)]
TelegramChatId = Annotated[
    int,
    Field(ge=-MAX_TELEGRAM_INTEGER, le=MAX_TELEGRAM_INTEGER),
]
TelegramMessageId = Annotated[int, Field(ge=1, le=MAX_TELEGRAM_INTEGER)]


class TelegramChatType(StrEnum):
    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class TelegramUpdateKind(StrEnum):
    MESSAGE = "message"


class TelegramAttachmentKind(StrEnum):
    PHOTO = "photo"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    VIDEO = "video"
    ANIMATION = "animation"
    STICKER = "sticker"


class TelegramAttachmentDisposition(StrEnum):
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class TelegramUpdateDisposition(StrEnum):
    INGESTED = "ingested"
    REJECTED = "rejected"
    PAIRING_CANDIDATE = "pairing_candidate"


class TelegramAttachmentReference(ContractModel):
    kind: TelegramAttachmentKind
    file_id: str = Field(min_length=1, max_length=512)
    file_unique_id: str = Field(min_length=1, max_length=512)
    declared_size_bytes: Annotated[int, Field(ge=0)] | None = None
    media_type: str | None = Field(default=None, min_length=1, max_length=255)
    file_name: str | None = Field(default=None, min_length=1, max_length=512)


class TelegramInboundMessage(ContractModel):
    telegram_message_id: TelegramMessageId
    sender_user_id: TelegramUserId
    chat_id: TelegramChatId
    chat_type: TelegramChatType
    sent_at: AwareDatetime
    text: str | None = Field(default=None, min_length=1, max_length=4096)
    attachments: tuple[TelegramAttachmentReference, ...] = Field(
        default=(),
        max_length=16,
    )

    @model_validator(mode="after")
    def validate_message(self) -> TelegramInboundMessage:
        if self.chat_id == 0:
            raise ValueError("Telegram chat ID cannot be zero")
        if self.text is None and not self.attachments:
            raise ValueError("Telegram messages require text or attachment metadata")
        unique_ids = tuple(item.file_unique_id for item in self.attachments)
        if len(set(unique_ids)) != len(unique_ids):
            raise ValueError("Telegram attachment references must be unique")
        return self


class TelegramInboundUpdate(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    update_id: TelegramUpdateId
    kind: Literal[TelegramUpdateKind.MESSAGE] = TelegramUpdateKind.MESSAGE
    message: TelegramInboundMessage
    received_at: AwareDatetime
    raw_size_bytes: Annotated[
        int,
        Field(ge=1, le=MAX_TELEGRAM_UPDATE_BYTES),
    ]
    source_payload_hash: Sha256Digest

    @model_validator(mode="after")
    def validate_update(self) -> TelegramInboundUpdate:
        if self.received_at < self.message.sent_at:
            raise ValueError("Telegram update cannot arrive before its message was sent")
        return self


def telegram_update_fingerprint(update: TelegramInboundUpdate) -> Sha256Digest:
    """Hash the complete normalized update for replay/conflict checks."""

    return sha256_digest(canonical_json_bytes(update))


class TelegramPairingCandidate(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    candidate_id: RecordId
    owner_id: RecordId
    update_id: TelegramUpdateId
    telegram_user_id: TelegramUserId
    telegram_chat_id: TelegramUserId
    confirmation_code_hash: Sha256Digest
    observed_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_candidate(self) -> TelegramPairingCandidate:
        if self.expires_at <= self.observed_at:
            raise ValueError("Telegram pairing candidate must expire after observation")
        return self


class TelegramOwnerPairing(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    pairing_id: RecordId
    candidate_id: RecordId
    owner_id: RecordId
    telegram_user_id: TelegramUserId
    telegram_chat_id: TelegramUserId
    confirmed_by_owner_id: RecordId
    confirmed_at: AwareDatetime
    revoked_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_pairing(self) -> TelegramOwnerPairing:
        if self.confirmed_by_owner_id != self.owner_id:
            raise ValueError("Telegram pairing requires confirmation by the exact owner")
        if self.revoked_at is not None and self.revoked_at < self.confirmed_at:
            raise ValueError("Telegram pairing cannot be revoked before confirmation")
        return self


def validate_telegram_pairing_candidate(
    update: TelegramInboundUpdate,
    candidate: TelegramPairingCandidate,
) -> None:
    """Verify a candidate came from one exact private ``/start`` update."""

    if update.message.chat_type is not TelegramChatType.PRIVATE:
        raise ValueError("Telegram pairing candidates require a private chat")
    if update.message.text != "/start" or update.message.attachments:
        raise ValueError("Telegram pairing candidates require a text-only /start message")
    if (
        candidate.update_id != update.update_id
        or candidate.telegram_user_id != update.message.sender_user_id
        or candidate.telegram_chat_id != update.message.chat_id
        or candidate.observed_at != update.received_at
    ):
        raise ValueError("Telegram pairing candidate does not match its source update")


def validate_telegram_pairing_confirmation(
    candidate: TelegramPairingCandidate,
    pairing: TelegramOwnerPairing,
) -> None:
    """Bind a local owner confirmation to the exact untrusted candidate."""

    if (
        pairing.candidate_id != candidate.candidate_id
        or pairing.owner_id != candidate.owner_id
        or pairing.telegram_user_id != candidate.telegram_user_id
        or pairing.telegram_chat_id != candidate.telegram_chat_id
    ):
        raise ValueError("Telegram pairing does not match its candidate")
    if not candidate.observed_at <= pairing.confirmed_at < candidate.expires_at:
        raise ValueError("Telegram pairing confirmation is outside the candidate lifetime")


def validate_paired_telegram_update(
    pairing: TelegramOwnerPairing,
    update: TelegramInboundUpdate,
) -> None:
    """Require one active exact owner user/private-chat pair before ingestion."""

    if pairing.revoked_at is not None:
        raise ValueError("Telegram pairing is revoked")
    message = update.message
    if message.chat_type is not TelegramChatType.PRIVATE:
        raise ValueError("Telegram owner updates require a private chat")
    if (
        message.sender_user_id != pairing.telegram_user_id
        or message.chat_id != pairing.telegram_chat_id
    ):
        raise ValueError("Telegram update does not match the exact paired owner and chat")
    if message.sent_at < pairing.confirmed_at:
        raise ValueError("Telegram update predates the owner pairing")


class TelegramAttachmentReceipt(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    file_unique_id: str = Field(min_length=1, max_length=512)
    disposition: TelegramAttachmentDisposition
    recorded_at: AwareDatetime
    reason_code: QualifiedName | None = None
    quarantine_blob_id: RecordId | None = None
    content_hash: Sha256Digest | None = None
    size_bytes: Annotated[int, Field(ge=0)] | None = None
    media_type: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_receipt(self) -> TelegramAttachmentReceipt:
        quarantine_fields = (
            self.quarantine_blob_id,
            self.content_hash,
            self.size_bytes,
            self.media_type,
        )
        if self.disposition is TelegramAttachmentDisposition.REJECTED:
            if self.reason_code is None or any(value is not None for value in quarantine_fields):
                raise ValueError("rejected Telegram attachments require only a reason code")
        elif self.reason_code is not None or any(value is None for value in quarantine_fields):
            raise ValueError("quarantined Telegram attachments require complete blob metadata")
        return self


class TelegramIngestionReceipt(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    receipt_id: RecordId
    adapter_id: QualifiedName
    update_id: TelegramUpdateId
    update_fingerprint: Sha256Digest
    disposition: TelegramUpdateDisposition
    recorded_at: AwareDatetime
    canonical_message_id: RecordId | None = None
    pairing_candidate_id: RecordId | None = None
    reason_code: QualifiedName | None = None
    attachment_receipts: tuple[TelegramAttachmentReceipt, ...] = ()

    @model_validator(mode="after")
    def validate_receipt(self) -> TelegramIngestionReceipt:
        if self.disposition is TelegramUpdateDisposition.INGESTED:
            if (
                self.canonical_message_id is None
                or self.pairing_candidate_id is not None
                or self.reason_code is not None
            ):
                raise ValueError("ingested Telegram updates require only a canonical message")
        elif self.disposition is TelegramUpdateDisposition.PAIRING_CANDIDATE:
            if (
                self.pairing_candidate_id is None
                or self.canonical_message_id is not None
                or self.reason_code is not None
            ):
                raise ValueError("pairing updates require only a pairing candidate")
        elif (
            self.reason_code is None
            or self.canonical_message_id is not None
            or self.pairing_candidate_id is not None
        ):
            raise ValueError("rejected Telegram updates require only a reason code")
        attachment_ids = tuple(item.file_unique_id for item in self.attachment_receipts)
        if len(set(attachment_ids)) != len(attachment_ids):
            raise ValueError("Telegram attachment receipts must be unique")
        return self


def validate_telegram_ingestion_receipt(
    update: TelegramInboundUpdate,
    receipt: TelegramIngestionReceipt,
) -> None:
    """Verify one durable outcome accounts for the complete normalized update."""

    if (
        receipt.update_id != update.update_id
        or receipt.update_fingerprint != telegram_update_fingerprint(update)
    ):
        raise ValueError("Telegram ingestion receipt does not match its update")
    if receipt.recorded_at < update.received_at:
        raise ValueError("Telegram ingestion receipt predates its update")
    if any(
        not update.received_at <= item.recorded_at <= receipt.recorded_at
        for item in receipt.attachment_receipts
    ):
        raise ValueError("Telegram attachment receipt chronology is invalid")
    referenced = {item.file_unique_id for item in update.message.attachments}
    recorded = {item.file_unique_id for item in receipt.attachment_receipts}
    if referenced != recorded:
        raise ValueError("Telegram ingestion must account for every attachment reference")
    if receipt.disposition is TelegramUpdateDisposition.REJECTED and any(
        item.disposition is TelegramAttachmentDisposition.QUARANTINED
        for item in receipt.attachment_receipts
    ):
        raise ValueError("rejected Telegram updates cannot fetch attachments")
    if receipt.disposition is TelegramUpdateDisposition.PAIRING_CANDIDATE:
        if update.message.text != "/start" or update.message.attachments:
            raise ValueError("Telegram pairing receipts require a text-only /start update")
    if receipt.disposition is TelegramUpdateDisposition.INGESTED:
        has_quarantined_attachment = any(
            item.disposition is TelegramAttachmentDisposition.QUARANTINED
            for item in receipt.attachment_receipts
        )
        if update.message.text is None and not has_quarantined_attachment:
            raise ValueError("ingested Telegram updates require usable quarantined content")


class TelegramPollRequest(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    adapter_id: QualifiedName
    offset: TelegramOffset
    timeout_seconds: Annotated[int, Field(ge=1, le=50)]
    limit: Annotated[int, Field(ge=1, le=100)] = 100
    allowed_updates: tuple[TelegramUpdateKind, ...] = Field(
        default=(TelegramUpdateKind.MESSAGE,),
        min_length=1,
        max_length=1,
    )

    @model_validator(mode="after")
    def validate_request(self) -> TelegramPollRequest:
        if self.allowed_updates != (TelegramUpdateKind.MESSAGE,):
            raise ValueError("Telegram V1 polling accepts only message updates")
        return self


class TelegramPollState(ContractModel):
    contract_version: Literal["1.0.0"] = "1.0.0"
    adapter_id: QualifiedName
    next_offset: TelegramOffset = 0
    revision: Annotated[int, Field(ge=0)] = 0
    last_update_id: TelegramUpdateId | None = None
    last_receipt_id: RecordId | None = None
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_state(self) -> TelegramPollState:
        if self.revision == 0:
            if (
                self.next_offset != 0
                or self.last_update_id is not None
                or self.last_receipt_id is not None
            ):
                raise ValueError("initial Telegram poll state cannot claim processed updates")
        elif self.last_update_id is None or self.last_receipt_id is None:
            raise ValueError("advanced Telegram poll state requires its last receipt")
        elif self.next_offset != self.last_update_id + 1:
            raise ValueError("Telegram offset must follow the last durably handled update")
        return self
