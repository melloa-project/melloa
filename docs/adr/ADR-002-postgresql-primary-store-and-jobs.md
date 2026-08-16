# ADR-002: Use PostgreSQL as the V1 primary store and durable work queue

- **Status:** Accepted for V1
- **Date:** 2026-08-15

## Context

Melloa needs transactions, relational queries, JSON, full text, migrations, authorization roles, semantic retrieval, and durable asynchronous work. A separate queue, graph database, vector database, and workflow engine would create multiple recovery authorities before scale justifies them.

## Decision

Use PostgreSQL 18 as the sole operational source of truth. Use tables for events/provenance, current projections, goals/policies, jobs/outbox, audit, and metadata. Use `pgvector` for rebuildable embeddings. Workers poll durable jobs with leases and idempotency; `LISTEN/NOTIFY` is only a latency hint.

## Alternatives considered

- SQLite: excellent simplicity, but weaker fit for concurrent workers, roles, remote tooling, and future edge/process split.
- NATS JetStream or Kafka/Redpanda: durable streams but another distributed state/operations system.
- Redis Streams: convenient queue, but adds a second persistence/recovery system.
- Temporal: strong workflows, excessive for initial bounded jobs.
- Graph/vector database: specialized retrieval, not canonical truth/provenance.

## Consequences

- One database to back up, migrate, and restore.
- At-least-once semantics and idempotency are explicit.
- Long-running workflow logic must remain visible state machines until a workflow engine is justified.
- Workload isolation and DB connection/lock monitoring matter.

## Revisit when

Sustained backlog violates recovery objectives; more than three independently deployed nodes require streaming; workflows span days with complex compensation/signals; or database contention cannot be solved without harming core state.
