# Development and verification

## Supported toolchain

- Python 3.13 or newer, locked with `uv.lock`;
- uv 0.12.0 for the blessed command path;
- Node.js 22 and the committed npm lock for the Owner Console;
- Docker for PostgreSQL integration and encrypted recovery drills;
- Go 1.24 or newer in the separate Guardian repository.

No model key, Telegram token, camera, public domain, owner deployment repository, or personal data is needed.

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

The harness starts a digest-pinned PostgreSQL 18 plus pgvector container on a random loopback port, provisions non-login role groups, applies immutable migrations through the CLI, and verifies append, audit, idempotency, leased conversation work, atomic completion, mutation denial, and role boundaries. The container is destroyed afterward.

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

## Private local services

The M0 API requires a Guardian status and public key:

```bash
uv run melloa serve \
  --status /var/lib/melloa-guardian/status.json \
  --public-key /etc/melloa-guardian/status-signing-key.pub.pem \
  --host 127.0.0.1 \
  --port 8000
```

The Owner Console keeps browser authentication same-origin by proxying only private API and health paths to the core. Its session cookie remains HTTP-only and its CSRF proof remains in page memory:

```bash
npm --prefix apps/web run build
MELLOA_CORE_URL=http://127.0.0.1:8000 npm --prefix apps/web start
```

The web source now implements login/reauthentication, Guardian and authenticated component health, canonical threads/messages, visible bounded reply processing with explicit dead-work resume, structured turn inspection, memory correction/contestation, bounded cost/disclosure activity, and metadata-only media inspection. API and owner text is rendered through text nodes, credentials are cleared immediately after submission, and no session or CSRF material is persisted in browser storage. The media contract deliberately exposes no content endpoint, blob path, camera address, or credential.

`GET /api/v1/conversations/{thread_id}/processing` and the message-scoped processing route expose owner-authenticated state, capped attempt history, retry eligibility, redacted error codes, and disclosure identifiers. `POST /api/v1/conversations/{thread_id}/messages/{message_id}/resume` requires the ordinary CSRF mutation proof and only grants a new bounded budget after work has reached terminal `dead` state. A message submission that was accepted but did not complete its reply returns `202 Accepted`; clients must not resend it under a new idempotency key.

The ordinary `melloa serve` command remains the fail-closed M0 status surface. For an explicit M1 acceptance drill, create a process-local owner credential file and start the synthetic runtime:

```bash
install -d -m 0700 "${XDG_RUNTIME_DIR}/melloa"
umask 077
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' \
  > "${XDG_RUNTIME_DIR}/melloa/owner-credential"

uv run melloa serve-synthetic \
  --status /var/lib/melloa-guardian/status.json \
  --public-key /etc/melloa-guardian/status-signing-key.pub.pem \
  --owner-credential-file "${XDG_RUNTIME_DIR}/melloa/owner-credential"
```

In a second terminal, build and start the same-origin console as shown above, then authenticate with the generated file value. The core prints the non-secret seeded assertion ID for the Memory view. This runtime still verifies the signed Guardian projection, registers only a deterministic device model route and an in-memory fake client route, runs process-local bounded reply and outbound-delivery workers, reports its queue and storage as degraded because neither survives restart, reports camera capture and backup as disabled, performs no provider/channel network calls, and loses all sessions, conversations, corrections, retry state, delivery state, and activity on restart. It is deliberately unsuitable for personal or production data.

When the signed Guardian mode is `normal`, the Conversation area's **Outbound delivery** panel can exercise the fake route: choose a canonical message, enter `client.fake` and `synthetic:owner`, then reauthenticate before authorizing the exact action. The console keeps the transport idempotency key only in memory until canonical acceptance, lists the complete redacted delivery status, summarizes queued/running/dead/completed recovery state from that status, and requires another recent-authenticated confirmation before a dead item is resumed under fresh policy. No separate summary record is created and no channel network call occurs.

For a deployed console, terminate private HTTPS on the same origin so the `__Host-` secure session cookie remains mandatory. Do not weaken cookie security to accommodate a public or cross-origin UI.

Do not bind either surface publicly. The CLI rejects unspecified and globally routable addresses; loopback, RFC1918/ULA, and Tailscale's carrier-grade NAT range are accepted.
