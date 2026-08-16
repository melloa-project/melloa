# Alternative architectures

## Evaluation criteria

Each alternative is plausible for a technically sophisticated single owner. They are scored against simplicity, maintainability, security boundaries, observability, autonomy, cost, self-modification, and migration options.

## A — Single local daemon with SQLite

### Shape

One Python process owns Telegram, camera ingestion, scheduling, reasoning, memory, and actions. SQLite WAL stores state and an append-only event table. Files are stored locally. A systemd service starts and stops the daemon.

### Strengths

- Minimal operational surface and fastest route to a prototype.
- Easy backup and inspection.
- Excellent for validating conversation, schema, and camera event volume.
- No networked database or message broker.

### Weaknesses

- One process failure affects all functions.
- Generated-code execution, policy enforcement, and perception compete for the same trust boundary.
- Long-running tasks and concurrent camera/event workloads can create awkward locking and lifecycle behavior.
- It encourages direct library calls and hidden coupling.
- Migrating identity, policy, and event consumers out of the daemon later may be more work than starting with explicit internal modules and a networked database.

### Best use

A throwaway two-week research spike, or a minimal edition that explicitly never enables self-modification.

## B — Modular monolith with PostgreSQL ledger and external Guardian

### Shape

A small set of rootless containers on one Linux host:

- Melloa core API and scheduler;
- event/job workers from the same codebase;
- PostgreSQL with `pgvector`;
- camera adapter/Frigate;
- optional local model runtime;
- OpenTelemetry collector or direct local telemetry sink.

Modules communicate through typed in-process interfaces and durable database records. PostgreSQL outbox/jobs provide asynchronous work. A host-level Guardian, controlled by separate credentials, can stop workloads and remove egress.

### Strengths

- One primary codebase and database keep operations understandable.
- PostgreSQL supports transactions, JSON, temporal queries, full-text search, row-level controls, and vector indexes without a database zoo. [S04](research/primary-sources.md#S04) [S05](research/primary-sources.md#S05)
- The outbox pattern avoids a database-plus-broker dual-write problem; consumers are designed for duplicate delivery and idempotency. [S06](research/primary-sources.md#S06)
- Explicit module contracts and event schemas preserve a path to process separation.
- The Guardian creates a real authority boundary without forcing a distributed platform.
- Self-modification can be introduced as a separate sandbox worker rather than granting the core host authority.

### Weaknesses

- PostgreSQL becomes a critical dependency and requires real backup/restore discipline.
- A modular monolith can decay into “everything imports everything” without dependency rules.
- Database-backed jobs are less elegant than a durable workflow engine for complex months-long workflows.
- One host remains a single failure domain.

### Best use

The recommended V1 and likely multi-year foundation for one owner.

## C — Distributed capability-oriented control plane

### Shape

Independent sensor, memory, policy, planner, action, and deployment services communicate over NATS JetStream or Kafka. Durable workflows run in Temporal/Restate. Every workload has SPIFFE identity and obtains dynamic secrets from OpenBao. Kubernetes schedules containers and microVM sandboxes across home and cloud nodes.

### Strengths

- Strong process and network isolation.
- Natural independent scaling and failure containment.
- Durable workflow engines are excellent for retries, timers, human approvals, and long-running state. [S09](research/primary-sources.md#S09)
- NATS JetStream provides persistence and replay when multiple independent nodes need a real event fabric. [S08](research/primary-sources.md#S08)
- Workload identity and dynamic secrets can become robust at larger scale.

### Weaknesses

- Far too many operational concepts for one owner and one camera.
- Policy, certificate, queue, workflow, schema, deployment, and observability failures multiply.
- Local debugging and clean-machine restoration become harder.
- Autonomous changes have a much larger blast radius.
- It risks building an infrastructure platform before demonstrating one beneficial personal loop.

### Best use

A later architecture after multiple hosts, independent capabilities, offline edge nodes, and high-volume durable workflows create measured pressure.

## Comparative score

Score 1 = poor, 5 = strong for the initial owner-operated deployment.

| Criterion | A: daemon + SQLite | B: modular monolith + Postgres | C: distributed control plane |
|---|---:|---:|---:|
| Initial simplicity | 5 | 4 | 1 |
| Five-year maintainability | 2 | 5 | 2 |
| Security boundary clarity | 2 | 4 | 5 |
| Observability | 2 | 4 | 5 |
| V1 cost | 5 | 4 | 1 |
| Camera/event fit | 3 | 5 | 4 |
| Safe self-modification path | 2 | 4 | 5 |
| Offline/local operation | 5 | 5 | 3 |
| Upgrade path | 2 | 5 | 4 |
| One-engineer operability | 5 | 5 | 1 |
| **Total** | **31** | **45** | **31** |

## Decision

Choose **B**. It retains almost all important long-term boundaries without enterprise-platform overhead.

## Migration triggers, not aspirations

Add a real event broker only when one or more are measured:

- several independent edge hosts must buffer and synchronize while offline;
- database polling causes unacceptable load or latency;
- consumers are maintained/deployed independently and fan-out is operationally painful;
- event throughput or retention exceeds comfortable PostgreSQL operation;
- external contributors need a stable cross-process subscription contract.

Add a durable workflow engine when:

- dozens of workflows remain active for days or months;
- retries, compensation, human pauses, and version migration dominate application code;
- replaying workflow state is more reliable than explicit jobs and state machines.

Add Kubernetes only when multi-host scheduling, rolling upgrades, resource placement, or high availability outweigh the operational burden. “Generated software might eventually be complex” is not a trigger.

## Rejected hybrid

A tempting hybrid is SQLite for core state plus NATS for events. It combines two sources of durability and recreates the transactional dual-write problem without delivering meaningful scale. PostgreSQL alone is simpler and safer for V1.
