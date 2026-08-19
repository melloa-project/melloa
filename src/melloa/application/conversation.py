"""Authenticated canonical owner-conversation use cases."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import ValidationError

from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import (
    QualifiedName,
    RecordId,
    canonical_json_bytes,
    new_record_id,
    sha256_digest,
    utc_now,
)
from melloa.domain.classification import (
    Sensitivity,
    most_restrictive_sensitivity,
    sensitivity_scope,
)
from melloa.domain.conversation import (
    ConversationMessage,
    ConversationProcessingAttempt,
    ConversationProcessingOutcome,
    ConversationProcessingResumption,
    ConversationProcessingState,
    ConversationProcessingStatus,
    ConversationReplyWork,
    ConversationThread,
    ConversationTurn,
    ConversationTurnInspection,
    MessageKind,
    MessagePart,
    processing_model_result,
)
from melloa.domain.guardian import GuardianMode
from melloa.domain.models import (
    ConversationModelOutput,
    ModelRequest,
    ModelResult,
    ProcessingLocation,
)
from melloa.domain.retrieval import RetrievalManifest
from melloa.ports.conversation import (
    ClaimedConversationReplyWork,
    CompletedConversationTurn,
    ConversationConflictError,
    ConversationNotFoundError,
    ConversationStore,
)
from melloa.ports.guardian import GuardianStatusReader
from melloa.ports.memory import MemoryRetriever
from melloa.ports.model import ModelGateway, ModelInvocationError
from melloa.release import CURRENT_RELEASE


class ConversationUnavailableError(RuntimeError):
    """Guardian mode or runtime state forbids a conversation write."""


class ConversationOwnershipError(PermissionError):
    """An authenticated owner attempted to access another owner's thread."""


class InvalidModelOutputError(RuntimeError):
    """Untrusted model output failed the declared conversation schema."""


@dataclass(frozen=True)
class ConversationReply:
    inbound_message: ConversationMessage
    output_message: ConversationMessage | None
    turn: ConversationTurn | None
    processing: ConversationProcessingStatus
    duplicate: bool


@dataclass(frozen=True)
class ConversationModelLimits:
    latency_deadline_ms: int = 30_000
    max_input_tokens: int = 4_096
    max_output_tokens: int = 1_024
    cost_ceiling_gbp: float = 0.0
    prompt_version: str = "conversation-response-v1"

    def __post_init__(self) -> None:
        if not 1 <= self.latency_deadline_ms <= 3_600_000:
            raise ValueError("conversation model deadline must be between 1 ms and 1 hour")
        if self.max_input_tokens <= 0 or self.max_output_tokens <= 0:
            raise ValueError("conversation model token ceilings must be positive")
        if self.cost_ceiling_gbp < 0:
            raise ValueError("conversation model cost ceiling cannot be negative")


class ConversationService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        intelligence_id: RecordId,
        store: ConversationStore,
        model_gateway: ModelGateway | None,
        retriever: MemoryRetriever,
        guardian_reader: GuardianStatusReader,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
        runtime_version: str = CURRENT_RELEASE.runtime_identifier,
        model_limits: ConversationModelLimits | None = None,
        max_processing_attempts: int = 3,
        processing_lease: timedelta = timedelta(seconds=45),
        retry_base: timedelta = timedelta(seconds=1),
        retry_ceiling: timedelta = timedelta(minutes=5),
    ) -> None:
        if max_processing_attempts < 1:
            raise ValueError("max processing attempts must be positive")
        if processing_lease <= timedelta(0):
            raise ValueError("processing lease must be positive")
        if retry_base <= timedelta(0) or retry_ceiling < retry_base:
            raise ValueError("retry delays must be positive and monotonically bounded")
        self._owner_id = owner_id
        self._intelligence_id = intelligence_id
        self._store = store
        self._model_gateway = model_gateway
        self._retriever = retriever
        self._guardian_reader = guardian_reader
        self._clock = clock
        self._id_factory = id_factory
        self._runtime_version = runtime_version
        self._model_limits = model_limits or ConversationModelLimits()
        self._max_processing_attempts = max_processing_attempts
        self._processing_lease = processing_lease
        self._retry_base = retry_base
        self._retry_ceiling = retry_ceiling

    def create_thread(
        self,
        principal: AuthenticatedOwner,
        *,
        title: str,
        sensitivity: Sensitivity,
    ) -> ConversationThread:
        self._require_owner(principal)
        self._require_write_mode()
        now = self._clock()
        thread = ConversationThread(
            thread_id=self._id_factory("thread"),
            owner_id=self._owner_id,
            intelligence_id=self._intelligence_id,
            title=title,
            sensitivity=sensitivity,
            created_at=now,
            updated_at=now,
        )
        self._store.create_thread(thread)
        return thread

    def list_threads(self, principal: AuthenticatedOwner) -> tuple[ConversationThread, ...]:
        self._require_owner(principal)
        return self._store.list_threads(principal.owner_id)

    def list_messages(
        self,
        principal: AuthenticatedOwner,
        thread_id: RecordId,
    ) -> tuple[ConversationMessage, ...]:
        self._require_thread_owner(principal, self._store.get_thread(thread_id))
        return self._store.list_messages(thread_id)

    def list_turns(
        self,
        principal: AuthenticatedOwner,
        thread_id: RecordId,
    ) -> tuple[ConversationTurn, ...]:
        self._require_thread_owner(principal, self._store.get_thread(thread_id))
        return self._store.list_turns(thread_id)

    def inspect_turn(
        self,
        principal: AuthenticatedOwner,
        *,
        thread_id: RecordId,
        turn_id: RecordId,
    ) -> ConversationTurnInspection:
        turns = self.list_turns(principal, thread_id)
        turn = next((candidate for candidate in turns if candidate.turn_id == turn_id), None)
        if turn is None:
            raise ConversationNotFoundError(f"turn not found: {turn_id}")
        completed = self._store.completed_turn_for_trigger(turn.triggering_message_ids[0])
        if completed is None or completed.turn != turn:
            raise ConversationNotFoundError(f"completed turn not found: {turn_id}")
        return ConversationTurnInspection(
            turn=turn,
            retrieval_manifest=completed.retrieval_manifest,
            model_result=completed.model_result,
            output_message=completed.output_message,
        )

    def post_owner_message(
        self,
        principal: AuthenticatedOwner,
        *,
        thread_id: RecordId,
        text: str,
        idempotency_key: str,
    ) -> ConversationReply:
        thread = self._store.get_thread(thread_id)
        self._require_thread_owner(principal, thread)
        if not 1 <= len(idempotency_key) <= 256:
            raise ValueError("idempotency key must contain between 1 and 256 characters")
        existing = self._store.get_inbound_by_idempotency_key(thread_id, idempotency_key)
        if existing is not None:
            self._require_same_submission(existing, text)
            return self._process_accepted(existing, duplicate=True)
        self._require_write_mode()
        now = self._clock()
        inbound = ConversationMessage(
            message_id=self._id_factory("message"),
            thread_id=thread_id,
            author_principal_id=principal.owner_id,
            source_client="client.owner-console",
            parts=(MessagePart(kind=MessageKind.TEXT, text=text),),
            sensitivity=thread.sensitivity,
            created_at=now,
            observed_at=now,
        )
        work = ConversationReplyWork(
            work_id=self._id_factory("work"),
            thread_id=thread_id,
            message_id=inbound.message_id,
            created_at=now,
        )
        accepted = self._store.append_inbound(
            inbound,
            idempotency_key,
            work,
            max_attempts=self._max_processing_attempts,
        )
        if not accepted.created:
            self._require_same_submission(accepted.message, text)
            return self._process_accepted(accepted.message, duplicate=True)
        return self._process_accepted(accepted.message, duplicate=False)

    def list_processing(
        self,
        principal: AuthenticatedOwner,
        thread_id: RecordId,
    ) -> tuple[ConversationProcessingStatus, ...]:
        self._require_thread_owner(principal, self._store.get_thread(thread_id))
        return self._store.list_reply_processing(thread_id)

    def inspect_processing(
        self,
        principal: AuthenticatedOwner,
        *,
        thread_id: RecordId,
        message_id: RecordId,
    ) -> ConversationProcessingStatus:
        self._require_thread_owner(principal, self._store.get_thread(thread_id))
        message = self._store.get_message(message_id)
        if message.thread_id != thread_id:
            raise ConversationNotFoundError(
                f"message not found in requested thread: {message_id}"
            )
        return self._store.reply_processing(message_id)

    def resume_owner_message(
        self,
        principal: AuthenticatedOwner,
        *,
        thread_id: RecordId,
        message_id: RecordId,
    ) -> ConversationReply:
        self._require_thread_owner(principal, self._store.get_thread(thread_id))
        message = self._store.get_message(message_id)
        if message.thread_id != thread_id or message.author_principal_id != principal.owner_id:
            raise ConversationNotFoundError(
                f"owner message not found in requested thread: {message_id}"
            )
        self._require_write_mode()
        processing = self._store.reply_processing(message_id)
        if processing.state is ConversationProcessingState.DEAD:
            resumed_at = self._clock()
            self._store.resume_reply_work(
                message_id,
                ConversationProcessingResumption(
                    resumption_id=self._id_factory("resumption"),
                    work_id=processing.work_id,
                    message_id=message_id,
                    requested_by=principal.owner_id,
                    requested_at=resumed_at,
                    prior_attempts=processing.attempt_count,
                    added_attempts=self._max_processing_attempts,
                ),
                available_at=resumed_at,
                added_attempts=self._max_processing_attempts,
            )
        return self._process_accepted(message, duplicate=True)

    def process_ready(
        self,
        *,
        limit: int = 10,
    ) -> tuple[ConversationProcessingStatus, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("processing limit must be between 1 and 100")
        self._require_write_mode()
        processed: list[ConversationProcessingStatus] = []
        for _ in range(limit):
            now = self._clock()
            claim = self._store.claim_next_reply_work(
                lease_owner=self._id_factory("worker"),
                now=now,
                lease_expires_at=now + self._processing_lease,
            )
            if claim is None:
                break
            processed.append(self._process_claim(claim))
        return tuple(processed)

    def _process_accepted(
        self,
        inbound: ConversationMessage,
        *,
        duplicate: bool,
    ) -> ConversationReply:
        completed = self._store.completed_turn_for_trigger(inbound.message_id)
        processing = self._store.reply_processing(inbound.message_id)
        if completed is not None or processing.state in {
            ConversationProcessingState.COMPLETED,
            ConversationProcessingState.DEAD,
            ConversationProcessingState.CANCELLED,
        }:
            return self._reply_for_existing(inbound, processing, duplicate=duplicate)
        try:
            self._require_write_mode()
        except ConversationUnavailableError:
            return self._reply_for_existing(inbound, processing, duplicate=duplicate)
        now = self._clock()
        claim = self._store.claim_reply_work(
            inbound.message_id,
            lease_owner=self._id_factory("worker"),
            now=now,
            lease_expires_at=now + self._processing_lease,
        )
        if claim is None:
            return self._reply_for_existing(
                inbound,
                self._store.reply_processing(inbound.message_id),
                duplicate=duplicate,
            )
        processing = self._process_claim(claim)
        completed = self._store.completed_turn_for_trigger(inbound.message_id)
        return ConversationReply(
            inbound_message=inbound,
            output_message=None if completed is None else completed.output_message,
            turn=None if completed is None else completed.turn,
            processing=processing,
            duplicate=duplicate,
        )

    def _process_claim(
        self,
        claim: ClaimedConversationReplyWork,
    ) -> ConversationProcessingStatus:
        inbound = self._store.get_message(claim.work.message_id)
        thread = self._store.get_thread(claim.work.thread_id)
        if (
            inbound.thread_id != thread.thread_id
            or thread.owner_id != self._owner_id
            or inbound.author_principal_id != self._owner_id
        ):
            raise ConversationConflictError("reply work escaped its canonical owner scope")
        text = self._message_text(inbound)
        attempt_started_at = self._clock()
        try:
            guardian_mode = self._require_write_mode()
        except ConversationUnavailableError:
            return self._record_processing_failure(
                claim,
                started_at=attempt_started_at,
                error_code="guardian.conversation_write_blocked",
            )
        if self._model_gateway is None:
            return self._record_processing_failure(
                claim,
                started_at=attempt_started_at,
                error_code="model.not_configured",
            )

        allowed_sensitivities = sensitivity_scope(thread.sensitivity)
        try:
            retrieval_manifest = self._retriever.retrieve(
                requester_id=self._intelligence_id,
                subject_id=self._owner_id,
                query=text,
                purpose="conversation.owner-reply",
                allowed_sensitivities=allowed_sensitivities,
            )
            self._validate_retrieval_manifest(
                retrieval_manifest,
                query=text,
                allowed_sensitivities=allowed_sensitivities,
            )
        except Exception:
            return self._record_processing_failure(
                claim,
                started_at=attempt_started_at,
                error_code="retrieval.failed",
            )

        message_sensitivity = most_restrictive_sensitivity(
            (
                thread.sensitivity,
                *(citation.sensitivity for citation in retrieval_manifest.citations),
            )
        )
        model_request = self._model_request(
            thread,
            inbound,
            text,
            guardian_mode,
            message_sensitivity,
            retrieval_manifest,
        )
        try:
            result = self._model_gateway.invoke(model_request)
        except ModelInvocationError as error:
            return self._record_processing_failure(
                claim,
                started_at=attempt_started_at,
                error_code="model.gateway_failed",
                retrieval_manifest=retrieval_manifest,
                request_id=model_request.request_id,
                external_disclosure=error.external_disclosure,
            )
        except Exception:
            return self._record_processing_failure(
                claim,
                started_at=attempt_started_at,
                error_code="model.gateway_failed",
                retrieval_manifest=retrieval_manifest,
                request_id=model_request.request_id,
            )

        try:
            disclosed_manifest = self._manifest_with_disclosure(
                retrieval_manifest,
                result.external_disclosure,
            )
        except InvalidModelOutputError:
            return self._record_processing_failure(
                claim,
                started_at=attempt_started_at,
                error_code="model.disclosure_invalid",
                retrieval_manifest=retrieval_manifest,
                model_result=result,
                request_id=model_request.request_id,
            )
        try:
            output = ConversationModelOutput.model_validate_json(
                canonical_json_bytes(result.output)
            )
        except ValidationError:
            return self._record_processing_failure(
                claim,
                started_at=attempt_started_at,
                error_code="model.invalid_output",
                retrieval_manifest=disclosed_manifest,
                model_result=result,
                request_id=model_request.request_id,
            )
        citations_by_id = {
            citation.citation_id: citation for citation in disclosed_manifest.citations
        }
        if not set(output.citation_ids) <= citations_by_id.keys():
            return self._record_processing_failure(
                claim,
                started_at=attempt_started_at,
                error_code="model.invalid_citations",
                retrieval_manifest=disclosed_manifest,
                model_result=result,
                request_id=model_request.request_id,
            )
        evidence_ids = tuple(
            citations_by_id[citation_id].assertion_id for citation_id in output.citation_ids
        )

        completed_at = max(
            self._clock(),
            attempt_started_at + timedelta(microseconds=1),
        )
        output_message = ConversationMessage(
            message_id=self._id_factory("message"),
            thread_id=thread.thread_id,
            author_principal_id=self._intelligence_id,
            source_client="client.owner-console",
            parts=(MessagePart(kind=MessageKind.TEXT, text=output.text),),
            reply_to_message_id=inbound.message_id,
            citation_ids=output.citation_ids,
            sensitivity=message_sensitivity,
            created_at=completed_at,
            observed_at=completed_at,
        )
        turn = ConversationTurn(
            turn_id=self._id_factory("turn"),
            thread_id=thread.thread_id,
            triggering_message_ids=(inbound.message_id,),
            retrieval_manifest_id=disclosed_manifest.manifest_id,
            evidence_ids=evidence_ids,
            model_run_ids=(result.result_id,),
            output_message_ids=(output_message.message_id,),
            decision_record={
                "summary": "Generated a bounded first-party owner reply.",
                "assumptions": [],
                "uncertainty": "Model output remains untrusted until schema validation.",
                "alternatives": ["Persist the owner message without a generated reply."],
                "selected_plan": "Invoke the configured conversation model and persist the result.",
                "limitations": (
                    []
                    if disclosed_manifest.citations
                    else ["No relevant memory citations were retrieved for this turn."]
                ),
                "retrieval_manifest_id": disclosed_manifest.manifest_id,
                "retrieved_citation_ids": [
                    citation.citation_id for citation in disclosed_manifest.citations
                ],
                "selected_citation_ids": list(output.citation_ids),
                "evidence_ids": list(evidence_ids),
                "model_id": result.model_id,
                "provider_id": result.provider_id,
                "prompt_version": model_request.prompt_version,
                "runtime_version": self._runtime_version,
                "message_sensitivity": model_request.sensitivity.value,
                "cost_gbp": result.cost_gbp,
                "external_disclosure": result.external_disclosure,
            },
            started_at=inbound.created_at,
            completed_at=completed_at,
        )
        completed = CompletedConversationTurn(
            turn=turn,
            output_message=output_message,
            model_result=result,
            retrieval_manifest=disclosed_manifest,
        )
        attempt = self._processing_attempt(
            claim,
            started_at=attempt_started_at,
            completed_at=completed_at,
            outcome=ConversationProcessingOutcome.SUCCEEDED,
            retrieval_manifest=disclosed_manifest,
            model_result=result,
            request_id=model_request.request_id,
        )
        return self._store.complete_reply_work(claim, completed, attempt)

    def _model_request(
        self,
        thread: ConversationThread,
        message: ConversationMessage,
        text: str,
        guardian_mode: GuardianMode,
        message_sensitivity: Sensitivity,
        retrieval_manifest: RetrievalManifest,
    ) -> ModelRequest:
        locations = frozenset({ProcessingLocation.DEVICE})
        if (
            guardian_mode is GuardianMode.NORMAL
            and message_sensitivity is not Sensitivity.DEVICE_ONLY
        ):
            locations = frozenset(
                {
                    ProcessingLocation.DEVICE,
                    ProcessingLocation.PRIVATE_NETWORK,
                    ProcessingLocation.APPROVED_PROVIDER,
                }
            )
        return ModelRequest(
            request_id=self._id_factory("request"),
            sensitivity=message_sensitivity,
            allowed_processing_locations=locations,
            latency_deadline_ms=self._model_limits.latency_deadline_ms,
            max_input_tokens=self._model_limits.max_input_tokens,
            max_output_tokens=self._model_limits.max_output_tokens,
            cost_ceiling_gbp=self._model_limits.cost_ceiling_gbp,
            prompt_version=self._model_limits.prompt_version,
            input={
                "thread_id": thread.thread_id,
                "message_id": message.message_id,
                "text": text,
                "retrieval_manifest_id": retrieval_manifest.manifest_id,
                "memory_citations": [
                    citation.model_dump(mode="json")
                    for citation in retrieval_manifest.citations
                ],
            },
        )

    def _validate_retrieval_manifest(
        self,
        manifest: RetrievalManifest,
        *,
        query: str,
        allowed_sensitivities: frozenset[Sensitivity],
    ) -> None:
        if (
            manifest.requester_id != self._intelligence_id
            or manifest.subject_id != self._owner_id
            or manifest.purpose != "conversation.owner-reply"
            or manifest.allowed_sensitivities != allowed_sensitivities
            or manifest.query_hash != sha256_digest(query.encode("utf-8"))
        ):
            raise ConversationUnavailableError(
                "retrieval manifest does not match the conversation turn scope"
            )

    @staticmethod
    def _manifest_with_disclosure(
        manifest: RetrievalManifest,
        external_disclosure: bool,
    ) -> RetrievalManifest:
        document = manifest.model_dump(mode="json")
        document["external_disclosure"] = external_disclosure
        try:
            return RetrievalManifest.model_validate_json(canonical_json_bytes(document))
        except ValidationError as error:
            raise InvalidModelOutputError(
                "model disclosure violated the retrieval manifest"
            ) from error

    def _record_processing_failure(
        self,
        claim: ClaimedConversationReplyWork,
        *,
        started_at: datetime,
        error_code: QualifiedName,
        retrieval_manifest: RetrievalManifest | None = None,
        model_result: ModelResult | None = None,
        request_id: RecordId | None = None,
        external_disclosure: bool | None = None,
    ) -> ConversationProcessingStatus:
        completed_at = max(self._clock(), started_at)
        if model_result is not None:
            request_id = model_result.request_id
        disclosed = (
            model_result.external_disclosure
            if model_result is not None
            else bool(external_disclosure)
        )
        persisted_manifest = retrieval_manifest
        if retrieval_manifest is not None:
            try:
                persisted_manifest = self._manifest_with_disclosure(
                    retrieval_manifest,
                    disclosed,
                )
            except InvalidModelOutputError:
                error_code = "model.disclosure_invalid"
        terminal = claim.attempt >= claim.max_attempts
        retry_at = None
        outcome = ConversationProcessingOutcome.DEAD
        if not terminal:
            retry_at = completed_at + self._retry_delay(
                claim.work.work_id,
                claim.attempt,
            )
            outcome = ConversationProcessingOutcome.RETRY_SCHEDULED
        attempt = self._processing_attempt(
            claim,
            started_at=started_at,
            completed_at=completed_at,
            outcome=outcome,
            error_code=error_code,
            retry_at=retry_at,
            retrieval_manifest=persisted_manifest,
            model_result=model_result,
            request_id=request_id,
            external_disclosure=disclosed,
        )
        return self._store.record_reply_failure(
            claim,
            attempt,
            persisted_manifest,
            model_result,
        )

    def _processing_attempt(
        self,
        claim: ClaimedConversationReplyWork,
        *,
        started_at: datetime,
        completed_at: datetime,
        outcome: ConversationProcessingOutcome,
        retrieval_manifest: RetrievalManifest | None = None,
        model_result: ModelResult | None = None,
        request_id: RecordId | None = None,
        error_code: QualifiedName | None = None,
        retry_at: datetime | None = None,
        external_disclosure: bool | None = None,
    ) -> ConversationProcessingAttempt:
        if model_result is not None:
            request_id = model_result.request_id
        disclosed = (
            model_result.external_disclosure
            if model_result is not None
            else bool(external_disclosure)
        )
        if external_disclosure is not None and external_disclosure != disclosed:
            raise ConversationConflictError("processing disclosure metadata conflicts")
        disclosed_memory_ids: tuple[RecordId, ...] = ()
        if disclosed and retrieval_manifest is not None:
            disclosed_memory_ids = tuple(
                citation.assertion_id for citation in retrieval_manifest.citations
            )
        return ConversationProcessingAttempt(
            attempt_id=self._id_factory("attempt"),
            work_id=claim.work.work_id,
            message_id=claim.work.message_id,
            attempt=claim.attempt,
            request_id=request_id,
            outcome=outcome,
            error_code=error_code,
            started_at=started_at,
            completed_at=completed_at,
            retry_at=retry_at,
            retrieval_manifest_id=(
                None if retrieval_manifest is None else retrieval_manifest.manifest_id
            ),
            model_result_summary=(
                None if model_result is None else processing_model_result(model_result)
            ),
            disclosed_memory_ids=disclosed_memory_ids,
            external_disclosure=disclosed,
        )

    def _retry_delay(self, work_id: RecordId, attempt: int) -> timedelta:
        digest = hashlib.sha256(f"{work_id}:{attempt}".encode()).digest()
        unit = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
        jitter = 0.75 + (unit * 0.5)
        exponential = self._retry_base.total_seconds() * (2 ** (attempt - 1))
        seconds = min(self._retry_ceiling.total_seconds(), exponential * jitter)
        return timedelta(seconds=max(seconds, 0.001))

    @staticmethod
    def _message_text(message: ConversationMessage) -> str:
        if len(message.parts) != 1 or message.parts[0].kind is not MessageKind.TEXT:
            raise ConversationConflictError("owner reply work requires one text part")
        return message.parts[0].text

    def _require_same_submission(self, inbound: ConversationMessage, text: str) -> None:
        if self._message_text(inbound) != text:
            raise ConversationConflictError(
                "idempotency key was reused with different message content"
            )

    def _reply_for_existing(
        self,
        inbound: ConversationMessage,
        processing: ConversationProcessingStatus,
        *,
        duplicate: bool,
    ) -> ConversationReply:
        completed = self._store.completed_turn_for_trigger(inbound.message_id)
        return ConversationReply(
            inbound_message=inbound,
            output_message=None if completed is None else completed.output_message,
            turn=None if completed is None else completed.turn,
            processing=processing,
            duplicate=duplicate,
        )

    def _require_owner(self, principal: AuthenticatedOwner) -> None:
        if principal.owner_id != self._owner_id:
            raise ConversationOwnershipError("authenticated principal does not own this runtime")

    def _require_thread_owner(
        self,
        principal: AuthenticatedOwner,
        thread: ConversationThread,
    ) -> None:
        self._require_owner(principal)
        if thread.owner_id != principal.owner_id:
            raise ConversationOwnershipError("authenticated principal does not own this thread")

    def _require_write_mode(self) -> GuardianMode:
        mode = self._guardian_reader.read_status().payload.mode
        if mode in {GuardianMode.READ_ONLY, GuardianMode.STOPPED, GuardianMode.RECOVERY}:
            raise ConversationUnavailableError(
                f"Guardian mode does not permit conversation writes: {mode.value}"
            )
        return mode
