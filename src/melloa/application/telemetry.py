"""Best-effort diagnostic telemetry helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from melloa.domain.observability import (
    DiagnosticComponent,
    DiagnosticReason,
    DiagnosticResult,
    DiagnosticSignal,
    DiagnosticSignalKind,
)
from melloa.ports.telemetry import TelemetrySink

T = TypeVar("T")


class BestEffortTelemetry:
    def __init__(self, sink: TelemetrySink) -> None:
        self._sink = sink
        self._failed_emissions = 0

    @property
    def failed_emissions(self) -> int:
        return self._failed_emissions

    def emit(self, signal: DiagnosticSignal) -> None:
        try:
            self._sink.emit(signal)
        except Exception:
            self._failed_emissions += 1

    def observe_accepted_operation(
        self,
        operation: Callable[[], T],
        *,
        component: DiagnosticComponent,
    ) -> T:
        result = operation()
        self.emit(
            DiagnosticSignal(
                kind=DiagnosticSignalKind.OPERATION_OBSERVED,
                component=component,
                result=DiagnosticResult.ACCEPTED,
                reason=DiagnosticReason.SOURCE_OPERATION_COMPLETED,
            )
        )
        return result


__all__ = ["BestEffortTelemetry"]
