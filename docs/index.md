# Melloa: a long-lived personal AI operating system

## The decision

Build Melloa V1 as a **local-first, event-oriented modular monolith** on a wired Linux mini-PC. Store durable observations, interpretations, beliefs, corrections, conversations, policies, goals, actions, and outcomes in PostgreSQL with explicit provenance. Let **Melli** persist as an identity even while model providers, prompts, workers, and interfaces change.

Give models no ambient authority. They may propose plans and actions; an independent capability broker decides whether each exact action is denied, allowed, constrained, or requires owner approval. Keep the final stop mechanism in a host-level **Guardian** whose credentials and deployment path are outside Melli's control.

Use cheap local perception to reduce continuous camera video into candidate events. Escalate only selected frames or structured context to stronger models. Treat every semantic perception as uncertain. Store raw evidence briefly by default and derived, provenance-rich events longer.

Make the **private Owner Console** the primary first-party interface. It supports direct conversation with Melli and exposes health, observations, interpretations, beliefs, provenance, structured decisions, tool use, retained media, actions, costs, disclosures, backups, and deployments. It is private-network-only and separately authenticated.

Treat Telegram as an optional secondary transport. Long polling provides remote convenience without public ingress, but Telegram is not Melloa's identity, memory, or permanent UI. Sensitive content remains local unless policy explicitly permits transmission. [S25](research/primary-sources.md#S25) [S26](research/primary-sources.md#S26)

## Names and lineage

**Meliorism** is the guiding philosophy; **Melloa** is the system; **Melli** is the primary persistent intelligence. **Otto** is a reserved philosophical reference, not a required component. The project's lineage includes human-computer symbiosis, the extended-mind thesis, and augmentation of human intellect. [S64](research/primary-sources.md#S64) [S65](research/primary-sources.md#S65) [S66](research/primary-sources.md#S66) [S67](research/primary-sources.md#S67)

See [v0.2 adopted decisions](23-v0.2-decisions.md) for the exact precedence rule.

## What survives model and interface churn

The durable system consists of:

- the owner's goals, values, constraints, approvals, and corrections;
- Melli's identity, relationships, memories, and responsibility history;
- canonical conversations, events, and provenance;
- policy and capability contracts;
- software and infrastructure history;
- evaluation datasets, replays, and outcomes;
- open export formats.

A model invocation is an ephemeral computation over a selected view of those durable assets. A worker is a process with a task and scoped authority. A client or channel is a view and transport. None is the persistent intelligence.

## North-star test

Seven years from now, Melloa is successful not because it has many integrations, but because the owner can point to repeated closed loops where it:

1. noticed something reliably enough;
2. related it to an intentionally chosen goal;
3. proposed or performed a proportionate intervention;
4. measured what happened;
5. retained evidence and uncertainty;
6. changed or retired the intervention;
7. remained understandable, inspectable, interruptible, and owner-controlled.

See [Final synthesis](22-final-synthesis.md) for the build recommendation and [Traceability](00-traceability.md) for coverage of the master brief.
