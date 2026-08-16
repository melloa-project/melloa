# Adversarial review, open questions, and rejected ideas

## Purpose

Expose unresolved trade-offs and document what Melloa deliberately refuses to build. The architecture is stronger when objections remain visible rather than being edited out of the final recommendation.

## Independent reviewer findings

### Security reviewer

**Objection:** A model that reads hostile content and can operate tools should be assumed compromisable. A policy engine called by the same compromised process is not enough.

**Resolution:** Authorization is deterministic and enforced at the capability broker; credentials are scoped/brokered; generated code is isolated; egress is constrained; Guardian/root authority is inaccessible to the autonomous plane. High-impact approvals bind the exact action hash. Residual risk remains if the broker/host itself is compromised.

### Reliability reviewer

**Objection:** One host, one database, a camera pipeline, model APIs, Telegram, backups, and generated code create too many failure modes for a personal project.

**Resolution:** Accept one-host downtime, not data ambiguity. Keep PostgreSQL as the sole durable operational dependency, use bounded queues and graceful degradation, make camera and providers optional, and prioritize clean restore over HA. Do not add a queue cluster/workflow engine before measured need.

### Simplicity reviewer

**Objection:** Event sourcing, knowledge graphs, permanent agents, Kubernetes, Vault, SPIFFE, and microVMs are architecture cosplay for one user.

**Resolution:** Use append-oriented evidence/audit plus ordinary relational projections, rootless Compose, SOPS/keyring, one Melli, temporary workers, and gVisor only when generated code exists. Preserve interfaces, not unused platforms.

### AI researcher

**Objection:** Current models are unreliable at persistent identity, long-horizon planning, causal inference, and self-evaluation. Calling an agent “continuous” does not create continuity.

**Resolution:** Put continuity in durable identity, memory, goals, relationships, policies, and change history. Treat models as replaceable cognitive engines. Break long-horizon work into explicit proposals/workflows with checkpoints. Use replay and owner feedback, and make “unknown/inconclusive” a valid result.

### Privacy reviewer

**Objection:** A private-room camera plus years of memory is intrinsically high risk, especially for visitors and cloud model disclosure.

**Resolution:** Camera is not required for initial value. When enabled: visible/private-space deployment, consent, isolated network, local segmentation, short raw retention, no continuous cloud upload, strict third-party handling, camera-off controls, and disclosure reports. Some residual privacy risk is unavoidable; users who reject it should disable the capability.

### Open-source maintainer

**Objection:** Personal assumptions and one-off hardware will make the repository impossible for others to reproduce.

**Resolution:** One blessed deployment, synthetic fixtures, stable contracts, documented personal configuration boundary, ADRs, migrations, export/import, CI, and explicit unsupported alternatives. Open-source quality does not mean universal hardware compatibility.

### Cost reviewer

**Objection:** Frontier reasoning, multimodal interpretation, coding agents, and evaluation can make the system financially unbounded.

**Resolution:** Filter locally, batch periodic work, route by adequacy and privacy, record cost by goal/capability, enforce step/token/daily/monthly limits, and stop experiments before core functions. Avoid continuous cloud video and premature GPU purchase.

### Future-self reviewer

**Objection:** Five years of schemas, prompts, capabilities, summaries, experiments, and generated software will become archaeology.

**Resolution:** Precise vocabulary, immutable provenance, versioned contracts, migration adapters, a monorepo, ADRs, runbooks, retention, deletion, and periodic simplicity reviews. Every artifact has an owner/expiry; temporary experiments are not permanent by default.

## Resolved disagreements

| Tension | Decision |
|---|---|
| More autonomy vs safety | autonomy grows by demonstrated action class; authority remains deterministic and least-privileged |
| Local processing vs quality | local-first, not local-only; sensitivity and adequacy jointly route work |
| Event-driven vs simplicity | durable event/provenance records and DB jobs now; external event bus only after thresholds |
| Rich memory vs privacy | preserve durable high-value structured evidence; expire raw high-volume data aggressively |
| One agent vs many | one persistent Melli plus temporary specialists; separate persistent identities only for real authority/memory boundaries |
| Fast iteration vs stable architecture | stabilize contracts/trust boundaries, keep internal implementation replaceable |
| Single host vs resilience | accept downtime; invest in restore, not premature HA |
| Open source vs personal optimization | personal success is first; public-quality contracts/docs/reproducibility are constraints |

## Rejected ideas

### Kafka/Redpanda in V1

Rejected because throughput and multi-team replay requirements do not justify another distributed durable state system. PostgreSQL jobs/outbox preserve a migration path. Revisit after measured backlog, multiple nodes, or independent consumer scaling.

### Kubernetes/service mesh in V1

Rejected because one host and a handful of processes gain little from a cluster control plane, certificates, controllers, and upgrade burden. Compose plus systemd/Ansible is inspectable and recoverable.

### Vector database as “memory”

Rejected because similarity search cannot represent provenance, correction, temporal truth, policy, or epistemic status. `pgvector` is a rebuildable retrieval index over canonical relational records.

### Graph database as primary store

Rejected because V1 relationships fit PostgreSQL tables/recursive queries and a second primary database increases migrations/backups/operational burden. Add a graph projection only after concrete queries demonstrate value.

### Pure event sourcing for all state

Rejected because reconstructing every operational object from an eternal log creates schema/replay complexity. Preserve append-oriented evidence and action history while maintaining normal current-state projections.

### Permanent multi-agent society

Rejected because multiple named agents create coordination, accountability, memory partition, and security questions without demonstrated benefit. Use temporary specialists under Melli’s run/proposal and policy boundary. Add persistent agents only for a durable distinct identity/responsibility/permission relationship.

### Raspberry Pi as the blessed core server

Rejected because storage endurance, memory/headroom, hardware variability, and future sandbox/model workloads make a modest x86 mini-PC a more maintainable default. Raspberry Pi remains useful as an edge camera/sensor node.

### Continuous cloud video interpretation

Rejected for privacy, bandwidth, storage, cost, and false-confidence reasons. Local segmentation and selective evidence are required.

### Telegram webhook/public domain in V1

Rejected because long polling avoids public ingress for one user. Telegram remains a convenience channel, not a confidential or root-control plane.

### Local-only models as doctrine

Rejected because privacy is one routing dimension; inadequate local intelligence can reduce usefulness and safety. Use the cheapest adequate eligible model and make disclosure explicit.

### Giant `.env` and ambient credentials

Rejected because any compromised process would inherit unrelated authority. Use scoped roles, brokered leases, OS/key management, and provider-side limits.

### OpenBao/Vault on day one

Rejected because operating a secret-management service adds an unsealing/recovery/availability system before dynamic credentials or multiple nodes justify it. Preserve a broker interface and migrate when needed.

### Firecracker/microVM fleet on day one

Rejected because generated code is deferred and rootless containers/gVisor plus no secrets/egress provide a simpler initial boundary. Firecracker is a future stronger isolation tier, not a checkbox.

### MCP as universal internal protocol

Rejected because MCP is useful at model/tool integration boundaries but does not replace Melloa’s policy, provenance, durable event, identity, or capability contracts. The architecture must survive protocol evolution.

### Autonomous cloud IAM, finance, or governance

Rejected in early versions because blast radius, irreversibility, external obligations, and approval ambiguity exceed demonstrated trust. Melli may draft exact plans; the owner executes/approves through a separate path.

### Unbounded “daily AI reflection”

Rejected because repeated summaries can create cost and self-reinforcing false beliefs. Periodic loops operate only on new evidence, explicit questions, and budgets; no-op is a valid result.

## Assumptions the research changed

1. **A Raspberry Pi is not the best default core.** It is a good edge component; a wired x86 mini-PC is the maintainable blessed host.
2. **Telegram is not a permanent/private UI.** Bots are useful as an optional secondary channel, while the private Owner Console is required for first-party conversation, inspection, correction, and operational control.
3. **An event-driven design does not require an event-bus product.** PostgreSQL can provide the durable V1 ledger/jobs/outbox while preserving later ports.
4. **More named agents are not automatically more capable.** Persistent identities need distinct long-lived responsibility, memory, permissions, or relationships—not just specialized prompts.
5. **A vector database is not memory.** Provenance and epistemic structure are the hard parts; vectors are derived retrieval aids.
6. **Local-first should not become local-only.** Quality, privacy, latency, cost, and modality jointly determine routing.
7. **Code generation is not the hardest part of self-modification.** Authorization, evaluation, deployment, rollback, and knowing whether the change helped are harder.
8. **The camera should not be the first milestone.** Trustworthy identity, memory, policy, audit, and recovery must exist before rich sensing.
9. **A public domain is unnecessary for V1.** Long polling and private networking eliminate most inbound exposure.
10. **“Jarvis-like” value is not primarily voice or UI.** The differentiator is the closed outcome-evaluated loop and durable relationship.

## Open questions, ranked

### P0 — resolve before implementation or enabling the capability

1. What exact owner authentication and recovery design protects Guardian actions on the chosen host?
2. Which policy language/runtime best fits typed, explainable action decisions without creating an expert-only UX—small in-house evaluator first, Cedar adapter, or another option?
3. What are the exact V1 event/assertion schemas and correction/supersession invariants?
4. Which provider/model routes are eligible for each sensitivity class under the owner’s jurisdiction and current contracts?
5. What camera placement/room consent and “camera off” physical indicator meet the owner’s real environment?

### P1 — answer through early prototypes/evidence

6. Does Frigate provide the right candidate-event interface, or is a thinner FFmpeg/OpenCV detector more maintainable for the selected camera?
7. How often do daily/weekly loops produce net value before notification/cost fatigue?
8. What local model tasks are actually adequate on the selected mini-PC or Apple Silicon device?
9. Which memory retrieval strategy minimizes plausible but unsupported synthesis over months?
10. What exact canary and rollback metrics are meaningful for prompt/model changes?
11. Which maintained local/private authentication implementation best satisfies Owner Console sessions, reauthentication, recovery, and future passkeys without coupling domain identity to one vendor?
12. At what observed job volume/node count should NATS or Temporal be introduced?

### P2 — intentionally deferred research

13. When should another persistent intelligence be created rather than an ephemeral specialist?
14. What native iOS/HealthKit architecture and consent model is justified?
15. Does voice in a private room produce enough value to justify microphone privacy and wake-word/streaming complexity?
16. When is OpenBao/SPIFFE/workload identity worth the operational cost?
17. Can intervention evaluation become more rigorous without turning the owner’s life into an experiment platform?
18. What legal/licensing obligations apply to AI-generated plugins and redistribution of model-derived artifacts?
19. What is the durable process for Melli choosing/changing its own name while preserving identity continuity and owner control?

## Simplicity review cadence

Quarterly, ask:

- Which service, capability, prompt, model, dataset, dashboard, or periodic loop has not produced measurable value?
- Which derived data can be rebuilt or deleted?
- Which permissions were unused?
- Which operational dependency can be removed?
- Which abstraction has only one implementation and no credible near-term alternate?
- Which “temporary” experiment lacks an owner/expiry?

Deletion is an architectural capability.
