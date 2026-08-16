# ADR-001: Use an event-oriented provenance ledger, not pure event sourcing

- **Status:** Accepted for V1
- **Date:** 2026-08-15

## Context

Melloa must preserve why it believed and did things over years. Observations, interpretations, corrections, authorizations, actions, outcomes, and software changes need durable history and replay. Pure CRUD loses history; pure event sourcing makes every current object dependent on indefinite replay and difficult schema evolution.

## Decision

Store append-oriented canonical records for evidence, interpretations, assertions, corrections, decisions, actions, outcomes, and audit. Maintain ordinary relational current-state projections for operational reads. Raw high-volume evidence has explicit retention; stable envelopes retain schema/source/provenance metadata. Rebuild derived indexes and selected projections through replay.

## Alternatives considered

- **CRUD only:** simple, but cannot reconstruct belief/action lineage reliably.
- **Pure event sourcing:** maximally replayable, but imposes unnecessary operational and migration complexity.
- **External event bus as source of truth:** duplicates durable state and complicates backup/recovery for one user.

## Consequences

- Every derived claim and side effect has traceable parents.
- Corrections append rather than silently overwrite history.
- Projection/replay code is required and must be tested.
- Retention and deletion need tombstones and derived-data rebuilds.

## Revisit when

Replay cost or independent consumer scale exceeds PostgreSQL thresholds, or a clear domain benefits from stricter event-sourced state. Do not generalize that need to every domain automatically.
