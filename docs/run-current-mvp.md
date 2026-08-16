# Run the current MVP

This is the one canonical path for running the current owner-facing Melloa MVP. It starts an independently built disposable Guardian fixture, the Melloa core with process-local stores by default or optional PostgreSQL restart durability, one optional real local Qwen route through Ollama, one optional experimental subscription-backed Codex CLI route, an optional real Telegram Bot API channel, and the same-origin Owner Console.

The result is a usable loop:

> owner login → canonical conversation → provider-neutral model route → Melli reply → route, disclosure, latency, token, cost, evidence, and decision inspection

With Telegram explicitly enabled, the same canonical loop also supports:

> private `/start` → Owner Console confirmation → Telegram text → canonical conversation → model route → exact policy-authorized reply to the same pairing

!!! warning "Local preview, not a personal-data deployment"
    The default path is entirely process-local. The optional PostgreSQL path preserves canonical conversations, turn/model provenance, memory corrections, reply/delivery work, Telegram pairing authority, normalized intake receipts, poll offsets, and pre-submission reply recovery across a core restart. Authentication sessions, provider health observations, Telegram challenge-send observation, attachment quarantine bytes, audit retention inventory, and backup remain preview-grade, ephemeral, or unavailable. Owner-conversation, owner-memory, and Telegram-quarantine retention inventory are aggregate-only and backed by canonical stores or the configured quarantine backend; unavailable audit inventory is shown as not measured rather than a zero count. This is not a backup-erasure claim. A deterministic synthetic route remains enabled as a visibly labelled fallback. Do not use personal, sensitive, or production data.

## Prerequisites

- Linux or macOS with Bash;
- Python 3.13 or newer;
- [uv](https://docs.astral.sh/uv/) 0.12.0;
- Node.js 22 or newer and npm;
- Go 1.24 or newer for the separate Guardian fixture;
- optionally [Ollama](https://ollama.com/) for the recommended real local-model path;
- optionally the [OpenAI Codex CLI](https://developers.openai.com/codex/cli/) and an eligible subscription for the experimental external route;
- optionally Docker and the repository's digest-pinned PostgreSQL 18 plus pgvector image for the restart-durability path.

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

## 3. Start local Qwen through Ollama

This is the recommended route because it requires no per-token billing and makes no external disclosure. Install Ollama using its upstream instructions, then pull the model:

```bash
ollama pull qwen3:4b
```

If Ollama is not already running as a service, keep it running in another terminal:

```bash
ollama serve
```

Verify its OpenAI-compatible endpoint:

```bash
curl -fsS http://127.0.0.1:11434/v1/models >/dev/null \
  && echo "Ollama OpenAI-compatible endpoint is ready"
```

The reviewed example route is `config/routes/ollama-qwen.example.json`. It declares device-only processing, zero configured cost, no-training retention, bounded timeouts, and the `qwen3:4b` model. The file contains no credential. Select it for the later core command:

```bash
model_args=(
  --model-route-config config/routes/ollama-qwen.example.json
)
```

!!! tip "Synthetic-only smoke path"
    Ollama is optional. Run `model_args=()` instead to omit the local route. If the configured endpoint later becomes unavailable or returns invalid structured output, routing fails visibly and falls back to the next explicitly ordered route, then to the labelled synthetic route.

### Alternative: experimental subscription-backed Codex CLI

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

### Optional: enable PostgreSQL restart durability

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

Both migration commands must report every committed version under `applied` and an empty `pending` list. Never pass either DSN as a command argument, reuse the migration DSN for the core, expose the container publicly, or treat PostgreSQL persistence as a backup. The core opens separate serialized connections for conversation, memory, delivery, and Telegram stores and redacts connection failures.

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

This sample shows Ollama, Codex, and Telegram enabled while `database_args=()`. With `codex_args=()`, `external_disclosure_routes` and the CLI-agent `route_ids` are empty, `experimental_cli_agent.configured` is `false`, and the Codex route is absent from both route-order arrays. With `telegram_args=()`, `telegram.configured` is `false` and `telegram.adapter_id` is `null`. With PostgreSQL enabled, `persistence.mode` becomes `postgresql-partial-preview`, `durable_state` adds canonical conversation/model provenance, memory correction history, reply/delivery work, and Telegram pairing/intake/offset/dispatch state. `ephemeral_state` still lists sessions, challenge-send observation, attachment quarantine bytes, and provider health. Telegram `delivery_records` and `pairing_offsets_ingestion` become `postgresql`; challenge-send observation remains process-only and attachment bytes remain unstored. The deterministic model fallback remains enabled in every case. The startup record contains route IDs and fixed boundaries, never DSNs, database errors, Codex executable/home paths, subscription authentication, owner credential, Telegram token, or message content.

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
3. Select the plus button beside **Conversations**, create a thread, and send a message.
4. Select Melli's reply to open **Turn details**.
5. Verify route ID, provider, model, processing location, disclosure state, latency, available usage/cost metadata, evidence, decision record, and every route attempt. Codex turns explicitly say **Unreported** for tokens and cost.
6. Open **Providers**. A healthy Ollama setup shows **Local Qwen via Ollama**. A configured Codex route is labelled **Experimental Codex CLI**, **External disclosure**, **Read-only sandbox**, **Ephemeral session**, **Approval policy: never**, and **No Melloa authority**. **Deterministic synthetic fixture** remains explicitly marked as not being a real intelligence route.
7. Open **Activity** to inspect the run ledger and **Operations** to see the exact persistence boundary. The default shows process-memory queue/storage degradation. PostgreSQL mode shows healthy durable queue/canonical and Telegram control storage, a live database component, degraded remaining process-local state, and disabled backup rather than a false all-durable claim.
8. Open **Memory**, paste the printed seed assertion ID, and inspect its value and append-only state history. Corrections and content deletion require the recent in-memory mutation proof established at login. Select **Delete content**, confirm, and verify the assertion value is gone while metadata, state history, tombstone ID, rebuild work ID, and the reported backup-expiry state remain visible. In the default fixture that state is **Not Configured**. In PostgreSQL mode, the deletion tombstone and rebuild work are durable across restart, but this is still not a backup-erasure claim.
9. Open **Settings → Telegram**. The card must say either **Synthetic fixture** with no network, or **Bot API** with live polling, reply, delivery, attachment, and ambiguous-retry status. It never displays the token or full Telegram identifiers.

### Verify PostgreSQL restart durability

This check applies only when `database_args` contains `--database-dsn-file`:

1. Create a conversation, send one message, inspect its turn, correct the seed assertion, and optionally submit a synthetic delivery. If Telegram is enabled, pair once, send one disposable text, and note the masked pairing ID plus poll revision in **Settings → Telegram**.
2. Stop only the core with `Ctrl-C`. Leave PostgreSQL running. The web console should report the private core unavailable; it must not fabricate cached state.
3. Rerun the exact `uv run melloa serve-mvp ...` command from step 5 with the same `database_args` and owner credential file.
4. Reload the Owner Console and log in again. The old session is intentionally invalid because sessions remain process-local.
5. Verify the conversation, both messages, turn/model/retrieval inspection, Activity entry, memory correction version/history, and completed delivery still exist. Reusing the original message idempotency key through an API retry must resolve the same turn rather than invoke a second model run.
6. If Telegram was paired, open **Settings → Telegram** and verify the same masked pairing remains active, **Channel state** says **PostgreSQL restart-safe**, and the poll revision did not regress. Send the next disposable text without another `/start`; its reply must use the same pairing.
7. Open **Operations** and verify `Database Postgresql Mvp`, `Queue Postgresql Durable`, and `Storage Postgresql Canonical` are healthy; `Storage Process Local Control State` remains degraded only for the explicitly reported session/provider/challenge/attachment boundaries, and `Backup Not Configured` remains disabled.

If canonical records disappear, stop using the preview and check that the restart command still contains the same core DSN file. PostgreSQL durability without a tested backup does not satisfy recovery.

## 8. Export and validate owner data

The current MVP includes an offline canonical export preview for owner data portability and import dry-run validation. It writes JSONL records plus copied JSON Schemas, a manifest, and SHA-256 checksums, then validates checksums, schema readability, and basic referential integrity. Model-activity rows preserve route, token, cost, timing, and external-disclosure evidence without prompts or raw model output. Memory inspection rows include deleted-content tombstone and rebuild-work evidence instead of dropping the accountability record. Before running the CLI command, open **Operations → Export** to inspect estimated record counts, covered record groups, dry-run validation checks, and explicit gaps through the authenticated Owner Console. The validation scope card should show checksum, schema, and reference checks as implemented while leaving database restore execution pending.

Keep using the disposable state directory and run:

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
```

The first command verifies the signed Guardian projection, reads the mode-`0600` owner credential file without printing it, exports the process-local preview state or the configured PostgreSQL MVP stores, and refuses to write into a non-empty target directory. Model activity is exported in `inspection/model-activity.jsonl`. Deleted assertion values remain absent, but their content-free tombstones remain present in `assertions/inspections.jsonl`. The second command is validation-only; it does not mutate a database or import records yet.

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
schemas/memory/inspection-v1.json
conversations/threads.jsonl
conversations/messages.jsonl
conversations/turns.jsonl
conversations/turn-inspections.jsonl
conversations/processing.jsonl
inspection/model-activity.jsonl
assertions/inspections.jsonl
```

This is not encrypted packaging, a logical SQL snapshot, blob export, or production backup. `manifest.json` states `encrypted: false`, `includes_sql_snapshot: false`, and `includes_blobs: false`; those limitations are deliberate until the full backup/export milestone lands. Do not place personal data in this preview export unless the target directory is protected by the owner.

### Expected route outcomes

| Condition | Reply route | What the inspector shows |
|---|---|---|
| Ollama and `qwen3:4b` are healthy and return the required JSON object | `model.local.ollama-qwen` | provider `provider.ollama-local`, model `qwen3:4b`, location `Device`, `Local`, no external disclosure, zero configured cost, token counts when supplied |
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
| Desktop conversation | [conversation desktop](assets/current-mvp/conversation-desktop.png) | conversation-first layout, compact authority bar, route/provenance inspector, visible synthetic fallback when Ollama is absent |
| Desktop providers | [providers desktop](assets/current-mvp/providers-desktop.png) | route health and ordering, local/external disclosure labels, bounded experimental Codex guidance, explicit synthetic fixture label |
| Mobile providers | [providers mobile](assets/current-mvp/providers-mobile.png) | responsive navigation and readable provider, sandbox, disclosure, and fallback guidance without horizontal overflow |
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

The configured model name must match `qwen3:4b`. **Providers** reports `Unavailable` with a redacted reason. Conversation remains usable through the visibly synthetic fallback; it never silently claims the fallback was Qwen.

### Qwen repeatedly falls back despite healthy route status

Health checks only prove `/v1/models` responds. A conversation can still fail because of timeout, response size, HTTP status, or invalid strict JSON. Select the synthetic reply and inspect **Route attempts**. Melloa sends a bounded system prompt requiring exactly `{ "text": "...", "citation_ids": [] }` and rejects invented citation IDs downstream.

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
- PostgreSQL mode durably backs canonical conversation, retrieval/model provenance, memory correction history, owner assertion-content deletion tombstones/rebuild work, aggregate owner-conversation and owner-memory retention inventory, reply/delivery work, Telegram pairing and revocation authority, normalized updates/receipts, monotonic poll offsets, and pre-submission reply reconstruction. Owner sessions, provider health, Telegram challenge-send observation, attachment quarantine bytes, audit retention inventory, event/audit emission, and backup remain process-local, synthetic, unassembled, unstored, or unconfigured as reported. Telegram-quarantine retention inventory reports aggregate retained objects, retained bytes, deletion receipts, and oldest retained timestamp from the configured attachment backend. Assertion content deletion removes the retained value from the canonical memory table and leaves content-free evidence; it does not claim immediate physical erasure from backups or external copies.
- The deterministic synthetic route is always present as a test and recovery fallback.
- Local/private OpenAI-compatible HTTP routes and one experimental subscription-backed Codex CLI route are implemented behind the same gateway. Claude Code and ACP routes remain future explicitly configured gateway kinds.
- The Codex route is an ephemeral read-only CLI invocation, not a production host-isolation boundary. It uses only its dedicated `CODEX_HOME` authentication, receives no Melloa/Guardian/policy/capability authority, and is eligible only in Guardian `normal`; nevertheless the executable runs as the current OS user and must not be trusted with a personal-data host.
- Codex token usage is unavailable through this integration. Its subscription fee is not represented as per-call cost, and a recorded `0.0` must not be interpreted as zero underlying usage or a free subscription.
- Direct paid APIs are not configured by default. Approved-provider routes require explicit HTTPS configuration, a mode-`0600` token file when needed, cost metadata, sensitivity constraints, and visible external disclosure.
- Telegram Bot API long polling, private owner pairing, canonical text ingestion, model routing, and policy-bound replies are available only when explicitly configured. PostgreSQL mode preserves pairing authority, offsets, ingestion provenance, canonical messages, unsent reply reconstruction, and submitted delivery work, so an ordinary core restart does not require re-pairing. Attachments are rejected before fetch; challenge-send and ambiguous outbound-send outcomes are not automatically retried as if success were known.
- Capture is disabled, media content is never served, backup is unconfigured, and only owner-conversation, owner-memory, and Telegram-quarantine retention inventory is backed by canonical stores or the configured quarantine backend.
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
