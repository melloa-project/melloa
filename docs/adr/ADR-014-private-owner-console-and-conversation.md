# ADR-014: Make the private Owner Console and canonical conversation mandatory in V1

- **Status:** Accepted
- **Date:** 2026-08-16

## Context

The owner needs to converse with Melli and inspect years of sensitive observations, uncertain interpretations, memories, actions, media, costs, disclosures, and system health. A terminal and messaging bot alone cannot provide the required visibility or correction experience. Public ingress is unnecessary for a one-owner deployment.

## Decision

Build a private, authenticated Owner Console as a V1 component. It is served only on local/private interfaces and is the primary first-party client for canonical Melloa conversations.

Persist conversations independently of clients and transports. Telegram long polling is an optional secondary adapter. The console exposes structured evidence and decision records rather than raw hidden chain-of-thought.

Guardian status may be displayed through a constrained read-only contract, but high-impact Guardian actions remain separately authenticated and outside ordinary Melloa authority.

## Alternatives considered

- Terminal plus Telegram only: simpler initially, but too weak for provenance, media, policy, correction, and operational inspection.
- Public web console: remotely convenient but unnecessarily enlarges attack and operating surface.
- Raw model reasoning trace viewer: unavailable or unreliable across providers, sensitive, and not a sound audit contract.
- Native application first: stronger device integration but slower to build and less portable than a private responsive web client.

## Consequences

- TypeScript becomes part of the blessed V1 language set for the web client, while domain authority remains in the Python/SQL backend.
- Conversation/thread/message contracts must be channel-independent from the first migration.
- Private-network membership does not replace application authentication.
- The console, API, docs, tests, backups, and runbooks evolve together.

## Revisit when

A native client or multi-device/offline requirement justifies another first-party client. The canonical conversation and inspection contracts remain the source of truth.
