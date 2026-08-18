# Melloa product spine

Primary owner journey:

> discover the promise → install verified dependencies → start a safe private preview → sign in → converse → inspect why → inspect/correct owner state → export/control → recover or stop cleanly → add durable state and real routes

## Active release slices

### D-001 — One-command local preview

- **Outcome:** after cloning the two public repositories, a newcomer starts the complete disposable Owner Console loop with one command and receives the URL, credential, safety/persistence truth, next action, and cleanup behavior in the terminal.
- **Acceptance:** Guardian is still independently built and signed; its private key or mutation command is never passed to the core; core and same-origin console become ready or fail with a corrective message; Ctrl-C stops children and removes disposable credentials/state; automated tests cover startup failure, readiness, shutdown, and secret-safe output; README and Pages use this as the canonical first run.
- **Owner/claim:** Director — launcher, launcher tests, Makefile, canonical onboarding docs; no overlap with F-004.
- **Reviewer:** Lens after implementation.
- **Integration:** implementation frozen; real Guardian/core/web start and cleanup exercised; full local `make check` green; Lens acceptance pending.
- **Next:** commit/push, then verify exact-SHA CI and Pages.

### F-004 — Audit truth and diagnostic telemetry contract

- **Outcome:** current owner/API audit ordering, durability, repair, and known gaps are executable truth; bounded diagnostics cannot masquerade as audit evidence or carry arbitrary private data.
- **Acceptance:** exhaustive fail-closed matrix; typed bounded signals only; sink failures never block accepted work; focused tests, Ruff, and affected unit suite pass; no runtime wiring or gauges.
- **Owner/claim:** Forge — `src/melloa/{application/telemetry.py,domain/observability.py,ports/telemetry.py}` and `tests/unit/test_observability.py` only.
- **Reviewer:** Lens after frozen handoff.
- **Integration:** Forge handoff complete with 35 focused and 539 no-coverage unit tests passing; independent technical acceptance pending; this slice must not delay D-001.
- **Next:** integrate as a separate commit only if Lens accepts it.

### L-001 — Independent product/release acceptance

- **Outcome:** concrete P0/P1 gaps and observable criteria from a newcomer traversal, followed by an explicit verdict on each frozen slice.
- **Owner/claim:** Lens — read-only across product files.
- **Integration:** initial verdict rejected the release on first-run productization and durability; D-001 re-review is active.
- **Next:** D-001 verdict, bounded F-004 verdict, then pushed CI and Pages.

## Next product blockers

1. **D-002 — Durable recovery loop (P0):** choose one canonical durable owner state, back it up, restore it into a clean runtime, and prove conversation/memory/evidence remain usable through the Owner Console.
2. **D-003 — Real Melli value (P1):** make one eligible model route straightforward to configure and exercise it in an automated product journey without weakening disclosure or fixture honesty.
3. **D-004 — One release identity (P1):** align package, web, health, README/Pages, tag/release, and milestone terminology; record the owner-only license decision as external until resolved.

## Release gates

- Primary path succeeds from a clean checkout with truthful output and no real credentials or personal data.
- Conversation, explanation, owner inspection/control, export, failure recovery, and cleanup are exercised, not inferred.
- README, CLI/output, Owner Console, examples, and Pages use one terminology and workflow.
- Full required checks pass; the latest pushed SHA is green and Pages is deployed.
- No unresolved P0/P1 product or release blocker remains; external/owner-only blockers are explicit.
