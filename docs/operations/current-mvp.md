# Current MVP operations runbook

## Purpose

Operate and validate the current owner-facing MVP preview without turning it into an implied production deployment. This runbook covers the reviewed loopback process-local path, optional PostgreSQL owner-state durability, encrypted clean-restore evidence, current export validation, visual smoke evidence, and incident response for the preview.

Use [Start Melloa locally](../getting-started.md) for the canonical launch and owner journey. Use [Configure advanced local routes and durable state](../run-current-mvp.md) for individual process commands. This page is the operator checklist for deciding whether a run is healthy enough to demonstrate, inspect, or continue developing.

## Boundaries

- The default runtime is process-local and disposable.
- Optional PostgreSQL mode is the canonical durable owner-state store; an installation is not backed up until its own encrypted schedule and destinations are configured and tested.
- `make recovery` proves the full logical-backup mechanism against synthetic owner state; it does not report the age or existence of an installation backup.
- Guardian remains independently controlled; do not edit signed Guardian status JSON by hand.
- The Owner Console and core bind loopback only in this preview.
- No personal, sensitive, production, or long-lived owner data belongs in the preview.
- The browser download ZIP and CLI export directory are plaintext unless wrapped with `melloa export-encrypt`.
- The encrypted export wrapper is not a signed archive, blob export, logical SQL snapshot, import executor, or backup proof.

## Prerequisites

- A clean repository checkout with `make bootstrap` completed.
- The sibling Guardian repository built from the documented path.
- A private mode-`0600` owner credential file under a disposable `MELLOA_MVP_STATE` directory.
- Optional Ollama, isolated Codex CLI, Telegram Bot API token file, and PostgreSQL container only when testing those paths.
- Docker access only for PostgreSQL integration, visual smoke, or recovery evidence that needs containers.

## Start Checklist

1. Create the disposable owner state and credential exactly as documented.
2. Build and initialize Guardian with a disposable signing identity.
3. Keep Guardian in `offline` for the local-only path. Transition through `read-only`, `no-actions`, then `normal` only when a real external route or Telegram path is intentionally enabled.
4. Start optional dependencies before the core: Ollama, isolated Codex CLI config, Telegram token file, or PostgreSQL.
5. Start `uv run melloa serve-mvp` with loopback `--host 127.0.0.1`.
6. Start the web console with `MELLOA_CORE_URL` pointing at that loopback core.
7. Open the web console through the web port, not the core port.

Record the core startup JSON with the incident/change notes for the run. It is intentionally non-secret and describes persistence mode, configured routes, Telegram mode, and disabled boundaries.

## Health Validation

Run these checks before treating the preview as usable:

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
```

Then verify these owner-visible states:

- **Conversation** accepts a disposable message and the turn inspector shows route attempts, disclosure, evidence, policy decision, latency, and available usage data.
- **Providers** labels synthetic fallback clearly and reports any Ollama or Codex route without exposing credentials or private paths.
- **Timeline** shows bounded content-free canonical records; **Timeline -> Audit** shows only the owner-export audit projection after an export preview is generated.
- **Memory** can inspect the seed assertion; deletion removes retained assertion content while preserving tombstone and rebuild evidence.
- **Operations** reports process-local, PostgreSQL, backup, retention, and export readiness without overstating durability.
- **Settings -> Owner session** lists sessions without token or digest values and can sign out other sessions after recent authentication.
- **Settings -> Telegram** says **Synthetic fixture** unless the real Bot API path was explicitly configured.

In PostgreSQL mode, stop and restart only the core, then verify the same unexpired session remains read-capable, the owner can unlock mutations again, and canonical conversations, memory correction/deletion evidence, delivery work, Telegram pairing/intake state, and audit append records survive the restart as documented.

## Durable Recovery Validation

Run the clean-database recovery traversal before treating PostgreSQL state as recoverable:

```bash
make recovery
```

The drill applies every migration, creates a synthetic owner conversation and evidence through the authenticated owner API, encrypts a logical dump with restic, restores it into a fresh database, and traverses the same conversation, explanation, memory, session/audit, and read-only boundaries after restore. It is deliberately separate from the Owner Console ZIP, which remains a portability package without import authority. See [Durable owner-state recovery](m0-recovery.md).

## Export Validation

For the running web path, use **Operations -> Export -> Download current ZIP**, unzip into an empty directory, and run:

```bash
uv run melloa import-validate --bundle-dir <unzipped-export-dir>
```

For the CLI path, use the commands in [Configure advanced local routes and durable state](../run-current-mvp.md#8-export-and-validate-owner-data):

```bash
uv run melloa export-mvp ...
uv run melloa import-validate --bundle-dir "$MELLOA_MVP_EXPORT_DIR"
uv run melloa export-encrypt ...
uv run melloa export-decrypt-validate ...
```

Acceptance requires successful checksum validation, schema readability, referential checks, and encrypted package validation when the wrapper is used. It does not prove import execution, backup restore, blob coverage, SQL snapshot coverage, or signature verification.

## Release Evidence

For a code or checked-in documentation change that affects the current MVP, capture the narrowest relevant checks plus the full gate before release when practical:

```bash
UV_SYSTEM_CERTS=true make bootstrap check
UV_SYSTEM_CERTS=true make integration
UV_SYSTEM_CERTS=true make recovery
```

For owner-console behavior or visual-reference changes, also run the built-server authenticated smoke path:

```bash
MELLOA_WEB_URL=http://127.0.0.1:<web-port> \
MELLOA_OWNER_CREDENTIAL_FILE="$MELLOA_MVP_STATE/owner-credential" \
npm --prefix apps/web run screenshots:mvp
```

Then verify generated artifacts:

```bash
UV_SYSTEM_CERTS=true uv run python tools/update_manifest.py --check
git diff --check -- MANIFEST.sha256 docs apps/web src tests
UV_SYSTEM_CERTS=true uv run mkdocs build --strict
```

If Docker cannot fetch the digest-pinned PostgreSQL or restic images, record the exact pull failure and rerun the blocked integration or recovery gate once the reviewed image is available. Do not substitute an unreviewed image tag as acceptance evidence.

## Incident Response

Use the smallest Guardian mode that preserves owner safety:

| Symptom | Immediate action | Validation before resuming |
|---|---|---|
| Core readiness fails | Keep web/core loopback only, inspect health JSON and startup record | Readiness returns expected Guardian and persistence state |
| Unexpected external disclosure | Move Guardian to `no-actions` or `stopped`, preserve logs, review route and policy evidence | Route config, timeline/activity, and disclosure records explain the attempted send |
| Telegram token exposure | Stop core, revoke token in BotFather, replace the mode-`0600` token file, revoke pairing | Settings shows only the intended new pairing and redacted provider state |
| PostgreSQL mismatch or migration error | Stop core, preserve the database volume, do not edit rows by hand | `melloa migrate check` passes and the core starts without fallback |
| Export validation fails | Preserve the failed bundle in owner-controlled storage, do not distribute it | `import-validate` and, if used, `export-decrypt-validate` pass on a fresh bundle |
| Owner credential or session concern | Rotate the disposable credential, restart preview, sign out other sessions if PostgreSQL is in use | Prior session fails closed and active-session inventory is credential-bound |

Never restart in `normal` after a suspected authority, credential, or disclosure incident until the exact route, policy decision, audit evidence, and external provider state have been inspected.

## Stop And Cleanup

Stop web, core, and optional foreground dependencies with `Ctrl-C`. If PostgreSQL was enabled, remove the disposable container and volume before deleting the private state directory:

```bash
if [[ -n "${MELLOA_MVP_POSTGRES_CONTAINER:-}" ]]; then
  docker rm --force "$MELLOA_MVP_POSTGRES_CONTAINER"
  docker volume rm "$MELLOA_MVP_POSTGRES_VOLUME"
fi
rm -rf -- "$MELLOA_MVP_STATE"
```

Local cleanup removes disposable local files only. Revoke real provider sessions, Telegram tokens, offsite copies, or external account access at the provider when those paths were enabled.
