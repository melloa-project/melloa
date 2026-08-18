# Development and verification

## Supported toolchain

- Python 3.13 or newer, locked with `uv.lock`;
- uv 0.12.0 for the blessed command path;
- Node.js 22 and the committed npm lock for the Owner Console;
- Docker for PostgreSQL integration and encrypted recovery drills;
- Go 1.24 or newer in the separate Guardian repository.

No model key, Telegram token, camera, public domain, owner deployment repository, or personal data is needed for bootstrap, verification, or the default no-network MVP. A disposable mode-`0600` token file is optional only when exercising the real Telegram Bot API path.

## Newcomer path

If this is your first checkout, run `make preview`, then follow [Start Melloa locally](getting-started.md). That command installs locked dependencies, builds the independent Guardian and production Owner Console, starts the private services, and cleans up disposable state on exit. The walkthrough completes an authenticated conversation, inspects provenance and disclosures, and validates an owner export.

The checks below are project and release gates. They are deliberately broader than what is required merely to try the preview; they do not open outside contribution intake.

## Bootstrap

```bash
make bootstrap
```

This source-gates the locks, installs all frozen Python dependency groups without the project, then builds the local project with only its exact locked Hatchling backend and installs web dependencies with lifecycle scripts disabled. `.env.example` contains paths only. Put local secret files under an owner-controlled runtime directory with mode `0600`; do not put values in `.env` or command arguments.

Repository configuration resolves Python and web packages only from the reviewed public PyPI and npm registries. `make dependency-sources` rejects lockfiles containing any other dependency host before bootstrap attempts network access.

## Dependency inventory and SBOM

CI generates a deterministic CycloneDX 1.6 dependency inventory from the committed Python runtime, development, documentation, and build declarations reconciled to `uv.lock`, the npm lock, and the independent Guardian Go manifests without resolving anything over the network. It records locked source/checksum evidence, has no timestamp or random serial number, and is uploaded as the short-lived `dependency-sbom` CI artifact.

With both publicly readable repositories checked out as siblings, reproduce it locally with:

```bash
python3 tools/check_dependency_sources.py
python3 tools/generate_dependency_sbom.py \
  --guardian-root ../melloa-guardian \
  --output dist/melloa-dependency-sbom.cdx.json
python3 tools/generate_dependency_sbom.py \
  --guardian-root ../melloa-guardian \
  --output dist/melloa-dependency-sbom.cdx.json \
  --check
```

The generated `dist/` artifact is intentionally not a canonical source file or a substitute for a signed release/provenance statement. It covers committed Melloa Python runtime/development/docs/build dependencies, npm packages, and Guardian Go modules. It does not inventory GitHub Actions, runner or operating-system toolchains, containers, deployment state, or prove which bytes executed. Guardian currently has no third-party Go requirements, so its module and Go version are recorded with a zero dependency count.

## Fast checks

```bash
make check
```

The target verifies generated schemas and migration digests, Python lint/type/unit tests, the TypeScript shell, architecture validation, and strict documentation build.

## Database integration

```bash
make integration
```

The harness starts a digest-pinned PostgreSQL 18 plus pgvector container on a random loopback port, provisions non-login role groups, applies immutable migrations through the CLI, and verifies append, audit, idempotency, leased conversation and delivery work, atomic completion, mutation denial, role boundaries, and stop/rebuild MVP journeys. Those journeys retain hashed owner sessions and append-only logout revocations, canonical conversation/model provenance, memory corrections and content-deletion evidence, assembled audit append records, delivery receipts, Telegram pairing/revocation authority, normalized intake receipts, poll offsets, and reply work. They also prove that owner-credential rotation invalidates a prior session without storing plaintext credentials, session tokens, or CSRF proofs; active-session inventory remains credential-bound; and the recent-authenticated, CSRF-protected sign-out-other-sessions operation durably revokes every other active session. Session issuance/revocation audit evidence excludes all credential and browser-token values, survives restart in the same transaction as its source state, and rolls bulk revocations back if audit append fails. The container is destroyed afterward.

`MELLOA_POSTGRES_IMAGE` and `MELLOA_RESTIC_IMAGE` exist only for an operator to select a preloaded image reference when a daemon cannot reach the public registry. CI and the documented default remain digest-pinned. Any override must resolve to the reviewed digest and must be recorded with the test evidence.

## Recovery integration

```bash
make recovery
```

The recovery harness is intentionally separate because a green unit suite is not evidence that a backup restores. See [the recovery runbook](operations/m0-recovery.md).

## Generated contracts

```bash
UV_CACHE_DIR=.cache/uv uv run python tools/generate_schemas.py
UV_CACHE_DIR=.cache/uv uv run python tools/update_migration_manifest.py
UV_CACHE_DIR=.cache/uv uv run python tools/update_manifest.py
```

Run generation only when intentionally changing a model or adding a migration. CI uses `--check` and rejects stale output. Released SQL migrations are immutable; add a new numbered file instead of editing one.

## Run the owner-facing MVP

Use [Start Melloa locally](getting-started.md) as the canonical setup and smoke guide. Use [Configure advanced local routes and durable state](run-current-mvp.md) only when you need the individual Guardian/core/console commands, optional Ollama/Qwen, PostgreSQL, isolated Codex CLI, or Telegram configuration.

The ordinary `melloa serve` command remains the fail-closed M0 status surface, while `serve-synthetic` remains the no-network test runtime. `serve-mvp` is the explicit owner-facing preview with process-local stores by default and optional partial PostgreSQL restart durability through a private core-role DSN file. Do not bind any surface publicly. For a private-network deployment, terminate HTTPS on the same origin so the `__Host-` secure session cookie remains mandatory; never weaken cookie security or enable CORS to simplify a demo.

## Validate an owner export

`melloa export-mvp` writes the current MVP's canonical conversation and memory-inspection records to a JSONL bundle with copied JSON Schemas, `manifest.json`, and `checksums.sha256`. Deleted assertion values are not restored into the export, but their memory-inspection rows preserve content-free tombstone and rebuild-work evidence. It requires the same signed Guardian status paths and mode-`0600` owner credential file as the MVP runtime, and accepts the optional core-role PostgreSQL DSN file when exporting durable preview stores.

```bash
uv run melloa export-mvp \
  --status "$MELLOA_MVP_STATE/guardian-status.json" \
  --public-key "$MELLOA_MVP_STATE/guardian-public.pem" \
  --owner-credential-file "$MELLOA_MVP_STATE/owner-credential" \
  "${database_args[@]}" \
  --output-dir "$MELLOA_MVP_STATE/export-test"

uv run melloa import-validate \
  --bundle-dir "$MELLOA_MVP_STATE/export-test"
```

The import command is a dry-run validator only. It checks checksums, schema readability, and basic references; it does not mutate a database or prove encrypted backup/restore.
