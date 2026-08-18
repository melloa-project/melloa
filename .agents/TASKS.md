# Melloa product spine

Primary owner journey:

> discover the promise → install verified dependencies → start a safe private preview → sign in → converse → inspect why → inspect/correct owner state → export/control → recover or stop cleanly → add durable state and real routes

## Active release slices

### D-001 — One-command local preview

- **Outcome:** after cloning the two public repositories, a newcomer starts the complete disposable Owner Console loop with one command and receives the URL, credential, safety/persistence truth, next action, and cleanup behavior in the terminal.
- **Acceptance:** Guardian is still independently built and signed; its private key or mutation command is never passed to the core; core and same-origin console become ready or fail with a corrective message; Ctrl-C stops children and removes disposable credentials/state; automated tests cover startup failure, readiness, shutdown, and secret-safe output; README and Pages use this as the canonical first run.
- **Owner/claim:** Director — launcher, launcher tests, Makefile, canonical onboarding docs; no overlap with F-004.
- **Reviewer:** Lens after implementation.
- **Integration:** shipped in `299d4ae` with signal-safe supervised cleanup in `40e5a15`; Lens accepted the slice; exact-SHA verification, PostgreSQL recovery, authenticated visual smoke, cleanup, docs publication, and the public Pages content are green.
- **Next:** complete; D-002 owns the next P0 journey gap.

### F-004 — Audit truth and diagnostic telemetry contract

- **Outcome:** current owner/API audit ordering, durability, repair, and known gaps are executable truth; bounded diagnostics cannot masquerade as audit evidence or carry arbitrary private data.
- **Acceptance:** exhaustive fail-closed matrix; typed bounded signals only; sink failures never block accepted work; focused tests, Ruff, and affected unit suite pass; no runtime wiring or gauges.
- **Owner/claim:** Forge — `src/melloa/{application/telemetry.py,domain/observability.py,ports/telemetry.py}` and `tests/unit/test_observability.py` only.
- **Reviewer:** Lens after frozen handoff.
- **Integration:** Forge handoff and Lens acceptance are complete; the clean combined tree passes 554 unit tests at 90.35% coverage, strict typing/lint, web checks, generated evidence, and strict docs.
- **Next:** complete; shipped in `f0ac5de` with exact-SHA CI and Pages deployment green.

### L-001 — Independent product/release acceptance

- **Outcome:** concrete P0/P1 gaps and observable criteria from a newcomer traversal, followed by an explicit verdict on each frozen slice.
- **Owner/claim:** Lens — read-only across product files.
- **Integration:** D-001 and F-004 are accepted; D-001's bounded release follow-ups are complete. The full product remains no-ship on durable recovery, real Melli value, and release identity.
- **Next:** independently review D-002 after its owner recovery journey is observable.

### D-002 — Durable owner-state recovery

- **Outcome:** one command proves that Melloa's complete PostgreSQL owner state can be encrypted, restored into a clean database, and used again through the authenticated owner API without treating export as backup.
- **Acceptance:** every migration is present; a canonical conversation, fixture turn, explanation evidence, memory mutation evidence, owner session/audit state, and read-only authority survive a custom-format logical dump, encrypted restic integrity check, and clean restore; cleanup is verified before the receipt, which contains no credentials, private text, DSNs, or paths.
- **Owner/claim:** Director — product decision, docs, integration, and release; Forge — recovery harness and focused tests only.
- **Reviewer:** Lens after clean local and CI evidence.
- **Integration:** the reviewed harness shipped in `21151f1`; its clean export passes 557 unit tests at 90.35% coverage, strict checks, 17 PostgreSQL integration tests, and the real exact-image restore, while exact-SHA CI independently passes the deterministic, PostgreSQL, and recovery gates.
- **Next:** publish the reconciled owner contract, verify its exact SHA and Pages deployment, then request Lens acceptance.

## Next product blockers

1. **D-003 — Real Melli value (P1):** make one eligible model route straightforward to configure and exercise it in an automated product journey without weakening disclosure or fixture honesty.
2. **D-004 — One release identity (P1):** align package, web, health, README/Pages, tag/release, and milestone terminology; record the owner-only license decision as external until resolved.

## Release gates

- Primary path succeeds from a clean checkout with truthful output and no real credentials or personal data.
- Conversation, explanation, owner inspection/control, export, failure recovery, and cleanup are exercised, not inferred.
- README, CLI/output, Owner Console, examples, and Pages use one terminology and workflow.
- Full required checks pass; the latest pushed SHA is green and Pages is deployed.
- No unresolved P0/P1 product or release blocker remains; external/owner-only blockers are explicit.
