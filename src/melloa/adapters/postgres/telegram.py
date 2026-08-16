"""PostgreSQL persistence for Telegram pairing, ingestion, and poll state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from melloa.domain.base import JsonObject, QualifiedName, RecordId, canonical_json_bytes
from melloa.domain.telegram import (
    TelegramInboundUpdate,
    TelegramIngestionReceipt,
    TelegramOwnerPairing,
    TelegramPairingCandidate,
    TelegramPollState,
    TelegramUpdateId,
    telegram_update_fingerprint,
    validate_telegram_ingestion_receipt,
    validate_telegram_pairing_confirmation,
)
from melloa.ports.telegram import (
    TelegramPairingConflictError,
    TelegramPairingNotFoundError,
    TelegramPollConflictError,
)


class PostgresTelegramPairingStateStore:
    """Persist immutable candidates and pairing authority with revocation history."""

    def __init__(self, connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        self._connection = connection

    def create_candidate(
        self,
        adapter_id: QualifiedName,
        candidate: TelegramPairingCandidate,
    ) -> TelegramPairingCandidate:
        try:
            with self._connection.transaction():
                inserted = self._connection.execute(
                    """
                    INSERT INTO melloa.telegram_pairing_candidates (
                        adapter_id, candidate_id, owner_id, update_id,
                        telegram_user_id, telegram_chat_id, confirmation_code_hash,
                        observed_at, expires_at, document
                    ) VALUES (
                        %(adapter_id)s, %(candidate_id)s, %(owner_id)s, %(update_id)s,
                        %(telegram_user_id)s, %(telegram_chat_id)s,
                        %(confirmation_code_hash)s, %(observed_at)s, %(expires_at)s,
                        %(document)s
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING candidate_id
                    """,
                    {
                        "adapter_id": adapter_id,
                        **candidate.model_dump(exclude={"contract_version"}),
                        "document": Jsonb(candidate.model_dump(mode="json")),
                    },
                ).fetchone()
                if inserted is not None:
                    return candidate
                by_id = self._candidate_row(adapter_id, candidate.candidate_id)
                by_update = self._connection.execute(
                    """
                    SELECT document
                      FROM melloa.telegram_pairing_candidates
                     WHERE adapter_id = %s AND update_id = %s
                    """,
                    (adapter_id, candidate.update_id),
                ).fetchone()
                if by_id is None or by_update is None:
                    raise TelegramPairingConflictError(
                        "Telegram candidate identity or update binding conflicts"
                    )
                persisted_by_id = self._parse_candidate(by_id[0])
                persisted_by_update = self._parse_candidate(by_update[0])
                if persisted_by_id != candidate or persisted_by_update != candidate:
                    raise TelegramPairingConflictError(
                        "Telegram candidate identity or update binding conflicts"
                    )
                return persisted_by_id
        except psycopg.IntegrityError as error:
            raise TelegramPairingConflictError(
                "Telegram candidate conflicts with durable pairing state"
            ) from error

    def get_candidate(
        self,
        adapter_id: QualifiedName,
        candidate_id: RecordId,
    ) -> TelegramPairingCandidate:
        row = self._candidate_row(adapter_id, candidate_id)
        if row is None:
            raise TelegramPairingNotFoundError("Telegram pairing candidate not found")
        return self._parse_candidate(row[0])

    def get_candidate_for_update(
        self,
        adapter_id: QualifiedName,
        update_id: TelegramUpdateId,
    ) -> TelegramPairingCandidate | None:
        row = self._connection.execute(
            """
            SELECT document
              FROM melloa.telegram_pairing_candidates
             WHERE adapter_id = %s AND update_id = %s
            """,
            (adapter_id, update_id),
        ).fetchone()
        return None if row is None else self._parse_candidate(row[0])

    def list_candidates(
        self,
        adapter_id: QualifiedName,
        owner_id: RecordId,
    ) -> tuple[TelegramPairingCandidate, ...]:
        rows = self._connection.execute(
            """
            SELECT document
              FROM melloa.telegram_pairing_candidates
             WHERE adapter_id = %s AND owner_id = %s
             ORDER BY observed_at, candidate_id
            """,
            (adapter_id, owner_id),
        ).fetchall()
        return tuple(self._parse_candidate(row[0]) for row in rows)

    def get_pairing(
        self,
        adapter_id: QualifiedName,
        pairing_id: RecordId,
    ) -> TelegramOwnerPairing:
        row = self._pairing_row(adapter_id, pairing_id)
        if row is None:
            raise TelegramPairingNotFoundError("Telegram owner pairing not found")
        return self._parse_pairing_row(row)

    def get_pairing_for_candidate(
        self,
        adapter_id: QualifiedName,
        candidate_id: RecordId,
    ) -> TelegramOwnerPairing | None:
        row = self._connection.execute(
            """
            SELECT pairing.document, revocation.document
              FROM melloa.telegram_owner_pairings AS pairing
              LEFT JOIN melloa.telegram_pairing_revocations AS revocation
                ON revocation.adapter_id = pairing.adapter_id
               AND revocation.pairing_id = pairing.pairing_id
             WHERE pairing.adapter_id = %s AND pairing.candidate_id = %s
            """,
            (adapter_id, candidate_id),
        ).fetchone()
        return None if row is None else self._parse_pairing_row(row)

    def active_pairing(
        self,
        adapter_id: QualifiedName,
        owner_id: RecordId,
    ) -> TelegramOwnerPairing | None:
        rows = self._connection.execute(
            """
            SELECT pairing.document, revocation.document
              FROM melloa.telegram_active_pairings AS active
              JOIN melloa.telegram_owner_pairings AS pairing
                ON pairing.adapter_id = active.adapter_id
               AND pairing.pairing_id = active.pairing_id
              LEFT JOIN melloa.telegram_pairing_revocations AS revocation
                ON revocation.adapter_id = pairing.adapter_id
               AND revocation.pairing_id = pairing.pairing_id
             WHERE active.adapter_id = %s AND active.owner_id = %s
            """,
            (adapter_id, owner_id),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1 or rows[0][1] is not None:
            raise TelegramPairingConflictError(
                "Telegram active pairing projection conflicts with revocation history"
            )
        return self._parse_pairing_row(rows[0])

    def confirm_pairing(
        self,
        adapter_id: QualifiedName,
        candidate: TelegramPairingCandidate,
        pairing: TelegramOwnerPairing,
    ) -> TelegramOwnerPairing:
        try:
            validate_telegram_pairing_confirmation(candidate, pairing)
        except ValueError as error:
            raise TelegramPairingConflictError(
                "Telegram pairing does not match its durable candidate"
            ) from error
        if pairing.revoked_at is not None:
            raise TelegramPairingConflictError("new Telegram pairing cannot be revoked")

        try:
            with self._connection.transaction():
                if self.get_candidate(adapter_id, candidate.candidate_id) != candidate:
                    raise TelegramPairingConflictError("Telegram pairing candidate changed")
                existing = self.get_pairing_for_candidate(adapter_id, candidate.candidate_id)
                if existing is not None:
                    if existing != pairing:
                        raise TelegramPairingConflictError(
                            "Telegram candidate has a different pairing outcome"
                        )
                    active = self.active_pairing(adapter_id, pairing.owner_id)
                    if active != existing:
                        raise TelegramPairingConflictError(
                            "Telegram pairing outcome is not the active authority"
                        )
                    return existing

                inserted = self._connection.execute(
                    """
                    INSERT INTO melloa.telegram_owner_pairings (
                        adapter_id, pairing_id, candidate_id, owner_id,
                        telegram_user_id, telegram_chat_id, confirmed_by_owner_id,
                        confirmed_at, document
                    ) VALUES (
                        %(adapter_id)s, %(pairing_id)s, %(candidate_id)s,
                        %(owner_id)s, %(telegram_user_id)s, %(telegram_chat_id)s,
                        %(confirmed_by_owner_id)s, %(confirmed_at)s, %(document)s
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING pairing_id
                    """,
                    {
                        "adapter_id": adapter_id,
                        **pairing.model_dump(exclude={"contract_version", "revoked_at"}),
                        "document": Jsonb(pairing.model_dump(mode="json")),
                    },
                ).fetchone()
                if inserted is None:
                    by_id = self._pairing_row(adapter_id, pairing.pairing_id)
                    by_candidate = self.get_pairing_for_candidate(
                        adapter_id,
                        candidate.candidate_id,
                    )
                    if (
                        by_id is None
                        or self._parse_pairing_row(by_id) != pairing
                        or by_candidate != pairing
                    ):
                        raise TelegramPairingConflictError("Telegram pairing identity conflicts")

                activated = self._connection.execute(
                    """
                    INSERT INTO melloa.telegram_active_pairings (
                        adapter_id, owner_id, pairing_id, activated_at
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING pairing_id
                    """,
                    (adapter_id, pairing.owner_id, pairing.pairing_id, pairing.confirmed_at),
                ).fetchone()
                active = self.active_pairing(adapter_id, pairing.owner_id)
                if activated is None and active != pairing:
                    raise TelegramPairingConflictError(
                        "Telegram owner already has an active pairing"
                    )
                return pairing
        except psycopg.IntegrityError as error:
            raise TelegramPairingConflictError(
                "Telegram confirmation conflicts with durable pairing state"
            ) from error

    def revoke_pairing(
        self,
        adapter_id: QualifiedName,
        pairing: TelegramOwnerPairing,
    ) -> TelegramOwnerPairing:
        if pairing.revoked_at is None:
            raise TelegramPairingConflictError("Telegram pairing revocation has no timestamp")
        try:
            with self._connection.transaction():
                existing = self.get_pairing(adapter_id, pairing.pairing_id)
                if existing == pairing:
                    return existing
                if existing.revoked_at is not None or existing.model_copy(
                    update={"revoked_at": pairing.revoked_at}
                ) != pairing:
                    raise TelegramPairingConflictError(
                        "Telegram pairing identity changed on revocation"
                    )
                inserted = self._connection.execute(
                    """
                    INSERT INTO melloa.telegram_pairing_revocations (
                        adapter_id, pairing_id, revoked_at, document
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING pairing_id
                    """,
                    (
                        adapter_id,
                        pairing.pairing_id,
                        pairing.revoked_at,
                        Jsonb(pairing.model_dump(mode="json")),
                    ),
                ).fetchone()
                if inserted is None and self.get_pairing(adapter_id, pairing.pairing_id) != pairing:
                    raise TelegramPairingConflictError(
                        "Telegram pairing revocation conflicts"
                    )
                self._connection.execute(
                    """
                    DELETE FROM melloa.telegram_active_pairings
                     WHERE adapter_id = %s AND owner_id = %s AND pairing_id = %s
                    """,
                    (adapter_id, pairing.owner_id, pairing.pairing_id),
                )
                active = self.active_pairing(adapter_id, pairing.owner_id)
                if active is not None:
                    raise TelegramPairingConflictError(
                        "Telegram revocation did not reduce active authority"
                    )
                return pairing
        except psycopg.IntegrityError as error:
            raise TelegramPairingConflictError(
                "Telegram revocation conflicts with durable pairing state"
            ) from error

    def _candidate_row(
        self,
        adapter_id: QualifiedName,
        candidate_id: RecordId,
    ) -> tuple[object, ...] | None:
        return self._connection.execute(
            """
            SELECT document
              FROM melloa.telegram_pairing_candidates
             WHERE adapter_id = %s AND candidate_id = %s
            """,
            (adapter_id, candidate_id),
        ).fetchone()

    def _pairing_row(
        self,
        adapter_id: QualifiedName,
        pairing_id: RecordId,
    ) -> tuple[object, ...] | None:
        return self._connection.execute(
            """
            SELECT pairing.document, revocation.document
              FROM melloa.telegram_owner_pairings AS pairing
              LEFT JOIN melloa.telegram_pairing_revocations AS revocation
                ON revocation.adapter_id = pairing.adapter_id
               AND revocation.pairing_id = pairing.pairing_id
             WHERE pairing.adapter_id = %s AND pairing.pairing_id = %s
            """,
            (adapter_id, pairing_id),
        ).fetchone()

    @staticmethod
    def _parse_candidate(document: object) -> TelegramPairingCandidate:
        try:
            return TelegramPairingCandidate.model_validate_json(
                canonical_json_bytes(cast(JsonObject, document))
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise TelegramPairingConflictError(
                "durable Telegram candidate document is invalid"
            ) from error

    @classmethod
    def _parse_pairing_row(cls, row: tuple[object, ...]) -> TelegramOwnerPairing:
        try:
            confirmed = TelegramOwnerPairing.model_validate_json(
                canonical_json_bytes(cast(JsonObject, row[0]))
            )
            if confirmed.revoked_at is not None:
                raise ValueError("confirmed pairing document contains a revocation")
            if row[1] is None:
                return confirmed
            revoked = TelegramOwnerPairing.model_validate_json(
                canonical_json_bytes(cast(JsonObject, row[1]))
            )
            if revoked.revoked_at is None or confirmed.model_copy(
                update={"revoked_at": revoked.revoked_at}
            ) != revoked:
                raise ValueError("revocation document changed pairing identity")
            return revoked
        except (ValidationError, TypeError, ValueError) as error:
            raise TelegramPairingConflictError(
                "durable Telegram pairing document is invalid"
            ) from error


class PostgresTelegramPollStateStore:
    """Atomically retain normalized outcomes before advancing the Telegram cursor."""

    def __init__(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        adapter_id: QualifiedName,
        initialized_at: datetime,
    ) -> None:
        self._connection = connection
        self._adapter_id = adapter_id
        self._initialize(initialized_at)

    def read_state(self, adapter_id: QualifiedName) -> TelegramPollState:
        self._require_adapter(adapter_id)
        row = self._connection.execute(
            "SELECT document FROM melloa.telegram_poll_states WHERE adapter_id = %s",
            (adapter_id,),
        ).fetchone()
        if row is None:
            raise TelegramPollConflictError("Telegram poll state is missing")
        return self._parse_state(row[0])

    def get_receipt(
        self,
        adapter_id: QualifiedName,
        update_id: TelegramUpdateId,
    ) -> TelegramIngestionReceipt | None:
        self._require_adapter(adapter_id)
        row = self._connection.execute(
            """
            SELECT document
              FROM melloa.telegram_ingestion_receipts
             WHERE adapter_id = %s AND update_id = %s
            """,
            (adapter_id, update_id),
        ).fetchone()
        return None if row is None else self._parse_receipt(row[0])

    def get_update(
        self,
        adapter_id: QualifiedName,
        update_id: TelegramUpdateId,
    ) -> TelegramInboundUpdate | None:
        self._require_adapter(adapter_id)
        row = self._connection.execute(
            """
            SELECT document
              FROM melloa.telegram_inbound_updates
             WHERE adapter_id = %s AND update_id = %s
            """,
            (adapter_id, update_id),
        ).fetchone()
        return None if row is None else self._parse_update(row[0])

    def list_ingested_receipts(
        self,
        adapter_id: QualifiedName,
        *,
        after_update_id: TelegramUpdateId | None = None,
        limit: int = 100,
    ) -> tuple[TelegramIngestionReceipt, ...]:
        self._require_adapter(adapter_id)
        if not 1 <= limit <= 1_000:
            raise ValueError("Telegram receipt scan limit must be between 1 and 1000")
        rows = self._connection.execute(
            """
            SELECT document
              FROM melloa.telegram_ingestion_receipts
             WHERE adapter_id = %(adapter_id)s
               AND disposition = 'ingested'
               AND (%(after_update_id)s::bigint IS NULL OR update_id > %(after_update_id)s)
             ORDER BY update_id
             LIMIT %(limit)s
            """,
            {
                "adapter_id": adapter_id,
                "after_update_id": after_update_id,
                "limit": limit,
            },
        ).fetchall()
        return tuple(self._parse_receipt(row[0]) for row in rows)

    def commit_ingestion(
        self,
        update: TelegramInboundUpdate,
        receipt: TelegramIngestionReceipt,
        *,
        expected_revision: int,
    ) -> TelegramPollState:
        self._require_adapter(receipt.adapter_id)
        try:
            with self._connection.transaction():
                existing_update = self.get_update(self._adapter_id, update.update_id)
                existing_receipt = self.get_receipt(self._adapter_id, update.update_id)
                if existing_update is not None or existing_receipt is not None:
                    if existing_update != update or existing_receipt != receipt:
                        raise TelegramPollConflictError(
                            "Telegram update ID has different immutable ingestion data"
                        )
                    return self.read_state(self._adapter_id)

                validate_telegram_ingestion_receipt(update, receipt)
                state_row = self._connection.execute(
                    """
                    SELECT document
                      FROM melloa.telegram_poll_states
                     WHERE adapter_id = %s
                     FOR UPDATE
                    """,
                    (self._adapter_id,),
                ).fetchone()
                if state_row is None:
                    raise TelegramPollConflictError("Telegram poll state is missing")
                state = self._parse_state(state_row[0])
                if expected_revision != state.revision:
                    raise TelegramPollConflictError("Telegram poll state revision is stale")
                if receipt.update_id < state.next_offset:
                    raise TelegramPollConflictError("Telegram poll offset cannot move backwards")
                if receipt.recorded_at < state.updated_at:
                    raise TelegramPollConflictError("Telegram receipt predates poll state")

                self._connection.execute(
                    """
                    INSERT INTO melloa.telegram_inbound_updates (
                        adapter_id, update_id, update_fingerprint,
                        source_payload_hash, received_at, document
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self._adapter_id,
                        update.update_id,
                        telegram_update_fingerprint(update),
                        update.source_payload_hash,
                        update.received_at,
                        Jsonb(update.model_dump(mode="json")),
                    ),
                )
                self._connection.execute(
                    """
                    INSERT INTO melloa.telegram_ingestion_receipts (
                        adapter_id, update_id, receipt_id, update_fingerprint,
                        disposition, recorded_at, canonical_message_id, pairing_id,
                        pairing_candidate_id, reason_code, document
                    ) VALUES (
                        %(adapter_id)s, %(update_id)s, %(receipt_id)s,
                        %(update_fingerprint)s, %(disposition)s, %(recorded_at)s,
                        %(canonical_message_id)s, %(pairing_id)s,
                        %(pairing_candidate_id)s, %(reason_code)s, %(document)s
                    )
                    """,
                    {
                        "adapter_id": self._adapter_id,
                        **receipt.model_dump(exclude={"contract_version", "attachment_receipts"}),
                        "disposition": receipt.disposition.value,
                        "document": Jsonb(receipt.model_dump(mode="json")),
                    },
                )
                advanced = TelegramPollState(
                    adapter_id=self._adapter_id,
                    next_offset=receipt.update_id + 1,
                    revision=state.revision + 1,
                    last_update_id=receipt.update_id,
                    last_receipt_id=receipt.receipt_id,
                    updated_at=receipt.recorded_at,
                )
                updated = self._connection.execute(
                    """
                    UPDATE melloa.telegram_poll_states
                       SET next_offset = %(next_offset)s,
                           revision = %(revision)s,
                           last_update_id = %(last_update_id)s,
                           last_receipt_id = %(last_receipt_id)s,
                           updated_at = %(updated_at)s,
                           document = %(document)s
                     WHERE adapter_id = %(adapter_id)s
                       AND revision = %(expected_revision)s
                    RETURNING adapter_id
                    """,
                    {
                        **advanced.model_dump(exclude={"contract_version"}),
                        "expected_revision": expected_revision,
                        "document": Jsonb(advanced.model_dump(mode="json")),
                    },
                ).fetchone()
                if updated is None:
                    raise TelegramPollConflictError("Telegram poll state revision is stale")
                return advanced
        except psycopg.IntegrityError as error:
            raise TelegramPollConflictError(
                "Telegram ingestion conflicts with durable poll state"
            ) from error

    def _initialize(self, initialized_at: datetime) -> None:
        initial = TelegramPollState(
            adapter_id=self._adapter_id,
            updated_at=initialized_at,
        )
        try:
            with self._connection.transaction():
                self._connection.execute(
                    """
                    INSERT INTO melloa.telegram_poll_states (
                        adapter_id, next_offset, revision, last_update_id,
                        last_receipt_id, updated_at, document
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (adapter_id) DO NOTHING
                    """,
                    (
                        initial.adapter_id,
                        initial.next_offset,
                        initial.revision,
                        initial.last_update_id,
                        initial.last_receipt_id,
                        initial.updated_at,
                        Jsonb(initial.model_dump(mode="json")),
                    ),
                )
                persisted = self.read_state(self._adapter_id)
                if persisted.adapter_id != self._adapter_id:
                    raise TelegramPollConflictError(
                        "Telegram poll state adapter is not configured"
                    )
        except psycopg.IntegrityError as error:
            raise TelegramPollConflictError(
                "Telegram poll state initialization conflicts"
            ) from error

    def _require_adapter(self, adapter_id: QualifiedName) -> None:
        if adapter_id != self._adapter_id:
            raise TelegramPollConflictError("Telegram poll state adapter is not configured")

    @staticmethod
    def _parse_state(document: object) -> TelegramPollState:
        try:
            return TelegramPollState.model_validate_json(
                canonical_json_bytes(cast(JsonObject, document))
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise TelegramPollConflictError(
                "durable Telegram poll state document is invalid"
            ) from error

    @staticmethod
    def _parse_update(document: object) -> TelegramInboundUpdate:
        try:
            return TelegramInboundUpdate.model_validate_json(
                canonical_json_bytes(cast(JsonObject, document))
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise TelegramPollConflictError(
                "durable Telegram update document is invalid"
            ) from error

    @staticmethod
    def _parse_receipt(document: object) -> TelegramIngestionReceipt:
        try:
            receipt = TelegramIngestionReceipt.model_validate_json(
                canonical_json_bytes(cast(JsonObject, document))
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise TelegramPollConflictError(
                "durable Telegram receipt document is invalid"
            ) from error
        return receipt
