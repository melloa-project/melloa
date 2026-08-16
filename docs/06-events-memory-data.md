# Event system, memory architecture, and data lifecycle

## Purpose

Define how Melloa represents years of observations and decisions without confusing raw evidence, model interpretations, current beliefs, and owner-confirmed facts. The design must support correction, replay, schema evolution, deletion, and reconstruction of why Melli believed or did something.

## Decision

Use PostgreSQL as a canonical **provenance ledger plus current-state store**. Do not implement textbook pure event sourcing for every aggregate. Append immutable events where history matters, and maintain ordinary relational projections for current state and efficient queries.

Embeddings, summaries, clusters, and knowledge-graph edges are derived views. They may be deleted and rebuilt. They are never the only copy of a durable fact.

## Canonical event envelope

Illustrative, not production code:

```json
{
  "event_id": "01J...",
  "event_type": "interpretation.person_entered.v1",
  "schema_version": "1.0.0",
  "occurred_at": "2026-08-15T19:42:11.215Z",
  "recorded_at": "2026-08-15T19:42:13.902Z",
  "subject_ids": ["person:owner", "place:private-room"],
  "source": {
    "capability_id": "camera.room-1",
    "observation_ids": ["obs_..."],
    "execution_id": "exec_..."
  },
  "producer": {
    "component": "perception.interpreter",
    "version": "0.3.1",
    "model_route": "local-vlm-small",
    "model_id": "provider/model@revision",
    "prompt_version": "camera-event-v7"
  },
  "epistemic_status": "interpretation",
  "confidence": 0.82,
  "alternatives": [
    {"claim": "person already present and stood up", "confidence": 0.13}
  ],
  "sensitivity": "highly_sensitive",
  "trust": "untrusted_sensor_derived",
  "retention_policy": "event-long-evidence-7d",
  "correlation_id": "corr_...",
  "causation_id": "evt_...",
  "payload": {"zone": "door", "direction": "in"},
  "evidence": [
    {"blob_hash": "sha256:...", "media_type": "image/jpeg", "expires_at": "..."}
  ],
  "integrity": {"payload_hash": "sha256:..."}
}
```

### Envelope rules

- `event_id` is immutable and globally unique within an installation.
- `occurred_at` describes the domain time; `recorded_at` describes ingestion time. Both are retained.
- Event type includes a major schema line; the full semantic version is explicit.
- Producer metadata records the component, model, prompt, and relevant configuration version.
- Confidence is calibrated per event family where possible; it is not comparable across arbitrary models without calibration metadata.
- Sensitivity and trust/taint labels travel with the event and constrain routing and retrieval.
- Evidence is addressed by cryptographic hash and may expire independently of the event.
- Corrections append new events and update projections; they do not mutate the old event.
- Correlation does not imply causation. `causation_id` is used only for known processing lineage, not causal inference about human behavior.

## Event families

| Family | Examples | Retention posture |
|---|---|---|
| Observation | motion interval, frame hash, Telegram message, API response | Raw/high-volume; short or source-specific retention |
| Interpretation | person entered, desk occupied, request intent | Longer than evidence; uncertainty required |
| Belief change | owner likely asleep, routine shifted | Retain with supersession and validity intervals |
| Confirmation/correction | owner confirms workout; disputes “went to bed” | Long-lived and high retrieval priority |
| Goal/policy | goal accepted, policy changed, grant revoked | Long-lived, signed/auditable |
| Decision | action proposed, route selected, no-action decision | Long-lived enough to explain behavior and costs |
| Action | Telegram sent, file read, deployment started | Audit retention; side-effect result and authorization link |
| Outcome | run occurred, owner dismissed prompt, deployment error rate | Long-lived for evaluation |
| Software/infrastructure | commit, build, migration, deploy, rollback | Long-lived; link to Git/release artifacts |
| Security/operations | auth failure, kill switch, secret rotation, restore test | Append-only audit policy |

## PostgreSQL logical schema

The exact physical schema should be validated by implementation spikes, but the domain should remain separable:

```text
identity            owner, persistent_intelligence, worker_execution
observations        raw metadata and blob references
interpretations     model/detector claims and alternatives
belief_assertions   temporal assertions, confidence, status
confirmations       owner confirmations, disputes, corrections
canonical_events    envelope and normalized indexes
provenance_edges    derived_from, supports, contradicts, supersedes
current_state       projections such as presence, routines, active goals
goals               values, objectives, goals, strategies
experiments         hypotheses, interventions, assignments, outcomes
policies             versions, grants, approvals, budgets
capabilities        manifests, installations, health, leases
model_runs          prompts/templates, routes, usage, validation
proposed_actions    canonical action request and risk classification
executed_actions    authorization, result, cost, outcome links
jobs_outbox         durable asynchronous work
artifacts           content hashes, versions, signatures
schema_registry     event/schema/prompt compatibility metadata
audit_events        security and administrative record
```

Use PostgreSQL roles and grants first. Row-level security may later partition memory/capability scopes, but it must be tested carefully and must not be the only barrier protecting highly privileged administration paths. PostgreSQL's row security defaults to deny when enabled without a policy, while owners and bypass roles require special attention. [S04](research/primary-sources.md#S04)

## Memory layers

### Layer 0 — transient working context

A bounded, per-run context assembled for one task. It is not automatically retained. It references durable IDs instead of copying entire histories when possible.

### Layer 1 — raw observations

Source-faithful metadata and optional blobs. Retention is short by default for camera media and longer where source records are already durable, such as owner messages.

### Layer 2 — interpretations

Versioned semantic claims derived from observations. Multiple interpretations may coexist. They retain evidence and the model/detector version.

### Layer 3 — episodic memory

Curated sequences such as “worked late at the desk for three evenings before release.” Episodes have temporal boundaries, participants, evidence, and summary provenance.

### Layer 4 — semantic assertions

Claims such as preferences, routines, relationships, and stable facts. Every assertion has:

- subject, predicate, object/value;
- valid-from/valid-to and observed-at times;
- confidence and epistemic status;
- supporting and contradicting evidence;
- source authority;
- sensitivity and sharing policy;
- supersession/correction links.

### Layer 5 — goals, policies, and commitments

These are not inferred facts. They are owner-authored or explicitly accepted normative records. Retrieval should prioritize their current version and display change history.

### Layer 6 — intervention and outcome memory

Records what Melloa tried, why, under which policy, whether it was delivered, how the owner responded, what outcome was observed, and how confident the evaluation is.

### Layer 7 — system and software memory

Prompts, model routes, schemas, code changes, deployments, migrations, incidents, costs, and ADRs. This enables operational learning without mixing platform facts into personal semantic memory.

## Belief lifecycle

A belief is a temporal projection over assertions, not a mutable text blob.

```text
candidate interpretation
        ↓
provisional belief (confidence + expiry)
        ↓
corroborated by more evidence / contradicted / owner-confirmed
        ↓
active belief with validity interval
        ↓
superseded, expired, disputed, or retracted
```

### Promotion policy

- One weak sensor event should rarely create a durable semantic fact.
- Repeated events may support a routine hypothesis, but the system should preserve the statistical basis and time window.
- Owner confirmation should be stored as an authoritative statement for the specified scope, not as proof of every related inference.
- High-impact beliefs—health, relationships, finance, identity—need stronger evidence and shorter automatic validity unless confirmed.

## Corrections and contested memory

When the owner says “I wasn't asleep; I was reading,” Melloa should:

1. append the correction with the target claim ID;
2. mark the original belief disputed or superseded in the current projection;
3. retain the original interpretation and evidence for model evaluation;
4. create a corrected assertion with owner authority and temporal scope;
5. add the example to a detector/prompt regression dataset if consent and retention permit;
6. avoid resurfacing the false claim as fact in future summaries.

Deletion is different from correction. A deletion request may remove blobs and payloads while retaining a minimal tombstone proving that an ID was intentionally removed, unless the owner requires complete erasure and accepts loss of audit linkage.

## Retrieval architecture

Retrieval is a policy-constrained query plan:

1. identify task purpose and permitted memory scopes;
2. apply identity, sensitivity, and temporal filters;
3. retrieve exact relational facts and recent episodes;
4. use full-text and vector similarity only as candidate generation;
5. rerank by provenance quality, confirmation, recency, contradiction, and task relevance;
6. assemble citations to memory IDs in the model context;
7. log the retrieval manifest and data that leaves the device.

A vector nearest neighbor is not evidence. `pgvector` is selected because it keeps semantic indexes beside the relational source and supports exact and approximate search, but the vector table is rebuildable. [S05](research/primary-sources.md#S05)

## Summarization and compression

Summaries must never overwrite source records silently.

- Daily summaries reference included events and the summary prompt/model version.
- Weekly episodes may supersede prior summaries as the preferred retrieval artifact while old versions remain traceable.
- Long-term semantic assertions are extracted separately from narrative summaries.
- A summary can expire or be regenerated after corrections.
- High-volume low-value observations may be deleted after aggregate features and integrity counts are stored.

## Schema evolution

### Event schemas

- JSON Schema 2020-12 for validation and generated documentation. [S11](research/primary-sources.md#S11)
- Additive changes within a major event type; breaking semantic changes create a new major type.
- Producers write one version; consumers declare accepted versions.
- Upcasters may produce a current view without mutating historical payloads.
- A compatibility test suite replays representative historical events.

### Database migrations

- Alembic migrations are immutable after release.
- Destructive changes use expand → backfill → switch → contract.
- Every migration declares rollback feasibility and backup prerequisite.
- Production migrations run from a restricted release identity, never an ordinary Melli worker.

### Prompt and model versions

Prompt templates, retrieval policies, output schemas, and model route policies are versioned together. Reproducibility means reconstructing the inputs and versions; it does not promise bit-identical stochastic output from a hosted model.

## Event transport

V1 uses PostgreSQL jobs/outbox. Writes to domain state and new work are atomic. Workers poll durable rows; `LISTEN/NOTIFY` reduces latency but is not durability. The transactional outbox pattern explicitly addresses dual-write inconsistency and assumes duplicate delivery, so consumers must be idempotent. [S06](research/primary-sources.md#S06) [S07](research/primary-sources.md#S07)

A CloudEvents-inspired envelope is useful for interoperability, but Melloa should not contort its epistemic/provenance requirements to match a generic transport envelope. [S10](research/primary-sources.md#S10)

## Replay and simulation

Replay reads a selected event interval, creates a new isolated execution namespace, and disables real side effects. It can compare:

- old and candidate camera classifiers;
- prompt/model routes;
- memory extraction and contradiction handling;
- policy decisions;
- proactive-message usefulness predictions;
- daily/weekly summaries;
- cost and latency.

Every replay result records the source event snapshot, code revision, schema adapters, model/prompt versions, random seeds where applicable, and scorer versions.

## Data lifecycle

| Stage | Decision |
|---|---|
| Collect | Capability must declare purpose, sensitivity, and default retention |
| Buffer | Raw sensor buffer is encrypted/local and bounded |
| Detect | Cheap local rules discard or aggregate low-value changes |
| Interpret | Selected evidence is processed under routing policy |
| Persist | Canonical event and provenance are committed atomically |
| Index | Full-text/vector/episode indexes are derived asynchronously |
| Use | Retrieval is purpose- and policy-scoped; egress is logged |
| Summarize | New artifact references source IDs and versions |
| Archive | Cold or offsite encrypted storage according to class |
| Delete | Blobs/payloads are removed; projections and indexes are rebuilt; tombstone policy applies |
| Export | JSONL + schemas + blob manifest + checksums + SQL snapshot |

## Build now

- Event envelope, provenance edges, observation/interpretation/belief/confirmation distinction.
- Database migrations, jobs/outbox, idempotency keys, event replay namespace.
- Content-addressed blob IDs and retention sweeper.
- Relational retrieval with citations; optional embeddings after baseline queries work.
- Owner correction workflow.

## Design for

- Separate edge event nodes and broker adapter.
- Cryptographic signatures from remote capabilities.
- Multiple persistent-intelligence memory partitions.
- Selective encrypted sharing and portable export bundles.

## Defer

- Graph database as the source of truth.
- Automatic permanent-memory promotion for every chat.
- Indefinite raw media retention.
- Exact-once claims across external APIs.
- Rewriting historical payloads to the newest schema.
