# Observability, reliability, and disaster recovery

## Purpose

Make Melloa inspectable enough to trust, operable enough for one engineer to maintain, and recoverable when ordinary infrastructure and probabilistic AI fail.

## Observability questions

The system must answer, without relying on hidden model reasoning:

- What arrived, from which source, at what time, and with what integrity/sensitivity labels?
- What interpretation or belief was produced, from which evidence, model, prompt, and schema?
- What did policy decide, under which version and grants?
- What tool/capability was called, with what exact authorized action and scoped credential lease?
- What left the trust boundary, how much did it cost, and which data classes were included?
- What code/config/model changed and what artifact was deployed?
- What outcome was observed, and did the intervention meet its declared success criteria?
- Can the run be approximately reproduced or replayed?

This is an **evidence trail**, not storage of private chain-of-thought. Record concise model-provided rationale, cited evidence IDs, alternatives/uncertainty where useful, policy facts, and deterministic execution metadata. Do not require or expose hidden reasoning traces.

## Telemetry architecture

OpenTelemetry supplies vendor-neutral APIs and data models for traces, metrics, and logs, and is an appropriate compatibility layer around application telemetry. [S44](research/primary-sources.md#S44)

### Three distinct records

1. **Domain/audit ledger:** durable, security-relevant, append-oriented records of observations, interpretations, decisions, actions, approvals, changes, and external disclosures. This is not optional telemetry.
2. **Operational telemetry:** traces, metrics, and structured logs for latency, error, resource use, queue health, and dependency behavior; shorter retention and aggressive redaction.
3. **Evaluation evidence:** replay datasets, expected behaviors, score distributions, intervention outcomes, and release decisions.

A SaaS tracing product must not become the only copy of the audit trail or receive raw personal prompts by default.

## Trace model

A root `run_id` correlates a bounded unit of work. Child spans record:

- ingestion and validation;
- retrieval manifest creation;
- model routing and invocation metadata;
- schema validation and retry;
- policy decision;
- approval wait;
- capability execution;
- delivery/side-effect result;
- outcome/evaluation links.

Attach IDs and hashes, not raw sensitive payloads, to ordinary spans. Payload access follows data-store policy and owner audit permissions.

## Core metrics

| Area | Example metrics and alerts |
|---|---|
| Ingestion | last event per source, invalid/duplicate rate, camera candidate volume, dropped/quarantined items |
| Jobs | ready/running/dead counts, oldest age, retries, lease expiry, idempotency conflicts |
| Models | calls by route, tokens, cost, p50/p95 latency, schema failure, fallback, refusal, provider availability |
| Policy | allow/deny/approval counts, stale approval, unknown capability, budget rejection, decision latency |
| Actions | proposed/executed/failed/reversed, side-effect deduplication, outcome linkage |
| Memory | corrections, contradictions, unsupported belief rate, stale fact review, index lag |
| Proactivity | messages/day, quiet-hour blocks, dismissals, owner usefulness feedback, topic cooldown hits |
| Infrastructure | CPU/RAM/disk, DB connections/locks, backup age, certificate/token expiry, camera heartbeat |
| Security | invalid sender, denied egress, secret access, hash mismatch, Guardian mode change, audit gaps |

## V1 service objectives

These are owner-facing objectives, not enterprise promises:

- 99% of accepted Telegram messages durably ingested within 30 seconds while Telegram and internet are available.
- 95% of local camera candidate events either interpreted or explicitly expired within 10 minutes.
- Dangerous action authorization fails closed on policy/broker error.
- No proactive message exceeds the configured daily and quiet-hour budgets.
- Backup age remains under 24 hours; monthly restore drill succeeds.
- Cost accounting covers at least 99% of model and priced capability calls by count.
- Audit linkage exists for every executed side effect.

Targets should be adjusted from observed usefulness rather than gamed as vanity SLOs.

## Reliability patterns

- Bounded queues and backpressure at every external source.
- At-least-once processing with idempotency keys and side-effect receipts.
- Timeouts, capped retries, exponential backoff, jitter, and circuit breakers.
- Per-run token, step, wall-clock, external-call, and spend limits.
- Schema validation and typed error handling for model/tool outputs.
- Dead-letter state that is visible and replayable, not an invisible discard queue.
- Graceful degradation: capture locally, defer cloud interpretation, communicate reduced capability.
- Health checks distinguish liveness, readiness, dependency degradation, and correctness signals.
- Retention and disk quotas enforced before storage exhaustion.
- Versioned migrations with preflight and restored-data rehearsal.

## Failure and recovery matrix

| Failure | Expected behavior | Recovery |
|---|---|---|
| Internet outage | local capture, memory reads, deterministic rules continue; cloud calls queue/expire by TTL | reconnect with rate-limited drain; do not replay stale proactive actions blindly |
| Model provider outage | route to eligible fallback or defer; never lower privacy class silently | provider health/circuit reset; replay deferred tasks by policy |
| Telegram outage | queue low-urgency output; local work continues | retry with deduplication; summarize rather than flood after recovery |
| Camera disconnect | heartbeat alert; mark absence of evidence, not “person absent” | check PoE/network/credentials; replace using runbook and recalibrate |
| Database unavailable | stop side effects; bounded local sensor spool; Guardian recovery mode | repair/restore; integrity check; replay spool idempotently |
| Disk near full | stop low-value media first, compact telemetry, block nonessential artifacts | retention cleanup, expand disk, verify DB headroom |
| Invalid model output | schema reject, limited repair/retry, fallback or abstain | capture failure class; regression test; never coerce dangerous fields |
| Runaway agent loop | hard ceilings terminate; alert and quarantine run | inspect trace/proposal; fix routing/prompt; replay in simulation |
| Bad deployment | health/eval guard triggers rollback | deploy previous digest/config; keep failed artifact and evidence |
| Migration failure | service remains stopped or old version active | transactional rollback where valid; restore snapshot; execute tested reverse/forward fix |
| Dependency compromise | block build/deploy or revoke affected capability | rotate secrets, rebuild from trusted lock/provenance, audit egress/actions |
| Power loss | filesystem/DB recover; UPS permits clean shutdown where present | boot health checks, DB recovery, camera reconnect, missed-window marker |
| Lost provider secret | affected capability degraded only | owner/Guardian issues new scoped token and records rotation |
| Corrupted backup | do not destroy last known-good copy | alternate repository/snapshot; investigate; increase verification cadence |

## Backup architecture

Use `restic` for encrypted, deduplicated repositories and integrity checking across local and remote backends. [S42](research/primary-sources.md#S42)

### Data tiers

- **Irreplaceable:** Postgres logical data, policies, goals, corrections, audit, change history, encryption metadata, deployment config, source repositories.
- **Valuable but reconstructable:** selected event media, evaluation corpora, generated artifacts.
- **Rebuildable:** embeddings, indexes, model caches, downloaded images, operational metrics.
- **Intentionally ephemeral:** ring buffers, sandbox files, quarantine after expiry, transient queues once durable state exists.

### V1 schedule

- Nightly database-consistent logical dump plus schema/role manifest.
- Nightly `restic` snapshot to attached/removable local storage.
- Nightly or daily encrypted offsite snapshot to B2/equivalent after local verification.
- Weekly extended integrity check and backup-age report.
- Monthly restore on a clean VM/spare host, including DB migration and a representative blob/audit lookup.
- Quarterly recovery-key and owner-account recovery review.

Backblaze B2’s published storage price is a useful low-cost benchmark, but pricing and egress policy must be rechecked before deployment. [S43](research/primary-sources.md#S43)

### Recovery objectives

For V1:

- **RPO:** 24 hours for ordinary durable state; lower only after WAL/PITR is justified.
- **RTO:** 4 hours to a functioning core on prepared hardware after a successful restore drill.
- **Camera continuity:** no guarantee during host/camera failure; missed intervals are recorded explicitly.

When Melloa becomes relied upon for urgent or safety-relevant functions, reduce these objectives through physical replicas/PITR and tested failover rather than optimistic documentation.

## Restore procedure outline

1. Place system in Guardian `stopped` mode and preserve failed media.
2. Provision a clean, patched host from Ansible at a known commit.
3. Recover age/restic keys through the owner-controlled recovery path.
4. Restore configuration, latest verified DB dump/physical snapshot, and required blobs.
5. Start Postgres only; run integrity and migration-version checks.
6. Start core in `offline/read-only` mode; verify identity, policies, audit continuity, and sample provenance links.
7. Rebuild derived indexes and model caches.
8. Start adapters individually; deduplicate spooled events.
9. Re-enable outbound actions only after owner review.
10. Record actual RPO/RTO and remediation actions.

A backup is not accepted until this process has succeeded.

## Audit protection

- Separate append permissions from correction/annotation permissions.
- Hash-chain or periodically checkpoint audit batches to detect accidental/tampered deletion; do not overclaim blockchain-grade immutability.
- Export signed/checksummed audit summaries to the backup trust domain.
- Prevent autonomous workloads from changing retention or deleting security records.
- Record Guardian actions locally and in an owner-visible location independent of the core when possible.

## Privacy and telemetry

- Default to local collection.
- Do not put raw prompts, room images, message bodies, secrets, or full tool payloads in labels/log lines.
- Apply sensitivity-aware sampling and retention.
- Keep high-cardinality personal identifiers out of metrics.
- Redaction happens before export, not merely in a dashboard.
- Debug capture requires a bounded, owner-visible temporary mode with automatic expiry.

## Build now

- Domain/audit schema, structured logs, run/correlation IDs, model/cost/action metrics.
- Local OpenTelemetry collector or compatible export path.
- Owner Console health, structured run/decision explorer, CLI diagnostics, and actionable alerts.
- Nightly encrypted local/offsite backup and a clean-machine restore drill.
- Run ceilings, queue quotas, provider circuits, and failure-visible dead-letter state.

## Design for

- PITR, stronger audit checkpointing, independent recovery host, and privacy-preserving external observability.
- Per-capability SLOs and chaos/replay drills.

## Defer

- Full high-availability database cluster, multi-region failover, raw personal telemetry in third-party SaaS, and “self-healing” that can conceal data corruption or bad policy.
