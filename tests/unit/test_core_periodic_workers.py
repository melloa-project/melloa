from __future__ import annotations

import asyncio
import logging
from threading import Event, get_ident

import pytest

from melloa.application.conversation import ConversationUnavailableError
from melloa.application.telegram import TelegramIngestionUnavailableError
from melloa.apps import core


class _IgnoredCycleError(RuntimeError):
    pass


def test_periodic_sync_worker_preserves_cycle_policy_and_thread_offload(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation_threads: list[int] = []
    scheduled_intervals: list[float] = []
    cycle = 0

    def operation() -> None:
        nonlocal cycle
        cycle += 1
        operation_threads.append(get_ident())
        if cycle == 1:
            raise _IgnoredCycleError
        if cycle == 2:
            raise RuntimeError("unexpected cycle failure")

    async def stop_after_third_cycle(interval: float) -> None:
        scheduled_intervals.append(interval)
        if len(scheduled_intervals) == 3:
            raise asyncio.CancelledError

    async def run_worker() -> int:
        event_loop_thread = get_ident()
        with pytest.raises(asyncio.CancelledError):
            await core._run_periodic_sync_worker(
                operation,
                interval=0.25,
                failure_message="periodic worker cycle failed",
                ignored_errors=(_IgnoredCycleError,),
            )
        return event_loop_thread

    monkeypatch.setattr(core.asyncio, "sleep", stop_after_third_cycle)
    caplog.set_level(logging.ERROR, logger=core.__name__)

    event_loop_thread = asyncio.run(run_worker())

    assert cycle == 3
    assert scheduled_intervals == [0.25, 0.25, 0.25]
    assert all(thread != event_loop_thread for thread in operation_threads)
    assert [record.getMessage() for record in caplog.records] == [
        "periodic worker cycle failed"
    ]


def test_telegram_worker_preserves_poll_observer_and_dispatch_thread_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    poll_cycle = object()
    call_threads: dict[str, int] = {}
    scheduled_intervals: list[float] = []

    class PollWorker:
        def poll_once(self) -> object:
            call_threads["poll"] = get_ident()
            return poll_cycle

    class ReplyDispatcher:
        def observe_poll_cycle(self, cycle: object) -> None:
            assert cycle is poll_cycle
            call_threads["observe"] = get_ident()

        def dispatch_ready(self) -> None:
            call_threads["dispatch"] = get_ident()

    async def stop_after_cycle(interval: float) -> None:
        scheduled_intervals.append(interval)
        raise asyncio.CancelledError

    async def run_worker() -> int:
        event_loop_thread = get_ident()
        with pytest.raises(asyncio.CancelledError):
            await core._run_telegram_worker(
                PollWorker(),
                interval=0.5,
                reply_dispatcher=ReplyDispatcher(),
            )
        return event_loop_thread

    monkeypatch.setattr(core.asyncio, "sleep", stop_after_cycle)

    event_loop_thread = asyncio.run(run_worker())

    assert call_threads["poll"] != event_loop_thread
    assert call_threads["observe"] == event_loop_thread
    assert call_threads["dispatch"] != event_loop_thread
    assert scheduled_intervals == [0.5]


def test_telegram_worker_cancellation_does_not_dispatch_after_blocked_poll() -> None:
    poll_started = Event()
    release_poll = Event()
    observed = Event()
    dispatched = Event()

    class BlockingPollWorker:
        def poll_once(self) -> object:
            poll_started.set()
            if not release_poll.wait(timeout=5):
                raise AssertionError("test did not release blocked poll")
            return object()

    class ReplyDispatcher:
        def observe_poll_cycle(self, cycle: object) -> None:
            observed.set()

        def dispatch_ready(self) -> None:
            dispatched.set()

    async def cancel_blocked_worker() -> None:
        task = asyncio.create_task(
            core._run_telegram_worker(
                BlockingPollWorker(),
                interval=60,
                reply_dispatcher=ReplyDispatcher(),
            )
        )
        try:
            assert await asyncio.to_thread(poll_started.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release_poll.set()

    asyncio.run(cancel_blocked_worker())

    assert not observed.is_set()
    assert not dispatched.is_set()


@pytest.mark.parametrize(
    ("poll_error", "dispatch_error", "expected_messages"),
    [
        (TelegramIngestionUnavailableError(), ConversationUnavailableError(), []),
        (
            RuntimeError("unexpected poll failure"),
            RuntimeError("unexpected dispatch failure"),
            ["Telegram poll worker cycle failed", "Telegram reply dispatch cycle failed"],
        ),
    ],
)
def test_telegram_cycle_preserves_error_partition_and_dispatch_attempt(
    poll_error: Exception,
    dispatch_error: Exception,
    expected_messages: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    dispatch_attempted = False

    class FailingPollWorker:
        def poll_once(self) -> object:
            raise poll_error

    class FailingReplyDispatcher:
        def observe_poll_cycle(self, cycle: object) -> None:
            raise AssertionError("failed poll must not be observed")

        def dispatch_ready(self) -> None:
            nonlocal dispatch_attempted
            dispatch_attempted = True
            raise dispatch_error

    caplog.set_level(logging.ERROR, logger=core.__name__)

    asyncio.run(
        core._poll_and_dispatch_telegram(FailingPollWorker(), FailingReplyDispatcher())
    )

    assert dispatch_attempted is True
    assert [record.getMessage() for record in caplog.records] == expected_messages
