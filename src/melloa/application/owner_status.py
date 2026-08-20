"""Short owner-facing health summary for the normal Telegram interface."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from melloa.domain.base import AwareDatetime, ContractModel, RecordId, utc_now
from melloa.domain.conversation import ConversationProcessingState
from melloa.domain.guardian import GuardianMode
from melloa.domain.models import ModelGatewayHealth, ModelHealthState, ModelRoute
from melloa.ports.conversation import ConversationNotFoundError, ConversationStore
from melloa.ports.guardian import GuardianStatusReader
from melloa.ports.telegram import TelegramStore
from melloa.release import CURRENT_RELEASE

_MAX_BACKUP_MARKER_BYTES = 4_096


class BackupResult(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class BackupMarker(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_version: Literal["1.0.0"] = "1.0.0"
    result: BackupResult
    checked_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    snapshot_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_.-]{1,127}$")

    @model_validator(mode="after")
    def validate_result_details(self) -> BackupMarker:
        if self.result is BackupResult.SUCCESS:
            if (
                self.completed_at is None
                or self.snapshot_id is None
                or self.reason_code is not None
            ):
                raise ValueError("successful backup marker requires completion and snapshot")
        elif (
            self.completed_at is not None
            or self.snapshot_id is not None
            or self.reason_code is None
        ):
            raise ValueError("failed backup marker requires only a reason code")
        return self


@dataclass(frozen=True)
class OwnerModelRoutes:
    capable_model_id: str
    economy_model_id: str
    health: Callable[[ModelRoute], ModelGatewayHealth]
    selected: Callable[[], ModelRoute]


class OwnerStatusReporter:
    def __init__(
        self,
        *,
        guardian_reader: GuardianStatusReader,
        conversation_store: ConversationStore,
        telegram_store: TelegramStore,
        thread_id: RecordId,
        model_id: str | None,
        model_health: Callable[[], ModelGatewayHealth] | None,
        backup_status_file: Path | None,
        model_routes: OwnerModelRoutes | None = None,
        clock: Callable[[], datetime] = utc_now,
        backup_stale_after: timedelta = timedelta(hours=26),
    ) -> None:
        if backup_stale_after <= timedelta(0):
            raise ValueError("backup stale interval must be positive")
        if model_routes is not None and (model_id is not None or model_health is not None):
            raise ValueError("single-model and routed-model status cannot be combined")
        self._guardian_reader = guardian_reader
        self._conversation_store = conversation_store
        self._telegram_store = telegram_store
        self._thread_id = thread_id
        self._model_id = model_id
        self._model_health = model_health
        self._backup_status_file = backup_status_file
        self._model_routes = model_routes
        self._clock = clock
        self._backup_stale_after = backup_stale_after

    def render(self) -> str:
        degraded = False

        try:
            guardian_mode = self._guardian_reader.read_status().payload.mode
            guardian_text = guardian_mode.value
            if guardian_mode in {
                GuardianMode.READ_ONLY,
                GuardianMode.STOPPED,
                GuardianMode.RECOVERY,
            }:
                degraded = True
        except Exception:
            guardian_text = "unverified"
            degraded = True

        model_lines, model_degraded = self._model_summary()
        degraded = degraded or model_degraded

        conversation_pending, conversation_failed, conversation_unknown = (
            self._conversation_summary()
        )
        degraded = degraded or conversation_failed > 0 or conversation_unknown

        try:
            deliveries = self._telegram_store.delivery_summary()
            delivery_text = f"{deliveries.pending} deliveries"
            delivery_failed = deliveries.dead
        except Exception:
            delivery_text = "unknown deliveries"
            delivery_failed = 0
            degraded = True
        degraded = degraded or delivery_failed > 0

        backup_text, backup_degraded = self._backup_summary()
        degraded = degraded or backup_degraded
        failed = conversation_failed + delivery_failed

        return "\n".join(
            (
                "Melli status",
                f"Overall: {'degraded' if degraded else 'healthy'}",
                f"Release: {CURRENT_RELEASE.release_display}",
                *model_lines,
                f"Backlog: {conversation_pending} replies, {delivery_text}; {failed} failed",
                f"Guardian: {guardian_text}",
                f"Backup: {backup_text}",
            )
        )

    def _model_summary(self) -> tuple[tuple[str, ...], bool]:
        if self._model_routes is not None:
            return self._routed_model_summary()
        if self._model_id is None or self._model_health is None:
            return ("Model: not configured",), True
        model_id = _single_line(self._model_id)
        try:
            health = self._model_health()
        except Exception:
            return (f"Model: {model_id} — unavailable",), True
        return (
            (f"Model: {model_id} — {health.state.value}",),
            health.state is not ModelHealthState.HEALTHY,
        )

    def _routed_model_summary(self) -> tuple[tuple[str, ...], bool]:
        routes = self._model_routes
        if routes is None:
            raise RuntimeError("routed model status is unavailable")
        degraded = False
        try:
            selected = routes.selected().value
        except Exception:
            selected = "unknown"
            degraded = True
        summaries: list[str] = []
        for route, model_id in (
            (ModelRoute.ECONOMY, routes.economy_model_id),
            (ModelRoute.CAPABLE, routes.capable_model_id),
        ):
            try:
                health = routes.health(route)
                state = health.state.value
                degraded = degraded or health.state is not ModelHealthState.HEALTHY
            except Exception:
                state = "unavailable"
                degraded = True
            summaries.append(f"{route.value} {_single_line(model_id)} — {state}")
        return (
            (
                f"Route: {selected}",
                f"Models: {'; '.join(summaries)}",
            ),
            degraded,
        )

    def _conversation_summary(self) -> tuple[int, int, bool]:
        try:
            processing = self._conversation_store.list_reply_processing(self._thread_id)
        except ConversationNotFoundError:
            return 0, 0, False
        except Exception:
            return 0, 0, True
        pending = sum(
            item.state
            in {
                ConversationProcessingState.READY,
                ConversationProcessingState.RUNNING,
            }
            for item in processing
        )
        failed = sum(
            item.state is ConversationProcessingState.DEAD for item in processing
        )
        return pending, failed, False

    def _backup_summary(self) -> tuple[str, bool]:
        if self._backup_status_file is None:
            return "not configured", True
        try:
            marker = _read_backup_marker(self._backup_status_file)
        except FileNotFoundError:
            return "missing", True
        except (OSError, ValueError, ValidationError):
            return "invalid", True
        now = self._clock()
        if marker.checked_at > now + timedelta(minutes=5):
            return "invalid", True
        if marker.result is BackupResult.FAILED:
            return "failed", True
        if marker.completed_at is None or marker.completed_at > marker.checked_at:
            return "invalid", True
        age = now - marker.completed_at
        if age < timedelta(0):
            return "invalid", True
        if age > self._backup_stale_after:
            return f"stale ({_age_text(age)} old)", True
        return f"healthy ({_age_text(age)} old)", False


def _read_backup_marker(path: Path) -> BackupMarker:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o022
            or metadata.st_size > _MAX_BACKUP_MARKER_BYTES
        ):
            raise ValueError("backup marker is not a protected bounded regular file")
        document = os.read(descriptor, _MAX_BACKUP_MARKER_BYTES + 1)
    finally:
        os.close(descriptor)
    if not document or len(document) > _MAX_BACKUP_MARKER_BYTES:
        raise ValueError("backup marker has an invalid size")
    return BackupMarker.model_validate_json(document, strict=True)


def _age_text(age: timedelta) -> str:
    total_minutes = max(0, int(age.total_seconds() // 60))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes}m"


def _single_line(value: str) -> str:
    normalized = " ".join(value.split())
    return normalized[:256] if normalized else "unnamed model"


__all__ = [
    "BackupMarker",
    "BackupResult",
    "OwnerModelRoutes",
    "OwnerStatusReporter",
]
