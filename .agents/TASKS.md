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
- **Integration:** D-001, F-004, D-002, and D-003 are accepted with no P0/P1 findings; D-003's bounded P2 documentation-precision follow-up is complete. The full product remains no-ship on release identity.
- **Next:** independently review D-004 after its release identity and clean evidence are frozen.

### D-002 — Durable owner-state recovery

- **Outcome:** one command proves that Melloa's complete PostgreSQL owner state can be encrypted, restored into a clean database, and used again through the authenticated owner API without treating export as backup.
- **Acceptance:** every migration is present; a canonical conversation, fixture turn, explanation evidence, memory mutation evidence, owner session/audit state, and read-only authority survive a custom-format logical dump, encrypted restic integrity check, and clean restore; cleanup is verified before the receipt, which contains no credentials, private text, DSNs, or paths.
- **Owner/claim:** Director — product decision, docs, integration, and release; Forge — recovery harness and focused tests only.
- **Reviewer:** Lens after clean local and CI evidence.
- **Integration:** the reviewed harness shipped in `21151f1` and the reconciled owner contract in `f9e3791`; its clean export passes 557 unit tests at 90.35% coverage, strict checks, 17 PostgreSQL integration tests, and the real exact-image restore. Exact-SHA CI run `32154464918` and Pages deployment are green, and Lens accepted the complete slice with no P0/P1 findings.
- **Next:** complete; D-003 owns the next P1 journey gap.

### D-003 — Real Melli value

- **Outcome:** a newcomer can select one reviewed on-device model path from the canonical preview command, receive corrective readiness guidance, converse with an actual eligible model as Melli, and inspect the exact route/disclosure/evidence record without confusing a protocol fixture or deterministic fallback for intelligence.
- **Acceptance:** `make preview` remains the honest no-network fixture; `make preview PREVIEW_MODEL=ollama` selects the reviewed Qwen route, requires the exact configured model from the loopback endpoint, and reports a truthful local-model contract; malformed or empty model listings are unavailable; an automated authenticated owner journey exercises the real HTTP protocol boundary and proves the Melli route, output, disclosure, tokens, evidence, and fallback distinction; focused and full checks pass.
- **Owner/claim:** Director — product contract, authenticated journey, docs, integration, and release; Forge — launcher, route-health mechanics, and focused tests only.
- **Reviewer:** Lens after implementation and clean evidence.
- **Integration:** accepted. A verified official Ollama `0.32.14` run showed that the moving `qwen3:4b` alias had become a thinking-only model that exhausted the 60-second route deadline, so the product now pins the purpose-matched `qwen3:4b-instruct-2507-q4_K_M` tag and rejects the alias as a model-ID mismatch. The canonical browser-origin journey completed one successful device attempt in about 24 seconds with 140 input tokens, 55 output tokens, zero configured cost, no external disclosure, a matching retrieval manifest, useful non-fixture output, and supervised credential/state cleanup. The exact Ollama artifact SHA-256 was `c620917a71e146ab3a7f893084f066069c4c65d144ef8379a91c3cbe8b27de8f`; the exercised model manifest digest was `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`. Its clean export passes 572 unit tests at 90.37% coverage, 158 web tests, strict checks, 17 PostgreSQL integration tests, and encrypted clean recovery. Exact-SHA CI run `32160031858` and Pages deployment `5966965243` are green, and Lens accepted the slice with no P0/P1 findings.
- **Next:** complete; D-004 owns the remaining P1 release gap.

### D-004 — One release identity

- **Outcome:** every owner-visible and machine-readable surface identifies one `v0.2.0` preview release at milestone `M1`, built on architecture baseline `v0.2`, while preserving `M0` only as historical evidence.
- **Acceptance:** one typed release identity drives runtime and event producers; Python and web metadata resolve to `0.2.0`; system status and the Owner Console expose version `0.2.0`, stage `preview`, and milestone `M1`; consistency tests reject drift; README, Pages, changelog, generated evidence, tag, and GitHub prerelease agree; the unresolved public-license choice remains explicitly owner-only and external.
- **Owner/claim:** Director — product contract, ledger, docs, generated evidence, integration, and release; Forge — runtime, web, package metadata, and focused consistency tests.
- **Reviewer:** Lens after implementation and clean evidence.
- **Integration:** active. The starting tree mixes Python `0.0.1`, web/API/event `0.1.0`, runtime `0.2.0-mvp-preview`, and milestone `M0`, with no tag or GitHub release.
- **Next:** establish the central identity, replace every active drift point, and prove agreement before release acceptance.

## Owner-only external blocker

- No public license has been chosen. Readable source does not authorize reuse, redistribution, or outside contributions; only the repository owner can choose license terms.

## Release gates

- Primary path succeeds from a clean checkout with truthful output and no real credentials or personal data.
- Conversation, explanation, owner inspection/control, export, failure recovery, and cleanup are exercised, not inferred.
- README, CLI/output, Owner Console, examples, and Pages use one terminology and workflow.
- Full required checks pass; the latest pushed SHA is green and Pages is deployed.
- No unresolved P0/P1 product or release blocker remains; external/owner-only blockers are explicit.
