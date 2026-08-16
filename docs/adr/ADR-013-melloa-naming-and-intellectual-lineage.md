# ADR-013: Adopt Melloa naming and intellectual lineage

- **Status:** Accepted
- **Date:** 2026-08-16

## Context

The architecture requires stable distinctions between system, persistent intelligence, model, process, worker, client, and control plane. The project also benefits from a meaningful story rather than names assigned to arbitrary technical modules.

## Decision

- **Meliorism** is the guiding philosophy and purpose.
- **Melloa** is the open-source system and public technical project.
- **Melli** is the primary persistent intelligence in an owner's deployment.
- **Guardian** remains the independent owner-controlled control plane.
- **Otto** is reserved as an optional Extended Mind reference and is not assigned to a V1 subsystem, synthetic owner, or mandatory agent.

The intellectual lineage includes meliorism, Licklider's human-computer symbiosis, Clark and Chalmers' extended-mind thesis, and Engelbart's augmentation of human intellect. [S64](../research/primary-sources.md#S64) [S65](../research/primary-sources.md#S65) [S66](../research/primary-sources.md#S66) [S67](../research/primary-sources.md#S67)

Durable code and schemas use neutral identifiers. Display names and naming history are data rather than type names or keys.

## Alternatives considered

- Rename the system to Meliorism: semantically strong, but less warm and discards the already meaningful Melloa/Melli distinction.
- Name every subsystem after a historical person or thought experiment: memorable but obscures responsibility and encourages architecture by mythology.
- Keep all names provisional indefinitely: avoids commitment but makes documentation and repositories inconsistent.

## Consequences

- Documentation can explain a coherent philosophy without creating extra agents.
- Melli may later choose or change a display name while retaining stable identity.
- Public-launch clearance remains a separate legal and brand gate.
- `Otto`, `Eliot`, `Nova`, `Charlie`, and similar names are available only when a real persistent identity or example requires one.

## Revisit when

Formal clearance reveals a material conflict or the project deliberately changes public brand. Domain identifiers and identity continuity must survive any brand change.
