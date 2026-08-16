"""Ports for provenance-aware memory reads and append-only correction writes."""

from dataclasses import dataclass
from typing import Protocol

from melloa.domain.base import RecordId
from melloa.domain.classification import Sensitivity
from melloa.domain.memory import (
    Assertion,
    AssertionCorrectionResult,
    AssertionStateChange,
    AssertionStateProjection,
    AssertionStateTransitionResult,
    ProvenanceEdge,
)
from melloa.domain.retrieval import RetrievalManifest


class MemoryNotFoundError(LookupError):
    """A canonical memory record was not found."""


class MemoryConflictError(RuntimeError):
    """Immutable memory data or correction state conflicts."""


@dataclass(frozen=True)
class AssertionCorrectionWrite:
    correction: Assertion
    provenance_edge: ProvenanceEdge
    expected_target_state: AssertionStateProjection
    target_state: AssertionStateProjection
    target_change: AssertionStateChange


@dataclass(frozen=True)
class AssertionStateTransitionWrite:
    expected_state: AssertionStateProjection
    state: AssertionStateProjection
    change: AssertionStateChange


class MemoryRepository(Protocol):
    def get_assertion(self, assertion_id: RecordId) -> Assertion:
        """Return the immutable assertion document."""

    def list_assertions(self, subject_id: RecordId) -> tuple[Assertion, ...]:
        """Return assertions for deterministic policy filtering and candidate generation."""

    def list_provenance_edges(
        self,
        record_ids: frozenset[RecordId],
    ) -> tuple[ProvenanceEdge, ...]:
        """Return edges touching any requested record ID."""

    def get_assertion_state(self, assertion_id: RecordId) -> AssertionStateProjection:
        """Return the mutable current-state projection for one immutable assertion."""

    def list_assertion_state_changes(
        self,
        assertion_id: RecordId,
    ) -> tuple[AssertionStateChange, ...]:
        """Return append-only state history in version order."""


class MemoryStore(MemoryRepository, Protocol):
    def apply_correction(
        self,
        write: AssertionCorrectionWrite,
    ) -> AssertionCorrectionResult:
        """Atomically append a correction and supersede its expected target state."""

    def apply_state_transition(
        self,
        write: AssertionStateTransitionWrite,
    ) -> AssertionStateTransitionResult:
        """Atomically append a version-checked assertion state transition."""


class MemoryRetriever(Protocol):
    def retrieve(
        self,
        *,
        requester_id: RecordId,
        subject_id: RecordId,
        query: str,
        purpose: str,
        allowed_sensitivities: frozenset[Sensitivity],
        limit: int = 5,
    ) -> RetrievalManifest:
        """Produce an immutable policy-scoped retrieval manifest."""
