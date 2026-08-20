"""PostgreSQL cursor and delivery state for one exact-owner Telegram channel."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import psycopg
from psycopg import sql

from melloa.domain.base import QualifiedName, RecordId
from melloa.domain.models import ModelRoute
from melloa.domain.telegram import (
    TelegramDelivery,
    TelegramDeliveryKind,
    TelegramDeliveryState,
    TelegramOwnerChannel,
)
from melloa.ports.telegram import TelegramDeliverySummary, TelegramStateConflictError

_CHANNEL_KEY = "owner.telegram"
_CHANNEL_LOCK_ID = 8_412_259_107_311
_DELIVERY_COLUMNS = sql.SQL("""
    update_id, incoming_message_id, delivery_kind, inbound_message_id,
    response_message_id, notice_code, control_text, state, sent_part_count,
    telegram_message_ids, attempt_count, max_attempts, available_at,
    lease_owner, lease_expires_at, last_error_code, created_at, updated_at,
    delivered_at
""")


class PostgresTelegramStore:
    def __init__(self, connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        self._connection = connection

    def bind_owner_channel(
        self,
        *,
        owner_user_id: int,
        owner_chat_id: int,
        initial_model_route: ModelRoute,
        now: datetime,
    ) -> TelegramOwnerChannel:
        with self._connection.transaction():
            self._lock_channel()
            self._connection.execute(
                """
                INSERT INTO melloa.telegram_owner_channels (
                    channel_key, owner_user_id, owner_chat_id,
                    model_route, last_update_id, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, NULL, %s, %s)
                ON CONFLICT (channel_key) DO NOTHING
                """,
                (
                    _CHANNEL_KEY,
                    owner_user_id,
                    owner_chat_id,
                    initial_model_route.value,
                    now,
                    now,
                ),
            )
            channel = self._read_channel(for_update=True)
            if (
                channel.owner_user_id != owner_user_id
                or channel.owner_chat_id != owner_chat_id
            ):
                raise TelegramStateConflictError(
                    "configured Telegram owner conflicts with the durable binding"
                )
            return channel

    def owner_channel(self) -> TelegramOwnerChannel:
        return self._read_channel(for_update=False)

    def advance_update(self, update_id: int, *, now: datetime) -> TelegramOwnerChannel:
        if update_id < 0:
            raise ValueError("Telegram update ID cannot be negative")
        with self._connection.transaction():
            self._lock_channel()
            channel = self._read_channel(for_update=True)
            if channel.last_update_id is None or update_id > channel.last_update_id:
                self._connection.execute(
                    """
                    UPDATE melloa.telegram_owner_channels
                       SET last_update_id = %s,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE channel_key = %s
                    """,
                    (update_id, now, _CHANNEL_KEY),
                )
                channel = self._read_channel(for_update=True)
            return channel

    def accept_conversation_update(
        self,
        *,
        update_id: int,
        incoming_message_id: int,
        inbound_message_id: RecordId,
        now: datetime,
        max_attempts: int,
    ) -> TelegramDelivery:
        return self._accept_delivery(
            update_id=update_id,
            incoming_message_id=incoming_message_id,
            kind=TelegramDeliveryKind.CONVERSATION,
            inbound_message_id=inbound_message_id,
            control_text=None,
            now=now,
            max_attempts=max_attempts,
            model_route=None,
        )

    def accept_status_update(
        self,
        *,
        update_id: int,
        incoming_message_id: int,
        now: datetime,
        max_attempts: int,
    ) -> TelegramDelivery:
        return self._accept_delivery(
            update_id=update_id,
            incoming_message_id=incoming_message_id,
            kind=TelegramDeliveryKind.STATUS,
            inbound_message_id=None,
            control_text=None,
            now=now,
            max_attempts=max_attempts,
            model_route=None,
        )

    def accept_control_update(
        self,
        *,
        update_id: int,
        incoming_message_id: int,
        control_text: str,
        now: datetime,
        max_attempts: int,
    ) -> TelegramDelivery:
        return self._accept_delivery(
            update_id=update_id,
            incoming_message_id=incoming_message_id,
            kind=TelegramDeliveryKind.CONTROL,
            inbound_message_id=None,
            control_text=control_text,
            now=now,
            max_attempts=max_attempts,
            model_route=None,
        )

    def accept_model_route_update(
        self,
        *,
        update_id: int,
        incoming_message_id: int,
        model_route: ModelRoute | None,
        now: datetime,
        max_attempts: int,
    ) -> TelegramDelivery:
        return self._accept_delivery(
            update_id=update_id,
            incoming_message_id=incoming_message_id,
            kind=TelegramDeliveryKind.MODEL_ROUTE,
            inbound_message_id=None,
            control_text=None,
            now=now,
            max_attempts=max_attempts,
            model_route=model_route,
        )

    def awaiting_conversation_deliveries(self, *, limit: int) -> tuple[TelegramDelivery, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("Telegram awaiting-delivery limit must be between 1 and 100")
        rows = self._connection.execute(
            sql.SQL("""
            SELECT {}
              FROM melloa.telegram_deliveries
             WHERE channel_key = %s
               AND state = 'awaiting_reply'
             ORDER BY update_id
             LIMIT %s
            """).format(_DELIVERY_COLUMNS),
            (_CHANNEL_KEY, limit),
        ).fetchall()
        return tuple(self._delivery(row) for row in rows)

    def mark_conversation_ready(
        self,
        update_id: int,
        *,
        response_message_id: RecordId,
        now: datetime,
    ) -> TelegramDelivery:
        return self._mark_conversation_response(
            update_id,
            response_message_id=response_message_id,
            notice_code=None,
            now=now,
        )

    def mark_conversation_notice_ready(
        self,
        update_id: int,
        *,
        notice_code: QualifiedName,
        now: datetime,
    ) -> TelegramDelivery:
        return self._mark_conversation_response(
            update_id,
            response_message_id=None,
            notice_code=notice_code,
            now=now,
        )

    def claim_next_delivery(
        self,
        *,
        lease_owner: RecordId,
        now: datetime,
        lease_expires_at: datetime,
    ) -> TelegramDelivery | None:
        if lease_expires_at <= now:
            raise ValueError("Telegram delivery lease must expire in the future")
        with self._connection.transaction():
            self._connection.execute(
                """
                UPDATE melloa.telegram_deliveries
                   SET state = 'dead',
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       last_error_code = 'telegram.delivery_lease_expired',
                       updated_at = GREATEST(updated_at, %s)
                 WHERE channel_key = %s
                   AND state = 'running'
                   AND lease_expires_at <= %s
                   AND attempt_count >= max_attempts
                """,
                (now, _CHANNEL_KEY, now),
            )
            row = self._connection.execute(
                sql.SQL("""
                SELECT {}
                  FROM melloa.telegram_deliveries
                 WHERE channel_key = %s
                   AND attempt_count < max_attempts
                   AND (
                       (state = 'ready' AND available_at <= %s)
                       OR (state = 'running' AND lease_expires_at <= %s)
                   )
                 ORDER BY available_at, update_id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
                """).format(_DELIVERY_COLUMNS),
                (_CHANNEL_KEY, now, now),
            ).fetchone()
            if row is None:
                return None
            update_id = int(row[0])
            claimed = self._connection.execute(
                sql.SQL("""
                UPDATE melloa.telegram_deliveries
                   SET state = 'running',
                       attempt_count = attempt_count + 1,
                       lease_owner = %s,
                       lease_expires_at = %s,
                       updated_at = GREATEST(updated_at, %s)
                 WHERE update_id = %s
                 RETURNING {}
                """).format(_DELIVERY_COLUMNS),
                (lease_owner, lease_expires_at, now, update_id),
            ).fetchone()
            if claimed is None:
                raise TelegramStateConflictError("Telegram delivery disappeared while claimed")
            return self._delivery(claimed)

    def record_delivery_part(
        self,
        claim: TelegramDelivery,
        *,
        telegram_message_id: int,
        now: datetime,
    ) -> TelegramDelivery:
        if telegram_message_id < 0:
            raise ValueError("Telegram message ID cannot be negative")
        with self._connection.transaction():
            existing = self._read_delivery(claim.update_id, for_update=True)
            if (
                existing.sent_part_count == claim.sent_part_count + 1
                and existing.telegram_message_ids[-1] == telegram_message_id
            ):
                return existing
            self._require_active_claim(existing, claim)
            if existing.sent_part_count != claim.sent_part_count:
                raise TelegramStateConflictError("Telegram response part order conflicts")
            row = self._connection.execute(
                sql.SQL("""
                UPDATE melloa.telegram_deliveries
                   SET sent_part_count = sent_part_count + 1,
                       telegram_message_ids = array_append(telegram_message_ids, %s),
                       updated_at = GREATEST(updated_at, %s)
                 WHERE update_id = %s
                 RETURNING {}
                """).format(_DELIVERY_COLUMNS),
                (telegram_message_id, now, claim.update_id),
            ).fetchone()
            if row is None:
                raise TelegramStateConflictError("Telegram delivery disappeared during send")
            return self._delivery(row)

    def complete_delivery(
        self,
        claim: TelegramDelivery,
        *,
        now: datetime,
    ) -> TelegramDelivery:
        with self._connection.transaction():
            existing = self._read_delivery(claim.update_id, for_update=True)
            if existing.state is TelegramDeliveryState.SENT:
                return existing
            self._require_active_claim(existing, claim)
            if existing.sent_part_count < 1:
                raise TelegramStateConflictError("empty Telegram response cannot complete")
            row = self._connection.execute(
                sql.SQL("""
                UPDATE melloa.telegram_deliveries
                   SET state = 'sent',
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       last_error_code = NULL,
                       delivered_at = %s,
                       updated_at = GREATEST(updated_at, %s)
                 WHERE update_id = %s
                 RETURNING {}
                """).format(_DELIVERY_COLUMNS),
                (now, now, claim.update_id),
            ).fetchone()
            if row is None:
                raise TelegramStateConflictError("Telegram delivery disappeared on completion")
            return self._delivery(row)

    def record_delivery_failure(
        self,
        claim: TelegramDelivery,
        *,
        error_code: QualifiedName,
        retry_at: datetime,
        now: datetime,
    ) -> TelegramDelivery:
        if retry_at <= now:
            raise ValueError("Telegram retry must be scheduled in the future")
        with self._connection.transaction():
            existing = self._read_delivery(claim.update_id, for_update=True)
            self._require_active_claim(existing, claim)
            next_state = (
                TelegramDeliveryState.DEAD
                if existing.attempt_count >= existing.max_attempts
                else TelegramDeliveryState.READY
            )
            available_at = now if next_state is TelegramDeliveryState.DEAD else retry_at
            row = self._connection.execute(
                sql.SQL("""
                UPDATE melloa.telegram_deliveries
                   SET state = %s,
                       available_at = %s,
                       lease_owner = NULL,
                       lease_expires_at = NULL,
                       last_error_code = %s,
                       updated_at = GREATEST(updated_at, %s)
                 WHERE update_id = %s
                 RETURNING {}
                """).format(_DELIVERY_COLUMNS),
                (next_state.value, available_at, error_code, now, claim.update_id),
            ).fetchone()
            if row is None:
                raise TelegramStateConflictError("Telegram delivery disappeared after failure")
            return self._delivery(row)

    def delivery_summary(self) -> TelegramDeliverySummary:
        rows = self._connection.execute(
            """
            SELECT state, count(*)
              FROM melloa.telegram_deliveries
             WHERE channel_key = %s
             GROUP BY state
            """,
            (_CHANNEL_KEY,),
        ).fetchall()
        counts = {str(state): int(count) for state, count in rows}
        return TelegramDeliverySummary(
            awaiting_reply=counts.get(TelegramDeliveryState.AWAITING_REPLY.value, 0),
            ready=counts.get(TelegramDeliveryState.READY.value, 0),
            running=counts.get(TelegramDeliveryState.RUNNING.value, 0),
            sent=counts.get(TelegramDeliveryState.SENT.value, 0),
            dead=counts.get(TelegramDeliveryState.DEAD.value, 0),
        )

    def _accept_delivery(
        self,
        *,
        update_id: int,
        incoming_message_id: int,
        kind: TelegramDeliveryKind,
        inbound_message_id: RecordId | None,
        control_text: str | None,
        now: datetime,
        max_attempts: int,
        model_route: ModelRoute | None,
    ) -> TelegramDelivery:
        if update_id < 0 or incoming_message_id < 0:
            raise ValueError("Telegram update and message IDs cannot be negative")
        if not 1 <= max_attempts <= 100:
            raise ValueError("Telegram delivery attempts must be between 1 and 100")
        if control_text is not None and not 1 <= len(control_text) <= 70_000:
            raise ValueError("Telegram control text must contain between 1 and 70,000 characters")
        initial_state = (
            TelegramDeliveryState.AWAITING_REPLY
            if kind is TelegramDeliveryKind.CONVERSATION
            else TelegramDeliveryState.READY
        )
        with self._connection.transaction():
            self._lock_channel()
            channel = self._read_channel(for_update=True)
            notice_code = (
                None
                if kind is not TelegramDeliveryKind.MODEL_ROUTE
                else f"telegram.model_route.{(model_route or channel.model_route).value}"
            )
            existing_row = self._connection.execute(
                sql.SQL("""
                SELECT {}
                  FROM melloa.telegram_deliveries
                 WHERE update_id = %s
                 FOR UPDATE
                """).format(_DELIVERY_COLUMNS),
                (update_id,),
            ).fetchone()
            if existing_row is None:
                if channel.last_update_id is not None and update_id <= channel.last_update_id:
                    raise TelegramStateConflictError(
                        "Telegram update was already acknowledged without a response"
                    )
                self._connection.execute(
                    """
                    INSERT INTO melloa.telegram_deliveries (
                        update_id, channel_key, incoming_message_id, delivery_kind,
                        inbound_message_id, notice_code, control_text, state, max_attempts,
                        available_at, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        update_id,
                        _CHANNEL_KEY,
                        incoming_message_id,
                        kind.value,
                        inbound_message_id,
                        notice_code,
                        control_text,
                        initial_state.value,
                        max_attempts,
                        now,
                        now,
                        now,
                    ),
                )
                if kind is TelegramDeliveryKind.MODEL_ROUTE and model_route is not None:
                    self._connection.execute(
                        """
                        UPDATE melloa.telegram_owner_channels
                           SET model_route = %s,
                               updated_at = GREATEST(updated_at, %s)
                         WHERE channel_key = %s
                        """,
                        (model_route.value, now, _CHANNEL_KEY),
                    )
            else:
                existing = self._delivery(existing_row)
                if (
                    existing.incoming_message_id != incoming_message_id
                    or existing.kind is not kind
                    or existing.inbound_message_id != inbound_message_id
                    or existing.control_text != control_text
                    or (
                        kind is TelegramDeliveryKind.MODEL_ROUTE
                        and model_route is not None
                        and existing.notice_code != notice_code
                    )
                ):
                    raise TelegramStateConflictError("Telegram update identity conflicts")
            if channel.last_update_id is None or update_id > channel.last_update_id:
                self._connection.execute(
                    """
                    UPDATE melloa.telegram_owner_channels
                       SET last_update_id = %s,
                           updated_at = GREATEST(updated_at, %s)
                     WHERE channel_key = %s
                    """,
                    (update_id, now, _CHANNEL_KEY),
                )
            return self._read_delivery(update_id, for_update=True)

    def _mark_conversation_response(
        self,
        update_id: int,
        *,
        response_message_id: RecordId | None,
        notice_code: QualifiedName | None,
        now: datetime,
    ) -> TelegramDelivery:
        if (response_message_id is None) == (notice_code is None):
            raise ValueError("Telegram conversation needs exactly one response source")
        with self._connection.transaction():
            existing = self._read_delivery(update_id, for_update=True)
            if existing.kind is not TelegramDeliveryKind.CONVERSATION:
                raise TelegramStateConflictError("Telegram update is not a conversation")
            if existing.state is not TelegramDeliveryState.AWAITING_REPLY:
                if (
                    existing.response_message_id == response_message_id
                    and existing.notice_code == notice_code
                ):
                    return existing
                raise TelegramStateConflictError("Telegram conversation response conflicts")
            row = self._connection.execute(
                sql.SQL("""
                UPDATE melloa.telegram_deliveries
                   SET response_message_id = %s,
                       notice_code = %s,
                       state = 'ready',
                       available_at = %s,
                       updated_at = GREATEST(updated_at, %s)
                 WHERE update_id = %s
                 RETURNING {}
                """).format(_DELIVERY_COLUMNS),
                (response_message_id, notice_code, now, now, update_id),
            ).fetchone()
            if row is None:
                raise TelegramStateConflictError("Telegram delivery disappeared while readied")
            return self._delivery(row)

    def _read_channel(self, *, for_update: bool) -> TelegramOwnerChannel:
        suffix = sql.SQL("FOR UPDATE") if for_update else sql.SQL("")
        row = self._connection.execute(
            sql.SQL("""
            SELECT owner_user_id, owner_chat_id, model_route, last_update_id,
                   created_at, updated_at
              FROM melloa.telegram_owner_channels
             WHERE channel_key = %s
             {}
            """).format(suffix),
            (_CHANNEL_KEY,),
        ).fetchone()
        if row is None:
            raise TelegramStateConflictError("Telegram owner channel is not bound")
        return TelegramOwnerChannel(
            owner_user_id=int(row[0]),
            owner_chat_id=int(row[1]),
            model_route=ModelRoute(str(row[2])),
            last_update_id=None if row[3] is None else int(row[3]),
            created_at=cast(datetime, row[4]),
            updated_at=cast(datetime, row[5]),
        )

    def _read_delivery(self, update_id: int, *, for_update: bool) -> TelegramDelivery:
        suffix = sql.SQL("FOR UPDATE") if for_update else sql.SQL("")
        row = self._connection.execute(
            sql.SQL("""
            SELECT {}
              FROM melloa.telegram_deliveries
             WHERE update_id = %s
             {}
            """).format(_DELIVERY_COLUMNS, suffix),
            (update_id,),
        ).fetchone()
        if row is None:
            raise TelegramStateConflictError(f"Telegram delivery not found: {update_id}")
        return self._delivery(row)

    @staticmethod
    def _delivery(row: tuple[Any, ...]) -> TelegramDelivery:
        return TelegramDelivery(
            update_id=int(row[0]),
            incoming_message_id=int(row[1]),
            kind=TelegramDeliveryKind(str(row[2])),
            inbound_message_id=None if row[3] is None else str(row[3]),
            response_message_id=None if row[4] is None else str(row[4]),
            notice_code=None if row[5] is None else str(row[5]),
            control_text=None if row[6] is None else str(row[6]),
            state=TelegramDeliveryState(str(row[7])),
            sent_part_count=int(row[8]),
            telegram_message_ids=tuple(int(value) for value in row[9]),
            attempt_count=int(row[10]),
            max_attempts=int(row[11]),
            available_at=cast(datetime, row[12]),
            lease_owner=None if row[13] is None else str(row[13]),
            lease_expires_at=None if row[14] is None else cast(datetime, row[14]),
            last_error_code=None if row[15] is None else str(row[15]),
            created_at=cast(datetime, row[16]),
            updated_at=cast(datetime, row[17]),
            delivered_at=None if row[18] is None else cast(datetime, row[18]),
        )

    @staticmethod
    def _require_active_claim(
        existing: TelegramDelivery,
        claim: TelegramDelivery,
    ) -> None:
        if (
            claim.state is not TelegramDeliveryState.RUNNING
            or existing.state is not TelegramDeliveryState.RUNNING
            or existing.update_id != claim.update_id
            or existing.attempt_count != claim.attempt_count
            or existing.lease_owner != claim.lease_owner
            or existing.lease_expires_at != claim.lease_expires_at
        ):
            raise TelegramStateConflictError("Telegram delivery lease is stale")

    def _lock_channel(self) -> None:
        self._connection.execute("SELECT pg_advisory_xact_lock(%s)", (_CHANNEL_LOCK_ID,))


__all__ = ["PostgresTelegramStore"]
