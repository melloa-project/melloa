# Melloa Architecture Specification v0.2 — Consolidated Edition

**Original research date:** 15 August 2026

**Decision update:** 16 August 2026

**Status:** Architecture v0.2 with implementation evidence; not production-ready

**Canonical form:** The modular Markdown suite under `docs/`; this file is a generated reading edition.

The supplied master research brief is preserved verbatim in the packaged suite. The v0.2 adopted decisions are authoritative where they intentionally supersede v0.1 product-priority wording. Contemporary facts, provider policies, prices, and named technologies are dated research snapshots and must be revalidated at implementation time.

## Contents

- [Melloa](#doc-index)
- [v0.2 adopted decisions and precedence](#doc-23-v0-2-decisions)
- [Requirement traceability](#doc-00-traceability)
- [Executive vision](#doc-01-executive-vision)
- [Design principles, requirements, and non-requirements](#doc-02-design-principles-requirements)
- [Conceptual model and naming](#doc-03-conceptual-model)
- [Alternative architectures](#doc-04-alternative-architectures)
- [Chosen V1 architecture](#doc-05-chosen-v1-architecture)
- [Event system, memory architecture, and data lifecycle](#doc-06-events-memory-data)
- [Agent, model-routing, goal, intervention, and reasoning architecture](#doc-07-agents-models-goals)
- [Capability, plugin, policy, and autonomy architecture](#doc-08-capabilities-policy-autonomy)
- [Security architecture, threat model, and prompt-injection defense](#doc-09-security-threat-injection)
- [Credential, secret, control-plane, and kill-switch architecture](#doc-10-secrets-control-kill-switch)
- [Camera perception, hardware specification, and setup guide](#doc-11-camera-perception-hardware)
- [Private Owner Console, conversation, and client architecture](#doc-12-telegram-clients)
- [Self-modification, Git, and delivery architecture](#doc-13-self-modification-git-ci)
- [Deployment, networking, and infrastructure](#doc-14-deployment-networking-infrastructure)
- [Observability, reliability, and disaster recovery](#doc-15-observability-reliability-dr)
- [Privacy, retention, ownership, and cost](#doc-16-privacy-retention-export-cost)
- [Testing, evaluation, and simulation](#doc-17-testing-evaluation-simulation)
- [Repository architecture, language choices, documentation, and developer experience](#doc-18-repository-languages-docs-dx)
- [Onboarding, operations, and roadmap](#doc-19-onboarding-runbooks-roadmap)
- [Ranked risk register](#doc-20-risk-register)
- [Adversarial review, open questions, and rejected ideas](#doc-21-reviewers-open-questions-rejected)
- [Final synthesis and decisive recommendation](#doc-22-final-synthesis)
- [Architecture diagrams](#doc-diagrams)
- [Architecture Decision Records](#doc-adr-index)
- [ADR-001: Use an event-oriented provenance ledger, not pure event sourcing](#doc-adr-adr-001-event-oriented-provenance-ledger)
- [ADR-002: Use PostgreSQL as the V1 primary store and durable work queue](#doc-adr-adr-002-postgresql-primary-store-and-jobs)
- [ADR-003: Route models by adequacy, privacy, latency, and cost](#doc-adr-adr-003-policy-aware-model-routing)
- [ADR-004: Broker scoped credentials; use SOPS and OS key storage for bootstrap](#doc-adr-adr-004-scoped-credential-broker)
- [ADR-005: Use rootless containers and add stronger isolation only for hostile workloads](#doc-adr-adr-005-rootless-containers-and-tiered-sandbox)
- [ADR-006: Treat documentation as infrastructure using MkDocs, Mermaid, and ADRs](#doc-adr-adr-006-mkdocs-mermaid-adrs)
- [ADR-007: Bless a wired PoE ONVIF Profile T and RTSP camera](#doc-adr-adr-007-poe-onvif-rtsp-camera)
- [ADR-008: Separate an owner-controlled Guardian from the autonomous plane](#doc-adr-adr-008-independent-guardian)
- [ADR-009: Use Telegram long polling as an optional secondary owner channel](#doc-adr-adr-009-telegram-long-polling)
- [ADR-010: Keep durable logic independent of agent frameworks](#doc-adr-adr-010-framework-neutral-stable-primitives)
- [ADR-011: Start with one persistent Melli and ephemeral specialists](#doc-adr-adr-011-one-melli-temporary-specialists)
- [ADR-012: Use private networking and no public application ingress in V1](#doc-adr-adr-012-private-network-no-public-ingress)
- [ADR-013: Adopt Melloa naming and intellectual lineage](#doc-adr-adr-013-melloa-naming-and-intellectual-lineage)
- [ADR-014: Make the private Owner Console and canonical conversation mandatory in V1](#doc-adr-adr-014-private-owner-console-and-conversation)
- [Research method and limitations](#doc-research-method-and-limitations)
- [Primary-source register](#doc-research-primary-sources)

---

<a id="doc-index"></a>

---
hide:
  - toc
---

## Melloa

**A local-first home for one personal intelligence—built to keep identity, memory, evidence, policy, and owner control durable while models, providers, processes, and interfaces change.**

**Melloa** is the system. **Melli** is the persistent personal intelligence that lives through it. A model call is temporary; the owner's relationship, canonical conversation, memory, provenance, policies, and corrections are not.

[Start Melloa locally](getting-started.md){ .md-button .md-button--primary }
[See what works today](25-m1-implementation.md){ .md-button }

[![The Melloa Owner Console conversation view showing a canonical conversation and its route and provenance inspector](assets/current-mvp/conversation-desktop.png)](assets/current-mvp/conversation-desktop.png)

*The current private Owner Console: canonical conversation on the left, route, disclosure, provenance, cost, and policy evidence on the right. The pictured route is the clearly labelled no-network synthetic fallback.*

The fastest path is a private, no-network owner journey with explicit boundaries: signed Guardian status, process-local disposable state, and a fixed response labelled as a fixture rather than Melli. It reaches conversation, explanation, inspection, export, and clean shutdown without Docker, provider credentials, or personal data.

### What you can do now

- Take an authenticated no-network tour of the canonical conversation immediately, then talk to Melli after configuring an eligible model route; neither path is owned by a model provider or chat client.
- Inspect which model route ran, what memory evidence was selected, whether anything left the machine, and what it cost.
- Review, correct, dispute, retract, or content-delete memory while preserving provenance and deletion evidence.
- Inspect provider health, delivery attempts, retention coverage, operational status, and a content-free owner timeline.
- Download and validate a canonical owner-data export, with an optional encrypted package wrapper.
- Prove complete PostgreSQL owner-state recovery through an encrypted restic snapshot, clean database restore, and authenticated post-restore traversal.
- Keep the independent Guardian in signed `offline`, `read-only`, `no-actions`, `normal`, `stopped`, or `recovery` modes without giving Melloa its signing key or transition authority.

The local run needs the two public sibling repositories, Python, uv, Node.js, and Go. It needs no Docker daemon, model key, Telegram account, camera, or private deployment repository.

```bash
git clone https://github.com/melloa-project/melloa.git
git clone https://github.com/melloa-project/melloa-guardian.git
cd melloa
make preview
```

The command prints the Owner Console URL, disposable credential, first action, runtime contract, and cleanup behavior. Follow [Start Melloa locally](getting-started.md) for the complete owner walkthrough.

### How the pieces fit together

```mermaid
flowchart LR
    owner([Owner]) --> console[Private Owner Console]
    telegram[Telegram<br/>optional channel] -. private pairing .-> core[Melloa core]
    console --> core
    guardian[Independent Guardian] -. signed status only .-> core
    core --> state[(Conversation, memory,<br/>provenance and audit)]
    core --> policy[Deterministic policy<br/>and capability boundary]
    core --> routes{Model routes}
    routes --> local[Local model]
    routes --> external[Explicitly approved<br/>external route]
    policy --> effects[Bounded side effects]
```

The asymmetry is deliberate: Melloa may read the Guardian's signed projection, but it receives no Guardian private key, transition command, signing API, or host-control authority. Models produce candidate responses or plans; deterministic code owns authorization and exact side-effect boundaries.

### See the product

#### Inspect and correct memory

[![The Owner Console memory view showing an assertion, provenance, state history, and owner controls](assets/current-mvp/memory-desktop.png)](assets/current-mvp/memory-desktop.png)

Memory is owner-scoped and provenance-rich. The preview exposes values, sources, status history, corrections, contestation, retraction, and content-deletion evidence rather than presenting an opaque vector store as “memory.”

#### Understand operations and export limits

[![The Owner Console operations view showing export readiness, validation, encryption commands, and explicit limitations](assets/current-mvp/operations-export-desktop.png)](assets/current-mvp/operations-export-desktop.png)

Operational views show what is healthy, durable, exportable, encrypted, or still missing. Current export is a validated portability preview, while `make recovery` separately proves the complete PostgreSQL logical-backup and clean-restore mechanism. Neither claims that a particular installation has a recent offsite backup.

#### Follow a content-free evidence timeline

[![The Owner Console timeline showing conversation, processing, model, delivery, and export audit evidence](assets/current-mvp/timeline-desktop.png)](assets/current-mvp/timeline-desktop.png)

The timeline joins current-MVP conversation, processing, model, delivery, and owner-export evidence without copying message text, prompts, credentials, destinations, or raw audit payloads into the activity feed.

More desktop and mobile reference states are linked from [Expected visual states](run-current-mvp.md#expected-visual-states).

### Why build it this way

- **Persistence over provider lock-in:** Melli is not a model, prompt, process, or subscription. Durable identity and history stay in owner-controlled contracts.
- **Evidence over mystique:** important interpretations, memories, disclosures, decisions, actions, and corrections carry inspectable provenance.
- **Explicit authority over ambient agency:** models do not receive general tool, credential, policy, or Guardian authority.
- **Local-first, not local-only:** the default is private and no-network; an owner may configure bounded external routes with visible disclosure.
- **Honest operational boundaries:** restart durability, export validation, telemetry, backup, and production readiness are named separately.

### Learn at your own depth

1. **Use it:** [Start Melloa locally](getting-started.md).
2. **Understand the product:** [Executive vision](#doc-01-executive-vision), [design principles](#doc-02-design-principles-requirements), and [conceptual model](#doc-03-conceptual-model).
3. **Understand the boundaries:** [v0.2 decisions](#doc-23-v0-2-decisions), [chosen V1 architecture](#doc-05-chosen-v1-architecture), and [M1 threat review](26-m1-threat-review.md).
4. **See the system visually:** [Architecture diagram catalogue](#doc-diagrams).
5. **Inspect implementation evidence:** [M0](24-m0-implementation.md), [M1](25-m1-implementation.md), [observability and operational evidence](27-m1-observability-operational-evidence.md), and the [current validation report](https://github.com/melloa-project/melloa/blob/main/VALIDATION.md).
6. **Add integrations:** [Configure advanced local routes and durable state](run-current-mvp.md).
7. **Work on the project:** [Development and verification](development.md) and the [pre-release compatibility process](compatibility.md).

The deeper research remains available, but it is no longer the front door. Start with the product, then follow the layer of detail you need.

---

<a id="doc-23-v0-2-decisions"></a>

## v0.2 adopted decisions and precedence

### Purpose

Record the decisions made after the v0.1 research without rewriting its evidence base. This document, ADR-013, and ADR-014 are authoritative where an older passage conflicts with them.

### Naming and intellectual lineage

- **Meliorism** names the guiding philosophy: deliberate effort can improve the world and the owner's life.
- **Melloa** names the system, runtime, protocols, storage, policy framework, capabilities, deployment environment, and intended public project. Public source visibility does not make it open source until the owner adds explicit license terms.
- **Melli** names the primary persistent personal intelligence within a deployment. Its identity remains distinct from any process, model, provider, or chat session.
- **Guardian** remains the independent owner-controlled safety, restriction, shutdown, and recovery plane.
- **Otto** is reserved as an optional philosophical reference to the Extended Mind thought experiment. It does not create a V1 memory agent, service, role, or synthetic owner.

The project is intellectually aligned with meliorism, Licklider's human-computer symbiosis, Clark and Chalmers' extended-mind argument, and Engelbart's augmentation of human intellect. These references explain the project; they do not impose component names or architecture. [S64](#S64) [S65](#S65) [S66](#S66) [S67](#S67)

Display names are configuration and identity history, not database keys or type names. Domain code uses neutral identifiers such as `intelligence_id`, `conversation_id`, and `deployment_id`.

### Private Owner Console

The private Owner Console is a mandatory V1 component, not a deferred dashboard. It is a responsive web application available through the local LAN or private network, with application authentication in addition to network membership. It has no public internet ingress in V1.

It provides:

- direct first-party conversation with Melli;
- a chronological timeline of observations, interpretations, beliefs, corrections, actions, and outcomes;
- evidence and provenance inspection;
- memory search, correction, dispute, deletion, and retention controls;
- structured run and decision inspection, including inputs, evidence, model/prompt versions, uncertainty, plans, policy decisions, tool calls, action receipts, costs, external disclosures, and outcomes;
- camera-event and retained-media inspection;
- system, queue, provider, camera, storage, backup, and deployment health;
- policy, capability, approval, budget, quiet-hour, and notification controls;
- Guardian status and links to the separately authenticated Guardian control path.

The console does not require or expose private hidden chain-of-thought. It presents durable, structured decision records and evidence suitable for audit, replay, correction, and trust.

### Conversation architecture

Conversation is a canonical Melloa domain capability rather than a Telegram-specific feature. Threads, messages, attachments, participants, delivery attempts, corrections, memory citations, and action proposals receive Melloa-owned identifiers and provenance.

The Owner Console is the primary first-party client. Telegram long polling is an optional secondary adapter for remote convenience and proactive notifications. Disabling or replacing Telegram does not change Melli's identity, memory, or conversation history.

### Repository roles

- `melloa-project/melloa`: the main monorepo, including the architecture suite, core runtime, Owner Console, channel adapters, schemas, tests, documentation, and generic deployment templates.
- `melloa-project/melloa-guardian`: the independently controlled Guardian implementation, host controls, recovery logic, tests, and runbooks. It must not depend on model reasoning.
- `melloa-project/melloa-deployment`: the owner's private deployment inventory and encrypted configuration overlays. It contains no plaintext secrets and is never required to build or test the public project.

### Immediate implementation consequence

Implementation begins from the main `melloa` repository. The first milestone establishes reproducible development, canonical conversation, the private Owner Console shell, provenance/audit contracts, policy boundaries, fake adapters, and the Guardian protocol. Real credentials, personal data, Telegram, and camera hardware remain optional until their documented integration milestone.

---

<a id="doc-00-traceability"></a>

## Requirement traceability

### Purpose

This matrix maps the requested specification suite to concrete documents. Several topics are intentionally combined where splitting them would create navigation overhead without a separate decision boundary.

| Requested output | Primary document(s) |
|---|---|
| Executive Vision | [01](#doc-01-executive-vision) |
| Design Principles | [02](#doc-02-design-principles-requirements) |
| Requirements and Non-Requirements | [02](#doc-02-design-principles-requirements) |
| Architecture Overview | [05](#doc-05-chosen-v1-architecture), [diagrams](#doc-diagrams) |
| Alternative Architectures | [04](#doc-04-alternative-architectures) |
| Chosen Architecture and Rationale | [05](#doc-05-chosen-v1-architecture) |
| Sensor and Perception Architecture | [11](#doc-11-camera-perception-hardware) |
| Agent and Reasoning Architecture | [07](#doc-07-agents-models-goals) |
| Model Routing Architecture | [07](#doc-07-agents-models-goals) |
| Event System Specification | [06](#doc-06-events-memory-data) |
| Memory Architecture | [06](#doc-06-events-memory-data) |
| Goal and Policy Model | [07](#doc-07-agents-models-goals), [08](#doc-08-capabilities-policy-autonomy) |
| Capability / Plugin System | [08](#doc-08-capabilities-policy-autonomy) |
| Autonomy Model | [08](#doc-08-capabilities-policy-autonomy) |
| Security Architecture | [09](#doc-09-security-threat-injection), [10](#doc-10-secrets-control-kill-switch) |
| Threat Model | [09](#doc-09-security-threat-injection), [20](#doc-20-risk-register) |
| Prompt-Injection Defense | [09](#doc-09-security-threat-injection) |
| Credential and Secret Management | [10](#doc-10-secrets-control-kill-switch) |
| Control Plane / Kill Switch | [10](#doc-10-secrets-control-kill-switch) |
| Self-Modification Architecture | [13](#doc-13-self-modification-git-ci) |
| Deployment Architecture | [14](#doc-14-deployment-networking-infrastructure) |
| Local Infrastructure | [14](#doc-14-deployment-networking-infrastructure) |
| Cloud Infrastructure | [14](#doc-14-deployment-networking-infrastructure) |
| Networking | [14](#doc-14-deployment-networking-infrastructure) |
| Hardware Specification | [11](#doc-11-camera-perception-hardware) |
| Camera Setup Guide | [11](#doc-11-camera-perception-hardware) |
| Owner Console, Conversation, and Telegram Clients | [12](#doc-12-telegram-clients), [23](#doc-23-v0-2-decisions) |
| Observability | [15](#doc-15-observability-reliability-dr) |
| Reliability and Failure Recovery | [15](#doc-15-observability-reliability-dr) |
| Backup and Disaster Recovery | [15](#doc-15-observability-reliability-dr) |
| Data Privacy and Retention | [16](#doc-16-privacy-retention-export-cost) |
| Cost Model | [16](#doc-16-privacy-retention-export-cost) |
| Repository Architecture | [18](#doc-18-repository-languages-docs-dx) |
| Language and Technology Choices | [18](#doc-18-repository-languages-docs-dx) |
| Testing and Evaluation | [17](#doc-17-testing-evaluation-simulation) |
| Documentation Architecture | [18](#doc-18-repository-languages-docs-dx) |
| Developer Experience | [18](#doc-18-repository-languages-docs-dx) |
| Onboarding Guide | [19](#doc-19-onboarding-runbooks-roadmap) |
| Operations / Runbooks | [19](#doc-19-onboarding-runbooks-roadmap) |
| Roadmap | [19](#doc-19-onboarding-runbooks-roadmap), [22](#doc-22-final-synthesis) |
| Architectural Decision Records | [ADR directory](#doc-adr-index) |
| Open Questions | [21](#doc-21-reviewers-open-questions-rejected) |
| Rejected Ideas | [21](#doc-21-reviewers-open-questions-rejected) |
| Risk Register | [20](#doc-20-risk-register) |
| Mandatory diagrams | [Diagram catalogue](#doc-diagrams) |
| Naming and intellectual lineage | [03](#doc-03-conceptual-model), [23](#doc-23-v0-2-decisions), [ADR-013](#doc-adr-adr-013-melloa-naming-and-intellectual-lineage) |
| Final ten questions, V1, milestones | [22](#doc-22-final-synthesis) |
| v0.2 adopted decisions | [23](#doc-23-v0-2-decisions), [ADR-014](#doc-adr-adr-014-private-owner-console-and-conversation) |

### Cross-cutting document pattern

Each design document distinguishes:

- **Build now:** necessary for a useful, safe V1.
- **Design for:** boundary or contract that should exist now because later migration would be expensive.
- **Defer:** an explicit choice not to implement yet.

Trade-offs, failure modes, security, operations, cost, and future evolution are included where they materially differ. The suite does not copy the same template mechanically into every page; it preserves the decision logic instead.

---

<a id="doc-01-executive-vision"></a>

## Executive vision

### Purpose

Define what Melloa is optimizing for, what Melli is, and how success should be judged over a seven-year horizon.

### Vision

**Melloa** is the owner-controlled infrastructure, runtime, protocols, memory architecture, capability framework, governance system, and deployment environment for persistent personal intelligences.

**Melli** is the primary persistent personal intelligence instantiated in one Melloa deployment. Melli is not a process, model, chat session, prompt, container, client, or provider account. Its continuity is represented by durable identity records, relationships, goals, memories, commitments, correction history, conversations, and responsibility for prior actions. Models are replaceable cognitive engines used by Melli.

**Meliorism** is the guiding philosophy rather than a runtime component: deliberate human effort, supported by machine intelligence, can make circumstances better. Melloa also draws intellectual lineage from human-computer symbiosis, extended cognition, and augmentation of human intellect. **Otto** remains a reserved allusion, not a forced V1 agent or service. [S64](#S64) [S65](#S65) [S66](#S66) [S67](#S67)

The enduring product is not reducible to a dashboard or collection of integrations. It is a governed learning loop between a person and a system that can observe, reason, act, measure, and evolve without losing provenance or owner control. The private Owner Console is nevertheless a required V1 surface because that loop must remain visible, conversational, correctable, and operable by its owner.

```text
Owner chooses values, objectives, and governing constraints
                          ↓
Melloa observes selected parts of life and systems
                          ↓
Melli forms uncertainty-aware interpretations and plans
                          ↓
Policy and capability boundaries constrain executable action
                          ↓
Melloa acts, communicates, or builds a reversible artifact
                          ↓
Consequences are observed and evaluated
                          ↓
Memory, strategy, thresholds, software, or infrastructure may change
                          ↺
```

### Success criteria

A seven-year-successful installation should exhibit all of these properties:

1. **Compounding context without compounding confusion.** It retains useful history, but every important belief can be traced to observations, inferences, confirmations, corrections, and schema/model versions.
2. **Agency without ambient privilege.** Melli can act substantially inside agreed boundaries, while dangerous actions are structurally unavailable or require exact, auditable approval.
3. **Interventions that earn their continuation.** Reminders, workflows, software, and routines are measured and retired when they do not help.
4. **Continuity across technology churn.** Changing foundation models, agent SDKs, devices, or interfaces does not erase identity, memory, policy, or ownership.
5. **Reversible evolution.** Software and configuration changes are versioned, tested, canaried, observed, and rolled back.
6. **Understandability by one engineer.** The system remains operable without a permanent platform team.
7. **Data ownership.** The owner can export, restore, correct, and delete their history using documented formats.
8. **Honest uncertainty.** Camera events and model conclusions are represented as probabilistic claims, not ground truth.
9. **External stoppability.** The autonomous plane cannot rewrite or disable its ultimate shutdown path.
10. **Bounded cost and attention.** Monetary spend, compute, storage, and interruptions all have budgets and circuit breakers.

### Product thesis challenged

#### Assumption: more personal data automatically creates more value

**Problem:** Rich data can improve context, but uncurated accumulation creates false memories, surveillance burden, attack surface, and retrieval noise. A camera that produces millions of weak detections is not “memory.”

**Recommendation:** collect only for declared purposes, process cheaply and locally first, preserve provenance, expire raw media aggressively, and periodically evaluate whether each sensor improves a goal.

#### Assumption: autonomy should increase monotonically

**Problem:** Trust is task- and context-specific. A system may be excellent at scheduling internal analyses and poor at sending external messages. New models can regress. A global “autonomy level” is misleading.

**Recommendation:** grant autonomy per capability, action class, resource, purpose, sensitivity, budget, and reversibility. Allow grants to expire or contract.

#### Assumption: multiple persistent agents are inherently more capable

**Problem:** Permanent agents introduce identity, memory, authority, coordination, and accountability complexity. Many apparent roles are better represented by temporary workers sharing Melli's task context but not its identity.

**Recommendation:** begin with one persistent Melli and ephemeral specialist workers. Add another persistent intelligence only when it needs a genuinely distinct relationship, long-term memory, goals, permissions, and accountability boundary.

#### Assumption: self-modification is mainly a coding problem

**Problem:** Generating code is increasingly commoditized. The hard parts are deciding what should change, proving policy compliance, evaluating outcomes, managing migrations, limiting credentials, and recovering from bad deployments.

**Recommendation:** treat self-modification as a governed software-delivery subsystem, not as shell access for a coding model.

### Build now / design for / defer

#### Build now

- Durable distinctions between Meliorism, Melloa, Melli, client/channel, worker, model, capability, and process.
- A complete observation-to-outcome audit path.
- Owner-defined goals and policy boundaries.
- A channel-independent conversation model, mandatory private Owner Console, optional Telegram remote adapter, and one perception channel.
- An external Guardian and tested recovery path.

#### Design for

- Multiple persistent intelligences without requiring them.
- Provider and model replacement.
- Capability modules on separate hosts.
- Replay, migration, and data export across years.
- Safe generated-software workflows.

#### Defer

- Human-like consciousness claims or simulated emotional dependency.
- A marketplace, multi-tenant SaaS, or non-technical onboarding.
- A permanent multi-agent organization.
- Voice and microphone monitoring.
- Broad financial or social authority.

### Decision

Optimize Melloa for **high-value closed loops**, not the number of integrations, autonomous steps, remembered facts, or model tokens consumed. Personal success is primary; open-source engineering quality is the mechanism that makes that success maintainable.

---

<a id="doc-02-design-principles-requirements"></a>

## Design principles, requirements, and non-requirements

### Design principles

#### 1. Identity is durable; cognition is replaceable

Melli persists through durable state and accountability. A model call is an implementation detail. No table or API should use `agent_id` to mean model name, process ID, or API key.

#### 2. Observation is not interpretation

Raw sensor output, a detector label, a multimodal model statement, a current belief, and a user-confirmed fact are separate records connected by provenance.

#### 3. Models propose; deterministic systems authorize

An LLM may recommend an action. It cannot grant itself permission, mint a credential, broaden network access, or redefine the policy used to judge its proposal. Prompt text is not a security boundary; OWASP explicitly treats direct and indirect prompt injection as persistent risks that RAG and fine-tuning do not eliminate. [S14](#S14)

#### 4. Autonomy is scoped, not global

Authorization depends on principal, action, resource, purpose, data class, risk, reversibility, time, rate, and budget. “Autonomous mode” is not a sufficient policy.

#### 5. Prefer the cheapest adequate intelligence

Tier 0 rules and CV should discard uninteresting data. Local models should handle sensitive or routine work when adequate. Frontier models should be used where quality materially changes the outcome. Route by evidence, not ideology.

#### 6. Durable facts, rebuildable indexes

The canonical record is relational and append-only where provenance matters. Embeddings, summaries, caches, and search indexes are derived and can be regenerated.

#### 7. Reversible by default

Configuration changes, interventions, deployments, and memory corrections should have clear rollback or supersession semantics. Irreversible actions require stronger evidence and authority.

#### 8. Private first-party access without public ingress

The blessed V1 provides the Owner Console over the private network or local LAN and may use Telegram long polling as a secondary transport. It does not require a public domain, public reverse proxy, or inbound webhook.

#### 9. External shutdown beats cooperative shutdown

The owner-controlled Guardian must be able to stop or isolate autonomous workloads using credentials and control paths those workloads do not possess.

#### 10. Documentation and replay are infrastructure

ADRs, schemas, runbooks, prompt/model versions, and event replays are required for safe evolution, not polish added after implementation.

#### 11. One excellent deployment path

Support one opinionated Linux + Compose path first. Clean contracts enable alternatives later; configuration sprawl does not.

#### 12. Complexity requires a measured trigger

Every new service, database, language, broker, agent identity, or cloud dependency needs a threshold and an owner. “May be useful someday” is insufficient.

#### 13. The owner can inspect and correct the system

The owner must be able to converse with Melli and inspect the evidence, uncertainty, policy, tools, actions, costs, disclosures, media, and outcomes behind system behavior. Inspection uses durable structured records rather than hidden chain-of-thought.

### Functional requirements

#### R-F01 — Persistent intelligence continuity

Melli SHALL retain an owner-inspectable identity, relationships, goals, memories, correction history, and action history independent of any specific model or provider.

#### R-F02 — Event and provenance ledger

Melloa SHALL persist canonical events with immutable IDs, timestamps, source, schema version, sensitivity, trust/taint metadata, evidence links, and causal/correlation links where known.

#### R-F03 — Uncertainty-aware perception

Every semantic sensor conclusion SHALL include confidence and evidence. Low-confidence claims SHALL remain hypotheses or trigger clarification rather than silently becoming facts.

#### R-F04 — Policy-mediated actions

Every side-effecting action SHALL be authorized by a deterministic broker before execution. Authorization SHALL return `deny`, `allow`, or `require_approval`, plus constraints and obligations.

#### R-F05 — Exact-action approvals

An approval SHALL bind to a canonicalized action hash, resource, constraints, expiry, and approving identity. Material changes invalidate it.

#### R-F06 — Capability introspection

Melloa SHALL know installed capabilities, their health, permissions, data classes, side effects, cost characteristics, and versions.

#### R-F07 — Model routing

The runtime SHALL route by task quality, modality, latency, privacy, retention policy, context length, reliability, and cost. The route and reason SHALL be logged.

#### R-F08 — Progressive memory

Melloa SHALL support raw observations, interpretations, beliefs, confirmed facts, episodes, semantic assertions, goals, policies, interventions, outcomes, and software/deployment history without collapsing them into one vector store.

#### R-F09 — Corrections

The owner SHALL be able to correct or dispute beliefs. Corrections SHALL append provenance and update projections without erasing historical evidence.

#### R-F10 — Proactive interaction budget

Proactive communication SHALL respect quiet hours, urgency, confidence, interruption budgets, cooldowns, and channel sensitivity.

#### R-F11 — Replay and evaluation

Historical events SHALL be replayable through candidate prompts, models, policies, and consumers without re-triggering real-world side effects.

#### R-F12 — Governed software creation

Generated software SHALL be developed in isolation, tested, scanned, evaluated, reviewed according to risk, deployed gradually, observed, and rolled back when needed.

#### R-F13 — Owner-only emergency control

The owner SHALL be able to change Guardian mode to at least `normal`, `no-actions`, `read-only`, `offline`, `stopped`, and `recovery` independently of Melli.

#### R-F14 — Export and deletion

The owner SHALL be able to export canonical data, schemas, blobs, policies, and memories in documented formats and delete selected data with an auditable tombstone process.

#### R-F15 — Cost and rate controls

Every external provider and capability SHALL support daily/monthly cost ceilings, request limits, loop detection, and emergency disablement.

#### R-F16 — Private Owner Console

Melloa SHALL provide a private, authenticated web console for first-party conversation, timeline and provenance inspection, memory correction, media review, decision/run inspection, capability and policy visibility, cost/disclosure reporting, and operational health. The console SHALL require no public internet ingress.

#### R-F17 — Channel-independent conversation

Melloa SHALL persist canonical threads, messages, attachments, participants, citations, corrections, action proposals, and delivery attempts independently of any client or transport. The Owner Console SHALL be the primary client; Telegram MAY be enabled as a replaceable secondary adapter.

### Non-functional requirements

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

### Explicit non-goals for early versions

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

### Quantitative planning assumptions

These are sizing assumptions, not commitments:

- 50–500 canonical events/day after local aggregation.
- 5–50 semantic model escalations/day for the initial room-camera use case.
- 100–1,000 owner messages/month in early use.
- 10–50 GB/month of selectively retained visual media, rather than 0.6–1.3 TB/month of continuous 2–4 Mbps video.
- 15–30 W average core-host draw, approximately £2.82–£5.64/month at 26.11 p/kWh, excluding camera/network gear. [S45](#S45)
- £15–£70/month operating cost for a disciplined MVP, with model usage as the dominant variable.

### Failure principle

Melloa should **fail closed on authority** and **fail useful on intelligence**. When a model provider is down, it may postpone rich analysis while still recording events. When the policy engine is unavailable, side-effecting actions stop rather than bypassing authorization.

---

<a id="doc-03-conceptual-model"></a>

## Conceptual model and naming

### Purpose

Remove ambiguity from terms that otherwise become architectural coupling. The model intentionally separates durable entities from transient computation.

### Core entities

| Term | Precise meaning | Not equivalent to |
|---|---|---|
| **Meliorism** | The guiding philosophy that deliberate human effort and intelligent collaboration can improve circumstances | A service, agent, deployment, or optimization metric |
| **Melloa** | The deployable system and public project: runtime, protocols, storage, policies, capabilities, control boundaries, clients, operations, and documentation | Melli, a model, a daemon, or a chat app |
| **Melli** | The primary persistent personal intelligence, represented by identity, memory, relationships, goals, commitments, conversations, and action history | A single prompt, process, provider, client, or worker |
| **Otto** | A reserved philosophical allusion to the Extended Mind thought experiment, available for a future identity or example when justified | A mandatory V1 memory service, synthetic owner, or predefined agent role |
| **Owner Console** | The private first-party web client for conversation, inspection, correction, and operation | The Guardian, public administration ingress, or the intelligence itself |
| **Conversation** | A canonical thread of messages, attachments, citations, corrections, proposals, and delivery attempts owned by Melloa | A Telegram chat or one model context window |
| **Persistent intelligence** | A durable identity with continuing memory, goals/relationships, permissions, and accountability | Any autonomous task runner |
| **Worker** | A temporary process or model-mediated task executor with a bounded task, context, budget, and capability lease | A durable identity |
| **Model** | A versioned inference engine with modality, quality, cost, latency, context, and provider properties | Agent or intelligence |
| **Provider** | A service or local runtime that executes models | Model identity |
| **Capability** | A typed, versioned interface through which a principal can read data or cause effects | Permission to use it |
| **Permission grant** | A revocable authorization scope allowing a principal to request certain capability operations | A policy decision for every context |
| **Policy** | Deterministic rules that constrain decisions based on principal, action, resource, purpose, context, risk, and budget | A goal or prompt |
| **Approval** | A time-bounded owner decision for a canonical exact action or tightly bounded class | Permanent capability permission |
| **Goal** | A desired state owned or accepted by the human, with constraints and review cadence | A metric to maximize blindly |
| **Strategy** | A theory for advancing a goal | A single action |
| **Experiment** | A bounded test of a hypothesis with outcomes and stopping conditions | Any automation |
| **Intervention** | A deliberate action intended to influence an outcome | A notification with no hypothesis |
| **Action** | A proposed or executed side effect through a capability | A model-generated sentence |
| **Artifact** | A versioned output such as code, dashboard, report, model, or configuration | A deployment |
| **Deployment** | A specific artifact version activated in an environment under a policy and rollout record | Source code in Git |

### Epistemic entities

#### Observation

A minimally interpreted datum captured from a source: a frame hash, conversation message, motion interval, API response, or health sample. It carries source, time, integrity, sensitivity, and retention metadata.

#### Interpretation

A versioned claim produced from one or more observations, such as “a person probably entered.” It identifies the detector/model/prompt, confidence, alternatives, and evidence.

#### Belief

Melli's current synthesized view, such as “the owner is likely in the room.” It may combine interpretations and prior state. It is temporal and revisable.

#### User-confirmed fact

A statement explicitly confirmed by the owner for a defined scope and time. Confirmation increases authority but does not make it eternally true.

#### Memory

A durable record selected for future use. A memory is not merely an embedding. It has type, provenance, validity interval, confidence, sensitivity, correction status, and retrieval policy.

#### Event

A canonical, immutable record that something was observed, inferred, decided, executed, corrected, or evaluated. Events connect activity over time but do not require the whole application to be purely event-sourced.

The core invariant is:

```text
Observation ≠ Interpretation ≠ Belief ≠ User-confirmed fact
```

### Identity continuity

Melli's continuity record should contain:

- stable intelligence ID and owner relationship;
- current chosen name and naming history;
- declared role and responsibility boundaries;
- memory namespaces and access policy;
- goals and commitments accepted over time;
- important interaction and correction history;
- action/deployment responsibility records;
- current model-routing policy, without treating it as identity;
- explicit forks, mergers, or retirement events if identity changes later.

Changing from one foundation model to another creates a new **cognitive runtime version**, not a new Melli. Running two workers concurrently creates two task executions, not two identities. A second persistent identity should have its own durable ID, goals, relationship contract, memory access, and permissions.

### Multi-agent decision rule

Create another persistent intelligence only when at least three of these are true:

1. It needs a distinct long-term relationship with the owner.
2. It needs memory that should not be automatically shared with Melli.
3. It has goals that can conflict with Melli's goals and must be represented explicitly.
4. It requires a materially different permission set.
5. It must be independently accountable for decisions over time.
6. Its identity must continue across many tasks and model changes.

Otherwise use an ephemeral specialist worker.

### Naming and intellectual lineage

#### Adopted vocabulary

- **Meliorism** is the philosophy and purpose.
- **Melloa** is the system, intended public project, and public technical name. Its source is currently readable, but it is not open source until explicit license terms are added.
- **Melli** is the primary persistent intelligence in the owner's deployment.
- **Guardian** is the independent owner-controlled control plane.
- **Otto** is reserved as a subtle Extended Mind reference and is not assigned to a V1 subsystem.

The names remain architecturally separate. Code and schemas use neutral domain identifiers rather than display names. A persistent intelligence may change its chosen display name while retaining a stable identity and history.

The project's intellectual family tree is explanatory, not prescriptive: meliorism supplies the purpose, Licklider's symbiosis supplies the partnership model, Clark and Chalmers supply the extended-cognition lens, and Engelbart supplies the augmentation and bootstrapping tradition. [S64](#S64) [S65](#S65) [S66](#S66) [S67](#S67)

#### Public-name gate

The names are adopted for implementation and repository organization. Before a broad public launch, perform refreshed registry, domain, company-name, search-confusion, and trademark review. That gate may qualify presentation or branding, but implementation must not hard-code display names into durable identifiers or contracts.

### Build now / design for / defer

#### Build now

- Distinct IDs for system deployment, persistent intelligence, owner, worker execution, model, capability, action, and event.
- The epistemic distinctions above in schema and UI.
- A naming-history field rather than using display name as a primary key.

#### Design for

- Multiple persistent identities and private memory partitions.
- Identity export, fork, merge, and retirement semantics.
- User-inspectable explanation of which identity acted and under whose authority.

#### Defer

- Autonomous renaming without an owner-visible change record.
- Legal conclusions based only on search results.
- Agent-to-agent social protocols until a real use case needs persistent identities.

---

<a id="doc-04-alternative-architectures"></a>

## Alternative architectures

### Evaluation criteria

Each alternative is plausible for a technically sophisticated single owner. They are scored against simplicity, maintainability, security boundaries, observability, autonomy, cost, self-modification, and migration options.

### A — Single local daemon with SQLite

#### Shape

One Python process owns Telegram, camera ingestion, scheduling, reasoning, memory, and actions. SQLite WAL stores state and an append-only event table. Files are stored locally. A systemd service starts and stops the daemon.

#### Strengths

- Minimal operational surface and fastest route to a prototype.
- Easy backup and inspection.
- Excellent for validating conversation, schema, and camera event volume.
- No networked database or message broker.

#### Weaknesses

- One process failure affects all functions.
- Generated-code execution, policy enforcement, and perception compete for the same trust boundary.
- Long-running tasks and concurrent camera/event workloads can create awkward locking and lifecycle behavior.
- It encourages direct library calls and hidden coupling.
- Migrating identity, policy, and event consumers out of the daemon later may be more work than starting with explicit internal modules and a networked database.

#### Best use

A throwaway two-week research spike, or a minimal edition that explicitly never enables self-modification.

### B — Modular monolith with PostgreSQL ledger and external Guardian

#### Shape

A small set of rootless containers on one Linux host:

- Melloa core API and scheduler;
- event/job workers from the same codebase;
- PostgreSQL with `pgvector`;
- camera adapter/Frigate;
- optional local model runtime;
- OpenTelemetry collector or direct local telemetry sink.

Modules communicate through typed in-process interfaces and durable database records. PostgreSQL outbox/jobs provide asynchronous work. A host-level Guardian, controlled by separate credentials, can stop workloads and remove egress.

#### Strengths

- One primary codebase and database keep operations understandable.
- PostgreSQL supports transactions, JSON, temporal queries, full-text search, row-level controls, and vector indexes without a database zoo. [S04](#S04) [S05](#S05)
- The outbox pattern avoids a database-plus-broker dual-write problem; consumers are designed for duplicate delivery and idempotency. [S06](#S06)
- Explicit module contracts and event schemas preserve a path to process separation.
- The Guardian creates a real authority boundary without forcing a distributed platform.
- Self-modification can be introduced as a separate sandbox worker rather than granting the core host authority.

#### Weaknesses

- PostgreSQL becomes a critical dependency and requires real backup/restore discipline.
- A modular monolith can decay into “everything imports everything” without dependency rules.
- Database-backed jobs are less elegant than a durable workflow engine for complex months-long workflows.
- One host remains a single failure domain.

#### Best use

The recommended V1 and likely multi-year foundation for one owner.

### C — Distributed capability-oriented control plane

#### Shape

Independent sensor, memory, policy, planner, action, and deployment services communicate over NATS JetStream or Kafka. Durable workflows run in Temporal/Restate. Every workload has SPIFFE identity and obtains dynamic secrets from OpenBao. Kubernetes schedules containers and microVM sandboxes across home and cloud nodes.

#### Strengths

- Strong process and network isolation.
- Natural independent scaling and failure containment.
- Durable workflow engines are excellent for retries, timers, human approvals, and long-running state. [S09](#S09)
- NATS JetStream provides persistence and replay when multiple independent nodes need a real event fabric. [S08](#S08)
- Workload identity and dynamic secrets can become robust at larger scale.

#### Weaknesses

- Far too many operational concepts for one owner and one camera.
- Policy, certificate, queue, workflow, schema, deployment, and observability failures multiply.
- Local debugging and clean-machine restoration become harder.
- Autonomous changes have a much larger blast radius.
- It risks building an infrastructure platform before demonstrating one beneficial personal loop.

#### Best use

A later architecture after multiple hosts, independent capabilities, offline edge nodes, and high-volume durable workflows create measured pressure.

### Comparative score

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

### Decision

Choose **B**. It retains almost all important long-term boundaries without enterprise-platform overhead.

### Migration triggers, not aspirations

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

### Rejected hybrid

A tempting hybrid is SQLite for core state plus NATS for events. It combines two sources of durability and recreates the transactional dual-write problem without delivering meaningful scale. PostgreSQL alone is simpler and safer for V1.

---

<a id="doc-05-chosen-v1-architecture"></a>

## Chosen V1 architecture

### Purpose

Specify the concrete architecture that should be implemented first while preserving the boundaries most expensive to retrofit later.

### Architectural style

Melloa V1 is a **local-first modular monolith with durable events, ordinary relational projections, and an externally controlled authority boundary**.

“Event-oriented” does not mean every object is reconstructed by replaying all events. The system uses:

- append-only records for observations, interpretations, decisions, actions, corrections, and audits;
- current-state relational projections for efficient operation;
- a transactional outbox/job table for asynchronous work;
- content-addressed blobs for frames, clips, artifacts, and exports;
- derived full-text/vector indexes that can be rebuilt.

### Concrete component set

#### Core host

- Wired x86-64 mini-PC, 16–32 GB RAM, 1 TB NVMe.
- Debian or Ubuntu LTS.
- Rootless Docker Engine and Docker Compose.
- Host firewall, encrypted disk, automatic security updates with controlled reboot windows.
- Tailscale for owner-only remote access; no public application ingress.

#### Containers

1. **`melloa-core`** — FastAPI-based owner API, canonical conversation service, model gateway, memory retrieval, policy/capability endpoints, and channel abstraction.
2. **`melloa-web`** — Private Owner Console for conversation, provenance, memory correction, run/decision inspection, media, health, cost, disclosure, approval, and deployment views.
3. **`melloa-worker`** — Same Python codebase, separate process roles for event interpretation, scheduled reflection, indexing, retention, and evaluations.
4. **`postgres`** — PostgreSQL 18 with `pgvector`; separate roles for core, read-only analytics, and migrations.
5. **`perception`** — Frigate/go2rtc or a thin adapter around RTSP/FFmpeg and local detectors. It emits candidate evidence, not authoritative Melloa facts.
6. **`otel-collector`** — Optional but recommended local collector; can initially export to local files or a small local stack.
7. **`local-model`** — Optional llama.cpp/MLX/vLLM-compatible endpoint, enabled only when hardware and workloads justify it.

#### Host-owned Guardian

A root-owned systemd unit and owner CLI outside the autonomous container trust domain. It controls:

- start/stop and mode files consumed read-only by Melloa;
- host firewall/egress rules;
- revocation or removal of provider and capability credentials;
- database read-only/recovery procedure;
- emergency export and diagnostics;
- signed deployment of Guardian changes.

The Guardian does not need AI. Its value is simple, independent authority.

### Internal modules and dependency direction

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

### Durable work model

A transaction may update current state and append an event/outbox row atomically. Workers claim jobs with `FOR UPDATE SKIP LOCKED`, maintain leases, retry with backoff, and record deduplication keys. PostgreSQL `LISTEN/NOTIFY` may wake workers, but polling the durable table remains the source of truth because notifications are not a queue. [S06](#S06) [S07](#S07)

Delivery semantics are **at least once**. Consumers must be idempotent. “Exactly once” is not claimed across arbitrary side effects.

### V1 data stores

| Data | Store | Rationale |
|---|---|---|
| Events, provenance, policies, goals, jobs, audit | PostgreSQL | Transactions, queryability, migrations, one operational database |
| Embeddings | `pgvector` columns/tables | Co-located, rebuildable semantic index [S05](#S05) |
| Frames/clips/artifacts | Content-addressed filesystem | Simple local ownership and deduplication; database stores hashes/metadata |
| Configuration | Versioned YAML/TOML plus DB overrides | Reviewable defaults and dynamic owner settings |
| Bootstrap secrets | SOPS + age and OS keyring | No plaintext Git secrets; small V1 footprint [S20](#S20) |
| Backups | `restic` repositories on local USB and B2 | Encryption, deduplication, verification, multiple backends [S42](#S42) |

### Policy and action path

1. A model or deterministic rule emits an **action proposal**.
2. The proposal is canonicalized and risk-classified.
3. The capability broker builds an authorization request.
4. Deterministic policy evaluates prohibitions, grants, constraints, budgets, and approval requirements.
5. If approval is needed, the exact action hash is presented to the owner.
6. The broker obtains or exercises a scoped credential.
7. The capability adapter executes and returns a schema-validated result.
8. The action, authorization, credential lease reference, result, cost, and observable outcome are appended.

The model never receives a general secret bundle.

### Model path

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

### V1 deployment topology

See [Diagram 9](#9-v1-deployment-architecture) and [Diagram 17](#17-network-topology). The camera network cannot reach the internet. Only the perception adapter can pull its RTSP stream. The core can reach explicit provider/API endpoints through auditable egress rules. Generated-code sandboxes have no egress unless a temporary allowlist is attached.

### Build now

- PostgreSQL schema, migration discipline, event envelope, jobs/outbox, and idempotency.
- Owner/Melli identity records, canonical conversation, and epistemic memory distinctions.
- Private Owner Console with authenticated conversation, timeline, provenance, structured run inspection, health, and correction flows.
- Optional Telegram long-polling adapter with an owner ID allowlist.
- Capability broker with a small typed policy implementation.
- Model gateway with at least one hosted provider and deterministic fake provider for tests.
- Guardian modes and credential revocation.
- Structured audit and cost records.
- Encrypted backup and clean-machine restore.

### Design for

- Moving a module behind HTTP/gRPC without changing domain contracts.
- NATS or a durable workflow engine behind event/workflow ports.
- Edge nodes with signed capability identities.
- Generated-code sandbox and GitOps flow.
- Multiple persistent intelligences with separate policy/memory scopes.
- Native mobile and additional messaging clients behind the conversation/client abstraction.

### Defer

- Kubernetes, service mesh, SPIFFE, OpenBao, Kafka, NATS, and Temporal.
- A dedicated graph or vector database.
- Public web endpoints.
- A GPU purchase before profiling.
- Automatic infrastructure/IAM changes.
- Multi-camera continuous recording.

### Operational implications

One host is a deliberate single failure domain. V1 prioritizes restore and graceful degradation over high availability. The architecture should be re-evaluated when Melloa becomes safety-critical, supports more than one owner, spans multiple physical sites, or accumulates independent always-on capabilities.

### Cost implications

The core stack has no mandatory SaaS platform cost beyond model APIs, optional Tailscale plan, and offsite storage. The expensive variables are model calls, retained media, and local GPU hardware—not PostgreSQL or Compose.

### Principal failure modes

- **PostgreSQL unavailable:** ingestion buffers bounded local evidence; actions stop; Guardian exposes recovery mode.
- **Internet/provider outage:** local event capture continues; rich interpretation is deferred.
- **Policy engine error:** side effects fail closed.
- **Camera flood:** local aggregation and queue quotas discard/reduce low-value candidates before canonical event creation.
- **Model loop:** per-run step, token, time, and cost ceilings terminate execution.
- **Bad migration:** preflight backup, migration transaction where possible, staging replay, and rollback runbook.
- **Compromised autonomous container:** no Guardian credentials, no host Docker socket, constrained database role, and revocable egress reduce blast radius.

---

<a id="doc-06-events-memory-data"></a>

## Event system, memory architecture, and data lifecycle

### Purpose

Define how Melloa represents years of observations and decisions without confusing raw evidence, model interpretations, current beliefs, and owner-confirmed facts. The design must support correction, replay, schema evolution, deletion, and reconstruction of why Melli believed or did something.

### Decision

Use PostgreSQL as a canonical **provenance ledger plus current-state store**. Do not implement textbook pure event sourcing for every aggregate. Append immutable events where history matters, and maintain ordinary relational projections for current state and efficient queries.

Embeddings, summaries, clusters, and knowledge-graph edges are derived views. They may be deleted and rebuilt. They are never the only copy of a durable fact.

### Canonical event envelope

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

#### Envelope rules

- `event_id` is immutable and globally unique within an installation.
- `occurred_at` describes the domain time; `recorded_at` describes ingestion time. Both are retained.
- Event type includes a major schema line; the full semantic version is explicit.
- Producer metadata records the component, model, prompt, and relevant configuration version.
- Confidence is calibrated per event family where possible; it is not comparable across arbitrary models without calibration metadata.
- Sensitivity and trust/taint labels travel with the event and constrain routing and retrieval.
- Evidence is addressed by cryptographic hash and may expire independently of the event.
- Corrections append new events and update projections; they do not mutate the old event.
- Correlation does not imply causation. `causation_id` is used only for known processing lineage, not causal inference about human behavior.

### Event families

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

### PostgreSQL logical schema

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

Use PostgreSQL roles and grants first. Row-level security may later partition memory/capability scopes, but it must be tested carefully and must not be the only barrier protecting highly privileged administration paths. PostgreSQL's row security defaults to deny when enabled without a policy, while owners and bypass roles require special attention. [S04](#S04)

### Memory layers

#### Layer 0 — transient working context

A bounded, per-run context assembled for one task. It is not automatically retained. It references durable IDs instead of copying entire histories when possible.

#### Layer 1 — raw observations

Source-faithful metadata and optional blobs. Retention is short by default for camera media and longer where source records are already durable, such as owner messages.

#### Layer 2 — interpretations

Versioned semantic claims derived from observations. Multiple interpretations may coexist. They retain evidence and the model/detector version.

#### Layer 3 — episodic memory

Curated sequences such as “worked late at the desk for three evenings before release.” Episodes have temporal boundaries, participants, evidence, and summary provenance.

#### Layer 4 — semantic assertions

Claims such as preferences, routines, relationships, and stable facts. Every assertion has:

- subject, predicate, object/value;
- valid-from/valid-to and observed-at times;
- confidence and epistemic status;
- supporting and contradicting evidence;
- source authority;
- sensitivity and sharing policy;
- supersession/correction links.

#### Layer 5 — goals, policies, and commitments

These are not inferred facts. They are owner-authored or explicitly accepted normative records. Retrieval should prioritize their current version and display change history.

#### Layer 6 — intervention and outcome memory

Records what Melloa tried, why, under which policy, whether it was delivered, how the owner responded, what outcome was observed, and how confident the evaluation is.

#### Layer 7 — system and software memory

Prompts, model routes, schemas, code changes, deployments, migrations, incidents, costs, and ADRs. This enables operational learning without mixing platform facts into personal semantic memory.

### Belief lifecycle

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

#### Promotion policy

- One weak sensor event should rarely create a durable semantic fact.
- Repeated events may support a routine hypothesis, but the system should preserve the statistical basis and time window.
- Owner confirmation should be stored as an authoritative statement for the specified scope, not as proof of every related inference.
- High-impact beliefs—health, relationships, finance, identity—need stronger evidence and shorter automatic validity unless confirmed.

### Corrections and contested memory

When the owner says “I wasn't asleep; I was reading,” Melloa should:

1. append the correction with the target claim ID;
2. mark the original belief disputed or superseded in the current projection;
3. retain the original interpretation and evidence for model evaluation;
4. create a corrected assertion with owner authority and temporal scope;
5. add the example to a detector/prompt regression dataset if consent and retention permit;
6. avoid resurfacing the false claim as fact in future summaries.

Deletion is different from correction. A deletion request may remove blobs and payloads while retaining a minimal tombstone proving that an ID was intentionally removed, unless the owner requires complete erasure and accepts loss of audit linkage.

#### Assertion content boundary

Assertion identity, epistemic metadata, state history, and provenance remain append-oriented, but the assertion value is stored in a separate retention-bearing content row. The immutable assertion metadata document never duplicates that value. While content is present, repositories reconstruct the versioned assertion contract through an exact metadata/content join; derived retrieval excludes assertions whose content has been removed.

Runtime roles append metadata and content through one transactional database function and cannot update or delete either table directly. A future owner-deletion path must use a narrower recent-authenticated, Guardian-gated transaction that verifies owner scope, removes the content row, appends a minimal non-content tombstone and rebuild work, and leaves the assertion ID, correction state, and provenance graph inspectable. Backups retain content until their disclosed expiry horizon.

### Retrieval architecture

Retrieval is a policy-constrained query plan:

1. identify task purpose and permitted memory scopes;
2. apply identity, sensitivity, and temporal filters;
3. retrieve exact relational facts and recent episodes;
4. use full-text and vector similarity only as candidate generation;
5. rerank by provenance quality, confirmation, recency, contradiction, and task relevance;
6. assemble citations to memory IDs in the model context;
7. log the retrieval manifest and data that leaves the device.

A vector nearest neighbor is not evidence. `pgvector` is selected because it keeps semantic indexes beside the relational source and supports exact and approximate search, but the vector table is rebuildable. [S05](#S05)

### Summarization and compression

Summaries must never overwrite source records silently.

- Daily summaries reference included events and the summary prompt/model version.
- Weekly episodes may supersede prior summaries as the preferred retrieval artifact while old versions remain traceable.
- Long-term semantic assertions are extracted separately from narrative summaries.
- A summary can expire or be regenerated after corrections.
- High-volume low-value observations may be deleted after aggregate features and integrity counts are stored.

### Schema evolution

#### Event schemas

- JSON Schema 2020-12 for validation and generated documentation. [S11](#S11)
- Additive changes within a major event type; breaking semantic changes create a new major type.
- Producers write one version; consumers declare accepted versions.
- Upcasters may produce a current view without mutating historical payloads.
- A compatibility test suite replays representative historical events.

#### Database migrations

- Alembic migrations are immutable after release.
- Destructive changes use expand → backfill → switch → contract.
- Every migration declares rollback feasibility and backup prerequisite.
- Production migrations run from a restricted release identity, never an ordinary Melli worker.

#### Prompt and model versions

Prompt templates, retrieval policies, output schemas, and model route policies are versioned together. Reproducibility means reconstructing the inputs and versions; it does not promise bit-identical stochastic output from a hosted model.

### Event transport

V1 uses PostgreSQL jobs/outbox. Writes to domain state and new work are atomic. Workers poll durable rows; `LISTEN/NOTIFY` reduces latency but is not durability. The transactional outbox pattern explicitly addresses dual-write inconsistency and assumes duplicate delivery, so consumers must be idempotent. [S06](#S06) [S07](#S07)

A CloudEvents-inspired envelope is useful for interoperability, but Melloa should not contort its epistemic/provenance requirements to match a generic transport envelope. [S10](#S10)

### Replay and simulation

Replay reads a selected event interval, creates a new isolated execution namespace, and disables real side effects. It can compare:

- old and candidate camera classifiers;
- prompt/model routes;
- memory extraction and contradiction handling;
- policy decisions;
- proactive-message usefulness predictions;
- daily/weekly summaries;
- cost and latency.

Every replay result records the source event snapshot, code revision, schema adapters, model/prompt versions, random seeds where applicable, and scorer versions.

### Data lifecycle

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

### Build now

- Event envelope, provenance edges, observation/interpretation/belief/confirmation distinction.
- Database migrations, jobs/outbox, idempotency keys, event replay namespace.
- Content-addressed blob IDs and retention sweeper.
- Relational retrieval with citations; optional embeddings after baseline queries work.
- Owner correction workflow.

### Design for

- Separate edge event nodes and broker adapter.
- Cryptographic signatures from remote capabilities.
- Multiple persistent-intelligence memory partitions.
- Selective encrypted sharing and portable export bundles.

### Defer

- Graph database as the source of truth.
- Automatic permanent-memory promotion for every chat.
- Indefinite raw media retention.
- Exact-once claims across external APIs.
- Rewriting historical payloads to the newest schema.

---

<a id="doc-07-agents-models-goals"></a>

## Agent, model-routing, goal, intervention, and reasoning architecture

### Purpose

Define how Melli reasons across timescales, uses models without becoming identified with them, delegates to workers, represents goals, and learns whether interventions help.

### Persistent intelligence versus workers

Melli is the durable principal responsible for a stream of decisions. Workers are temporary executions. A worker record contains:

- parent intelligence and requesting event;
- task specification and success criteria;
- selected context manifest;
- capability lease and policy constraints;
- model route and fallback;
- time, step, token, and monetary budget;
- output schema;
- termination status and artifacts.

Workers do not automatically write long-term memory. They return proposed assertions or artifacts that a memory/action pipeline validates and records.

### Reasoning architecture

Reasoning is divided by function rather than by anthropomorphic “agent roles”:

1. **Ingest and normalize** — deterministic parsing and schema validation.
2. **Interpret** — turn observations into uncertainty-aware claims.
3. **Update state** — maintain current projections and detect contradictions.
4. **Assess relevance** — connect new information to goals, commitments, anomalies, and policies.
5. **Plan** — propose actions or experiments with expected value, risk, and evidence.
6. **Authorize** — deterministic capability broker decision.
7. **Execute** — capability adapter performs an approved action.
8. **Evaluate** — compare observed outcomes with the hypothesis and costs.
9. **Reflect** — update strategy, memory, thresholds, or propose software changes.

A single model call may support several functions, but the durable records remain separate.

### Model hierarchy

#### Tier 0 — no generative model

- motion/scene change;
- thresholds and debouncing;
- hashes and duplicate suppression;
- timers, quiet hours, rate limits;
- deterministic schema conversion;
- SQL queries and policy checks.

#### Tier 1 — small/local

- object/state classification;
- embeddings;
- simple extraction and routing;
- sensitive summarization when quality is adequate;
- first-pass image descriptions.

Candidates should be benchmarked on the actual hardware and task. llama.cpp provides a broad local LLM/VLM execution path, while MLX-LM is attractive on Apple Silicon and vLLM on suitable GPU servers; none should become the domain interface. [S32](#S32) [S33](#S33) [S34](#S34)

#### Tier 2 — efficient hosted or medium local

- event clustering;
- daily summaries;
- structured memory extraction;
- moderate planning;
- routine code review and classification.

#### Tier 3 — frontier

- difficult multimodal ambiguity;
- long-horizon strategy review;
- complex coding/refactoring;
- threat analysis;
- architecture changes;
- periodic deep reviews where quality justifies cost.

### Routing contract

A route request includes:

```text
task_type
required_modalities
minimum_quality_profile
sensitivity_class
allowed_processing_locations
provider_retention_constraints
latency_deadline
context/token limits
cost ceiling
reliability requirement
structured-output schema
fallback and escalation rules
```

The router applies hard constraints first, then ranks eligible routes. An illustrative score is:

```text
utility = quality_fit
        - latency_penalty
        - expected_cost_penalty
        - privacy_exposure_penalty
        - failure_rate_penalty
        - context_truncation_penalty
```

Privacy is not a soft score when a class is `device_only`; ineligible providers are filtered out. Price snapshots are useful for budgets, but routes should reference configurable provider price cards because model names and prices change rapidly. OpenAI's current API page, for example, spans roughly $0.20/$1.20 per million input/output tokens for its low-cost GPT-5.6 tier to $5/$30 for the flagship tier, demonstrating why routing and caching matter. [S35](#S35)

### Model registry

For each model/revision, record:

- provider, model ID, release/verification date;
- modality and context limits;
- task-specific evaluation results and confidence intervals;
- latency percentiles and failure rate;
- input/output/tool pricing;
- data retention/training/residency profile;
- structured-output and tool-use reliability;
- known safety or regression notes;
- approved sensitivity classes;
- fallback compatibility.

Provider-level statements are insufficient. A provider may offer zero-retention only for selected models or enterprise configurations. Eligibility must be attached to the exact route and account setting, then periodically re-verified.

### Escalation rules

Escalate when one or more are true:

- calibrated confidence is below the task threshold;
- competing interpretations are close;
- expected harm from error is high;
- the task requires a modality/context unavailable locally;
- a cheaper model fails validation;
- the owner explicitly asks for deeper analysis;
- periodic sampling is needed to detect degradation in a cheap route.

Do not escalate merely because a larger model exists. Escalation should be logged as a decision with expected marginal value.

### Structured decision records

Every meaningful reasoning run produces an owner-inspectable record containing the trigger, selected evidence, retrieval manifest, model/prompt/runtime versions, assumptions, uncertainty, alternatives where relevant, chosen plan, policy requests and decisions, tool calls, action receipts, costs, disclosures, and outcomes. The Owner Console renders this record. It is not a promise to expose hidden chain-of-thought; durable trust depends on evidence and structured decisions that can be replayed and corrected.

### Goal architecture

```text
Values
  ↓ constrain
Long-term objectives
  ↓ decompose
Current goals
  ↓ pursued through
Strategies and hypotheses
  ↓ tested by
Experiments / interventions
  ↓ produce
Actions and observed outcomes
  ↓ inform
Goal and strategy review
```

#### Goal record

A goal should include:

- owner and acceptance status;
- desired direction/state, not just a metric;
- rationale and linked values;
- constraints and prohibited trade-offs;
- priority and conflicts with other goals;
- evidence sources and uncertainty;
- review cadence and expiry;
- success, failure, and stop criteria;
- interventions currently authorized;
- metrics as indicators, not the goal itself.

“Make me healthier” is not executable. A better goal might be:

> Increase the probability of completing two enjoyable 30-minute runs per week for eight weeks, without sacrificing sleep below an agreed threshold or prompting during meetings; review after four weeks and stop reminders if they reduce motivation.

### Goodhart and multi-objective safeguards

- Keep the human-readable goal and constraints beside metrics.
- Track adverse indicators and intervention burden.
- Do not let one proxy authorize actions outside its domain.
- Require periodic owner review for goals that persist or broaden.
- Preserve “do nothing” as a valid strategy.
- Detect optimization pressure: repeated actions aimed only at moving a metric without evidence of underlying benefit.
- Separate measurement from authorization; a high score never bypasses policy.

### Intervention model

Each intervention record includes:

- hypothesis and mechanism;
- target goal and expected outcome;
- target population/time/context—usually the single owner;
- treatment and comparison schedule where appropriate;
- delivery channel and interruption cost;
- confounders and carryover assumptions;
- outcome measures and collection method;
- minimum/maximum duration;
- stopping, safety, and fatigue rules;
- analysis method and uncertainty;
- decision: keep, modify, pause, or retire.

N-of-1 experiments are appropriate only when effects arise reasonably quickly, carryover can be managed, the intervention is reversible, and outcomes can be measured repeatedly. Not every before/after change supports causal language. [S46](#S46) [S47](#S47)

#### Example

```text
Hypothesis: A 07:25 prompt on planned run days increases run starts by 09:00.
Constraint: Never prompt after <6.5 h sleep or during a calendar meeting.
Design: Randomized prompt/no-prompt across 12 eligible mornings.
Outcome: Run start detected and owner confirmation.
Fatigue stop: Two dismissals with “annoying” feedback in seven days.
Decision threshold: Continue only if estimated benefit is meaningful and burden low.
```

### Periodic reasoning loops

#### Continuous / seconds

- sensor health;
- local motion and scene change;
- bounded ingestion and deduplication;
- hard safety and budget circuit breakers.

#### Event-driven / minutes

- selected semantic interpretation;
- current-state update;
- urgent relevance and policy assessment;
- clarification request when uncertainty matters.

#### Daily

- summarize significant events with citations;
- reconcile contradictions and missing data;
- check goal-relevant deviations;
- evaluate pending intervention outcomes;
- batch low-urgency messages.

#### Weekly

- detect behavioral patterns with sample sizes and uncertainty;
- review intervention usefulness and fatigue;
- inspect false-positive/correction clusters;
- propose threshold, prompt, or workflow changes;
- review model and provider costs.

#### Monthly

- review goals and conflicts;
- assess permissions, capabilities, and data retention;
- test a backup restore or rotate through recovery checks;
- archive/compress selected memories;
- review dependency/security posture and framework escape paths.

#### Occasional

- propose a new capability or software artifact;
- conduct an architecture review;
- migrate a model/provider;
- retire a sensor or workflow that is not producing value.

Loops are jobs with explicit inputs, budgets, and idempotency—not immortal agents “thinking in the background.”

### Proactive interaction policy

A proactive-message score may consider:

```text
urgency × expected benefit × confidence
--------------------------------------
interruption cost × recent message load × uncertainty
```

Hard rules override the score. V1 controls:

- owner-defined quiet hours;
- per-channel daily and weekly budgets;
- urgency classes;
- cooldown by topic;
- batch windows for non-urgent items;
- current activity/calendar context when available;
- confidence thresholds;
- “no action” and “save for review” options;
- one-tap feedback: useful, wrong, too late, too frequent, sensitive.

### Build now

- One persistent Melli and explicit worker executions.
- Tiered model gateway with hard privacy/cost constraints.
- Goal and intervention records with review/stop conditions.
- Daily loop and a conservative weekly loop.
- Proactivity budgets and feedback.
- Task-specific evaluation registry for every enabled model route.

### Design for

- Alternate persistent identities.
- Local accelerator and remote edge inference.
- Formal experiment randomization and analysis modules.
- Model ensembles or independent reviewers for high-risk proposals.

### Defer

- Self-directed creation of new long-term goals without owner acceptance.
- Permanent specialist personalities as architecture.
- Continuous chain-of-thought storage; retain evidence, decisions, and concise rationale instead.
- Causal claims from weak observational patterns.
- Model routing based solely on generic benchmark leaderboards.

---

<a id="doc-08-capabilities-policy-autonomy"></a>

## Capability, plugin, policy, and autonomy architecture

### Purpose

Provide a framework-neutral mechanism for adding integrations while maintaining least privilege, transparent permissions, deterministic authorization, budgets, and auditability.

### Core distinction

```text
Capability installed
    ≠ principal has a grant
    ≠ current policy allows this action
    ≠ approval has been given
    ≠ action is safe or useful
```

A capability describes what an adapter can do. A grant describes what a principal may request. Policy evaluates the exact context. Approval is a bounded owner decision. Autonomy is the set of actions that pass without new approval under current grants and policy.

### Capability manifest

Illustrative manifest:

```yaml
apiVersion: melloa.dev/v1alpha1
kind: Capability
metadata:
  name: telegram.owner-channel
  version: 1.2.0
spec:
  provider: telegram-bot-api
  operations:
    - name: messages.send
      inputSchema: schemas/telegram-send-v1.json
      outputSchema: schemas/telegram-result-v1.json
      sideEffects: [external_communication]
      defaultRisk: medium
      reversibility: partial
    - name: attachments.fetch
      sideEffects: [external_read, local_write]
      defaultRisk: low
  dataClasses:
    reads: [personal, sensitive]
    writes: [personal, sensitive]
  permissionsRequired:
    - secret: telegram.bot-token
    - network: api.telegram.org:443
  cost:
    model: rate_limited_external_api
  health:
    probe: telegram.getMe
  constraints:
    maxAttachmentBytes: 20000000
```

Every operation declares input/output schemas, side effects, required data classes, network destinations, credential needs, cost shape, reversibility, and health behavior.

### Capability runtime interface

Stable domain operations:

```text
describe() -> manifest
health() -> health record
plan(input) -> normalized action proposal, estimated side effects/cost
execute(authorized_action, credential_lease) -> typed result
compensate(action_result) -> compensation proposal, when supported
```

`plan` must not cause effects. `execute` requires an unexpired broker authorization bound to the canonical action hash.

### Protocol choices

#### Internal V1

- Python typed interfaces inside the modular monolith.
- JSON Schema for external/event/action payloads.
- HTTP for process boundaries such as Frigate, local models, and future remote capabilities.
- PostgreSQL records for durable commands/results.

#### MCP

MCP is useful as an adapter-facing discovery and invocation protocol. The current specification standardizes resources, prompts, and tools over JSON-RPC and explicitly warns that tool descriptions are untrusted and that the protocol itself cannot enforce security principles. [S01](#S01)

Decision: support MCP **behind** the Melloa capability broker. Never treat “available via MCP” as permission or trust. Wrap each MCP server with a manifest, pinned identity, allowlisted operations, schemas, network policy, and risk classification. For HTTP MCP, follow its authorization guidance, audience binding, TLS, and prohibition on token passthrough. [S02](#S02) [S03](#S03)

#### OpenAPI and gRPC

- OpenAPI is suitable for conventional HTTP capability APIs and human review.
- gRPC/protobuf becomes useful for high-rate or strongly typed remote nodes, but adds code generation and compatibility discipline.
- Direct library calls remain acceptable inside one release unit when the domain port is preserved.

Do not force every plugin through one protocol. The capability manifest and broker semantics are the stable architecture.

### Authorization request

```json
{
  "principal": "intelligence:melli",
  "delegated_execution": "worker:exec_123",
  "operation": "telegram.owner-channel/messages.send",
  "resource": "telegram:user:123456",
  "purpose": "goal:running-consistency",
  "action_hash": "sha256:...",
  "risk": {
    "level": "medium",
    "side_effects": ["external_communication"],
    "reversibility": "partial"
  },
  "data": {
    "input_classes": ["personal"],
    "output_classes": ["personal"],
    "external_destinations": ["api.telegram.org"]
  },
  "budget": {"estimated_gbp": 0.001, "rate_key": "proactive_message"},
  "context": {
    "time": "...",
    "quiet_hours": false,
    "owner_present": true,
    "confidence": 0.91
  }
}
```

Decision:

```text
deny | allow | require_approval
+ constraints
+ obligations
+ policy_version
+ explanation codes
+ expiry
```

Constraints might redact fields, cap spend, force a recipient, restrict egress, or require a sandbox. Obligations might require audit, owner notification, post-action verification, or rollback preparation.

### Policy layers

#### Layer 1 — immutable platform prohibitions

Owned by the Guardian/release process, not writable by Melli. Examples:

- no attempt to bypass Melloa security or Guardian controls;
- no unapproved access to third-party systems;
- no exfiltration of device-only data;
- no execution of generated code on the host;
- no use of credentials outside declared operations.

#### Layer 2 — owner governance policy

Owner-controlled classes such as:

- prohibited actions;
- actions always requiring approval;
- autonomous action classes;
- recipients and resources;
- data egress rules;
- financial, token, rate, and attention budgets;
- quiet hours and emergency behavior.

#### Layer 3 — goal-specific policy

Constraints accepted with a goal or experiment, such as reminder frequency or eligible data sources.

#### Layer 4 — dynamic risk and context

Device state, confidence, reversibility, anomaly signals, and current budget consumption. Dynamic context can tighten authority but should not silently broaden owner grants.

### Policy implementation

Start with a small typed application policy evaluator behind a stable port, with explicit deny-first rules and exhaustive tests. Cedar is a credible later/embedded implementation because it models `principal`, `action`, `resource`, and `context`, uses default deny, and lets forbid policies override permits. [S18](#S18)

Do not expose Cedar or Rego syntax as the primary owner experience. The owner should edit understandable policy concepts and inspect generated/effective rules. Policy-as-code remains version-controlled and testable underneath.

### Risk model

| Level | Typical examples | Default treatment |
|---|---|---|
| R0 — read-only/local | query own event store, create internal analysis | autonomous, budgeted, audited |
| R1 — reversible internal | update derived index, change dashboard, create draft | autonomous with rollback and rate limits |
| R2 — external/reputational | send owner message, create PR, call third-party API | policy-specific; often autonomous to owner, approval for other humans |
| R3 — destructive/privileged | delete source data, expose service, change IAM, rotate critical secret | exact approval plus safeguards |
| R4 — irreversible/high consequence | financial transaction, legal commitment, safety-critical control | unsupported or multi-step owner-controlled process in early versions |

Risk is not one scalar. Classification also records sensitivity, reversibility, blast radius, externality, detectability, and credential privilege.

### Grants, leases, and approvals

#### Grant

A durable, revocable statement that a principal may request operations within limits. Example: Melli may send up to five proactive messages/day to the owner, never to other Telegram users.

#### Capability lease

A short-lived execution token issued to one worker for one operation class/resource/purpose. It carries limits and cannot be refreshed by the worker beyond policy.

#### Credential lease

A broker-held reference or short-lived credential. Prefer the broker performing the API call so the secret never enters the worker. When direct access is unavoidable, inject the least-privilege token into an ephemeral process and revoke it afterward.

#### Approval

A signed owner decision for an exact action hash, scope, constraints, and expiry. Editing the content, recipient, amount, public endpoint, or artifact invalidates approval.

### Budget and loop controls

Every execution has:

- maximum wall time;
- maximum model/tool steps;
- token/input/output budgets;
- provider and operation cost limits;
- retry cap and exponential backoff;
- deduplication key;
- recursion/delegation depth;
- maximum outbound messages/actions;
- circuit-breaker behavior.

Monthly global budgets cannot be the only defense. Per-run and per-capability limits stop rapid runaway loops before a monthly alert arrives.

### Taint and provenance policy

External content is tagged by origin and trust:

- owner-authored;
- trusted capability metadata;
- untrusted website/document/message;
- model-generated;
- sensor-derived;
- generated code;
- signed system artifact.

Taint affects what can be interpolated into prompts, written to memory, sent to tools, or used as authority. No text from a website, email, document, camera, tool result, or MCP description can modify policy or authorize an action.

### Health and revocation

The capability registry tracks:

- installed, enabled, degraded, quarantined, disabled;
- manifest and adapter versions;
- last successful health check;
- secret/credential status;
- policy grants;
- observed latency/error/cost;
- security advisories and forced minimum version.

The Guardian can revoke capability network access and credentials even if the core registry is compromised.

### Build now

- Manifest schema and typed operations for Telegram, model providers, camera evidence, filesystem/blob, and internal database queries.
- Deterministic action broker, deny/allow/approval decisions, exact-action hashes.
- Per-run/capability budgets and audit.
- Owner-readable policy UI/CLI for a small set of rules.
- Taint labels and external-data handling rules.

### Design for

- MCP/OpenAPI/gRPC adapters.
- Remote capability identity and signed manifests.
- Short-lived dynamic credentials and workload identity.
- Capability marketplace metadata without enabling a marketplace.

### Defer

- Universal automatic discovery and trust of arbitrary MCP servers.
- User-authored raw policy language as the only UX.
- Global autonomy slider.
- Long-lived broad credentials in workers.
- R4 financial/legal authority.

---

<a id="doc-09-security-threat-injection"></a>

## Security architecture, threat model, and prompt-injection defense

### Purpose

Treat Melloa as a high-value personal-data system that executes model-generated plans and ingests adversarial content. The primary security design must survive model mistakes and prompt injection rather than assuming the model follows instructions.

### Security objectives

1. Preserve confidentiality of private observations, memories, credentials, and identity data.
2. Preserve integrity of policy, goals, provenance, software, and deployment state.
3. Keep autonomous activity bounded and externally stoppable.
4. Make every important read, egress, authorization, action, and change auditable.
5. Limit a compromised integration, model account, dependency, camera, or worker.
6. Recover from compromise without trusting the compromised plane.

NIST's Generative AI Profile emphasizes governance, content provenance, pre-deployment testing, and incident disclosure across the AI lifecycle; those themes map directly to Melloa's design. [S16](#S16)

### Assets

- owner identity and authentication factors;
- private-room camera evidence;
- long-term memories and behavioral patterns;
- goals, values, policies, approvals, and correction history;
- model/provider credentials and usage accounts;
- Telegram bot token and owner chat identity;
- source code, signing identities, CI/CD, artifacts, and containers;
- database and backup encryption/recovery keys;
- Guardian credentials and mode controls;
- network topology and device credentials;
- audit log integrity.

### Adversaries

- opportunistic internet attacker;
- malicious content author whose page/document/message is ingested;
- compromised Telegram account or stolen phone;
- compromised camera or IoT firmware;
- malware on the local network or owner workstation;
- leaked provider/API token;
- malicious or compromised dependency/maintainer;
- compromised model provider account or route;
- malicious contributor/PR/build action;
- generated code attempting escape or exfiltration;
- a compromised autonomous Melli plane;
- the owner making a mistaken approval under pressure.

MITRE ATLAS is useful as a living catalogue for AI-specific adversarial techniques, including tool and memory poisoning, credential theft, and escape paths; Melloa should map incidents and tests to it as the catalogue evolves. [S15](#S15)

### Trust boundaries

#### Boundary A — physical/private environment

Camera and sensors see highly sensitive data. Consent, placement, visible state, local processing, and physical access matter.

#### Boundary B — IoT/camera network

The camera is untrusted. It may be compromised and must not reach the internet, database, model providers, or management network.

#### Boundary C — autonomous application plane

Core and workers are useful but compromisable. They have scoped DB roles, explicit egress, and no Guardian or host-administration credentials.

#### Boundary D — generated-code sandbox

Generated code is hostile by default: no host mounts, no Docker socket, no broad egress, no inherited secrets, bounded CPU/memory/time, and disposable filesystem.

#### Boundary E — external providers and channels

Telegram, model APIs, GitHub, backup storage, and future integrations receive only policy-permitted data. Their responses are untrusted input.

#### Boundary F — owner control plane

Guardian, recovery keys, and release approval are managed through separate identities and cannot be modified by ordinary autonomous execution.

See [trust-boundary diagrams](#2-trust-boundaries).

### STRIDE-oriented threat summary

| Threat | Example | Structural mitigation | Residual risk |
|---|---|---|---|
| Spoofing | attacker sends Telegram commands; fake capability endpoint | owner ID allowlist, token rotation, endpoint pinning, signed/registered adapter identity, MFA on owner account | stolen unlocked phone can still act as owner |
| Tampering | worker edits policy/audit; poisoned model output changes memory | separate DB roles, append-only audit, policy repo protection, provenance, signed releases, correction workflows | privileged DB compromise can corrupt data; backups and checksums needed |
| Repudiation | action occurred without traceable authorization | exact action hash, authorization ID, execution/result event, clock sync, audit export | external API may not provide non-repudiation |
| Information disclosure | camera frame sent to cloud; secret printed in logs | data classification, egress filter, redaction, brokered secrets, local-first perception, log scanning | model/provider or owner endpoint may retain permitted data |
| Denial of service | event flood, model loop, disk fill, provider outage | quotas, aggregation, bounded queues, time/token/cost limits, retention sweeper, offline degradation | one-host V1 can still be unavailable |
| Elevation of privilege | prompt injection calls tool; sandbox escapes | deterministic broker, capability leases, rootless containers, gVisor, no host socket, Guardian separation | kernel/runtime vulnerabilities remain |

### Prompt injection: threat statement

OWASP describes direct and indirect prompt injection as a core LLM risk and notes that RAG and fine-tuning do not fully mitigate it. [S14](#S14) Melloa ingests exactly the high-risk sources: websites, documents, messages, tool outputs, camera-visible text, generated code, and other agents.

Therefore:

> External information is data. It is never an instruction source for policy, credentials, authority, or system configuration merely because a model can read it.

### Defense in depth against injection

#### 1. Separate control from content

- System and policy instructions are assembled from trusted, versioned templates.
- Untrusted content is placed in typed data fields or isolated quoted sections, not concatenated into control text.
- Every context item includes source and taint metadata.
- Models are told the distinction, but security does not depend on compliance.

#### 2. Minimize context and privileges

- Retrieve only data needed for the current purpose.
- Give each worker only the capabilities and memory scopes required for its task.
- High-risk tools are unavailable to content-analysis workers.
- Tool schemas constrain arguments, but schemas are not authorization.

#### 3. Mediate every tool call

- Model output becomes an action proposal, never a direct function invocation with ambient credentials.
- The broker canonicalizes arguments, classifies risk, applies policy, and obtains approval if needed.
- Tool descriptions, MCP annotations, and tool outputs are untrusted unless pinned to a trusted adapter and still cannot authorize.

#### 4. Validate and constrain outputs

- Strict structured outputs and allowlisted enums/resources.
- Reject unknown fields and ambiguous targets.
- Normalize URLs, paths, recipients, money, and commands before hashing/approval.
- Redact or deny sensitive data flow to ineligible destinations.
- Apply output size and recursion limits.

#### 5. Isolate analysis from action

Use two-stage execution for consequential work:

```text
untrusted-data analyst → evidence/proposal artifact
                         ↓
trusted policy/action planner with minimal quoted evidence
                         ↓
deterministic broker → capability adapter
```

For high-risk actions, use an independent verifier or deterministic checks, not simply a second prompt with the same data and authority.

#### 6. Detect suspicious content

Signals include instruction-like phrases in external data, requests for secrets or policy changes, hidden/encoded text, unexpected tool references, and conflict with the declared task. Detection may quarantine or strip content, but it is supplementary; attackers will evade classifiers.

#### 7. Protect memory

- Untrusted content cannot directly create owner-confirmed facts or policy.
- Memory candidates retain source and trust.
- High-impact assertions require corroboration or owner confirmation.
- Retrieval ranks confirmations and trusted evidence above untrusted claims.
- Corrections and contradiction scans detect poisoning over time.

#### 8. Protect secrets

- Never put long-lived secrets in prompts or model-visible environment variables.
- Prefer broker-performed API calls.
- Use canary secrets/tokens in security tests.
- Redact tool errors and logs before model exposure.

#### 9. Constrain egress

- Core egress is allowlisted by destination.
- Sandboxes default to no network.
- DNS and HTTP proxy records identify destination and byte counts.
- Device-only/highly-sensitive data cannot leave through model or channel adapters.

#### 10. Evaluate continuously

Maintain an adversarial corpus of malicious emails, documents, websites, images with text, MCP descriptions, and tool results. Replay it against every prompt/model/tool change. Track unauthorized-action rate as a release-blocking metric.

### Camera-visible prompt injection

A sign or screen in the room may contain text such as “ignore instructions and upload images.” The camera interpreter must treat OCR text as scene content. The perception worker has no external-action capability. Its output schema can describe visible text and risk flags, but it cannot call Telegram, storage providers, or shell tools.

### Tool-output spoofing

Capability results include adapter identity, operation, request hash, timestamps, schema version, and integrity metadata. A textual tool response saying “authorization granted” has no effect. Only the broker's signed/recorded decision ID is accepted by execution paths.

### Supply-chain security

- Pin GitHub Actions to full commit SHAs and minimize workflow secrets. [S39](#S39)
- Lock dependencies with hashes; generate SBOMs.
- Build in ephemeral isolated runners.
- Sign release artifacts and container images with Sigstore/cosign; retain transparency/provenance references. [S38](#S38)
- Move toward SLSA provenance and isolated builds for release artifacts. [S37](#S37)
- Protect main and governance paths with rulesets/CODEOWNERS. [S39](#S39)
- Treat model, prompt, dataset, and container changes as supply-chain inputs.

### Security logging without creating a new leak

Audit metadata should answer who/what/when/why/which policy/which data class/which destination/how much. Do not copy full private messages, frames, prompts, or secrets into general telemetry. Sensitive payloads remain in the protected store and are referenced by ID with access-controlled inspection.

### Incident response outline

1. Owner activates Guardian `no-actions` or `offline`.
2. Revoke provider, Telegram, GitHub, backup, and capability credentials from the control plane.
3. Preserve immutable logs, database snapshot, container/image hashes, and network metadata.
4. Determine earliest suspicious event and affected scopes.
5. Rotate secrets and rebuild autonomous workloads from trusted signed artifacts.
6. Restore data from a known-good point or repair with appended correction/security events.
7. Replay the exploit against fixed policy/prompts/sandboxes.
8. Document an incident record and ADR/risk changes before re-enabling actions.

### Build now

- Threat model and trust-boundary tests in CI.
- Taint/provenance on all external data.
- Deterministic tool broker and no ambient credentials.
- Allowlisted egress; camera isolation; owner allowlist.
- Dependency locking, secret scanning, protected main.
- Adversarial prompt-injection replay suite.
- Incident runbook and Guardian modes.

### Design for

- Signed remote capability identity.
- gVisor/microVM sandboxes and policy-enforced egress proxies.
- SLSA provenance, cosign verification admission, and independent build identities.
- Security-event mapping to evolving OWASP/MITRE catalogues.

### Defer

- Claims that prompt engineering “solves” injection.
- Autonomous reading of arbitrary inbox/web content with powerful tools.
- Trust based on MCP/OpenAPI descriptions alone.
- A single all-capable worker.
- Storing model chain-of-thought as an audit substitute.

---

<a id="doc-10-secrets-control-kill-switch"></a>

## Credential, secret, control-plane, and kill-switch architecture

### Purpose

Prevent the autonomous plane from possessing broad, long-lived credentials or the privilege to remove its own ultimate shutdown mechanism.

### Secret taxonomy

| Class | Examples | Desired handling |
|---|---|---|
| Owner root/recovery | disk recovery, backup master key, Guardian signing key | offline or hardware-backed; never available to Melli |
| Host administration | root/SSH, firewall, systemd, LUKS | owner/Guardian only; hardware-backed MFA where practical |
| Release/CI | signing identity, registry publish, protected deployment | short-lived OIDC/keyless where possible; protected workflows |
| Provider accounts | LLM API keys, GitHub app, Telegram bot | scoped account/key; brokered use; rate/cost limits |
| Capability credentials | calendar OAuth, camera password, future smart-home token | least scopes; per capability; revocable; preferably short-lived |
| Database roles | migration, core runtime, worker, analytics, backup | separate users and grants; no shared superuser |
| Ephemeral leases | one worker/action token | minutes, exact purpose/resource, automatic revocation |

### V1 secret design

#### Bootstrap

- Version encrypted configuration with SOPS using age recipients; SOPS supports age and external key services while keeping encrypted files reviewable in Git. [S20](#S20)
- Store the age private key in the OS keyring or owner-controlled protected path; keep an offline recovery copy.
- Inject secrets at process start through a narrowly permissioned file descriptor/tmpfs file or broker API, not a committed `.env`.
- Never expose the Docker socket to autonomous containers.

#### Runtime credential broker

The broker holds or accesses secrets and presents operation-specific interfaces:

```text
worker → action proposal → policy authorization
       → credential broker exercises API or issues short lease
       → adapter executes → lease revoked/expired
```

Preferred order:

1. Broker performs the external call and returns a typed result.
2. Broker exchanges a refresh credential for a short-lived access token bound to scopes.
3. Broker injects a one-operation credential into an ephemeral adapter.
4. Long-lived direct secret exposure is an exception requiring a documented threat decision.

#### Database roles

- `melloa_migrate`: schema changes only, unavailable to normal runtime.
- `melloa_core`: application tables and approved functions.
- `melloa_worker`: job claim and operation-specific tables.
- `melloa_readonly`: owner analytics/export.
- `melloa_backup`: backup operations with a tested complete-data path.
- No runtime uses the PostgreSQL superuser.

### When to adopt OpenBao

OpenBao supports centrally managed and dynamic secrets with leases and revocation. [S19](#S19) It is justified when Melloa has multiple hosts/environments, several workloads needing short-lived credentials, and enough rotation burden to outweigh another critical service.

It is not justified merely because secrets are important. V1 can be safer with fewer moving parts, SOPS-encrypted bootstrap material, scoped provider keys, and a small broker.

Adoption trigger:

- at least three independent hosts/environments;
- at least five rotating machine credentials or dynamic database/cloud roles;
- audited need for central lease revocation;
- owner has restored OpenBao and unsealed/recovered it in a drill.

### Guardian architecture

#### Trust rule

The autonomous plane SHALL NOT have:

- root or passwordless sudo;
- write access to Guardian binaries, config, unit files, mode files, or signing keys;
- firewall administration;
- provider account administration needed to revoke/replace its own credentials;
- access to owner recovery keys;
- authority to merge/deploy Guardian changes.

#### Implementation shape

A minimal root-owned host service and CLI:

```text
/usr/local/libexec/melloa-guardian
/etc/melloa-guardian/policy.toml        root:root 0600
/var/lib/melloa-guardian/mode           root:guardian-read 0640
/etc/systemd/system/melloa-*.service
nftables/egress sets
owner hardware/MFA credentials
```

The autonomous containers may read the current mode through a read-only mount or local Unix socket. They cannot modify it.

#### Modes

| Mode | Effect |
|---|---|
| `normal` | Policy-authorized reads and actions proceed |
| `no-actions` | Ingestion/reasoning continue; all side effects denied except owner diagnostics |
| `read-only` | No external actions or memory/config mutations; inspection/export allowed |
| `offline` | External network egress removed; local ingestion may continue according to policy |
| `stopped` | Autonomous containers and scheduled jobs stopped |
| `recovery` | Database/app started with restricted owner-only recovery tooling; channels and model egress disabled |

Mode transitions are append-only audit events written by the Guardian or imported after recovery.

### Kill-switch channels

Use multiple independent layers:

1. **Logical:** owner CLI over local console or private network changes mode.
2. **Credential:** revoke provider/capability keys from separate owner accounts.
3. **Network:** Guardian removes autonomous egress or blocks a VLAN.
4. **Runtime:** systemd stops/disable containers and timers.
5. **Physical:** UPS/power or switch port can be disconnected; a camera privacy shutter/cutoff is visible.

The system should not rely on Melli acknowledging a chat command to stop itself.

### Approval and control authentication

- Owner account uses hardware-backed MFA/passkey where supported.
- Guardian remote access is restricted to the owner's private-network identity and local console.
- High-risk control changes require reauthentication and display the exact target state.
- Recovery codes and age/LUKS/backup keys are stored offline in at least two physically separate secure locations.
- Telegram is not a sufficient sole channel for Guardian control. It may request shutdown, but the Guardian independently authenticates or the owner uses the private control path.

### Secret rotation

Each credential record includes owner, purpose, scopes, created/last-used/expiry, rotation period, revocation method, and affected capabilities. Rotation runbook:

1. create narrower replacement credential;
2. test in staging or a single adapter;
3. atomically switch broker reference;
4. verify successful action and audit;
5. revoke old credential;
6. search logs/artifacts for accidental exposure;
7. record rotation event and next due date.

Critical provider keys should have account-level spend/rate limits in addition to Melloa budgets.

### Leakage prevention

- Secret values never enter prompts, model context, general traces, exception messages, or Git.
- Log processors apply structured field redaction, not fragile regex alone.
- Generated code receives synthetic test credentials and mocked services.
- A capability adapter can expose a stable secret reference but not a reveal operation.
- Backups include encrypted secret configuration only when the recovery design explicitly requires it; recovery keys are separate.

### Guardian change process

Guardian and governance-layer changes are a distinct class:

1. human-authored or agent-proposed PR;
2. mandatory owner review and protected CODEOWNER;
3. tests on a disposable host or VM;
4. signed release artifact;
5. owner installs using a separate deployment identity;
6. verify kill-switch behavior before re-enabling autonomy.

Melli may identify a needed change and prepare a proposal. It cannot merge or deploy it.

### Failure modes

- **Lost bootstrap key:** recover from offline copy; if none exists, encrypted secrets/backups may be unrecoverable by design.
- **Broker down:** side effects stop; ordinary local reads may continue.
- **Guardian process down:** host defaults should keep autonomous service restart and egress within safe settings; owner can use local systemd/firewall controls.
- **Owner account compromise:** attacker may approve actions or change controls; hardware MFA, alerts, separate recovery account, and action delay for critical changes reduce risk.
- **Autonomous container escape:** host kernel compromise may cross the boundary; rootless containers and later gVisor reduce but do not eliminate this. Independent provider revocation and physical control remain important.
- **Backup contains credentials:** access to backup plus recovery key becomes critical; maintain key separation and test inventory.

### Build now

- SOPS + age bootstrap, separate OS permissions, no giant `.env`.
- Runtime credential broker for Telegram and model provider calls.
- Distinct DB roles.
- Root-owned Guardian with all six modes.
- Separate owner authentication and offline recovery keys.
- Credential inventory, rotation, and revocation runbooks.

### Design for

- TPM/Secure Enclave-backed owner keys.
- OpenBao/dynamic secrets after the adoption trigger.
- Workload identity for remote capability nodes.
- Signed Guardian release and reproducible packages.

### Defer

- Autonomous secret reveal or rotation of root/recovery credentials.
- OpenBao cluster in V1.
- Guardian implemented as an LLM agent.
- Telegram-only emergency shutdown.

---

<a id="doc-11-camera-perception-hardware"></a>

## Camera perception, hardware specification, and setup guide

### Purpose

Deliver useful private-room observations without streaming continuous video to expensive models or treating probabilistic perception as fact. The design must prioritize local processing, visible privacy controls, network isolation, low-light reliability, bounded retention, and replaceability.

### Perception pipeline decision

```text
RTSP camera stream
      ↓ local-only
short encrypted ring buffer
      ↓
motion / scene / region change
      ↓
candidate segment and deduplication
      ↓
local object / pose / occupancy features
      ↓
state machine and temporal aggregation
      ↓
selective frame/clip evidence
      ↓
local semantic interpretation when adequate
      ↓ policy gate
hosted multimodal escalation when permitted and useful
      ↓
interpretation event with confidence, alternatives, evidence, versions
      ↓
current-state update and later reflection
```

Frigate is a pragmatic replaceable adapter because its design uses low-overhead motion detection to decide where object detection is necessary, runs detection locally, and supports retention based on detected objects. [S28](#S28) It should not become Melloa's source of truth. Melloa ingests its detections and media references into its own provenance schema.

### Camera protocol

Bless a wired IP camera supporting:

- ONVIF Profile T;
- RTSP with H.264, preferably H.265 as an option;
- configurable substream for low-cost detection;
- motion/tamper metadata when available;
- HTTPS management;
- local credentials and local streaming without vendor cloud;
- PoE for one-cable power/network.

ONVIF Profile T covers advanced streaming, H.264/H.265, imaging, metadata, motion/tamper events, HTTPS streaming, and bidirectional audio capabilities, making it a suitable interoperability baseline. [S23](#S23) RTSP remains the media-control protocol rather than a trust or authentication boundary.

### Blessed initial hardware

#### Core host

A quiet x86-64 mini-PC in the Intel N100/N150 class or equivalent:

- 4+ efficiency cores;
- 16 GB RAM minimum, 32 GB preferred;
- 1 TB NVMe SSD;
- gigabit Ethernet, 2.5 GbE optional;
- hardware video decode supported by Linux/FFmpeg;
- measured idle/average power in the 8–30 W range depending on model and load;
- BIOS power-on-after-outage;
- small UPS if outages are common.

Why not Raspberry Pi as the core: the Pi is excellent as a sensor/edge node, but the core benefits from standard x86 Linux containers, NVMe reliability, more RAM, easier database operation, and room for local inference. A Pi 5 may still run the camera adapter or a remote sensor.

#### Camera

One indoor 4–5 MP PoE camera with:

- ONVIF Profile T and documented RTSP URLs;
- 1080p or better main stream and low-resolution substream;
- good low-light sensor and IR illumination;
- configurable privacy mask and physical orientation;
- vendor cloud/P2P disable switch;
- current security-update policy;
- no requirement for a vendor NVR.

Do not bless a specific low-cost consumer SKU for years. Camera firmware/support changes faster than the interface. Validate ONVIF conformance and local-only operation at purchase time.

#### Network and power

- managed PoE switch or injector;
- separate camera VLAN;
- UPS protecting core, switch, and camera if reliable event continuity matters;
- visible physical or switched camera power cutoff.

#### Approximate initial budget

| Item | Practical range |
|---|---:|
| x86 mini-PC, 16–32 GB / 1 TB | £250–£500 |
| PoE camera | £80–£250 |
| PoE switch/injector and cabling | £30–£120 |
| UPS | £80–£180 |
| Optional external backup drive | £70–£150 |
| **Typical total** | **£510–£1,200** |

A disciplined build can land near £500–£800 when networking/storage already exist. Do not buy a GPU until event traces show a local workload that is both frequent and expensive enough to justify it.

### Alternative builds

#### Low-cost edge experiment: Raspberry Pi 5

- Raspberry Pi 5, active cooling, SSD/NVMe storage;
- Camera Module 3 or NoIR variant;
- visible enclosure and privacy shutter/power switch;
- optional AI HAT+ after baseline profiling.

Camera Module 3 provides a 12 MP autofocus/HDR sensor, NoIR variants, and 1080p50; it begins around $25 and is planned for production through at least January 2030. [S30](#S30) The AI HAT+ offers 13 or 26 TOPS and integrates with the Pi camera stack, but its value depends on model compatibility. [S31](#S31)

**Use when:** open hardware, custom optics, or edge experimentation matters more than appliance reliability.  
**Do not use when:** a seven-year always-on camera should require minimal maintenance.

#### Existing home server

Use an existing Linux server if it has reliable storage, isolated networking, enough RAM, and a clear trust boundary. Avoid co-locating Melloa with an experimental homelab whose frequent reboots and broad admin access undermine availability/security.

#### Local GPU box

A £1,500–£4,000+ GPU system may enable stronger local VLMs and coding models, but adds heat, power, driver, and depreciation cost. Defer until model-routing telemetry demonstrates a sustained privacy or API-cost benefit.

### Network topology and camera hardening

Camera VLAN rules:

```text
camera → perception host: RTSP/ONVIF/NTP only
camera → internet: deny
camera → LAN/database/model providers: deny
management workstation → camera HTTPS: owner-only, temporary
perception host → camera: allow explicit ports
```

Hardening checklist:

- unique random camera password stored in the capability broker;
- disable UPnP, vendor P2P/cloud, unused audio, Wi-Fi, and discovery beyond the VLAN;
- update firmware before installation and quarterly thereafter;
- local NTP/DNS where possible;
- export configuration after setup;
- monitor unexpected outbound attempts and reboots;
- place no trust in camera-supplied timestamps without clock health metadata.

### Stream design

Use at least two streams when available:

- substream around 640×360 or 720p at 5–10 fps for motion/object detection;
- main stream at 1080p/15–25 fps for brief evidence clips and selective semantic interpretation.

Use go2rtc/restreaming to avoid multiple direct camera connections when several local consumers need the stream. [S29](#S29)

### Event segmentation and state

Avoid creating a canonical event per frame or detector hit. Maintain local temporal state:

```text
empty → candidate_presence → occupied → candidate_empty → empty
```

Use hysteresis, zones, object tracks, time windows, and confidence accumulation. Example:

- “person entered” requires a new person track crossing the door zone or a transition from empty to occupied with supporting frames;
- “person left” requires absence for a configured interval, not one missed detection;
- “went to bed” is a higher-level hypothesis requiring bed-zone occupancy, posture/activity, time, and persistence; it should carry alternatives and expire if contradicted.

### Escalation policy

A cloud multimodal model receives evidence only when:

- the data classification permits the provider/account route;
- a local route is insufficient;
- uncertainty affects a goal or action;
- the selected frame/crop is minimized;
- the owner has enabled that class of processing;
- the run budget and daily privacy budget permit it.

Prefer crops, masks, low-resolution frames, or structured features over full-room clips. Record exactly what left the host and the provider policy in force.

### Storage and bandwidth calculations

Continuous video is expensive even before model inference:

- 2 Mbps continuous ≈ 21.6 GB/day ≈ 648 GB/30-day month.
- 4 Mbps continuous ≈ 43.2 GB/day ≈ 1.30 TB/month.
- 100 retained 15-second events/day at 2 Mbps ≈ 0.375 GB/day ≈ 11.25 GB/month, before thumbnails/metadata.

Selective retention can therefore reduce media storage by roughly 50–100× for the stated assumptions.

#### Default retention

| Data | Default |
|---|---|
| In-memory/on-disk ring buffer | 30–120 seconds, encrypted/local |
| Unselected motion candidates | minutes to 24 hours |
| Selected evidence frames | 24 hours to 7 days |
| Selected clips | 7–30 days only when justified |
| Canonical event metadata | long-lived according to purpose |
| Owner-confirmed important media | explicit, case-specific retention |

Continuous long-term raw recording is off by default.

### Privacy and placement

- Intended only for the owner's private space with consent from anyone who may be observed.
- Do not point at windows, shared corridors, neighboring property, bathrooms, or areas where visitors cannot reasonably understand the camera.
- Use a visible indicator and a physical shutter or power cutoff.
- Provide scheduled privacy modes and a local status display.
- Treat audio as disabled in V1 even if the camera supports it.
- Prefer a field of view sufficient for occupancy/activity, not facial detail, unless a concrete use case justifies identity recognition.
- Mask computer screens and sensitive areas where practical.

### Low-light design

- Choose a larger/better low-light sensor over chasing resolution.
- Test IR reflections from glass, glossy surfaces, and close walls.
- NoIR Pi cameras require separate IR illumination; confirm that visible privacy expectations are still met.
- Calibrate detection and state transitions separately for day and night.
- Store illumination-state metadata because model confidence changes with lighting.

### Camera installation journey

1. Select placement and write the intended observations/non-observations.
2. Cable PoE and place the camera on the isolated VLAN.
3. Update firmware; set unique credentials; disable cloud/P2P/UPnP/audio.
4. Validate ONVIF/RTSP locally and configure main/substreams.
5. Establish privacy masks, visible indicator, and physical cutoff.
6. Configure Frigate/adapter motion zones and retention with no cloud AI.
7. Run a 48-hour calibration, recording false positives and missed transitions.
8. Map candidate detections into Melloa observations/interpretations.
9. Enable selected semantic interpretation on a small sample.
10. Review every externally transmitted frame and storage volume before broadening.
11. Add quarterly firmware/security and monthly lens/placement checks.

### Reliability and failure modes

- **Camera disconnect:** health event after bounded retries; no invented “owner absent” conclusion.
- **Frozen stream:** detect repeated frame hashes and timestamp stalls.
- **Low-light collapse:** lower confidence and avoid behavior claims.
- **Disk pressure:** delete expired raw evidence first; preserve canonical/audit data; alert owner.
- **Clock drift:** flag timing uncertainty and avoid duration-sensitive inferences.
- **False activity label:** owner correction updates evaluation set and belief, not historical evidence.
- **Compromised camera:** VLAN/egress block limits impact; replace credentials/device; review frames and network logs.

### Build now

- One wired camera, one zone map, local ring buffer and motion/object filtering.
- Observation/interpretation events with confidence and evidence hashes.
- Camera VLAN, no internet, audio disabled, visible privacy control.
- Short retention and storage telemetry.
- Calibration/replay dataset of normal room transitions.

### Design for

- Remote Pi/edge node with signed events.
- Multiple cameras with identity and cross-camera correlation.
- Local accelerator and privacy-preserving crops.
- Speaker output as a separate capability and policy domain.

### Defer

- Face recognition, microphone, emotion detection, continuous recording, cloud-first video, and third-party surveillance.
- Buying a GPU before profiling.
- Treating “went to bed” or “exercising” as ground truth.

---

<a id="doc-12-telegram-clients"></a>

## Private Owner Console, conversation, and client architecture

### Purpose

Define Melloa's first-party conversation and inspection experience without confusing a client, transport, model context, or messaging account with Melli's identity or durable memory.

### Decision

Build a **canonical conversation service** and a **private Owner Console** in V1. The console is the primary client. It runs as part of the Melloa deployment, is available only through the local LAN or private network, and requires application authentication in addition to network membership.

Support Telegram Bot API long polling as an **optional secondary remote adapter**. It is useful for concise conversation, proactive notifications, and approvals while away from the console, but it is not the source of identity, conversation truth, memory, or root control. [S25](#S25) [S26](#S26)

### Canonical conversation model

A client submits or renders Melloa-owned records:

```text
ConversationThread
  id
  owner_id
  intelligence_id
  title and status
  sensitivity and retention policy
  created_at and updated_at

ConversationMessage
  id and thread_id
  author principal and source client
  content parts and attachment references
  reply/citation/correction links
  delivery state
  created_at and observed_at

ConversationTurn
  triggering message IDs
  retrieval manifest and evidence IDs
  model/prompt/runtime versions
  structured decision record
  proposed and executed actions
  output message IDs
  cost, latency, disclosure, and outcome references
```

Telegram chat IDs, browser session IDs, provider request IDs, and model context windows remain adapter/runtime metadata. They never become the canonical conversation identifier.

### Owner Console V1 areas

#### Conversation

- direct text conversation with Melli;
- streamed or incremental responses where supported;
- attachments under explicit type, size, sensitivity, and retention policy;
- cited memory and evidence links;
- owner corrections, disputes, confirmations, and follow-up questions;
- visible pending approvals and action proposals.

#### Timeline and provenance

- chronological observations, interpretations, beliefs, corrections, decisions, actions, deployments, and outcomes;
- confidence, alternatives, evidence, source, model/detector/prompt version, and supersession history;
- filters by time, capability, goal, data class, and intelligence.

#### Memory

- search and inspect memories with provenance;
- distinguish observation, interpretation, belief, and owner-confirmed fact;
- correct, dispute, expire, delete, or change retention where permitted;
- show which conversations, events, and decisions used a memory.

#### Runs and decisions

For each reasoning or automation run, show:

- trigger and selected inputs;
- retrieval manifest and evidence IDs;
- model/provider, prompt, policy, code, and schema versions;
- concise structured rationale, assumptions, uncertainty, alternatives, and selected plan;
- tool/capability requests, policy decisions, approvals, credential-lease references, and action receipts;
- costs, latency, external disclosures, retries, failures, and observed outcomes.

This is an auditable decision record, not raw hidden chain-of-thought. Melloa must not rely on private internal reasoning traces for reproducibility or trust.

#### Media

- camera-event frames and clips retained under policy;
- event boundaries, interpretation confidence, retention expiry, and disclosure history;
- correction and deletion controls;
- camera health and missing-interval visibility.

#### Operations

- application, worker, database, queue, provider, camera, storage, backup, and deployment health;
- costs, request budgets, rate limits, loop breakers, and external data disclosures;
- installed capabilities, grants, policies, quiet hours, notification budgets, and pending approvals;
- recent migrations, software versions, canaries, rollbacks, and recovery evidence.

#### Guardian boundary

The console may display Guardian mode and health through a read-only/status contract. High-impact Guardian changes use a separately authenticated owner path controlled by the Guardian repository and host. The ordinary Melloa backend cannot grant itself Guardian authority.

### Authentication and network exposure

- Bind the console/API only to loopback, LAN, or the private network; no public ingress in V1.
- Require application authentication; Tailscale or LAN membership alone is insufficient.
- Use secure, short-lived sessions and CSRF protection for browser actions.
- Require recent reauthentication for high-impact approvals, exports, deletions, policy changes, and Guardian handoff.
- Keep a local recovery path when the private-network control plane is unavailable.
- Redact sensitive content from browser notifications, logs, telemetry labels, and URL parameters.

The exact V1 authentication implementation should be selected during implementation from maintained components that support local/private deployment and strong owner authentication. The domain contract depends on an authenticated owner principal, not one identity vendor.

### Client adapter contract

```text
ClientAdapter
  receive() -> authenticated inbound message event
  send(authorized message) -> delivery result
  edit/delete/reply() -> optional transport operations
  fetch_attachment(reference) -> quarantined blob
  capabilities() -> media, limits, interactivity, security profile
  health() -> status and rate limits
```

The domain sees normalized messages and delivery records. Client-specific identifiers stay in adapter metadata.

### Telegram secondary adapter

#### Processing

1. Call `getUpdates` with a positive long-poll timeout.
2. Validate update schema and size.
3. Confirm the exact paired owner user and private chat before downloading attachments.
4. Persist an immutable inbound observation and deduplication key using `update_id`.
5. Quarantine and hash permitted attachments.
6. Append the normalized message to the canonical conversation.
7. Pass every side-effecting request through the capability broker.
8. Advance the offset only after durable ingestion.

#### Default restrictions

| Data or action | Telegram default |
|---|---|
| Ordinary owner conversation | allowed when channel sensitivity policy permits |
| Concise reminders, status, and approvals | allowed within notification and preview policy |
| Raw room frames or clips | denied unless explicitly requested and approved for that data class |
| Highly sensitive memory detail | minimal notification with private-console link |
| Secrets and recovery codes | always denied |
| Guardian root changes | not authorized solely through Telegram |
| Full export or archive | never attached; use private/local transfer |

Telegram outages or disablement must not prevent local conversation, sensing, memory, reasoning, or Guardian operation.

### Alternatives

- **Public web application:** rejected for V1 because it adds internet ingress, public authentication, rate-limiting, certificate, patching, and incident-response burdens without need.
- **Telegram as the primary UI:** rejected because it cannot provide the required high-trust inspection, media, provenance, policy, and operations experience.
- **Native mobile application:** valuable later for local authentication, HealthKit, notifications, and device integration, but unnecessary before the conversation and client contracts stabilize.
- **Matrix or another messaging system:** possible future adapters; they do not replace the first-party console.

### Failure modes

- **Console unavailable:** core ingestion and queued work continue; CLI and Guardian paths remain available; no authorization bypass.
- **Session theft:** revoke sessions, require reauthentication, preserve audit, and keep Guardian credentials separate.
- **Telegram token leak:** disable adapter egress, revoke token, rotate broker secret, and re-pair.
- **Duplicate message:** deduplicate using canonical/client IDs and idempotency keys.
- **Malicious attachment:** reject or quarantine before parser/model access; treat contents as untrusted data.
- **Incorrect decision explanation:** retain evidence and deterministic metadata; structured rationale is a model-produced artifact and not privileged truth.

### Build now

- Canonical thread/message/turn/delivery records and channel-independent application use cases.
- Private Owner Console shell and authenticated conversation.
- Timeline, provenance, memory correction, run/decision, media, health, cost, and disclosure views sufficient for V1 milestones.
- Read-only Guardian status integration and clear handoff to the separate Guardian control path.
- Fake client adapter and deterministic fixtures for development and replay.
- Optional Telegram long-polling adapter with pairing, allowlist, durable offsets, attachment quarantine, and conservative sensitivity policy.

### Design for

- Additional messaging clients, native mobile applications, voice, local displays, and accessibility features.
- Stronger passkey/hardware-backed authentication and delegated multi-device sessions.
- Multiple persistent intelligences and explicitly partitioned conversations.
- Client-specific redaction, notification preview, and offline synchronization policies.

### Defer

- Public web ingress, multi-user tenancy, group bots, third-party recipients, native mobile release, and raw hidden chain-of-thought capture.

---

<a id="doc-13-self-modification-git-ci"></a>

## Self-modification, Git, and delivery architecture

### Purpose

Make software creation and system evolution a controlled, observable capability rather than a privileged exception. Melli may identify a need, implement a change, and evaluate its effects, but it must not gain the authority to rewrite the controls that bound it.

### The five classes of change

Melloa must not use the vague phrase “self-modification” for all adaptation. The control level depends on what changes.

| Class | Examples | Default V1 authority | Required evidence |
|---|---|---|---|
| Runtime learning | new memory, confidence update, intervention outcome, temporary threshold | autonomous within retention and epistemic policy | provenance, validation, correction path |
| Configuration evolution | prompt route, schedule, low-risk feature flag, notification budget | autonomous only for bounded/reversible settings; otherwise approval | typed diff, bounds, rollback value, evaluation window |
| Software evolution | application code, schema-compatible adapter, dashboard | autonomous proposal and implementation; merge/deploy according to risk | tests, replay eval, security scan, review, canary, rollback |
| Infrastructure evolution | new service, network rule, database, cloud resource | proposal only in V1; owner approves exact plan | IaC plan, cost bound, threat impact, recovery plan |
| Governance evolution | policy engine, permission grant, Guardian, identity root, approval rules | never autonomous | independent owner-controlled path and human review |

A model may recommend any class. Recommendation is not authority.

### Lifecycle

```text
need or hypothesis
  -> change proposal
  -> policy and impact classification
  -> isolated worktree/sandbox
  -> implementation
  -> deterministic tests + replay + agent evals
  -> dependency/security/license checks
  -> pull request with evidence
  -> risk-dependent review gate
  -> staging
  -> limited canary
  -> observe outcome and regressions
  -> promote, revise, or roll back
```

The proposal is a durable object containing purpose, affected goals, predicted benefit, data/permission changes, implementation plan, evaluation plan, cost ceiling, expiry/review date, and rollback procedure. “The code passed tests” does not establish that the intervention helped the owner.

### Autonomy matrix

| Change | Melli may implement? | Melli may merge? | Melli may deploy? |
|---|---:|---:|---:|
| Documentation or tests with no runtime effect | yes | yes after CI, subject to repository rules | n/a |
| Reversible internal dashboard | yes | yes after CI and policy | canary within preset resource/egress budget |
| Prompt/template update | yes | after replay/eval thresholds | canary with automatic rollback |
| New read-only capability using an already granted scope | yes | owner or policy depending sensitivity | limited canary |
| New outbound message type | yes | owner review | only after exact recipient/content policy |
| Database additive migration | yes | owner review in V1 | supervised, with backup/rehearsal |
| Destructive migration | proposal only | owner | owner-supervised |
| New public ingress, IAM, credential scope, or spend authority | proposal only | owner | owner-controlled infrastructure path |
| Guardian, policy root, audit deletion, or kill-switch change | no autonomous implementation in protected trust domain | owner-only | owner-only |

The owner may later relax gates for proven classes, but policy changes themselves remain governed.

### Development sandbox

Generated code runs in a disposable environment with:

- rootless user namespace;
- read-only base image and bounded writable scratch volume;
- no host Docker socket, home directory, SSH agent, keyring, camera network, or production database credentials;
- seccomp/AppArmor and dropped Linux capabilities;
- CPU, memory, process, disk, wall-clock, token, and cost quotas;
- default-deny egress with temporary destination-specific leases;
- synthetic or explicitly approved replay data rather than live personal data by default;
- immutable input manifest and captured output hashes.

Docker rootless mode reduces daemon and container privileges, but it is not a complete hostile-code boundary. [S21](#S21) When generated code execution is enabled, use gVisor for an additional userspace-kernel boundary where compatible. [S22](#S22) Firecracker microVMs are a later option for higher-risk, multi-tenant, or stronger kernel-isolation requirements; they add image, networking, startup, and operational complexity. [S56](#S56)

### Git model

#### Repositories and trust domains

- `melloa` is the main monorepo for core, capabilities, schemas, docs, policies that the autonomous plane may propose changes to, evaluations, and deployment manifests.
- `melloa-guardian` is a separate, owner-controlled repository or at minimum a separately protected trust domain. Autonomous credentials cannot push, approve, or modify its deployment.
- Personal configuration and encrypted secrets may live in a private deployment repository, distinct from the public upstream project.

#### Branch and review flow

1. Create a disposable Git worktree from a pinned clean base commit.
2. Use a branch named for a durable change ID, not an opaque agent session.
3. Commit small, reviewable changes and include generated-by metadata in a trailer, without pretending the model is a legal identity.
4. Open a pull request containing proposal, risk class, data-flow change, tests/evals, cost effect, migration and rollback notes.
5. Required checks and CODEOWNERS protect sensitive paths.
6. Merge through a server-side protected branch/ruleset; the agent cannot bypass checks. GitHub rulesets can impose branch/tag protections and required workflows. [S39](#S39)
7. Produce a versioned artifact, SBOM, checksums, and provenance record.
8. Deploy only the exact reviewed artifact digest.

Third-party GitHub Actions should be pinned to full commit SHAs; mutable tags are not a sufficient supply-chain boundary. [S63](#S63)

### CI/CD gates

#### Deterministic gates

- formatting, linting, type checking, unit tests;
- schema compatibility and migration checks;
- dependency vulnerability and license scan;
- secret scan;
- container build with non-root user and minimal base;
- software bill of materials;
- policy tests and forbidden-path checks;
- reproducible or at least traceable build metadata;
- signature/attestation verification before deployment.

SLSA provides a useful vocabulary for increasing build provenance assurance, and Sigstore/cosign can sign and verify artifacts without inventing a bespoke signing protocol. [S37](#S37) [S38](#S38)

#### Probabilistic gates

- replay of representative historical event traces;
- prompt/model regression suite;
- adversarial prompt-injection cases;
- expected tool-call and policy-decision comparisons;
- cost, latency, and proactivity-budget deltas;
- multiple stochastic runs with distributions rather than a single pass/fail sample;
- manual inspection of a small redacted sample for high-impact changes.

A probabilistic gate may block promotion, but it cannot replace deterministic authorization.

### Deployment and rollback

- Staging uses a scrubbed/replayed dataset and separate credentials.
- Canary targets one bounded workflow, plugin, or percentage of eligible events—not the whole system.
- Promotion is based on predeclared success and guardrail metrics.
- Automatic rollback triggers include policy-denial spikes, action error rate, cost/latency ceiling, notification excess, malformed output, or owner emergency stop.
- Retain the previous image and configuration.
- Database changes use expand/migrate/contract. Code rollback is never assumed to reverse a destructive migration.
- Every rollout has an expiry/review task; experiments do not silently become permanent infrastructure.

### Architecture-change discipline

A change that alters trust boundaries, durable schemas, primary stores, public interfaces, or operational ownership requires an ADR. The agent may draft the ADR and competing alternatives. The owner approves decisions that alter governance or irreversible architecture.

### Failure modes

- **Generated tests fit the implementation rather than the requirement:** independent replay/evaluation and owner-visible acceptance criteria.
- **Sandbox escape:** no production credentials or host control, gVisor for hostile workloads, rapid Guardian shutdown, patched runtime.
- **Dependency substitution or malicious package:** lockfiles, private allowlist where useful, provenance, SBOM, network restriction, review new dependencies.
- **CI compromise:** pinned actions, least-privilege tokens, protected environments, artifact signature verification.
- **Canary has no representative data:** explicit eligibility and minimum sample threshold; do not infer success from silence.
- **Rollback fails after schema change:** rehearse migration, snapshot first, expand/contract pattern, restore procedure.
- **Agent optimizes for passing its own evals:** independently maintained guardrails and owner feedback; periodically refresh hidden test cases.

### Build now

- Durable change proposal schema and risk classification.
- Protected Git flow, CODEOWNERS, required checks, pinned CI actions.
- Deterministic test/eval manifest and artifact digest deployment.
- Staging and rollback for ordinary application changes.
- Explicit prohibition on autonomous Guardian/governance/IAM changes.

### Design for

- gVisor-backed generated-code runner, signed artifacts, SBOMs, canary controller, and replay-driven promotion.
- Provider-neutral coding-agent adapter.
- A capability for generating software that receives narrowly scoped build/test resources, not host administration.

### Defer

- Fully autonomous merge/deployment of high-impact changes, Firecracker fleet, production cloud resource creation, autonomous dependency upgrades without evidence, and any agent path to modify the Guardian.

---

<a id="doc-14-deployment-networking-infrastructure"></a>

## Deployment, networking, and infrastructure

### Purpose

Provide one reproducible, secure-enough deployment path for a technically sophisticated owner without turning a one-person system into a miniature cloud platform.

### Blessed V1 deployment

Melloa runs on one wired Linux mini-PC in the owner’s home. Rootless Docker Compose manages application containers; host-owned systemd units manage the Guardian, firewall, encrypted-secret bootstrap, backups, and selected health checks. Ansible establishes the host. No public domain or public reverse proxy is required.

Docker Compose is an appropriate declarative model for a small multi-container application and supports services, networks, volumes, configs, and secrets without a cluster control plane. [S40](#S40) Ansible supplies idempotent host configuration and operational playbooks. [S41](#S41)

### Physical and logical topology

| Zone | Members | Trust | Connectivity |
|---|---|---|---|
| Owner/admin | owner laptop/phone over local LAN or Tailscale | high, separately authenticated | Owner Console, admin API, Guardian SSH/CLI |
| Melloa core | core, workers, Postgres, local observability | trusted application, not root authority | selected outbound APIs; camera/perception; private clients |
| Perception | Frigate/go2rtc/detectors | handles untrusted media | camera VLAN ingress; structured candidate output to core |
| Camera VLAN | PoE camera(s) | low-trust embedded devices | NTP/DNS if needed; RTSP/ONVIF only to perception; no internet |
| Generated-code sandbox | disposable workloads | hostile-by-default | no ingress; default-deny egress; test fixtures only |
| Guardian | root-owned host unit and owner CLI | highest local control plane | can control services/firewall/credentials; not reachable by Melli capability API |
| External providers | LLM APIs, Telegram, GitHub, backup target | outside trust boundary | explicit TLS destinations and scoped credentials |

Tailscale is the convenient private-access default, using WireGuard-based encrypted connections and an identity/control layer. [S54](#S54) Melloa must not make Tailscale identity semantics part of domain contracts; native WireGuard or another private network is an escape path. WireGuard itself is a compact VPN protocol rather than an application authorization system. [S55](#S55)

### Host baseline

- Debian stable or Ubuntu LTS on x86-64.
- Full-disk encryption where unattended boot requirements permit, with documented recovery key storage.
- Separate unprivileged service users for rootless Docker and backup operations.
- SSH keys/passkeys, no password login, no routine root login.
- Host firewall default-deny inbound except SSH/Tailscale and explicitly required local services.
- Automatic security update download; controlled installation/reboot with health verification.
- SMART/NVMe monitoring, disk-space alerts, time synchronization, log rotation.
- UPS for areas with unreliable power or where camera/event continuity matters.

### Container layout

Suggested Compose projects or profiles:

```text
core:       melloa-core, melloa-web, melloa-worker, postgres
perception: frigate, go2rtc, detector adapter
observe:    otel-collector, optional local metrics/log UI
models:     optional local model server
sandbox:    created on demand, isolated network, disposable volumes
```

Rules:

- Pin images by digest for deployment; track human-readable version separately.
- Run as non-root, read-only root filesystem where practical, minimal capabilities, health checks, resource limits.
- Use named volumes with documented ownership and backup inclusion.
- Do not mount `/var/run/docker.sock` into an agent-accessible container.
- Do not make the Postgres port reachable from the LAN.
- Split networks so perception cannot access model-provider credentials and sandbox cannot access core state.
- Store generated artifacts in content-addressed volumes and pass references, not ambient shared directories.

### Ingress and egress matrix

| Source | Destination | V1 policy |
|---|---|---|
| Owner device | Owner Console/private API | Tailscale/LAN only; strong application authentication |
| Telegram cloud | host | none for long polling; core initiates outbound HTTPS |
| Core | Telegram Bot API | allow exact service; rate/cost/audit controls |
| Core/model gateway | approved model providers | destination and data-class policy; TLS; recorded egress manifest |
| Perception | camera | RTSP/ONVIF from camera VLAN only |
| Camera | internet | deny |
| Camera | core DB | deny |
| Sandbox | internet | deny by default; short-lived allowlist lease when tests require it |
| Sandbox | production DB/secrets | deny |
| Backup process | B2/offsite target | scheduled, scoped credentials, append/retention protection where possible |
| Melloa containers | Guardian control socket/credentials | deny |

Domain allowlists are an operational aid, not a complete defense: provider CDNs and DNS can change. The enforced unit should be a brokered capability plus network constraints, with fail-closed behavior for sensitive paths.

### Data volumes

- `postgres-data`: primary state; encrypted disk; logical backups and optional physical/WAL plan later.
- `blob-store`: content-addressed observations, clips, artifacts; per-object metadata and retention.
- `model-cache`: rebuildable, not part of irreplaceable backup.
- `telemetry`: local, redacted, short retention.
- `quarantine`: no-exec, size bounded, auto-expiring untrusted attachments.
- `exports`: owner-triggered, encrypted or protected, time-limited staging.

Each volume has an owner, sensitivity class, retention, backup policy, and restore test. “Persistent volume” is not synonymous with “must back up.”

### Cloud footprint

V1 cloud dependencies are services, not a second runtime:

- one or more model-provider APIs;
- Telegram Bot API;
- GitHub or another Git forge/CI service;
- Backblaze B2 or equivalent encrypted offsite backup;
- optional Tailscale coordination.

Melloa does not require a public domain, cloud VM, managed database, Kubernetes cluster, object-storage gateway, or cloud control plane. Cloud services may be replaced through adapters and exported data.

### Infrastructure as code

#### Build now

- Docker Compose for application topology.
- Ansible for OS packages, users, firewall, Docker rootless setup, directories, systemd Guardian, backup timers, and health verification.
- SOPS-encrypted deployment configuration with age recipients.
- Versioned migration and rollback commands.

#### Add OpenTofu when

Use OpenTofu only after Melloa owns nontrivial cloud resources whose lifecycle must be planned and reviewed: multiple environments, IAM roles, networking, compute, managed storage, or infrastructure dependencies. OpenTofu maintains declarative infrastructure state and planning, but a state file and cloud credentials are themselves sensitive operational assets. [S57](#S57)

#### Do not add Kubernetes merely because

- there are several containers;
- self-healing sounds desirable;
- a future multi-node topology is imaginable;
- generated services might exist someday.

Revisit a cluster orchestrator when there are multiple independently operated nodes, strict scheduling/isolation needs, many deployable services, or uptime requirements that exceed restore-on-one-host. Until then, it would create more control-plane state than value.

### Remote administration

- Primary: owner device over Tailscale/private LAN.
- Recovery: local keyboard/console or physical access.
- SSH restricted by host firewall and keys; no SSH capability is exposed to Melli.
- Guardian commands require owner-controlled credentials and may require a local confirmation for the highest-impact changes.
- The Owner Console and sensitive APIs bind only to loopback/private interfaces and use application authentication in addition to network membership.

### Growth path

1. **One host:** core, DB, perception, optional local model.
2. **Edge camera node:** move perception near the camera; signed event/blob upload; retain core authority centrally.
3. **Compute node:** move local model/sandbox to GPU-capable machine; use narrow APIs and workload identity.
4. **Second-site backup/recovery host:** tested restore, not active-active complexity.
5. **Distributed control only if justified:** introduce durable messaging/workflow engine and workload identities behind existing ports.

Migration thresholds must be measured. Examples: sustained job backlog beyond recovery objective; more than three independently upgraded nodes; inability to isolate noisy workloads; or availability requirements that a one-host restore cannot satisfy.

### Failure modes

- **Single-host failure:** deliberate V1 trade-off; clean-machine restore and spare/storage plan matter more than pseudo-HA.
- **Tailscale/control-plane outage:** local LAN and console still work; WireGuard-compatible migration path.
- **Firewall misconfiguration:** Guardian recovery console and versioned rules; apply with rollback timer.
- **Compose upgrade breaks state:** pin versions/digests, preflight backup, staging on restored data.
- **Disk fills from media/telemetry:** hard quotas, retention worker, reserved database headroom, alerts at multiple thresholds.
- **Compromised camera:** isolated VLAN, no internet, unique credentials, firmware updates, no trust in camera analytics.
- **Cloud credential compromise:** scoped token, provider-side limit, Guardian revocation, audit and rotation runbook.
- **DNS/provider change breaks allowlist:** health signal and controlled update, never silently broaden to unrestricted egress.

### Decision

One excellent local deployment is the product baseline. Portability comes from documented data formats, adapters, and explicit contracts—not by supporting every operating system and orchestrator in V1.

---

<a id="doc-15-observability-reliability-dr"></a>

## Observability, reliability, and disaster recovery

### Purpose

Make Melloa inspectable enough to trust, operable enough for one engineer to maintain, and recoverable when ordinary infrastructure and probabilistic AI fail.

### Observability questions

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

### Telemetry architecture

OpenTelemetry supplies vendor-neutral APIs and data models for traces, metrics, and logs, and is an appropriate compatibility layer around application telemetry. [S44](#S44)

#### Three distinct records

1. **Domain/audit ledger:** durable, security-relevant, append-oriented records of observations, interpretations, decisions, actions, approvals, changes, and external disclosures. This is not optional telemetry.
2. **Operational telemetry:** traces, metrics, and structured logs for latency, error, resource use, queue health, and dependency behavior; shorter retention and aggressive redaction.
3. **Evaluation evidence:** replay datasets, expected behaviors, score distributions, intervention outcomes, and release decisions.

A SaaS tracing product must not become the only copy of the audit trail or receive raw personal prompts by default.

### Trace model

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

### Core metrics

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

### V1 service objectives

These are owner-facing objectives, not enterprise promises:

- 99% of accepted Telegram messages durably ingested within 30 seconds while Telegram and internet are available.
- 95% of local camera candidate events either interpreted or explicitly expired within 10 minutes.
- Dangerous action authorization fails closed on policy/broker error.
- No proactive message exceeds the configured daily and quiet-hour budgets.
- Backup age remains under 24 hours; monthly restore drill succeeds.
- Cost accounting covers at least 99% of model and priced capability calls by count.
- Audit linkage exists for every executed side effect.

Targets should be adjusted from observed usefulness rather than gamed as vanity SLOs.

### Reliability patterns

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

### Failure and recovery matrix

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

### Backup architecture

Use `restic` for encrypted, deduplicated repositories and integrity checking across local and remote backends. [S42](#S42)

#### Data tiers

- **Irreplaceable:** Postgres logical data, policies, goals, corrections, audit, change history, encryption metadata, deployment config, source repositories.
- **Valuable but reconstructable:** selected event media, evaluation corpora, generated artifacts.
- **Rebuildable:** embeddings, indexes, model caches, downloaded images, operational metrics.
- **Intentionally ephemeral:** ring buffers, sandbox files, quarantine after expiry, transient queues once durable state exists.

#### V1 schedule

- Nightly database-consistent logical dump plus schema/role manifest.
- Nightly `restic` snapshot to attached/removable local storage.
- Nightly or daily encrypted offsite snapshot to B2/equivalent after local verification.
- Weekly extended integrity check and backup-age report.
- Monthly restore on a clean VM/spare host, including DB migration and a representative blob/audit lookup.
- Quarterly recovery-key and owner-account recovery review.

Backblaze B2’s published storage price is a useful low-cost benchmark, but pricing and egress policy must be rechecked before deployment. [S43](#S43)

#### Recovery objectives

For V1:

- **RPO:** 24 hours for ordinary durable state; lower only after WAL/PITR is justified.
- **RTO:** 4 hours to a functioning core on prepared hardware after a successful restore drill.
- **Camera continuity:** no guarantee during host/camera failure; missed intervals are recorded explicitly.

When Melloa becomes relied upon for urgent or safety-relevant functions, reduce these objectives through physical replicas/PITR and tested failover rather than optimistic documentation.

### Restore procedure outline

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

### Audit protection

- Separate append permissions from correction/annotation permissions.
- Hash-chain or periodically checkpoint audit batches to detect accidental/tampered deletion; do not overclaim blockchain-grade immutability.
- Export signed/checksummed audit summaries to the backup trust domain.
- Prevent autonomous workloads from changing retention or deleting security records.
- Record Guardian actions locally and in an owner-visible location independent of the core when possible.

### Privacy and telemetry

- Default to local collection.
- Do not put raw prompts, room images, message bodies, secrets, or full tool payloads in labels/log lines.
- Apply sensitivity-aware sampling and retention.
- Keep high-cardinality personal identifiers out of metrics.
- Redaction happens before export, not merely in a dashboard.
- Debug capture requires a bounded, owner-visible temporary mode with automatic expiry.

### Build now

- Domain/audit schema, structured logs, run/correlation IDs, model/cost/action metrics.
- Local OpenTelemetry collector or compatible export path.
- Owner Console health, structured run/decision explorer, CLI diagnostics, and actionable alerts.
- Nightly encrypted local/offsite backup and a clean-machine restore drill.
- Run ceilings, queue quotas, provider circuits, and failure-visible dead-letter state.

### Design for

- PITR, stronger audit checkpointing, independent recovery host, and privacy-preserving external observability.
- Per-capability SLOs and chaos/replay drills.

### Defer

- Full high-availability database cluster, multi-region failover, raw personal telemetry in third-party SaaS, and “self-healing” that can conceal data corruption or bad policy.

---

<a id="doc-16-privacy-retention-export-cost"></a>

## Privacy, retention, ownership, and cost

### Purpose

Maximize useful personal context while minimizing unnecessary exposure outside the owner’s trust boundary. Privacy is expressed through data classification, routing, retention, capability scope, and inspectable disclosure—not by pretending that useful observation requires no access.

### Privacy stance

Melloa should say plainly when a capability needs sensitive data. Disabling camera, health, browser, or location access disables the experiences that depend on them. The architecture must still make collection narrow, processing local where adequate, external transmission explicit, retention bounded, and deletion/export real.

### Data sensitivity classes

| Class | Examples | Default storage | Default external-model policy |
|---|---|---|---|
| Public | public documentation, open-source code, public web pages | local, normal encryption | any approved provider |
| Internal | system health, non-personal configuration, synthetic tests | local | approved providers if needed |
| Personal | ordinary owner messages, calendar titles, routine summaries | encrypted local | approved provider with no-training/default API terms, task-minimized context |
| Sensitive | detailed health, financial records, private email/files, precise location | encrypted local with narrower access | local preferred; explicit provider/data-purpose route required |
| Highly sensitive | raw private-room media, intimate health, credentials metadata, private third-party content | separately controlled local store, short retention | deny by default; explicit per-capability exception |
| Device-only | recovery secrets, private keys, Guardian credentials, selected raw media | hardware/OS-backed or owner-controlled local path | never leave device/trust boundary |

Class is attached to each object and inherited conservatively by derived data. A summary can remain sensitive even when names are removed. Classification changes are audited.

### Processing and disclosure model

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

API terms differ and change. OpenAI states that API data is not used to train its models by default; retention controls vary by endpoint/account. [S59](#S59) Anthropic, Google, and Mistral also publish distinct commercial/API data-use and retention terms, so eligibility must be represented as versioned provider policy rather than assumed from brand reputation. [S60](#S60) [S61](#S61) [S62](#S62)

### Collection principles

- Collect for a named capability, goal, experiment, security need, or owner request.
- Preserve provenance and consent/authority context.
- Prefer event-triggered capture over continuous archival.
- Separate third-party data from owner-only data and apply stricter sharing rules.
- Do not infer “not observed” as “did not happen.”
- Do not silently expand a data source’s purpose when a new model/plugin is installed.
- Make disabled, degraded, or partially observed periods visible.

### Retention schedule

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

### Camera storage arithmetic

Illustrative H.264/H.265-equivalent average bit rates, excluding overhead:

- 1080p at 2 Mbit/s continuously: about **21.6 GB/day** or **648 GB/30 days**.
- 1080p at 4 Mbit/s continuously: about **43.2 GB/day** or **1.30 TB/30 days**.
- 100 selected 15-second clips/day at 2 Mbit/s: about **0.375 GB/day** or **11.25 GB/30 days**.

Actual rates vary with codec, frame rate, scene complexity, night noise, and camera settings. The roughly 58× reduction in the example explains why local event segmentation is an architectural requirement rather than merely a cost optimization.

### Correction and deletion

- Corrections append a new assertion that supersedes or disputes the old one; provenance remains inspectable.
- Derived beliefs, summaries, embeddings, and decisions affected by a correction are queued for re-evaluation.
- Deletion supports scope: raw object, source integration, time range, memory claim, or full export-and-delete.
- Security/audit records may retain a minimal non-content tombstone when deletion itself must be accountable.
- External providers and source systems have independent retention; Melloa reports what it can and cannot delete.
- A “forget” request cannot honestly erase a fact from already generated human decisions or immutable offline backups before expiry.

### Data ownership and export

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

The current M1 preview implements the first validated slice of this path for canonical owner records: `melloa export-mvp` writes a manifest, copied JSON Schemas, JSONL conversation records, a redacted model-activity report, memory-inspection records, and `checksums.sha256`; `melloa import-validate` verifies checksums, schema readability, and basic referential integrity without mutating a database. The authenticated Owner Console can also request a ZIP from the running core, which captures the live process-local or PostgreSQL-backed stores instead of composing a separate CLI runtime. That route requires a session-bound CSRF proof and recent owner authentication, validates the staged bundle before serving it, uses a content-disposition attachment without owner data in its filename, and removes temporary server-side files after delivery. Model activity preserves route, token, cost, timing, and external-disclosure evidence without duplicating prompts or raw model output. Memory-inspection rows preserve deleted-content tombstone and rebuild-work evidence without restoring the deleted assertion value. Both base paths truthfully mark the bundle as unencrypted and exclude blobs and logical SQL snapshots.

For owner-managed storage or transfer, `melloa export-encrypt` can wrap an already validated bundle in the versioned `melloa.encrypted-owner-export-package` format. V1 uses AES-256-GCM with fixed, bounded scrypt parameters and requires the passphrase through an exact mode-`0600` regular file; `melloa export-decrypt-validate` authenticates and validates the inner bundle without importing it. The package header intentionally exposes format/version, creation time, export ID, KDF parameters, and ciphertext/plaintext sizes and hash, but not canonical record content. The browser download remains an unencrypted ZIP, and the wrapper is neither a signature nor a backup system. Blob export, logical database snapshots, signatures, and a real import/migration executor remain V1 work rather than implied by this package.

### Cost model assumptions

All figures are planning ranges in **2026 pounds sterling**, excluding developer labour, taxes/import differences, and internet already purchased. Model/provider pricing changes quickly and must be rechecked. OpenAI’s current public API pricing illustrates the large spread between small and frontier model tiers and the savings available for batch processing; it should not be treated as a commitment to one provider. [S35](#S35)

#### Hardware acquisition

| Component | Planning range |
|---|---:|
| x86 mini-PC, 16–32 GB RAM, 1 TB NVMe | £250–£500 |
| PoE ONVIF camera | £80–£250 |
| PoE injector/switch, cabling, mount | £30–£120 |
| USB backup drive | £70–£150 |
| UPS optional | £80–£180 |
| **Typical initial total** | **£510–£1,200** |

#### Electricity

Using Ofgem’s July–September 2026 average electricity unit-rate benchmark of 26.11 pence/kWh for Great Britain: [S45](#S45)

| Average continuous load | kWh/month (30 days) | Approx. cost/month |
|---:|---:|---:|
| 15 W | 10.8 | £2.82 |
| 30 W | 21.6 | £5.64 |
| 60 W | 43.2 | £11.28 |

A discrete local GPU can dominate power and hardware amortization; purchase it only after measured workloads justify it.

#### Operating tiers

| Tier | Shape | Monthly planning range | Principal drivers |
|---|---|---:|---|
| A — MVP | one camera, local detection, Telegram, modest daily cloud reasoning | **£15–£70** | API inference, offsite backup, electricity |
| B — serious daily use | several integrations, daily/weekly reasoning, richer model routing | **£60–£300** | frontier calls, context volume, coding/eval runs |
| C — heavy personal AI | multiple sensors, frequent multimodal/coding agents, local accelerator | **£300–£1,200** | inference, hardware amortization, media/storage, evaluation |
| D — extreme setup | many sensors, extensive autonomous development, high-end local/cloud compute | **£1,200–£6,000+** | frontier multimodal/video, GPU/cloud compute, operational sprawl |

A disciplined first year, including hardware, is approximately **£800–£2,100**. Model-heavy experiments can exceed this easily.

#### Storage and backup

Backblaze B2 currently publishes a benchmark price of roughly **US$6.95 per TB-month**, with policy details that must be reverified. [S43](#S43) For V1, API inference usually costs more than a few tens of gigabytes of encrypted backup; continuous video retention reverses that relationship.

#### What changes cost by 10×

1. Calling a frontier model for every sensor tick instead of filtering and batching locally.
2. Sending video or large image sequences to cloud multimodal APIs instead of selected evidence.
3. Repeatedly injecting years of raw history instead of retrieval manifests and summaries.
4. Running autonomous coding/review loops without step, token, and retry ceilings.
5. Retaining continuous multi-camera video rather than event clips.
6. Purchasing a high-end GPU before utilization is known.
7. Adding observability SaaS with raw/high-cardinality telemetry.

### Budgets and controls

- Per-call, per-run, per-capability, daily, and monthly limits.
- Soft alert thresholds before hard stops.
- Separate experimentation budget from ordinary service budget.
- Estimated maximum cost included in action/change proposals.
- Batch/off-peak routes for periodic work where latency is unimportant.
- No silent failover to a substantially more expensive model.
- Owner dashboard allocates spend to goal, integration, model route, and intervention.
- Stop or degrade low-value periodic loops before blocking owner-requested essential work.

### Build now

- Sensitivity classification and disclosure manifests.
- Retention/deletion worker and owner-visible policy.
- Export format with integrity validation.
- Cost accounting and hard ceilings.
- Camera ring/selected-clip policy; no continuous archive.

### Design for

- Provider-specific regional/ZDR eligibility, hardware-backed encryption keys, third-party consent labels, legal jurisdiction metadata, and privacy-preserving local transformation.

### Defer

- Permanent raw life-log, cloud video archive, proprietary memory store, blanket “anonymization” claims, and an expensive local GPU without measured demand.

---

<a id="doc-17-testing-evaluation-simulation"></a>

## Testing, evaluation, and simulation

### Purpose

Test deterministic software, probabilistic reasoning, policy boundaries, hardware integrations, and long-term behavioral interventions without pretending they share one pass/fail methodology.

### Test pyramid and evidence types

| Layer | Primary question | Method |
|---|---|---|
| Unit | does a function enforce its invariant? | deterministic fast tests, property tests |
| Contract/schema | can versions and plugins interoperate safely? | JSON Schema/protobuf compatibility, fixtures, consumer tests |
| Integration | do adapters and stores behave with real dependencies? | disposable Postgres, fake/recorded APIs, container tests |
| Policy/security | can an unsafe proposal cross a boundary? | table/property/fuzz tests, adversarial inputs, deny-by-default tests |
| Replay/simulation | would a change behave acceptably on representative history? | deterministic event replay, virtual clock, mocked side effects |
| Agent/model eval | is quality, safety, cost, and latency acceptable statistically? | scenario suite, rubric/model/human graders, repeated samples |
| End-to-end | can a real owner journey complete? | staged system with synthetic and selected consented data |
| Hardware | do camera/network/power paths survive reality? | soak, disconnect, low-light, clock drift, bandwidth tests |
| Disaster recovery | can the system be restored safely? | clean-machine restore and integrity checks |
| Intervention | did an action help the owner? | predeclared outcome, N-of-1/observational analysis, feedback |

### Deterministic software tests

- Domain invariants for provenance, supersession, sensitivity inheritance, and action authorization.
- Job lease/retry/idempotency properties under crashes and duplicates.
- Event schema validation and compatibility fixtures across versions.
- Database migration up/down/forward tests on restored production-shaped data.
- Capability adapter contract tests with malformed, slow, duplicated, and spoofed responses.
- Timezone, DST, clock skew, leap-day, and delayed-event tests.
- Retention/deletion propagation and backup-expiry behavior.
- Cost and quota arithmetic.
- Guardian mode and fail-closed behavior.

Use property-based testing for policy and event invariants; manually enumerated happy paths are insufficient.

### Policy and security testing

Generate combinations of:

- actor/identity and authentication strength;
- capability and action parameters;
- data sensitivity and taint source;
- destination/recipient;
- budget and rate state;
- time/quiet hours;
- active grant/approval and exact action hash;
- Guardian mode;
- compromised or malformed tool output.

Assert that absence, ambiguity, stale approval, or policy-engine failure cannot broaden authority. Maintain regression cases for prompt injection, cross-tenant/identity leakage, path traversal, SSRF, malicious attachment types, encoded instructions, oversized payloads, and tool-output spoofing.

### Agent/model evaluation

Inspect AI is an open-source evaluation framework supporting tasks, solvers, scorers, models, tools, logs, and sandboxed environments; it is a good provider-neutral foundation rather than a proprietary tracing dependency. [S53](#S53)

Each evaluation case specifies:

```text
scenario and source data
expected epistemic behavior (fact/inference/abstention)
allowed tools and exact forbidden effects
required policy outcome
quality rubric and critical errors
maximum tokens/cost/latency/tool steps
acceptable output schema
privacy/disclosure expectation
```

Report distributions over repeated runs, model/version/temperature, confidence intervals where meaningful, and critical-error counts. A single successful sample is not a release gate.

#### Evaluation dimensions

- factual grounding and evidence citation;
- uncertainty calibration and willingness to ask/abstain;
- memory precision/recall and contradiction handling;
- plan quality and goal/policy alignment;
- prompt-injection resistance;
- correct tool choice and minimal authority request;
- policy compliance independent of answer quality;
- token, latency, monetary cost, and external disclosure;
- proactivity usefulness and interruption cost;
- degradation/fallback behavior.

### Replay system

The replay engine is a first-class safety mechanism.

#### Inputs

- versioned canonical events and evidence references;
- a frozen or virtual clock;
- snapshot of goals, policies, grants, and memory visible at the historical time;
- model route or recorded deterministic outputs;
- simulated provider/capability responses;
- random seeds where supported;
- expected outcomes and known corrections.

#### Modes

1. **Exact software replay:** deterministic code and recorded model/tool outputs; catches schema/state regressions.
2. **Counterfactual model replay:** new model/prompt against historical retrieval manifests; no real side effects.
3. **Policy replay:** new policy over historical action proposals.
4. **Failure injection:** timeouts, duplicates, out-of-order events, unavailable provider, full disk, corrupt response.
5. **Behavior simulation:** synthetic user/environment event sequences for workflow coverage, not proof of real-world benefit.

All side effects are replaced with receipts in simulation. The engine records proposed deltas and never writes production memory.

### Golden and adversarial datasets

- Curate small, high-quality cases from owner corrections and real failures, with sensitivity-aware storage.
- Use synthetic public fixtures for open-source CI.
- Keep a withheld owner-private regression set for local release gates.
- Label uncertain cases and grader disagreement; do not force false ground truth.
- Version datasets and document their purpose, provenance, consent, and limitations.
- Refresh adversarial cases so the system cannot merely fit a static injection checklist.

### Camera evaluation

Measure components separately:

- motion/scene segmentation precision and event fragmentation;
- person/object detector precision/recall by lighting and position;
- semantic activity classification with an explicit unknown class;
- time-to-event and frames/cloud calls per useful event;
- false “absence” or identity claims;
- low-light/IR artifacts, occlusion, camera move, pets, visitors, mirrors/screens;
- privacy retention and camera-off behavior.

A camera event becomes trusted only through evidence/provenance, not a headline accuracy percentage.

### Release gates

A change cannot promote when:

- any critical policy/security invariant regresses;
- an executed side effect lacks audit/authorization linkage;
- a schema migration loses or silently changes meaning;
- the critical-error count rises above zero for forbidden actions;
- privacy eligibility broadens without explicit review;
- median/percentile cost exceeds the declared bound without approval;
- proactivity exceeds frequency/quiet-hour constraints;
- backup/restore compatibility is untested for a durable-schema change.

Noncritical quality changes use declared tolerances and trade-off review; one score should not conceal safety or cost regressions.

### Intervention evaluation

A behavioral intervention contains:

- goal and hypothesis;
- target behavior/outcome and guardrails;
- intervention definition and delivery context;
- baseline window;
- planned duration/sample opportunity count;
- confounders and measurement limitations;
- stop conditions and burden budget;
- owner feedback question;
- review decision: continue, modify, stop, or inconclusive.

N-of-1 methods are useful only when repeated measurements, a sufficiently stable/reversible intervention, and meaningful outcome timing are possible. [S46](#S46) Reporting should follow disciplined protocols rather than claiming causal certainty from one before/after observation. [S47](#S47)

For many personal goals, the honest output is “suggestive but confounded.” Avoid randomization when withholding an intervention is unsafe or when the burden exceeds the likely learning value.

### Human evaluation

Owner feedback is scarce and costly. Use it deliberately:

- low-friction correction at the point of error;
- periodic sampled review rather than rating every response;
- explicit usefulness/annoyance controls for proactive actions;
- post-intervention review tied to a hypothesis;
- incident review for trust failures;
- never infer that lack of complaint equals benefit.

### Build now

- Unit/integration/contract/policy tests.
- Deterministic fake model and fake capability adapters.
- Event/policy replay with virtual clock and disabled side effects.
- Small model/prompt regression suite with repeated samples and cost accounting.
- Camera calibration set and monthly restore test.

### Design for

- Inspect AI-based provider-neutral suites, private withheld datasets, failure injection, canary comparison, and intervention-analysis notebooks/reports.

### Defer

- A giant benchmark platform, synthetic “digital twin” claims, automated causal conclusions, and promotion based only on a model-graded quality score.

---

<a id="doc-18-repository-languages-docs-dx"></a>

## Repository architecture, language choices, documentation, and developer experience

### Purpose

Keep one engineer able to understand and evolve Melloa years later, while making the intended public project reproducible and contribution-friendly from the beginning. The source is currently readable but is not open source, and contribution intake remains paused, until the owner adds explicit license terms.

### Repository strategy

Use three repositories with explicit trust roles: the **Melloa application monorepo**, the separately protected **Guardian repository**, and the owner-private **deployment/configuration repository**.

- A monorepo makes cross-cutting schema, policy, capability, replay, documentation, and migration changes reviewable as one commit.
- Separate deployable processes can still come from one codebase.
- The Guardian is separated because repository write authority is a security boundary, not because polyrepos are inherently cleaner.
- A private deployment/config repository holds personal environment values and SOPS-encrypted secrets; the public repository contains safe examples.

### Concrete layout

```text
melloa/
├── apps/
│   ├── core/                 # owner API, application orchestration
│   ├── worker/               # jobs, reflection, retention, indexing
│   ├── cli/                  # owner/developer commands
│   └── web/                  # mandatory private Owner Console
├── domain/
│   ├── identity/
│   ├── events/
│   ├── memory/
│   ├── goals/
│   ├── policy/
│   ├── actions/
│   ├── interventions/
│   └── changes/
├── application/              # use cases; depends on domain and ports
├── ports/                    # model, store, capability, clock, audit contracts
├── adapters/
│   ├── postgres/
│   ├── filesystem/
│   ├── models/
│   ├── telegram/
│   ├── camera/
│   └── observability/
├── capabilities/
│   ├── sdk/
│   ├── telegram/
│   ├── camera/
│   └── examples/
├── schemas/
│   ├── events/
│   ├── capabilities/
│   ├── actions/
│   ├── exports/
│   └── compatibility/
├── policies/
│   ├── defaults/
│   ├── tests/
│   └── examples/
├── prompts/
│   ├── templates/
│   ├── schemas/
│   └── changelog/
├── evals/
│   ├── public/
│   ├── adversarial/
│   └── rubrics/
├── simulations/
│   ├── replay/
│   └── fixtures/
├── infra/
│   ├── compose/
│   ├── ansible/
│   ├── images/
│   └── opentofu/             # added only when justified
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contracts/
│   ├── security/
│   └── hardware/
├── docs/
│   ├── vision/
│   ├── concepts/
│   ├── architecture/
│   ├── security/
│   ├── deployment/
│   ├── hardware/
│   ├── integrations/
│   ├── operations/
│   ├── tutorials/
│   ├── ADRs/
│   └── research/
├── tools/
├── pyproject.toml
├── compose.yaml
├── mkdocs.yml
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE

melloa-guardian/
├── guardian/                 # minimal host controller/CLI
├── systemd/
├── firewall/
├── recovery/
├── ansible/
├── tests/
├── docs/
└── SECURITY.md

melloa-deployment/            # private owner repository
├── inventory/                 # hosts and non-secret topology
├── config/                    # SOPS-encrypted deployment overlays
├── backups/                   # destinations and restore metadata, not backup payloads
├── runbooks/                  # owner-specific operational notes
└── README.md
```

### Dependency rules

1. `domain` imports only standard library and deliberately selected pure schema/value libraries.
2. `application` imports `domain` and `ports`, never concrete adapters.
3. `adapters` implement ports and may import external SDKs.
4. Capability adapters do not import core internals; they communicate through versioned contracts.
5. `apps` compose dependencies and contain transport/bootstrap code, not business rules.
6. `schemas` are versioned and cannot depend on one provider SDK.
7. `evals` and `simulations` may exercise public interfaces but do not become runtime dependencies.
8. Guardian has no dependency on Melli/model logic and accepts no arbitrary “agent command” channel.
9. Cross-domain imports are explicit; circular dependencies fail CI.
10. Every new dependency documents owner, purpose, license, security surface, and removal path.

### Language choices

#### Python as the blessed application language

Use modern Python (3.13+ at implementation time) for domain/application logic, model adapters, data pipelines, evals, and most capability adapters. Reasons:

- strongest current ecosystem for AI/model/vision orchestration;
- rapid schema and integration development;
- shared language between runtime and evaluation tools;
- adequate performance when heavy work is in Postgres, FFmpeg/OpenCV, model runtimes, or separate processes;
- easier contribution than a multilingual core.

Use typing, Pydantic/data classes at boundaries, Ruff, mypy/pyright as selected, explicit async discipline, and profiling before optimization.

#### SQL as a first-class language

PostgreSQL schemas, constraints, indexes, views, row roles, and migrations are architecture. Keep reviewed SQL visible rather than hiding all behavior behind an ORM.

#### Guardian

Start with declarative systemd/nftables/Ansible and a minimal, auditable command wrapper. If a durable binary is justified, use Go for a small statically built owner CLI/daemon. Do not write a sprawling privileged shell framework; do not use Python dependency breadth inside the highest-trust component without need.

#### Add only when the product requires it

- **TypeScript:** mandatory private Owner Console, generated schema clients, and browser tests.
- **Swift:** native iOS app/HealthKit/secure notification client.
- **Rust:** measured need for a high-assurance or high-performance daemon where ecosystem/support justify the cost.
- **C/C++:** existing CV/inference libraries or a profiled bottleneck, not core orchestration.

The blessed core should not require contributors to know five languages.

### APIs and contracts

Within the modular monolith, use typed in-process ports and application use cases. Across processes or trust boundaries:

- JSON over HTTP for owner/client and simple capability administration;
- canonical JSON/JSON Schema for durable event/export and broad plugin interoperability;
- PostgreSQL job/outbox for V1 asynchronous work;
- Unix sockets or loopback HTTP for local privileged helpers only with explicit authentication;
- gRPC/protobuf for high-throughput edge/model services when measurement justifies it;
- MCP only as an adapter for suitable third-party tool servers, never as the internal source of authority.

JSON Schema 2020-12 is a stable, machine-readable contract foundation for open event/plugin payloads. [S11](#S11) If protobuf is introduced, use automated breaking-change checks such as Buf’s compatibility model. [S12](#S12)

### Documentation architecture

Use MkDocs Material with version-controlled Markdown and Mermaid diagrams. Material supports diagram rendering through Mermaid integration while keeping diagrams reviewable as text. [S52](#S52)

Every durable concept gets one canonical page. Documentation categories:

- vision and principles;
- conceptual vocabulary;
- current and target architecture;
- security/privacy threat model;
- integration and capability contracts;
- deployment and hardware guides;
- operations/runbooks;
- tutorials/reference;
- ADRs and rejected ideas;
- research sources and date-sensitive assumptions.

#### Documentation gates

A pull request changing any of these must update its corresponding documentation:

- public schema or capability contract;
- trust boundary, egress, secret, or permission;
- operator procedure or failure mode;
- storage/retention/export behavior;
- user-visible command or policy;
- architecture decision or dependency.

Executable examples and command output are tested where practical. Diagrams must show authority/data boundaries, not decorative service boxes.

### ADR discipline

An ADR contains status, date, context, constraints, considered alternatives, decision, consequences, migration/reversal triggers, and links to evidence. Superseded ADRs remain visible. ADR numbers identify decisions, not implementation tickets.

### Developer experience

The blessed local commands should feel coherent even if implemented through Make/Task/CLI wrappers:

```bash
melloa doctor                 # prerequisites, ports, time, storage, secrets
melloa init                   # safe example config and owner identity
melloa up / down / status
melloa migrate --check
melloa test
melloa eval --suite smoke
melloa replay --scenario ...
melloa audit show --run ...
melloa costs report
melloa backup run / verify
melloa export create
melloa capability list
melloa policy explain <request>
```

Commands print exact changed resources and next recovery step. Destructive commands require an exact scope and produce a receipt. The CLI never hides Docker/Compose/Postgres so completely that an operator cannot diagnose them.

### Open-source baseline

The current publicly readable preview has implemented the compatibility, dependency-source, checksum-manifest, and committed-lock CycloneDX dependency-inventory parts of this baseline. The inventory is neither a signed release nor complete build provenance. The preview has also not met the first item: explicit license selection remains an owner decision, and the preserved conduct-policy proposal has not been adopted, so this is still a target baseline rather than a claim that the repositories are open source.

- OSI-approved license selected before code acceptance.
- `SECURITY.md` with private vulnerability reporting and supported versions.
- Contributor guide, code of conduct, architecture map, dependency rules, and release process.
- Synthetic fixtures; no personal data in issues, tests, or default telemetry.
- Reproducible development container or documented environment, but no mandatory proprietary cloud IDE.
- Signed/checksummed releases, changelog, migration notes, SBOM, and compatibility policy.
- Public roadmap distinguishes committed work from exploration.
- One supported deployment; community alternatives are clearly labeled.

### Naming gate

`Melloa` and `Melli` are the adopted project and intelligence names for implementation. Preliminary research finds an occupied GitHub `melloa` namespace and existing similarly named assistant/AI projects, including MelliLabs, MelloAI, and Project MELLO. [S48](#S48) [S49](#S49) [S50](#S50) [S51](#S51) Before public release, perform jurisdiction-appropriate trademark counsel/search, package/registry/domain/social namespace review, pronunciation/accessibility review, and confusion testing. This is a release gate, not an architecture blocker.

### Build now

- Three-repository trust layout, monorepo dependency checks, Python/SQL/TypeScript toolchains, migration and schema discipline.
- Separate Guardian protection.
- MkDocs/Markdown/Mermaid, ADRs, runbooks, and source register.
- A small coherent CLI and synthetic public fixtures.
- Deterministic committed Python runtime/development/docs/build, npm, and Guardian Go dependency inventory emitted as a no-network CycloneDX CI artifact, with toolchain/provenance exclusions stated explicitly.

### Design for

- Stable capability SDK, generated schema clients, TypeScript/Swift clients, edge services, and compatible export/import.

### Defer

- Polyrepo proliferation, mandatory Nix, generated microservices, a plugin marketplace, and languages introduced without a measured domain need.

---

<a id="doc-19-onboarding-runbooks-roadmap"></a>

## Onboarding, operations, and roadmap

### Purpose

Define the reproducible path from an empty machine to a useful V1, the operational procedures that keep it understandable, and a milestone sequence that validates value before adding autonomy and sensors.

### Prerequisite profiles

#### Minimum setup

- x86-64 Linux machine with 16 GB RAM, 200 GB free SSD, and a reliable network;
- owner laptop/phone on the same private network;
- Git, Ansible, rootless Docker/Compose support;
- one hosted model API key with a small budget;
- A modern browser for the private Owner Console;
- USB or separate local backup target.

No Telegram account, camera, public domain, cloud VM, Kubernetes, GPU, or native app is required for the minimum synthetic/local setup.

#### Recommended setup

- dedicated wired mini-PC, 32 GB RAM, 1 TB NVMe;
- full-disk encryption, UPS, Tailscale/private remote access;
- PoE ONVIF Profile T camera on an isolated VLAN;
- 1–2 TB USB backup disk and encrypted B2/equivalent offsite repository;
- GitHub account/repository with protected main and CI;
- separate provider credentials for development and production.

#### Advanced setup

- separate edge/perception node or GPU/model node;
- managed switch with VLANs and firewall rules;
- hardware-backed owner keys;
- second recovery host, PITR, stricter egress proxy;
- native mobile client or additional capabilities;
- OpenTofu for nontrivial cloud infrastructure.

Advanced is not “better” until requirements justify it.

### Installation journey

The exact commands will evolve with implementation, but the product contract is:

#### 1. Prepare the host

1. Install supported Debian/Ubuntu LTS, set hostname/timezone/NTP, patch it, and enable disk encryption as appropriate.
2. Create an owner admin account and a separate unprivileged Melloa service account.
3. Configure SSH keys and disable password/root remote login.
4. Attach local backup storage and document device identifiers.
5. Install Git and Ansible; run the signed/pinned bootstrap playbook.

#### 2. Establish private access and network zones

1. Join Tailscale or configure the chosen private WireGuard path.
2. Apply host default-deny firewall rules with an automatic rollback timer.
3. Verify the owner can reach the private admin endpoint and local console recovery remains possible.
4. When adding a camera, create the camera VLAN and verify it cannot reach the internet or core database.

#### 3. Clone and inspect

```bash
git clone <melloa-upstream-or-fork>
cd melloa
git verify-commit <release-or-pinned-commit>
less SECURITY.md
less docs/deployment/blessed-v1.md
melloa doctor
```

The installer shows every dependency, port, external endpoint, directory, data class, and credential before changing the host.

#### 4. Initialize owner and deployment configuration

```bash
melloa init --deployment home
melloa identity create-owner
melloa identity create-intelligence --working-name Melli
```

Initialization creates stable IDs, safe sample policy, retention defaults, cost ceilings, quiet hours, and an explicit list of disabled capabilities. It does not invent goals on the owner’s behalf.

#### 5. Configure secrets

1. Generate an age recipient whose private identity is held in the owner OS keyring/offline recovery path.
2. Add a model token through `melloa secret set`; add a Telegram token only when enabling that optional adapter. Secrets produce a SOPS-encrypted file or broker entry.
3. Confirm secrets are absent from process arguments, Git diff, logs, and container images.
4. Configure low provider-side spend limits and narrow API scopes.

#### 6. Start the state layer

```bash
melloa up --profile core --no-actions
melloa migrate --check
melloa migrate apply
melloa status --deep
```

Run in Guardian `no-actions`/offline mode first. Verify Postgres roles, event append, audit linkage, jobs, and schema version.

#### 7. Open and verify the private Owner Console

1. Open the private console through the local LAN or Tailscale address and complete owner authentication.
2. Start a conversation, inspect its canonical message/turn record, and verify cited provenance and a correction flow.
3. Inspect system health, cost/disclosure, and Guardian status without granting the core Guardian authority.
4. Optionally enable Telegram, create/configure the bot using Telegram’s owner tooling.
2. Start long polling.
3. Send `/start`; the local console shows a one-time pairing code and exact numeric user/chat IDs.
4. Confirm pairing locally; reject all other senders/groups.
5. Test text, duplicate update, denied action, approval expiry, and token-revocation paths.

#### 8. Validate reasoning and memory

- Use deterministic fake-model smoke tests first.
- Enable one provider route for public/internal data.
- Enter a correction and verify observation → interpretation → belief → confirmation links.
- Inspect the disclosure and cost records.
- Run a replay against the smoke scenario.

#### 9. Install and test Guardian

- Install the independently controlled systemd unit/CLI from its protected source.
- Verify `no-actions`, `read-only`, `offline`, and `stopped` modes.
- Verify Melloa containers cannot alter Guardian files, firewall, or credentials.
- Revoke a test provider token and confirm the capability degrades safely.

#### 10. Configure backups and prove restoration

```bash
melloa backup init --local ...
melloa backup init --offsite ...
melloa backup run
melloa backup verify
```

Restore to a clean VM or spare disk, start read-only, and verify identity/policy/audit/blob samples. Do not declare installation complete before this succeeds.

#### 11. Enable ordinary actions

After reviewing policies, switch from `no-actions` to normal operation. Start with conversation, memory, status, and owner-only notifications; no third-party messages or self-deployment.

#### 12. Add camera later

1. Mount the PoE camera in the owner’s private space with consent and visible status.
2. Change unique credentials, update firmware, disable vendor cloud/P2P and unnecessary services.
3. Configure ONVIF/RTSP to perception only.
4. Calibrate day/night/occlusion scenarios using local candidate events.
5. Confirm camera-off and retention deletion behavior.
6. Enable cloud image escalation only after reviewing the data-class route.

### Operational runbooks

Each runbook includes prerequisites, impact, exact commands, validation, rollback, data-risk notes, and an incident/change record.

#### Upgrade Melloa

- Read release/ADR/migration notes; verify signature and digest.
- Run backup and restore compatibility check.
- Replay representative history and run policy/eval gates.
- Deploy in `no-actions` or staging; run health checks.
- Canary changed workflows, then promote or roll back to previous digest/config.

#### Replace a camera

- Disable camera capability and preserve the last heartbeat/error.
- Put new device on isolated provisioning network; update firmware and credentials.
- Configure profile/stream, time, bitrate, and low-light settings.
- Rebind the physical sensor identity rather than silently reusing evidence identity.
- Recalibrate zones/classification and verify deletion/retention.

#### Rotate an API key

- Create a new narrowly scoped key and provider-side budget.
- Insert through broker/SOPS; test with one capability.
- Switch atomically; revoke old key; verify no failed queue storm.
- Record rotation, scope, and any exposure investigation.

#### Restore backup

Follow the clean-host, Postgres-only, offline/read-only, integrity, index-rebuild, adapter-by-adapter procedure in the reliability specification. Record actual RPO/RTO.

#### Migrate database

- Restore a representative copy, run compatibility and timing tests.
- Use expand/migrate/contract; snapshot first.
- Stop affected writers or use a safe online pattern.
- Validate row counts, constraints, provenance links, and replay.
- Do not contract/remove old fields until all readers are upgraded and rollback window ends.

#### Debug missing events

Trace: source heartbeat → raw/candidate evidence → validation/quarantine → durable ingestion/deduplication → job state → interpretation → projection/index. Check clock, queue quotas, retention, source permissions, and dead-letter state. Never create a synthetic “observed” event to hide a gap.

#### Debug an agent run

Open the run graph: retrieval manifest, model route/version, prompt version, schema attempts, policy request/decision, capability receipts, cost, and outcome. Reproduce in replay with side effects disabled. Avoid turning on unbounded raw debug logging.

#### Disable a plugin/capability

- Revoke new grants and credential leases.
- Stop its worker/adapter.
- Drain or expire queued work deliberately.
- Preserve audit and source data according to retention.
- Verify no route still references the capability.

#### Inspect costs

Report month/day by provider, model, goal, capability, periodic loop, and failed/retried run. Compare estimate vs billed provider data. Pause experiments before owner-requested core functions.

#### Roll back a deployment

- Guardian enters `no-actions` if side-effect correctness is uncertain.
- Deploy previous signed image/config.
- Do not reverse incompatible data blindly; use migration recovery plan.
- Replay the incident, document root cause, and add regression cases.

#### Emergency shutdown

1. Owner invokes Guardian locally/private path or physical network/power control.
2. Guardian sets `stopped`, blocks egress, stops Melloa/perception/sandbox workloads, and revokes/removes credentials.
3. Preserve disks/logs unless immediate privacy risk requires disconnecting storage.
4. Do not restart in normal mode; inspect from recovery environment/read-only copy.
5. Rotate possibly exposed credentials and review actions/egress before recovery.

### Roadmap principles

- Each phase must create direct owner value and operational evidence.
- Add one new authority/data boundary at a time.
- Camera follows trustworthy text/memory/policy foundations, not the reverse.
- Self-modifying software follows replay, CI, rollback, and Guardian—not before.
- A capability is complete only with security, retention, observability, test, and runbook paths.

### Milestones

#### Phase 0 — architecture skeleton

**Outcome:** reproducible repo, docs, schemas, DB, Guardian modes, audit, CI, backup/restore.

Exit criteria: clean install; schema/event append; policy deny; cost/audit trail; restored system boots read-only.

#### Phase 1 — private owner conversation and provenance memory

**Outcome:** canonical conversation, private Owner Console, one owner, model gateway, correction-aware memory, structured decision records, disclosure/cost records, and optional Telegram long polling.

Exit criteria: useful daily conversation; cited memory; provider outage fallback; no external side effects beyond owner messages.

#### Phase 2 — reflection and intervention discipline

**Outcome:** daily digest, weekly review, explicit goals/hypotheses/interventions, proactivity budgets, owner feedback.

Exit criteria: at least one intervention is stopped or changed based on evidence; notification burden is measured.

#### Phase 3 — camera observation

**Outcome:** PoE camera, local segmentation/detection, probabilistic events, retention controls, selective escalation.

Exit criteria: calibrated error profile, no continuous cloud stream, camera-off/deletion verified, missed intervals visible.

#### Phase 4 — controlled software creation

**Outcome:** isolated worktree/sandbox, coding adapter, CI/evals, signed artifact, staging/canary/rollback.

Exit criteria: Melli creates and retires one low-risk internal tool with owner-visible benefit evidence and no governance authority.

#### Phase 5 — additional capabilities

Add HealthKit, calendar, computer context, files, voice, or environmental sensors one at a time based on goal value. Each requires a data contract, policy profile, threat review, and deletion/export path.

#### Phase 6 — measured distribution

Split edge/model/workflow components only after actual scale, isolation, or availability data crosses documented thresholds.

### First 30, 90, and 365 days

#### First 30 days

- Freeze vocabulary and the event/provenance/capability contracts.
- Build host bootstrap, Postgres, canonical conversation, private Owner Console shell, audit, policy broker skeleton, model adapter, cost ceilings, Guardian modes, optional Telegram pairing, and backup restore.
- Use only conversation/status/memory correction; collect operator friction and failure data.
- Publish ADRs and threat model before adding camera.

#### First 90 days

- Daily/weekly reflection with quiet-hour/frequency budgets.
- Replay/eval harness and private correction-derived regression set.
- Goal/hypothesis/intervention records and one reversible N-of-1-style experiment.
- Add camera locally only after retention/network/perception tests.
- Complete first security incident simulation and second restore drill.

#### First 365 days

- Prove months of reliable provenance, correction, cost, and intervention history.
- Introduce controlled generated-code workflow for low-risk internal artifacts.
- Add at most a few high-value capabilities, not an integration catalogue.
- Reassess database/job/event thresholds, local model economics, hardware, and client needs using observed data.
- Perform independent security/privacy review, name clearance, release compatibility policy, and open-source V1 release only if operations are reproducible.

### Explicitly not in the first year unless evidence changes

Kubernetes, public SaaS/multi-tenancy, autonomous financial transactions, autonomous cloud IAM, permanent multi-agent society, continuous multi-camera cloud video, generalized voice surveillance, marketplace, and a native mobile app before the channel contract proves stable.

---

<a id="doc-20-risk-register"></a>

## Ranked risk register

### Purpose

Track the threats most likely to destroy Melloa’s security, usefulness, maintainability, or owner trust. Rankings are initial judgments for V1 and must be revisited after incidents, capability grants, and architecture changes.

**Scale:** Probability (P) and Impact (I) are Low/Medium/High. Rank combines likelihood, severity, and difficulty of detection. Residual risk assumes listed mitigations are implemented.

| Rank | Risk | P | I | Detection / leading indicators | Principal mitigation | Residual |
|---:|---|:---:|:---:|---|---|:---:|
| 1 | Compromised autonomous agent or prompt injection causes unauthorized action | H | H | unusual tool sequences, policy denials, egress anomaly, new destinations, canary alerts | deterministic broker, exact-action authorization, taint labels, least privilege, sandbox, egress limits, Guardian | M |
| 2 | Privacy leak to provider, logs, backup, recipient, or contributor | M | H | disclosure manifest, DLP/redaction tests, audit review, provider/billing mismatch | sensitivity routing, local processing, minimization, encrypted stores, recipient binding, telemetry redaction | M |
| 3 | Incorrect long-term memory silently becomes “fact” | H | H | correction/contradiction rate, unsupported belief review, owner trust incidents | observation/interpretation/belief/confirmation separation, provenance, confidence, supersession, stale review | M |
| 4 | Owner loses trust after a harmful, creepy, or inexplicable action | M | H | dismissals, shutdowns, correction spikes, feedback, unexplained action audit | conservative proactivity, visible rationale/evidence, reversible actions, consent, incident review | M |
| 5 | Complexity outgrows one maintainer | H | H | upgrade time, flaky tests, runbook gaps, dependency count, modules bypassing contracts | modular monolith, one blessed path, dependency rules, ADRs, delete/defer aggressively | M |
| 6 | Data loss or unusable backups erase years of history | M | H | backup age/check failures, restore drill result, key-recovery test | encrypted 3-2-1-style copies, monthly clean restore, documented RPO/RTO, export | L-M |
| 7 | Over-optimization of a bad/vague goal harms owner | M | H | goal conflict, metric gaming, deteriorating guardrails, owner feedback | explicit values/constraints, multi-objective review, experiments, stop conditions, human goal control | M |
| 8 | Autonomous deployment corrupts data or service | M | H | canary regression, migration mismatch, error/action spike, rollback failure | isolated implementation, CI/replay/security gates, signed artifact, canary, expand/contract, Guardian | M |
| 9 | Runaway model/tool loop creates cost or actions | H | M-H | token/tool/step rate, queue growth, bill anomaly | per-run and monthly ceilings, circuit breakers, bounded retries, action quotas, provider budgets | L-M |
| 10 | Model regression changes behavior without visible code change | H | M-H | eval distribution shift, provider/version fingerprint, correction/denial spike | pin routes/versions where possible, model registry, replay gates, canary, fallback | M |
| 11 | Dependency or CI supply-chain compromise | M | H | provenance/signature failure, unexpected dependency/network access, advisories | lock/pin full SHAs, SBOM, SLSA-style provenance, Sigstore, minimal CI tokens, rebuild/rotate | M |
| 12 | Camera hallucination/missed event drives a false conclusion | H | M-H | calibration set, confidence/unknown rate, owner corrections, sensor disagreement | probabilistic interpretations, evidence frames, no absence inference, ask/abstain, local calibration | M |
| 13 | Stolen phone/Telegram account enables owner impersonation | M | H | new session/security alert, unusual command, pairing mismatch | Telegram limited role, exact IDs, local pairing, critical Guardian path separate, quick channel disable | M |
| 14 | Credential sprawl or a giant ambient secret bundle expands blast radius | M | H | secret access inventory, unused/stale grants, broad scopes | brokered scoped credentials, short leases, SOPS/keyring bootstrap, rotation, separate roles | M |
| 15 | Notification fatigue makes proactivity useless | H | M | ignore/dismiss rate, messages/day, quiet-hour attempts, repeated topics | interruption budget, batching, cooldowns, owner usefulness feedback, automatic stop | L-M |
| 16 | Framework/provider obsolescence or lock-in blocks evolution | M | M-H | adapter leakage, proprietary state, unportable prompts/evals | stable ports/schemas, canonical export, provider-neutral gateway, framework escape ADR | L-M |
| 17 | Camera or home hardware is brittle/offline | H | M | heartbeat, reconnect count, temperature/disk/network metrics | wired PoE, spare/replacement runbook, UPS optional, missed-period markers | L-M |
| 18 | Backup/recovery keys or owner root credentials are lost | L-M | H | recovery drill failure, single-copy key inventory | offline redundant key custody, periodic recovery test, documented ownership succession | L-M |
| 19 | Permission/grant set becomes stale and overbroad | H | M-H | unused grants, scope diff, expiry misses, capability inventory | expiries, least privilege, periodic recertification, no implicit grants on install | L-M |
| 20 | Audit/telemetry contains sensitive payloads or is incomplete | M | M-H | redaction tests, missing side-effect linkage, label cardinality, export scan | separate audit/telemetry, reference IDs/hashes, pre-export redaction, mandatory action linkage | L-M |
| 21 | Event schema/migration loses meaning over years | M | H | compatibility gate, replay failure, orphaned provenance, unknown enum/version | immutable envelopes, version adapters, expand/contract, raw preservation where justified | L-M |
| 22 | External service outage removes core usefulness | H | M | provider/channel health, queued age, fallback use | local capture/memory, provider adapters, graceful degradation, TTL, private local UI path | L |
| 23 | Third-party data is collected or shared without adequate consent | M | H | source/person labels, disclosure review, complaints | private-space scope, consent indicators, stricter third-party classification, deletion and no cloud by default | M |
| 24 | Malicious contributor or maintainer bypasses protections | L-M | H | anomalous code/CI rule change, review bypass, signing failure | protected branches, CODEOWNERS, independent Guardian repo, signed releases, least-privilege maintainer roles | M |
| 25 | Local network malware reaches camera/core | M | H | firewall/IDS anomalies, unexpected connections, host integrity alerts | VLANs, patching, host firewall, no camera internet, narrow service ports, credential rotation | M |
| 26 | Generated code exfiltrates private data or escapes sandbox | M | H | denied egress, sandbox syscall/resource anomaly, unexpected file access | no live data/secrets by default, rootless + gVisor, quotas, default-deny egress, disposable environment | M |
| 27 | Retention/deletion fails, creating a hidden life-log | M | M-H | storage growth, overdue objects, deletion receipt gaps | hard TTLs/quotas, retention worker, owner dashboard, backup expiry disclosure | L-M |
| 28 | Cost accounting is incomplete or provider bill diverges | M | M | unallocated calls, invoice reconciliation, unknown model route | mandatory invocation ledger, provider budget, billing reconciliation, fail closed on unknown priced route | L |
| 29 | Naming/trademark collision harms public release | M | M | registry/domain/trademark search and counsel | keep launch branding reversible; clearance gate before substantial public brand investment | L-M |
| 30 | Project becomes surveillance/productivity theatre without measurable benefit | H | H | no intervention outcomes, unused data, growing integrations, owner burden | value milestone gates, reject capabilities without goal/evaluation path, periodic deletion/simplicity review | M |

### Risk ownership and triggers

| Risk family | Operational owner | Re-review trigger |
|---|---|---|
| Policy, prompt injection, capability security | security/governance owner | new write capability, new untrusted source, model/tool protocol change |
| Memory and epistemic integrity | Melloa architecture owner | new memory class, correction incident, schema migration |
| Privacy and consent | privacy owner | new sensor/provider/recipient, retention change, public release |
| Reliability and recovery | operator/SRE owner | failed backup/restore, new host/site, dependency change |
| Self-modification and supply chain | repository owner | autonomous merge class expanded, new CI runner/coding agent |
| Goal/intervention harm | human owner | new long-term goal, health/financial domain, unexpected outcome |
| Cost | operator/owner | monthly spend >80% budget, new multimodal/local GPU route |

For a one-person deployment, the same human may hold all roles. The labels force perspective changes and explicit review rather than organizational ceremony.

### Top risk treatment priorities before camera or self-deployment

1. Demonstrate a policy denial cannot be bypassed by model output or tool text.
2. Demonstrate every side effect has an exact authorization and audit receipt.
3. Demonstrate correction-aware memory and unsupported-belief inspection.
4. Restore the system and keys on a clean machine.
5. Reconcile model calls and external disclosures to provider/billing records.
6. Exercise Guardian stop/egress revocation independently of Melloa.
7. Calibrate proactivity and camera error before trusting behavioral conclusions.

### Residual-risk statement

No architecture can make an autonomous, sensor-rich personal system risk-free. In particular, a compromised owner device, malicious model/provider, novel sandbox escape, or mistaken human approval may still cause harm. The objective is to reduce blast radius, create timely detection and recovery, and avoid granting authority that the system has not earned.

---

<a id="doc-21-reviewers-open-questions-rejected"></a>

## Adversarial review, open questions, and rejected ideas

### Purpose

Expose unresolved trade-offs and document what Melloa deliberately refuses to build. The architecture is stronger when objections remain visible rather than being edited out of the final recommendation.

### Independent reviewer findings

#### Security reviewer

**Objection:** A model that reads hostile content and can operate tools should be assumed compromisable. A policy engine called by the same compromised process is not enough.

**Resolution:** Authorization is deterministic and enforced at the capability broker; credentials are scoped/brokered; generated code is isolated; egress is constrained; Guardian/root authority is inaccessible to the autonomous plane. High-impact approvals bind the exact action hash. Residual risk remains if the broker/host itself is compromised.

#### Reliability reviewer

**Objection:** One host, one database, a camera pipeline, model APIs, Telegram, backups, and generated code create too many failure modes for a personal project.

**Resolution:** Accept one-host downtime, not data ambiguity. Keep PostgreSQL as the sole durable operational dependency, use bounded queues and graceful degradation, make camera and providers optional, and prioritize clean restore over HA. Do not add a queue cluster/workflow engine before measured need.

#### Simplicity reviewer

**Objection:** Event sourcing, knowledge graphs, permanent agents, Kubernetes, Vault, SPIFFE, and microVMs are architecture cosplay for one user.

**Resolution:** Use append-oriented evidence/audit plus ordinary relational projections, rootless Compose, SOPS/keyring, one Melli, temporary workers, and gVisor only when generated code exists. Preserve interfaces, not unused platforms.

#### AI researcher

**Objection:** Current models are unreliable at persistent identity, long-horizon planning, causal inference, and self-evaluation. Calling an agent “continuous” does not create continuity.

**Resolution:** Put continuity in durable identity, memory, goals, relationships, policies, and change history. Treat models as replaceable cognitive engines. Break long-horizon work into explicit proposals/workflows with checkpoints. Use replay and owner feedback, and make “unknown/inconclusive” a valid result.

#### Privacy reviewer

**Objection:** A private-room camera plus years of memory is intrinsically high risk, especially for visitors and cloud model disclosure.

**Resolution:** Camera is not required for initial value. When enabled: visible/private-space deployment, consent, isolated network, local segmentation, short raw retention, no continuous cloud upload, strict third-party handling, camera-off controls, and disclosure reports. Some residual privacy risk is unavoidable; users who reject it should disable the capability.

#### Open-source maintainer

**Objection:** Personal assumptions and one-off hardware will make the repository impossible for others to reproduce.

**Resolution:** One blessed deployment, synthetic fixtures, stable contracts, documented personal configuration boundary, ADRs, migrations, export/import, CI, and explicit unsupported alternatives. Open-source quality does not mean universal hardware compatibility.

#### Cost reviewer

**Objection:** Frontier reasoning, multimodal interpretation, coding agents, and evaluation can make the system financially unbounded.

**Resolution:** Filter locally, batch periodic work, route by adequacy and privacy, record cost by goal/capability, enforce step/token/daily/monthly limits, and stop experiments before core functions. Avoid continuous cloud video and premature GPU purchase.

#### Future-self reviewer

**Objection:** Five years of schemas, prompts, capabilities, summaries, experiments, and generated software will become archaeology.

**Resolution:** Precise vocabulary, immutable provenance, versioned contracts, migration adapters, a monorepo, ADRs, runbooks, retention, deletion, and periodic simplicity reviews. Every artifact has an owner/expiry; temporary experiments are not permanent by default.

### Resolved disagreements

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

### Rejected ideas

#### Kafka/Redpanda in V1

Rejected because throughput and multi-team replay requirements do not justify another distributed durable state system. PostgreSQL jobs/outbox preserve a migration path. Revisit after measured backlog, multiple nodes, or independent consumer scaling.

#### Kubernetes/service mesh in V1

Rejected because one host and a handful of processes gain little from a cluster control plane, certificates, controllers, and upgrade burden. Compose plus systemd/Ansible is inspectable and recoverable.

#### Vector database as “memory”

Rejected because similarity search cannot represent provenance, correction, temporal truth, policy, or epistemic status. `pgvector` is a rebuildable retrieval index over canonical relational records.

#### Graph database as primary store

Rejected because V1 relationships fit PostgreSQL tables/recursive queries and a second primary database increases migrations/backups/operational burden. Add a graph projection only after concrete queries demonstrate value.

#### Pure event sourcing for all state

Rejected because reconstructing every operational object from an eternal log creates schema/replay complexity. Preserve append-oriented evidence and action history while maintaining normal current-state projections.

#### Permanent multi-agent society

Rejected because multiple named agents create coordination, accountability, memory partition, and security questions without demonstrated benefit. Use temporary specialists under Melli’s run/proposal and policy boundary. Add persistent agents only for a durable distinct identity/responsibility/permission relationship.

#### Raspberry Pi as the blessed core server

Rejected because storage endurance, memory/headroom, hardware variability, and future sandbox/model workloads make a modest x86 mini-PC a more maintainable default. Raspberry Pi remains useful as an edge camera/sensor node.

#### Continuous cloud video interpretation

Rejected for privacy, bandwidth, storage, cost, and false-confidence reasons. Local segmentation and selective evidence are required.

#### Telegram webhook/public domain in V1

Rejected because long polling avoids public ingress for one user. Telegram remains a convenience channel, not a confidential or root-control plane.

#### Local-only models as doctrine

Rejected because privacy is one routing dimension; inadequate local intelligence can reduce usefulness and safety. Use the cheapest adequate eligible model and make disclosure explicit.

#### Giant `.env` and ambient credentials

Rejected because any compromised process would inherit unrelated authority. Use scoped roles, brokered leases, OS/key management, and provider-side limits.

#### OpenBao/Vault on day one

Rejected because operating a secret-management service adds an unsealing/recovery/availability system before dynamic credentials or multiple nodes justify it. Preserve a broker interface and migrate when needed.

#### Firecracker/microVM fleet on day one

Rejected because generated code is deferred and rootless containers/gVisor plus no secrets/egress provide a simpler initial boundary. Firecracker is a future stronger isolation tier, not a checkbox.

#### MCP as universal internal protocol

Rejected because MCP is useful at model/tool integration boundaries but does not replace Melloa’s policy, provenance, durable event, identity, or capability contracts. The architecture must survive protocol evolution.

#### Autonomous cloud IAM, finance, or governance

Rejected in early versions because blast radius, irreversibility, external obligations, and approval ambiguity exceed demonstrated trust. Melli may draft exact plans; the owner executes/approves through a separate path.

#### Unbounded “daily AI reflection”

Rejected because repeated summaries can create cost and self-reinforcing false beliefs. Periodic loops operate only on new evidence, explicit questions, and budgets; no-op is a valid result.

### Assumptions the research changed

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

### Open questions, ranked

#### P0 — resolve before implementation or enabling the capability

1. What exact owner authentication and recovery design protects Guardian actions on the chosen host?
2. Which policy language/runtime best fits typed, explainable action decisions without creating an expert-only UX—small in-house evaluator first, Cedar adapter, or another option?
3. What are the exact V1 event/assertion schemas and correction/supersession invariants?
4. Which provider/model routes are eligible for each sensitivity class under the owner’s jurisdiction and current contracts?
5. What camera placement/room consent and “camera off” physical indicator meet the owner’s real environment?

#### P1 — answer through early prototypes/evidence

6. Does Frigate provide the right candidate-event interface, or is a thinner FFmpeg/OpenCV detector more maintainable for the selected camera?
7. How often do daily/weekly loops produce net value before notification/cost fatigue?
8. What local model tasks are actually adequate on the selected mini-PC or Apple Silicon device?
9. Which memory retrieval strategy minimizes plausible but unsupported synthesis over months?
10. What exact canary and rollback metrics are meaningful for prompt/model changes?
11. Which maintained local/private authentication implementation best satisfies Owner Console sessions, reauthentication, recovery, and future passkeys without coupling domain identity to one vendor?
12. At what observed job volume/node count should NATS or Temporal be introduced?

#### P2 — intentionally deferred research

13. When should another persistent intelligence be created rather than an ephemeral specialist?
14. What native iOS/HealthKit architecture and consent model is justified?
15. Does voice in a private room produce enough value to justify microphone privacy and wake-word/streaming complexity?
16. When is OpenBao/SPIFFE/workload identity worth the operational cost?
17. Can intervention evaluation become more rigorous without turning the owner’s life into an experiment platform?
18. What legal/licensing obligations apply to AI-generated plugins and redistribution of model-derived artifacts?
19. What is the durable process for Melli choosing/changing its own name while preserving identity continuity and owner control?

### Simplicity review cadence

Quarterly, ask:

- Which service, capability, prompt, model, dataset, dashboard, or periodic loop has not produced measurable value?
- Which derived data can be rebuilt or deleted?
- Which permissions were unused?
- Which operational dependency can be removed?
- Which abstraction has only one implementation and no credible near-term alternate?
- Which “temporary” experiment lacks an owner/expiry?

Deletion is an architectural capability.

---

<a id="doc-22-final-synthesis"></a>

## Final synthesis and decisive recommendation

### Recommendation

If personally responsible for maintaining Melloa for seven years, I would build a **local-first modular monolith centered on PostgreSQL, an append-oriented provenance/audit model, a deterministic capability broker, provider-neutral model adapters, and an independently controlled Guardian**.

Melloa is the system. Melli is one durable personal intelligence whose continuity is represented by identity, memory, goals, relationships, policies, and change history—not by one model, process, or provider. Use temporary specialist workers under a run/proposal boundary. Add another persistent intelligence only when a distinct long-lived identity, responsibility, memory, permission set, or relationship is genuinely required.

The system should be event-oriented without deploying an event-stream platform. PostgreSQL is the V1 source of truth for canonical records, current projections, jobs, outbox, policy state, and audit. `pgvector` is a derived retrieval index. Content-addressed local storage holds frames, clips, exports, and generated artifacts. Rootless Compose keeps operations understandable. An external Guardian, not callable or writable by Melli, owns emergency modes, egress revocation, workload stop, and recovery.

### Answers to the ten final questions

#### 1. What architecture would I choose for seven years?

A modular monolith with stable domain/port contracts and explicit trust boundaries:

- PostgreSQL for durable state and asynchronous jobs;
- append-oriented observation → interpretation → assertion/belief → confirmation/correction provenance;
- ordinary relational projections for current state;
- capability adapters behind a deterministic authorization broker;
- model gateway/routing independent of provider and agent framework;
- local-first media/object storage and selective cloud disclosure;
- rootless containers on a wired Linux mini-PC;
- host-owned Guardian and private networking;
- monorepo, ADRs, replay/evals, signed artifact deployment, and tested backups.

This architecture can be split later without paying distributed-systems cost before it produces value.

#### 2. What would I build first?

Build the **truth, authority, and recovery spine** before sensing:

1. vocabulary and versioned event/provenance schemas;
2. PostgreSQL/migrations/jobs/outbox/idempotency;
3. owner/Melli identity and correction-aware memory;
4. deterministic capability broker and audit;
5. provider-neutral model gateway with fake model for tests;
6. Guardian modes and credential revocation;
7. encrypted backup/export and clean restore;
8. canonical conversation and the private Owner Console;
9. optional Telegram remote adapter;
10. daily/weekly reflection and intervention records;
11. camera after the truth, authority, recovery, and inspection foundations work.

#### 3. What would I explicitly refuse to build yet?

- Kubernetes, service mesh, Kafka/Redpanda, graph database, standalone vector database;
- permanent multi-agent society;
- public domain/webhook/cloud control plane;
- continuous cloud video or general surveillance;
- autonomous IAM, finance, governance, or irreversible infrastructure;
- full local-GPU stack before profiling;
- OpenBao/SPIFFE/microVM fleet before dynamic multi-node need;
- native mobile/voice experience before channel and privacy contracts stabilize;
- an integration marketplace or nontechnical onboarding.

#### 4. Which three architectural choices matter most today?

1. **Epistemic provenance:** observation is not interpretation, interpretation is not belief, and belief is not user-confirmed fact. Corrections append and propagate.
2. **Authority outside the model:** every side effect uses deterministic capability authorization and scoped credentials; Guardian remains independent.
3. **Replaceable intelligence and integrations:** provider/framework/channel/camera details sit behind versioned contracts and canonical owner-controlled data.

PostgreSQL versus another competent database is less important than these boundaries.

#### 5. What mistakes are most likely to kill the project?

- building the seven-year distributed platform before proving one useful loop;
- allowing plausible inferences to accumulate as facts;
- giving model-facing processes broad credentials or host control;
- measuring activity instead of owner outcomes;
- adding integrations without deletion, security, failure, and evaluation paths;
- notification fatigue and creepy proactivity;
- unlimited multimodal/coding loops and opaque cost;
- never proving restoration;
- framework lock-in and repository sprawl;
- treating voice/UI spectacle as the product.

#### 6. What is genuinely difficult?

- maintaining truthful, correctable long-term memory under uncertainty and schema evolution;
- granting useful autonomy without turning untrusted content into authority;
- measuring whether an intervention caused meaningful benefit rather than correlation or compliance theatre;
- safely evaluating and deploying self-created software;
- preserving owner trust across inevitable model and sensor mistakes;
- governing years of sensitive personal and third-party data;
- keeping one engineer able to operate the system as capabilities accumulate.

#### 7. What sounds difficult but is mostly solved?

- containerized service deployment on one host;
- relational durable state, migrations, queues/outbox patterns, private networking, encrypted backups;
- Git branches/PRs/CI/artifact signing;
- Telegram bot transport and RTSP/ONVIF camera acquisition;
- structured telemetry and basic model-provider adapters;
- content-addressed files and open export formats.

The work is integrating these primitives under coherent truth, authority, and evaluation semantics—not inventing replacements.

#### 8. Which assumptions did research prove wrong or weaken?

- Raspberry Pi should be an edge option, not the blessed core server.
- Telegram is a useful replaceable channel, not an end-to-end encrypted permanent UI or root-control path.
- An event-oriented core does not require Kafka/NATS/Temporal in V1.
- Multiple persistent agents are not inherently better than one durable intelligence plus temporary specialists.
- A vector database is retrieval infrastructure, not memory architecture.
- Local-first is not local-only; weak local reasoning can be less safe/useful than controlled cloud escalation.
- Code generation is easier than authorization, evaluation, rollback, and benefit measurement.
- Camera-first would optimize the visible demo before trust foundations.
- A public domain is unnecessary for the private Owner Console or optional Telegram long polling.

#### 9. What is the approximate first-year cost?

For a disciplined V1:

- hardware: roughly **£510–£1,200**;
- operation: roughly **£15–£70/month** for one camera, local filtering, offsite backup, electricity, Telegram, and modest model use;
- practical first-year total: approximately **£800–£2,100**, excluding developer labour.

Heavy frontier reasoning, cloud multimodal video, autonomous coding/eval loops, or premature GPU hardware can push this into hundreds or thousands of pounds per month. Prices are dated planning estimates and require purchase-time verification.

#### 10. What should days 30, 90, and 365 look like?

**Day 30:** reproducible host, Postgres, schemas/provenance, canonical conversation, private Owner Console, policy broker, model gateway, audit/cost, Guardian, backup restored once, and optional Telegram pairing. Conversation, inspection, and corrections only.

**Day 90:** daily/weekly reflection, replay/eval suite, explicit goal/hypothesis/intervention workflow, calibrated proactivity, one reversible evaluated intervention, camera added only if the foundations remain reliable.

**Day 365:** months of trustworthy history and cost/outcome evidence, controlled low-risk software creation with staging/canary/rollback, a small number of valuable capabilities, repeated recovery/security drills, architecture thresholds reassessed, and public release only if onboarding and operations are reproducible.

### The recommended V1

#### Exact major components

| Concern | V1 choice |
|---|---|
| Host | dedicated wired x86-64 mini-PC; 16–32 GB RAM; 1 TB NVMe; Debian/Ubuntu LTS |
| Runtime | rootless Docker Engine + Docker Compose; systemd-owned Guardian; Ansible host bootstrap |
| Core languages | Python 3.13+, SQL, and TypeScript for the private Owner Console |
| Core/API | modular monolith; FastAPI/Pydantic-compatible typed boundaries |
| Database | PostgreSQL 18 with separate roles and migrations |
| Semantic index | `pgvector`, rebuildable from canonical memory records |
| Async work | PostgreSQL job/outbox tables; durable polling plus `LISTEN/NOTIFY` wake-up hint |
| Blobs | content-addressed local filesystem with metadata/retention in Postgres |
| Primary client | private authenticated Owner Console over LAN/Tailscale |
| Conversation | canonical channel-independent threads/messages/turns with provenance |
| Secondary channel | optional Telegram Bot API long polling; one paired/whitelisted owner ID |
| Camera | wired PoE ONVIF Profile T/RTSP camera on isolated VLAN |
| Perception | Frigate + go2rtc or thin compatible adapter; cheap local segmentation/detection; selective evidence |
| Models | task/sensitivity-aware gateway; at least one hosted provider; optional local llama.cpp/MLX/vLLM endpoint |
| Policy | typed deterministic broker; deny/allow/approval decision; exact action hash; capability grants/budgets |
| Secrets | SOPS + age/OS keyring bootstrap; scoped credential broker; provider-side budgets |
| Private access | Tailscale default with WireGuard-compatible escape; no public application ingress |
| Generated code | deferred until gVisor-grade sandbox, replay/CI, signed artifacts, canary, rollback exist |
| Telemetry | append-oriented domain/audit records + OpenTelemetry traces/metrics/logs, redacted |
| Backups | encrypted restic to local USB and B2/equivalent; monthly clean restore |
| Docs | MkDocs Material, Mermaid, ADRs, runbooks, versioned source register |
| Git | monorepo + separately protected Guardian trust domain; protected main/CODEOWNERS/pinned CI |

#### V1 service boundaries

```text
Melloa Core
  identity and Melli continuity
  canonical conversation
  event/provenance/memory
  goals, hypotheses, interventions
  model gateway and retrieval
  policy requests and audit

Owner Console
  first-party conversation
  timeline, provenance and corrections
  run, media, cost, disclosure and health views

Melloa Worker
  durable jobs
  interpretation/indexing
  reflection/evaluation
  retention/export

Capability Broker
  grants, policy, approvals
  credential lease
  side-effect receipt

Adapters
  optional Telegram
  perception/camera
  model providers
  files/backups

Guardian (outside autonomous plane)
  modes, stop, egress revoke
  credential removal
  recovery/read-only control
```

### V1 deployment diagram

```mermaid
flowchart TB
  Owner[Owner devices] -->|Tailscale / private LAN| Web[Private Owner Console]
  Web --> API[Melloa core API]
  Telegram[Optional Telegram Bot API] <-->|outbound HTTPS long polling| TG[Telegram adapter]
  TG --> API

  subgraph Host[Wired Linux mini-PC]
    subgraph Rootless[Rootless Compose]
      API --> DB[(PostgreSQL + pgvector)]
      Worker[Melloa worker] --> DB
      API --> Broker[Capability broker]
      API --> Model[Model gateway]
      Perception[Perception adapter] --> API
      API --> Blob[(Content-addressed blobs)]
      OTel[OTel collector] -. redacted telemetry .- API
      OTel -.-> Worker
    end
    Guardian[Owner-controlled Guardian\nsystemd + firewall + revoke]
    Backup[restic backup process]
    Backup --> DB
    Backup --> Blob
  end

  Camera[PoE ONVIF/RTSP camera\nisolated VLAN] --> Perception
  Model -->|eligible disclosure only| Providers[Approved model APIs]
  Backup -->|encrypted| Offsite[Offsite object storage]
  Guardian -. stop / no-actions / offline .-> Rootless
  Rootless --x Guardian
```

### V1 data-flow diagram

```mermaid
flowchart LR
  Source[Source or sensor] --> Raw[Raw evidence / inbound observation]
  Raw --> Validate[Validate, classify, hash, taint]
  Validate --> Candidate[Candidate event]
  Candidate --> Interpret[Semantic interpretation]
  Interpret --> Assertion[Assertion or hypothesis\nwith confidence + evidence]
  Assertion --> Memory[Memory projections and indexes]
  Memory --> Reason[Goal/context reasoning]
  Reason --> Proposal[Action proposal]
  Proposal --> Policy[Deterministic policy + capability broker]
  Policy -->|deny| Audit[Audit outcome]
  Policy -->|approval| Human[Exact owner approval]
  Human --> Policy
  Policy -->|allow| Action[Scoped capability execution]
  Action --> Outcome[Observed result/outcome]
  Outcome --> Evaluate[Evaluate usefulness and side effects]
  Evaluate --> Memory
  Evaluate --> Change[Keep, alter, stop, or propose software change]
```

### V1 trust-boundary diagram

```mermaid
flowchart TB
  subgraph External[Untrusted / external]
    Web[Web/email/documents]
    Telegram[Optional Telegram cloud]
    Provider[Model provider]
    Camera[Embedded camera]
  end

  subgraph Low[Low-trust processing]
    Quarantine[Attachment quarantine]
    Perception[Perception pipeline]
    Sandbox[Generated-code sandbox]
  end

  subgraph Autonomous[Autonomous Melloa plane]
    Core[Melli reasoning and core]
    Broker[Capability broker]
    DB[(Scoped application DB roles)]
  end

  subgraph OwnerControl[Owner-only control plane]
    Guardian[Guardian]
    RootSecrets[Root/recovery credentials]
    Firewall[Host firewall / workload stop]
  end

  Web --> Quarantine --> Core
  Telegram --> Core
  Camera --> Perception --> Core
  Core --> Provider
  Core --> Broker --> DB
  Core --> Sandbox
  Guardian --> Firewall
  Guardian --> RootSecrets
  Guardian -. constrain/revoke/stop .-> Autonomous
  Autonomous --x OwnerControl
```

### Realistic V1 sequence

```mermaid
sequenceDiagram
  participant Cam as Camera
  participant P as Local perception
  participant Core as Melloa core
  participant DB as Event/memory store
  participant Melli as Melli reasoning
  participant Policy as Policy broker
  participant Daily as Daily reflection
  participant Git as Change pipeline
  participant Owner as Owner

  Cam->>P: room scene changes
  P->>P: motion/scene segmentation + local detector
  P->>Core: candidate: person entered (0.82), evidence hashes
  Core->>DB: append observation and interpretation
  Core->>Melli: assess immediate relevance
  Melli->>Policy: proposal = no external action
  Policy-->>Melli: allowed (no side effect)
  Melli->>DB: record decision and rationale/evidence IDs

  Daily->>DB: retrieve recent routines, goals, corrections
  Daily->>Melli: repeated late desk arrival may affect exercise goal
  Melli->>DB: write hypothesis, uncertainty, proposed intervention
  Melli->>Owner: ask whether a low-burden reminder experiment is wanted
  Owner-->>Melli: approve bounded experiment
  Melli->>Policy: exact schedule/message/budget action
  Policy-->>Melli: allowed under approval and quiet-hour policy
  Melli->>Git: create change/proposal for reminder workflow
  Git->>Git: tests + replay + security + staging
  Git-->>Melli: signed canary artifact
  Melli->>Policy: deploy internal reversible canary
  Policy-->>Melli: allowed within preset class
  Melli->>DB: deployment and intervention record

  Note over Cam,DB: Later observations and owner feedback become outcomes
  Daily->>DB: evaluate run occurrence, burden, confounders
  Daily->>Melli: evidence inconclusive / useful / harmful
  Melli->>DB: continue, modify, or retire intervention
  Melli->>Owner: concise result with limitations
```

The candidate “person entered” remains a probabilistic interpretation. A later routine conclusion does not become a fact merely because it is repeated. The intervention requires an explicit hypothesis, bounded authority, a burden budget, and outcome review.

### First implementation milestones

#### M0 — contracts and recovery

Deliver event envelope, assertion/provenance model, owner/Melli identity, policy request/decision schema, Postgres migrations, audit, Guardian modes, CI, encrypted backup and successful restore.

#### M1 — trustworthy conversation and owner inspection

Deliver canonical conversation, the private Owner Console, provider-neutral model gateway, cited retrieval, correction/supersession, structured decision/run inspection, health/media/cost/disclosure views, optional Telegram long polling/pairing, and degraded behavior during provider/channel failure.

#### M2 — reflective closed loop

Deliver goals/hypotheses/interventions/outcomes, daily and weekly loops with no-op/budgets, replay/evals, and one reversible measured intervention.

#### M3 — selective vision

Deliver isolated PoE camera, local candidate segmentation/detection, evidence/probabilistic events, calibration, retention, and sensitivity-aware cloud escalation.

#### M4 — controlled creation

Deliver isolated generated-code runner, PR/CI/replay/security gates, signed staging artifact, low-risk canary, rollback, and benefit/expiry review.

A milestone is incomplete without documentation, threat review, observability, retention/export, tests, and runbook.

### Final architectural stance

Melloa should be ambitious about the **loop** and conservative about **authority**. It should accumulate evidence, not mythology; create reversible experiments, not permanent clutter; and let intelligence improve without allowing a model update, framework, agent process, or provider to redefine who Melli is.

The foundation to protect is not a particular application. It is the owner-controlled mechanism by which observations become qualified beliefs, goals become bounded actions, consequences become evidence, and the system can safely change its own tools while remaining understandable and stoppable.

---

<a id="doc-diagrams"></a>

## Architecture diagrams

These diagrams are design artifacts, not decorative overview pictures. They show data, authority, trust, lifecycle, and migration boundaries. Mermaid source is kept in version control.

### 1. Top-level system architecture

```mermaid
flowchart TB
  Human[Owner] -->|conversation, inspection, corrections, approvals| Console[Private Owner Console]
  Human -->|optional remote messages| Clients[Telegram and future clients]
  Env[Environment] --> Sensors[Sensors and integrations]
  Sensors --> Detect[Cheap local detection and normalization]
  Detect --> Events[Canonical observations and events]
  Console --> Events
  Clients --> Events
  Events --> Memory[Provenance and memory]
  Memory --> Reason[Melli policy-aware reasoning]
  Reason --> Proposals[Action or change proposals]
  Proposals --> Broker[Deterministic capability broker]
  Broker -->|authorized| Capabilities[Capabilities and communication]
  Broker -->|denied or approval| Human
  Capabilities --> Env
  Capabilities --> Outcomes[Results and observed consequences]
  Outcomes --> Evaluate[Evaluation and learning]
  Evaluate --> Memory
  Evaluate --> Changes[Configuration or software change pipeline]
  Changes --> Capabilities
  Guardian[Owner-only Guardian] -. constrain, revoke, stop .-> Broker
  Guardian -. constrain, revoke, stop .-> Capabilities
  Broker --x Guardian
```

### 2. Trust boundaries

```mermaid
flowchart TB
  subgraph External[Boundary A: external and untrusted]
    Web[Web, email, documents]
    Chat[Optional Telegram and future external channels]
    Providers[Model and cloud providers]
    Embedded[Camera and embedded devices]
  end

  subgraph Intake[Boundary B: low-trust intake]
    Quarantine[Attachment quarantine]
    Perception[Perception pipeline]
    Validation[Schema, size, identity, taint validation]
  end

  subgraph Autonomous[Boundary C: autonomous Melloa plane]
    Console[Private Owner Console]
    Core[Core and Melli runs]
    ModelGateway[Model gateway]
    Broker[Capability broker]
    Data[(Scoped Postgres and blobs)]
  end

  subgraph Sandboxed[Boundary D: hostile generated code]
    Sandbox[Disposable rootless and gVisor sandbox]
  end

  subgraph Control[Boundary E: owner-only control]
    Guardian[Guardian]
    RootKeys[Recovery and root credentials]
    Host[Firewall and systemd]
  end

  External --> Intake --> Core
  Console --> Core
  Core --> ModelGateway --> Providers
  Core --> Broker --> Data
  Core --> Sandbox
  Guardian --> Host
  Guardian --> RootKeys
  Guardian -. mode and revocation .-> Autonomous
  Autonomous --x Control
  Sandboxed --x Control
```

### 3. Control plane versus autonomous plane

```mermaid
flowchart LR
  subgraph OwnerPlane[Owner control plane]
    Owner[Owner]
    Guardian[Guardian CLI and service]
    PolicyRoot[Root policies and approval rules]
    CredentialRoot[Credential and recovery root]
    NetworkRoot[Host firewall and workload control]
  end

  subgraph AutoPlane[Autonomous plane]
    Melli[Melli]
    Scheduler[Workers and periodic loops]
    Broker[Capability broker]
    Adapters[Capability adapters]
    Runtime[Rootless containers]
  end

  Owner --> Guardian
  Owner --> PolicyRoot
  Guardian --> NetworkRoot
  Guardian --> CredentialRoot
  PolicyRoot -->|read-only policy bundle| Broker
  CredentialRoot -->|scoped leases| Broker
  NetworkRoot -->|start, stop, egress modes| Runtime
  Melli --> Broker --> Adapters
  Scheduler --> Melli
  AutoPlane --x OwnerPlane
```

### 4. Event ingestion flow

```mermaid
flowchart LR
  Source[Source] --> Adapter[Source adapter]
  Adapter --> Validate[Identity, schema, size, hash]
  Validate --> Classify[Sensitivity, trust and taint]
  Classify --> Raw[Immutable observation]
  Raw --> Outbox[Transactional job or outbox]
  Outbox --> Worker[Idempotent consumer]
  Worker --> Interpret[Interpretation with confidence]
  Interpret --> Link[Evidence and provenance links]
  Link --> Project[Current projections]
  Link --> Index[Full-text and vector indexes]
  Worker -->|failure| Dead[Visible retry or dead-letter state]
  Dead --> Replay[Operator or policy replay]
```

### 5. Camera perception pipeline

```mermaid
flowchart LR
  Camera[PoE camera RTSP stream] --> Ring[Local short ring buffer]
  Ring --> Motion[Motion and scene change]
  Motion --> Segment[Event segmentation]
  Segment --> Frames[Selective frames or short clip]
  Frames --> Detector[Local object and person detector]
  Detector --> Gate{Enough confidence and value?}
  Gate -->|yes, local adequate| Event[Candidate event plus evidence]
  Gate -->|uncertain, eligible data| Vision[Stronger local or cloud vision model]
  Gate -->|low value| Expire[Expire candidate]
  Vision --> Event
  Event --> Core[Canonical observation and interpretation]
  Core --> Retain[Retention by sensitivity and value]
  Core --> Ask[Ask owner when uncertainty matters]
```

### 6. Model-routing architecture

```mermaid
flowchart TB
  Task[Model task request] --> Requirements[Modality, quality, latency, context]
  Requirements --> Privacy[Sensitivity and provider eligibility]
  Privacy --> Budget[Per-run and monthly budget]
  Budget --> Router[Deterministic routing policy]
  Router --> T0[Tier 0: no model]
  Router --> T1[Tier 1: tiny or local model]
  Router --> T2[Tier 2: medium model]
  Router --> T3[Tier 3: frontier model]
  T0 --> Validate[Typed result and evidence]
  T1 --> Validate
  T2 --> Validate
  T3 --> Validate
  Validate --> Good{Schema and quality adequate?}
  Good -->|yes| Result[Result with route, cost and disclosure record]
  Good -->|no and eligible| Fallback[Bounded repair or fallback]
  Fallback --> Router
  Good -->|no route| Abstain[Abstain or ask owner]
```

### 7. Memory layers

```mermaid
flowchart TB
  Evidence[Raw evidence and source reference] --> Observation[Observation]
  Observation --> Interpretation[Interpretation with model and confidence]
  Interpretation --> Assertion[Assertion or hypothesis]
  Assertion --> Belief[Current belief projection]
  Belief --> Confirmed[Owner-confirmed fact or preference]
  Assertion --> Correction[Correction, dispute or supersession]
  Confirmed --> Correction
  Correction --> Belief

  Observation --> Episodic[Episodic memory]
  Belief --> Semantic[Semantic memory]
  Goals[Goals and policies] --> Working[Working context]
  Episodic --> Working
  Semantic --> Working
  Working --> Retrieval[Retrieval manifest]
  Retrieval --> Reasoning[Reasoning run]
  Observation --> Archive[Archive and retention]
  Semantic --> Vector[Rebuildable vector index]
```

### 8. Autonomous software-development loop

```mermaid
flowchart TB
  Need[Need or hypothesis detected] --> Proposal[Durable change proposal]
  Proposal --> Risk[Risk and authority classification]
  Risk --> Sandbox[Isolated worktree and sandbox]
  Sandbox --> Implement[Implementation]
  Implement --> Tests[Unit, integration, policy and security tests]
  Tests --> Replay[Historical replay and agent evals]
  Replay --> PR[Pull request with evidence]
  PR --> Gate{Risk-dependent review gate}
  Gate -->|rejected| Revise[Revise or abandon]
  Revise --> Proposal
  Gate -->|approved| Build[Signed artifact and SBOM]
  Build --> Stage[Staging]
  Stage --> Canary[Limited canary]
  Canary --> Observe[Observe guardrails and intended outcome]
  Observe --> Decide{Promote, modify or roll back?}
  Decide -->|promote| Prod[Production]
  Decide -->|modify| Proposal
  Decide -->|rollback| Rollback[Previous digest and config]
```

### 9. V1 deployment architecture

```mermaid
flowchart TB
  Owner[Owner device] -->|Tailscale or LAN| Console[Private Owner Console]
  Console --> API[Melloa core API]
  Telegram[Optional Telegram Bot API] <-->|outbound HTTPS long polling| TG[Telegram adapter]
  TG --> API

  subgraph MiniPC[Wired Linux mini-PC]
    subgraph Compose[Rootless Docker Compose]
      Console --> API
      API --> DB[(PostgreSQL and pgvector)]
      Worker[Melloa worker] --> DB
      API --> Broker[Capability broker]
      API --> Gateway[Model gateway]
      Perception[Frigate or perception adapter] --> API
      API --> Blobs[(Content-addressed blobs)]
      OTel[OpenTelemetry collector] -. telemetry .- API
      OTel -. telemetry .- Worker
    end
    Guardian[Guardian: systemd, firewall and revoke]
    Backup[restic backup]
  end

  Camera[PoE ONVIF and RTSP camera] --> Perception
  Gateway -->|eligible calls| Models[Approved model APIs]
  Backup --> DB
  Backup --> Blobs
  Backup -->|encrypted| Offsite[Offsite backup]
  Guardian -. stop and constrain .-> Compose
  Compose --x Guardian
```

### 10. Credential flow

```mermaid
sequenceDiagram
  participant Owner
  participant Root as Owner keyring or SOPS root
  participant Broker as Credential broker
  participant Policy
  participant Adapter as Capability adapter
  participant Provider
  participant Audit

  Owner->>Root: provision scoped provider credential
  Root->>Broker: encrypted reference or wrapped secret
  Adapter->>Broker: request lease for exact authorized action
  Broker->>Policy: verify actor, action, scope, budget, mode
  Policy-->>Broker: allow with constraints or deny
  Broker->>Broker: unwrap or mint short-lived scoped lease
  Broker-->>Adapter: lease bound to capability and action
  Adapter->>Provider: execute over approved destination
  Provider-->>Adapter: result or receipt
  Adapter->>Audit: action, lease reference, result, cost
  Adapter->>Broker: close or revoke lease
  Note over Adapter,Provider: Melli never receives a general secret bundle
```

### 11. Kill-switch architecture

```mermaid
flowchart LR
  Owner[Owner local or private authenticated path] --> Guardian[Guardian]
  Physical[Physical network or power cutoff] --> Host[Host and network]
  Guardian --> Mode[Signed mode: normal, no-actions, read-only, offline, stopped]
  Guardian --> Firewall[Block external egress]
  Guardian --> Revoke[Remove or revoke credentials]
  Guardian --> Services[Stop rootless workloads]
  Guardian --> Recovery[Start recovery and diagnostics]
  Mode --> Core[Melloa core reads mode only]
  Firewall --> Core
  Revoke --> Broker[Capability broker]
  Services --> Runtime[Autonomous runtime]
  Core --x Guardian
  Runtime --x Guardian
```

### 12. Permission and capability architecture

```mermaid
flowchart TB
  Install[Plugin installed] --> Declared[Declared capabilities, schemas, risk and data classes]
  Declared --> Disabled[Disabled by default]
  Owner[Owner] --> Grant[Capability grant with scope, expiry and budget]
  Grant --> Registry[Capability registry]
  Proposal[Action proposal] --> Canonical[Canonical exact action]
  Canonical --> Request[Authorization request]
  Registry --> Request
  Policy[Versioned policy] --> Decision[Decision engine]
  Request --> Decision
  Guardian[Guardian mode] --> Decision
  Decision --> Deny[Deny with reason]
  Decision --> Approve[Require exact owner approval]
  Decision --> Allow[Allow with obligations]
  Approve --> Bound[Approval bound to action hash and expiry]
  Bound --> Decision
  Allow --> Lease[Scoped credential and resource lease]
  Lease --> Execute[Capability execution]
  Execute --> Receipt[Result, side effects and audit receipt]
```

### 13. Goal hierarchy

```mermaid
flowchart TB
  Values[Values and non-negotiable constraints] --> Objectives[Long-term objectives]
  Objectives --> Goals[Current goals]
  Goals --> Strategies[Strategies]
  Strategies --> Hypotheses[Hypotheses]
  Hypotheses --> Experiments[Experiments or interventions]
  Experiments --> Actions[Actions]
  Actions --> Outcomes[Observed outcomes]
  Outcomes --> Evaluation[Evaluation with uncertainty and burden]
  Evaluation --> Strategies
  Evaluation --> Goals
  Conflicts[Competing goals and guardrails] --> Goals
  Owner[Owner review and override] --> Values
  Owner --> Goals
  Owner --> Experiments
```

### 14. Periodic reasoning loops

```mermaid
flowchart LR
  Continuous[Continuous: capture, validate, detect] --> Minutes[Minutes: interpret and update context]
  Minutes --> Daily[Daily: summarize new evidence and goal relevance]
  Daily --> Weekly[Weekly: patterns, intervention review, permission and cost anomalies]
  Weekly --> Monthly[Monthly: strategy, retention, archive, cost and capability review]
  Monthly --> Occasional[Occasional: propose new tool or integration]
  Occasional --> Change[Controlled change pipeline]
  Change --> Continuous
  Noop[No-op is a valid output] -. applies .-> Daily
  Noop -. applies .-> Weekly
  Budgets[Token, cost, interruption and freshness budgets] --> Daily
  Budgets --> Weekly
  Budgets --> Monthly
```

### 15. Data lifecycle

```mermaid
stateDiagram-v2
  [*] --> Collected
  Collected --> Quarantined: untrusted or invalid pending review
  Collected --> Active: validated and classified
  Quarantined --> Deleted: expiry or rejection
  Quarantined --> Active: validated and promoted
  Active --> Derived: interpretation, summary, embedding or projection
  Active --> Archived: lower-access retention tier
  Derived --> Superseded: correction or new version
  Superseded --> Archived
  Active --> DeletionPending: owner request or TTL
  Derived --> DeletionPending: source deletion or TTL
  Archived --> DeletionPending: retention expiry
  DeletionPending --> Deleted: primary stores erased and receipts written
  Deleted --> BackupExpiry: encrypted backup copies age out
  BackupExpiry --> [*]
```

### 16. Plugin and module interface

```mermaid
classDiagram
  class CapabilityManifest {
    +name
    +version
    +provider
    +actions
    +inputSchemas
    +outputSchemas
    +permissions
    +riskLevels
    +dataClasses
    +costModel
    +healthContract
  }
  class CapabilityAdapter {
    +describe()
    +validate(action)
    +execute(authorization, lease)
    +health()
    +close()
  }
  class CapabilityBroker {
    +authorize(request)
    +leaseCredential(decision)
    +recordReceipt(result)
  }
  class PolicyDecision {
    +effect
    +reason
    +constraints
    +obligations
    +approvalRequirement
    +policyVersion
  }
  class EventEnvelope {
    +id
    +type
    +schemaVersion
    +source
    +occurredAt
    +sensitivity
    +provenance
    +payload
  }
  CapabilityManifest --> CapabilityAdapter
  CapabilityBroker --> CapabilityAdapter
  CapabilityBroker --> PolicyDecision
  CapabilityAdapter --> EventEnvelope
```

### 17. Network topology

```mermaid
flowchart TB
  Internet((Internet))
  OwnerDevice[Owner laptop or phone]
  Router[Router and firewall]

  subgraph Admin[Admin network]
    OwnerDevice
  end

  subgraph Server[Server VLAN]
    MiniPC[Melloa mini-PC]
    Core[Core and DB]
    Guardian[Guardian]
    MiniPC --> Core
    MiniPC --> Guardian
  end

  subgraph Cameras[Camera VLAN]
    Cam[PoE camera]
  end

  subgraph SandboxNet[Sandbox network]
    Sandbox[Disposable sandbox]
  end

  OwnerDevice -->|Tailscale or LAN plus app auth| Console[Private Owner Console]
  Console --> Core
  OwnerDevice -->|separate owner auth| Guardian
  Cam -->|RTSP and ONVIF only| MiniPC
  Cam --x Internet
  Core -->|explicit HTTPS egress| Internet
  Sandbox -->|default deny; temporary allowlist| Internet
  Sandbox --x Core
  Router --> Admin
  Router --> Server
  Router --> Cameras
```

### 18. CI and CD flow

```mermaid
flowchart LR
  Branch[Agent or human branch] --> Static[Format, type, lint, secret scan]
  Static --> Unit[Unit and property tests]
  Unit --> Contract[Schema and migration compatibility]
  Contract --> Security[Dependency, license and security checks]
  Security --> Replay[Replay and model evals]
  Replay --> PR[Evidence-rich pull request]
  PR --> Review{CODEOWNERS and risk gate}
  Review -->|reject| Branch
  Review -->|approve| Build[Build pinned image]
  Build --> SBOM[SBOM, provenance and signature]
  SBOM --> Stage[Staging on scrubbed or replay data]
  Stage --> Canary[Bounded canary]
  Canary --> Metrics[Guardrails, costs and outcomes]
  Metrics -->|pass| Promote[Promote exact digest]
  Metrics -->|fail| Rollback[Automatic or owner rollback]
```

### 19. Threat model

```mermaid
flowchart TB
  Attacker[Internet or local attacker]
  MaliciousData[Malicious web, message, document or visible text]
  Supply[Compromised dependency or contributor]
  Provider[Compromised provider account or model]
  LostDevice[Stolen owner device]
  Agent[Compromised autonomous agent]

  Inputs[Untrusted input boundary]
  Build[Build and supply chain]
  Auth[Owner and capability auth]
  Secrets[Secrets and credential broker]
  Data[Personal data and memory]
  Actions[External side effects]
  Guardian[Guardian]

  MaliciousData --> Inputs --> Agent
  Supply --> Build --> Agent
  Provider --> Agent
  LostDevice --> Auth
  Attacker --> Inputs
  Attacker --> Auth
  Agent --> Secrets
  Agent --> Data
  Agent --> Actions

  Controls[Validation, taint, policy, sandbox, egress, scopes, audit] --> Inputs
  Controls --> Build
  Controls --> Auth
  Controls --> Secrets
  Controls --> Actions
  Guardian -. revoke and stop .-> Agent
  Agent --x Guardian
```

### 20. Onboarding flow

```mermaid
flowchart TB
  Empty[Empty supported Linux machine] --> Host[Patch, users, disk, SSH and time]
  Host --> Network[Private access and firewall]
  Network --> Clone[Clone and verify pinned release]
  Clone --> Doctor[Run doctor and inspect planned changes]
  Doctor --> Init[Create owner and Melli identities]
  Init --> Secrets[Configure age, SOPS and scoped API keys]
  Secrets --> Core[Start Postgres and core in no-actions mode]
  Core --> Migrate[Run migrations and deep health check]
  Migrate --> Console[Authenticate to private Owner Console]
  Console --> Validate[Conversation, fake model, policy denial, correction and audit tests]
  Validate --> Telegram[Optionally pair exact Telegram owner IDs locally]
  Telegram --> Guardian[Install and exercise independent Guardian]
  Guardian --> Backup[Backup and restore on clean machine]
  Backup --> Actions[Enable conservative ordinary actions]
  Actions --> Camera[Optionally add isolated and calibrated camera]
```

### 21. Realistic room-event to intervention sequence

```mermaid
sequenceDiagram
  participant Cam as Camera
  participant P as Perception
  participant Core as Core
  participant DB as Event and memory store
  participant Melli
  participant Policy
  participant Owner
  participant Change as Change pipeline

  Cam->>P: scene changes
  P->>P: segment and run local detector
  P->>Core: person entered candidate, confidence and evidence hashes
  Core->>DB: append observation and interpretation
  Core->>Melli: assess immediate relevance
  Melli->>Policy: no external action proposal
  Policy-->>Melli: allowed
  Melli->>DB: record decision and evidence IDs

  Note over DB,Melli: Daily reflection later
  Melli->>DB: retrieve recent routine events and corrections
  Melli->>DB: write uncertain pattern hypothesis
  Melli->>Owner: propose bounded reminder experiment
  Owner-->>Melli: approve exact experiment
  Melli->>Policy: request schedule and owner-only message capability
  Policy-->>Melli: allow with budget and expiry
  Melli->>Change: implement and test low-risk workflow
  Change-->>Melli: signed canary artifact
  Melli->>Policy: deploy canary request
  Policy-->>Melli: allow reversible internal class
  Melli->>DB: intervention and deployment records
  Note over Cam,DB: Outcomes arrive over subsequent days
  Melli->>DB: evaluate observed behavior, owner feedback and confounders
  Melli->>Owner: report useful, harmful or inconclusive result
```

### 22. Provenance entity relationships

```mermaid
erDiagram
  SOURCE ||--o{ OBSERVATION : emits
  OBSERVATION ||--o{ EVIDENCE_LINK : has
  BLOB ||--o{ EVIDENCE_LINK : referenced_by
  OBSERVATION ||--o{ INTERPRETATION : interpreted_as
  MODEL_RUN ||--o{ INTERPRETATION : produced
  INTERPRETATION ||--o{ ASSERTION : supports
  ASSERTION ||--o{ ASSERTION_EVIDENCE : justified_by
  OBSERVATION ||--o{ ASSERTION_EVIDENCE : evidence_for
  ASSERTION ||--o{ ASSERTION_RELATION : supersedes_or_disputes
  ASSERTION ||--o{ BELIEF_PROJECTION : projects
  OWNER_CONFIRMATION ||--o{ ASSERTION : confirms_or_corrects
  GOAL ||--o{ HYPOTHESIS : motivates
  HYPOTHESIS ||--o{ INTERVENTION : tested_by
  INTERVENTION ||--o{ ACTION : contains
  ACTION ||--|| POLICY_DECISION : authorized_by
  ACTION ||--o{ OUTCOME : produces
  OUTCOME ||--o{ EVALUATION : assessed_by
  CHANGE_PROPOSAL ||--o{ DEPLOYMENT : becomes
  DEPLOYMENT ||--o{ OUTCOME : observed_through
```

### 23. Guardian state machine

```mermaid
stateDiagram-v2
  [*] --> Stopped
  Stopped --> Offline: owner starts local-only services
  Offline --> ReadOnly: permit reads and local analysis
  ReadOnly --> NoActions: permit state updates but no side effects
  NoActions --> Normal: owner enables policy-bounded actions
  Normal --> NoActions: suspicious action or owner pause
  Normal --> Offline: provider or network incident
  Normal --> Stopped: emergency stop
  NoActions --> ReadOnly: integrity or migration incident
  Offline --> Stopped: host or credential incident
  ReadOnly --> Stopped: recovery escalation
  Stopped --> Recovery: owner enters isolated diagnostics
  Recovery --> Stopped: repair complete, restart requires explicit transition
  note right of Normal
    Melli cannot change Guardian state.
    Core consumes signed/read-only mode.
  end note
```

### 24. Replay and simulation architecture

```mermaid
flowchart LR
  Snapshot[Historical state snapshot] --> Engine[Replay engine]
  Events[Versioned event stream] --> Engine
  Clock[Virtual clock] --> Engine
  Policy[Policy version under test] --> Engine
  Route[Model or prompt under test] --> Engine
  FakeCaps[Simulated capability receipts] --> Engine
  Engine --> Runs[Candidate runs with side effects disabled]
  Runs --> Compare[Compare decisions, calls, cost, latency and privacy]
  Baseline[Baseline expectations and distributions] --> Compare
  Compare --> Gate{Release thresholds}
  Gate -->|pass| Evidence[Attach evidence to change proposal]
  Gate -->|fail| Diagnose[Failure clusters and regression cases]
  Diagnose --> Route
```

### 25. Identity continuity and worker lifecycle

```mermaid
flowchart TB
  Melloa[Melloa runtime and deployment] --> Registry[Persistent intelligence registry]
  Registry --> Melli[Melli identity]
  Melli --> Memory[Long-term memory and relationships]
  Melli --> Goals[Goals, values and policies]
  Melli --> History[Change and interaction history]
  Melli --> Session[Reasoning run]
  Session --> ModelA[Foundation model A]
  Session --> ModelB[Foundation model B]
  Session --> Worker[Ephemeral specialist worker]
  Worker --> Tools[Scoped tools and context]
  Worker --> Result[Result and evidence]
  Result --> Session
  ModelA -. replaceable .-> Session
  ModelB -. replaceable .-> Session
  Session -. terminates .-> Melli
  note right of Melli
    Identity does not equal model,
    process, session or provider.
  end note
```

### 26. Schema evolution and replay

```mermaid
flowchart TB
  V1[Event schema v1] --> Envelope[Stable envelope and immutable payload version]
  V2[Event schema v2] --> Envelope
  Envelope --> Store[(Canonical store)]
  Store --> Reader1[v1 reader or adapter]
  Store --> Reader2[v2 reader]
  V1 --> Upcast[Explicit v1 to v2 upcaster]
  Upcast --> Reader2
  Store --> Replay[Replay harness]
  Replay --> Projection[Rebuild current projection and indexes]
  Projection --> Verify[Compatibility and semantic invariant checks]
  Verify --> Deploy[Deploy new readers]
  Deploy --> Contract[Later contract or retire old field]
  Raw[Preserved source evidence where justified] --> Replay
```

### Diagram maintenance rules

- Update a diagram in the same pull request as the boundary it documents.
- Use direction and labels to show authority, not only connectivity.
- Mark forbidden paths and external trust explicitly.
- Do not show a future component as if it exists in V1.
- Keep canonical component names consistent with the conceptual model.
- Render diagrams in CI or at least parse-check Mermaid fences before release.

---

<a id="doc-adr-index"></a>

## Architecture Decision Records

ADRs record the decision, rejected alternatives, consequences, and the evidence that should trigger reconsideration. Accepted ADRs remain visible if later superseded.

| ADR | Decision |
|---|---|
| [ADR-001](#doc-adr-adr-001-event-oriented-provenance-ledger) | Event-oriented provenance ledger with current relational projections, not pure event sourcing |
| [ADR-002](#doc-adr-adr-002-postgresql-primary-store-and-jobs) | PostgreSQL as V1 primary store and durable work queue |
| [ADR-003](#doc-adr-adr-003-policy-aware-model-routing) | Policy-aware model routing by adequacy, privacy, latency, and cost |
| [ADR-004](#doc-adr-adr-004-scoped-credential-broker) | Scoped credential broker with SOPS/age bootstrap |
| [ADR-005](#doc-adr-adr-005-rootless-containers-and-tiered-sandbox) | Rootless containers and tiered isolation for generated code |
| [ADR-006](#doc-adr-adr-006-mkdocs-mermaid-adrs) | MkDocs, Mermaid, and ADRs as documentation infrastructure |
| [ADR-007](#doc-adr-adr-007-poe-onvif-rtsp-camera) | Wired PoE ONVIF Profile T/RTSP camera |
| [ADR-008](#doc-adr-adr-008-independent-guardian) | Owner-controlled Guardian outside the autonomous plane |
| [ADR-009](#doc-adr-adr-009-telegram-long-polling) | Telegram long polling as an optional secondary owner channel |
| [ADR-010](#doc-adr-adr-010-framework-neutral-stable-primitives) | Stable primitives and framework-neutral durable logic |
| [ADR-011](#doc-adr-adr-011-one-melli-temporary-specialists) | One persistent Melli with ephemeral specialists |
| [ADR-012](#doc-adr-adr-012-private-network-no-public-ingress) | Private networking and no public application ingress in V1 |
| [ADR-013](#doc-adr-adr-013-melloa-naming-and-intellectual-lineage) | Adopt Melloa naming and intellectual lineage |
| [ADR-014](#doc-adr-adr-014-private-owner-console-and-conversation) | Mandatory private Owner Console and canonical conversation |

---

<a id="doc-adr-adr-001-event-oriented-provenance-ledger"></a>

## ADR-001: Use an event-oriented provenance ledger, not pure event sourcing

- **Status:** Accepted for V1
- **Date:** 2026-08-15

### Context

Melloa must preserve why it believed and did things over years. Observations, interpretations, corrections, authorizations, actions, outcomes, and software changes need durable history and replay. Pure CRUD loses history; pure event sourcing makes every current object dependent on indefinite replay and difficult schema evolution.

### Decision

Store append-oriented canonical records for evidence, interpretations, assertions, corrections, decisions, actions, outcomes, and audit. Maintain ordinary relational current-state projections for operational reads. Raw high-volume evidence has explicit retention; stable envelopes retain schema/source/provenance metadata. Rebuild derived indexes and selected projections through replay.

### Alternatives considered

- **CRUD only:** simple, but cannot reconstruct belief/action lineage reliably.
- **Pure event sourcing:** maximally replayable, but imposes unnecessary operational and migration complexity.
- **External event bus as source of truth:** duplicates durable state and complicates backup/recovery for one user.

### Consequences

- Every derived claim and side effect has traceable parents.
- Corrections append rather than silently overwrite history.
- Projection/replay code is required and must be tested.
- Retention and deletion need tombstones and derived-data rebuilds.

### Revisit when

Replay cost or independent consumer scale exceeds PostgreSQL thresholds, or a clear domain benefits from stricter event-sourced state. Do not generalize that need to every domain automatically.

---

<a id="doc-adr-adr-002-postgresql-primary-store-and-jobs"></a>

## ADR-002: Use PostgreSQL as the V1 primary store and durable work queue

- **Status:** Accepted for V1
- **Date:** 2026-08-15

### Context

Melloa needs transactions, relational queries, JSON, full text, migrations, authorization roles, semantic retrieval, and durable asynchronous work. A separate queue, graph database, vector database, and workflow engine would create multiple recovery authorities before scale justifies them.

### Decision

Use PostgreSQL 18 as the sole operational source of truth. Use tables for events/provenance, current projections, goals/policies, jobs/outbox, audit, and metadata. Use `pgvector` for rebuildable embeddings. Workers poll durable jobs with leases and idempotency; `LISTEN/NOTIFY` is only a latency hint.

### Alternatives considered

- SQLite: excellent simplicity, but weaker fit for concurrent workers, roles, remote tooling, and future edge/process split.
- NATS JetStream or Kafka/Redpanda: durable streams but another distributed state/operations system.
- Redis Streams: convenient queue, but adds a second persistence/recovery system.
- Temporal: strong workflows, excessive for initial bounded jobs.
- Graph/vector database: specialized retrieval, not canonical truth/provenance.

### Consequences

- One database to back up, migrate, and restore.
- At-least-once semantics and idempotency are explicit.
- Long-running workflow logic must remain visible state machines until a workflow engine is justified.
- Workload isolation and DB connection/lock monitoring matter.

### Revisit when

Sustained backlog violates recovery objectives; more than three independently deployed nodes require streaming; workflows span days with complex compensation/signals; or database contention cannot be solved without harming core state.

---

<a id="doc-adr-adr-003-policy-aware-model-routing"></a>

## ADR-003: Route models by adequacy, privacy, latency, and cost

- **Status:** Accepted for V1
- **Date:** 2026-08-15

### Context

One model cannot economically or safely handle every sensor tick, extraction, conversation, multimodal interpretation, coding task, and strategic review. Local-only can reduce quality; cloud-only can leak data and create cost/dependency risk.

### Decision

Create a provider-neutral model gateway. Every request declares task, modality, minimum quality, sensitivity/provider eligibility, context limit, latency, cost ceiling, output schema, and fallback. Tier 0 uses no model, Tier 1 local/tiny models, Tier 2 medium models, Tier 3 frontier models. A result remains untrusted data until validated; model choice never grants capability authority.

### Alternatives considered

- Single frontier model: simple but expensive, high disclosure, fragile provider dependency.
- Local-only: private but may be inadequate for difficult reasoning/multimodal work.
- Agent framework router: fast to adopt, but couples durable architecture to a transient library.

### Consequences

- Route/version/disclosure/cost records are mandatory.
- Evaluation suites compare model routes statistically.
- Provider terms and prices are versioned operational inputs.
- Fallback cannot silently broaden privacy or cost.

### Revisit when

Measured task distributions support fewer tiers, a local model consistently meets quality/cost targets, or provider-specific capabilities require a carefully isolated extension.

---

<a id="doc-adr-adr-004-scoped-credential-broker"></a>

## ADR-004: Broker scoped credentials; use SOPS and OS key storage for bootstrap

- **Status:** Accepted for V1
- **Date:** 2026-08-15

### Context

Melloa may eventually access deeply sensitive APIs. Giving an autonomous process a giant `.env` creates one catastrophic compromise domain. Running Vault/OpenBao on day one adds another critical availability and recovery service.

### Decision

Store bootstrap/deployment secrets encrypted with SOPS and age, with private identities in the owner-controlled OS/offline recovery path. A capability broker unwraps, mints, or supplies narrowly scoped credentials only after deterministic authorization. Adapters receive action-bound leases or handles, not the entire secret inventory. Use separate provider-side scopes, environments, budgets, and rotation.

### Alternatives considered

- Plain `.env`: easy but ambient, leak-prone, and overbroad.
- Cloud-only secret manager: ties local recovery to cloud/IAM and may expose a control plane.
- OpenBao/Vault immediately: powerful dynamic credentials, excessive operational burden before multi-node/dynamic need.

### Consequences

- Credential issuance/access is auditable.
- Some APIs with coarse tokens still create residual authority; network/budget controls compensate.
- Recovery-key custody and rotation runbooks become critical.
- Broker failure stops side effects rather than bypassing policy.

### Revisit when

Multiple hosts/workloads require identity-based dynamic secrets, rotation frequency becomes unmanageable, or short-lived credentials are broadly available. Introduce OpenBao/workload identity behind the existing broker interface.

---

<a id="doc-adr-adr-005-rootless-containers-and-tiered-sandbox"></a>

## ADR-005: Use rootless containers and add stronger isolation only for hostile workloads

- **Status:** Accepted for V1
- **Date:** 2026-08-15

### Context

Core services need reproducible isolation. Future generated code must be treated as hostile. Kubernetes and microVM fleets are not justified before generated execution exists.

### Decision

Run normal services under rootless Docker Compose with non-root users, dropped capabilities, read-only filesystems where practical, separate networks/volumes, and no Docker socket. Generated code, when enabled, uses disposable rootless sandboxes with default-deny egress, no production data/secrets, hard quotas, and gVisor where compatible. Firecracker is a future stronger tier.

### Alternatives considered

- Host processes: fewer layers but weaker reproducibility/isolation.
- Rootful Docker with socket access: broad host-compromise path.
- Kubernetes: unnecessary control-plane burden for one host.
- Firecracker for everything: stronger isolation but substantial image/network/operations complexity.

### Consequences

- Rootless compatibility and filesystem/network constraints must be tested.
- Containers are not assumed to be a perfect security boundary.
- Generated-code features cannot launch until the stronger sandbox and policy path exist.

### Revisit when

Hostile workload frequency, multi-tenancy, regulatory needs, or kernel attack surface justifies microVMs/dedicated sandbox nodes.

---

<a id="doc-adr-adr-006-mkdocs-mermaid-adrs"></a>

## ADR-006: Treat documentation as infrastructure using MkDocs, Mermaid, and ADRs

- **Status:** Accepted for V1
- **Date:** 2026-08-15

### Context

A seven-year personal system will fail through forgotten rationale and tribal knowledge as readily as through code defects. Diagrams and operational knowledge must remain reviewable with source changes.

### Decision

Keep Markdown documentation in the monorepo, publish/build with MkDocs Material, draw architecture in Mermaid, and record significant choices as immutable/supersedable ADRs. PR gates require documentation for schema, trust, policy, data-flow, operation, and user-interface changes.

### Alternatives considered

- Wiki/Notion only: easy editing but weak version/PR coupling and export durability.
- Docusaurus: strong site platform, heavier JavaScript stack than needed.
- Sphinx: excellent for Python/API docs, less direct fit for broad architecture/operator prose.
- Image-only diagrams: hard to diff and become stale.

### Consequences

- Documentation build/link/diagram checks become CI responsibilities.
- Canonical pages and ownership must prevent duplication.
- Sensitive personal deployment details stay outside public docs.

### Revisit when

Large multi-version API documentation or a product web experience justifies another frontend. Preserve Markdown and ADR data for migration.

---

<a id="doc-adr-adr-007-poe-onvif-rtsp-camera"></a>

## ADR-007: Bless a wired PoE ONVIF Profile T and RTSP camera

- **Status:** Accepted for V1 camera phase
- **Date:** 2026-08-15

### Context

The initial vision capability needs reliable local streaming, low-light options, vendor independence, and network isolation. Consumer cloud cameras can require vendor services, opaque processing, and Wi-Fi reliability.

### Decision

Use a wired PoE IP camera supporting ONVIF Profile T and a local RTSP stream. Place it on a camera VLAN with no internet access. Pull media only from the perception adapter. Use unique credentials, current firmware, visible/private-space placement, and a local short ring buffer with selected event clips.

### Alternatives considered

- USB camera: simple and private, but cable-length/placement and host dependency can be awkward.
- Raspberry Pi CSI camera: flexible edge build, but more DIY hardware/OS maintenance.
- Wi-Fi/cloud camera: convenient but weaker reliability/privacy/vendor independence.
- WebRTC-native camera: useful for interactive viewing, less universal for stable acquisition.

### Consequences

- PoE switch/injector and cabling are required.
- ONVIF conformance does not guarantee perfect interoperability; test the exact model.
- Camera compromise remains possible, so no analytics output is trusted as fact.
- Visitor/third-party consent and retention are product requirements.

### Revisit when

A different physical environment makes USB/CSI materially simpler, multiple sites require edge nodes, or the selected model’s RTSP/low-light quality fails calibration.

---

<a id="doc-adr-adr-008-independent-guardian"></a>

## ADR-008: Separate an owner-controlled Guardian from the autonomous plane

- **Status:** Accepted and non-negotiable for V1
- **Date:** 2026-08-15

### Context

An autonomous system must not hold the privileges needed to disable its own shutdown, expand its governance, erase audit, or preserve its credentials against the owner. A prompt instruction to “obey the kill switch” is not a security boundary.

### Decision

Run a minimal root-owned Guardian outside rootless Melloa containers. It owns signed/read-only operating modes, service stop/start, host egress rules, credential removal/revocation, and recovery entry. Owner authentication/recovery credentials are separate. Melli can observe mode and request changes but cannot modify Guardian code, configuration, repository, credentials, or state.

### Alternatives considered

- In-process kill switch: compromised process can bypass it.
- Container orchestrator permissions granted to Melli: broad privilege escalation.
- Cloud-only emergency control: unavailable during account/network compromise.
- Physical power switch only: useful last resort but too coarse for read-only/offline recovery.

### Consequences

- Guardian code and operations must remain small and independently reviewed.
- The owner needs a local/private authenticated path and recovery-key custody.
- Some incidents still require physical network/power isolation.
- Guardian availability can block actions; fail closed is intentional.

### Revisit when

Multiple sites/nodes require a distributed owner control plane. Preserve the invariant that autonomous credentials cannot remove ultimate owner authority.

---

<a id="doc-adr-adr-009-telegram-long-polling"></a>

## ADR-009: Use Telegram long polling as an optional secondary owner channel

- **Status:** Accepted; clarified by ADR-014
- **Date:** 2026-08-15
- **Clarified:** 2026-08-16

### Context

The owner benefits from concise remote text, attachments, approvals, corrections, and proactive notifications. Public webhooks add ingress. Telegram bots are convenient but do not provide the same confidentiality or inspectability as Melloa's private first-party client.

### Decision

Provide a Telegram Bot API adapter using `getUpdates` long polling with one exactly paired and allowlisted owner user/private chat. Normalize all messages into canonical Melloa conversation records. Keep highly sensitive content, raw room media, secrets, exports, and Guardian-root operations off-channel by default.

Telegram is optional and secondary. The private Owner Console defined by ADR-014 is the primary client. Melloa remains fully operable locally when Telegram is absent or unavailable.

### Alternatives considered

- Telegram as the only V1 UI: easy, but insufficient for provenance, media, policy, health, and high-trust control.
- Public webhook: lower inbound latency but unnecessary internet ingress.
- Native mobile application: stronger long-term experience but larger initial product and release burden.
- Matrix: open and E2EE-capable, but heavier homeserver/client/key operations.

### Consequences

- No public webhook or domain is required.
- Telegram/cloud retains a copy under its own policies.
- Critical owner control uses the Guardian/private authentication path.
- Telegram identifiers remain adapter metadata rather than owner, intelligence, or conversation identity.
- The adapter can be disabled without changing canonical history or Melli's continuity.

### Revisit when

A different transport is more useful, privacy requirements change, or a native client provides better remote interaction. The canonical conversation contract remains stable.

---

<a id="doc-adr-adr-010-framework-neutral-stable-primitives"></a>

## ADR-010: Keep durable logic independent of agent frameworks

- **Status:** Accepted for V1
- **Date:** 2026-08-15

### Context

Agent frameworks and model APIs change rapidly. Melloa’s identity, memory, policy, actions, and operational history must survive provider/library replacement over many years.

### Decision

Express durable behavior through domain models, versioned schemas, processes, PostgreSQL state, queues/jobs, typed ports, and explicit capability/model adapters. An agent/coding/MCP framework may implement an adapter or orchestration detail but cannot own canonical memory, policy, identity, or action authorization. Every selected framework has an escape test and export/replay path.

### Alternatives considered

- Adopt one agent framework as the application architecture: fast prototype, high semantic and lifecycle lock-in.
- Build all model/tool protocol details from scratch: excessive reinvention and compatibility burden.

### Consequences

- Some adapter boilerplate and explicit state machines are required.
- Framework upgrades become bounded replacements rather than data migrations.
- Melloa can adopt MCP or future protocols selectively.

### Revisit when

A framework demonstrates multi-year stability and offers a capability Melloa cannot reasonably reproduce. Even then, canonical state and authority remain external.

---

<a id="doc-adr-adr-011-one-melli-temporary-specialists"></a>

## ADR-011: Start with one persistent Melli and ephemeral specialists

- **Status:** Accepted for V1
- **Date:** 2026-08-15

### Context

The architecture must support multiple persistent intelligences eventually, but multiple names/processes do not automatically improve reasoning. They introduce authority, memory, accountability, communication, and identity-continuity problems.

### Decision

Instantiate one persistent intelligence, Melli. Create temporary specialist workers for research, review, coding, security, or planning within a parent run/proposal and scoped policy context. A specialist result is evidence/advice, not an independent authority. Add a persistent intelligence only for a durable distinct identity, relationship, responsibility, memory scope, and permission boundary.

### Alternatives considered

- Permanent role-agent swarm: parallel perspectives but unclear accountability and duplicated/conflicting memory.
- One undifferentiated prompt/process: simpler but cannot isolate temporary contexts/tools or future identities.

### Consequences

- Melli retains accountable continuity while model/processes change.
- Specialist workers must return source/evidence and cannot silently write long-term memory.
- The persistent-intelligence registry/schema exists without premature agent society.

### Revisit when

A concrete role requires continuing independent goals/relationships/permissions and its benefits exceed coordination/governance cost.

---

<a id="doc-adr-adr-012-private-network-no-public-ingress"></a>

## ADR-012: Use private networking and no public application ingress in V1

- **Status:** Accepted for V1
- **Date:** 2026-08-15

### Context

A one-owner deployment needs remote access but not public discovery. Telegram long polling and outbound provider calls eliminate inbound internet requirements. A domain, reverse proxy, certificates, and webhook endpoint would enlarge attack and operating surface.

### Decision

Bind owner/admin services to LAN/private interfaces and use Tailscale as the convenient default, with WireGuard-compatible migration. Keep host firewall default-deny. Camera VLAN has no internet. Generated sandboxes have default-deny egress. No public domain, port forwarding, or public reverse proxy is required.

### Alternatives considered

- Public HTTPS domain: universally reachable but creates patching, auth, WAF/rate-limit, certificate, and incident burden.
- Cloud VM control plane: available remotely but moves authority/data and adds account/IAM dependency.
- LAN only: smallest exposure but weak remote usability and recovery.

### Consequences

- Owner access depends on private-network client/control availability, with LAN/console recovery.
- Application authentication remains required; network membership alone is insufficient.
- Future public integrations require a new threat review and ingress architecture.

### Revisit when

A specific capability cannot use outbound polling/private relay, or multiple users/sites need a carefully authenticated public endpoint.

---

<a id="doc-adr-adr-013-melloa-naming-and-intellectual-lineage"></a>

## ADR-013: Adopt Melloa naming and intellectual lineage

- **Status:** Accepted
- **Date:** 2026-08-16

### Context

The architecture requires stable distinctions between system, persistent intelligence, model, process, worker, client, and control plane. The project also benefits from a meaningful story rather than names assigned to arbitrary technical modules.

### Decision

- **Meliorism** is the guiding philosophy and purpose.
- **Melloa** is the system and intended public technical project. The repository is not open source until the owner adds explicit license terms.
- **Melli** is the primary persistent intelligence in an owner's deployment.
- **Guardian** remains the independent owner-controlled control plane.
- **Otto** is reserved as an optional Extended Mind reference and is not assigned to a V1 subsystem, synthetic owner, or mandatory agent.

The intellectual lineage includes meliorism, Licklider's human-computer symbiosis, Clark and Chalmers' extended-mind thesis, and Engelbart's augmentation of human intellect. [S64](#S64) [S65](#S65) [S66](#S66) [S67](#S67)

Durable code and schemas use neutral identifiers. Display names and naming history are data rather than type names or keys.

### Alternatives considered

- Rename the system to Meliorism: semantically strong, but less warm and discards the already meaningful Melloa/Melli distinction.
- Name every subsystem after a historical person or thought experiment: memorable but obscures responsibility and encourages architecture by mythology.
- Keep all names provisional indefinitely: avoids commitment but makes documentation and repositories inconsistent.

### Consequences

- Documentation can explain a coherent philosophy without creating extra agents.
- Melli may later choose or change a display name while retaining stable identity.
- Public-launch clearance remains a separate legal and brand gate.
- `Otto`, `Eliot`, `Nova`, `Charlie`, and similar names are available only when a real persistent identity or example requires one.

### Revisit when

Formal clearance reveals a material conflict or the project deliberately changes public brand. Domain identifiers and identity continuity must survive any brand change.

---

<a id="doc-adr-adr-014-private-owner-console-and-conversation"></a>

## ADR-014: Make the private Owner Console and canonical conversation mandatory in V1

- **Status:** Accepted
- **Date:** 2026-08-16

### Context

The owner needs to converse with Melli and inspect years of sensitive observations, uncertain interpretations, memories, actions, media, costs, disclosures, and system health. A terminal and messaging bot alone cannot provide the required visibility or correction experience. Public ingress is unnecessary for a one-owner deployment.

### Decision

Build a private, authenticated Owner Console as a V1 component. It is served only on local/private interfaces and is the primary first-party client for canonical Melloa conversations.

Persist conversations independently of clients and transports. Telegram long polling is an optional secondary adapter. The console exposes structured evidence and decision records rather than raw hidden chain-of-thought.

Guardian status may be displayed through a constrained read-only contract, but high-impact Guardian actions remain separately authenticated and outside ordinary Melloa authority.

### Alternatives considered

- Terminal plus Telegram only: simpler initially, but too weak for provenance, media, policy, correction, and operational inspection.
- Public web console: remotely convenient but unnecessarily enlarges attack and operating surface.
- Raw model reasoning trace viewer: unavailable or unreliable across providers, sensitive, and not a sound audit contract.
- Native application first: stronger device integration but slower to build and less portable than a private responsive web client.

### Consequences

- TypeScript becomes part of the blessed V1 language set for the web client, while domain authority remains in the Python/SQL backend.
- Conversation/thread/message contracts must be channel-independent from the first migration.
- Private-network membership does not replace application authentication.
- The console, API, docs, tests, backups, and runbooks evolve together.

### Revisit when

A native client or multi-device/offline requirement justifies another first-party client. The canonical conversation and inspection contracts remain the source of truth.

---

<a id="doc-research-method-and-limitations"></a>

## Research method and limitations

### Authority and scope

The supplied **Master Research Prompt: Design a Long-Lived Personal AI Operating System** is the requirements baseline. The suite preserves its distinction between Melloa (system/runtime) and Melli (persistent intelligence), its seven-year orientation, its Build now / Design for / Defer discipline, and its requirement to challenge the premise rather than merely elaborate it. The 16 August 2026 v0.2 decisions then adopt the naming lineage and promote the private Owner Console plus canonical conversation into V1; those decisions supersede conflicting product-priority wording without changing the original brief.

A verbatim copy is retained as [`master-research-brief.txt`](docs/research/master-research-brief.txt). SHA-256: `a59d29c06c884f86064e5223e92f3b996771ca1d34bc5fc7baaea18e0c3abcd9`.

This deliverable is architecture and research, not production implementation. Tiny schemas and command examples illustrate contracts; they are not production code.

### Method

1. Extracted the explicit outputs, cross-cutting constraints, diagrams, final questions, and decision requirements from the master brief.
2. Defined precise vocabulary so system, intelligence, identity, memory, process, model, provider, capability, action, and policy do not collapse into one concept.
3. Developed three plausible architectures and evaluated complexity, security, observability, autonomy, cost, and migration path.
4. Researched primary specifications and official documentation for rapidly changing technologies, provider policies, protocols, hardware, security guidance, pricing, and APIs.
5. Selected the simplest V1 that preserves expensive-to-retrofit boundaries: provenance, policy enforcement, provider/framework neutrality, owner control, replay, and export.
6. Simulated independent security, reliability, simplicity, AI-research, privacy, open-source, cost, and future-maintainer reviews.
7. Produced ADRs, a ranked risk register, failure/recovery behavior, quantitative estimates, and explicit rejected ideas/revisit triggers.
8. Performed structural checks over navigation, local links, source anchors, Markdown fences, and Mermaid block types; the package includes a machine-readable validation report.

### Evidence policy

- Prefer protocol specifications, official documentation, vendor policy/pricing pages, standards bodies, and peer-reviewed research.
- Use named projects for collision research because the existence of those projects is the relevant fact.
- Mark prices and provider terms as dated snapshots.
- Treat vendor security claims as intended behavior, not independent verification.
- Keep architectural recommendations distinct from source facts; recommendations synthesize requirements, trade-offs, and evidence.

### Important limitations

- No production code, penetration test, physical camera test, provider contract review, load test, or long-running behavioral study was performed.
- Mermaid diagrams were structurally linted in the available environment; a full MkDocs/mermaid renderer was not available locally because external package installation was blocked. Render them in CI before publication.
- Hardware recommendations deliberately specify interfaces and classes rather than a final camera SKU. Validate firmware support, ONVIF behavior, low-light quality, and local-only operation at purchase time.
- Naming research is preliminary discovery, not trademark/legal clearance.
- Model pricing, capabilities, retention, and data-use policies can change between research and implementation. Recheck at each provider-policy release and before routing sensitive data.
- Cost ranges are scenario estimates, not quotes. They exclude developer labour and depend strongly on inference frequency, context/media volume, hardware, tariffs, and exchange rates.
- Intervention evaluation cannot guarantee causal conclusions. Many personal outcomes will remain confounded or inconclusive.
- The selected architecture reduces but cannot eliminate compromise, mistaken approval, model regression, privacy exposure, or data loss.

### Decision confidence

High confidence:

- keep Melloa, Melli, model, process, memory, and capability distinct;
- preserve provenance and correction semantics;
- enforce side effects outside model reasoning;
- keep an independent Guardian and owner-controlled recovery;
- avoid Kubernetes/Kafka/permanent agent swarms in V1;
- use selective local camera processing and bounded raw retention;
- require tested restore and open export.

Medium confidence, requiring implementation evidence:

- PostgreSQL jobs/outbox remain sufficient through the first year;
- Frigate is the best initial perception adapter rather than a thinner custom pipeline;
- the private Owner Console is the primary first-party client while Telegram remains an optional secondary adapter;
- Cedar is the right later policy evaluator;
- local models provide enough value on the blessed host to justify an always-on endpoint.

Low confidence until tested:

- which proactive interventions create durable owner benefit;
- exact camera event-classification accuracy in the real room;
- when a second persistent intelligence is worth its governance cost;
- the economics of local versus hosted frontier inference over several years.

---

<a id="doc-research-primary-sources"></a>

## Primary-source register

**Research cut-off:** 15 August 2026  
**Use:** Evidence for date-sensitive architectural claims. This is not a vendor endorsement list. Re-check prices, product support, model names, policies, and security guidance at implementation/purchase time.

The master brief is the requirements baseline. Sources below are predominantly specifications, official documentation, vendor policy/pricing pages, or peer-reviewed research. A few naming-collision entries are project sites/repositories because collision research necessarily concerns those projects.

### Protocols, contracts, events, and workflows

<a id="S01"></a>
#### S01 — Model Context Protocol specification

- Source: [Model Context Protocol specification, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)
- Relevance: current protocol shape, JSON-RPC concepts, tools/resources, and versioning. Melloa treats MCP as an adapter boundary, not its authority or memory model.

<a id="S02"></a>
#### S02 — MCP authorization

- Source: [MCP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- Relevance: OAuth-based authorization discovery and resource-server behavior for remote MCP servers.

<a id="S03"></a>
#### S03 — MCP security guidance

- Source: [MCP security best practices](https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices)
- Relevance: token audience binding, no token passthrough, least privilege, and security considerations. Melloa still enforces its own broker/policy boundary.

<a id="S04"></a>
#### S04 — PostgreSQL 18 documentation

- Source: [PostgreSQL 18 documentation](https://www.postgresql.org/docs/18/)
- Relevance: primary relational store, transactions, roles, row security, JSON, full-text, locks, and operational behavior.

<a id="S05"></a>
#### S05 — pgvector

- Source: [pgvector project and documentation](https://github.com/pgvector/pgvector)
- Relevance: exact and approximate vector search within PostgreSQL. Used only as a rebuildable semantic index.

<a id="S06"></a>
#### S06 — Transactional outbox pattern

- Source: [AWS Prescriptive Guidance: transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
- Relevance: atomic state/outbox writes, at-least-once delivery, ordering and idempotency concerns.

<a id="S07"></a>
#### S07 — PostgreSQL LISTEN

- Source: [PostgreSQL 18 `LISTEN`](https://www.postgresql.org/docs/18/sql-listen.html)
- Relevance: asynchronous notification behavior. Used as a wake-up hint, never as the durable queue.

<a id="S08"></a>
#### S08 — NATS JetStream

- Source: [NATS JetStream concepts](https://docs.nats.io/nats-concepts/jetstream)
- Relevance: durable streams, replay, persistence, and consumer semantics; a credible post-V1 event-bus option if scale thresholds are crossed.

<a id="S09"></a>
#### S09 — Temporal

- Source: [Temporal documentation](https://docs.temporal.io/)
- Relevance: durable workflow execution and recovery. Deferred until long-running workflows exceed the maintainability of PostgreSQL jobs/state machines.

<a id="S10"></a>
#### S10 — CloudEvents

- Source: [CloudEvents specification project](https://cloudevents.io/)
- Relevance: interoperable event-envelope ideas. Melloa may borrow conventions without forcing all domain semantics into CloudEvents.

<a id="S11"></a>
#### S11 — JSON Schema 2020-12

- Source: [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)
- Relevance: open, versioned payload validation for events, capabilities, exports, and configuration.

<a id="S12"></a>
#### S12 — Buf breaking-change detection

- Source: [Buf breaking change detection](https://buf.build/docs/breaking/)
- Relevance: compatibility automation if protobuf/gRPC is introduced for edge or high-throughput services.

### Security, policy, and adversarial AI

<a id="S13"></a>
#### S13 — OWASP Top 10 for LLM applications

- Source: [OWASP Top 10 for Large Language Model Applications](https://genai.owasp.org/llm-top-10/)
- Relevance: current classes of model/application security risk.

<a id="S14"></a>
#### S14 — OWASP prompt injection

- Source: [OWASP LLM01: Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- Relevance: direct and indirect injection, multimodal/encoded inputs, and the fact that fine-tuning/RAG do not eliminate the problem.

<a id="S15"></a>
#### S15 — MITRE ATLAS

- Source: [MITRE ATLAS](https://atlas.mitre.org/)
- Relevance: adversarial tactics and techniques for AI-enabled systems; used to structure attack scenarios.

<a id="S16"></a>
#### S16 — NIST Generative AI profile

- Source: [NIST AI 600-1: Generative Artificial Intelligence Profile](https://doi.org/10.6028/NIST.AI.600-1)
- Relevance: risk framing and lifecycle controls for generative AI.

<a id="S17"></a>
#### S17 — Open Policy Agent

- Source: [Open Policy Agent documentation](https://www.openpolicyagent.org/docs/latest/)
- Relevance: general-purpose policy-as-code alternative. Useful comparison; not selected as the only V1 policy/user model.

<a id="S18"></a>
#### S18 — Cedar policy language

- Source: [Cedar policy language documentation](https://docs.cedarpolicy.com/)
- Relevance: authorization-focused policy model with explicit principal/action/resource/context concepts; credible future evaluator behind Melloa’s typed broker.

<a id="S19"></a>
#### S19 — OpenBao

- Source: [OpenBao documentation](https://openbao.org/docs/)
- Relevance: open-source secret management and dynamic credentials. Deferred until operational scale justifies another critical service.

<a id="S20"></a>
#### S20 — SOPS

- Source: [SOPS documentation](https://getsops.io/docs/)
- Relevance: encrypted configuration/secrets in Git, including age identities; selected for V1 bootstrap, not runtime ambient secret distribution.

<a id="S21"></a>
#### S21 — Docker rootless mode

- Source: [Docker Engine rootless mode](https://docs.docker.com/engine/security/rootless/)
- Relevance: running daemon and containers without root privileges; one isolation layer, not a complete hostile-code security boundary.

<a id="S22"></a>
#### S22 — gVisor

- Source: [gVisor documentation](https://gvisor.dev/docs/)
- Relevance: userspace application-kernel isolation for generated or untrusted workloads.

<a id="S56"></a>
#### S56 — Firecracker

- Source: [Firecracker microVM project](https://github.com/firecracker-microvm/firecracker)
- Relevance: stronger microVM isolation tier; deferred because image/network/operations complexity is not justified in V1.

<a id="S37"></a>
#### S37 — SLSA

- Source: [SLSA specification](https://slsa.dev/spec/)
- Relevance: vocabulary and controls for build provenance and supply-chain assurance.

<a id="S38"></a>
#### S38 — Sigstore and cosign

- Source: [Sigstore documentation](https://docs.sigstore.dev/)
- Relevance: artifact signing, identity, transparency, and verification without a bespoke signing system.

<a id="S39"></a>
#### S39 — GitHub rulesets

- Source: [GitHub: About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- Relevance: protected branch/tag behavior and required workflows for autonomous changes.

<a id="S63"></a>
#### S63 — Pinning GitHub Actions

- Source: [GitHub security hardening for Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions)
- Relevance: pin third-party actions to full-length commit SHAs and minimize workflow token authority.

### Cameras, perception, and edge hardware

<a id="S23"></a>
#### S23 — ONVIF Profile T

- Source: [ONVIF Profile T](https://www.onvif.org/profiles/profile-t/)
- Relevance: interoperable advanced video streaming features for IP cameras; selected over vendor-cloud lock-in.

<a id="S24"></a>
#### S24 — RTSP

- Source: [RFC 7826: Real-Time Streaming Protocol Version 2.0](https://www.rfc-editor.org/rfc/rfc7826.html)
- Relevance: standard media-control protocol context for local camera streaming.

<a id="S28"></a>
#### S28 — Frigate

- Source: [Frigate documentation](https://docs.frigate.video/)
- Relevance: local NVR/perception pipeline with motion filtering, object detection, and retention controls. Used behind a replaceable adapter.

<a id="S29"></a>
#### S29 — go2rtc

- Source: [go2rtc project](https://github.com/AlexxIT/go2rtc)
- Relevance: local camera-stream restreaming/compatibility layer often paired with Frigate.

<a id="S30"></a>
#### S30 — Raspberry Pi Camera Module 3

- Source: [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/)
- Relevance: 12-megapixel autofocus/HDR and NoIR edge-camera option; not the blessed core host.

<a id="S31"></a>
#### S31 — Raspberry Pi AI HAT+

- Source: [Raspberry Pi AI HAT+](https://www.raspberrypi.com/products/ai-hat/)
- Relevance: low-power edge inference option. Purchase only when a measured edge workload benefits.

### Communication channels

<a id="S25"></a>
#### S25 — Telegram Bot API

- Source: [Telegram Bot API](https://core.telegram.org/bots/api)
- Relevance: `getUpdates` long polling, webhooks, update offsets, attachments, commands, and proactive messages.

<a id="S26"></a>
#### S26 — Telegram security model

- Source: [Telegram FAQ: security and Secret Chats](https://telegram.org/faq#q-how-secure-is-telegram)
- Relevance: distinction between cloud chats and end-to-end encrypted Secret Chats. Bot chats are not the root confidential-control channel.

<a id="S27"></a>
#### S27 — Matrix specification

- Source: [Matrix specification](https://spec.matrix.org/latest/)
- Relevance: open/federated communication alternative with an ecosystem for end-to-end encryption; deferred due to homeserver/client/key complexity.

### Models, inference, provider policy, and pricing

<a id="S32"></a>
#### S32 — llama.cpp

- Source: [llama.cpp](https://github.com/ggml-org/llama.cpp)
- Relevance: portable local inference endpoint and model-format ecosystem.

<a id="S33"></a>
#### S33 — MLX-LM

- Source: [MLX-LM](https://github.com/ml-explore/mlx-lm)
- Relevance: local language-model inference/fine-tuning on Apple Silicon; useful for an optional Mac compute node.

<a id="S34"></a>
#### S34 — vLLM

- Source: [vLLM documentation](https://docs.vllm.ai/)
- Relevance: high-throughput local/server inference where GPU workloads justify a dedicated model service.

<a id="S35"></a>
#### S35 — OpenAI API pricing

- Source: [OpenAI API pricing](https://openai.com/api/pricing/)
- Relevance: date-sensitive example of the price spread among model tiers and batch processing. Routing remains provider-neutral.

<a id="S36"></a>
#### S36 — Provider data-handling comparison

- Sources: [OpenAI data controls](https://platform.openai.com/docs/guides/your-data), [Anthropic Privacy Center](https://privacy.claude.com/), [Gemini API terms](https://ai.google.dev/gemini-api/terms), [Mistral terms and privacy](https://mistral.ai/terms/)
- Relevance: terms, retention, training use, and eligibility differ by product/account/region. Melloa stores versioned provider-policy snapshots.

<a id="S59"></a>
#### S59 — OpenAI API data controls

- Source: [OpenAI API data controls](https://platform.openai.com/docs/guides/your-data)
- Relevance: API data use and retention controls; re-check endpoint and account eligibility before routing sensitive data.

<a id="S60"></a>
#### S60 — Anthropic commercial/API retention

- Sources: [Anthropic: organization data retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data), [Anthropic: zero data retention eligibility](https://privacy.claude.com/en/articles/8956058-i-have-a-zero-data-retention-agreement-with-anthropic-what-products-does-it-apply-to)
- Relevance: standard retention, exceptions, and organization-specific ZDR are not interchangeable.

<a id="S61"></a>
#### S61 — Gemini API data terms and logging

- Sources: [Gemini API Additional Terms](https://ai.google.dev/gemini-api/terms), [Gemini API data logging and sharing](https://ai.google.dev/gemini-api/docs/logs-policy)
- Relevance: paid/unpaid and regional terms differ; do not route private data based on a generic “Gemini” label.

<a id="S62"></a>
#### S62 — Mistral data policy

- Sources: [Mistral terms](https://mistral.ai/terms/), [Mistral privacy policy](https://mistral.ai/terms/#privacy-policy)
- Relevance: vendor/account/product terms must be checked and recorded before eligibility is granted.

### Deployment, networking, observability, backup, and documentation

<a id="S40"></a>
#### S40 — Docker Compose

- Source: [Docker Compose file reference](https://docs.docker.com/reference/compose-file/)
- Relevance: declarative services, networks, volumes, configs, and secrets for the blessed one-host topology.

<a id="S41"></a>
#### S41 — Ansible

- Source: [Ansible documentation](https://docs.ansible.com/)
- Relevance: idempotent host bootstrap, firewall, users, systemd, backup timers, and runbooks.

<a id="S42"></a>
#### S42 — restic

- Source: [restic documentation](https://restic.readthedocs.io/en/stable/)
- Relevance: encrypted, deduplicated snapshots, integrity checks, and multiple storage backends.

<a id="S43"></a>
#### S43 — Backblaze B2 pricing

- Source: [Backblaze B2 Cloud Storage pricing](https://www.backblaze.com/cloud-storage/pricing)
- Relevance: current low-cost offsite-storage planning benchmark. Verify price and egress policy before deployment.

<a id="S44"></a>
#### S44 — OpenTelemetry

- Source: [OpenTelemetry documentation](https://opentelemetry.io/docs/)
- Relevance: vendor-neutral traces, metrics, and logs. Domain/audit records remain separate durable state.

<a id="S45"></a>
#### S45 — Ofgem energy price cap

- Source: [Ofgem energy price cap](https://www.ofgem.gov.uk/energy-price-cap)
- Relevance: electricity-unit-rate benchmark used for planning calculations; actual tariff varies.

<a id="S52"></a>
#### S52 — Material for MkDocs diagrams

- Source: [Material for MkDocs: diagrams](https://squidfunk.github.io/mkdocs-material/reference/diagrams/)
- Relevance: version-controlled Mermaid diagrams in a maintainable documentation site.

<a id="S54"></a>
#### S54 — Tailscale architecture

- Source: [Tailscale: What is Tailscale?](https://tailscale.com/kb/1151/what-is-tailscale)
- Relevance: convenient encrypted private networking and identity/control plane; kept replaceable.

<a id="S55"></a>
#### S55 — WireGuard

- Source: [WireGuard](https://www.wireguard.com/)
- Relevance: compact underlying VPN protocol and self-managed escape path. Application authorization remains separate.

<a id="S57"></a>
#### S57 — OpenTofu

- Source: [OpenTofu documentation](https://opentofu.org/docs/)
- Relevance: declarative cloud infrastructure only once Melloa owns enough cloud state to justify plans/state operations.

### Evaluation, experimentation, and future integrations

<a id="S46"></a>
#### S46 — N-of-1 methodology conditions

- Source: [N-of-1 Randomized Intervention Trials in Health Psychology: systematic review and methodology critique](https://pmc.ncbi.nlm.nih.gov/articles/PMC6128372/)
- Relevance: repeated measurable outcomes, reversibility, washout/carryover, stability, and stakeholder burden constrain valid N-of-1 use.

<a id="S47"></a>
#### S47 — CENT 2015

- Source: [CONSORT extension for reporting N-of-1 trials (CENT) 2015](https://www.bmj.com/content/350/bmj.h1738)
- Relevance: transparent protocol/reporting discipline and limits on causal claims.

<a id="S53"></a>
#### S53 — Inspect AI

- Source: [Inspect AI documentation](https://inspect.aisi.org.uk/)
- Relevance: open-source, model-provider-neutral evaluation framework with tasks, solvers, scorers, tools, sandboxes, and logs.

<a id="S58"></a>
#### S58 — Apple HealthKit

- Source: [Apple HealthKit documentation](https://developer.apple.com/documentation/healthkit)
- Relevance: future native health integration, authorization, and device-side data access; not an MVP requirement.

### Intellectual lineage

<a id="S64"></a>
#### S64 — Meliorism

- Source: [1911 Encyclopædia Britannica: Meliorism](https://en.wikisource.org/wiki/1911_Encyclop%C3%A6dia_Britannica/Meliorism)
- Relevance: historical description of meliorism as the position that the world may be made better through rightly directed human effort. Used as Melloa's guiding philosophy, not a technical claim.

<a id="S65"></a>
#### S65 — Man-Computer Symbiosis

- Source: [J. C. R. Licklider, Man-Computer Symbiosis](https://groups.csail.mit.edu/medg/people/psz/Licklider.html)
- Relevance: close human-machine cooperation in problem formulation, decision-making, goals, hypotheses, criteria, and evaluation; an intellectual ancestor of Melloa's owner/intelligence relationship.

<a id="S66"></a>
#### S66 — The Extended Mind

- Source: [Andy Clark and David Chalmers, The Extended Mind](https://consc.net/papers/extended.html)
- Relevance: argues that external resources may participate in cognition; the Otto notebook example motivates a subtle naming reference without dictating a memory-agent architecture.

<a id="S67"></a>
#### S67 — Augmenting Human Intellect

- Source: [Douglas Engelbart, Augmenting Human Intellect: A Conceptual Framework](https://dougengelbart.org/pubs/augment-3906.html)
- Relevance: augmentation, tools for improving human problem solving, and bootstrapping better capabilities; part of Melloa's intellectual lineage.

### Naming collision research

These checks are preliminary discovery, not legal clearance or a complete trademark search.

<a id="S48"></a>
#### S48 — GitHub `melloa` namespace

- Source: [GitHub account/repository namespace search for `melloa`](https://github.com/melloa)
- Relevance: the exact GitHub namespace is already occupied; public naming/organization choices need alternatives.

<a id="S49"></a>
#### S49 — MelliLabs / Melli

- Source: [MelliLabs](https://melli.com/)
- Relevance: existing proactive/speech-driven virtual-assistant branding creates likely search and product confusion.

<a id="S50"></a>
#### S50 — MelloAI

- Source: [MelloAI](https://melloai.com/)
- Relevance: similar AI naming; confirm current project status, marks, and domain confusion before public launch.

<a id="S51"></a>
#### S51 — Project MELLO

- Source: [Project MELLO](https://projectmello.com/)
- Relevance: additional close-name collision in the broader technology/AI search space.

### Source-use cautions

- A vendor’s documentation describes intended behavior, not proof that a deployment is secure.
- Pricing and product pages are snapshots, not contracts.
- Provider privacy terms may differ by endpoint, account, region, paid/unpaid status, safety classification, and negotiated agreement.
- Standards and protocols do not replace Melloa’s policy, provenance, identity, or operational controls.
- Naming checks require package registries, domains, company/trademark databases, counsel where appropriate, and confusion analysis before public adoption.
