# Changelog

## M1 implementation — in progress

- Added the explicit `serve-mvp` owner-facing preview with loopback-only core/web serving, signed Guardian reads, process-local defaults, and optional restricted-role PostgreSQL restart durability.
- Added provider-neutral local OpenAI-compatible routing, a bounded experimental Codex CLI adapter with isolated configuration and no Melloa authority, and visibly labelled deterministic fallback.
- Added optional real Telegram Bot API long polling, private owner pairing, canonical text ingestion, durable offsets/work where PostgreSQL is enabled, and exact policy-authorized replies.
- Added hashed owner-session persistence, append-only revocation evidence, active-session inventory, credential-bound rotation behavior, and recent-authenticated sign-out-other-sessions control.
- Added chronological owner timeline, export-audit projection, expanded activity/providers/operations/settings views, responsive mobile states, and authenticated production-build browser smoke evidence.
- Added canonical owner export with JSONL, copied schemas, checksums, dry-run validation, live browser ZIP download, and an optional AES-256-GCM/Scrypt encrypted package round trip.
- Added owner assertion-content deletion that removes retained value while preserving metadata, state history, content-free tombstone, rebuild obligation, and honest backup-expiry disclosure.
- Added content-free accepted/denied audit evidence for canonical owner-message acceptance/resume and outbound-delivery enqueue/resume, including durable PostgreSQL proof and honest post-mutation audit-failure recovery tests.
- Published an evidence-backed M1 implementation threat review and pre-release compatibility process without implying production readiness, stable support, a license grant, or open contribution intake.
- Published the M1 observability and operational-evidence acceptance design, separating durable audit truth from diagnostic telemetry and defining no-network, redaction, cardinality, failure-semantics, and preview-SLO boundaries.
- Added a deterministic, no-network CycloneDX 1.6 dependency inventory for committed Python runtime/development/docs/build locks, the npm lock, and Guardian Go modules, with source/checksum evidence and a short-lived CI artifact; CI actions, runner/OS toolchains, containers, and signed provenance remain outside its claim.
- Reworked newcomer entry points around the safe no-network journey, refreshed current validation evidence, made validation statistics independent of local test artifacts, and added non-mutating generated checks for the consolidated reading edition and validation snapshot.
- Added authenticated owner sessions, secure cookie/CSRF boundaries, and channel-neutral private conversation APIs.
- Added canonical idempotent conversation turns and deterministic policy-aware model routing with disclosure-aware fallback records.
- Added policy-scoped, provenance-ranked retrieval manifests and carried validated citation/evidence IDs through model context, output messages, and structured turns.
- Added an additive M1 PostgreSQL schema for durable retrieval, conversation idempotency/trigger links, external disclosures, and mutable correction projection over immutable assertions.
- Added restricted-role PostgreSQL adapters for atomic conversation completion and correction-aware assertion/provenance retrieval, with exact replay and durable disclosure records.
- Added authenticated, thread-scoped turn inspection with retrieval manifests, cited evidence, structured decisions, model results, costs, disclosures, and canonical output.
- Added typed assertion projection/history/correction contracts and an append-only, version-checked PostgreSQL state-transition boundary that prevents direct runtime projection mutation.
- Added authenticated owner-scoped memory inspection/correction APIs with recent-authentication, CSRF, and Guardian gates, immutable in-memory/PostgreSQL writes, provenance links, durable history, and optimistic conflict handling.
- Added explicit owner dispute and retraction endpoints that append versioned state history through the restricted compare-and-swap projection boundary.
- Added an authenticated bounded-window model activity report with redacted per-turn token/cost metadata, external route attempts, and complete sent-memory disclosure accounting.
- Corrected durable disclosure records to distinguish all retrieved context sent externally from the smaller set of citations selected in model output.
- Added the Owner Console's typed same-origin API client and loopback core proxy with in-memory-only CSRF handling, structured errors, and executable browser-client contract tests.
- Replaced the M0 Owner Console cards with authenticated canonical conversation, turn inspection, memory correction/contestation, model cost/disclosure, Guardian status, and explicit unavailable-surface workflows, using text-node rendering for all private data.
- Added an explicit `serve-synthetic` M1 acceptance runtime that preserves signed Guardian reads while wiring process-local authentication, memory, deterministic device routing, conversation, correction, and inspection from a private credential file.
- Added authenticated owner health and media-metadata reports plus console views, with deterministic component/source ordering, owner isolation, explicit disabled capture, retention/disclosure fields, and no media content endpoint or infrastructure secrets.
- Added atomic inbound-message/reply-work acceptance, leased at-least-once processing, capped exponential backoff with stable jitter, failure/disclosure attempt records, authenticated processing inspection, dead-work resume, and process-local synthetic worker behavior.
- Replaced client adapters' arbitrary authorization-ID input with an exact message-hash-bound policy request/allow decision contract and a synthetic transport that deduplicates retries under one stable external receipt.
- Added a process-local outbound-delivery state machine with deterministic leases, Guardian revalidation, capped stable-jitter retry, crash recovery through transport deduplication, append-only adapter/execution receipts, visible terminal failure, and fresh-policy owner resume.
- Added an additive outbound-delivery migration and restricted-role PostgreSQL adapter that cross-check mutable job payloads against immutable identity/history, persists exact policy and side-effect receipts, recovers expired leases, restricts reauthorization to core, and completes receipts plus work atomically.
- Added authenticated thread-scoped outbound-delivery list/inspection plus recent-authenticated CSRF enqueue/resume APIs, with idempotent duplicate responses, `202 Accepted` recovery states, ownership concealment, and generic conflict/unavailable errors.
- Wired exact-authority delivery into the explicit synthetic runtime with an in-memory fake client route, a separately bounded background worker, truthful worker/ephemeral-queue health, and an end-to-end canonical output delivery drill that performs no channel network call.
- Added the Owner Console outbound-delivery workflow with typed same-origin API calls, memory-only idempotency until acceptance, exact-action confirmation, recent-authenticated enqueue/resume, complete attempt/resumption inspection, and deterministic recovery summaries derived from canonical status.
- Added strict synthetic Telegram pairing, normalized update, attachment disposition, ingestion receipt, and positive long-poll contracts plus a replayable no-network source and monotonic in-memory offset store that durably records each observation/outcome before advancement.
- Added Guardian-gated Telegram canonical ingestion into one pre-existing owner thread, with adapter/update-scoped idempotency, reject-before-fetch attachments, atomic reply-work enqueueing, exact receipt replay, and crash recovery between canonical acceptance and cursor commit.
- Added a bounded Telegram poll worker with whole-batch ordering checks, source-outage immutability, forbidden-mode no-poll behavior, redacted health, and no-network synthetic lifespan wiring into a dedicated canonical intake thread.
- Added replay-stable synthetic Telegram pairing challenges, thread-safe candidate/active-pair state, CSRF and recent-auth protected redacted pairing APIs, live ingestion resolution, and authority-reducing revocation without pre-granting channel identity at runtime startup.
- Added the Owner Console Telegram pairing workflow with typed same-origin reads/mutations, masked provider identifiers, transient cleared challenge entry, recent-authenticated explicit confirm/revoke controls, optional-unconfigured state, and post-mutation projection refresh.
- Added an immutable Telegram attachment-intake contract plus no-network rejecting and bounded in-memory quarantine backends with pre-fetch metadata policy, hard byte quotas, content-addressed receipts, and exact replay.
- Integrated reject-or-quarantine attachment intake after exact Telegram pairing validation, with ordered outcome checks before canonical mutation, Melloa-owned quarantine references, attachment-only reply work, no-refetch crash recovery, and model-input isolation from attachment bytes and metadata.
- Added owner-bound synthetic quarantine expiry with a one-hour-to-seven-day policy bound, newest-reference extension for deduplicated blobs, deterministic bounded sweeps, quota reclamation, and immutable content-free deletion tombstones.
- Wired quarantine expiry into a separately bounded no-network lifespan worker that permits local deletion only in Guardian `normal`/`offline`, validates backend receipt bounds and owner scope, and reports redacted optional health.
- Added an authenticated owner retention report with strict policy bounds, deletion-scope availability, tombstone/rebuild obligations, external-copy status, aggregate inventory coverage, and honest backup-expiry disclosure; unavailable deletion and inventory paths remain explicit.
- Added a typed same-origin Owner Console retention view that renders policy, aggregate coverage, external-copy limits, and backup expiry through safe text nodes while withholding deletion controls until a real recent-authenticated mutation boundary exists.

## M0 implementation — 16 August 2026

- Added strict event, identity, assertion/provenance, policy, audit, model, conversation, and Guardian contracts with generated JSON Schemas.
- Added PostgreSQL 18 plus pgvector migration, narrow role groups, durable jobs/outbox, append-only records, and audit predecessor enforcement.
- Added deterministic deny-first policy evaluation with exact-action hashes, Guardian modes, privacy constraints, grants, budgets, approvals, and platform prohibitions.
- Added Ed25519 Guardian status verification and a separate Guardian implementation with six modes, chained receipts, atomic projection, and journal reconciliation.
- Added deterministic fake model, client, and Guardian adapters with no credentials or external calls.
- Added the mandatory private Owner Console TypeScript shell with loopback-only serving and explicit M1 authentication gate.
- Added digest/commit-pinned CI, locked Python/Node toolchains, PostgreSQL integration tests, and encrypted restic clean-restore drill.
- Added M0 threat review, development guide, Guardian protocol reference, security policy, contribution guide, and recovery runbook.

## v0.2 — 16 August 2026

- Adopted **Meliorism** as the guiding philosophy, **Melloa** as the system/project, and **Melli** as the primary persistent intelligence.
- Reserved **Otto** as an optional philosophical reference; it is not a mandatory V1 component or agent.
- Made the private **Owner Console** a mandatory V1 client and inspection surface.
- Made conversation a channel-independent core capability with the Owner Console as the primary first-party client.
- Reclassified Telegram long polling as an optional secondary remote transport.
- Added structured decision/run inspection requirements without requiring or storing hidden chain-of-thought.
- Recorded repository roles for `melloa`, `melloa-guardian`, and the private `melloa-deployment` repository.
- Added ADR-013 and ADR-014 and updated diagrams, milestones, onboarding, and traceability.

## v0.1 — 15 August 2026

- Initial research-backed architecture baseline.
