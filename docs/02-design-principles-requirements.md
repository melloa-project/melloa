# Design principles, requirements, and non-requirements

## Design principles

### 1. Identity is durable; cognition is replaceable

Melli persists through durable state and accountability. A model call is an implementation detail. No table or API should use `agent_id` to mean model name, process ID, or API key.

### 2. Observation is not interpretation

Raw sensor output, a detector label, a multimodal model statement, a current belief, and a user-confirmed fact are separate records connected by provenance.

### 3. Models propose; deterministic systems authorize

An LLM may recommend an action. It cannot grant itself permission, mint a credential, broaden network access, or redefine the policy used to judge its proposal. Prompt text is not a security boundary; OWASP explicitly treats direct and indirect prompt injection as persistent risks that RAG and fine-tuning do not eliminate. [S14](research/primary-sources.md#S14)

### 4. Autonomy is scoped, not global

Authorization depends on principal, action, resource, purpose, data class, risk, reversibility, time, rate, and budget. “Autonomous mode” is not a sufficient policy.

### 5. Prefer the cheapest adequate intelligence

Tier 0 rules and CV should discard uninteresting data. Local models should handle sensitive or routine work when adequate. Frontier models should be used where quality materially changes the outcome. Route by evidence, not ideology.

### 6. Durable facts, rebuildable indexes

The canonical record is relational and append-only where provenance matters. Embeddings, summaries, caches, and search indexes are derived and can be regenerated.

### 7. Reversible by default

Configuration changes, interventions, deployments, and memory corrections should have clear rollback or supersession semantics. Irreversible actions require stronger evidence and authority.

### 8. Private first-party access without public ingress

The blessed V1 provides the Owner Console over the private network or local LAN and may use Telegram long polling as a secondary transport. It does not require a public domain, public reverse proxy, or inbound webhook.

### 9. External shutdown beats cooperative shutdown

The owner-controlled Guardian must be able to stop or isolate autonomous workloads using credentials and control paths those workloads do not possess.

### 10. Documentation and replay are infrastructure

ADRs, schemas, runbooks, prompt/model versions, and event replays are required for safe evolution, not polish added after implementation.

### 11. One excellent deployment path

Support one opinionated Linux + Compose path first. Clean contracts enable alternatives later; configuration sprawl does not.

### 12. Complexity requires a measured trigger

Every new service, database, language, broker, agent identity, or cloud dependency needs a threshold and an owner. “May be useful someday” is insufficient.

### 13. The owner can inspect and correct the system

The owner must be able to converse with Melli and inspect the evidence, uncertainty, policy, tools, actions, costs, disclosures, media, and outcomes behind system behavior. Inspection uses durable structured records rather than hidden chain-of-thought.

## Functional requirements

### R-F01 — Persistent intelligence continuity

Melli SHALL retain an owner-inspectable identity, relationships, goals, memories, correction history, and action history independent of any specific model or provider.

### R-F02 — Event and provenance ledger

Melloa SHALL persist canonical events with immutable IDs, timestamps, source, schema version, sensitivity, trust/taint metadata, evidence links, and causal/correlation links where known.

### R-F03 — Uncertainty-aware perception

Every semantic sensor conclusion SHALL include confidence and evidence. Low-confidence claims SHALL remain hypotheses or trigger clarification rather than silently becoming facts.

### R-F04 — Policy-mediated actions

Every side-effecting action SHALL be authorized by a deterministic broker before execution. Authorization SHALL return `deny`, `allow`, or `require_approval`, plus constraints and obligations.

### R-F05 — Exact-action approvals

An approval SHALL bind to a canonicalized action hash, resource, constraints, expiry, and approving identity. Material changes invalidate it.

### R-F06 — Capability introspection

Melloa SHALL know installed capabilities, their health, permissions, data classes, side effects, cost characteristics, and versions.

### R-F07 — Model routing

The runtime SHALL route by task quality, modality, latency, privacy, retention policy, context length, reliability, and cost. The route and reason SHALL be logged.

### R-F08 — Progressive memory

Melloa SHALL support raw observations, interpretations, beliefs, confirmed facts, episodes, semantic assertions, goals, policies, interventions, outcomes, and software/deployment history without collapsing them into one vector store.

### R-F09 — Corrections

The owner SHALL be able to correct or dispute beliefs. Corrections SHALL append provenance and update projections without erasing historical evidence.

### R-F10 — Proactive interaction budget

Proactive communication SHALL respect quiet hours, urgency, confidence, interruption budgets, cooldowns, and channel sensitivity.

### R-F11 — Replay and evaluation

Historical events SHALL be replayable through candidate prompts, models, policies, and consumers without re-triggering real-world side effects.

### R-F12 — Governed software creation

Generated software SHALL be developed in isolation, tested, scanned, evaluated, reviewed according to risk, deployed gradually, observed, and rolled back when needed.

### R-F13 — Owner-only emergency control

The owner SHALL be able to change Guardian mode to at least `normal`, `no-actions`, `read-only`, `offline`, `stopped`, and `recovery` independently of Melli.

### R-F14 — Export and deletion

The owner SHALL be able to export canonical data, schemas, blobs, policies, and memories in documented formats and delete selected data with an auditable tombstone process.

### R-F15 — Cost and rate controls

Every external provider and capability SHALL support daily/monthly cost ceilings, request limits, loop detection, and emergency disablement.

### R-F16 — Private Owner Console

Melloa SHALL provide a private, authenticated web console for first-party conversation, timeline and provenance inspection, memory correction, media review, decision/run inspection, capability and policy visibility, cost/disclosure reporting, and operational health. The console SHALL require no public internet ingress.

### R-F17 — Channel-independent conversation

Melloa SHALL persist canonical threads, messages, attachments, participants, citations, corrections, action proposals, and delivery attempts independently of any client or transport. The Owner Console SHALL be the primary client; Telegram MAY be enabled as a replaceable secondary adapter.

## Non-functional requirements

| Area | V1 target |
|---|---|
| Security | No high-risk side effect without broker decision; no autonomous access to Guardian credentials; default-deny generated-code egress |
| Privacy | Raw private-room media remains device-local by default; external transmission is explicit and logged |
| Reliability | At-least-once job delivery with idempotent consumers; graceful operation through temporary internet/model outages |
| Recoverability | Documented clean-machine restore; V1 RPO ≤ 24 h and RTO ≤ 4 h after the first restore drill |
| Observability | Trace observation → inference → policy → action → outcome; record model/prompt/tool/cost/egress versions |
| Maintainability | One primary application language; no distributed broker or orchestrator without migration trigger |
| Performance | Tier 0 detection under roughly 500 ms; event interpretation usually under 15 s when cloud is available; daily loops need no real-time SLO |
| Scale | One owner, one core host, one camera initially; hundreds of canonical events/day; raw detector noise aggregated before the ledger |
| Portability | Provider adapters, documented schemas, JSONL/blob export, SQL migrations, reproducible Compose deployment |
| Auditability | Append-only security/action audit trail; sensitive payload minimization; clock and correlation IDs |
| Accessibility | Terminal-first installation plus a responsive private Owner Console; human-readable config, evidence, policy explanations, and correction flows |

## Explicit non-goals for early versions

- Non-technical consumer onboarding.
- Multi-tenant hosting or shared personal data.
- General surveillance of third parties.
- Continuous remote video recording.
- Unbounded email, browser, or document ingestion before injection controls mature.
- A universal “do anything” MCP gateway.
- Autonomous public communications, cloud IAM changes, destructive migrations, or financial transactions.
- Clinical diagnosis, emergency response, or medical-device behavior.
- A custom iOS application before the channel abstraction is proven.
- High availability across multiple sites.
- Replacing mature infrastructure tools with bespoke equivalents.

## Quantitative planning assumptions

These are sizing assumptions, not commitments:

- 50–500 canonical events/day after local aggregation.
- 5–50 semantic model escalations/day for the initial room-camera use case.
- 100–1,000 owner messages/month in early use.
- 10–50 GB/month of selectively retained visual media, rather than 0.6–1.3 TB/month of continuous 2–4 Mbps video.
- 15–30 W average core-host draw, approximately £2.82–£5.64/month at 26.11 p/kWh, excluding camera/network gear. [S45](research/primary-sources.md#S45)
- £15–£70/month operating cost for a disciplined MVP, with model usage as the dominant variable.

## Failure principle

Melloa should **fail closed on authority** and **fail useful on intelligence**. When a model provider is down, it may postpone rich analysis while still recording events. When the policy engine is unavailable, side-effecting actions stop rather than bypassing authorization.
