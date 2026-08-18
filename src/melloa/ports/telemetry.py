"""Diagnostic-only telemetry ports."""

from __future__ import annotations

from typing import Protocol

from melloa.domain.observability import DiagnosticSignal


class TelemetrySink(Protocol):
    def emit(self, signal: DiagnosticSignal) -> None:
        """Record bounded diagnostics; this is not audit evidence."""


__all__ = ["TelemetrySink"]
