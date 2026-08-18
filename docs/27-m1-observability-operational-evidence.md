# M1 Observability and Operational Evidence Acceptance Design

## Status

This is an acceptance design for the current M1 preview as of 2026-08-18. It is
not a runtime implementation, not a production observability signoff, and not a
claim that backup, recovery, or complete audit coverage is finished.

The design is grounded in the implemented owner health, timeline, model
activity, provider route, queue status, retention, export-readiness,
PostgreSQL, Guardian, and recovery surfaces. It preserves the current default:
no external telemetry collector, no network dependency, synthetic data for the
safe first run, and no raw personal data in operational evidence.

## Acceptance Goal

M1 observability is accepted only when a technically capable owner can answer
these questions from owner-visible evidence without relying on hidden model
reasoning or third-party telemetry:

- Is the core live and ready, and which dependency or Guardian state blocks it?
- What persistence mode is active, and which state is durable versus
  process-local?
- Which model route was used, what it cost, how long it took, and whether
  external disclosure occurred?
- Which accepted work is ready, running, completed, dead, or resumed?
- Which owner-visible mutation has durable audit evidence, and what are the
  known audit gaps?
- What export validation proves, and what it explicitly does not prove?
- Which release or recovery gates passed, failed, were skipped, or were
  environment-blocked?

## Existing Evidence Surfaces

| Surface | Current evidence | Acceptance value | Current limit |
| --- | --- | --- | --- |
| Liveness and readiness | `/health/live`, `/health/ready`, and Guardian-mode readiness handling in `apps/core.py` | Fast operator signal for process health and fail-closed Guardian states | Readiness is not a deep production dependency probe |
| Owner health report | `OwnerHealthReport`, `ComponentHealth`, and `aggregate_health_state` in `domain/operations.py`; assembled by `OwnerOperationsService.health` | Deterministic owner-visible component state by category and component ID | Current synthetic and PostgreSQL health is snapshot-based, not trend telemetry |
| Persistence mode | `RuntimePersistenceStatus` and synthetic/PostgreSQL component summaries in `apps/synthetic.py` and `apps/postgres_mvp.py` | States which data survives restart and which state remains process-local | Does not prove backup, PITR, or restore readiness |
| Provider routes | `OwnerModelRouteReport`, `ModelRouteStatus`, and `ModelGatewayHealth` | Shows route identity, kind, processing location, retention policy, health, timeout, cost ceiling, and disclosure boundary | Health is route supplied and may be unknown; it is not provider billing reconciliation |
| Model activity | `OwnerModelActivityReport` and `ModelActivityEntry` | Redacted completed-run view with route, provider, model, tokens, cost, timing, and disclosure details | Counts completed turns; no separate operational latency histogram or billing proof |
| Timeline | `OwnerTimelineReport` | Owner-visible chronological projection over canonical conversation, model activity, reply work, delivery work, and selected audit events | Current coverage is explicitly partial and excludes auth/security audit events |
| Conversation work | `ConversationProcessingStatus` | Shows reply-work state, attempts, lease expiry, last error, completion, and resumptions | No shared cross-domain queue metrics yet |
| Delivery work | `DeliveryWorkStatus` | Shows exact-authority delivery state, attempts, policy decision IDs, receipts, lease expiry, and resumptions | Telegram successful-send dedupe is not production-durable |
| Retention | `OwnerRetentionReport` | Shows policies, aggregate inventory, deletion controls, tombstone obligations, and backup-expiry disclosure | Most lifecycle mutation controls are still unavailable |
| Export readiness | `OwnerExportReadinessReport` | Shows included record groups, validation checks, encryption wrapper readiness, and limitations | Explicitly excludes SQL snapshots, blobs, Telegram control state, signed archives, and restore execution |
| Event/audit ledger | `EventAuditStore`, `AuditContent`, PostgreSQL audit append, and recent Forge audit slices | Durable content-free evidence for implemented actions and denials | Coverage and source-plus-audit atomicity remain incomplete outside coupled paths |
| PostgreSQL health | `database_health_reader` over the MVP PostgreSQL connections | Redacted database availability and server-version evidence | Does not report table bloat, lock waits, replication, backups, or restore age |
| Guardian status | Signed Guardian status consumed through `GuardianStatusReader` | Independent owner-controlled mode evidence; Melloa has no Guardian mutation authority | Production value depends on deployment keeping Guardian keys and controls outside Melloa |
| Recovery evidence | `make recovery`, the M0 recovery runbook, and current-MVP operations commands | Synthetic encrypted restore proof and release-gate commands | M0 synthetic recovery is not production backup and does not restore full M1 state |
| Browser evidence | production Owner Console smoke and screenshot workflow in CI/docs | Confirms authenticated browser workflows render and operate | Screenshot success is not semantic health or production monitoring |

## Audit Truth Versus Telemetry

Melloa needs two different evidence classes:

- **Audit truth:** durable, append-oriented, owner-visible records for
  security, authorization, mutation, egress, lifecycle, export, and recovery
  claims. These records must be queryable without a telemetry backend and must
  be backed by source-state semantics.
- **Operational telemetry:** short-lived counters, durations, gauges, traces,
  and structured logs for diagnosing latency, load, dependency failures,
  backlogs, and resource pressure. Telemetry helps operate the system; it must
  not become the source of truth for owner actions or security claims.

Rules:

- Audit evidence wins when audit and telemetry disagree.
- A telemetry exporter failure must not block owner reads, accepted source
  mutations, Guardian reads, or audit appends.
- A security-relevant audit append failure must follow the per-mutation failure
  semantics table proposed by TR-001 follow-up work. Until a path has explicit
  semantics, do not claim source-plus-audit atomicity.
- Telemetry may reference low-cardinality categories and bounded reason codes.
  Owner-authenticated audit or inspection views may carry internal record IDs;
  exported metrics must avoid owner IDs, message IDs, action hashes,
  idempotency keys, destinations, filenames, and provider credentials.

## Privacy and Redaction Boundary

Default collection is local, disabled for external export, and safe for the
no-network preview. Any future OpenTelemetry or log export must pass this
allow/deny boundary before data leaves the process:

| Data class | Audit and owner inspection | Metrics/log labels | External telemetry export |
| --- | --- | --- | --- |
| Message text, prompts, model output, memory values, media bytes | Forbidden except through the domain content store and authenticated owner views | Forbidden | Forbidden |
| Credentials, DSNs, token file paths, Guardian private material, deployment state | Forbidden | Forbidden | Forbidden |
| Owner, session, message, turn, work, audit, action, and idempotency IDs | Allowed only where the owner-visible contract requires them | Forbidden as labels; counts only | Forbidden unless hashed into a bounded diagnostic sample with owner opt-in |
| Route kind, provider class, processing location, health state, queue state, reason code | Allowed | Allowed when values are bounded enums | Allowed only to a local/private collector by explicit configuration |
| Durations, counts, byte sizes, retries, attempts, backlog age, cost totals | Allowed | Allowed, preferably as buckets or windowed aggregates | Allowed when no personal identifiers are attached |
| Sensitivity class and external-disclosure boolean | Allowed | Allowed as bounded labels | Allowed only in aggregate |
| Raw stack traces and exception text | Redacted before owner display | Redacted and normalized to reason codes | Redacted; no secrets or paths |

Debug capture may exist later only as an owner-visible temporary mode with an
expiry, a narrow scope, and an audit record that says it was enabled.

## Cardinality Boundary

Metrics and exported trace attributes should use a small stable vocabulary:

- component category and component ID from `HealthCategory` and
  `ComponentHealth`;
- route kind, processing location, and external-disclosure boolean;
- queue domain (`conversation_reply`, `outbound_delivery`, `telegram_poll`,
  `telegram_quarantine`) and queue state;
- reason codes already exposed in health, route, retention, export, and worker
  reports;
- result class (`accepted`, `denied`, `completed`, `dead`, `retry_scheduled`,
  `unavailable`, `disabled`, `skipped`, `environment_blocked`).

Do not use unbounded IDs, exception strings, prompt names, arbitrary URLs,
Telegram user/chat identifiers, destination refs, file paths, branch names, or
provider response text as metric labels.

## Failure Semantics

| Failure | Required behavior |
| --- | --- |
| Telemetry collector unavailable | Core continues. Health reports telemetry as disabled or degraded. No retry storm, no owner data spool to an external sink. |
| Metrics/log emission fails | Drop or locally count the telemetry failure. Never fail a source mutation because a metric could not be emitted. |
| Audit append fails before mutation | Fail closed for security-sensitive operations where no source state was changed. Return a bounded owner/operator error. |
| Audit append fails after mutation | Preserve honest retry/idempotency semantics and expose the gap. Do not pretend atomicity; use the TR-001 semantics table. |
| Health probe fails | Return `unavailable` for the component with a bounded reason code and redacted summary. Do not expose connection strings, token paths, or host inventories. |
| Queue lease expires | Recover through the queue's existing lease-expiry transition and expose attempt/dead state through owner status views. |
| Provider health probe fails | Route remains inspectable as degraded/unavailable/unknown. Invocation routing must still enforce privacy, retention, cost, and reliability constraints. |
| Recovery gate is skipped or environment-blocked | Record it as skipped or environment-blocked, not passed. Include exact command and failure class. |

## M1 Operational SLO Candidates

These are preview acceptance targets, not public service promises:

| Area | Candidate target | Evidence source |
| --- | --- | --- |
| Owner API readiness | Ready endpoint returns success only when Guardian mode permits the preview and configured dependencies are usable | `/health/ready`, Guardian status, health report |
| Conversation reply work | Accepted owner messages expose processing status immediately and eventually reach completed, retry, or dead state | conversation processing API, timeline, audit event when implemented |
| Delivery work | Owner-enqueued delivery exposes status immediately and terminal failures are resumable with fresh policy | delivery status API, delivery audit events |
| Model route disclosure | 100 percent of completed model results have route/provider/model identity, timing, cost/token fields, and external-disclosure state | model activity report and turn inspection |
| Provider failure handling | Eligible fallback attempts are recorded, and all-route failure returns a bounded reason code | model route attempts and route health |
| Telegram polling | Poll worker reports healthy, disabled, or degraded with a bounded reason code; offset advancement remains monotonic | Telegram worker health and poll state |
| Retention visibility | Every reported retention policy has matching inventory or an explicit unavailable/partial reason | retention report |
| Export validation | Every generated preview export passes checksum, schema, and reference validation, or reports precise validation failures | export readiness and `import-validate` |
| PostgreSQL restart durability | In PostgreSQL mode, selected sessions, conversations, memory changes, queues, Telegram control state, and audit records survive core restart | integration evidence and PostgreSQL health |
| Recovery evidence | Clean recovery gates are either passed with receipts or explicitly marked environment-blocked/skipped | `make recovery`, operations runbook, CI evidence |

## Acceptance Matrix

| Priority | Work item | Scope | Acceptance evidence |
| --- | --- | --- | --- |
| P0 | Audit/telemetry contract | Define the source-of-truth rule, per-mutation audit failure semantics, and telemetry non-blocking behavior in code/docs before new mutation categories are added | Tests or review matrix showing each owner mutation's source/audit ordering and retry behavior |
| P0 | Low-cardinality health and queue gauges | Add local metrics for health state, queue ready/running/dead counts, oldest due age, retry count, and lease-expiry count for conversation, delivery, Telegram, and quarantine | No-network tests prove metrics contain no IDs/content and match owner status views |
| P0 | Operational evidence receipt | Produce a redacted JSON receipt for release runs that records revision, commands, pass/fail/skipped/environment-blocked state, health snapshot, export validation status, Guardian mode, and PostgreSQL/recovery proof links | `make check` or a separate evidence command can generate and validate the receipt without external network |
| P1 | Disabled-by-default telemetry adapter | Add a local OpenTelemetry-compatible adapter behind explicit configuration. Default remains off; external endpoints require private/loopback target validation and owner opt-in | Tests prove default emits nothing externally; configured local collector receives only allowed attributes |
| P1 | Provider/billing reconciliation | Add a route/provider usage report that compares recorded model activity to configured provider billing/export evidence when available | Owner-visible report marks unknown/unreported cost distinctly, especially for subscription CLI routes |
| P1 | PostgreSQL operational views | Add read-only views or queries for audit append continuity, table migration version, queue backlog, stale leases, and backup/export readiness without exposing row payloads | Integration tests verify readonly role can inspect views but cannot mutate protected state |
| P1 | Recovery drill receipt | Extend recovery evidence to produce machine-readable RPO/RTO, dump/checksum/restic check results, restore identity, read-only denial, and unsupported M1 coverage | Recovery command emits a receipt and docs state it remains synthetic until production data scope exists |
| P1 | Owner Console evidence dashboard | Show health, queue states, route health, export limitations, recovery/evidence status, and recent dead work in one operational page | Browser smoke proves labels remain redacted and disabled/incomplete states are explicit |
| P2 | Structured local logs | Normalize bounded reason-code logs for lifecycle, worker cycle, route health, export, and recovery events | Unit tests or snapshot checks reject raw message text, prompts, token paths, and DSNs |
| P2 | Alert thresholds | Add owner-configurable local alerts for dead work, stale queues, export validation failure, backup age, provider outage, Guardian stopped/no-actions, and disk pressure | Synthetic tests prove alerts are owner-visible and do not send external notifications by default |

## Non-Goals For M1

- No third-party SaaS telemetry dependency.
- No raw prompts, messages, memory values, media, credentials, or deployment
  state in telemetry.
- No production SLO promise, uptime promise, or support guarantee.
- No claim that current export validation is backup or restore.
- No self-healing behavior that hides audit gaps, failed migrations, corrupted
  backups, or unexpected side effects.
- No high-availability database or multi-node tracing system before a single
  owner deployment proves the need.

## Recommended Sequence

1. Treat clean generated evidence and the locked dependency inventory as release
   prerequisites.
2. Implement the audit/telemetry contract and mutation failure-semantics matrix.
3. Add local low-cardinality health and queue metrics from existing owner status
   projections.
4. Add a no-network operational evidence receipt for release and recovery runs.
5. Add the disabled-by-default telemetry adapter only after redaction and
   cardinality tests exist.

This sequence keeps M1 honest: audit remains the durable truth, telemetry
remains diagnostic, and the default preview stays local, inspectable, and
safe to run without external services.
