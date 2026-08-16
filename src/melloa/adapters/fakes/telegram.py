"""Deterministic Telegram source and poll state with no network or credentials."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from datetime import datetime
from threading import RLock

from melloa.domain.base import JsonObject, QualifiedName, utc_now
from melloa.domain.telegram import (
    TelegramInboundUpdate,
    TelegramIngestionReceipt,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramPollRequest,
    TelegramPollState,
    TelegramUpdateId,
    validate_telegram_ingestion_receipt,
    validate_telegram_pairing_confirmation,
)
from melloa.ports.telegram import (
    TelegramPairingChallenge,
    TelegramPairingConflictError,
    TelegramPairingNotFoundError,
    TelegramPollConflictError,
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
