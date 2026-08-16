# Chosen V1 architecture

## Purpose

Specify the concrete architecture that should be implemented first while preserving the boundaries most expensive to retrofit later.

## Architectural style

Melloa V1 is a **local-first modular monolith with durable events, ordinary relational projections, and an externally controlled authority boundary**.

“Event-oriented” does not mean every object is reconstructed by replaying all events. The system uses:

- append-only records for observations, interpretations, decisions, actions, corrections, and audits;
- current-state relational projections for efficient operation;
- a transactional outbox/job table for asynchronous work;
- content-addressed blobs for frames, clips, artifacts, and exports;
- derived full-text/vector indexes that can be rebuilt.

## Concrete component set

### Core host

- Wired x86-64 mini-PC, 16–32 GB RAM, 1 TB NVMe.
- Debian or Ubuntu LTS.
- Rootless Docker Engine and Docker Compose.
- Host firewall, encrypted disk, automatic security updates with controlled reboot windows.
- Tailscale for owner-only remote access; no public application ingress.

### Containers

1. **`melloa-core`** — FastAPI-based owner API, canonical conversation service, model gateway, memory retrieval, policy/capability endpoints, and channel abstraction.
2. **`melloa-web`** — Private Owner Console for conversation, provenance, memory correction, run/decision inspection, media, health, cost, disclosure, approval, and deployment views.
3. **`melloa-worker`** — Same Python codebase, separate process roles for event interpretation, scheduled reflection, indexing, retention, and evaluations.
4. **`postgres`** — PostgreSQL 18 with `pgvector`; separate roles for core, read-only analytics, and migrations.
5. **`perception`** — Frigate/go2rtc or a thin adapter around RTSP/FFmpeg and local detectors. It emits candidate evidence, not authoritative Melloa facts.
6. **`otel-collector`** — Optional but recommended local collector; can initially export to local files or a small local stack.
7. **`local-model`** — Optional llama.cpp/MLX/vLLM-compatible endpoint, enabled only when hardware and workloads justify it.

### Host-owned Guardian

A root-owned systemd unit and owner CLI outside the autonomous container trust domain. It controls:

- start/stop and mode files consumed read-only by Melloa;
- host firewall/egress rules;
- revocation or removal of provider and capability credentials;
- database read-only/recovery procedure;
- emergency export and diagnostics;
- signed deployment of Guardian changes.

The Guardian does not need AI. Its value is simple, independent authority.

## Internal modules and dependency direction

```text
interfaces (Owner Console/HTTP/CLI/channel adapters)
                 ↓
application use cases / orchestration
                 ↓
domain: events, memory, goals, policy requests, interventions
                 ↓
ports: repository, model, capability, clock, identity, audit
                 ↓
adapters: Postgres, Telegram, camera, provider APIs, filesystem
```

Rules:

- Domain code does not import the Owner Console, Telegram, OpenAI, Frigate, Docker, or PostgreSQL libraries.
- Capability adapters cannot call models to decide whether they are allowed to act.
- Model adapters cannot access secrets directly; they receive a brokered invocation request.
- Every side effect requires an authorization decision ID.
- Every external input enters with provenance, sensitivity, and trust/taint labels.

## Durable work model

A transaction may update current state and append an event/outbox row atomically. Workers claim jobs with `FOR UPDATE SKIP LOCKED`, maintain leases, retry with backoff, and record deduplication keys. PostgreSQL `LISTEN/NOTIFY` may wake workers, but polling the durable table remains the source of truth because notifications are not a queue. [S06](research/primary-sources.md#S06) [S07](research/primary-sources.md#S07)

Delivery semantics are **at least once**. Consumers must be idempotent. “Exactly once” is not claimed across arbitrary side effects.

## V1 data stores

| Data | Store | Rationale |
|---|---|---|
| Events, provenance, policies, goals, jobs, audit | PostgreSQL | Transactions, queryability, migrations, one operational database |
| Embeddings | `pgvector` columns/tables | Co-located, rebuildable semantic index [S05](research/primary-sources.md#S05) |
| Frames/clips/artifacts | Content-addressed filesystem | Simple local ownership and deduplication; database stores hashes/metadata |
| Configuration | Versioned YAML/TOML plus DB overrides | Reviewable defaults and dynamic owner settings |
| Bootstrap secrets | SOPS + age and OS keyring | No plaintext Git secrets; small V1 footprint [S20](research/primary-sources.md#S20) |
| Backups | `restic` repositories on local USB and B2 | Encryption, deduplication, verification, multiple backends [S42](research/primary-sources.md#S42) |

## Policy and action path

1. A model or deterministic rule emits an **action proposal**.
2. The proposal is canonicalized and risk-classified.
3. The capability broker builds an authorization request.
4. Deterministic policy evaluates prohibitions, grants, constraints, budgets, and approval requirements.
5. If approval is needed, the exact action hash is presented to the owner.
6. The broker obtains or exercises a scoped credential.
7. The capability adapter executes and returns a schema-validated result.
8. The action, authorization, credential lease reference, result, cost, and observable outcome are appended.

The model never receives a general secret bundle.

## Model path

Every model invocation includes:

- task type and required modality;
- minimum quality tier and latency objective;
- data sensitivity and provider eligibility;
- context budget and retrieval manifest;
- token/cost ceiling;
- fallback route;
- prompt/template version;
- output schema and validation policy.

A model result is untrusted data until validated and, for side effects, authorized.

## V1 deployment topology

See [Diagram 9](diagrams.md#9-v1-deployment-architecture) and [Diagram 17](diagrams.md#17-network-topology). The camera network cannot reach the internet. Only the perception adapter can pull its RTSP stream. The core can reach explicit provider/API endpoints through auditable egress rules. Generated-code sandboxes have no egress unless a temporary allowlist is attached.

## Build now

- PostgreSQL schema, migration discipline, event envelope, jobs/outbox, and idempotency.
- Owner/Melli identity records, canonical conversation, and epistemic memory distinctions.
- Private Owner Console with authenticated conversation, timeline, provenance, structured run inspection, health, and correction flows.
- Optional Telegram long-polling adapter with an owner ID allowlist.
- Capability broker with a small typed policy implementation.
- Model gateway with at least one hosted provider and deterministic fake provider for tests.
- Guardian modes and credential revocation.
- Structured audit and cost records.
- Encrypted backup and clean-machine restore.

## Design for

- Moving a module behind HTTP/gRPC without changing domain contracts.
- NATS or a durable workflow engine behind event/workflow ports.
- Edge nodes with signed capability identities.
- Generated-code sandbox and GitOps flow.
- Multiple persistent intelligences with separate policy/memory scopes.
- Native mobile and additional messaging clients behind the conversation/client abstraction.

## Defer

- Kubernetes, service mesh, SPIFFE, OpenBao, Kafka, NATS, and Temporal.
- A dedicated graph or vector database.
- Public web endpoints.
- A GPU purchase before profiling.
- Automatic infrastructure/IAM changes.
- Multi-camera continuous recording.

## Operational implications

One host is a deliberate single failure domain. V1 prioritizes restore and graceful degradation over high availability. The architecture should be re-evaluated when Melloa becomes safety-critical, supports more than one owner, spans multiple physical sites, or accumulates independent always-on capabilities.

## Cost implications

The core stack has no mandatory SaaS platform cost beyond model APIs, optional Tailscale plan, and offsite storage. The expensive variables are model calls, retained media, and local GPU hardware—not PostgreSQL or Compose.

## Principal failure modes

- **PostgreSQL unavailable:** ingestion buffers bounded local evidence; actions stop; Guardian exposes recovery mode.
- **Internet/provider outage:** local event capture continues; rich interpretation is deferred.
- **Policy engine error:** side effects fail closed.
- **Camera flood:** local aggregation and queue quotas discard/reduce low-value candidates before canonical event creation.
- **Model loop:** per-run step, token, time, and cost ceilings terminate execution.
- **Bad migration:** preflight backup, migration transaction where possible, staging replay, and rollback runbook.
- **Compromised autonomous container:** no Guardian credentials, no host Docker socket, constrained database role, and revocable egress reduce blast radius.
