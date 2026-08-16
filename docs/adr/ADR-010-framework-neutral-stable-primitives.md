# ADR-010: Keep durable logic independent of agent frameworks

- **Status:** Accepted for V1
- **Date:** 2026-08-15

## Context

Agent frameworks and model APIs change rapidly. Melloa’s identity, memory, policy, actions, and operational history must survive provider/library replacement over many years.

## Decision

Express durable behavior through domain models, versioned schemas, processes, PostgreSQL state, queues/jobs, typed ports, and explicit capability/model adapters. An agent/coding/MCP framework may implement an adapter or orchestration detail but cannot own canonical memory, policy, identity, or action authorization. Every selected framework has an escape test and export/replay path.

## Alternatives considered

- Adopt one agent framework as the application architecture: fast prototype, high semantic and lifecycle lock-in.
- Build all model/tool protocol details from scratch: excessive reinvention and compatibility burden.

## Consequences

- Some adapter boilerplate and explicit state machines are required.
- Framework upgrades become bounded replacements rather than data migrations.
- Melloa can adopt MCP or future protocols selectively.

## Revisit when

A framework demonstrates multi-year stability and offers a capability Melloa cannot reasonably reproduce. Even then, canonical state and authority remain external.
