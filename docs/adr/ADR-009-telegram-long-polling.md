# ADR-009: Use Telegram long polling as an optional secondary owner channel

- **Status:** Accepted; clarified by ADR-014
- **Date:** 2026-08-15
- **Clarified:** 2026-08-16

## Context

The owner benefits from concise remote text, attachments, approvals, corrections, and proactive notifications. Public webhooks add ingress. Telegram bots are convenient but do not provide the same confidentiality or inspectability as Melloa's private first-party client.

## Decision

Provide a Telegram Bot API adapter using `getUpdates` long polling with one exactly paired and allowlisted owner user/private chat. Normalize all messages into canonical Melloa conversation records. Keep highly sensitive content, raw room media, secrets, exports, and Guardian-root operations off-channel by default.

Telegram is optional and secondary. The private Owner Console defined by ADR-014 is the primary client. Melloa remains fully operable locally when Telegram is absent or unavailable.

## Alternatives considered

- Telegram as the only V1 UI: easy, but insufficient for provenance, media, policy, health, and high-trust control.
- Public webhook: lower inbound latency but unnecessary internet ingress.
- Native mobile application: stronger long-term experience but larger initial product and release burden.
- Matrix: open and E2EE-capable, but heavier homeserver/client/key operations.

## Consequences

- No public webhook or domain is required.
- Telegram/cloud retains a copy under its own policies.
- Critical owner control uses the Guardian/private authentication path.
- Telegram identifiers remain adapter metadata rather than owner, intelligence, or conversation identity.
- The adapter can be disabled without changing canonical history or Melli's continuity.

## Revisit when

A different transport is more useful, privacy requirements change, or a native client provides better remote interaction. The canonical conversation contract remains stable.
