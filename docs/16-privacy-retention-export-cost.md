# Privacy, retention, ownership, and cost

## Purpose

Maximize useful personal context while minimizing unnecessary exposure outside the owner’s trust boundary. Privacy is expressed through data classification, routing, retention, capability scope, and inspectable disclosure—not by pretending that useful observation requires no access.

## Privacy stance

Melloa should say plainly when a capability needs sensitive data. Disabling camera, health, browser, or location access disables the experiences that depend on them. The architecture must still make collection narrow, processing local where adequate, external transmission explicit, retention bounded, and deletion/export real.

## Data sensitivity classes

| Class | Examples | Default storage | Default external-model policy |
|---|---|---|---|
| Public | public documentation, open-source code, public web pages | local, normal encryption | any approved provider |
| Internal | system health, non-personal configuration, synthetic tests | local | approved providers if needed |
| Personal | ordinary owner messages, calendar titles, routine summaries | encrypted local | approved provider with no-training/default API terms, task-minimized context |
| Sensitive | detailed health, financial records, private email/files, precise location | encrypted local with narrower access | local preferred; explicit provider/data-purpose route required |
| Highly sensitive | raw private-room media, intimate health, credentials metadata, private third-party content | separately controlled local store, short retention | deny by default; explicit per-capability exception |
| Device-only | recovery secrets, private keys, Guardian credentials, selected raw media | hardware/OS-backed or owner-controlled local path | never leave device/trust boundary |

Class is attached to each object and inherited conservatively by derived data. A summary can remain sensitive even when names are removed. Classification changes are audited.

## Processing and disclosure model

Each external invocation carries a **disclosure manifest**:

- data object/evidence IDs;
- sensitivity classes;
- exact fields or transformed artifact sent;
- provider/model and region/endpoint where known;
- purpose and lawful/owner policy basis;
- retention/training policy snapshot reference;
- token/media volume and cost ceiling;
- redactions or local transformations;
- deletion/expiry expectation where supported.

The owner can query, “What left the machine this week?” without reading raw logs.

API terms differ and change. OpenAI states that API data is not used to train its models by default; retention controls vary by endpoint/account. [S59](research/primary-sources.md#S59) Anthropic, Google, and Mistral also publish distinct commercial/API data-use and retention terms, so eligibility must be represented as versioned provider policy rather than assumed from brand reputation. [S60](research/primary-sources.md#S60) [S61](research/primary-sources.md#S61) [S62](research/primary-sources.md#S62)

## Collection principles

- Collect for a named capability, goal, experiment, security need, or owner request.
- Preserve provenance and consent/authority context.
- Prefer event-triggered capture over continuous archival.
- Separate third-party data from owner-only data and apply stricter sharing rules.
- Do not infer “not observed” as “did not happen.”
- Do not silently expand a data source’s purpose when a new model/plugin is installed.
- Make disabled, degraded, or partially observed periods visible.

## Retention schedule

These are V1 defaults, configurable within policy bounds.

| Data | Default retention | Long-term form | Notes |
|---|---:|---|---|
| Camera ring buffer | 30–120 seconds | none | overwritten unless an event triggers selection |
| Non-event candidate frames | 24 hours | none | enough for debugging/calibration; shorter for highly sensitive rooms |
| Selected event frames/clips | 7–30 days | structured event plus optional representative thumbnail | clips require value/sensitivity review |
| Structured observations/events | 1–7 years or owner policy | canonical event/provenance | low-volume and reconstructive value |
| Interpretations/hypotheses | until superseded plus history | append correction/supersession | never overwrite belief history silently |
| User-confirmed facts/preferences | until withdrawn or stale-review date | semantic memory with evidence | review sensitive/stale facts periodically |
| Raw Telegram messages | 90 days–1 year | selected durable memory/summary | Telegram remains an external copy outside Melloa control |
| Raw email/files/calendar data | source-linked cache 7–90 days | extracted facts/events only when justified | avoid duplicating entire source unnecessarily |
| Model prompts/responses | 7–30 days raw; metadata longer | run metadata, hashes, selected evidence | shorter for sensitive tasks; provider retention is separate |
| Operational logs/traces | 7–30 days | aggregate metrics and incidents | redact before storage/export |
| Audit/action/change ledger | multi-year | append-oriented record | deletion restricted; contains references rather than secrets |
| Quarantine/sandbox data | hours–7 days | none unless promoted | automatic expiry and hard quota |
| Backups | daily/weekly/monthly policy | encrypted snapshots | deletion propagates subject to documented backup expiry |
| Derived embeddings/indexes | while source retained | rebuildable | delete/rebuild when source/classification changes |

A retention worker produces deletion receipts and tombstones/rebuild tasks. Backups cannot offer immediate physical erasure; the UI must show the backup expiry horizon honestly.

## Camera storage arithmetic

Illustrative H.264/H.265-equivalent average bit rates, excluding overhead:

- 1080p at 2 Mbit/s continuously: about **21.6 GB/day** or **648 GB/30 days**.
- 1080p at 4 Mbit/s continuously: about **43.2 GB/day** or **1.30 TB/30 days**.
- 100 selected 15-second clips/day at 2 Mbit/s: about **0.375 GB/day** or **11.25 GB/30 days**.

Actual rates vary with codec, frame rate, scene complexity, night noise, and camera settings. The roughly 58× reduction in the example explains why local event segmentation is an architectural requirement rather than merely a cost optimization.

## Correction and deletion

- Corrections append a new assertion that supersedes or disputes the old one; provenance remains inspectable.
- Derived beliefs, summaries, embeddings, and decisions affected by a correction are queued for re-evaluation.
- Deletion supports scope: raw object, source integration, time range, memory claim, or full export-and-delete.
- Security/audit records may retain a minimal non-content tombstone when deletion itself must be accountable.
- External providers and source systems have independent retention; Melloa reports what it can and cannot delete.
- A “forget” request cannot honestly erase a fact from already generated human decisions or immutable offline backups before expiry.

## Data ownership and export

The canonical export is open, documented, and provider-independent:

```text
export-YYYYMMDD/
  manifest.json
  schemas/
  events/*.jsonl
  observations/*.jsonl
  assertions/*.jsonl
  goals-policies/*.jsonl
  actions-interventions/*.jsonl
  changes-audit/*.jsonl
  blobs/sha256/...
  blob-index.jsonl
  database/logical.sql.gz
  human-readable/summary.md
  checksums.sha256
  signature.json
```

Requirements:

- stable IDs and schema versions;
- ISO-8601 timestamps with original timezone/clock metadata;
- content hashes and provenance links;
- sensitivity and retention metadata;
- no proprietary vector representation required to reconstruct meaning;
- documented import/migration path;
- encrypted packaging for sensitive exports;
- validation tool that verifies checksums, referential integrity, and schema readability.

Export is a recovery and ownership feature, not a formatted report alone.

The current M1 preview implements the first validated slice of this path for canonical owner records: `melloa export-mvp` writes a manifest, copied JSON Schemas, JSONL conversation and memory-inspection records, and `checksums.sha256`; `melloa import-validate` verifies checksums, schema readability, and basic referential integrity without mutating a database. The manifest truthfully marks the bundle as unencrypted and excludes blobs and logical SQL snapshots. Encrypted packaging, blob export, full database snapshots, signatures, and a real import/migration executor remain V1 work rather than implied by this preview.

## Cost model assumptions

All figures are planning ranges in **2026 pounds sterling**, excluding developer labour, taxes/import differences, and internet already purchased. Model/provider pricing changes quickly and must be rechecked. OpenAI’s current public API pricing illustrates the large spread between small and frontier model tiers and the savings available for batch processing; it should not be treated as a commitment to one provider. [S35](research/primary-sources.md#S35)

### Hardware acquisition

| Component | Planning range |
|---|---:|
| x86 mini-PC, 16–32 GB RAM, 1 TB NVMe | £250–£500 |
| PoE ONVIF camera | £80–£250 |
| PoE injector/switch, cabling, mount | £30–£120 |
| USB backup drive | £70–£150 |
| UPS optional | £80–£180 |
| **Typical initial total** | **£510–£1,200** |

### Electricity

Using Ofgem’s July–September 2026 average electricity unit-rate benchmark of 26.11 pence/kWh for Great Britain: [S45](research/primary-sources.md#S45)

| Average continuous load | kWh/month (30 days) | Approx. cost/month |
|---:|---:|---:|
| 15 W | 10.8 | £2.82 |
| 30 W | 21.6 | £5.64 |
| 60 W | 43.2 | £11.28 |

A discrete local GPU can dominate power and hardware amortization; purchase it only after measured workloads justify it.

### Operating tiers

| Tier | Shape | Monthly planning range | Principal drivers |
|---|---|---:|---|
| A — MVP | one camera, local detection, Telegram, modest daily cloud reasoning | **£15–£70** | API inference, offsite backup, electricity |
| B — serious daily use | several integrations, daily/weekly reasoning, richer model routing | **£60–£300** | frontier calls, context volume, coding/eval runs |
| C — heavy personal AI | multiple sensors, frequent multimodal/coding agents, local accelerator | **£300–£1,200** | inference, hardware amortization, media/storage, evaluation |
| D — extreme setup | many sensors, extensive autonomous development, high-end local/cloud compute | **£1,200–£6,000+** | frontier multimodal/video, GPU/cloud compute, operational sprawl |

A disciplined first year, including hardware, is approximately **£800–£2,100**. Model-heavy experiments can exceed this easily.

### Storage and backup

Backblaze B2 currently publishes a benchmark price of roughly **US$6.95 per TB-month**, with policy details that must be reverified. [S43](research/primary-sources.md#S43) For V1, API inference usually costs more than a few tens of gigabytes of encrypted backup; continuous video retention reverses that relationship.

### What changes cost by 10×

1. Calling a frontier model for every sensor tick instead of filtering and batching locally.
2. Sending video or large image sequences to cloud multimodal APIs instead of selected evidence.
3. Repeatedly injecting years of raw history instead of retrieval manifests and summaries.
4. Running autonomous coding/review loops without step, token, and retry ceilings.
5. Retaining continuous multi-camera video rather than event clips.
6. Purchasing a high-end GPU before utilization is known.
7. Adding observability SaaS with raw/high-cardinality telemetry.

## Budgets and controls

- Per-call, per-run, per-capability, daily, and monthly limits.
- Soft alert thresholds before hard stops.
- Separate experimentation budget from ordinary service budget.
- Estimated maximum cost included in action/change proposals.
- Batch/off-peak routes for periodic work where latency is unimportant.
- No silent failover to a substantially more expensive model.
- Owner dashboard allocates spend to goal, integration, model route, and intervention.
- Stop or degrade low-value periodic loops before blocking owner-requested essential work.

## Build now

- Sensitivity classification and disclosure manifests.
- Retention/deletion worker and owner-visible policy.
- Export format with integrity validation.
- Cost accounting and hard ceilings.
- Camera ring/selected-clip policy; no continuous archive.

## Design for

- Provider-specific regional/ZDR eligibility, hardware-backed encryption keys, third-party consent labels, legal jurisdiction metadata, and privacy-preserving local transformation.

## Defer

- Permanent raw life-log, cloud video archive, proprietary memory store, blanket “anonymization” claims, and an expensive local GPU without measured demand.
