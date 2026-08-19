"""Durable channel-neutral conversation persistence port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from melloa.domain.base import RecordId
from melloa.domain.conversation import (
    ConversationDeletionReceipt,
    ConversationMessage,
    ConversationProcessingAttempt,
    ConversationProcessingResumption,
    ConversationProcessingStatus,
    ConversationReplyWork,
    ConversationThread,
    ConversationTurn,
)
from melloa.domain.models import ModelResult
from melloa.domain.retrieval import RetrievalManifest


class ConversationNotFoundError(LookupError):
    """A canonical conversation record was not found."""


class ConversationConflictError(RuntimeError):
    """An immutable conversation identifier was reused with different content."""


@dataclass(frozen=True)
class InboundAppendResult:
    message: ConversationMessage
    created: bool


@dataclass(frozen=True)
class CompletedConversationTurn:
    turn: ConversationTurn
    output_message: ConversationMessage
    model_result: ModelResult
    retrieval_manifest: RetrievalManifest


@dataclass(frozen=True)
class ClaimedConversationReplyWork:
    work: ConversationReplyWork
    attempt: int
    max_attempts: int
    lease_owner: RecordId
    lease_expires_at: datetime


class ConversationStore(Protocol):
    def create_thread(self, thread: ConversationThread) -> None:
        """Create a canonical thread or accept an exact idempotent replay."""

    def get_thread(self, thread_id: RecordId) -> ConversationThread:
        """Return one canonical thread or raise ConversationNotFoundError."""

    def list_threads(self, owner_id: RecordId) -> tuple[ConversationThread, ...]:
        """Return the owner's threads in deterministic update order."""

    def delete_thread(
        self,
        deletion: ConversationDeletionReceipt,
    ) -> ConversationDeletionReceipt:
        """Delete active conversation content and retain only bounded deletion evidence."""

    def get_inbound_by_idempotency_key(
        self,
        thread_id: RecordId,
        idempotency_key: str,
    ) -> ConversationMessage | None:
        """Resolve a prior owner submission without causing a write."""

    def append_inbound(
        self,
        message: ConversationMessage,
        idempotency_key: str,
        work: ConversationReplyWork,
        *,
        max_attempts: int,
    ) -> InboundAppendResult:
        """Atomically accept an inbound message and enqueue its reply work."""

    def get_message(self, message_id: RecordId) -> ConversationMessage:
        """Return one canonical message or raise ConversationNotFoundError."""

    def claim_reply_work(
        self,
        message_id: RecordId,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedConversationReplyWork | None:
        """Lease due reply work for one accepted message."""

    def claim_next_reply_work(
        self,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ClaimedConversationReplyWork | None:
        """Lease the next due reply work item in deterministic queue order."""

    def record_reply_failure(
        self,
        claim: ClaimedConversationReplyWork,
        attempt: ConversationProcessingAttempt,
        retrieval_manifest: RetrievalManifest | None,
        model_result: ModelResult | None,
    ) -> ConversationProcessingStatus:
        """Record one redacted failure and either schedule retry or mark dead."""

    def complete_reply_work(
        self,
        claim: ClaimedConversationReplyWork,
        completed: CompletedConversationTurn,
        attempt: ConversationProcessingAttempt,
    ) -> ConversationProcessingStatus:
        """Atomically complete canonical turn records and their leased work."""

    def reply_processing(self, message_id: RecordId) -> ConversationProcessingStatus:
        """Return owner-visible processing state for one accepted message."""

    def list_reply_processing(
        self,
        thread_id: RecordId,
    ) -> tuple[ConversationProcessingStatus, ...]:
        """Return a thread's processing state in deterministic queue order."""

    def resume_reply_work(
        self,
        message_id: RecordId,
        resumption: ConversationProcessingResumption,
        *,
        available_at: datetime,
        added_attempts: int,
    ) -> ConversationProcessingStatus:
        """Requeue dead reply work after an explicit owner resumption."""

    def complete_turn(self, completed: CompletedConversationTurn) -> None:
        """Atomically persist a validated model result, output message, and turn."""

    def completed_turn_for_trigger(
        self,
        message_id: RecordId,
    ) -> CompletedConversationTurn | None:
        """Return the completed turn caused by an inbound message, if present."""

    def list_completed_turns(
        self,
        owner_id: RecordId,
        *,
        completed_from: datetime,
        completed_before: datetime,
    ) -> tuple[CompletedConversationTurn, ...]:
        """Return owner-scoped completed turns within a half-open time window."""

    def get_retrieval_manifest(self, manifest_id: RecordId) -> RetrievalManifest:
        """Return one immutable retrieval manifest or raise ConversationNotFoundError."""

    def list_messages(self, thread_id: RecordId) -> tuple[ConversationMessage, ...]:
        """Return canonical messages in chronological order."""

    def list_turns(self, thread_id: RecordId) -> tuple[ConversationTurn, ...]:
        """Return structured turns in chronological order."""
