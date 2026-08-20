"""Apply only exact approved proposals through deterministic release orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

from melloa.domain.base import new_record_id, utc_now
from melloa.domain.self_change import SelfChange
from melloa.ports.self_change import (
    SelfChangeReleaseError,
    SelfChangeReleaseExecutor,
    SelfChangeStore,
)


class SelfChangeApplyingWorker:
    def __init__(
        self,
        *,
        store: SelfChangeStore,
        executor: SelfChangeReleaseExecutor,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[str], str] = new_record_id,
        lease_duration: timedelta = timedelta(hours=2),
        retry_delay: timedelta = timedelta(minutes=10),
        idle_delay: float = 5.0,
    ) -> None:
        if lease_duration <= timedelta(0):
            raise ValueError("self-change application lease must be positive")
        if retry_delay <= timedelta(0):
            raise ValueError("self-change application retry delay must be positive")
        if idle_delay <= 0:
            raise ValueError("self-change application idle delay must be positive")
        self._store = store
        self._executor = executor
        self._clock = clock
        self._id_factory = id_factory
        self._lease_duration = lease_duration
        self._retry_delay = retry_delay
        self._idle_delay = idle_delay

    def process_next(self) -> SelfChange | None:
        claimed_at = self._clock()
        claim = self._store.claim_next_applying(
            lease_owner=self._id_factory("worker"),
            now=claimed_at,
            lease_expires_at=claimed_at + self._lease_duration,
        )
        if claim is None:
            return None
        try:
            candidate_revision = self._executor.prepare_candidate(claim)
            claim = self._store.record_candidate(
                claim,
                candidate_revision=candidate_revision,
                now=self._clock(),
            )
            self._executor.release_candidate(claim)
        except SelfChangeReleaseError as error:
            failed_at = self._clock()
            return self._store.record_applying_failure(
                claim,
                error_code=error.reason_code,
                retry_at=failed_at + self._retry_delay,
                now=failed_at,
            )
        return self._store.record_deployed(
            claim,
            candidate_revision=candidate_revision,
            now=self._clock(),
        )

    async def run_forever(self) -> None:
        while True:
            result = await asyncio.to_thread(self.process_next)
            if result is None:
                await asyncio.sleep(self._idle_delay)


__all__ = ["SelfChangeApplyingWorker"]
