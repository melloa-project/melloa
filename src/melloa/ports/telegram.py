"""Ports for credential-free Telegram pairing, polling, and durable state."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from melloa.domain.base import JsonObject, QualifiedName, RecordId
from melloa.domain.retention import RetentionDeletionReceipt
from melloa.domain.telegram import (
    TelegramAttachmentIntakeRequest,
    TelegramAttachmentReceipt,
    TelegramInboundUpdate,
    TelegramIngestionReceipt,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramPollRequest,
    TelegramPollState,
    TelegramUpdateId,
)


class TelegramPollingError(RuntimeError):
    """Polling failed without exposing raw provider details."""

    def __init__(self, reason_code: QualifiedName, *, retryable: bool) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.retryable = retryable


class TransientTelegramPollingError(TelegramPollingError):
    def __init__(self, reason_code: QualifiedName) -> None:
        super().__init__(reason_code, retryable=True)


class PermanentTelegramPollingError(TelegramPollingError):
    def __init__(self, reason_code: QualifiedName) -> None:
        super().__init__(reason_code, retryable=False)


class TelegramPollConflictError(RuntimeError):
    """Immutable update state or its optimistic cursor revision conflicted."""


class TelegramAttachmentError(RuntimeError):
    """Attachment intake failed without exposing raw provider details."""

    def __init__(self, reason_code: QualifiedName, *, retryable: bool) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.retryable = retryable


class TransientTelegramAttachmentError(TelegramAttachmentError):
    def __init__(self, reason_code: QualifiedName) -> None:
        super().__init__(reason_code, retryable=True)


class TelegramAttachmentConflictError(RuntimeError):
    """An attachment request or immutable quarantine outcome conflicted."""


class TelegramPairingNotFoundError(LookupError):
    """A pairing candidate or confirmed pairing was not found."""


class TelegramPairingConflictError(RuntimeError):
    """Pairing state or an exact immutable binding conflicted."""


@dataclass(frozen=True)
class TelegramPairingChallenge:
    candidate: TelegramPairingCandidate
    confirmation_code: str = field(repr=False)


class TelegramPairingCodeIssuer(Protocol):
    def issue(self, candidate_id: RecordId) -> str:
        """Derive one replay-stable high-entropy code without storing plaintext."""


class TelegramPairingChallengePublisher(Protocol):
    def publish(self, challenge: TelegramPairingChallenge) -> None:
        """Deliver an exact candidate-bound code through the initiating private chat."""


class TelegramPairingStateStore(Protocol):
    def create_candidate(
        self,
        adapter_id: QualifiedName,
        candidate: TelegramPairingCandidate,
    ) -> TelegramPairingCandidate:
        """Create one immutable candidate or accept its exact replay."""

    def get_candidate(
        self,
        adapter_id: QualifiedName,
        candidate_id: RecordId,
    ) -> TelegramPairingCandidate:
        """Return one candidate or raise TelegramPairingNotFoundError."""

    def get_candidate_for_update(
        self,
        adapter_id: QualifiedName,
        update_id: TelegramUpdateId,
    ) -> TelegramPairingCandidate | None:
        """Resolve a candidate previously created for one adapter update."""

    def list_candidates(
        self,
        adapter_id: QualifiedName,
        owner_id: RecordId,
    ) -> tuple[TelegramPairingCandidate, ...]:
        """List owner-scoped candidates in deterministic observation order."""

    def get_pairing(
        self,
        adapter_id: QualifiedName,
        pairing_id: RecordId,
    ) -> TelegramOwnerPairing:
        """Return one confirmed pairing or raise TelegramPairingNotFoundError."""

    def get_pairing_for_candidate(
        self,
        adapter_id: QualifiedName,
        candidate_id: RecordId,
    ) -> TelegramOwnerPairing | None:
        """Resolve the one-time outcome for a candidate."""

    def active_pairing(
        self,
        adapter_id: QualifiedName,
        owner_id: RecordId,
    ) -> TelegramOwnerPairing | None:
        """Return the owner's one active exact pairing, if configured."""

    def confirm_pairing(
        self,
        adapter_id: QualifiedName,
        candidate: TelegramPairingCandidate,
        pairing: TelegramOwnerPairing,
    ) -> TelegramOwnerPairing:
        """Atomically consume a candidate and establish one active pairing."""

    def revoke_pairing(
        self,
        adapter_id: QualifiedName,
        pairing: TelegramOwnerPairing,
    ) -> TelegramOwnerPairing:
        """Persist an exact authority-reducing revocation."""


@dataclass(frozen=True)
class TelegramQuarantineRetentionInventory:
    retained_objects: int
    retained_bytes: int
    deletion_receipts: int
    oldest_retained_at: datetime | None


class TelegramAttachmentBackend(Protocol):
    @property
    def owner_id(self) -> RecordId:
        """Return the local owner whose quarantine namespace this backend serves."""

    def retention_inventory(self) -> TelegramQuarantineRetentionInventory:
        """Return aggregate retained quarantine counts for this owner namespace."""

    def handle(
        self,
        request: TelegramAttachmentIntakeRequest,
    ) -> tuple[TelegramAttachmentReceipt, ...]:
        """Reject before fetch or idempotently quarantine every exact reference."""


class TelegramAttachmentRetentionBackend(TelegramAttachmentBackend, Protocol):
    def sweep_expired(
        self,
        *,
        as_of: datetime,
        limit: int = 100,
    ) -> tuple[RetentionDeletionReceipt, ...]:
        """Delete a bounded deterministic batch of due quarantine blobs."""


class TelegramUpdateSource(Protocol):
    def poll(self, request: TelegramPollRequest) -> tuple[TelegramInboundUpdate, ...]:
        """Long-poll normalized, size-checked updates without advancing state."""

    def health(self) -> JsonObject:
        """Return non-sensitive source health without making Telegram authoritative."""


class TelegramPollStateStore(Protocol):
    def read_state(self, adapter_id: QualifiedName) -> TelegramPollState:
        """Return the durable next offset for one configured adapter."""

    def get_receipt(
        self,
        adapter_id: QualifiedName,
        update_id: TelegramUpdateId,
    ) -> TelegramIngestionReceipt | None:
        """Resolve an immutable prior outcome by Telegram update ID."""

    def get_update(
        self,
        adapter_id: QualifiedName,
        update_id: TelegramUpdateId,
    ) -> TelegramInboundUpdate | None:
        """Resolve the immutable normalized inbound observation by update ID."""

    def list_ingested_receipts(
        self,
        adapter_id: QualifiedName,
        *,
        after_update_id: TelegramUpdateId | None = None,
        limit: int = 100,
    ) -> tuple[TelegramIngestionReceipt, ...]:
        """Scan a bounded ordered batch for restart-safe reply dispatch."""

    def commit_ingestion(
        self,
        update: TelegramInboundUpdate,
        receipt: TelegramIngestionReceipt,
        *,
        expected_revision: int,
    ) -> TelegramPollState:
        """Persist one observation/outcome before monotonically advancing the offset."""
