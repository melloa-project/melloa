# Conceptual model and naming

## Purpose

Remove ambiguity from terms that otherwise become architectural coupling. The model intentionally separates durable entities from transient computation.

## Core entities

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

## Epistemic entities

### Observation

A minimally interpreted datum captured from a source: a frame hash, conversation message, motion interval, API response, or health sample. It carries source, time, integrity, sensitivity, and retention metadata.

### Interpretation

A versioned claim produced from one or more observations, such as “a person probably entered.” It identifies the detector/model/prompt, confidence, alternatives, and evidence.

### Belief

Melli's current synthesized view, such as “the owner is likely in the room.” It may combine interpretations and prior state. It is temporal and revisable.

### User-confirmed fact

A statement explicitly confirmed by the owner for a defined scope and time. Confirmation increases authority but does not make it eternally true.

### Memory

A durable record selected for future use. A memory is not merely an embedding. It has type, provenance, validity interval, confidence, sensitivity, correction status, and retrieval policy.

### Event

A canonical, immutable record that something was observed, inferred, decided, executed, corrected, or evaluated. Events connect activity over time but do not require the whole application to be purely event-sourced.

The core invariant is:

```text
Observation ≠ Interpretation ≠ Belief ≠ User-confirmed fact
```

## Identity continuity

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

## Multi-agent decision rule

Create another persistent intelligence only when at least three of these are true:

1. It needs a distinct long-term relationship with the owner.
2. It needs memory that should not be automatically shared with Melli.
3. It has goals that can conflict with Melli's goals and must be represented explicitly.
4. It requires a materially different permission set.
5. It must be independently accountable for decisions over time.
6. Its identity must continue across many tasks and model changes.

Otherwise use an ephemeral specialist worker.

## Naming and intellectual lineage

### Adopted vocabulary

- **Meliorism** is the philosophy and purpose.
- **Melloa** is the system, intended public project, and public technical name. Its source is currently readable, but it is not open source until explicit license terms are added.
- **Melli** is the primary persistent intelligence in the owner's deployment.
- **Guardian** is the independent owner-controlled control plane.
- **Otto** is reserved as a subtle Extended Mind reference and is not assigned to a V1 subsystem.

The names remain architecturally separate. Code and schemas use neutral domain identifiers rather than display names. A persistent intelligence may change its chosen display name while retaining a stable identity and history.

The project's intellectual family tree is explanatory, not prescriptive: meliorism supplies the purpose, Licklider's symbiosis supplies the partnership model, Clark and Chalmers supply the extended-cognition lens, and Engelbart supplies the augmentation and bootstrapping tradition. [S64](research/primary-sources.md#S64) [S65](research/primary-sources.md#S65) [S66](research/primary-sources.md#S66) [S67](research/primary-sources.md#S67)

### Public-name gate

The names are adopted for implementation and repository organization. Before a broad public launch, perform refreshed registry, domain, company-name, search-confusion, and trademark review. That gate may qualify presentation or branding, but implementation must not hard-code display names into durable identifiers or contracts.

## Build now / design for / defer

### Build now

- Distinct IDs for system deployment, persistent intelligence, owner, worker execution, model, capability, action, and event.
- The epistemic distinctions above in schema and UI.
- A naming-history field rather than using display name as a primary key.

### Design for

- Multiple persistent identities and private memory partitions.
- Identity export, fork, merge, and retirement semantics.
- User-inspectable explanation of which identity acted and under whose authority.

### Defer

- Autonomous renaming without an owner-visible change record.
- Legal conclusions based only on search results.
- Agent-to-agent social protocols until a real use case needs persistent identities.
