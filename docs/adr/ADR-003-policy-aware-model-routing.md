# ADR-003: Route models by adequacy, privacy, latency, and cost

- **Status:** Accepted for V1
- **Date:** 2026-08-15

## Context

One model cannot economically or safely handle every sensor tick, extraction, conversation, multimodal interpretation, coding task, and strategic review. Local-only can reduce quality; cloud-only can leak data and create cost/dependency risk.

## Decision

Create a provider-neutral model gateway. Every request declares task, modality, minimum quality, sensitivity/provider eligibility, context limit, latency, cost ceiling, output schema, and fallback. Tier 0 uses no model, Tier 1 local/tiny models, Tier 2 medium models, Tier 3 frontier models. A result remains untrusted data until validated; model choice never grants capability authority.

## Alternatives considered

- Single frontier model: simple but expensive, high disclosure, fragile provider dependency.
- Local-only: private but may be inadequate for difficult reasoning/multimodal work.
- Agent framework router: fast to adopt, but couples durable architecture to a transient library.

## Consequences

- Route/version/disclosure/cost records are mandatory.
- Evaluation suites compare model routes statistically.
- Provider terms and prices are versioned operational inputs.
- Fallback cannot silently broaden privacy or cost.

## Revisit when

Measured task distributions support fewer tiers, a local model consistently meets quality/cost targets, or provider-specific capabilities require a carefully isolated extension.
