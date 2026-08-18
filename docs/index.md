---
hide:
  - toc
---

# Melloa

**A local-first home for one personal intelligence—built to keep identity, memory, evidence, policy, and owner control durable while models, providers, processes, and interfaces change.**

**Melloa** is the system. **Melli** is the persistent personal intelligence that lives through it. A model call is temporary; the owner's relationship, canonical conversation, memory, provenance, policies, and corrections are not.

[Try the local preview](run-current-mvp.md){ .md-button .md-button--primary }
[See what works today](25-m1-implementation.md){ .md-button }

[![The Melloa Owner Console conversation view showing a canonical conversation and its route and provenance inspector](assets/current-mvp/conversation-desktop.png)](assets/current-mvp/conversation-desktop.png)

*The current private Owner Console: canonical conversation on the left, route, disclosure, provenance, cost, and policy evidence on the right. The pictured route is the clearly labelled no-network synthetic fallback.*

!!! warning "Usable preview, not production-ready"
    The default path runs on loopback with synthetic data and process-local state. Optional PostgreSQL adds only the restart-durability boundaries the runtime reports. No public source license has been selected yet, so the repository is readable but reuse, redistribution, and outside contributions are not authorized.

## What you can do now

- Talk to Melli in an authenticated, channel-neutral conversation that is not owned by a model provider or chat client.
- Inspect which model route ran, what memory evidence was selected, whether anything left the machine, and what it cost.
- Review, correct, dispute, retract, or content-delete memory while preserving provenance and deletion evidence.
- Inspect provider health, delivery attempts, retention coverage, operational status, and a content-free owner timeline.
- Download and validate a canonical owner-data export, with an optional encrypted package wrapper.
- Keep the independent Guardian in signed `offline`, `read-only`, `no-actions`, `normal`, `stopped`, or `recovery` modes without giving Melloa its signing key or transition authority.

The safe first run needs the two public sibling repositories, Python, uv, Node.js, and Go. It needs no Docker daemon, model key, Telegram account, camera, or private deployment repository.

```bash
git clone https://github.com/melloa-project/melloa.git
git clone https://github.com/melloa-project/melloa-guardian.git
cd melloa
make bootstrap
```

Continue with [Run the current MVP](run-current-mvp.md) for disposable Guardian setup, login, conversation, inspection, export, and cleanup.

## How the pieces fit together

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

## See the product

### Inspect and correct memory

[![The Owner Console memory view showing an assertion, provenance, state history, and owner controls](assets/current-mvp/memory-desktop.png)](assets/current-mvp/memory-desktop.png)

Memory is owner-scoped and provenance-rich. The preview exposes values, sources, status history, corrections, contestation, retraction, and content-deletion evidence rather than presenting an opaque vector store as “memory.”

### Understand operations and export limits

[![The Owner Console operations view showing export readiness, validation, encryption commands, and explicit limitations](assets/current-mvp/operations-export-desktop.png)](assets/current-mvp/operations-export-desktop.png)

Operational views show what is healthy, durable, exportable, encrypted, or still missing. Current export is a validated portability preview—not a claim of SQL/blob backup or production recovery.

### Follow a content-free evidence timeline

[![The Owner Console timeline showing conversation, processing, model, delivery, and export audit evidence](assets/current-mvp/timeline-desktop.png)](assets/current-mvp/timeline-desktop.png)

The timeline joins current-MVP conversation, processing, model, delivery, and owner-export evidence without copying message text, prompts, credentials, destinations, or raw audit payloads into the activity feed.

More desktop and mobile reference states are linked from [Expected visual states](run-current-mvp.md#expected-visual-states).

## Why build it this way

- **Persistence over provider lock-in:** Melli is not a model, prompt, process, or subscription. Durable identity and history stay in owner-controlled contracts.
- **Evidence over mystique:** important interpretations, memories, disclosures, decisions, actions, and corrections carry inspectable provenance.
- **Explicit authority over ambient agency:** models do not receive general tool, credential, policy, or Guardian authority.
- **Local-first, not local-only:** the default is private and no-network; an owner may configure bounded external routes with visible disclosure.
- **Honest operational boundaries:** restart durability, export validation, telemetry, backup, and production readiness are named separately.

## Learn at your own depth

1. **Use it:** [Run the current MVP](run-current-mvp.md).
2. **Understand the product:** [Executive vision](01-executive-vision.md), [design principles](02-design-principles-requirements.md), and [conceptual model](03-conceptual-model.md).
3. **Understand the boundaries:** [v0.2 decisions](23-v0.2-decisions.md), [chosen V1 architecture](05-chosen-v1-architecture.md), and [M1 threat review](26-m1-threat-review.md).
4. **See the system visually:** [Architecture diagram catalogue](diagrams.md).
5. **Inspect implementation evidence:** [M0](24-m0-implementation.md), [M1](25-m1-implementation.md), [observability and operational evidence](27-m1-observability-operational-evidence.md), and the [current validation report](https://github.com/melloa-project/melloa/blob/main/VALIDATION.md).
6. **Work on the project:** [Development and verification](development.md) and the [pre-release compatibility process](compatibility.md).

The deeper research remains available, but it is no longer the front door. Start with the product, then follow the layer of detail you need.
