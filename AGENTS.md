# Melloa working instructions

## Authority

Read [PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md) and
[docs/trust-boundaries.md](docs/trust-boundaries.md) before material work.

Those files define current product intent and durable safety constraints. Everything else in
the repository—including code, tests, schemas, migrations, UI routes, tags, and old behavior—is
evidence to evaluate, not a requirement to preserve. Git history is the archive. There is no
architecture milestone queue.

An old decision may be superseded directly when owner evidence supports it. Record only the
small amount of current rationale that a future contributor needs; do not create an ADR merely
to protect previous work.

## Product standard

Melloa exists to support the owner's long-lived relationship with Melli. Prefer work that makes
the owner voluntarily choose Melli because she understands their context, remembers useful
history, follows through, and creates value a stateless assistant could not.

For material work, state the owner-visible before/after. If the improvement is hard to explain
without subsystem terminology, reconsider it. Product experience outranks specification
coverage, test count, schema breadth, infrastructure completeness, and lines of code.

The current phase is destructive simplification. Until the subtraction checkpoint in
`PRODUCT_DIRECTION.md` is met, remove or collapse obsolete documentation, demo machinery,
owner-facing administration, speculative abstractions, and premature integrations before adding
substantial Melli functionality. Deletion is a successful change when it removes work or concepts
the owner should never have had to understand.

## Hard boundaries

- Melloa is the system; Melli is the persistent intelligence, not a model or process.
- Melli's continuity must survive model and provider replacement.
- Guardian remains independently owner-controlled and outside Melloa's write, deploy, signing,
  credential, and recovery authority.
- Owner data remains private by default, owner-controlled, exportable, and deletable within
  clearly stated limits.
- Models and untrusted content never authorize external side effects. Deterministic policy and
  capabilities constrain them.
- Sensitive external disclosure is explicit and inspectable.
- Provenance is retained where it changes trust in memories, decisions, disclosures, or actions.
- High-risk or irreversible actions remain structurally constrained and fail closed.

Preserve these principles, not their present implementation size or shape.

## Working method

1. Begin from an actual owner journey, not a subsystem map.
2. Inspect rendered desktop and mobile behavior for owner-facing changes.
3. Prefer one concrete path and strong defaults over configurable frameworks.
4. Keep ordinary conversation free of provider, route, assertion, audit, database, and Guardian
   protocol terminology. Reveal trustworthy detail in context when it can change an owner decision.
5. Change or delete tests that enforce intentionally rejected behavior. Keep focused tests for
   trust boundaries, data integrity, and the owner journey being improved.
6. Keep the repository runnable while simplifying it; do not preserve dead paths for compatibility
   with a technical preview.
7. Use real longitudinal dogfooding as primary product evidence. Synthetic fixtures prove bounded
   mechanics only and must never be presented as evidence that Melli is useful.

## Adversarial review

At the subtraction checkpoint, after major experience changes, and before broad completion claims,
run multiple independent reviewers against the real repository and rendered product. Include these
perspectives across the review set:

- daily owner experience;
- modern product and interface quality;
- owner attention and leverage;
- long-term human–AI symbiosis;
- ruthless simplicity;
- longitudinal intelligence.

Ask reviewers to find reasons the work is wrong, not to validate it. Preserve material disagreement,
respond to substantive objections, change course when the objection is stronger, and explain any
rejected recommendation. A review with no concrete criticism is not useful evidence.
