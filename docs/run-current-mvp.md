# Configure advanced local routes and durable state

This is the advanced operator path after the canonical [`make preview`](getting-started.md) journey works. It exposes the individual Guardian, core, console, model, database, and channel controls needed to add a real local Qwen route through Ollama, optional PostgreSQL owner-state durability, an isolated subscription-backed Codex CLI route, or the optional Telegram Bot API adapter.

Use one optional boundary at a time and repeat the conversation, explanation, inspection, export, and recovery checks before combining them. Use [the local operations runbook](operations/current-mvp.md) for health validation, incident response, release evidence, and cleanup.

With an eligible model route, the result is a usable loop:

> owner login → canonical conversation → provider-neutral model route → Melli reply → route, disclosure, latency, token, cost, evidence, and decision inspection

The default no-network path exercises the same owner controls and evidence without claiming semantic help:

> owner login → canonical conversation → fixed guided-tour response → explicit non-Melli label → route, disclosure, cost, evidence, and decision inspection

With Telegram explicitly enabled, the same canonical loop also supports:

> private `/start` → Owner Console confirmation → Telegram text → canonical conversation → route result → exact policy-authorized reply to the same pairing

## Reproduce the manual baseline

Use [Start Melloa locally](getting-started.md) for the product path. The table below maps that launcher's safe defaults to the manual process controls used by this advanced guide:

| Guide section | Manual baseline choice |
|---|---|
| Prerequisites and bootstrap | Install Python, uv, Node.js, and Go; clone the two public sibling repositories; run `make bootstrap` |
| 1. Disposable owner paths | Follow as written |
| 2. Guardian | Build it independently, initialize disposable keys, and leave it in signed `offline` mode |
| 3. Model route | Set `model_args=()` and `codex_args=()`; the UI labels the deterministic synthetic route clearly |
| 4. Telegram | Skip it and set `telegram_args=()` |
| 5. Core persistence | Set `database_args=()` and start the loopback core |
| 6–7. Owner Console | Start the production web server, log in, create a conversation, send a disposable message, and inspect the turn |
| 8. Export | Download and validate the owner export while the process-local core is still running |
| Stop and clean up | Stop both processes and remove the disposable state directory |

After that loop works, add **one optional boundary at a time**—local Ollama, PostgreSQL owner-state durability, isolated Codex CLI, or Telegram—and verify the corresponding disclosure and health state before combining them. The remainder of this page provides the exact commands, expected evidence, limitations, and troubleshooting for every path.

!!! warning "Local preview, not a personal-data deployment"
    The default path loses its state when the core stops. PostgreSQL adds the explicitly reported durable owner-state boundaries, but this disposable setup has no scheduled/offsite backup, owner-held recovery key, or production deployment controls. Use disposable data, keep every server on loopback, run `make recovery` to prove the clean-restore mechanism, and read [Current limitations](#current-limitations) before enabling an optional integration.

## Prerequisites

- Linux or macOS with Bash;
- Python 3.13 or newer;
- [uv](https://docs.astral.sh/uv/) 0.12.0;
- Node.js 22 or newer and npm;
- Go 1.24 or newer for the separate Guardian fixture;
- optionally [Ollama](https://ollama.com/) for the recommended real local-model path;
- optionally the [OpenAI Codex CLI](https://developers.openai.com/codex/cli/) and an eligible subscription for the experimental external route;
- optionally Docker and the repository's digest-pinned PostgreSQL 18 plus pgvector image for the durable-state path.

The commands assume the main and Guardian repositories are siblings:

```text
workspace/
├── melloa/
└── melloa-guardian/
```

From the workspace directory, clone anything missing and bootstrap Melloa:

```bash
git clone https://github.com/melloa-project/melloa.git
git clone https://github.com/melloa-project/melloa-guardian.git
cd melloa
make bootstrap
```

If the repositories already exist, start in the `melloa` repository and run only `make bootstrap`. No paid API key, Telegram token, database, Docker daemon, or public hostname is required for the default path.

If `uv` fails with `UnknownIssuer` on a managed network and the organization CA is already installed in the system trust store, use `UV_SYSTEM_CERTS=true make bootstrap`. Never bypass TLS verification or accept an unexpected certificate; stop and inspect the network trust path if the issuer is not one you expect.

## 1. Create the disposable owner paths

Run these commands from the `melloa` repository:

```bash
export MELLOA_MVP_STATE="$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/melloa-mvp.XXXXXX")"
chmod 0700 "$MELLOA_MVP_STATE"
umask 077
python3 -c 'import secrets; print(secrets.token_urlsafe(32))' \
  > "$MELLOA_MVP_STATE/owner-credential"
chmod 0600 "$MELLOA_MVP_STATE/owner-credential"
printf 'Disposable MVP state: %s\n' "$MELLOA_MVP_STATE"
printf 'Owner credential: '
cat "$MELLOA_MVP_STATE/owner-credential"
```

Keep this terminal open. The credential is an ephemeral local bootstrap value. It is never placed in a command argument, environment variable, repository file, browser storage, or screenshot.

## 2. Build and initialize Guardian

Build the independently controlled Guardian binary:

```bash
make -C ../melloa-guardian check build
```

Create a disposable signing identity and transition once from the mandatory initial `stopped` state to `offline`:

```bash
guardian="../melloa-guardian/bin/guardianctl"
guardian_flags=(
  --status-file "$MELLOA_MVP_STATE/guardian-status.json"
  --audit-file "$MELLOA_MVP_STATE/guardian-audit.jsonl"
  --private-key-file "$MELLOA_MVP_STATE/guardian-private.pem"
  --public-key-file "$MELLOA_MVP_STATE/guardian-public.pem"
  --lock-file "$MELLOA_MVP_STATE/guardian.lock"
)

"$guardian" init \
  --instance-id local-mvp-guardian \
  --key-id guardian.status-v1 \
  "${guardian_flags[@]}"
"$guardian" transition \
  --mode offline \
  --reason owner.local_mvp \
  "${guardian_flags[@]}"
```

Verify the signed projection through Melloa's read-only port:

```bash
uv run melloa guardian-status \
  --status "$MELLOA_MVP_STATE/guardian-status.json" \
  --public-key "$MELLOA_MVP_STATE/guardian-public.pem"
```

Expected output includes `"mode": "offline"`, `"sequence": 2`, and `"key_id": "guardian.status-v1"`. The main runtime receives no Guardian private key, transition command, signing API, or host-control authority.

## 3. Choose a model route

For the first-run no-network path, enable neither optional route:

```bash
model_args=()
codex_args=()
```

The deterministic fixture remains available and visibly labelled. It proves the complete conversation, provenance, policy, inspection, and export loop without pretending to be a real intelligence route.

### Optional: start local Qwen through Ollama

This is the recommended route because it requires no per-token billing and makes no external disclosure. Install Ollama using its upstream instructions, then pull the model:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

The dated instruct tag avoids moving-alias drift and is suited to bounded structured conversation output.

If Ollama is not already running as a service, keep it running in another terminal:

```bash
ollama serve
```

For the canonical Owner Console journey, return to the repository and use the reviewed selector; it performs the endpoint and exact-model preflight for you:

```bash
make preview PREVIEW_MODEL=ollama
```

The remaining commands in this section are the advanced manual equivalent.

Verify its OpenAI-compatible endpoint:

```bash
curl -fsS http://127.0.0.1:11434/v1/models >/dev/null \
  && echo "Ollama OpenAI-compatible endpoint is ready"
```

The reviewed example route is `config/routes/ollama-qwen.example.json`. It declares device-only processing, zero configured cost, no-training retention, bounded timeouts, and the exact `qwen3:4b-instruct-2507-q4_K_M` model. The file contains no credential. Select it for the later core command:

```bash
model_args=(
  --model-route-config config/routes/ollama-qwen.example.json
)
```

If the configured endpoint later becomes unavailable or returns invalid structured output, routing fails visibly and falls back to the next explicitly ordered route, then to the labelled synthetic route.

### Optional: experimental subscription-backed Codex CLI

Start with this route disabled:

```bash
codex_args=()
```

Keep that empty array if you do not want owner text and selected citations sent to OpenAI. To enable the route, first install the official Codex CLI, then create a dedicated empty working directory and a dedicated `CODEX_HOME` inside the disposable state directory. Do not point Melloa at your ordinary home directory or ordinary Codex configuration:

```bash
codex_command="$(command -v codex)"
MELLOA_CODEX_EXECUTABLE="$(
  python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve(strict=True))' \
    "$codex_command"
)"
MELLOA_CODEX_HOME="$MELLOA_MVP_STATE/codex-home"
MELLOA_CODEX_WORK="$MELLOA_MVP_STATE/codex-work"
MELLOA_CODEX_ROUTE_CONFIG="$MELLOA_MVP_STATE/codex-route.json"

test -f "$MELLOA_CODEX_EXECUTABLE"
test -x "$MELLOA_CODEX_EXECUTABLE"
mkdir -p "$MELLOA_CODEX_HOME" "$MELLOA_CODEX_WORK"
chmod 0700 "$MELLOA_CODEX_HOME" "$MELLOA_CODEX_WORK"
"$MELLOA_CODEX_EXECUTABLE" --version
```

Authenticate that isolated Codex home with the official interactive subscription flow, then verify it without printing credential material:

```bash
CODEX_HOME="$MELLOA_CODEX_HOME" "$MELLOA_CODEX_EXECUTABLE" login
CODEX_HOME="$MELLOA_CODEX_HOME" "$MELLOA_CODEX_EXECUTABLE" login status
```

Only continue if the account's current data controls or contract satisfy the declared `retention.no-training` route policy. The route does not infer that policy from a subscription and Melloa cannot enforce provider-side retention. Enter a model ID actually available to that subscription, then generate the machine-specific, credential-free config:

```bash
read -r -p 'Codex model ID available to this subscription: ' MELLOA_CODEX_MODEL
test -n "$MELLOA_CODEX_MODEL"
case "$MELLOA_CODEX_MODEL" in
  [[:alnum:]]*) ;;
  *) echo 'Model ID must start with a letter or digit' >&2; exit 1 ;;
esac
case "$MELLOA_CODEX_MODEL" in
  *[!A-Za-z0-9._:/-]*) echo 'Model ID contains unsupported characters' >&2; exit 1 ;;
esac

python3 - \
  "$MELLOA_CODEX_ROUTE_CONFIG" \
  "$MELLOA_CODEX_EXECUTABLE" \
  "$MELLOA_CODEX_WORK" \
  "$MELLOA_CODEX_HOME" \
  "$MELLOA_CODEX_MODEL" <<'PY'
import json
import pathlib
import sys

target, executable, working_directory, codex_home, model_id = sys.argv[1:]
document = {
    "contract_version": "1.0.0",
    "route_id": "model.codex.subscription",
    "display_name": "Codex subscription route",
    "provider_id": "provider.openai-codex-subscription",
    "model_id": model_id,
    "executable": executable,
    "working_directory": working_directory,
    "codex_home": codex_home,
    "processing_location": "approved_provider",
    "allowed_sensitivities": ["public", "internal", "personal"],
    "provider_retention_policies": ["retention.no-training"],
    "max_input_tokens": 16384,
    "max_output_tokens": 2048,
    "estimated_max_cost_gbp": 0.0,
    "reliability": 0.85,
    "priority": 100,
    "timeout_ms": 120000,
    "health_timeout_ms": 2000,
    "inherit_proxy_environment": False,
    "sandbox_mode": "read-only",
    "approval_policy": "never",
    "session_persistence": "ephemeral",
    "ignore_user_config": True,
    "ignore_exec_rules": True,
}
pathlib.Path(target).write_text(
    json.dumps(document, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
chmod 0600 "$MELLOA_CODEX_ROUTE_CONFIG"
unset MELLOA_CODEX_MODEL

codex_args=(
  --cli-agent-route-config "$MELLOA_CODEX_ROUTE_CONFIG"
)
```

The checked-in template is `config/routes/codex-cli.example.json`; the generated copy supplies the actual executable, private directories, and selected model. Melloa accepts only an absolute config path with a canonical parent, opens that config without following symlinks, bounds its size, and rejects group/world-writable config files or containing directories. At invocation it resolves and validates the exact runtime paths, requires the executable and its containing directory not be group/world-writable, requires both private directories to be mode `0700` under a non-writable parent, sends the bounded prompt only over standard input, strips ambient API/AWS/SSH and unrelated environment variables, and invokes `codex exec` with a read-only sandbox, approval policy `never`, ignored user config/rules, an ephemeral session, and strict JSON output files. Codex receives its own isolated subscription authentication through `CODEX_HOME`; it receives no Guardian, deterministic-policy, Melloa credential-broker, or capability authority.

!!! danger "Read-only is not production host isolation"
    The Codex sandbox constrains model-generated commands, but this preview still starts a local executable as the same OS user. It is not a container, VM, dedicated account, or proven confidentiality boundary, and readable host files may remain in scope outside the empty working directory. Do not use this preview beside personal or production data. A production route needs the stronger isolation and dedicated runtime identity required by ADR-005; never treat a prompt instruction or CLI sandbox flag as the Guardian boundary.

Codex CLI does not currently return per-call token counts through this integration. The Owner Console therefore labels token and cost metadata **Unreported**. Recorded `0.0` route cost means no incremental per-call charge was measured by Melloa; it does not mean the subscription is free and it does not allocate the subscription fee to a turn.

## 4. Optionally enable real Telegram

Skip this section if you want the default no-network Telegram fixture, and run `telegram_args=()` in the core terminal. No Telegram account or token is required for the Owner Console loop.

!!! warning "Telegram is an external convenience channel"
    Telegram is not end-to-end encrypted for bots and Telegram may retain inbound and outbound content under its policies. Use only disposable text in this process-local preview. Never send secrets, recovery codes, highly sensitive memory, raw room media, exports, or Guardian-root instructions. The Owner Console remains the primary inspection and control surface.

Create a dedicated disposable bot with [BotFather](https://t.me/BotFather). Keep group joining disabled and do not add the bot to groups or channels. In the same private state directory, enter the token without placing it in shell history or an environment variable:

```bash
read -r -s -p 'Disposable Telegram bot token: ' telegram_bot_token
printf '\n'
printf '%s\n' "$telegram_bot_token" > "$MELLOA_MVP_STATE/telegram-bot-token"
unset telegram_bot_token
chmod 0600 "$MELLOA_MVP_STATE/telegram-bot-token"
telegram_args=(
  --telegram-bot-token-file "$MELLOA_MVP_STATE/telegram-bot-token"
)
```

The adapter accepts the token only from an exact mode-`0600` regular file. The token is never printed, included in startup output, returned by health APIs, stored in browser state, or placed in a Bot API query parameter. `MELLOA_TELEGRAM_BOT_TOKEN_FILE` is the equivalent path-only environment setting. `MELLOA_TELEGRAM_API_BASE_URL` may select a self-hosted Bot API only at localhost or a private literal IP; the default public endpoint is the canonical `https://api.telegram.org` origin.

The externally disclosed Codex route, fresh Telegram pairing, and outbound Telegram replies require Guardian `normal`. Already-paired Telegram polling and canonical intake may continue in `no-actions`, but challenge publication, confirmation, all outbound communication, and approved-provider inference remain denied. If either optional external route is enabled, progress through every required independently signed transition exactly once; do not edit the signed status JSON and do not give the private key or transition command to Melloa:

```bash
if ((${#codex_args[@]} > 0 || ${#telegram_args[@]} > 0)); then
  "$guardian" transition \
    --mode read-only \
    --reason owner.external_route_preflight \
    "${guardian_flags[@]}"
  "$guardian" transition \
    --mode no-actions \
    --reason owner.external_route_validation \
    "${guardian_flags[@]}"
  "$guardian" transition \
    --mode normal \
    --reason owner.external_routes_enabled \
    "${guardian_flags[@]}"
fi

uv run melloa guardian-status \
  --status "$MELLOA_MVP_STATE/guardian-status.json" \
  --public-key "$MELLOA_MVP_STATE/guardian-public.pem"
```

When either optional external route is enabled, expected output now includes `"mode": "normal"` and `"sequence": 5`. If both are skipped, keep `codex_args=()` and `telegram_args=()`, leave Guardian in `offline`, and use only device routes; local Owner Console conversation remains usable and external activity stays disabled.

## 5. Start the private core

Keep the zero-database default unless you are explicitly testing restart durability:

```bash
database_args=()
```

### Optional: enable PostgreSQL owner-state durability

This disposable local path gives the running core only the committed `melloa_core` privileges. The one-time migration connection remains separate. PostgreSQL binds a random loopback port; the core rejects public IPs, hostnames, service indirection, symlink DSN paths, and DSN files accessible by group or others.

```bash
export MELLOA_MVP_POSTGRES_CONTAINER="melloa-mvp-postgres-${RANDOM}-$$"
export MELLOA_MVP_POSTGRES_VOLUME="${MELLOA_MVP_POSTGRES_CONTAINER}-data"
postgres_image='pgvector/pgvector:0.8.6-pg18-trixie@sha256:78bf48b801e792f99e3ac62b5036fd3876e9be48afda16c1e331af1c75ceb2ff'

python3 -c 'import secrets; print(secrets.token_hex(32))' \
  > "$MELLOA_MVP_STATE/postgres-admin-password"
python3 -c 'import secrets; print(secrets.token_hex(32))' \
  > "$MELLOA_MVP_STATE/postgres-core-password"
chmod 0600 \
  "$MELLOA_MVP_STATE/postgres-admin-password" \
  "$MELLOA_MVP_STATE/postgres-core-password"

docker run --detach \
  --name "$MELLOA_MVP_POSTGRES_CONTAINER" \
  --publish 127.0.0.1::5432 \
  --security-opt no-new-privileges:true \
  --env POSTGRES_DB=melloa \
  --env POSTGRES_USER=postgres \
  --env POSTGRES_PASSWORD_FILE=/run/secrets/postgres-admin-password \
  --mount "type=bind,src=$MELLOA_MVP_STATE/postgres-admin-password,dst=/run/secrets/postgres-admin-password,readonly" \
  --volume "$MELLOA_MVP_POSTGRES_VOLUME:/var/lib/postgresql" \
  "$postgres_image"

for attempt in $(seq 1 60); do
  docker exec "$MELLOA_MVP_POSTGRES_CONTAINER" \
    pg_isready -U postgres -d melloa >/dev/null 2>&1 && break
  if ((attempt == 60)); then
    docker logs "$MELLOA_MVP_POSTGRES_CONTAINER" >&2
    false
  fi
  sleep 1
done

docker cp infra/postgres/init/001_roles.sql \
  "$MELLOA_MVP_POSTGRES_CONTAINER:/tmp/001_roles.sql"
docker exec "$MELLOA_MVP_POSTGRES_CONTAINER" \
  psql -v ON_ERROR_STOP=1 -U postgres -d melloa \
  --file /tmp/001_roles.sql

postgres_core_password="$(cat "$MELLOA_MVP_STATE/postgres-core-password")"
printf "CREATE ROLE melloa_mvp_core LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT PASSWORD '%s';\nGRANT melloa_core TO melloa_mvp_core;\n" \
  "$postgres_core_password" \
  | docker exec -i "$MELLOA_MVP_POSTGRES_CONTAINER" \
      psql -v ON_ERROR_STOP=1 -U postgres -d melloa
unset postgres_core_password

export MELLOA_MVP_POSTGRES_PORT="$(
  docker port "$MELLOA_MVP_POSTGRES_CONTAINER" 5432/tcp | awk -F: 'END {print $NF}'
)"
printf 'host=127.0.0.1 port=%s dbname=melloa user=postgres password=%s sslmode=disable\n' \
  "$MELLOA_MVP_POSTGRES_PORT" \
  "$(cat "$MELLOA_MVP_STATE/postgres-admin-password")" \
  > "$MELLOA_MVP_STATE/postgres-migrate-dsn"
printf 'host=127.0.0.1 port=%s dbname=melloa user=melloa_mvp_core password=%s sslmode=disable\n' \
  "$MELLOA_MVP_POSTGRES_PORT" \
  "$(cat "$MELLOA_MVP_STATE/postgres-core-password")" \
  > "$MELLOA_MVP_STATE/postgres-core-dsn"
chmod 0600 \
  "$MELLOA_MVP_STATE/postgres-migrate-dsn" \
  "$MELLOA_MVP_STATE/postgres-core-dsn"

uv run melloa migrate apply \
  --dsn-file "$MELLOA_MVP_STATE/postgres-migrate-dsn"
uv run melloa migrate check \
  --dsn-file "$MELLOA_MVP_STATE/postgres-migrate-dsn"
database_args=(--database-dsn-file "$MELLOA_MVP_STATE/postgres-core-dsn")
```

Both migration commands must report every committed version under `applied` and an empty `pending` list. Never pass either DSN as a command argument, reuse the migration DSN for the core, or expose the container publicly. Persistence alone does not mean this disposable instance has a configured backup; `make recovery` separately proves the repository's encrypted logical-backup and clean-restore mechanism. The core opens separate serialized connections for conversation, memory, delivery, Telegram, and audit/authentication stores and redacts connection failures.

In the terminal where `MELLOA_MVP_STATE` is set, run:

```bash
uv run melloa serve-mvp \
  --status "$MELLOA_MVP_STATE/guardian-status.json" \
  --public-key "$MELLOA_MVP_STATE/guardian-public.pem" \
  --owner-credential-file "$MELLOA_MVP_STATE/owner-credential" \
  "${database_args[@]}" \
  "${model_args[@]}" \
  "${codex_args[@]}" \
  "${telegram_args[@]}" \
  --host 127.0.0.1 \
  --port 8000
```

Before serving, the core prints a non-secret startup record. Expected fields include:

```json
{
  "external_disclosure_routes": [
    "model.codex.subscription"
  ],
  "experimental_cli_agent": {
    "approval_policy": "never",
    "configured": true,
    "external_disclosure": true,
    "melloa_authority": "none",
    "route_ids": [
      "model.codex.subscription"
    ],
    "sandbox": "read-only",
    "session_persistence": "ephemeral",
    "usage_metadata": "unreported"
  },
  "fallback_route_ids": [
    "model.local.ollama-qwen",
    "model.codex.subscription",
    "model.fake.deterministic"
  ],
  "persistence": {
    "durable_state": [],
    "ephemeral_state": [
      "authentication sessions",
      "canonical conversations and model provenance",
      "memory assertions and corrections",
      "reply and delivery retry state",
      "Telegram pairing, offsets, and attachment quarantine"
    ],
    "mode": "process-only-preview"
  },
  "route_ids": [
    "model.local.ollama-qwen",
    "model.codex.subscription",
    "model.fake.deterministic"
  ],
  "runtime": "owner-console-mvp-preview",
  "seed_assertion_id": "assertion_00000000000000000000000000000001",
  "synthetic_fallback": true,
  "telegram": {
    "adapter_id": "client.telegram.bot-api",
    "attachments": "rejected-before-fetch",
    "configured": true,
    "persistence": {
      "attachment_quarantine_bytes": "not-stored",
      "challenge_send_observation": "process-only-preview",
      "delivery_records": "process-only-preview",
      "pairing_offsets_ingestion": "process-only-preview"
    }
  }
}
```

This sample shows Ollama, Codex, and Telegram enabled while `database_args=()`. With `codex_args=()`, `external_disclosure_routes` and the CLI-agent `route_ids` are empty, `experimental_cli_agent.configured` is `false`, and the Codex route is absent from both route-order arrays. With `telegram_args=()`, `telegram.configured` is `false` and `telegram.adapter_id` is `null`. With PostgreSQL enabled, `persistence.mode` becomes `postgresql-partial-preview`, `durable_state` adds hashed owner sessions and append-only revocations, canonical conversation/model provenance, memory correction history, reply/delivery work, and Telegram pairing/intake/offset/dispatch state. `ephemeral_state` still lists challenge-send observation, attachment quarantine bytes, and provider health. Telegram `delivery_records` and `pairing_offsets_ingestion` become `postgresql`; challenge-send observation remains process-only and attachment bytes remain unstored. The deterministic model fallback remains enabled in every case. The startup record contains route IDs and fixed boundaries, never DSNs, database errors, Codex executable/home paths, subscription authentication, owner credential, Telegram token, or message content.

In PostgreSQL mode, an unexpired secure owner-session cookie remains valid through an ordinary core restart. The database stores only fixed-length SHA-256 digests for the owner credential, session token, and CSRF proof plus the non-secret principal contract; it never stores their plaintext values. Changing the configured owner credential makes earlier sessions fail closed, and signing out appends a revocation that remains effective after restart. **Settings → Owner session** lists every active session bound to the current credential, labels this browser, offers a recent-authenticated, CSRF-protected **Sign out other sessions** control, and triggers bounded cleanup for expired session rows and their revocations. Issuance and each ordinary or bulk revocation append deterministic content-free event/audit evidence; PostgreSQL does this in the same transaction as session state, and process-only auth appends through the configured audit store before changing the in-memory session map. Failed logins, missing/expired session denials outside routine session-status probing, and CSRF/recent-auth mutation denials append content-free security events through the configured audit store. The evidence contains only internal IDs, authentication method or denial boundary, lifecycle/denial state, reason code, event ID, and result. The browser still holds the CSRF proof only in page memory: reloading a restored read-capable session requires selecting **Unlock changes** and entering the owner credential before mutations.

Check the loopback endpoints from another terminal:

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
```

Both should return JSON. Readiness reports the signed Guardian state. It is `offline` for the local-only path and `normal` only after the explicit Telegram transition chain.

## 6. Start the Owner Console

In a separate terminal, still from the `melloa` repository:

```bash
npm --prefix apps/web run build
MELLOA_CORE_URL=http://127.0.0.1:8000 \
MELLOA_WEB_PORT=8787 \
npm --prefix apps/web start
```

Open exactly:

```text
http://127.0.0.1:8787
```

Do not browse directly to port `8000`: the console server keeps browser/API traffic same-origin and proxies only `/api/` and `/health/`. Both servers bind loopback by default. The CLI rejects public or unspecified bind addresses.

## 7. Log in and use the conversation loop

1. Paste the value printed from `$MELLOA_MVP_STATE/owner-credential` into **Owner credential**.
2. Select **Open Owner Console**. The first authenticated screen is **Conversation**.
3. Select the plus button beside **Conversations** and create a thread. For the default no-network path, select **Fill a no-network tour message**, review or edit the text it places in the composer, then select **Send message**. The other starters are labelled **Eligible model required** because the fixed fixture cannot answer planning, decision, or memory questions. Every starter only fills and focuses the composer; none sends automatically. The browser keeps each draft and retry idempotency key in page memory scoped to the selected canonical thread, so switching threads cannot send another thread's prepared text.
4. Verify the output is labelled **Guided tour fixture** and **Fixed fixture · no network**, not Melli. It must say that the fixed response did not interpret your message. Select its separate **Why this response?** action to open the evidence inspector; the response body itself is intentionally not an action.
5. Verify route ID, provider, model, processing location, disclosure state, latency, available usage/cost metadata, evidence, decision record, and every route attempt. Codex turns explicitly say **Unreported** for tokens and cost.
6. Open **Providers**. A healthy Ollama setup shows **Local Qwen via Ollama** with its privacy scope, provider-retention policy, modality, quality profile, token ceilings, and reliability. A configured Codex route is labelled **Experimental Codex CLI**, **External disclosure**, **Read-only sandbox**, **Ephemeral session**, **Approval policy: never**, and **No Melloa authority** with the same route constraints. **Deterministic synthetic fixture** remains explicitly marked as not being a real intelligence route.
7. Open **Timeline** to inspect newest-first canonical records without message text or model output. When the selected window contains more records than the response bound, the summary shows both the matching count and how many newest records are displayed, and **Limits** includes **Newest Events Only**. Then open **Activity** to inspect the model run ledger and **Operations** to see the exact persistence boundary. The default shows process-memory queue/storage degradation. PostgreSQL mode shows healthy durable queue/canonical and Telegram control storage, a live database component, degraded remaining process-local state, and disabled backup rather than a false all-durable claim.
8. Open **Memory**, paste the printed seed assertion ID, and inspect its value and append-only state history. Corrections and content deletion require the recent in-memory mutation proof established at login. Select **Delete content**, confirm, and verify the assertion value is gone while metadata, state history, tombstone ID, rebuild work ID, and the reported backup-expiry state remain visible. In the default fixture that state is **Not Configured**. In PostgreSQL mode, the deletion tombstone and rebuild work are durable across restart, but this is still not a backup-erasure claim.
9. Open **Settings → Owner session**. Verify this browser and every other active credential-bound session are listed without opaque tokens or digests. With a second browser signed in, select **Sign out other sessions**, confirm the recent-authenticated action, and verify only this browser remains. If recent authentication lapses while the modal is open, the destructive action stays disabled until the owner unlocks changes again.
10. Open **Settings → Telegram**. The card must say either **Synthetic fixture** with no network, or **Bot API** with live polling, reply, delivery, attachment, and ambiguous-retry status. It never displays the token or full Telegram identifiers. Pairing confirmation and revocation also re-check the live browser mutation proof at submit time.

### Verify PostgreSQL restart durability

This check applies only when `database_args` contains `--database-dsn-file`:

1. Create a conversation, send one message, inspect its turn, correct the seed assertion, and optionally submit a synthetic delivery. If Telegram is enabled, pair once, send one disposable text, and note the masked pairing ID plus poll revision in **Settings → Telegram**.
2. Stop only the core with `Ctrl-C`. Leave PostgreSQL running. The web console should report the private core unavailable; it must not fabricate cached state.
3. Rerun the exact `uv run melloa serve-mvp ...` command from step 5 with the same `database_args` and owner credential file.
4. Reload the Owner Console. The unexpired PostgreSQL-backed cookie remains read-capable. Select **Unlock changes** and enter the owner credential to restore the page-memory CSRF proof before mutations; **Settings → Owner session** must still list this browser.
5. Verify the conversation, both messages, turn/model/retrieval inspection, Timeline records, Activity entry, memory correction version/history, and completed delivery still exist. Reusing the original message idempotency key through an API retry must resolve the same turn rather than invoke a second model run.
6. If Telegram was paired, open **Settings → Telegram** and verify the same masked pairing remains active, **Channel state** says **PostgreSQL restart-safe**, and the poll revision did not regress. Send the next disposable text without another `/start`; its reply must use the same pairing.
7. Open **Operations** and verify `Database Postgresql Mvp`, `Queue Postgresql Durable`, and `Storage Postgresql Canonical` are healthy; `Storage Process Local Control State` remains degraded only for the explicitly reported session/provider/challenge/attachment boundaries, and `Backup Not Configured` remains disabled.

If canonical records disappear, stop using the preview and check that the restart command still contains the same core DSN file. Run `make recovery` before relying on the mechanism, and do not treat a real installation as protected until its own destinations, schedule, key custody, and clean-host restore cadence are configured.

## 8. Export and validate owner data

The current MVP includes a canonical export preview for owner data portability and import dry-run validation. It writes JSONL records plus copied JSON Schemas, a manifest, and SHA-256 checksums, then validates checksums, schema readability, and basic referential integrity. Delivery rows preserve redacted exact-authority work status, attempts, resumptions, and receipt identifiers without message text. Retention rows preserve owner-visible policy, aggregate inventory, and backup-expiry disclosure without retained object content. Model-activity rows preserve route, token, cost, timing, and external-disclosure evidence without prompts or raw model output. Memory inspection rows include deleted-content tombstone and rebuild-work evidence instead of dropping the accountability record.

For the running MVP, open **Operations → Export**, inspect the readiness summary and explicit gaps, select **Unlock changes** if the console is read-only, and choose **Download current ZIP**. The private core requires the session-bound CSRF proof and live recent authentication, reads the current runtime stores, validates the complete bundle before responding, appends content-free generation audit evidence, serves it as an attachment, and removes its temporary server-side files after the response. The downloaded filename starts with `melloa-owner-export-` and ends in `.zip`. After the response, **Timeline → Audit** shows the owner-export audit projection with only the export ID, source event ID, aggregate counts, and format/encryption flags. Unzip the download into an empty directory before running `melloa import-validate --bundle-dir <unzipped-export-dir>`.

Use the browser download before stopping the default process-local core: another process cannot recover that volatile state. The CLI path below is still useful for headless operation and for the explicitly configured PostgreSQL stores, but a newly started CLI process sees a newly composed in-memory fixture rather than another process's conversations.

For the CLI path, keep using the disposable state directory and run:

```bash
export MELLOA_MVP_EXPORT_DIR="$MELLOA_MVP_STATE/export-$(date -u +%Y%m%dT%H%M%SZ)"
uv run melloa export-mvp \
  --status "$MELLOA_MVP_STATE/guardian-status.json" \
  --public-key "$MELLOA_MVP_STATE/guardian-public.pem" \
  --owner-credential-file "$MELLOA_MVP_STATE/owner-credential" \
  "${database_args[@]}" \
  --output-dir "$MELLOA_MVP_EXPORT_DIR"

uv run melloa import-validate \
  --bundle-dir "$MELLOA_MVP_EXPORT_DIR"

python3 -c 'import secrets; print(secrets.token_urlsafe(48))' \
  > "$MELLOA_MVP_STATE/export-passphrase"
chmod 0600 "$MELLOA_MVP_STATE/export-passphrase"
uv run melloa export-encrypt \
  --bundle-dir "$MELLOA_MVP_EXPORT_DIR" \
  --passphrase-file "$MELLOA_MVP_STATE/export-passphrase" \
  --output-file "$MELLOA_MVP_EXPORT_DIR.melloaenc"

uv run melloa export-decrypt-validate \
  --package-file "$MELLOA_MVP_EXPORT_DIR.melloaenc" \
  --passphrase-file "$MELLOA_MVP_STATE/export-passphrase"
```

The first command verifies the signed Guardian projection, reads the mode-`0600` owner credential file without printing it, exports a newly composed process-local fixture or the configured PostgreSQL MVP stores, and refuses to write into a non-empty target directory. It does not attach to another running process's in-memory stores. Delivery status is exported in `conversations/deliveries.jsonl`, retention disclosure is exported in `inspection/retention.jsonl`, and model activity is exported in `inspection/model-activity.jsonl`. Deleted assertion values remain absent, but their content-free tombstones remain present in `assertions/inspections.jsonl`. The second command is validation-only; it does not mutate a database or import records yet.

The encrypted package commands keep the passphrase in a mode-`0600` file rather than an argument or environment variable. `export-encrypt` validates the bundle first, wraps it as a ZIP, then encrypts that ZIP with AES-256-GCM using a Scrypt-derived key. `export-decrypt-validate` authenticates and decrypts the package into a temporary directory, reruns the canonical bundle validation, and removes the temporary plaintext. The clear package header contains only package metadata such as the inner export ID, KDF/cipher parameters, and payload hash/size; it does not include owner IDs, credentials, message text, assertion values, prompts, or model output. The live browser preview's event/audit evidence records the generated export ID, format/version, coverage counts, limitations, and encryption/blob/SQL flags, but not bundle contents, file paths, archive paths, content hashes, credentials, cookies, CSRF proofs, prompts, model output, assertion values, or message text. The authenticated Owner Console Operations export panel exposes the same package and validation commands as typed readiness data while continuing to label the live browser ZIP and inner bundle as plaintext.

Expected bundle files include:

```text
manifest.json
checksums.sha256
schemas/owner-export/manifest-v1.json
schemas/owner-export/validation-report-v1.json
schemas/conversation/thread-v1.json
schemas/conversation/message-v1.json
schemas/conversation/turn-v1.json
schemas/conversation/turn-inspection-v1.json
schemas/conversation/processing-status-v1.json
schemas/inspection/owner-model-activity-v1.json
schemas/retention/owner-report-v1.json
schemas/memory/inspection-v1.json
conversations/threads.jsonl
conversations/messages.jsonl
conversations/turns.jsonl
conversations/turn-inspections.jsonl
conversations/processing.jsonl
conversations/deliveries.jsonl
inspection/model-activity.jsonl
inspection/retention.jsonl
assertions/inspections.jsonl
```

The export directory is still not itself encrypted, a logical SQL snapshot, blob export, signed archive, restore executor, or production backup. `manifest.json` states `encrypted: false`, `includes_sql_snapshot: false`, and `includes_blobs: false`; those limitations are deliberate because portability and database recovery are separate contracts. The `.melloaenc` wrapper protects the validated bundle while it is moved or stored, but it does not add missing SQL/blob content or prove clean restore. Use `make recovery` for the PostgreSQL recovery proof, and do not place personal data in the plaintext preview export directory unless the target directory is protected by the owner.

### Expected route outcomes

| Condition | Reply route | What the inspector shows |
|---|---|---|
| Ollama and `qwen3:4b-instruct-2507-q4_K_M` are healthy and return the required JSON object | `model.local.ollama-qwen` | provider `provider.ollama-local`, model `qwen3:4b-instruct-2507-q4_K_M`, location `Device`, `Local`, no external disclosure, zero configured cost, token counts when supplied |
| Ollama is unavailable, Codex is configured and healthy, and Guardian is `normal` | `model.codex.subscription` | failed local attempt followed by provider `provider.openai-codex-subscription`, location `Approved provider`, recorded external disclosure, and unreported token/subscription-cost metadata |
| Codex is configured while Guardian is `offline` or `no-actions` | next eligible device route | the approved-provider route is policy-ineligible and receives no prompt; no Codex attempt or disclosure is recorded |
| Every configured eligible route is absent, times out, or returns invalid output | `model.fake.deterministic` | unsuccessful configured attempts followed by the deterministic device route; reply text begins **Synthetic local reply** |
| Both route-config arrays are empty | `model.fake.deterministic` | only the clearly labelled synthetic fixture is available |

## 9. Pair and use Telegram

This section applies only when the real Bot API argument and Guardian `normal` mode are active.

1. Open a private chat with the disposable bot and send exactly `/start`.
2. The bot returns a 32-character pairing code in that private chat. This code is short-lived, candidate-bound, deterministically derived from the configured bot credential for crash replay, and retained only as a hash by pairing state.
3. In the Owner Console, open **Settings → Telegram**, select the masked pending candidate, and enter the code. Confirmation requires the authenticated owner session, CSRF proof, and recent authentication.
4. Send an ordinary text message to the bot. Melloa verifies the exact paired user and private chat, records the immutable normalized update and offset, appends one owner-authored canonical message, invokes the same provider-neutral model gateway, and sends Melli's direct text reply through the deterministic delivery policy path.
5. Open the **Telegram owner conversation** in the Owner Console. Inspect the reply's model route, attempts, disclosure, evidence, tokens, cost, and decision record. The conversation is canonical history; Telegram is only its source/delivery adapter.
6. Open the conversation's delivery state or **Settings → Telegram**. The delivery resource names the immutable pairing record rather than exposing a raw chat ID, and the execution receipt binds the exact message hash, action hash, policy decision, attempt, and Telegram message receipt.

Text is the only usable content in this slice. Attachment references, locations, and other unsupported message content are recorded and rejected before any file fetch. A caption may still become canonical text while its attachment metadata is rejected.

## Expected visual states

These checked-in references are generated from the same loopback MVP and contain no credential or private data.

| State | Reference | Verify |
|---|---|---|
| Desktop login | [login desktop](assets/current-mvp/login-desktop.png) | calm private-access screen, application-authentication copy, independent Guardian boundary |
| Desktop conversation starters | [conversation starters desktop](assets/current-mvp/conversation-starters-desktop.png) | empty private thread separates the no-network guided tour from real-job starters that require an eligible model; every action only fills the composer |
| Mobile conversation starters | [conversation starters mobile](assets/current-mvp/conversation-starters-mobile.png) | the no-network tour action is visible above the fixed composer, while model-required starters remain reachable without horizontal overflow or bottom-navigation overlap |
| Desktop conversation | [conversation desktop](assets/current-mvp/conversation-desktop.png) | fixed output is attributed to the guided-tour fixture rather than Melli, with a separate **Why this response?** action for route, disclosure, evidence, policy, cost, and durable IDs |
| Desktop activity | [activity desktop](assets/current-mvp/activity-desktop.png) | owner-readable model ledger with run totals, local/external filters, no-disclosure local route state, and route/turn actions |
| Mobile activity | [activity mobile](assets/current-mvp/activity-mobile.png) | readable model-run ledger, disclosure filter state, run identifiers, and footer boundary without bottom-navigation overlap |
| Desktop timeline | [timeline desktop](assets/current-mvp/timeline-desktop.png) | chronological content-free conversation, processing, delivery, model, and owner-export audit records with filter and aggregate-count disclosure |
| Mobile timeline | [timeline mobile](assets/current-mvp/timeline-mobile.png) | timeline filters and newest content-free rows remain readable without horizontal overflow or bottom-navigation overlap |
| Desktop timeline audit | [timeline audit desktop](assets/current-mvp/timeline-audit-desktop.png) | owner-export audit projection shows export ID, source event ID, aggregate counts, encryption/blob/SQL flags, and status without raw audit payloads |
| Mobile timeline audit | [timeline audit mobile](assets/current-mvp/timeline-audit-mobile.png) | audit filter and owner-export audit row remain inspectable on narrow screens without exposing bundle paths, content hashes, prompt text, or message content |
| Desktop memory | [memory desktop](assets/current-mvp/memory-desktop.png) | seed assertion lookup with value, status, provenance, metadata, state history, and owner mutation affordances |
| Mobile memory | [memory mobile](assets/current-mvp/memory-mobile.png) | memory lookup and the seed assertion record collapse into a readable owner-authenticated inspection view |
| Desktop providers | [providers desktop](assets/current-mvp/providers-desktop.png) | route health and ordering, privacy/retention constraints, local/external disclosure labels, bounded experimental Codex guidance, explicit synthetic fixture label |
| Mobile providers | [providers mobile](assets/current-mvp/providers-mobile.png) | responsive navigation and readable provider, privacy/retention constraints, sandbox, disclosure, and fallback guidance without horizontal overflow |
| Desktop operations export | [operations export desktop](assets/current-mvp/operations-export-desktop.png) | owner attention summary plus canonical export preview readiness, validation status, live ZIP download, encrypted-package commands, and explicit missing SQL/blob/signed-archive gaps |
| Mobile operations export | [operations export mobile](assets/current-mvp/operations-export-mobile.png) | export format, validation, package readiness, command guidance, and deliberate limitations remain readable on narrow screens |
| Mobile operations export download | [operations export download mobile](assets/current-mvp/operations-export-download-mobile.png) | live ZIP download command remains reachable after transient validation feedback clears |
| Desktop operations retention | [operations retention desktop](assets/current-mvp/operations-retention-desktop.png) | owner attention summary, aggregate retention inventory, and backup-expiry disclosure for current canonical stores without content exposure |
| Mobile operations retention | [operations retention mobile](assets/current-mvp/operations-retention-mobile.png) | retention inventory cards and backup-expiry status remain readable on narrow screens |
| Desktop Telegram settings | [settings desktop](assets/current-mvp/settings-desktop.png) | owner and Guardian boundaries, explicit transport mode, polling/reply/delivery status, no credential or full identifier |
| Mobile Telegram settings | [settings mobile](assets/current-mvp/settings-mobile.png) | responsive channel status, pairing empty state, and readable authority copy without horizontal overflow |

Screenshot generation is an inspection aid, not an acceptance substitute. Run the interaction yourself and confirm that loading, empty, error, and retry states remain readable at your browser size.

## Troubleshooting

### Owner credential path rejected

The path must be a regular file, 32–4096 characters after trimming, and inaccessible to group or other users:

```bash
chmod 0600 "$MELLOA_MVP_STATE/owner-credential"
stat "$MELLOA_MVP_STATE/owner-credential"
```

### Guardian verification or readiness fails

- Use the status and public key from the same disposable initialization.
- Keep both as regular files; symlinks and oversized files fail closed.
- Run `uv run melloa guardian-status ...` before starting the core.
- `stopped` and `recovery` intentionally return readiness `503` and deny conversation writes. Repeat the disposable setup instead of editing signed JSON.

### Login succeeds, then authenticated views fail

- Use `http://127.0.0.1:8787`, not port `8000` and not a different hostname.
- Confirm the web terminal uses `MELLOA_CORE_URL=http://127.0.0.1:8000`.
- Restarting the core invalidates process-local sessions; reload and log in again.
- A restored read session has no browser-held CSRF proof. Select **Unlock changes** and re-enter the owner credential.

### Owner Console reports `Private core unavailable`

Confirm the core is still listening and that its liveness path responds:

```bash
curl -v http://127.0.0.1:8000/health/live
```

The production console server returns a redacted `502` instead of exposing proxy internals.

### Ollama route is unavailable

```bash
ollama list
curl -v http://127.0.0.1:11434/v1/models
```

The configured model name must match `qwen3:4b-instruct-2507-q4_K_M`. **Providers** reports `Unavailable` with a redacted reason. Conversation remains usable through the visibly synthetic fallback; it never silently claims the fallback was Qwen.

### Qwen repeatedly falls back despite healthy route status

Health checks prove that `/v1/models` returns a bounded OpenAI-compatible model list containing the exact configured `qwen3:4b-instruct-2507-q4_K_M` ID. A conversation can still fail because of timeout, response size, completion HTTP status, or invalid strict JSON. Select the synthetic reply and inspect **Route attempts**. Melloa sends a bounded system prompt requiring exactly `{ "text": "...", "citation_ids": [] }` and rejects invented citation IDs downstream.

### Codex CLI route is unavailable

Verify the exact isolated executable and authentication context used to generate the route config:

```bash
"$MELLOA_CODEX_EXECUTABLE" --version
CODEX_HOME="$MELLOA_CODEX_HOME" "$MELLOA_CODEX_EXECUTABLE" login status
ls -ld "$MELLOA_CODEX_HOME" "$MELLOA_CODEX_WORK"
```

Both directories must exist with mode `0700`. The resolved executable must be a regular executable file, and neither it nor its containing directory may be writable by group or others. Every configured path must be absolute. **Providers** reports only a redacted unavailable reason; child stderr, authentication content, executable/home paths, and prompt text are not returned by the API.

If health is green but a turn falls back, inspect **Route attempts**. Guardian must be `normal`, the thread sensitivity must be allowed by the config, the selected model must be available to the isolated subscription, and Codex must produce the strict response object before the shorter of the route and turn deadlines. A healthy earlier local route wins by configured fallback order. `offline` and `no-actions` intentionally restrict conversation to device routes and do not disclose the prompt to Codex.

### Telegram candidate does not appear

- Confirm the core startup record says `telegram.configured: true` and **Settings → Telegram** says **Bot API** rather than **Synthetic fixture**.
- Confirm Guardian is `normal`. `offline`, `read-only`, `stopped`, and `recovery` suspend polling; `no-actions` allows intake but refuses challenge publication and confirmation. Do not edit the signed projection to work around the mode.
- Send `/start` in a private one-to-one chat. Do not add the bot to a group.
- Check the Telegram card's redacted polling reason. Authentication, HTTP, response-size, and schema errors never include the token-bearing Bot API URL.
- Confirm the token file is a regular file with exact mode `0600`. Stop the core before replacing it.

### Telegram reply is pending or dead

- Guardian `no-actions` permits canonical ingestion and reasoning but deterministic policy denies outbound communication. Returning independently to `normal` allows an in-process pending reply to be submitted.
- Connection failures and explicit rate limits use bounded retry work. A timeout or upstream response that could have sent the message is marked `telegram.delivery.outcome_unknown` and is not retried automatically, avoiding a silent duplicate.
- Replies longer than 4096 characters, non-text replies, revoked pairings, and sensitivity above `personal` fail closed and remain inspectable.
- Without PostgreSQL, pairing, offsets, successful-send deduplication, and pending dispatch are process-local. With PostgreSQL, pairing authority, normalized receipts, offsets, and unsent reply reconstruction survive restart; challenge publication and an interrupted external send still have no transactional outcome proof.

### Telegram token may be exposed

Stop the core, revoke the token through BotFather, replace the owner-only token file, and restart. Treat the old pairing as compromised: revoke its durable authority in the Owner Console and pair again before resuming Telegram. Never paste a token into an issue, log, URL, command argument, browser field, or repository file.

### PostgreSQL mode is rejected or unavailable

- Confirm both migration commands completed before starting the core and report no pending version. The runtime never applies migrations with its core-role DSN and never silently falls back to memory after database configuration fails.
- Confirm the core DSN file is a regular non-symlink file with mode `0600`. Keep credentials in that file only; do not paste the DSN into a command, issue, or log.
- Use an absolute Unix-socket path, `localhost`, or a loopback/private literal IP. Public targets, unspecified addresses, DNS hostnames, multiple opaque service definitions, and public fallback are intentionally rejected.
- Check `docker ps`, `docker logs "$MELLOA_MVP_POSTGRES_CONTAINER"`, and `docker exec "$MELLOA_MVP_POSTGRES_CONTAINER" pg_isready -U postgres -d melloa`. A missing pinned image must be fetched or preloaded by digest; do not substitute an unreviewed tag.
- If startup reports incompatible canonical bootstrap state, preserve the database for inspection rather than deleting or editing rows. The fixed owner, Melli, seed assertion, and Telegram thread identities fail closed on conflicting immutable data.

### Port already in use

Choose unused loopback ports and keep the proxy target aligned:

```bash
uv run melloa serve-mvp ... --port 8010
MELLOA_CORE_URL=http://127.0.0.1:8010 MELLOA_WEB_PORT=8790 npm --prefix apps/web start
```

Never work around a collision by binding `0.0.0.0` or a public address.

## Current limitations

- The default path remains entirely in memory and is discarded on core restart. PostgreSQL is explicit and optional, never an implicit dependency or fallback.
- PostgreSQL mode durably backs hashed owner sessions and append-only revocations with bounded expired-row cleanup, canonical conversation and model provenance, memory correction/deletion evidence, aggregate retention inventory, assembled audit records, reply/delivery work, Telegram pairing authority, normalized updates/receipts, poll offsets, and pre-submission reply reconstruction. Provider health, Telegram challenge-send observation, attachment bytes, backup, and all unlisted mutation/audit categories remain process-local, synthetic, unassembled, unstored, or unconfigured as reported.
- Content-free audit coverage currently includes authentication/security denials, owner-session lifecycle, canonical owner-message acceptance/resume, outbound-delivery enqueue/resume, owner memory mutations, Telegram pairing lifecycle, and owner export preview generation. PostgreSQL session issue/revoke couples source and audit in one transaction; process-local authentication appends audit before session mutation. Conversation, delivery, memory, pairing, and export still append audit after a separate source-store call. An audit failure can therefore follow a committed mutation; idempotent conversation and delivery retries recover evidence without repeating model execution or external send, but comprehensive action auditing and broader cross-store atomicity remain pending.
- Audit evidence uses internal IDs, bounded status/count/decision metadata, and content-free reason codes. It excludes credentials, tokens, Telegram user/chat IDs, confirmation codes, source addresses, user agents, message text, destinations, idempotency keys, prompts, citations/evidence content, raw model output, external-disclosure payloads, assertion values, bundle contents, file/blob paths, content hashes, and action hashes.
- Timeline is a bounded current-MVP view over canonical conversation, reply processing, outbound delivery, model activity, and owner-export audit projections. It is neither a complete life timeline nor a raw security-audit browser; auth/security audit records remain outside that view.
- Retention inventory is aggregate-only. Owner delivery reports work/attempt/resumption counts without content; Telegram quarantine reports aggregate objects/bytes/deletion receipts; audit inventory reports only record counts and bytes. Assertion content deletion removes the retained canonical value and leaves content-free evidence, but does not claim immediate physical erasure from backups or external copies.
- The deterministic synthetic route is always present as a test and recovery fallback.
- Local/private OpenAI-compatible HTTP routes and one experimental subscription-backed Codex CLI route are implemented behind the same gateway. Claude Code and ACP routes remain future explicitly configured gateway kinds.
- The Codex route is an ephemeral read-only CLI invocation, not a production host-isolation boundary. It uses only its dedicated `CODEX_HOME` authentication, receives no Melloa/Guardian/policy/capability authority, and is eligible only in Guardian `normal`; nevertheless the executable runs as the current OS user and must not be trusted with a personal-data host.
- Codex token usage is unavailable through this integration. Its subscription fee is not represented as per-call cost, and a recorded `0.0` must not be interpreted as zero underlying usage or a free subscription.
- Direct paid APIs are not configured by default. Approved-provider routes require explicit HTTPS configuration, a mode-`0600` token file when needed, cost metadata, sensitivity constraints, and visible external disclosure.
- Telegram Bot API long polling, private owner pairing, canonical text ingestion, model routing, and policy-bound replies are available only when explicitly configured. PostgreSQL mode preserves pairing authority, offsets, ingestion provenance, canonical messages, unsent reply reconstruction, and submitted delivery work, so an ordinary core restart does not require re-pairing. Attachments are rejected before fetch; challenge-send and ambiguous outbound-send outcomes are not automatically retried as if success were known.
- Capture is disabled, media content is never served, backup is unconfigured, and owner-conversation, owner-memory, owner-delivery, Telegram-quarantine, and audit-store retention inventory is backed only by canonical stores, the delivery store, the configured quarantine backend, or the configured append store.
- The local HTTP console is a loopback development surface. A private-network deployment must terminate HTTPS on the same origin and preserve the secure `__Host-` session cookie; do not weaken cookie security or enable CORS.

## GitHub automation and repository settings

The public CI workflow performs Python tests/lint/typecheck, schema and manifest checks, the web test/typecheck/build, strict docs validation, PostgreSQL integration, encrypted restore validation, and an authenticated Playwright smoke journey. Pull requests and `main` pushes receive a `current-mvp-screenshots` artifact containing the desktop and mobile states from a fresh process-local fixture.

No repository or environment secret is required for the current MVP, visual smoke, or documentation deployment. The workflow checks out the public Guardian repository independently and generates only disposable CI credentials under `runner.temp`.

For GitHub Pages:

1. Open **Settings → Pages** in the GitHub repository.
2. Set **Build and deployment → Source** to **GitHub Actions**.
3. Keep the workflow's scoped `pages: write` and `id-token: write` permissions; do not add a long-lived Pages token.
4. Allow the automatically created `github-pages` environment to deploy from `main`. If environment reviewers are added, deployments wait for that explicit review.

After the main `verify` and `visual-smoke` jobs pass, `publish-docs` rebuilds MkDocs with `--strict`, uploads the generated `site` directory, and deploys it through GitHub's OIDC-backed Pages actions. Pull requests never deploy Pages.

## Stop and clean up

Stop the web, core, and optional Ollama foreground processes with `Ctrl-C`. If PostgreSQL was enabled, remove its disposable container and named volume before deleting the credential directory:

```bash
if [[ -n "${MELLOA_MVP_POSTGRES_CONTAINER:-}" ]]; then
  docker rm --force "$MELLOA_MVP_POSTGRES_CONTAINER"
  docker volume rm "$MELLOA_MVP_POSTGRES_VOLUME"
fi
printf 'Removing disposable state: %s\n' "$MELLOA_MVP_STATE"
rm -rf -- "$MELLOA_MVP_STATE"
```

This cleanup removes the disposable database, Guardian private key, owner credential, database credentials, and isolated Codex authentication copy when configured. Use the provider account's current session controls if revocation is required. Local cleanup is not a substitute for provider-side retention, canonical deletion, export, or backup-expiry behavior in a real deployment.
