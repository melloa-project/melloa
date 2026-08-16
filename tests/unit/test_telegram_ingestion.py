from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

import pytest

from melloa.adapters.fakes.conversation import InMemoryConversationStore
from melloa.adapters.fakes.guardian import FakeGuardianStatusReader
from melloa.adapters.fakes.telegram import (
    DeterministicTelegramPairingCodeIssuer,
    FakeTelegramPairingChallengePublisher,
    FakeTelegramUpdateSource,
    InMemoryTelegramAttachmentQuarantine,
    InMemoryTelegramPairingStateStore,
    InMemoryTelegramPollStateStore,
    RejectingTelegramAttachmentBackend,
    SyntheticTelegramAttachmentPayload,
)
from melloa.application.telegram import (
    TelegramIngestionOwnershipError,
    TelegramIngestionService,
    TelegramIngestionUnavailableError,
    TelegramPairingOwnershipError,
    TelegramPairingService,
    TelegramPairingUnavailableError,
    TelegramPollBatchError,
    TelegramPollWorker,
    telegram_inbound_idempotency_key,
)
from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import sha256_digest
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingState,
    ConversationReplyWork,
    ConversationThread,
    DeliveryState,
    MessageKind,
    MessagePart,
)
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.telegram import (
    TelegramAttachmentDisposition,
    TelegramAttachmentIntakeRequest,
    TelegramAttachmentKind,
    TelegramAttachmentReceipt,
    TelegramAttachmentReference,
    TelegramChatType,
    TelegramInboundMessage,
    TelegramInboundUpdate,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramUpdateDisposition,
)
from melloa.ports.auth import RecentAuthenticationRequired
from melloa.ports.conversation import ConversationConflictError
from melloa.ports.telegram import (
    TelegramAttachmentConflictError,
    TelegramPairingConflictError,
    TelegramPollConflictError,
    TransientTelegramAttachmentError,
    TransientTelegramPollingError,
)
from tests.conftest import record_id

ADAPTER_ID = "client.telegram.synthetic"
OWNER_ID = record_id("owner", 1)
THREAD_ID = record_id("thread", 1)


class CrashOncePollStateStore(InMemoryTelegramPollStateStore):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.crash_once = True

    def commit_ingestion(self, update, receipt, *, expected_revision):
        if self.crash_once:
            self.crash_once = False
            raise RuntimeError("synthetic crash after canonical acceptance")
        return super().commit_ingestion(
            update,
            receipt,
            expected_revision=expected_revision,
        )


class IncompleteReplayPollStateStore(InMemoryTelegramPollStateStore):
    hide_receipt = False

    def get_receipt(self, adapter_id, update_id):
        if self.hide_receipt:
            return None
        return super().get_receipt(adapter_id, update_id)


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class RecordingAttachmentBackend:
    def __init__(self, delegate: InMemoryTelegramAttachmentQuarantine) -> None:
        self.delegate = delegate
        self.results: list[tuple[TelegramAttachmentReceipt, ...]] = []

    @property
    def owner_id(self) -> str:
        return self.delegate.owner_id

    def handle(
        self,
        request: TelegramAttachmentIntakeRequest,
    ) -> tuple[TelegramAttachmentReceipt, ...]:
        result = self.delegate.handle(request)
        self.results.append(result)
        return result


class ReorderingAttachmentBackend:
    def __init__(self, fixed_time: datetime) -> None:
        self.delegate = RejectingTelegramAttachmentBackend(
            owner_id=OWNER_ID,
            clock=lambda: fixed_time + timedelta(minutes=4)
        )

    @property
    def owner_id(self) -> str:
        return self.delegate.owner_id

    def handle(
        self,
        request: TelegramAttachmentIntakeRequest,
    ) -> tuple[TelegramAttachmentReceipt, ...]:
        return tuple(reversed(self.delegate.handle(request)))


def sequential_id_factory():
    counts: defaultdict[str, int] = defaultdict(int)

    def create(prefix: str) -> str:
        counts[prefix] += 1
        return record_id(prefix, counts[prefix])

    return create


def guardian(
    fixed_time: datetime,
    mode: GuardianMode = GuardianMode.NO_ACTIONS,
) -> FakeGuardianStatusReader:
    return FakeGuardianStatusReader.from_payload(
        GuardianStatusPayload(
            instance_id="home-guardian",
            mode=mode,
            sequence=1,
            changed_at=fixed_time,
            reason_code="guardian.synthetic-test",
        ),
        receipt_hash="sha256:" + "1" * 64,
    )


def owner_pairing(
    fixed_time: datetime,
    *,
    owner_id: str = OWNER_ID,
    revoked: bool = False,
) -> TelegramOwnerPairing:
    confirmed_at = fixed_time + timedelta(minutes=1)
    return TelegramOwnerPairing(
        pairing_id=record_id("tgpairing", 1),
        candidate_id=record_id("tgcandidate", 1),
        owner_id=owner_id,
        telegram_user_id=1001,
        telegram_chat_id=1001,
        confirmed_by_owner_id=owner_id,
        confirmed_at=confirmed_at,
        revoked_at=confirmed_at + timedelta(minutes=1) if revoked else None,
    )


def configured_pairing_service(
    fixed_time: datetime,
    guardian_reader: FakeGuardianStatusReader,
    *,
    pairing: TelegramOwnerPairing | None,
    owner_id: str = OWNER_ID,
    id_factory=None,
    clock=None,
) -> tuple[
    TelegramPairingService,
    InMemoryTelegramPairingStateStore,
    FakeTelegramPairingChallengePublisher,
]:
    store = InMemoryTelegramPairingStateStore()
    issuer = DeterministicTelegramPairingCodeIssuer()
    publisher = FakeTelegramPairingChallengePublisher()
    effective_clock = clock or (lambda: fixed_time + timedelta(minutes=3))
    if pairing is not None:
        candidate = TelegramPairingCandidate(
            candidate_id=pairing.candidate_id,
            owner_id=pairing.owner_id,
            update_id=1,
            telegram_user_id=pairing.telegram_user_id,
            telegram_chat_id=pairing.telegram_chat_id,
            confirmation_code_hash=sha256_digest(
                issuer.issue(pairing.candidate_id).encode()
            ),
            observed_at=fixed_time,
            expires_at=fixed_time + timedelta(minutes=10),
        )
        store.create_candidate(ADAPTER_ID, candidate)
        active = pairing.model_copy(update={"revoked_at": None})
        store.confirm_pairing(ADAPTER_ID, candidate, active)
        if pairing.revoked_at is not None:
            store.revoke_pairing(ADAPTER_ID, pairing)
    return (
        TelegramPairingService(
            owner_id=owner_id,
            adapter_id=ADAPTER_ID,
            store=store,
            code_issuer=issuer,
            challenge_publisher=publisher,
            guardian_reader=guardian_reader,
            clock=effective_clock,
            id_factory=id_factory or sequential_id_factory(),
        ),
        store,
        publisher,
    )


def attachment(number: int = 1) -> TelegramAttachmentReference:
    return TelegramAttachmentReference(
        kind=TelegramAttachmentKind.DOCUMENT,
        file_id=f"synthetic-file-{number}",
        file_unique_id=f"synthetic-unique-{number}",
        declared_size_bytes=128,
        media_type="text/plain",
        file_name=f"attachment-{number}.txt",
    )


def attachment_payload(number: int) -> SyntheticTelegramAttachmentPayload:
    content = f"synthetic-safe-attachment-{number}".encode().ljust(128, b".")
    return SyntheticTelegramAttachmentPayload(content=content, media_type="text/plain")


def quarantine_backend(
    fixed_time: datetime,
    *numbers: int,
) -> InMemoryTelegramAttachmentQuarantine:
    return InMemoryTelegramAttachmentQuarantine(
        {
            f"synthetic-unique-{number}": attachment_payload(number)
            for number in numbers
        },
        owner_id=OWNER_ID,
        allowed_kinds=frozenset({TelegramAttachmentKind.DOCUMENT}),
        allowed_media_types=frozenset({"text/plain"}),
        max_attachment_bytes=1_024,
        max_quarantine_bytes=4_096,
        clock=lambda: fixed_time + timedelta(minutes=4),
    )


def inbound_update(
    fixed_time: datetime,
    *,
    update_id: int = 10,
    text: str | None = "Hello from Telegram",
    attachments: tuple[TelegramAttachmentReference, ...] = (),
    sender_user_id: int = 1001,
    chat_id: int = 1001,
    chat_type: TelegramChatType = TelegramChatType.PRIVATE,
    sent_at: datetime | None = None,
) -> TelegramInboundUpdate:
    effective_sent_at = sent_at or fixed_time + timedelta(minutes=2)
    return TelegramInboundUpdate(
        update_id=update_id,
        message=TelegramInboundMessage(
            telegram_message_id=update_id + 1,
            sender_user_id=sender_user_id,
            chat_id=chat_id,
            chat_type=chat_type,
            sent_at=effective_sent_at,
            text=text,
            attachments=attachments,
        ),
        received_at=effective_sent_at + timedelta(seconds=5),
        raw_size_bytes=256,
        source_payload_hash=sha256_digest(
            f"{update_id}:{sender_user_id}:{chat_id}:{text}".encode()
        ),
    )


def ingestion_fixture(
    fixed_time: datetime,
    *,
    mode: GuardianMode = GuardianMode.NO_ACTIONS,
    pairing: TelegramOwnerPairing | None = None,
    paired: bool = True,
    thread_owner_id: str = OWNER_ID,
    poll_store: InMemoryTelegramPollStateStore | None = None,
    guardian_reader: FakeGuardianStatusReader | None = None,
    pairing_service_override: TelegramPairingService | None = None,
    attachment_backend=None,
    clock=None,
) -> tuple[
    TelegramIngestionService,
    InMemoryConversationStore,
    InMemoryTelegramPollStateStore,
    ConversationThread,
]:
    conversation_store = InMemoryConversationStore()
    thread = ConversationThread(
        thread_id=THREAD_ID,
        owner_id=thread_owner_id,
        intelligence_id=record_id("intelligence", 1),
        title="Telegram intake",
        sensitivity=Sensitivity.PERSONAL,
        retention_policy="retention.owner-conversation",
        created_at=fixed_time,
        updated_at=fixed_time,
    )
    conversation_store.create_thread(thread)
    effective_poll_store = poll_store or InMemoryTelegramPollStateStore(
        adapter_id=ADAPTER_ID,
        clock=lambda: fixed_time,
    )
    effective_guardian = guardian_reader or guardian(fixed_time, mode)
    effective_clock = clock or (lambda: fixed_time + timedelta(minutes=3))
    effective_pairing = (pairing or owner_pairing(fixed_time)) if paired else None
    pairing_owner_id = OWNER_ID if effective_pairing is None else effective_pairing.owner_id
    if pairing_service_override is None:
        pairing_service, _pairing_store, _publisher = configured_pairing_service(
            fixed_time,
            effective_guardian,
            pairing=effective_pairing,
            owner_id=pairing_owner_id,
            clock=effective_clock,
        )
    else:
        pairing_service = pairing_service_override
    effective_attachment_backend = attachment_backend or RejectingTelegramAttachmentBackend(
        owner_id=OWNER_ID,
        clock=effective_clock
    )
    service = TelegramIngestionService(
        owner_id=OWNER_ID,
        thread_id=THREAD_ID,
        adapter_id=ADAPTER_ID,
        pairing_service=pairing_service,
        attachment_backend=effective_attachment_backend,
        conversation_store=conversation_store,
        poll_state_store=effective_poll_store,
        guardian_reader=effective_guardian,
        clock=effective_clock,
        id_factory=sequential_id_factory(),
        max_processing_attempts=4,
    )
    return service, conversation_store, effective_poll_store, thread


def owner_principal(
    fixed_time: datetime,
    *,
    owner_id: str = OWNER_ID,
    recent_until: datetime | None = None,
) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=owner_id,
        session_id=record_id("session", 1),
        authentication_method="auth.synthetic-opaque-token",
        authenticated_at=fixed_time,
        reauthenticated_until=recent_until or fixed_time + timedelta(minutes=5),
        expires_at=fixed_time + timedelta(minutes=30),
    )


@pytest.mark.parametrize("mode", [GuardianMode.NORMAL, GuardianMode.NO_ACTIONS])
def test_paired_text_becomes_one_channel_neutral_canonical_message(
    fixed_time: datetime,
    mode: GuardianMode,
) -> None:
    service, store, poll_store, thread = ingestion_fixture(fixed_time, mode=mode)
    update = inbound_update(fixed_time)

    result = service.ingest(update, expected_revision=0)

    message = result.canonical_message
    assert message is not None
    assert result.canonical_created is True
    assert result.receipt_replayed is False
    assert message.thread_id == thread.thread_id
    assert message.author_principal_id == OWNER_ID
    assert message.source_client == ADAPTER_ID
    assert message.parts == (MessagePart(kind=MessageKind.TEXT, text=update.message.text),)
    assert message.sensitivity is thread.sensitivity
    assert message.created_at == update.received_at
    assert message.observed_at == update.message.sent_at
    assert result.receipt.disposition is TelegramUpdateDisposition.INGESTED
    assert result.receipt.canonical_message_id == message.message_id
    assert result.receipt.pairing_id == record_id("tgpairing", 1)
    assert result.poll_state.next_offset == update.update_id + 1
    assert poll_store.get_update(ADAPTER_ID, update.update_id) == update
    assert (
        store.get_inbound_by_idempotency_key(
            THREAD_ID,
            telegram_inbound_idempotency_key(ADAPTER_ID, update.update_id),
        )
        == message
    )
    processing = store.reply_processing(message.message_id)
    assert processing.state is ConversationProcessingState.READY
    assert processing.max_attempts == 4


def test_text_survives_only_after_every_attachment_is_rejected_before_fetch(
    fixed_time: datetime,
) -> None:
    service, store, _poll_store, _thread = ingestion_fixture(fixed_time)
    update = inbound_update(
        fixed_time,
        text="Use the text only",
        attachments=(attachment(1), attachment(2)),
    )

    result = service.ingest(update, expected_revision=0)

    assert result.receipt.disposition is TelegramUpdateDisposition.INGESTED
    assert tuple(item.disposition for item in result.receipt.attachment_receipts) == (
        TelegramAttachmentDisposition.REJECTED,
        TelegramAttachmentDisposition.REJECTED,
    )
    assert all(
        item.reason_code == "telegram.attachment.unsupported"
        and item.quarantine_blob_id is None
        and item.content_hash is None
        for item in result.receipt.attachment_receipts
    )
    assert result.canonical_message is not None
    assert result.canonical_message.parts == (
        MessagePart(kind=MessageKind.TEXT, text="Use the text only"),
    )
    assert len(store.list_messages(THREAD_ID)) == 1


def test_text_and_quarantined_attachments_become_ordered_canonical_parts(
    fixed_time: datetime,
) -> None:
    backend = quarantine_backend(fixed_time, 1, 2)
    service, store, _poll_store, _thread = ingestion_fixture(
        fixed_time,
        attachment_backend=backend,
    )
    update = inbound_update(
        fixed_time,
        text="Keep these quarantined",
        attachments=(attachment(1), attachment(2)),
    )

    result = service.ingest(update, expected_revision=0)

    receipts = result.receipt.attachment_receipts
    assert tuple(item.file_unique_id for item in receipts) == (
        "synthetic-unique-1",
        "synthetic-unique-2",
    )
    assert all(
        item.disposition is TelegramAttachmentDisposition.QUARANTINED
        for item in receipts
    )
    assert result.canonical_message is not None
    assert result.canonical_message.parts == (
        MessagePart(kind=MessageKind.TEXT, text="Keep these quarantined"),
        *(
            MessagePart(
                kind=MessageKind.ATTACHMENT,
                attachment_id=item.quarantine_blob_id,
                media_type=item.media_type,
                content_hash=item.content_hash,
            )
            for item in receipts
        ),
    )
    assert backend.fetched_file_unique_ids == [
        "synthetic-unique-1",
        "synthetic-unique-2",
    ]
    assert len(store.list_messages(THREAD_ID)) == 1

    replay = service.ingest(update, expected_revision=0)

    assert replay.receipt == result.receipt
    assert replay.canonical_message == result.canonical_message
    assert replay.receipt_replayed is True
    assert len(backend.requests) == 1
    assert backend.fetched_file_unique_ids == [
        "synthetic-unique-1",
        "synthetic-unique-2",
    ]


def test_attachment_only_quarantine_becomes_canonical_reply_work(
    fixed_time: datetime,
) -> None:
    backend = quarantine_backend(fixed_time, 1)
    service, store, _poll_store, _thread = ingestion_fixture(
        fixed_time,
        attachment_backend=backend,
    )
    update = inbound_update(fixed_time, text=None, attachments=(attachment(1),))

    result = service.ingest(update, expected_revision=0)

    assert result.receipt.disposition is TelegramUpdateDisposition.INGESTED
    assert result.canonical_message is not None
    receipt = result.receipt.attachment_receipts[0]
    assert result.canonical_message.parts == (
        MessagePart(
            kind=MessageKind.ATTACHMENT,
            attachment_id=receipt.quarantine_blob_id,
            media_type=receipt.media_type,
            content_hash=receipt.content_hash,
        ),
    )
    processing = store.reply_processing(result.canonical_message.message_id)
    assert processing.state is ConversationProcessingState.READY
    assert processing.attempt_count == 0


def test_attachment_only_update_is_rejected_and_advances_after_durable_receipt(
    fixed_time: datetime,
) -> None:
    service, store, poll_store, _thread = ingestion_fixture(fixed_time)
    update = inbound_update(fixed_time, text=None, attachments=(attachment(),))

    result = service.ingest(update, expected_revision=0)

    assert result.canonical_message is None
    assert result.receipt.disposition is TelegramUpdateDisposition.REJECTED
    assert result.receipt.reason_code == "telegram.attachment_only_unsupported"
    assert result.receipt.attachment_receipts[0].disposition is (
        TelegramAttachmentDisposition.REJECTED
    )
    assert store.list_messages(THREAD_ID) == ()
    assert poll_store.read_state(ADAPTER_ID).next_offset == update.update_id + 1

    replay = service.ingest(update, expected_revision=0)
    assert replay.receipt == result.receipt
    assert replay.receipt_replayed is True


@pytest.mark.parametrize(
    ("paired", "update_kwargs"),
    [
        (False, {}),
        (True, {"sender_user_id": 2002}),
        (True, {"chat_id": 2002}),
    ],
)
def test_unauthorized_attachment_sources_never_reach_quarantine_backend(
    fixed_time: datetime,
    paired: bool,
    update_kwargs: dict[str, object],
) -> None:
    backend = quarantine_backend(fixed_time, 1)
    service, store, _poll_store, _thread = ingestion_fixture(
        fixed_time,
        paired=paired,
        attachment_backend=backend,
    )
    update = inbound_update(
        fixed_time,
        attachments=(attachment(1),),
        **update_kwargs,
    )

    result = service.ingest(update, expected_revision=0)

    assert result.receipt.disposition is TelegramUpdateDisposition.REJECTED
    assert result.receipt.attachment_receipts[0].reason_code == (
        "telegram.attachment.source_not_authorized"
    )
    assert backend.requests == []
    assert backend.fetched_file_unique_ids == []
    assert backend.stored_blob_ids == ()
    assert store.list_messages(THREAD_ID) == ()


def test_transient_attachment_failure_leaves_canonical_and_cursor_state_unchanged(
    fixed_time: datetime,
) -> None:
    backend = quarantine_backend(fixed_time)
    service, store, poll_store, _thread = ingestion_fixture(
        fixed_time,
        attachment_backend=backend,
    )
    update = inbound_update(fixed_time, attachments=(attachment(1),))
    state_before = poll_store.read_state(ADAPTER_ID)

    with pytest.raises(TransientTelegramAttachmentError) as failure:
        service.ingest(update, expected_revision=0)

    assert failure.value.reason_code == "telegram.attachment.fetch_unavailable"
    assert store.list_messages(THREAD_ID) == ()
    assert poll_store.read_state(ADAPTER_ID) == state_before
    assert poll_store.get_update(ADAPTER_ID, update.update_id) is None
    assert poll_store.get_receipt(ADAPTER_ID, update.update_id) is None
    assert backend.fetched_file_unique_ids == ["synthetic-unique-1"]
    assert backend.stored_blob_ids == ()


def test_invalid_attachment_backend_order_fails_before_any_durable_mutation(
    fixed_time: datetime,
) -> None:
    backend = ReorderingAttachmentBackend(fixed_time)
    service, store, poll_store, _thread = ingestion_fixture(
        fixed_time,
        attachment_backend=backend,
    )
    update = inbound_update(
        fixed_time,
        attachments=(attachment(1), attachment(2)),
    )

    with pytest.raises(TelegramAttachmentConflictError, match="invalid outcome"):
        service.ingest(update, expected_revision=0)

    assert len(backend.delegate.requests) == 1
    assert store.list_messages(THREAD_ID) == ()
    assert poll_store.read_state(ADAPTER_ID).revision == 0
    assert poll_store.get_receipt(ADAPTER_ID, update.update_id) is None


@pytest.mark.parametrize(
    ("update_kwargs", "revoked"),
    [
        ({"sender_user_id": 2002}, False),
        ({"chat_id": 2002}, False),
        ({"chat_id": -1001, "chat_type": TelegramChatType.GROUP}, False),
        ({}, True),
    ],
)
def test_unpaired_or_revoked_sources_are_recorded_as_rejections(
    fixed_time: datetime,
    update_kwargs: dict[str, object],
    revoked: bool,
) -> None:
    service, store, _poll_store, _thread = ingestion_fixture(
        fixed_time,
        pairing=owner_pairing(fixed_time, revoked=revoked),
    )
    update = inbound_update(fixed_time, **update_kwargs)

    result = service.ingest(update, expected_revision=0)

    assert result.receipt.disposition is TelegramUpdateDisposition.REJECTED
    assert result.receipt.reason_code == (
        "telegram.owner_not_paired" if revoked else "telegram.owner_pairing_mismatch"
    )
    assert result.canonical_message is None
    assert store.list_messages(THREAD_ID) == ()


@pytest.mark.parametrize(
    "mode",
    [
        GuardianMode.OFFLINE,
        GuardianMode.READ_ONLY,
        GuardianMode.STOPPED,
        GuardianMode.RECOVERY,
    ],
)
def test_guardian_modes_forbid_poll_state_and_conversation_mutation(
    fixed_time: datetime,
    mode: GuardianMode,
) -> None:
    service, store, poll_store, _thread = ingestion_fixture(fixed_time, mode=mode)

    with pytest.raises(TelegramIngestionUnavailableError, match=mode.value):
        service.ingest(inbound_update(fixed_time), expected_revision=0)

    assert store.list_messages(THREAD_ID) == ()
    assert poll_store.read_state(ADAPTER_ID).revision == 0


def test_exact_receipt_replay_does_not_duplicate_message_or_work(fixed_time: datetime) -> None:
    service, store, poll_store, _thread = ingestion_fixture(fixed_time)
    update = inbound_update(fixed_time)
    first = service.ingest(update, expected_revision=0)

    replay = service.ingest(update, expected_revision=0)

    assert replay.receipt == first.receipt
    assert replay.canonical_message == first.canonical_message
    assert replay.canonical_created is False
    assert replay.receipt_replayed is True
    assert replay.poll_state == first.poll_state
    assert len(store.list_messages(THREAD_ID)) == 1
    assert len(store.list_reply_processing(THREAD_ID)) == 1
    assert poll_store.read_state(ADAPTER_ID).revision == 1

    changed = inbound_update(fixed_time, text="Changed replay")
    with pytest.raises(TelegramPollConflictError, match="different content"):
        service.ingest(changed, expected_revision=1)


def test_crash_after_canonical_append_replays_without_duplicate_message_or_work(
    fixed_time: datetime,
) -> None:
    poll_store = CrashOncePollStateStore(
        adapter_id=ADAPTER_ID,
        clock=lambda: fixed_time,
    )
    service, store, _poll_store, _thread = ingestion_fixture(
        fixed_time,
        poll_store=poll_store,
    )
    update = inbound_update(fixed_time)

    with pytest.raises(RuntimeError, match="after canonical acceptance"):
        service.ingest(update, expected_revision=0)

    accepted = store.list_messages(THREAD_ID)
    assert len(accepted) == 1
    assert len(store.list_reply_processing(THREAD_ID)) == 1
    assert poll_store.read_state(ADAPTER_ID).revision == 0
    assert poll_store.get_receipt(ADAPTER_ID, update.update_id) is None

    recovered = service.ingest(update, expected_revision=0)

    assert recovered.canonical_message == accepted[0]
    assert recovered.canonical_created is False
    assert recovered.receipt_replayed is False
    assert poll_store.read_state(ADAPTER_ID).next_offset == update.update_id + 1
    assert len(store.list_messages(THREAD_ID)) == 1
    assert len(store.list_reply_processing(THREAD_ID)) == 1


def test_crash_reuses_exact_quarantine_receipt_without_refetching(
    fixed_time: datetime,
) -> None:
    poll_store = CrashOncePollStateStore(
        adapter_id=ADAPTER_ID,
        clock=lambda: fixed_time,
    )
    delegate = quarantine_backend(fixed_time, 1)
    backend = RecordingAttachmentBackend(delegate)
    service, store, _poll_store, _thread = ingestion_fixture(
        fixed_time,
        poll_store=poll_store,
        attachment_backend=backend,
    )
    update = inbound_update(fixed_time, text=None, attachments=(attachment(1),))

    with pytest.raises(RuntimeError, match="after canonical acceptance"):
        service.ingest(update, expected_revision=0)

    assert len(backend.results) == 1
    assert delegate.fetched_file_unique_ids == ["synthetic-unique-1"]
    assert len(delegate.stored_blob_ids) == 1
    accepted = store.list_messages(THREAD_ID)
    assert len(accepted) == 1
    assert poll_store.read_state(ADAPTER_ID).revision == 0

    recovered = service.ingest(update, expected_revision=0)

    assert backend.results == [backend.results[0], backend.results[0]]
    assert recovered.receipt.attachment_receipts == backend.results[0]
    assert recovered.canonical_message == accepted[0]
    assert recovered.canonical_created is False
    assert recovered.receipt_replayed is False
    assert delegate.requests == [delegate.requests[0], delegate.requests[0]]
    assert delegate.fetched_file_unique_ids == ["synthetic-unique-1"]
    assert poll_store.read_state(ADAPTER_ID).next_offset == update.update_id + 1
    assert poll_store.get_receipt(ADAPTER_ID, update.update_id) == recovered.receipt
    assert len(store.list_messages(THREAD_ID)) == 1
    assert len(store.list_reply_processing(THREAD_ID)) == 1


def test_stale_writer_and_foreign_thread_fail_before_canonical_acceptance(
    fixed_time: datetime,
) -> None:
    service, store, poll_store, _thread = ingestion_fixture(fixed_time)
    update = inbound_update(fixed_time)

    with pytest.raises(TelegramPollConflictError, match="revision is stale"):
        service.ingest(update, expected_revision=1)
    assert store.list_messages(THREAD_ID) == ()
    assert poll_store.read_state(ADAPTER_ID).revision == 0

    foreign_service, foreign_store, foreign_poll_store, _foreign_thread = ingestion_fixture(
        fixed_time,
        thread_owner_id=record_id("owner", 2),
    )
    with pytest.raises(TelegramIngestionOwnershipError, match="thread"):
        foreign_service.ingest(update, expected_revision=0)
    assert foreign_store.list_messages(THREAD_ID) == ()
    assert foreign_poll_store.read_state(ADAPTER_ID).revision == 0


def test_ingestion_rejects_attachment_backend_from_another_owner(
    fixed_time: datetime,
) -> None:
    backend = RejectingTelegramAttachmentBackend(
        owner_id=record_id("owner", 2),
        clock=lambda: fixed_time,
    )

    with pytest.raises(TelegramIngestionOwnershipError, match="attachment backend"):
        ingestion_fixture(fixed_time, attachment_backend=backend)


def test_invalid_revision_offset_and_incomplete_replay_state_fail_closed(
    fixed_time: datetime,
) -> None:
    poll_store = IncompleteReplayPollStateStore(
        adapter_id=ADAPTER_ID,
        clock=lambda: fixed_time,
    )
    service, store, _poll_store, _thread = ingestion_fixture(
        fixed_time,
        poll_store=poll_store,
    )

    with pytest.raises(ValueError, match="cannot be negative"):
        service.ingest(inbound_update(fixed_time), expected_revision=-1)

    accepted = service.ingest(inbound_update(fixed_time, update_id=10), expected_revision=0)
    assert accepted.poll_state.revision == 1
    with pytest.raises(TelegramPollConflictError, match="move backwards"):
        service.ingest(inbound_update(fixed_time, update_id=9), expected_revision=1)
    assert len(store.list_messages(THREAD_ID)) == 1

    poll_store.hide_receipt = True
    with pytest.raises(TelegramPollConflictError, match="incomplete"):
        service.ingest(inbound_update(fixed_time, update_id=10), expected_revision=1)


def test_pairing_and_canonical_idempotency_cannot_cross_owner_or_source(
    fixed_time: datetime,
) -> None:
    with pytest.raises(TelegramIngestionOwnershipError, match="pairing"):
        ingestion_fixture(
            fixed_time,
            pairing=owner_pairing(fixed_time, owner_id=record_id("owner", 2)),
        )

    service, store, poll_store, thread = ingestion_fixture(fixed_time)
    update = inbound_update(fixed_time)
    conflicting = ConversationMessage(
        message_id=record_id("message", 99),
        thread_id=THREAD_ID,
        author_principal_id=OWNER_ID,
        source_client="client.owner-console",
        parts=(MessagePart(kind=MessageKind.TEXT, text=update.message.text),),
        delivery_state=DeliveryState.DELIVERED,
        sensitivity=thread.sensitivity,
        created_at=update.received_at,
        observed_at=update.message.sent_at,
    )
    store.append_inbound(
        conflicting,
        telegram_inbound_idempotency_key(ADAPTER_ID, update.update_id),
        ConversationReplyWork(
            work_id=record_id("work", 99),
            thread_id=THREAD_ID,
            message_id=conflicting.message_id,
            created_at=conflicting.created_at,
        ),
        max_attempts=3,
    )

    with pytest.raises(ConversationConflictError, match="canonical content"):
        service.ingest(update, expected_revision=0)

    assert store.list_messages(THREAD_ID) == (conflicting,)
    assert poll_store.read_state(ADAPTER_ID).revision == 0


def test_private_start_requires_local_recent_auth_confirmation_before_ingestion(
    fixed_time: datetime,
) -> None:
    guardian_reader = guardian(fixed_time, GuardianMode.NORMAL)
    clock = MutableClock(fixed_time + timedelta(minutes=3))
    pairing_service, pairing_store, publisher = configured_pairing_service(
        fixed_time,
        guardian_reader,
        pairing=None,
        clock=clock,
    )
    service, conversation_store, poll_store, _thread = ingestion_fixture(
        fixed_time,
        paired=False,
        guardian_reader=guardian_reader,
        pairing_service_override=pairing_service,
        clock=clock,
    )
    start = inbound_update(fixed_time, update_id=10, text="/start")

    candidate_result = service.ingest(start, expected_revision=0)

    assert candidate_result.receipt.disposition is (
        TelegramUpdateDisposition.PAIRING_CANDIDATE
    )
    candidate_id = candidate_result.receipt.pairing_candidate_id
    assert candidate_id is not None
    assert candidate_result.canonical_message is None
    assert conversation_store.list_messages(THREAD_ID) == ()
    challenge = publisher.challenge_for(candidate_id)
    assert challenge.candidate.confirmation_code_hash == sha256_digest(
        challenge.confirmation_code.encode()
    )
    assert challenge.confirmation_code not in repr(challenge)
    principal = owner_principal(
        fixed_time,
        recent_until=fixed_time + timedelta(minutes=10),
    )
    assert pairing_service.pending_candidates(principal) == (challenge.candidate,)

    with pytest.raises(TelegramPairingConflictError, match="code is invalid"):
        pairing_service.confirm(principal, candidate_id, "wrong-code-with-enough-length")
    assert pairing_service.pairing_for_ingestion() is None

    pairing = pairing_service.confirm(
        principal,
        candidate_id,
        challenge.confirmation_code,
    )
    assert pairing.owner_id == OWNER_ID
    assert pairing.telegram_user_id == start.message.sender_user_id
    assert pairing.telegram_chat_id == start.message.chat_id
    assert pairing.confirmed_by_owner_id == OWNER_ID
    assert pairing_service.confirm(
        principal,
        candidate_id,
        challenge.confirmation_code,
    ) == pairing
    assert pairing_service.pending_candidates(principal) == ()
    assert pairing_store.active_pairing(ADAPTER_ID, OWNER_ID) == pairing

    clock.now = fixed_time + timedelta(minutes=5)
    message_update = inbound_update(
        fixed_time,
        update_id=11,
        text="Accepted only after local confirmation",
        sent_at=fixed_time + timedelta(minutes=4),
    )
    accepted = service.ingest(message_update, expected_revision=1)
    assert accepted.receipt.disposition is TelegramUpdateDisposition.INGESTED
    assert accepted.canonical_message is not None
    assert poll_store.read_state(ADAPTER_ID).next_offset == 12

    revoked = pairing_service.revoke(principal, pairing.pairing_id)
    assert revoked.revoked_at == fixed_time + timedelta(minutes=5)
    assert pairing_store.active_pairing(ADAPTER_ID, OWNER_ID) is None
    after_revoke = service.ingest(
        inbound_update(
            fixed_time,
            update_id=12,
            text="Must not pass after revocation",
            sent_at=fixed_time + timedelta(minutes=4),
        ),
        expected_revision=2,
    )
    assert after_revoke.receipt.disposition is TelegramUpdateDisposition.REJECTED
    assert after_revoke.receipt.reason_code == "telegram.owner_not_paired"
    with pytest.raises(TelegramPairingConflictError, match="already consumed"):
        pairing_service.confirm(
            principal,
            candidate_id,
            challenge.confirmation_code,
        )


def test_pairing_candidate_and_challenge_replay_after_cursor_commit_crash(
    fixed_time: datetime,
) -> None:
    guardian_reader = guardian(fixed_time, GuardianMode.NORMAL)
    pairing_service, pairing_store, publisher = configured_pairing_service(
        fixed_time,
        guardian_reader,
        pairing=None,
    )
    poll_store = CrashOncePollStateStore(
        adapter_id=ADAPTER_ID,
        clock=lambda: fixed_time,
    )
    service, conversation_store, _poll_store, _thread = ingestion_fixture(
        fixed_time,
        paired=False,
        guardian_reader=guardian_reader,
        poll_store=poll_store,
        pairing_service_override=pairing_service,
    )
    start = inbound_update(fixed_time, update_id=20, text="/start")

    with pytest.raises(RuntimeError, match="after canonical acceptance"):
        service.ingest(start, expected_revision=0)

    candidates = pairing_store.list_candidates(ADAPTER_ID, OWNER_ID)
    assert len(candidates) == 1
    assert len(publisher.published) == 1
    assert conversation_store.list_messages(THREAD_ID) == ()
    assert poll_store.read_state(ADAPTER_ID).revision == 0

    recovered = service.ingest(start, expected_revision=0)
    assert recovered.receipt.disposition is TelegramUpdateDisposition.PAIRING_CANDIDATE
    assert recovered.receipt.pairing_candidate_id == candidates[0].candidate_id
    assert len(publisher.published) == 1
    assert poll_store.read_state(ADAPTER_ID).next_offset == 21


def test_pairing_confirmation_requires_owner_recent_auth_and_permitted_guardian(
    fixed_time: datetime,
) -> None:
    guardian_reader = guardian(fixed_time, GuardianMode.NORMAL)
    pairing_service, store, publisher = configured_pairing_service(
        fixed_time,
        guardian_reader,
        pairing=None,
    )
    candidate = pairing_service.begin_candidate(
        inbound_update(fixed_time, update_id=30, text="/start")
    )
    code = publisher.challenge_for(candidate.candidate_id).confirmation_code

    with pytest.raises(TelegramPairingOwnershipError):
        pairing_service.pending_candidates(
            owner_principal(fixed_time, owner_id=record_id("owner", 2))
        )
    with pytest.raises(RecentAuthenticationRequired):
        pairing_service.confirm(
            owner_principal(
                fixed_time,
                recent_until=fixed_time + timedelta(minutes=3),
            ),
            candidate.candidate_id,
            code,
        )

    read_only_service = TelegramPairingService(
        owner_id=OWNER_ID,
        adapter_id=ADAPTER_ID,
        store=store,
        code_issuer=DeterministicTelegramPairingCodeIssuer(),
        challenge_publisher=publisher,
        guardian_reader=guardian(fixed_time, GuardianMode.READ_ONLY),
        clock=lambda: fixed_time + timedelta(minutes=3),
        id_factory=sequential_id_factory(),
    )
    with pytest.raises(TelegramPairingUnavailableError, match="read-only"):
        read_only_service.confirm(
            owner_principal(fixed_time),
            candidate.candidate_id,
            code,
        )

    pairing = pairing_service.confirm(
        owner_principal(fixed_time),
        candidate.candidate_id,
        code,
    )
    assert read_only_service.revoke(
        owner_principal(fixed_time),
        pairing.pairing_id,
    ).revoked_at == fixed_time + timedelta(minutes=3)


def test_no_actions_forbids_pairing_challenge_publication(
    fixed_time: datetime,
) -> None:
    pairing_service, store, publisher = configured_pairing_service(
        fixed_time,
        guardian(fixed_time, GuardianMode.NO_ACTIONS),
        pairing=None,
    )

    with pytest.raises(TelegramPairingUnavailableError, match="no-actions"):
        pairing_service.begin_candidate(
            inbound_update(fixed_time, update_id=31, text="/start")
        )

    assert store.list_candidates(ADAPTER_ID, OWNER_ID) == ()
    assert publisher.published == []


def test_no_actions_forbids_pairing_confirmation(fixed_time: datetime) -> None:
    pairing_service, store, publisher = configured_pairing_service(
        fixed_time,
        guardian(fixed_time, GuardianMode.NORMAL),
        pairing=None,
    )
    candidate = pairing_service.begin_candidate(
        inbound_update(fixed_time, update_id=32, text="/start")
    )
    challenge = publisher.challenge_for(candidate.candidate_id)
    no_actions_service = TelegramPairingService(
        owner_id=OWNER_ID,
        adapter_id=ADAPTER_ID,
        store=store,
        code_issuer=DeterministicTelegramPairingCodeIssuer(),
        challenge_publisher=publisher,
        guardian_reader=guardian(fixed_time, GuardianMode.NO_ACTIONS),
        clock=lambda: fixed_time + timedelta(minutes=3),
        id_factory=sequential_id_factory(),
    )

    with pytest.raises(TelegramPairingUnavailableError, match="no-actions"):
        no_actions_service.confirm(
            owner_principal(fixed_time),
            candidate.candidate_id,
            challenge.confirmation_code,
        )

    assert store.active_pairing(ADAPTER_ID, OWNER_ID) is None


def test_invalid_unpaired_start_is_rejected_without_challenge_or_canonical_write(
    fixed_time: datetime,
) -> None:
    guardian_reader = guardian(fixed_time, GuardianMode.NORMAL)
    pairing_service, _store, publisher = configured_pairing_service(
        fixed_time,
        guardian_reader,
        pairing=None,
    )
    service, conversation_store, _poll_store, _thread = ingestion_fixture(
        fixed_time,
        paired=False,
        guardian_reader=guardian_reader,
        pairing_service_override=pairing_service,
    )
    invalid_start = inbound_update(
        fixed_time,
        update_id=40,
        text="/start",
        chat_id=-1001,
        chat_type=TelegramChatType.GROUP,
    )

    result = service.ingest(invalid_start, expected_revision=0)

    assert result.receipt.disposition is TelegramUpdateDisposition.REJECTED
    assert result.receipt.reason_code == "telegram.pairing_candidate_invalid"
    assert publisher.published == []
    assert conversation_store.list_messages(THREAD_ID) == ()


def test_bounded_poll_worker_ingests_ordered_updates_and_reports_health(
    fixed_time: datetime,
) -> None:
    guardian_reader = guardian(fixed_time)
    service, store, poll_store, _thread = ingestion_fixture(
        fixed_time,
        guardian_reader=guardian_reader,
    )
    source = FakeTelegramUpdateSource(
        (
            inbound_update(fixed_time, update_id=10, text="First"),
            inbound_update(fixed_time, update_id=12, text="Second"),
        ),
        adapter_id=ADAPTER_ID,
    )
    worker = TelegramPollWorker(
        adapter_id=ADAPTER_ID,
        source=source,
        poll_state_store=poll_store,
        ingestion_service=service,
        guardian_reader=guardian_reader,
        timeout_seconds=7,
        batch_limit=2,
        clock=lambda: fixed_time + timedelta(minutes=3),
    )

    cycle = worker.poll_once()

    assert cycle.request.offset == 0
    assert cycle.request.timeout_seconds == 7
    assert cycle.request.limit == 2
    assert tuple(outcome.receipt.update_id for outcome in cycle.outcomes) == (10, 12)
    assert cycle.state_before.revision == 0
    assert cycle.state_after.revision == 2
    assert cycle.state_after.next_offset == 13
    assert len(store.list_messages(THREAD_ID)) == 2
    assert len(store.list_reply_processing(THREAD_ID)) == 2

    empty = worker.poll_once()
    assert empty.request.offset == 13
    assert empty.outcomes == ()
    assert empty.state_after == cycle.state_after
    health = worker.health()
    assert health["state"] == "healthy"
    assert health["reason_code"] == "telegram.worker.ready"
    assert health["cycles"] == 2
    assert health["updates_handled"] == 2
    assert health["next_offset"] == 13
    assert health["timeout_seconds"] == 7
    assert health["batch_limit"] == 2
    assert health["source"] == source.health()


def test_source_outage_leaves_cursor_and_conversation_unchanged_then_recovers(
    fixed_time: datetime,
) -> None:
    guardian_reader = guardian(fixed_time)
    service, store, poll_store, _thread = ingestion_fixture(
        fixed_time,
        guardian_reader=guardian_reader,
    )
    source = FakeTelegramUpdateSource(
        (inbound_update(fixed_time),),
        adapter_id=ADAPTER_ID,
        failure_codes=("telegram.synthetic.unavailable",),
    )
    worker = TelegramPollWorker(
        adapter_id=ADAPTER_ID,
        source=source,
        poll_state_store=poll_store,
        ingestion_service=service,
        guardian_reader=guardian_reader,
        clock=lambda: fixed_time + timedelta(minutes=3),
    )

    with pytest.raises(TransientTelegramPollingError) as failure:
        worker.poll_once()
    assert failure.value.reason_code == "telegram.synthetic.unavailable"
    assert poll_store.read_state(ADAPTER_ID).revision == 0
    assert store.list_messages(THREAD_ID) == ()
    degraded = worker.health()
    assert degraded["state"] == "degraded"
    assert degraded["last_error_code"] == "telegram.synthetic.unavailable"

    recovered = worker.poll_once()
    assert len(recovered.outcomes) == 1
    assert poll_store.read_state(ADAPTER_ID).next_offset == 11
    assert len(store.list_messages(THREAD_ID)) == 1
    assert worker.health()["state"] == "healthy"
    assert worker.health()["last_error_code"] is None


@pytest.mark.parametrize(
    "mode",
    [
        GuardianMode.OFFLINE,
        GuardianMode.READ_ONLY,
        GuardianMode.STOPPED,
        GuardianMode.RECOVERY,
    ],
)
def test_poll_worker_never_calls_source_in_forbidden_guardian_modes(
    fixed_time: datetime,
    mode: GuardianMode,
) -> None:
    guardian_reader = guardian(fixed_time, mode)
    service, store, poll_store, _thread = ingestion_fixture(
        fixed_time,
        guardian_reader=guardian_reader,
    )
    source = FakeTelegramUpdateSource(
        (inbound_update(fixed_time),),
        adapter_id=ADAPTER_ID,
    )
    worker = TelegramPollWorker(
        adapter_id=ADAPTER_ID,
        source=source,
        poll_state_store=poll_store,
        ingestion_service=service,
        guardian_reader=guardian_reader,
    )

    with pytest.raises(TelegramIngestionUnavailableError, match="polling"):
        worker.poll_once()

    assert source.requests == []
    assert store.list_messages(THREAD_ID) == ()
    assert poll_store.read_state(ADAPTER_ID).revision == 0
    health = worker.health()
    assert health["state"] == "disabled"
    assert health["reason_code"] == f"guardian.{mode.value.replace('-', '_')}"


class InvalidBatchSource:
    def __init__(self, updates: tuple[TelegramInboundUpdate, ...]) -> None:
        self.updates = updates
        self.requests = []

    def poll(self, request):
        self.requests.append(request)
        return self.updates

    def health(self):
        return {"status": "healthy", "transport": "invalid-test-double"}


@pytest.mark.parametrize("violation", ["limit", "order", "offset"])
def test_poll_worker_validates_complete_batch_before_any_mutation(
    fixed_time: datetime,
    violation: str,
) -> None:
    guardian_reader = guardian(fixed_time)
    service, store, poll_store, _thread = ingestion_fixture(
        fixed_time,
        guardian_reader=guardian_reader,
    )
    first = inbound_update(fixed_time, update_id=10)
    second = inbound_update(fixed_time, update_id=11)
    if violation == "limit":
        updates = (first, second)
        batch_limit = 1
    elif violation == "order":
        updates = (second, first)
        batch_limit = 2
    else:
        service.ingest(first, expected_revision=0)
        updates = (inbound_update(fixed_time, update_id=9),)
        batch_limit = 1
    source = InvalidBatchSource(updates)
    worker = TelegramPollWorker(
        adapter_id=ADAPTER_ID,
        source=source,
        poll_state_store=poll_store,
        ingestion_service=service,
        guardian_reader=guardian_reader,
        batch_limit=batch_limit,
        clock=lambda: fixed_time + timedelta(minutes=3),
    )
    messages_before = store.list_messages(THREAD_ID)
    state_before = poll_store.read_state(ADAPTER_ID)

    with pytest.raises(TelegramPollBatchError):
        worker.poll_once()

    assert store.list_messages(THREAD_ID) == messages_before
    assert poll_store.read_state(ADAPTER_ID) == state_before
    assert worker.health()["last_error_code"] == "telegram.worker.cycle_failed"


def test_poll_worker_rejects_unbounded_request_configuration(fixed_time: datetime) -> None:
    guardian_reader = guardian(fixed_time)
    service, _store, poll_store, _thread = ingestion_fixture(
        fixed_time,
        guardian_reader=guardian_reader,
    )
    source = FakeTelegramUpdateSource(adapter_id=ADAPTER_ID)
    with pytest.raises(ValueError, match="timeout"):
        TelegramPollWorker(
            adapter_id=ADAPTER_ID,
            source=source,
            poll_state_store=poll_store,
            ingestion_service=service,
            guardian_reader=guardian_reader,
            timeout_seconds=0,
        )
    with pytest.raises(ValueError, match="batch limit"):
        TelegramPollWorker(
            adapter_id=ADAPTER_ID,
            source=source,
            poll_state_store=poll_store,
            ingestion_service=service,
            guardian_reader=guardian_reader,
            batch_limit=101,
        )
