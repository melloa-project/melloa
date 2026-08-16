# Development and verification

## Supported toolchain

- Python 3.13 or newer, locked with `uv.lock`;
- uv 0.12.0 for the blessed command path;
- Node.js 22 and the committed npm lock for the Owner Console;
- Docker for PostgreSQL integration and encrypted recovery drills;
- Go 1.24 or newer in the separate Guardian repository.

No model key, Telegram token, camera, public domain, owner deployment repository, or personal data is needed for bootstrap, verification, or the default no-network MVP. A disposable mode-`0600` token file is optional only when exercising the real Telegram Bot API path.

## Bootstrap

```bash
make bootstrap
```

This installs locked Python and web dependencies. `.env.example` contains paths only. Put local secret files under an owner-controlled runtime directory with mode `0600`; do not put values in `.env` or command arguments.

Repository configuration resolves Python and web packages only from the reviewed public PyPI and npm registries. `make dependency-sources` rejects lockfiles containing any other dependency host before bootstrap attempts network access.

## Fast checks

```bash
make check
```

The target verifies generated schemas and migration digests, Python lint/type/unit tests, the TypeScript shell, architecture validation, and strict documentation build.

## Database integration

```bash
make integration
```

The harness starts a digest-pinned PostgreSQL 18 plus pgvector container on a random loopback port, provisions non-login role groups, applies immutable migrations through the CLI, and verifies append, audit, idempotency, leased conversation and delivery work, atomic completion, mutation denial, role boundaries, and stop/rebuild MVP journeys. Those journeys retain canonical conversation/model provenance, memory corrections, delivery receipts, Telegram pairing/revocation authority, normalized intake receipts, poll offsets, and reply work while requiring a new process-local owner session. The container is destroyed afterward.

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

Use [Run the current MVP](run-current-mvp.md) as the sole setup and smoke guide. It includes disposable Guardian initialization, mode-`0600` owner authentication, optional Ollama/Qwen, isolated experimental Codex CLI, and Telegram Bot API configuration, exact core and console commands, expected URLs and visual states, limitations, cleanup, and troubleshooting.

The ordinary `melloa serve` command remains the fail-closed M0 status surface, while `serve-synthetic` remains the no-network test runtime. `serve-mvp` is the explicit owner-facing preview with process-local stores by default and optional partial PostgreSQL restart durability through a private core-role DSN file. Do not bind any surface publicly. For a private-network deployment, terminate HTTPS on the same origin so the `__Host-` secure session cookie remains mandatory; never weaken cookie security or enable CORS to simplify a demo.

## Validate an owner export

`melloa export-mvp` writes the current MVP's canonical conversation and memory-inspection records to a JSONL bundle with copied JSON Schemas, `manifest.json`, and `checksums.sha256`. It requires the same signed Guardian status paths and mode-`0600` owner credential file as the MVP runtime, and accepts the optional core-role PostgreSQL DSN file when exporting durable preview stores.

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
