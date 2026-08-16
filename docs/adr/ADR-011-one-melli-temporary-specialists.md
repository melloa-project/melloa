# ADR-011: Start with one persistent Melli and ephemeral specialists

- **Status:** Accepted for V1
- **Date:** 2026-08-15

## Context

The architecture must support multiple persistent intelligences eventually, but multiple names/processes do not automatically improve reasoning. They introduce authority, memory, accountability, communication, and identity-continuity problems.

## Decision

Instantiate one persistent intelligence, Melli. Create temporary specialist workers for research, review, coding, security, or planning within a parent run/proposal and scoped policy context. A specialist result is evidence/advice, not an independent authority. Add a persistent intelligence only for a durable distinct identity, relationship, responsibility, memory scope, and permission boundary.

## Alternatives considered

- Permanent role-agent swarm: parallel perspectives but unclear accountability and duplicated/conflicting memory.
- One undifferentiated prompt/process: simpler but cannot isolate temporary contexts/tools or future identities.

## Consequences

- Melli retains accountable continuity while model/processes change.
- Specialist workers must return source/evidence and cannot silently write long-term memory.
- The persistent-intelligence registry/schema exists without premature agent society.

## Revisit when

A concrete role requires continuing independent goals/relationships/permissions and its benefits exceed coordination/governance cost.
