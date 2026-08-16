"""Authenticated, policy-bound outbound channel delivery use cases."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import ValidationError

from melloa.domain.auth import AuthenticatedOwner
from melloa.domain.base import QualifiedName, RecordId, new_record_id, utc_now
from melloa.domain.classification import Sensitivity
from melloa.domain.conversation import DeliveryState
from melloa.domain.delivery import (
    AuthorizedClientDelivery,
    DeliveryExecutionReceipt,
    DeliveryWorkAttempt,
    DeliveryWorkOutcome,
    DeliveryWorkResumption,
    DeliveryWorkState,
    DeliveryWorkStatus,
    OutboundDeliveryWork,
    canonical_delivery_action,
    conversation_message_hash,
)
from melloa.domain.guardian import GuardianMode, GuardianStatusPayload
from melloa.domain.policy import (
    AuthorizationRequest,
    CanonicalAction,
    DecisionEffect,
    DeterministicPolicyEvaluator,
    PolicyContext,
    PolicyDecision,
    action_hash,
)
from melloa.ports.client import ClientAdapter, ClientDeliveryError
from melloa.ports.conversation import ConversationNotFoundError, ConversationStore
from melloa.ports.delivery import ClaimedDeliveryWork, DeliveryNotFoundError, DeliveryStore
from melloa.ports.guardian import GuardianStatusReader


class DeliveryUnavailableError(RuntimeError):
    """Current policy, Guardian, or adapter state forbids outbound delivery."""

    def __init__(self, reason_code: QualifiedName) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class DeliveryOwnershipError(PermissionError):
    """An authenticated owner attempted to access another owner's delivery."""


@dataclass(frozen=True)
class ClientDeliveryRoute:
    adapter_id: QualifiedName
    destination_ref: str
    external_destination: str
    purpose: str
    adapter: ClientAdapter
    allowed_sensitivities: frozenset[Sensitivity]
    estimated_cost_gbp: Decimal = Decimal("0")


@dataclass(frozen=True)
class DeliverySubmission:
    status: DeliveryWorkStatus
    created: bool


class DeliveryService:
    def __init__(
        self,
        *,
        owner_id: RecordId,
        intelligence_id: RecordId,
        conversation_store: ConversationStore,
        delivery_store: DeliveryStore,
        routes: tuple[ClientDeliveryRoute, ...],
        guardian_reader: GuardianStatusReader,
        policy_evaluator: DeterministicPolicyEvaluator | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
        max_attempts: int = 3,
        lease_duration: timedelta = timedelta(seconds=45),
        retry_base: timedelta = timedelta(seconds=1),
        retry_ceiling: timedelta = timedelta(minutes=5),
        remaining_daily_budget_gbp: Decimal = Decimal("0"),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max delivery attempts must be positive")
        if lease_duration <= timedelta(0):
            raise ValueError("delivery lease must be positive")
        if retry_base <= timedelta(0) or retry_ceiling < retry_base:
            raise ValueError("delivery retry delays must be positive and bounded")
        route_keys = tuple((route.adapter_id, route.destination_ref) for route in routes)
        if len(set(route_keys)) != len(route_keys):
            raise ValueError("delivery routes must use unique adapter destinations")
        self._owner_id = owner_id
        self._intelligence_id = intelligence_id
        self._conversation_store = conversation_store
        self._delivery_store = delivery_store
        self._routes = {(route.adapter_id, route.destination_ref): route for route in routes}
        self._guardian_reader = guardian_reader
        self._policy_evaluator = policy_evaluator or DeterministicPolicyEvaluator(
            policy_version="m1-owner-delivery-v1"
        )
        self._clock = clock
        self._id_factory = id_factory
        self._max_attempts = max_attempts
        self._lease_duration = lease_duration
        self._retry_base = retry_base
        self._retry_ceiling = retry_ceiling
        self._remaining_daily_budget_gbp = remaining_daily_budget_gbp

    def enqueue_owner_delivery(
        self,
        principal: AuthenticatedOwner,
        *,
        thread_id: RecordId,
        message_id: RecordId,
        client_adapter: QualifiedName,
        destination_ref: str,
        idempotency_key: str,
    ) -> DeliverySubmission:
        self._require_thread_owner(principal, thread_id)
        if not 1 <= len(idempotency_key) <= 256:
            raise ValueError("idempotency key must contain between 1 and 256 characters")
        message = self._conversation_store.get_message(message_id)
        if message.thread_id != thread_id:
            raise ConversationNotFoundError(f"message not found in requested thread: {message_id}")
        route = self._route(client_adapter, destination_ref)
        if message.sensitivity not in route.allowed_sensitivities:
            raise DeliveryUnavailableError("delivery.sensitivity_not_allowed")
        now = self._clock()
        action = canonical_delivery_action(
            message,
            client_adapter=route.adapter_id,
            destination_ref=route.destination_ref,
            external_destination=route.external_destination,
            purpose=route.purpose,
            estimated_cost_gbp=route.estimated_cost_gbp,
        )
        request, decision = self._authorize_owner_action(action, now=now)
        work = OutboundDeliveryWork(
            work_id=self._id_factory("deliverywork"),
            thread_id=thread_id,
            message_id=message.message_id,
            message_hash=conversation_message_hash(message),
            requested_by=principal.owner_id,
            client_adapter=route.adapter_id,
            destination_ref=route.destination_ref,
            idempotency_key=idempotency_key,
            authorization_request=request,
            policy_decision=decision,
            authorized_at=now,
            created_at=now,
        )
        enqueued = self._delivery_store.enqueue(work, max_attempts=self._max_attempts)
        status = self._process_accepted(enqueued.work, enqueued.status)
        return DeliverySubmission(status=status, created=enqueued.created)

    def list_deliveries(
        self,
        principal: AuthenticatedOwner,
        thread_id: RecordId,
    ) -> tuple[DeliveryWorkStatus, ...]:
        self._require_thread_owner(principal, thread_id)
        return self._delivery_store.list_status(thread_id)

    def inspect_delivery(
        self,
        principal: AuthenticatedOwner,
        *,
        thread_id: RecordId,
        work_id: RecordId,
    ) -> DeliveryWorkStatus:
        self._require_thread_owner(principal, thread_id)
        status = self._delivery_store.status(work_id)
        if status.thread_id != thread_id:
            raise DeliveryNotFoundError(f"delivery not found in requested thread: {work_id}")
        return status

    def resume_delivery(
        self,
        principal: AuthenticatedOwner,
        *,
        thread_id: RecordId,
        work_id: RecordId,
    ) -> DeliveryWorkStatus:
        self._require_thread_owner(principal, thread_id)
        status = self._delivery_store.status(work_id)
        if status.thread_id != thread_id:
            raise DeliveryNotFoundError(f"delivery not found in requested thread: {work_id}")
        if status.state is DeliveryWorkState.DEAD:
            work = self._delivery_store.get_work(work_id)
            message = self._conversation_store.get_message(work.message_id)
            if conversation_message_hash(message) != work.message_hash:
                raise DeliveryUnavailableError("delivery.message_hash_mismatch")
            self._route(work.client_adapter, work.destination_ref)
            now = self._clock()
            request, decision = self._authorize_owner_action(
                work.authorization_request.action,
                now=now,
            )
            if request.action_hash != work.authorization_request.action_hash:
                raise DeliveryUnavailableError("delivery.action_hash_changed")
            self._delivery_store.resume(
                work_id,
                DeliveryWorkResumption(
                    resumption_id=self._id_factory("deliveryresume"),
                    work_id=work_id,
                    message_id=work.message_id,
                    requested_by=principal.owner_id,
                    requested_at=now,
                    prior_attempts=status.attempt_count,
                    added_attempts=self._max_attempts,
                    authorization_request=request,
                    policy_decision=decision,
                ),
                available_at=now,
                added_attempts=self._max_attempts,
            )
        work = self._delivery_store.get_work(work_id)
        return self._process_accepted(work, self._delivery_store.status(work_id))

    def process_ready(self, *, limit: int = 10) -> tuple[DeliveryWorkStatus, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("delivery limit must be between 1 and 100")
        processed: list[DeliveryWorkStatus] = []
        for _ in range(limit):
            now = self._clock()
            claim = self._delivery_store.claim_next_work(
                lease_owner=self._id_factory("deliveryworker"),
                now=now,
                lease_expires_at=now + self._lease_duration,
            )
            if claim is None:
                break
            processed.append(self._process_claim(claim))
        return tuple(processed)

    def _process_accepted(
        self,
        work: OutboundDeliveryWork,
        status: DeliveryWorkStatus,
    ) -> DeliveryWorkStatus:
        if status.state in {
            DeliveryWorkState.COMPLETED,
            DeliveryWorkState.DEAD,
            DeliveryWorkState.CANCELLED,
        }:
            return status
        now = self._clock()
        claim = self._delivery_store.claim_work(
            work.work_id,
            lease_owner=self._id_factory("deliveryworker"),
            now=now,
            lease_expires_at=now + self._lease_duration,
        )
        if claim is None:
            return self._delivery_store.status(work.work_id)
        return self._process_claim(claim)

    def _process_claim(self, claim: ClaimedDeliveryWork) -> DeliveryWorkStatus:
        work = claim.work
        message = self._conversation_store.get_message(work.message_id)
        started_at = self._clock()
        if (
            message.thread_id != work.thread_id
            or conversation_message_hash(message) != work.message_hash
        ):
            return self._record_failure(
                claim,
                started_at=started_at,
                error_code="delivery.message_hash_mismatch",
                force_terminal=True,
            )
        request, decision, authorized_at = work.current_authorization()
        guardian = self._guardian_reader.read_status().payload
        guardian_error = self._guardian_error(guardian, request)
        if guardian_error is not None:
            return self._record_failure(
                claim,
                started_at=started_at,
                error_code=guardian_error,
            )
        route = self._routes.get((work.client_adapter, work.destination_ref))
        if route is None:
            return self._record_failure(
                claim,
                started_at=started_at,
                error_code="delivery.adapter_unconfigured",
                force_terminal=True,
            )
        try:
            authorized = AuthorizedClientDelivery(
                message=message,
                destination_ref=work.destination_ref,
                attempt=claim.attempt,
                idempotency_key=work.idempotency_key,
                authorization_request=request,
                policy_decision=decision,
                authorized_at=authorized_at,
            )
            receipt = route.adapter.send(authorized)
        except ClientDeliveryError as error:
            return self._record_failure(
                claim,
                started_at=started_at,
                error_code=error.reason_code,
                force_terminal=not error.retryable,
            )
        except (ValidationError, ValueError):
            return self._record_failure(
                claim,
                started_at=started_at,
                error_code="delivery.authorization_invalid",
                force_terminal=True,
            )
        except Exception:
            return self._record_failure(
                claim,
                started_at=started_at,
                error_code="delivery.adapter_failed",
            )
        if (
            receipt.message_id != work.message_id
            or receipt.client_adapter != work.client_adapter
            or receipt.destination_ref != work.destination_ref
            or receipt.attempt != claim.attempt
            or receipt.state not in {DeliveryState.SENT, DeliveryState.DELIVERED}
        ):
            return self._record_failure(
                claim,
                started_at=started_at,
                error_code="delivery.adapter_receipt_invalid",
                force_terminal=True,
            )
        completed_at = max(self._clock(), started_at, receipt.attempted_at)
        execution = DeliveryExecutionReceipt(
            action_id=self._id_factory("action"),
            decision_id=decision.decision_id,
            action_hash=request.action_hash,
            capability_id=request.action.capability_id,
            operation=request.action.operation,
            delivery_id=receipt.delivery_id,
            executed_at=completed_at,
            result_summary={
                "delivery_state": receipt.state.value,
                "deduplicated": receipt.adapter_metadata.get("deduplicated", False),
            },
        )
        attempt = DeliveryWorkAttempt(
            attempt_id=self._id_factory("deliveryattempt"),
            work_id=work.work_id,
            message_id=work.message_id,
            attempt=claim.attempt,
            authorization_request_id=request.request_id,
            policy_decision_id=decision.decision_id,
            action_hash=request.action_hash,
            outcome=DeliveryWorkOutcome.SUCCEEDED,
            started_at=started_at,
            completed_at=completed_at,
            adapter_receipt=receipt,
            execution_receipt=execution,
        )
        return self._delivery_store.complete(claim, attempt)

    def _record_failure(
        self,
        claim: ClaimedDeliveryWork,
        *,
        started_at: datetime,
        error_code: QualifiedName,
        force_terminal: bool = False,
    ) -> DeliveryWorkStatus:
        completed_at = max(self._clock(), started_at)
        terminal = force_terminal or claim.attempt >= claim.max_attempts
        retry_at = None
        outcome = DeliveryWorkOutcome.DEAD
        if not terminal:
            retry_at = completed_at + self._retry_delay(claim.work.work_id, claim.attempt)
            outcome = DeliveryWorkOutcome.RETRY_SCHEDULED
        request, decision, _authorized_at = claim.work.current_authorization()
        attempt = DeliveryWorkAttempt(
            attempt_id=self._id_factory("deliveryattempt"),
            work_id=claim.work.work_id,
            message_id=claim.work.message_id,
            attempt=claim.attempt,
            authorization_request_id=request.request_id,
            policy_decision_id=decision.decision_id,
            action_hash=request.action_hash,
            outcome=outcome,
            error_code=error_code,
            started_at=started_at,
            completed_at=completed_at,
            retry_at=retry_at,
        )
        return self._delivery_store.record_failure(claim, attempt)

    def _authorize_owner_action(
        self,
        action: CanonicalAction,
        *,
        now: datetime,
    ) -> tuple[AuthorizationRequest, PolicyDecision]:
        guardian = self._guardian_reader.read_status().payload
        request = AuthorizationRequest(
            request_id=self._id_factory("request"),
            proposal_id=self._id_factory("proposal"),
            principal_id=self._intelligence_id,
            action=action,
            action_hash=action_hash(action),
            guardian_sequence=guardian.sequence,
            requested_at=now,
        )
        decision = self._policy_evaluator.evaluate(
            request,
            PolicyContext(
                guardian_mode=guardian.mode,
                guardian_sequence=guardian.sequence,
                granted_operations=frozenset({f"{action.capability_id}/{action.operation}"}),
                approved_action_hashes=frozenset({request.action_hash}),
                remaining_daily_budget_gbp=self._remaining_daily_budget_gbp,
            ),
            decision_id=self._id_factory("decision"),
            decided_at=now,
        )
        if decision.effect is not DecisionEffect.ALLOW:
            raise DeliveryUnavailableError(decision.reason_codes[0])
        return request, decision

    def _retry_delay(self, work_id: RecordId, attempt: int) -> timedelta:
        digest = hashlib.sha256(f"{work_id}:{attempt}".encode()).digest()
        unit = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
        jitter = 0.75 + (unit * 0.5)
        exponential = self._retry_base.total_seconds() * (2 ** (attempt - 1))
        seconds = min(self._retry_ceiling.total_seconds(), exponential * jitter)
        return timedelta(seconds=max(seconds, 0.001))

    @staticmethod
    def _guardian_error(
        guardian: GuardianStatusPayload,
        request: AuthorizationRequest,
    ) -> QualifiedName | None:
        if guardian.sequence != request.guardian_sequence:
            return "guardian.sequence_mismatch"
        if guardian.mode is not GuardianMode.NORMAL:
            return f"guardian.{guardian.mode.value.replace('-', '_')}"
        return None

    def _route(
        self,
        client_adapter: QualifiedName,
        destination_ref: str,
    ) -> ClientDeliveryRoute:
        try:
            return self._routes[(client_adapter, destination_ref)]
        except KeyError as error:
            raise DeliveryUnavailableError("delivery.route_not_configured") from error

    def _require_thread_owner(
        self,
        principal: AuthenticatedOwner,
        thread_id: RecordId,
    ) -> None:
        if principal.owner_id != self._owner_id:
            raise DeliveryOwnershipError("authenticated principal does not own this runtime")
        thread = self._conversation_store.get_thread(thread_id)
        if thread.owner_id != principal.owner_id:
            raise DeliveryOwnershipError("authenticated principal does not own this thread")
