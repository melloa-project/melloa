"""Deterministic Telegram source and poll state with no network or credentials."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import RLock

from melloa.domain.base import (
    JsonObject,
    QualifiedName,
    RecordId,
    new_record_id,
    sha256_digest,
    utc_now,
)
from melloa.domain.retention import RetentionDeletionReceipt
from melloa.domain.telegram import (
    TelegramAttachmentDisposition,
    TelegramAttachmentIntakeRequest,
    TelegramAttachmentKind,
    TelegramAttachmentReceipt,
    TelegramAttachmentReference,
    TelegramInboundUpdate,
    TelegramIngestionReceipt,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramPollRequest,
    TelegramPollState,
    TelegramUpdateId,
    validate_telegram_attachment_receipts,
    validate_telegram_ingestion_receipt,
    validate_telegram_pairing_confirmation,
)
from melloa.ports.telegram import (
    TelegramAttachmentConflictError,
    TelegramPairingChallenge,
    TelegramPairingConflictError,
    TelegramPairingNotFoundError,
    TelegramPollConflictError,
    TransientTelegramAttachmentError,
    TransientTelegramPollingError,
)


class DeterministicTelegramPairingCodeIssuer:
    """Derive replay-stable synthetic codes without credentials or stored plaintext."""

    def __init__(self, namespace: str = "melloa-synthetic-telegram-pairing") -> None:
        self._namespace = namespace.encode()

    def issue(self, candidate_id: str) -> str:
        digest = hashlib.sha256(self._namespace + b":" + candidate_id.encode()).digest()
        return base64.urlsafe_b64encode(digest[:18]).rstrip(b"=").decode()


class FakeTelegramPairingChallengePublisher:
    """Record exact private-chat challenges with idempotent synthetic delivery."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._by_candidate: dict[str, TelegramPairingChallenge] = {}
        self.published: list[TelegramPairingChallenge] = []

    def publish(self, challenge: TelegramPairingChallenge) -> None:
        with self._lock:
            candidate_id = challenge.candidate.candidate_id
            existing = self._by_candidate.get(candidate_id)
            if existing is not None:
                if existing != challenge:
                    raise TelegramPairingConflictError(
                        "Telegram pairing challenge changed across replay"
                    )
                return
            self._by_candidate[candidate_id] = challenge
            self.published.append(challenge)

    def challenge_for(self, candidate_id: str) -> TelegramPairingChallenge:
        with self._lock:
            try:
                return self._by_candidate[candidate_id]
            except KeyError as error:
                raise TelegramPairingNotFoundError(
                    "Telegram pairing challenge not found"
                ) from error


class RejectingTelegramAttachmentBackend:
    """Reject every reference from metadata without fetching attachment bytes."""

    def __init__(
        self,
        *,
        owner_id: RecordId,
        reason_code: QualifiedName = "telegram.attachment.unsupported",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._owner_id = owner_id
        self._reason_code = reason_code
        self._clock = clock
        self._lock = RLock()
        self._requests_by_update: dict[
            tuple[QualifiedName, int], TelegramAttachmentIntakeRequest
        ] = {}
        self._receipts_by_update: dict[
            tuple[QualifiedName, int], tuple[TelegramAttachmentReceipt, ...]
        ] = {}
        self.requests: list[TelegramAttachmentIntakeRequest] = []

    @property
    def owner_id(self) -> RecordId:
        return self._owner_id

    def handle(
        self,
        request: TelegramAttachmentIntakeRequest,
    ) -> tuple[TelegramAttachmentReceipt, ...]:
        with self._lock:
            key = (request.adapter_id, request.update_id)
            self.requests.append(request)
            existing_request = self._requests_by_update.get(key)
            if existing_request is not None and existing_request != request:
                raise TelegramAttachmentConflictError(
                    "Telegram attachment request changed across replay"
                )
            self._requests_by_update[key] = request
            existing = self._receipts_by_update.get(key)
            if existing is not None:
                return existing
            recorded_at = max(request.received_at, self._clock())
            receipts = tuple(
                TelegramAttachmentReceipt(
                    file_unique_id=attachment.file_unique_id,
                    disposition=TelegramAttachmentDisposition.REJECTED,
                    recorded_at=recorded_at,
                    reason_code=self._reason_code,
                )
                for attachment in request.attachments
            )
            validate_telegram_attachment_receipts(request, receipts)
            self._receipts_by_update[key] = receipts
            return receipts


@dataclass(frozen=True)
class SyntheticTelegramAttachmentPayload:
    content: bytes = field(repr=False)
    media_type: str

    def __post_init__(self) -> None:
        if not self.media_type.strip():
            raise ValueError("synthetic Telegram attachment media type cannot be empty")


@dataclass(frozen=True)
class _QuarantinedTelegramBlob:
    owner_id: RecordId
    content: bytes = field(repr=False)
    content_hash: str
    retained_at: datetime
    expires_at: datetime
    retention_policy: QualifiedName


class InMemoryTelegramAttachmentQuarantine:
    """Apply fail-closed metadata policy and content-address synthetic bytes."""

    def __init__(
        self,
        payloads: Mapping[str, SyntheticTelegramAttachmentPayload],
        *,
        owner_id: RecordId,
        allowed_kinds: frozenset[TelegramAttachmentKind],
        allowed_media_types: frozenset[str],
        max_attachment_bytes: int,
        max_quarantine_bytes: int,
        retention_ttl: timedelta = timedelta(days=1),
        retention_policy: QualifiedName = "retention.telegram-quarantine",
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
    ) -> None:
        if max_attachment_bytes < 1:
            raise ValueError("Telegram attachment size limit must be positive")
        if max_quarantine_bytes < max_attachment_bytes:
            raise ValueError("Telegram quarantine quota must cover one attachment")
        if not timedelta(hours=1) <= retention_ttl <= timedelta(days=7):
            raise ValueError(
                "Telegram quarantine retention must be between one hour and seven days"
            )
        self._owner_id = owner_id
        self._payloads = dict(payloads)
        self._allowed_kinds = allowed_kinds
        self._allowed_media_types = frozenset(
            self._normalize_media_type(item) for item in allowed_media_types
        )
        self._max_attachment_bytes = max_attachment_bytes
        self._max_quarantine_bytes = max_quarantine_bytes
        self._retention_ttl = retention_ttl
        self._retention_policy = retention_policy
        self._clock = clock
        self._id_factory = id_factory
        self._lock = RLock()
        self._requests_by_update: dict[
            tuple[QualifiedName, int], TelegramAttachmentIntakeRequest
        ] = {}
        self._receipts_by_update: dict[
            tuple[QualifiedName, int], tuple[TelegramAttachmentReceipt, ...]
        ] = {}
        self._blobs: dict[str, _QuarantinedTelegramBlob] = {}
        self._deletion_receipts: list[RetentionDeletionReceipt] = []
        self._deletion_receipts_by_id: dict[str, RetentionDeletionReceipt] = {}
        self.requests: list[TelegramAttachmentIntakeRequest] = []
        self.fetched_file_unique_ids: list[str] = []

    @property
    def owner_id(self) -> RecordId:
        return self._owner_id

    @property
    def stored_blob_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._blobs))

    @property
    def deletion_receipts(self) -> tuple[RetentionDeletionReceipt, ...]:
        with self._lock:
            return tuple(self._deletion_receipts)

    def has_blob(self, blob_id: str) -> bool:
        with self._lock:
            return blob_id in self._blobs

    def retention_deadline(self, blob_id: str) -> datetime:
        with self._lock:
            try:
                return self._blobs[blob_id].expires_at
            except KeyError as error:
                raise LookupError("Telegram quarantine blob not found") from error

    def sweep_expired(
        self,
        *,
        as_of: datetime,
        limit: int = 100,
    ) -> tuple[RetentionDeletionReceipt, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("Telegram quarantine sweep time must be timezone-aware")
        if not 1 <= limit <= 1_000:
            raise ValueError("Telegram quarantine sweep limit must be between 1 and 1000")
        with self._lock:
            due = tuple(
                sorted(
                    (
                        (blob_id, blob)
                        for blob_id, blob in self._blobs.items()
                        if blob.expires_at <= as_of
                    ),
                    key=lambda item: (item[1].expires_at, item[0]),
                )
            )[:limit]
            planned: list[tuple[str, RetentionDeletionReceipt]] = []
            planned_ids: set[str] = set()
            for blob_id, blob in due:
                receipt = RetentionDeletionReceipt(
                    receipt_id=self._id_factory("deletion"),
                    owner_id=blob.owner_id,
                    object_id=blob_id,
                    object_type="object.telegram-quarantine-blob",
                    content_hash=blob.content_hash,
                    size_bytes=len(blob.content),
                    retention_policy=blob.retention_policy,
                    retained_at=blob.retained_at,
                    expires_at=blob.expires_at,
                    deleted_at=as_of,
                    reason_code="retention.expired",
                )
                if (
                    receipt.receipt_id in self._deletion_receipts_by_id
                    or receipt.receipt_id in planned_ids
                ):
                    raise TelegramAttachmentConflictError(
                        "Telegram quarantine deletion receipt identity conflicts"
                    )
                planned_ids.add(receipt.receipt_id)
                planned.append((blob_id, receipt))
            for blob_id, receipt in planned:
                self._deletion_receipts_by_id[receipt.receipt_id] = receipt
                self._deletion_receipts.append(receipt)
                del self._blobs[blob_id]
            return tuple(receipt for _blob_id, receipt in planned)

    def handle(
        self,
        request: TelegramAttachmentIntakeRequest,
    ) -> tuple[TelegramAttachmentReceipt, ...]:
        with self._lock:
            key = (request.adapter_id, request.update_id)
            self.requests.append(request)
            existing_request = self._requests_by_update.get(key)
            if existing_request is not None and existing_request != request:
                raise TelegramAttachmentConflictError(
                    "Telegram attachment request changed across replay"
                )
            self._requests_by_update[key] = request
            existing = self._receipts_by_update.get(key)
            if existing is not None:
                return existing
            recorded_at = max(request.received_at, self._clock())
            receipts = tuple(
                self._handle_reference(attachment, recorded_at)
                for attachment in request.attachments
            )
            validate_telegram_attachment_receipts(request, receipts)
            self._receipts_by_update[key] = receipts
            return receipts

    def _handle_reference(
        self,
        attachment: TelegramAttachmentReference,
        recorded_at: datetime,
    ) -> TelegramAttachmentReceipt:
        if attachment.kind not in self._allowed_kinds:
            return self._rejected(attachment, recorded_at, "telegram.attachment.kind_denied")
        if attachment.declared_size_bytes is None:
            return self._rejected(attachment, recorded_at, "telegram.attachment.size_unknown")
        if attachment.declared_size_bytes > self._max_attachment_bytes:
            return self._rejected(
                attachment,
                recorded_at,
                "telegram.attachment.declared_size_exceeded",
            )
        if attachment.media_type is None:
            return self._rejected(
                attachment,
                recorded_at,
                "telegram.attachment.media_type_unknown",
            )
        declared_media_type = self._normalize_media_type(attachment.media_type)
        if declared_media_type not in self._allowed_media_types:
            return self._rejected(
                attachment,
                recorded_at,
                "telegram.attachment.media_type_denied",
            )

        self.fetched_file_unique_ids.append(attachment.file_unique_id)
        try:
            payload = self._payloads[attachment.file_unique_id]
        except KeyError as error:
            raise TransientTelegramAttachmentError(
                "telegram.attachment.fetch_unavailable"
            ) from error
        size_bytes = len(payload.content)
        if size_bytes > self._max_attachment_bytes:
            return self._rejected(
                attachment,
                recorded_at,
                "telegram.attachment.actual_size_exceeded",
            )
        if size_bytes != attachment.declared_size_bytes:
            return self._rejected(
                attachment,
                recorded_at,
                "telegram.attachment.size_mismatch",
            )
        media_type = self._normalize_media_type(payload.media_type)
        if media_type not in self._allowed_media_types:
            return self._rejected(
                attachment,
                recorded_at,
                "telegram.attachment.actual_media_type_denied",
            )
        if media_type != declared_media_type:
            return self._rejected(
                attachment,
                recorded_at,
                "telegram.attachment.media_type_mismatch",
            )

        content_hash = sha256_digest(payload.content)
        blob_id = f"quarantine_{content_hash.removeprefix('sha256:')[:32]}"
        existing = self._blobs.get(blob_id)
        if existing is not None and (
            existing.owner_id != self._owner_id or existing.content != payload.content
        ):
            raise TelegramAttachmentConflictError(
                "Telegram quarantine content-address collision"
            )
        if existing is None and sum(len(blob.content) for blob in self._blobs.values()) + (
            size_bytes
        ) > self._max_quarantine_bytes:
            return self._rejected(
                attachment,
                recorded_at,
                "telegram.attachment.quarantine_quota_exceeded",
            )
        expires_at = recorded_at + self._retention_ttl
        self._blobs[blob_id] = _QuarantinedTelegramBlob(
            owner_id=self._owner_id,
            content=payload.content,
            content_hash=content_hash,
            retained_at=recorded_at if existing is None else existing.retained_at,
            expires_at=(
                expires_at if existing is None else max(expires_at, existing.expires_at)
            ),
            retention_policy=self._retention_policy,
        )
        return TelegramAttachmentReceipt(
            file_unique_id=attachment.file_unique_id,
            disposition=TelegramAttachmentDisposition.QUARANTINED,
            recorded_at=recorded_at,
            quarantine_blob_id=blob_id,
            content_hash=content_hash,
            size_bytes=size_bytes,
            media_type=media_type,
        )

    @staticmethod
    def _rejected(
        attachment: TelegramAttachmentReference,
        recorded_at: datetime,
        reason_code: QualifiedName,
    ) -> TelegramAttachmentReceipt:
        return TelegramAttachmentReceipt(
            file_unique_id=attachment.file_unique_id,
            disposition=TelegramAttachmentDisposition.REJECTED,
            recorded_at=recorded_at,
            reason_code=reason_code,
        )

    @staticmethod
    def _normalize_media_type(value: str) -> str:
        return value.split(";", maxsplit=1)[0].strip().lower()


class InMemoryTelegramPairingStateStore:
    """Keep immutable candidates and one exact active pairing per owner/adapter."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._candidates: dict[tuple[str, str], TelegramPairingCandidate] = {}
        self._candidate_by_update: dict[tuple[str, int], str] = {}
        self._pairings: dict[tuple[str, str], TelegramOwnerPairing] = {}
        self._pairing_by_candidate: dict[tuple[str, str], str] = {}
        self._active_by_owner: dict[tuple[str, str], str] = {}

    def create_candidate(
        self,
        adapter_id: str,
        candidate: TelegramPairingCandidate,
    ) -> TelegramPairingCandidate:
        with self._lock:
            key = (adapter_id, candidate.candidate_id)
            update_key = (adapter_id, candidate.update_id)
            existing = self._candidates.get(key)
            existing_id = self._candidate_by_update.get(update_key)
            if existing is not None or existing_id is not None:
                if existing != candidate or existing_id != candidate.candidate_id:
                    raise TelegramPairingConflictError(
                        "Telegram candidate identity or update binding conflicts"
                    )
                return candidate
            self._candidates[key] = candidate
            self._candidate_by_update[update_key] = candidate.candidate_id
            return candidate

    def get_candidate(self, adapter_id: str, candidate_id: str) -> TelegramPairingCandidate:
        with self._lock:
            try:
                return self._candidates[(adapter_id, candidate_id)]
            except KeyError as error:
                raise TelegramPairingNotFoundError(
                    "Telegram pairing candidate not found"
                ) from error

    def get_candidate_for_update(
        self,
        adapter_id: str,
        update_id: int,
    ) -> TelegramPairingCandidate | None:
        with self._lock:
            candidate_id = self._candidate_by_update.get((adapter_id, update_id))
            if candidate_id is None:
                return None
            return self._candidates[(adapter_id, candidate_id)]

    def list_candidates(
        self,
        adapter_id: str,
        owner_id: str,
    ) -> tuple[TelegramPairingCandidate, ...]:
        with self._lock:
            candidates = (
                candidate
                for (stored_adapter_id, _candidate_id), candidate in self._candidates.items()
                if stored_adapter_id == adapter_id and candidate.owner_id == owner_id
            )
            return tuple(
                sorted(
                    candidates,
                    key=lambda candidate: (candidate.observed_at, candidate.candidate_id),
                )
            )

    def get_pairing(self, adapter_id: str, pairing_id: str) -> TelegramOwnerPairing:
        with self._lock:
            try:
                return self._pairings[(adapter_id, pairing_id)]
            except KeyError as error:
                raise TelegramPairingNotFoundError("Telegram owner pairing not found") from error

    def get_pairing_for_candidate(
        self,
        adapter_id: str,
        candidate_id: str,
    ) -> TelegramOwnerPairing | None:
        with self._lock:
            pairing_id = self._pairing_by_candidate.get((adapter_id, candidate_id))
            if pairing_id is None:
                return None
            return self._pairings[(adapter_id, pairing_id)]

    def active_pairing(
        self,
        adapter_id: str,
        owner_id: str,
    ) -> TelegramOwnerPairing | None:
        with self._lock:
            pairing_id = self._active_by_owner.get((adapter_id, owner_id))
            if pairing_id is None:
                return None
            pairing = self._pairings[(adapter_id, pairing_id)]
            return None if pairing.revoked_at is not None else pairing

    def confirm_pairing(
        self,
        adapter_id: str,
        candidate: TelegramPairingCandidate,
        pairing: TelegramOwnerPairing,
    ) -> TelegramOwnerPairing:
        with self._lock:
            stored_candidate = self.get_candidate(adapter_id, candidate.candidate_id)
            if stored_candidate != candidate:
                raise TelegramPairingConflictError("Telegram pairing candidate changed")
            validate_telegram_pairing_confirmation(candidate, pairing)
            candidate_key = (adapter_id, candidate.candidate_id)
            existing_id = self._pairing_by_candidate.get(candidate_key)
            if existing_id is not None:
                existing = self._pairings[(adapter_id, existing_id)]
                if existing != pairing:
                    raise TelegramPairingConflictError(
                        "Telegram candidate has a different pairing outcome"
                    )
                return existing
            active = self.active_pairing(adapter_id, candidate.owner_id)
            if active is not None:
                raise TelegramPairingConflictError(
                    "Telegram owner already has an active pairing"
                )
            pairing_key = (adapter_id, pairing.pairing_id)
            existing_pairing = self._pairings.get(pairing_key)
            if existing_pairing is not None and existing_pairing != pairing:
                raise TelegramPairingConflictError("Telegram pairing ID conflicts")
            self._pairings[pairing_key] = pairing
            self._pairing_by_candidate[candidate_key] = pairing.pairing_id
            self._active_by_owner[(adapter_id, pairing.owner_id)] = pairing.pairing_id
            return pairing

    def revoke_pairing(
        self,
        adapter_id: str,
        pairing: TelegramOwnerPairing,
    ) -> TelegramOwnerPairing:
        with self._lock:
            TelegramOwnerPairing.model_validate(pairing.model_dump())
            existing = self.get_pairing(adapter_id, pairing.pairing_id)
            if existing == pairing:
                return existing
            if pairing.revoked_at is None or existing.revoked_at is not None:
                raise TelegramPairingConflictError("Telegram pairing revocation conflicts")
            if existing.model_copy(update={"revoked_at": pairing.revoked_at}) != pairing:
                raise TelegramPairingConflictError(
                    "Telegram pairing identity changed on revocation"
                )
            self._pairings[(adapter_id, pairing.pairing_id)] = pairing
            active_key = (adapter_id, pairing.owner_id)
            if self._active_by_owner.get(active_key) == pairing.pairing_id:
                del self._active_by_owner[active_key]
            return pairing


class FakeTelegramUpdateSource:
    """Replay normalized synthetic updates without consuming or hiding them."""

    def __init__(
        self,
        updates: tuple[TelegramInboundUpdate, ...] = (),
        *,
        adapter_id: QualifiedName = "client.telegram.synthetic",
        failure_codes: tuple[QualifiedName, ...] = (),
    ) -> None:
        self._adapter_id = adapter_id
        self._updates: dict[int, TelegramInboundUpdate] = {}
        self._failure_codes = list(failure_codes)
        self.requests: list[TelegramPollRequest] = []
        for update in updates:
            self.add_update(update)

    def add_update(self, update: TelegramInboundUpdate) -> None:
        existing = self._updates.get(update.update_id)
        if existing is not None and existing != update:
            raise TelegramPollConflictError(
                "Telegram update ID was reused with different content"
            )
        self._updates[update.update_id] = update

    def poll(self, request: TelegramPollRequest) -> tuple[TelegramInboundUpdate, ...]:
        if request.adapter_id != self._adapter_id:
            raise TelegramPollConflictError("Telegram source adapter identity mismatch")
        self.requests.append(request)
        if self._failure_codes:
            raise TransientTelegramPollingError(self._failure_codes.pop(0))
        eligible = (
            update
            for update_id, update in sorted(self._updates.items())
            if update_id >= request.offset
        )
        return tuple(eligible)[: request.limit]

    def health(self) -> JsonObject:
        return {
            "status": "degraded" if self._failure_codes else "healthy",
            "transport": "synthetic",
            "network": False,
            "credentials": False,
            "available_updates": len(self._updates),
            "planned_failures": len(self._failure_codes),
        }


class InMemoryTelegramPollStateStore:
    """Commit immutable observations and outcomes before advancing a cursor."""

    def __init__(
        self,
        *,
        adapter_id: QualifiedName = "client.telegram.synthetic",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._adapter_id = adapter_id
        self._state = TelegramPollState(
            adapter_id=adapter_id,
            updated_at=clock(),
        )
        self._updates: dict[int, TelegramInboundUpdate] = {}
        self._receipts: dict[int, TelegramIngestionReceipt] = {}

    def read_state(self, adapter_id: QualifiedName) -> TelegramPollState:
        self._require_adapter(adapter_id)
        return self._state

    def get_receipt(
        self,
        adapter_id: QualifiedName,
        update_id: TelegramUpdateId,
    ) -> TelegramIngestionReceipt | None:
        self._require_adapter(adapter_id)
        return self._receipts.get(update_id)

    def get_update(
        self,
        adapter_id: QualifiedName,
        update_id: TelegramUpdateId,
    ) -> TelegramInboundUpdate | None:
        self._require_adapter(adapter_id)
        return self._updates.get(update_id)

    def commit_ingestion(
        self,
        update: TelegramInboundUpdate,
        receipt: TelegramIngestionReceipt,
        *,
        expected_revision: int,
    ) -> TelegramPollState:
        self._require_adapter(receipt.adapter_id)
        existing_update = self._updates.get(update.update_id)
        existing = self._receipts.get(receipt.update_id)
        if existing_update is not None or existing is not None:
            if existing_update != update or existing != receipt:
                raise TelegramPollConflictError(
                    "Telegram update ID has different immutable ingestion data"
                )
            return self._state
        validate_telegram_ingestion_receipt(update, receipt)
        if expected_revision != self._state.revision:
            raise TelegramPollConflictError("Telegram poll state revision is stale")
        if receipt.update_id < self._state.next_offset:
            raise TelegramPollConflictError("Telegram poll offset cannot move backwards")
        if receipt.recorded_at < self._state.updated_at:
            raise TelegramPollConflictError("Telegram receipt predates poll state")

        next_state = TelegramPollState(
            adapter_id=self._adapter_id,
            next_offset=receipt.update_id + 1,
            revision=self._state.revision + 1,
            last_update_id=receipt.update_id,
            last_receipt_id=receipt.receipt_id,
            updated_at=receipt.recorded_at,
        )
        self._updates[update.update_id] = update
        self._receipts[receipt.update_id] = receipt
        self._state = next_state
        return next_state

    def _require_adapter(self, adapter_id: QualifiedName) -> None:
        if adapter_id != self._adapter_id:
            raise TelegramPollConflictError("Telegram poll state adapter is not configured")
