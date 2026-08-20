#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d "$ROOT/.server-runtime.XXXXXX")"
readonly PROJECT="melloa-server-test-${RANDOM}-$$"
readonly IMAGE="melloa-local/server-test:${PROJECT}"
readonly ENV_FILE="$WORKDIR/server.env"

detect_build_ca() {
  local candidate
  if [[ -n "${MELLOA_BUILD_CA_FILE:-}" && -f "$MELLOA_BUILD_CA_FILE" ]]; then
    printf '%s' "$MELLOA_BUILD_CA_FILE"
    return 0
  fi
  for candidate in \
    /etc/ssl/certs/ca-certificates.crt \
    /etc/pki/tls/certs/ca-bundle.crt \
    /opt/bb/share/ssl/cert.pem; do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  echo "No host CA bundle was found for the locked image build" >&2
  return 1
}

readonly BUILD_CA_FILE="$(detect_build_ca)"

compose() {
  docker compose \
    --project-directory "$ROOT" \
    --env-file "$ENV_FILE" \
    --file "$ROOT/compose.server.yaml" \
    "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  docker image rm "$IMAGE" >/dev/null 2>&1 || true
  if [[ "$WORKDIR" == "$ROOT"/.server-runtime.* && -d "$WORKDIR" ]]; then
    rm -rf "$WORKDIR"
  fi
}
trap cleanup EXIT

write_private() {
  local path="$1"
  local value="$2"
  install -m 0600 /dev/null "$path"
  printf '%s' "$value" >"$path"
}

wait_for_melloa() {
  local attempt
  local container
  local state
  local health
  for attempt in $(seq 1 120); do
    container="$(compose ps --all --quiet melloa)"
    if [[ -n "$container" ]]; then
      state="$(docker inspect --format '{{.State.Status}}' "$container")"
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")"
      if [[ "$state" == running && "$health" == healthy ]]; then
        printf '%s' "$container"
        return 0
      fi
      if [[ "$state" == exited || "$state" == dead ]]; then
        break
      fi
    fi
    sleep 1
  done
  echo "Melloa server runtime did not become healthy" >&2
  compose ps --all >&2 || true
  compose logs --no-color --tail=120 >&2 || true
  return 1
}

wait_for_restart() {
  local container="$1"
  local previous_count="$2"
  local attempt
  local count
  local health
  for attempt in $(seq 1 120); do
    count="$(docker inspect --format '{{.RestartCount}}' "$container")"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")"
    if ((count > previous_count)) && [[ "$health" == healthy ]]; then
      return 0
    fi
    sleep 1
  done
  echo "Melloa did not restart and recover" >&2
  compose ps --all >&2 || true
  compose logs --no-color --tail=120 melloa postgres >&2 || true
  return 1
}

mkdir -p \
  "$WORKDIR/private/model-credentials" \
  "$WORKDIR/guardian-handoff" \
  "$WORKDIR/runtime-state"
chmod 0700 \
  "$WORKDIR/private" \
  "$WORKDIR/private/model-credentials" \
  "$WORKDIR/guardian-handoff" \
  "$WORKDIR/runtime-state"

readonly ADMIN_PASSWORD="admin_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
readonly APP_PASSWORD="app_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
readonly MIGRATION_PASSWORD="migration_CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"

write_private "$WORKDIR/private/postgres-admin-password" "$ADMIN_PASSWORD"
write_private "$WORKDIR/private/postgres-app-password" "$APP_PASSWORD"
write_private "$WORKDIR/private/postgres-migration-password" "$MIGRATION_PASSWORD"
write_private "$WORKDIR/private/database-application-dsn" \
  "host=172.30.37.2 port=5432 dbname=melloa user=melloa_app password=$APP_PASSWORD"
write_private "$WORKDIR/private/database-migration-dsn" \
  "host=172.30.37.2 port=5432 dbname=melloa user=melloa_migrator password=$MIGRATION_PASSWORD"
write_private "$WORKDIR/private/owner-credential" \
  "server-runtime-owner-credential-00000000000000000001"
write_private "$WORKDIR/private/telegram-bot-token" \
  "123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456"
write_private "$WORKDIR/private/telegram-owner.json" \
  '{"owner_user_id":1234,"owner_chat_id":5678,"poll_timeout_seconds":1}'
write_private "$WORKDIR/private/capable-model.json" \
  '{"display_name":"Server capable test","provider_id":"provider.server-capable-test","model_id":"server-capable-test-v1","base_url":"https://capable.invalid/v1","api_style":"responses","processing_location":"approved_provider","allowed_sensitivities":["public","internal","personal"],"max_input_tokens":4096,"max_output_tokens":512,"estimated_max_cost_gbp":1.0,"input_cost_gbp_per_million_tokens":1.0,"output_cost_gbp_per_million_tokens":1.0,"timeout_ms":5000,"health_timeout_ms":1000}'
write_private "$WORKDIR/private/economy-model.json" \
  '{"display_name":"Server economy test","provider_id":"provider.server-economy-test","model_id":"server-economy-test-v1","base_url":"https://economy.invalid/v1","processing_location":"approved_provider","allowed_sensitivities":["public","internal","personal"],"max_input_tokens":4096,"max_output_tokens":512,"estimated_max_cost_gbp":0.1,"input_cost_gbp_per_million_tokens":0.1,"output_cost_gbp_per_million_tokens":0.1,"timeout_ms":5000,"health_timeout_ms":1000}'

cp "$ROOT/tests/fixtures/guardian/offline-status.json" \
  "$WORKDIR/guardian-handoff/status.json"
cp "$ROOT/tests/fixtures/guardian/public-key.pub" \
  "$WORKDIR/guardian-handoff/public.pem"
chmod 0400 "$WORKDIR/guardian-handoff/status.json" "$WORKDIR/guardian-handoff/public.pem"

install -m 0600 /dev/null "$ENV_FILE"
{
  printf 'MELLOA_COMPOSE_PROJECT_NAME=%s\n' "$PROJECT"
  printf 'MELLOA_IMAGE=%s\n' "$IMAGE"
  printf 'MELLOA_SOURCE_REVISION=server-runtime-test\n'
  printf 'MELLOA_RUNTIME_UID=%s\n' "$(id -u)"
  printf 'MELLOA_RUNTIME_GID=%s\n' "$(id -g)"
  printf 'MELLOA_STATE_SUBNET=172.30.37.0/28\n'
  printf 'MELLOA_DATABASE_ADDRESS=172.30.37.2\n'
  printf 'MELLOA_EGRESS_INTERNAL=true\n'
  printf 'MELLOA_BUILD_CA_FILE=%s\n' "$BUILD_CA_FILE"
  printf 'MELLOA_POSTGRES_ADMIN_PASSWORD_FILE=%s\n' \
    "$WORKDIR/private/postgres-admin-password"
  printf 'MELLOA_POSTGRES_APP_PASSWORD_FILE=%s\n' \
    "$WORKDIR/private/postgres-app-password"
  printf 'MELLOA_POSTGRES_MIGRATION_PASSWORD_FILE=%s\n' \
    "$WORKDIR/private/postgres-migration-password"
  printf 'MELLOA_DATABASE_APPLICATION_DSN_FILE=%s\n' \
    "$WORKDIR/private/database-application-dsn"
  printf 'MELLOA_DATABASE_MIGRATION_DSN_FILE=%s\n' \
    "$WORKDIR/private/database-migration-dsn"
  printf 'MELLOA_OWNER_CREDENTIAL_FILE=%s\n' "$WORKDIR/private/owner-credential"
  printf 'MELLOA_TELEGRAM_OWNER_CONFIG_FILE=%s\n' "$WORKDIR/private/telegram-owner.json"
  printf 'MELLOA_TELEGRAM_BOT_TOKEN_FILE=%s\n' "$WORKDIR/private/telegram-bot-token"
  printf 'MELLOA_CAPABLE_MODEL_CONFIG_FILE=%s\n' "$WORKDIR/private/capable-model.json"
  printf 'MELLOA_ECONOMY_MODEL_CONFIG_FILE=%s\n' "$WORKDIR/private/economy-model.json"
  printf 'MELLOA_MODEL_CREDENTIALS_DIR=%s\n' "$WORKDIR/private/model-credentials"
  printf 'MELLOA_GUARDIAN_HANDOFF_DIR=%s\n' "$WORKDIR/guardian-handoff"
  printf 'MELLOA_RUNTIME_STATE_DIR=%s\n' "$WORKDIR/runtime-state"
} >"$ENV_FILE"

compose config --quiet
compose build melloa
if ! compose up --detach --no-build; then
  compose ps --all >&2 || true
  compose logs --no-color --tail=160 >&2 || true
  exit 1
fi

readonly MIGRATION_CONTAINER="$(compose ps --all --quiet migrate)"
for _ in $(seq 1 90); do
  migration_state="$(docker inspect --format '{{.State.Status}}' "$MIGRATION_CONTAINER")"
  if [[ "$migration_state" == exited ]]; then
    break
  fi
  sleep 1
done
[[ "$(docker inspect --format '{{.State.ExitCode}}' "$MIGRATION_CONTAINER")" == 0 ]]

readonly MELLOA_CONTAINER="$(wait_for_melloa)"
[[ "$(docker inspect --format '{{.Config.User}}' "$MELLOA_CONTAINER")" == "$(id -u):$(id -g)" ]]
[[ -z "$(docker port "$MELLOA_CONTAINER")" ]]

readonly ROLE_ROWS="$(
  compose exec --no-TTY --user postgres postgres \
    psql --tuples-only --no-align --field-separator=, \
    --username postgres --dbname melloa \
    --command="SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolinherit FROM pg_roles WHERE rolname IN ('melloa_app', 'melloa_migrator') ORDER BY rolname"
)"
grep -qx 'melloa_app,f,f,f,f' <<<"$ROLE_ROWS"
grep -qx 'melloa_migrator,f,f,f,f' <<<"$ROLE_ROWS"
[[ "$(
  compose exec --no-TTY --user postgres postgres psql --tuples-only --no-align \
    --username postgres --dbname melloa \
    --command="SELECT schema_owner FROM information_schema.schemata WHERE schema_name = 'melloa'"
)" == melloa_migrate ]]

compose run --rm --no-deps migrate migrate check >/dev/null

restart_count="$(docker inspect --format '{{.RestartCount}}' "$MELLOA_CONTAINER")"
docker exec --interactive "$MELLOA_CONTAINER" python - <<'PY' || [[ $? -eq 137 ]]
import os
from pathlib import Path

current = os.getpid()
for entry in Path("/proc").iterdir():
    if not entry.name.isdigit() or int(entry.name) in {1, current}:
        continue
    try:
        command = (entry / "cmdline").read_bytes()
    except OSError:
        continue
    if b"melloa.apps.cli" in command:
        os.kill(int(entry.name), 9)
        break
else:
    raise SystemExit("Melloa application process was not found")
PY
wait_for_restart "$MELLOA_CONTAINER" "$restart_count"

restart_count="$(docker inspect --format '{{.RestartCount}}' "$MELLOA_CONTAINER")"
compose restart postgres >/dev/null
wait_for_restart "$MELLOA_CONTAINER" "$restart_count"
compose run --rm --no-deps migrate migrate check >/dev/null

echo "Persistent server runtime, migration gate, and supervised database recovery passed."
