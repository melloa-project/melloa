"""Canonical ingestion for the optional secondary Telegram adapter."""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from threading import RLock
from typing import Literal

from melloa.application.delivery import (
    ClientDeliveryRoute,
    DeliveryService,
    DeliveryUnavailableError,
)
from melloa.domain.audit import AuditContent
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import (
    JsonObject,
    QualifiedName,
    RecordId,
    canonical_json_bytes,
    new_record_id,
    sha256_digest,
    utc_now,
)
from melloa.domain.classification import (
    EpistemicStatus,
    Sensitivity,
    TrustLabel,
    sensitivity_scope,
)
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingState,
    ConversationReplyWork,
    ConversationThread,
    DeliveryState,
    MessageKind,
    MessagePart,
)
from melloa.domain.delivery import DeliveryWorkStatus
from melloa.domain.events import EventEnvelope, EventIntegrity, EventProducer, EventSource
from melloa.domain.guardian import GuardianMode
from melloa.domain.retention import RetentionDeletionReceipt
from melloa.domain.telegram import (
    TelegramAttachmentDisposition,
    TelegramAttachmentIntakeRequest,
    TelegramAttachmentReceipt,
    TelegramInboundUpdate,
    TelegramIngestionReceipt,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramPollRequest,
    TelegramPollState,
    TelegramUpdateDisposition,
    TelegramUpdateId,
    telegram_pairing_destination,
    telegram_pairing_id_from_destination,
    telegram_update_fingerprint,
    validate_paired_telegram_update,
    validate_telegram_attachment_receipts,
    validate_telegram_ingestion_receipt,
    validate_telegram_pairing_candidate,
)
from melloa.ports.auth import RecentAuthenticationRequired
from melloa.ports.client import ClientAdapter
from melloa.ports.conversation import ConversationConflictError, ConversationStore
from melloa.ports.delivery import DeliveryStore
from melloa.ports.guardian import GuardianStatusReader
from melloa.ports.store import EventAuditStore
from melloa.ports.telegram import (
    TelegramAttachmentBackend,
    TelegramAttachmentConflictError,
    TelegramAttachmentRetentionBackend,
    TelegramPairingChallenge,
    TelegramPairingChallengePublisher,
    TelegramPairingCodeIssuer,
    TelegramPairingConflictError,
    TelegramPairingNotFoundError,
    TelegramPairingStateStore,
    TelegramPollConflictError,
    TelegramPollingError,
    TelegramPollStateStore,
    TelegramUpdateSource,
)


class TelegramIngestionUnavailableError(RuntimeError):
    """Guardian state forbids Telegram polling or canonical writes."""


class TelegramRetentionUnavailableError(RuntimeError):
    """Guardian state forbids destructive quarantine expiry."""


class TelegramIngestionOwnershipError(PermissionError):
    """Configured pairing or thread does not belong to the local owner."""


class TelegramPollBatchError(RuntimeError):
    """A source violated the bounded ordered polling contract."""


class TelegramPairingOwnershipError(PermissionError):
    """An authenticated principal attempted to inspect another owner's pairing."""


class TelegramPairingUnavailableError(RuntimeError):
    """Guardian state forbids activation of Telegram channel authority."""


class TelegramPairingCandidateRejectedError(ValueError):
    """An untrusted update cannot become a pairing candidate."""


@dataclass(frozen=True)
class TelegramIngestionResult:
    receipt: TelegramIngestionReceipt
    poll_state: TelegramPollState
    canonical_message: ConversationMessage | None
    canonical_created: bool
    receipt_replayed: bool


@dataclass(frozen=True)
class TelegramPollCycle:
    request: TelegramPollRequest
    state_before: TelegramPollState
    state_after: TelegramPollState
    outcomes: tuple[TelegramIngestionResult, ...]


def telegram_inbound_idempotency_key(
    adapter_id: QualifiedName,
    update_id: TelegramUpdateId,
) -> str:
    """Bind canonical acceptance to one adapter-scoped Telegram update ID."""

    return f"telegram:{adapter_id}:update:{update_id}"


class TelegramPairingService:
    """Coordinate one-time private-chat challenges and local owner confirmation."""

    def __init__(
        self,
        *,
        owner_id: RecordId,
        adapter_id: QualifiedName,
        store: TelegramPairingStateStore,
        code_issuer: TelegramPairingCodeIssuer,
        challenge_publisher: TelegramPairingChallengePublisher,
        guardian_reader: GuardianStatusReader,
        event_audit_store: EventAuditStore | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
        candidate_ttl: timedelta = timedelta(minutes=10),
    ) -> None:
        if not timedelta(minutes=1) <= candidate_ttl <= timedelta(hours=1):
            raise ValueError("Telegram pairing candidate lifetime must be 1 to 60 minutes")
        self._owner_id = owner_id
        self._adapter_id = adapter_id
        self._store = store
        self._code_issuer = code_issuer
        self._challenge_publisher = challenge_publisher
        self._guardian_reader = guardian_reader
        self._event_audit_store = event_audit_store
        self._clock = clock
        self._id_factory = id_factory
        self._candidate_ttl = candidate_ttl

    @property
    def owner_id(self) -> RecordId:
        return self._owner_id

    @property
    def adapter_id(self) -> QualifiedName:
        return self._adapter_id

    def begin_candidate(self, update: TelegramInboundUpdate) -> TelegramPairingCandidate:
        self._require_activation_mode()
        existing = self._store.get_candidate_for_update(self._adapter_id, update.update_id)
        if existing is not None:
            try:
                validate_telegram_pairing_candidate(update, existing)
            except ValueError as error:
                raise TelegramPairingConflictError(
                    "Telegram candidate update changed across replay"
                ) from error
            if self._clock() >= existing.expires_at:
                raise TelegramPairingCandidateRejectedError(
                    "Telegram pairing candidate has expired"
                )
            self._publish_replay_stable_challenge(existing)
            return existing

        candidate_id = self._id_factory("tgcandidate")
        confirmation_code = self._issue_code(candidate_id)
        try:
            candidate = TelegramPairingCandidate(
                candidate_id=candidate_id,
                owner_id=self._owner_id,
                update_id=update.update_id,
                telegram_user_id=update.message.sender_user_id,
                telegram_chat_id=update.message.chat_id,
                confirmation_code_hash=sha256_digest(confirmation_code.encode()),
                observed_at=update.received_at,
                expires_at=update.received_at + self._candidate_ttl,
            )
            validate_telegram_pairing_candidate(update, candidate)
        except ValueError as error:
            raise TelegramPairingCandidateRejectedError(
                "Telegram update is not an exact private pairing request"
            ) from error
        if self._clock() >= candidate.expires_at:
            raise TelegramPairingCandidateRejectedError(
                "Telegram pairing candidate has expired"
            )
        stored = self._store.create_candidate(self._adapter_id, candidate)
        self._challenge_publisher.publish(
            TelegramPairingChallenge(
                candidate=stored,
                confirmation_code=confirmation_code,
            )
        )
        return stored

    def pending_candidates(
        self,
        principal: AuthenticatedOwner,
    ) -> tuple[TelegramPairingCandidate, ...]:
        self._require_owner(principal)
        now = self._clock()
        return tuple(
            candidate
            for candidate in self._store.list_candidates(self._adapter_id, self._owner_id)
            if candidate.expires_at > now
            and self._store.get_pairing_for_candidate(
                self._adapter_id,
                candidate.candidate_id,
            )
            is None
        )

    def inspect_active_pairing(
        self,
        principal: AuthenticatedOwner,
    ) -> TelegramOwnerPairing | None:
        self._require_owner(principal)
        return self.pairing_for_ingestion()

    def pairing_for_ingestion(self) -> TelegramOwnerPairing | None:
        pairing = self._store.active_pairing(self._adapter_id, self._owner_id)
        if pairing is not None and pairing.owner_id != self._owner_id:
            raise TelegramPairingConflictError(
                "Telegram active pairing belongs to another owner"
            )
        return pairing

    def pairing_for_delivery(self, pairing_id: RecordId) -> TelegramOwnerPairing:
        pairing = self._store.get_pairing(self._adapter_id, pairing_id)
        active = self.pairing_for_ingestion()
        if (
            pairing.owner_id != self._owner_id
            or pairing.revoked_at is not None
            or active != pairing
        ):
            raise TelegramPairingNotFoundError("active Telegram owner pairing not found")
        return pairing

    def confirm(
        self,
        principal: AuthenticatedOwner,
        candidate_id: RecordId,
        confirmation_code: str,
    ) -> TelegramOwnerPairing:
        now = self._clock()
        self._require_owner(principal)
        self._require_recent_authentication(principal, now)
        self._require_activation_mode()
        candidate = self._store.get_candidate(self._adapter_id, candidate_id)
        if candidate.owner_id != self._owner_id:
            raise TelegramPairingNotFoundError("Telegram pairing candidate not found")
        existing = self._store.get_pairing_for_candidate(self._adapter_id, candidate_id)
        if existing is not None:
            if existing.revoked_at is not None:
                raise TelegramPairingConflictError(
                    "Telegram pairing candidate was already consumed"
                )
            self._append_pairing_audit(
                principal=principal,
                pairing=existing,
                lifecycle="confirmed",
            )
            return existing
        if now >= candidate.expires_at:
            raise TelegramPairingConflictError("Telegram pairing candidate expired")
        expected_hash = sha256_digest(confirmation_code.encode())
        if not hmac.compare_digest(candidate.confirmation_code_hash, expected_hash):
            raise TelegramPairingConflictError("Telegram pairing confirmation code is invalid")
        if self.pairing_for_ingestion() is not None:
            raise TelegramPairingConflictError("Telegram owner already has an active pairing")
        pairing = TelegramOwnerPairing(
            pairing_id=self._id_factory("tgpairing"),
            candidate_id=candidate.candidate_id,
            owner_id=self._owner_id,
            telegram_user_id=candidate.telegram_user_id,
            telegram_chat_id=candidate.telegram_chat_id,
            confirmed_by_owner_id=principal.owner_id,
            confirmed_at=now,
        )
        persisted = self._store.confirm_pairing(self._adapter_id, candidate, pairing)
        self._append_pairing_audit(
            principal=principal,
            pairing=persisted,
            lifecycle="confirmed",
        )
        return persisted

    def revoke(
        self,
        principal: AuthenticatedOwner,
        pairing_id: RecordId,
    ) -> TelegramOwnerPairing:
        now = self._clock()
        self._require_owner(principal)
        self._require_recent_authentication(principal, now)
        pairing = self._store.get_pairing(self._adapter_id, pairing_id)
        if pairing.owner_id != self._owner_id:
            raise TelegramPairingNotFoundError("Telegram owner pairing not found")
        if pairing.revoked_at is not None:
            self._append_pairing_audit(
                principal=principal,
                pairing=pairing,
                lifecycle="revoked",
            )
            return pairing
        revoked = TelegramOwnerPairing.model_validate(
            {
                **pairing.model_dump(),
                "revoked_at": now,
            }
        )
        persisted = self._store.revoke_pairing(self._adapter_id, revoked)
        self._append_pairing_audit(
            principal=principal,
            pairing=persisted,
            lifecycle="revoked",
        )
        return persisted

    def _append_pairing_audit(
        self,
        *,
        principal: AuthenticatedOwner,
        pairing: TelegramOwnerPairing,
        lifecycle: Literal["confirmed", "revoked"],
    ) -> None:
        event_audit_store = self._event_audit_store
        if event_audit_store is None:
            return
        if lifecycle == "confirmed":
            occurred_at = pairing.confirmed_at
            event_type: QualifiedName = "telegram.owner-pairing-confirmed.v1"
            action: QualifiedName = "telegram.owner-pairing.confirm"
        else:
            revoked_at = pairing.revoked_at
            if revoked_at is None:
                raise TelegramPairingConflictError(
                    "Telegram pairing revocation audit requires revoked state"
                )
            occurred_at = revoked_at
            event_type = "telegram.owner-pairing-revoked.v1"
            action = "telegram.owner-pairing.revoke"
        payload: JsonObject = {
            "adapter_id": self._adapter_id,
            "candidate_id": pairing.candidate_id,
            "pairing_id": pairing.pairing_id,
            "state": lifecycle,
        }
        event = EventEnvelope(
            event_id=self._derived_pairing_audit_id(
                "event",
                pairing.pairing_id,
                event_type,
            ),
            event_type=event_type,
            schema_version="1.0.0",
            occurred_at=occurred_at,
            recorded_at=occurred_at,
            subject_ids=(pairing.owner_id,),
            source=EventSource(
                capability_id="telegram.owner-pairing",
                execution_id=pairing.pairing_id,
            ),
            producer=EventProducer(
                component="telegram.pairing-service",
                version="0.1.0",
            ),
            epistemic_status=EpistemicStatus.OBSERVATION,
            sensitivity=Sensitivity.PERSONAL,
            trust=TrustLabel.TRUSTED_SYSTEM,
            retention_policy="retention.audit-ledger",
            correlation_id=pairing.pairing_id,
            payload=payload,
            integrity=EventIntegrity(
                payload_hash=sha256_digest(canonical_json_bytes(payload))
            ),
        )
        audit = AuditContent(
            audit_id=self._derived_pairing_audit_id(
                "audit",
                pairing.pairing_id,
                action,
            ),
            event_type="audit.event-appended.v1",
            occurred_at=occurred_at,
            actor_id=principal.owner_id,
            action=action,
            object_ids=(pairing.pairing_id, pairing.candidate_id),
            metadata={
                "adapter_id": self._adapter_id,
                "event_id": event.event_id,
                "result": lifecycle,
            },
        )
        event_audit_store.append_event(event, audit)

    @staticmethod
    def _derived_pairing_audit_id(
        prefix: str,
        pairing_id: RecordId,
        purpose: QualifiedName,
    ) -> str:
        digest = sha256_digest(
            canonical_json_bytes(
                {
                    "pairing_id": pairing_id,
                    "prefix": prefix,
                    "purpose": purpose,
                }
            )
        ).removeprefix("sha256:")
        return f"{prefix}_{digest[:32]}"

    def _publish_replay_stable_challenge(
        self,
        candidate: TelegramPairingCandidate,
    ) -> None:
        confirmation_code = self._issue_code(candidate.candidate_id)
        expected_hash = sha256_digest(confirmation_code.encode())
        if not hmac.compare_digest(candidate.confirmation_code_hash, expected_hash):
            raise TelegramPairingConflictError(
                "Telegram pairing code issuer changed across replay"
            )
        self._challenge_publisher.publish(
            TelegramPairingChallenge(
                candidate=candidate,
                confirmation_code=confirmation_code,
            )
        )

    def _issue_code(self, candidate_id: RecordId) -> str:
        confirmation_code = self._code_issuer.issue(candidate_id)
        if re.fullmatch(r"[A-Za-z0-9_-]{20,128}", confirmation_code) is None:
            raise TelegramPairingConflictError(
                "Telegram pairing code issuer returned an invalid code"
            )
        return confirmation_code

    def _require_owner(self, principal: AuthenticatedOwner) -> None:
        if principal.owner_id != self._owner_id:
            raise TelegramPairingOwnershipError(
                "authenticated principal does not own this Telegram pairing"
            )

    @staticmethod
    def _require_recent_authentication(
        principal: AuthenticatedOwner,
        now: datetime,
    ) -> None:
        if now >= principal.reauthenticated_until:
            raise RecentAuthenticationRequired("recent owner authentication required")

    def _require_activation_mode(self) -> GuardianMode:
        mode = self._guardian_reader.read_status().payload.mode
        if mode in {
            GuardianMode.NO_ACTIONS,
            GuardianMode.OFFLINE,
            GuardianMode.READ_ONLY,
            GuardianMode.STOPPED,
            GuardianMode.RECOVERY,
        }:
            raise TelegramPairingUnavailableError(
                f"Guardian mode does not permit Telegram pairing activation: {mode.value}"
            )
        return mode


class TelegramIngestionService:
    """Validate one paired update and record its canonical durable outcome."""

    def __init__(
        self,
        *,
        owner_id: RecordId,
        thread_id: RecordId,
        adapter_id: QualifiedName,
        pairing_service: TelegramPairingService,
        attachment_backend: TelegramAttachmentBackend,
        conversation_store: ConversationStore,
        poll_state_store: TelegramPollStateStore,
        guardian_reader: GuardianStatusReader,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
        max_processing_attempts: int = 3,
    ) -> None:
        if pairing_service.owner_id != owner_id:
            raise TelegramIngestionOwnershipError(
                "Telegram pairing service does not belong to the configured owner"
            )
        if pairing_service.adapter_id != adapter_id:
            raise ValueError("Telegram pairing service adapter identity mismatch")
        if attachment_backend.owner_id != owner_id:
            raise TelegramIngestionOwnershipError(
                "Telegram attachment backend does not belong to the configured owner"
            )
        if max_processing_attempts < 1:
            raise ValueError("max processing attempts must be positive")
        self._owner_id = owner_id
        self._thread_id = thread_id
        self._adapter_id = adapter_id
        self._pairing_service = pairing_service
        self._attachment_backend = attachment_backend
        self._conversation_store = conversation_store
        self._poll_state_store = poll_state_store
        self._guardian_reader = guardian_reader
        self._clock = clock
        self._id_factory = id_factory
        self._max_processing_attempts = max_processing_attempts

    def ingest(
        self,
        update: TelegramInboundUpdate,
        *,
        expected_revision: int,
    ) -> TelegramIngestionResult:
        if expected_revision < 0:
            raise ValueError("expected Telegram poll revision cannot be negative")
        replay = self._resolve_receipt_replay(update)
        if replay is not None:
            return replay

        self._require_write_mode()
        state = self._poll_state_store.read_state(self._adapter_id)
        if state.revision != expected_revision:
            raise TelegramPollConflictError("Telegram poll state revision is stale")
        if update.update_id < state.next_offset:
            raise TelegramPollConflictError("Telegram poll offset cannot move backwards")
        thread = self._require_owner_thread()
        recorded_at = self._receipt_time(update)
        attachments = self._rejected_attachments(
            update,
            recorded_at,
            reason_code="telegram.attachment.source_not_authorized",
        )

        pairing = self._pairing_service.pairing_for_ingestion()
        if pairing is None:
            if update.message.text == "/start":
                try:
                    candidate = self._pairing_service.begin_candidate(update)
                except TelegramPairingCandidateRejectedError:
                    return self._commit_rejection(
                        update,
                        attachments,
                        reason_code="telegram.pairing_candidate_invalid",
                        recorded_at=recorded_at,
                        expected_revision=expected_revision,
                    )
                return self._commit_pairing_candidate(
                    update,
                    candidate,
                    recorded_at=recorded_at,
                    expected_revision=expected_revision,
                )
            return self._commit_rejection(
                update,
                attachments,
                reason_code="telegram.owner_not_paired",
                recorded_at=recorded_at,
                expected_revision=expected_revision,
            )

        try:
            validate_paired_telegram_update(pairing, update)
        except ValueError:
            return self._commit_rejection(
                update,
                attachments,
                reason_code="telegram.owner_pairing_mismatch",
                recorded_at=recorded_at,
                expected_revision=expected_revision,
            )

        attachments = self._handle_attachments(update)
        recorded_at = self._receipt_time(update, attachments)
        if not self._canonical_parts(update, attachments):
            return self._commit_rejection(
                update,
                attachments,
                reason_code="telegram.attachment_only_unsupported",
                recorded_at=recorded_at,
                expected_revision=expected_revision,
            )

        canonical, created = self._append_message(thread, update, attachments)
        receipt = TelegramIngestionReceipt(
            receipt_id=self._id_factory("tgreceipt"),
            adapter_id=self._adapter_id,
            update_id=update.update_id,
            update_fingerprint=telegram_update_fingerprint(update),
            disposition=TelegramUpdateDisposition.INGESTED,
            recorded_at=recorded_at,
            canonical_message_id=canonical.message_id,
            pairing_id=pairing.pairing_id,
            attachment_receipts=attachments,
        )
        poll_state = self._poll_state_store.commit_ingestion(
            update,
            receipt,
            expected_revision=expected_revision,
        )
        return TelegramIngestionResult(
            receipt=receipt,
            poll_state=poll_state,
            canonical_message=canonical,
            canonical_created=created,
            receipt_replayed=False,
        )

    def _resolve_receipt_replay(
        self,
        update: TelegramInboundUpdate,
    ) -> TelegramIngestionResult | None:
        existing_update = self._poll_state_store.get_update(
            self._adapter_id,
            update.update_id,
        )
        receipt = self._poll_state_store.get_receipt(
            self._adapter_id,
            update.update_id,
        )
        if existing_update is None and receipt is None:
            return None
        if existing_update is None or receipt is None:
            raise TelegramPollConflictError(
                "Telegram update has incomplete immutable ingestion state"
            )
        if existing_update != update:
            raise TelegramPollConflictError("Telegram update ID was reused with different content")
        if receipt.adapter_id != self._adapter_id:
            raise TelegramPollConflictError("Telegram receipt adapter identity mismatch")
        validate_telegram_ingestion_receipt(update, receipt)
        thread = self._require_owner_thread()
        canonical = self._canonical_for_receipt(update, receipt, thread)
        return TelegramIngestionResult(
            receipt=receipt,
            poll_state=self._poll_state_store.read_state(self._adapter_id),
            canonical_message=canonical,
            canonical_created=False,
            receipt_replayed=True,
        )

    def _canonical_for_receipt(
        self,
        update: TelegramInboundUpdate,
        receipt: TelegramIngestionReceipt,
        thread: ConversationThread,
    ) -> ConversationMessage | None:
        if receipt.disposition is not TelegramUpdateDisposition.INGESTED:
            return None
        if receipt.canonical_message_id is None:
            raise TelegramPollConflictError(
                "ingested Telegram receipt has no usable canonical message"
            )
        canonical = self._conversation_store.get_message(receipt.canonical_message_id)
        self._require_same_canonical_message(
            canonical,
            thread,
            update,
            receipt.attachment_receipts,
        )
        return canonical

    def _append_message(
        self,
        thread: ConversationThread,
        update: TelegramInboundUpdate,
        attachments: tuple[TelegramAttachmentReceipt, ...],
    ) -> tuple[ConversationMessage, bool]:
        parts = self._canonical_parts(update, attachments)
        if not parts:
            raise ValueError("Telegram canonical content cannot be absent")
        idempotency_key = telegram_inbound_idempotency_key(
            self._adapter_id,
            update.update_id,
        )
        existing = self._conversation_store.get_inbound_by_idempotency_key(
            self._thread_id,
            idempotency_key,
        )
        if existing is not None:
            self._require_same_canonical_message(existing, thread, update, attachments)
            return existing, False

        candidate = ConversationMessage(
            message_id=self._id_factory("message"),
            thread_id=self._thread_id,
            author_principal_id=self._owner_id,
            source_client=self._adapter_id,
            parts=parts,
            delivery_state=DeliveryState.DELIVERED,
            sensitivity=thread.sensitivity,
            created_at=update.received_at,
            observed_at=update.message.sent_at,
        )
        work = ConversationReplyWork(
            work_id=self._id_factory("work"),
            thread_id=self._thread_id,
            message_id=candidate.message_id,
            created_at=candidate.created_at,
        )
        accepted = self._conversation_store.append_inbound(
            candidate,
            idempotency_key,
            work,
            max_attempts=self._max_processing_attempts,
        )
        self._require_same_canonical_message(
            accepted.message,
            thread,
            update,
            attachments,
        )
        return accepted.message, accepted.created

    def _require_same_canonical_message(
        self,
        message: ConversationMessage,
        thread: ConversationThread,
        update: TelegramInboundUpdate,
        attachments: tuple[TelegramAttachmentReceipt, ...],
    ) -> None:
        expected = ConversationMessage(
            message_id=message.message_id,
            thread_id=self._thread_id,
            author_principal_id=self._owner_id,
            source_client=self._adapter_id,
            parts=self._canonical_parts(update, attachments),
            delivery_state=DeliveryState.DELIVERED,
            sensitivity=thread.sensitivity,
            created_at=update.received_at,
            observed_at=update.message.sent_at,
        )
        if message != expected:
            raise ConversationConflictError(
                "Telegram idempotency key was reused with different canonical content"
            )

    def _handle_attachments(
        self,
        update: TelegramInboundUpdate,
    ) -> tuple[TelegramAttachmentReceipt, ...]:
        if not update.message.attachments:
            return ()
        request = TelegramAttachmentIntakeRequest(
            adapter_id=self._adapter_id,
            update_id=update.update_id,
            update_fingerprint=telegram_update_fingerprint(update),
            received_at=update.received_at,
            attachments=update.message.attachments,
        )
        receipts = self._attachment_backend.handle(request)
        try:
            validate_telegram_attachment_receipts(request, receipts)
        except ValueError as error:
            raise TelegramAttachmentConflictError(
                "Telegram attachment backend returned an invalid outcome"
            ) from error
        return receipts

    @staticmethod
    def _canonical_parts(
        update: TelegramInboundUpdate,
        attachments: tuple[TelegramAttachmentReceipt, ...],
    ) -> tuple[MessagePart, ...]:
        parts: list[MessagePart] = []
        if update.message.text is not None:
            parts.append(MessagePart(kind=MessageKind.TEXT, text=update.message.text))
        for receipt in attachments:
            if receipt.disposition is TelegramAttachmentDisposition.REJECTED:
                continue
            if (
                receipt.quarantine_blob_id is None
                or receipt.media_type is None
                or receipt.content_hash is None
            ):
                raise TelegramAttachmentConflictError(
                    "Telegram quarantine receipt lacks canonical attachment metadata"
                )
            parts.append(
                MessagePart(
                    kind=MessageKind.ATTACHMENT,
                    attachment_id=receipt.quarantine_blob_id,
                    media_type=receipt.media_type,
                    content_hash=receipt.content_hash,
                )
            )
        return tuple(parts)

    def _receipt_time(
        self,
        update: TelegramInboundUpdate,
        attachments: tuple[TelegramAttachmentReceipt, ...] = (),
    ) -> datetime:
        recorded_at = max(self._clock(), update.received_at)
        for attachment in attachments:
            recorded_at = max(recorded_at, attachment.recorded_at)
        return recorded_at

    def _commit_pairing_candidate(
        self,
        update: TelegramInboundUpdate,
        candidate: TelegramPairingCandidate,
        *,
        recorded_at: datetime,
        expected_revision: int,
    ) -> TelegramIngestionResult:
        receipt = TelegramIngestionReceipt(
            receipt_id=self._id_factory("tgreceipt"),
            adapter_id=self._adapter_id,
            update_id=update.update_id,
            update_fingerprint=telegram_update_fingerprint(update),
            disposition=TelegramUpdateDisposition.PAIRING_CANDIDATE,
            recorded_at=recorded_at,
            pairing_candidate_id=candidate.candidate_id,
        )
        poll_state = self._poll_state_store.commit_ingestion(
            update,
            receipt,
            expected_revision=expected_revision,
        )
        return TelegramIngestionResult(
            receipt=receipt,
            poll_state=poll_state,
            canonical_message=None,
            canonical_created=False,
            receipt_replayed=False,
        )

    def _commit_rejection(
        self,
        update: TelegramInboundUpdate,
        attachments: tuple[TelegramAttachmentReceipt, ...],
        *,
        reason_code: QualifiedName,
        recorded_at: datetime,
        expected_revision: int,
    ) -> TelegramIngestionResult:
        receipt = TelegramIngestionReceipt(
            receipt_id=self._id_factory("tgreceipt"),
            adapter_id=self._adapter_id,
            update_id=update.update_id,
            update_fingerprint=telegram_update_fingerprint(update),
            disposition=TelegramUpdateDisposition.REJECTED,
            recorded_at=recorded_at,
            reason_code=reason_code,
            attachment_receipts=attachments,
        )
        poll_state = self._poll_state_store.commit_ingestion(
            update,
            receipt,
            expected_revision=expected_revision,
        )
        return TelegramIngestionResult(
            receipt=receipt,
            poll_state=poll_state,
            canonical_message=None,
            canonical_created=False,
            receipt_replayed=False,
        )

    def _rejected_attachments(
        self,
        update: TelegramInboundUpdate,
        recorded_at: datetime,
        *,
        reason_code: QualifiedName,
    ) -> tuple[TelegramAttachmentReceipt, ...]:
        return tuple(
            TelegramAttachmentReceipt(
                file_unique_id=attachment.file_unique_id,
                disposition=TelegramAttachmentDisposition.REJECTED,
                recorded_at=recorded_at,
                reason_code=reason_code,
            )
            for attachment in update.message.attachments
        )

    def _require_owner_thread(self) -> ConversationThread:
        thread = self._conversation_store.get_thread(self._thread_id)
        if thread.owner_id != self._owner_id:
            raise TelegramIngestionOwnershipError(
                "Telegram canonical thread does not belong to the configured owner"
            )
        return thread

    def _require_write_mode(self) -> GuardianMode:
        mode = self._guardian_reader.read_status().payload.mode
        if mode in {
            GuardianMode.OFFLINE,
            GuardianMode.READ_ONLY,
            GuardianMode.STOPPED,
            GuardianMode.RECOVERY,
        }:
            raise TelegramIngestionUnavailableError(
                f"Guardian mode does not permit Telegram ingestion: {mode.value}"
            )
        return mode


@dataclass(frozen=True)
class TelegramAttachmentRetentionCycle:
    swept_at: datetime
    deletion_receipts: tuple[RetentionDeletionReceipt, ...]


class TelegramAttachmentRetentionWorker:
    """Delete one bounded batch of due quarantine blobs under Guardian control."""

    def __init__(
        self,
        *,
        backend: TelegramAttachmentRetentionBackend,
        guardian_reader: GuardianStatusReader,
        batch_limit: int = 100,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not 1 <= batch_limit <= 1_000:
            raise ValueError("Telegram retention batch limit must be between 1 and 1000")
        self._backend = backend
        self._guardian_reader = guardian_reader
        self._batch_limit = batch_limit
        self._clock = clock
        self._health_lock = RLock()
        self._cycles = 0
        self._deletions = 0
        self._last_sweep_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error_code: QualifiedName | None = None

    def sweep_once(self) -> TelegramAttachmentRetentionCycle:
        self._require_sweep_mode()
        swept_at = self._clock()
        try:
            receipts = self._backend.sweep_expired(
                as_of=swept_at,
                limit=self._batch_limit,
            )
            self._validate_receipts(receipts)
        except Exception:
            self._record_failure(swept_at)
            raise
        self._record_success(swept_at, len(receipts))
        return TelegramAttachmentRetentionCycle(
            swept_at=swept_at,
            deletion_receipts=receipts,
        )

    def health(self) -> JsonObject:
        guardian_mode = self._guardian_reader.read_status().payload.mode
        with self._health_lock:
            cycles = self._cycles
            deletions = self._deletions
            last_sweep_at = self._last_sweep_at
            last_success_at = self._last_success_at
            last_error_code = self._last_error_code
        if guardian_mode in {
            GuardianMode.NO_ACTIONS,
            GuardianMode.READ_ONLY,
            GuardianMode.STOPPED,
            GuardianMode.RECOVERY,
        }:
            worker_state = "disabled"
            reason_code = f"guardian.{guardian_mode.value.replace('-', '_')}"
        elif last_error_code is not None:
            worker_state = "degraded"
            reason_code = last_error_code
        else:
            worker_state = "healthy"
            reason_code = "retention.worker.ready"
        return {
            "state": worker_state,
            "reason_code": reason_code,
            "batch_limit": self._batch_limit,
            "cycles": cycles,
            "deletions": deletions,
            "last_sweep_at": None if last_sweep_at is None else last_sweep_at.isoformat(),
            "last_success_at": (
                None if last_success_at is None else last_success_at.isoformat()
            ),
            "last_error_code": last_error_code,
        }

    def _validate_receipts(
        self,
        receipts: tuple[RetentionDeletionReceipt, ...],
    ) -> None:
        if len(receipts) > self._batch_limit:
            raise TelegramAttachmentConflictError(
                "Telegram retention backend exceeded the requested batch limit"
            )
        receipt_ids = tuple(receipt.receipt_id for receipt in receipts)
        if len(set(receipt_ids)) != len(receipt_ids):
            raise TelegramAttachmentConflictError(
                "Telegram retention backend returned duplicate deletion receipts"
            )
        if any(receipt.owner_id != self._backend.owner_id for receipt in receipts):
            raise TelegramAttachmentConflictError(
                "Telegram retention backend returned another owner's deletion receipt"
            )

    def _record_success(self, swept_at: datetime, deletions: int) -> None:
        with self._health_lock:
            self._cycles += 1
            self._deletions += deletions
            self._last_sweep_at = swept_at
            self._last_success_at = swept_at
            self._last_error_code = None

    def _record_failure(self, swept_at: datetime) -> None:
        with self._health_lock:
            self._cycles += 1
            self._last_sweep_at = swept_at
            self._last_error_code = "retention.worker.cycle_failed"

    def _require_sweep_mode(self) -> GuardianMode:
        mode = self._guardian_reader.read_status().payload.mode
        if mode in {
            GuardianMode.NO_ACTIONS,
            GuardianMode.READ_ONLY,
            GuardianMode.STOPPED,
            GuardianMode.RECOVERY,
        }:
            raise TelegramRetentionUnavailableError(
                f"Guardian mode does not permit quarantine expiry: {mode.value}"
            )
        return mode


class TelegramPollWorker:
    """Run one bounded, ordered long-poll cycle without owning network credentials."""

    def __init__(
        self,
        *,
        adapter_id: QualifiedName,
        source: TelegramUpdateSource,
        poll_state_store: TelegramPollStateStore,
        ingestion_service: TelegramIngestionService,
        guardian_reader: GuardianStatusReader,
        timeout_seconds: int = 30,
        batch_limit: int = 25,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not 1 <= timeout_seconds <= 50:
            raise ValueError("Telegram poll timeout must be between 1 and 50 seconds")
        if not 1 <= batch_limit <= 100:
            raise ValueError("Telegram poll batch limit must be between 1 and 100")
        self._adapter_id = adapter_id
        self._source = source
        self._poll_state_store = poll_state_store
        self._ingestion_service = ingestion_service
        self._guardian_reader = guardian_reader
        self._timeout_seconds = timeout_seconds
        self._batch_limit = batch_limit
        self._clock = clock
        self._health_lock = RLock()
        self._cycles = 0
        self._updates_handled = 0
        self._last_poll_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error_code: QualifiedName | None = None

    def poll_once(self) -> TelegramPollCycle:
        self._require_poll_mode()
        state_before = self._poll_state_store.read_state(self._adapter_id)
        request = TelegramPollRequest(
            adapter_id=self._adapter_id,
            offset=state_before.next_offset,
            timeout_seconds=self._timeout_seconds,
            limit=self._batch_limit,
        )
        polled_at = self._clock()
        try:
            updates = self._source.poll(request)
            self._validate_batch(request, updates)
            outcomes: list[TelegramIngestionResult] = []
            state_after = state_before
            for update in updates:
                outcome = self._ingestion_service.ingest(
                    update,
                    expected_revision=state_after.revision,
                )
                outcomes.append(outcome)
                state_after = outcome.poll_state
        except TelegramPollingError as error:
            self._record_failure(polled_at, error.reason_code)
            raise
        except Exception:
            self._record_failure(polled_at, "telegram.worker.cycle_failed")
            raise

        self._record_success(polled_at, len(outcomes))
        return TelegramPollCycle(
            request=request,
            state_before=state_before,
            state_after=state_after,
            outcomes=tuple(outcomes),
        )

    def health(self) -> JsonObject:
        guardian_mode = self._guardian_reader.read_status().payload.mode
        state = self._poll_state_store.read_state(self._adapter_id)
        source = self._source.health()
        with self._health_lock:
            cycles = self._cycles
            updates_handled = self._updates_handled
            last_poll_at = self._last_poll_at
            last_success_at = self._last_success_at
            last_error_code = self._last_error_code

        if guardian_mode in {
            GuardianMode.OFFLINE,
            GuardianMode.READ_ONLY,
            GuardianMode.STOPPED,
            GuardianMode.RECOVERY,
        }:
            worker_state = "disabled"
            reason_code = f"guardian.{guardian_mode.value.replace('-', '_')}"
        elif last_error_code is not None or source.get("status") != "healthy":
            worker_state = "degraded"
            reason_code = last_error_code or "telegram.source.degraded"
        else:
            worker_state = "healthy"
            reason_code = "telegram.worker.ready"
        return {
            "adapter_id": self._adapter_id,
            "state": worker_state,
            "reason_code": reason_code,
            "next_offset": state.next_offset,
            "poll_revision": state.revision,
            "timeout_seconds": self._timeout_seconds,
            "batch_limit": self._batch_limit,
            "cycles": cycles,
            "updates_handled": updates_handled,
            "last_poll_at": None if last_poll_at is None else last_poll_at.isoformat(),
            "last_success_at": (None if last_success_at is None else last_success_at.isoformat()),
            "last_error_code": last_error_code,
            "source": source,
        }

    @staticmethod
    def _validate_batch(
        request: TelegramPollRequest,
        updates: tuple[TelegramInboundUpdate, ...],
    ) -> None:
        if len(updates) > request.limit:
            raise TelegramPollBatchError("Telegram source exceeded the requested batch limit")
        update_ids = tuple(update.update_id for update in updates)
        if update_ids != tuple(sorted(set(update_ids))):
            raise TelegramPollBatchError(
                "Telegram source returned duplicate or out-of-order updates"
            )
        if any(update_id < request.offset for update_id in update_ids):
            raise TelegramPollBatchError("Telegram source returned an update below the offset")

    def _record_success(self, polled_at: datetime, updates_handled: int) -> None:
        with self._health_lock:
            self._cycles += 1
            self._updates_handled += updates_handled
            self._last_poll_at = polled_at
            self._last_success_at = polled_at
            self._last_error_code = None

    def _record_failure(self, polled_at: datetime, reason_code: QualifiedName) -> None:
        with self._health_lock:
            self._cycles += 1
            self._last_poll_at = polled_at
            self._last_error_code = reason_code

    def _require_poll_mode(self) -> GuardianMode:
        mode = self._guardian_reader.read_status().payload.mode
        if mode in {
            GuardianMode.OFFLINE,
            GuardianMode.READ_ONLY,
            GuardianMode.STOPPED,
            GuardianMode.RECOVERY,
        }:
            raise TelegramIngestionUnavailableError(
                f"Guardian mode does not permit Telegram polling: {mode.value}"
            )
        return mode


class TelegramDeliveryRouteResolver:
    """Resolve only the exact immutable active pairing named by a delivery action."""

    def __init__(
        self,
        *,
        adapter_id: QualifiedName,
        pairing_service: TelegramPairingService,
        adapter: ClientAdapter,
        external_destination: str,
        maximum_sensitivity: Sensitivity = Sensitivity.PERSONAL,
        estimated_cost_gbp: Decimal = Decimal("0"),
    ) -> None:
        self._adapter_id = adapter_id
        self._pairing_service = pairing_service
        self._adapter = adapter
        self._external_destination = external_destination
        self._allowed_sensitivities = sensitivity_scope(maximum_sensitivity)
        self._estimated_cost_gbp = estimated_cost_gbp

    def resolve(
        self,
        client_adapter: QualifiedName,
        destination_ref: str,
    ) -> ClientDeliveryRoute | None:
        if client_adapter != self._adapter_id:
            return None
        try:
            pairing_id = telegram_pairing_id_from_destination(destination_ref)
            self._pairing_service.pairing_for_delivery(pairing_id)
        except (TelegramPairingNotFoundError, ValueError):
            return None
        return ClientDeliveryRoute(
            adapter_id=self._adapter_id,
            destination_ref=destination_ref,
            external_destination=self._external_destination,
            purpose="conversation.owner_initiated_reply",
            adapter=self._adapter,
            allowed_sensitivities=self._allowed_sensitivities,
            estimated_cost_gbp=self._estimated_cost_gbp,
        )


class TelegramReplyDispatcher:
    """Route completed Telegram-triggered turns back to their exact source pairing."""

    def __init__(
        self,
        *,
        owner_id: RecordId,
        thread_id: RecordId,
        adapter_id: QualifiedName,
        conversation_store: ConversationStore,
        delivery_service: DeliveryService,
        delivery_store: DeliveryStore,
        receipt_store: TelegramPollStateStore,
    ) -> None:
        self._owner_id = owner_id
        self._thread_id = thread_id
        self._adapter_id = adapter_id
        self._conversation_store = conversation_store
        self._delivery_service = delivery_service
        self._delivery_store = delivery_store
        self._receipt_store = receipt_store
        self._lock = RLock()
        self._pending: dict[RecordId, RecordId] = {}
        self._recovery_after_update_id: TelegramUpdateId | None = None
        self._deliveries_submitted = 0
        self._last_error_code: QualifiedName | None = None

    def observe_poll_cycle(self, cycle: TelegramPollCycle) -> None:
        for outcome in cycle.outcomes:
            if outcome.receipt.disposition is not TelegramUpdateDisposition.INGESTED:
                continue
            canonical = outcome.canonical_message
            pairing_id = outcome.receipt.pairing_id
            if canonical is None or pairing_id is None:
                raise TelegramPollConflictError(
                    "ingested Telegram outcome lacks canonical pairing provenance"
                )
            self._remember_pending(canonical, pairing_id)

    def dispatch_ready(self, *, limit: int = 25) -> tuple[DeliveryWorkStatus, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("Telegram reply dispatch limit must be between 1 and 100")
        self._recover_ingested_receipts(limit=limit)
        with self._lock:
            pending = tuple(self._pending.items())[:limit]
        submitted: list[DeliveryWorkStatus] = []
        for triggering_message_id, pairing_id in pending:
            completed = self._conversation_store.completed_turn_for_trigger(
                triggering_message_id
            )
            if completed is None:
                processing = self._conversation_store.reply_processing(triggering_message_id)
                if processing.state is ConversationProcessingState.DEAD:
                    self._record_error("telegram.reply.processing_dead")
                continue
            output = completed.output_message
            destination_ref = telegram_pairing_destination(pairing_id)
            existing = tuple(
                status
                for status in self._delivery_store.find_by_message(output.message_id)
                if status.client_adapter == self._adapter_id
                and status.destination_ref == destination_ref
            )
            if existing:
                self._remove_pending(triggering_message_id, pairing_id)
                continue
            try:
                submission = self._delivery_service.enqueue_owner_initiated_reply(
                    triggering_message_id=triggering_message_id,
                    reply_message_id=output.message_id,
                    client_adapter=self._adapter_id,
                    destination_ref=destination_ref,
                    idempotency_key=f"telegram:reply:{output.message_id}",
                )
            except DeliveryUnavailableError as error:
                self._record_error(error.reason_code)
                continue
            submitted.append(submission.status)
            self._remove_pending(triggering_message_id, pairing_id)
            with self._lock:
                self._deliveries_submitted += 1
                self._last_error_code = None
        return tuple(submitted)

    def health(self) -> JsonObject:
        with self._lock:
            pending = len(self._pending)
            submitted = self._deliveries_submitted
            error_code = self._last_error_code
            recovery_after_update_id = self._recovery_after_update_id
        return {
            "state": "healthy" if error_code is None else "degraded",
            "reason_code": error_code or "telegram.reply.ready",
            "pending_replies": pending,
            "deliveries_submitted": submitted,
            "recovery_after_update_id": recovery_after_update_id,
            "last_error_code": error_code,
        }

    def _recover_ingested_receipts(self, *, limit: int) -> None:
        with self._lock:
            after_update_id = self._recovery_after_update_id
        receipts = self._receipt_store.list_ingested_receipts(
            self._adapter_id,
            after_update_id=after_update_id,
            limit=limit,
        )
        for receipt in receipts:
            if receipt.canonical_message_id is None or receipt.pairing_id is None:
                raise TelegramPollConflictError(
                    "ingested Telegram receipt lacks canonical pairing provenance"
                )
            canonical = self._conversation_store.get_message(receipt.canonical_message_id)
            self._remember_pending(canonical, receipt.pairing_id)
            with self._lock:
                self._recovery_after_update_id = receipt.update_id

    def _remember_pending(
        self,
        canonical: ConversationMessage,
        pairing_id: RecordId,
    ) -> None:
        if (
            canonical.thread_id != self._thread_id
            or canonical.author_principal_id != self._owner_id
            or canonical.source_client != self._adapter_id
        ):
            raise TelegramPollConflictError(
                "Telegram reply work escaped its configured owner channel"
            )
        with self._lock:
            existing = self._pending.setdefault(canonical.message_id, pairing_id)
            if existing != pairing_id:
                raise TelegramPollConflictError(
                    "Telegram canonical message changed pairing identity"
                )

    def _remove_pending(self, message_id: RecordId, pairing_id: RecordId) -> None:
        with self._lock:
            if self._pending.get(message_id) == pairing_id:
                del self._pending[message_id]

    def _record_error(self, reason_code: QualifiedName) -> None:
        with self._lock:
            self._last_error_code = reason_code
