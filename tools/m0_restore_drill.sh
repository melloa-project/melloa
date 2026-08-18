#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly POSTGRES_IMAGE="${MELLOA_POSTGRES_IMAGE:-pgvector/pgvector:0.8.6-pg18-trixie@sha256:78bf48b801e792f99e3ac62b5036fd3876e9be48afda16c1e331af1c75ceb2ff}"
readonly RESTIC_IMAGE="${MELLOA_RESTIC_IMAGE:-restic/restic:0.19.1@sha256:136600b6ff6843d61d355f7f71f460a166429f35de6fd11b568fece3c9a4d510}"
readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RUN_UID="$(id -u)"
readonly RUN_GID="$(id -g)"
readonly RUN_ID="melloa-d002-$RANDOM-$$"
readonly SOURCE_CONTAINER="${RUN_ID}-source"
readonly TARGET_CONTAINER="${RUN_ID}-target"
readonly NETWORK="${RUN_ID}-network"
readonly SENSITIVE_FIXTURE_MARKER='d002-owner-private-recovery-marker-v1'
readonly UV_CACHE_PATH="$ROOT/.cache/uv"

mkdir -p "$ROOT/.cache"
readonly WORKDIR="$(mktemp -d "$ROOT/.cache/d002-recovery.XXXXXX")"
readonly SOURCE_DSN_FILE="$WORKDIR/source-dsn"
readonly TARGET_DSN_FILE="$WORKDIR/target-dsn"
readonly OWNER_CREDENTIAL_FILE="$WORKDIR/owner-credential"
readonly RESTIC_PASSWORD_FILE="$WORKDIR/restic-password"
readonly EXPECTED_FILE="$WORKDIR/expected-owner-state.json"

cleanup() {
  docker rm -f "$SOURCE_CONTAINER" "$TARGET_CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  if [[ "$WORKDIR" == "$ROOT"/.cache/d002-recovery.* ]]; then
    rm -rf -- "$WORKDIR"
  fi
}
trap cleanup EXIT

verify_cleanup() {
  docker rm -f "$SOURCE_CONTAINER" "$TARGET_CONTAINER" >/dev/null
  docker network rm "$NETWORK" >/dev/null
  if [[ "$WORKDIR" != "$ROOT"/.cache/d002-recovery.* ]]; then
    echo 'refusing to remove an unexpected recovery work directory' >&2
    return 1
  fi
  rm -rf -- "$WORKDIR"
  if [[ -e "$WORKDIR" ]]; then
    echo 'recovery work directory was not removed' >&2
    return 1
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "required command is unavailable: $1" >&2
    exit 2
  fi
}

wait_for_postgres() {
  local container="$1"
  local attempt
  local ready_count=0
  for attempt in $(seq 1 60); do
    if docker exec "$container" pg_isready -U postgres -d melloa >/dev/null 2>&1; then
      ready_count=$((ready_count + 1))
      if ((ready_count >= 2)); then
        return 0
      fi
    else
      ready_count=0
    fi
    sleep 1
  done
  echo "PostgreSQL did not become stably ready: $container" >&2
  docker logs "$container" >&2 || true
  return 1
}

start_postgres() {
  local container="$1"
  docker run --detach --rm \
    --name "$container" \
    --network "$NETWORK" \
    --publish 127.0.0.1::5432 \
    --security-opt no-new-privileges:true \
    --env POSTGRES_HOST_AUTH_METHOD=trust \
    --env POSTGRES_DB=melloa \
    "$POSTGRES_IMAGE" >/dev/null
  wait_for_postgres "$container"
}

apply_roles() {
  local container="$1"
  docker cp "$ROOT/infra/postgres/init/001_roles.sql" "$container:/tmp/001_roles.sql"
  docker exec "$container" psql -v ON_ERROR_STOP=1 -U postgres -d melloa \
    --file /tmp/001_roles.sql >/dev/null
}

write_dsn() {
  local container="$1"
  local output_file="$2"
  local endpoint
  local port
  endpoint="$(docker port "$container" 5432/tcp)"
  port="${endpoint##*:}"
  if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    echo "could not resolve the private PostgreSQL port" >&2
    return 1
  fi
  printf 'host=127.0.0.1 port=%s dbname=melloa user=postgres' "$port" >"$output_file"
  chmod 600 "$output_file"
}

run_migration_command() {
  UV_CACHE_DIR="$UV_CACHE_PATH" uv run melloa migrate "$@"
}

run_owner_journey() {
  UV_CACHE_DIR="$UV_CACHE_PATH" uv run python \
    "$ROOT/tools/recovery_owner_journey.py" "$@"
}

require_command docker
require_command grep
require_command openssl
require_command uv

printf '%s' "$(openssl rand -hex 32)" >"$OWNER_CREDENTIAL_FILE"
printf '%s' "$(openssl rand -hex 32)" >"$RESTIC_PASSWORD_FILE"
chmod 600 "$OWNER_CREDENTIAL_FILE" "$RESTIC_PASSWORD_FILE"
mkdir -p "$WORKDIR/repository" "$WORKDIR/backup-input" "$WORKDIR/restore-output"

docker network create "$NETWORK" >/dev/null
start_postgres "$SOURCE_CONTAINER"
apply_roles "$SOURCE_CONTAINER"
write_dsn "$SOURCE_CONTAINER" "$SOURCE_DSN_FILE"
run_migration_command apply --dsn-file "$SOURCE_DSN_FILE" >/dev/null
run_migration_command check --dsn-file "$SOURCE_DSN_FILE" >/dev/null

run_owner_journey seed \
  --dsn-file "$SOURCE_DSN_FILE" \
  --owner-credential-file "$OWNER_CREDENTIAL_FILE" \
  --expected-file "$EXPECTED_FILE" >/dev/null

docker exec "$SOURCE_CONTAINER" pg_dump -U postgres -d melloa \
  --format=custom --no-owner --file=/tmp/melloa.dump
docker exec "$SOURCE_CONTAINER" pg_restore \
  --file=/tmp/melloa.fixture.sql /tmp/melloa.dump
if ! docker exec "$SOURCE_CONTAINER" grep --fixed-strings --quiet \
  "$SENSITIVE_FIXTURE_MARKER" /tmp/melloa.fixture.sql; then
  echo 'custom logical dump did not contain the known private fixture marker' >&2
  exit 1
fi
docker cp "$SOURCE_CONTAINER:/tmp/melloa.dump" "$WORKDIR/backup-input/melloa.dump"

docker run --rm --network none \
  --user "$RUN_UID:$RUN_GID" \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$WORKDIR/repository,target=/repository" \
  --mount "type=bind,source=$RESTIC_PASSWORD_FILE,target=/run/secrets/restic-password,readonly" \
  --env RESTIC_REPOSITORY=/repository \
  --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  "$RESTIC_IMAGE" --no-cache init >/dev/null
docker run --rm --network none \
  --user "$RUN_UID:$RUN_GID" \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$WORKDIR/repository,target=/repository" \
  --mount "type=bind,source=$WORKDIR/backup-input,target=/data,readonly" \
  --mount "type=bind,source=$RESTIC_PASSWORD_FILE,target=/run/secrets/restic-password,readonly" \
  --env RESTIC_REPOSITORY=/repository \
  --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  "$RESTIC_IMAGE" --no-cache backup /data/melloa.dump >/dev/null
docker run --rm --network none \
  --user "$RUN_UID:$RUN_GID" \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$WORKDIR/repository,target=/repository" \
  --mount "type=bind,source=$RESTIC_PASSWORD_FILE,target=/run/secrets/restic-password,readonly" \
  --env RESTIC_REPOSITORY=/repository \
  --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  "$RESTIC_IMAGE" --no-cache check >/dev/null

if grep -R --binary-files=text --fixed-strings --quiet \
  "$SENSITIVE_FIXTURE_MARKER" "$WORKDIR/repository"; then
  echo 'restic repository exposed the private fixture marker in plaintext' >&2
  exit 1
else
  plaintext_scan_status=$?
  if ((plaintext_scan_status != 1)); then
    echo 'restic repository plaintext scan could not inspect every file' >&2
    exit 1
  fi
fi

docker run --rm --network none \
  --user "$RUN_UID:$RUN_GID" \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$WORKDIR/repository,target=/repository,readonly" \
  --mount "type=bind,source=$WORKDIR/restore-output,target=/restore" \
  --mount "type=bind,source=$RESTIC_PASSWORD_FILE,target=/run/secrets/restic-password,readonly" \
  --env RESTIC_REPOSITORY=/repository \
  --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  "$RESTIC_IMAGE" --no-cache --no-lock restore latest --target /restore >/dev/null

readonly RESTORED_DUMP="$WORKDIR/restore-output/data/melloa.dump"
if [[ ! -f "$RESTORED_DUMP" ]]; then
  echo 'restic restore did not produce the database dump' >&2
  exit 1
fi

start_postgres "$TARGET_CONTAINER"
apply_roles "$TARGET_CONTAINER"
docker cp "$RESTORED_DUMP" "$TARGET_CONTAINER:/tmp/melloa.dump"
docker exec "$TARGET_CONTAINER" pg_restore -U postgres -d melloa \
  --no-owner --exit-on-error /tmp/melloa.dump >/dev/null
write_dsn "$TARGET_CONTAINER" "$TARGET_DSN_FILE"
run_migration_command check --dsn-file "$TARGET_DSN_FILE" >/dev/null

run_owner_journey verify \
  --dsn-file "$TARGET_DSN_FILE" \
  --owner-credential-file "$OWNER_CREDENTIAL_FILE" \
  --expected-file "$EXPECTED_FILE" >/dev/null

readonly READONLY_HAS_MUTATION_PRIVILEGE="$(
  docker exec "$TARGET_CONTAINER" psql -qAt -U postgres -d melloa -c \
    "SELECT has_table_privilege('melloa_readonly', 'melloa.conversation_threads', 'INSERT') OR has_table_privilege('melloa_readonly', 'melloa.conversation_threads', 'UPDATE') OR has_table_privilege('melloa_readonly', 'melloa.conversation_threads', 'DELETE');"
)"
if [[ "$READONLY_HAS_MUTATION_PRIVILEGE" != 'f' ]]; then
  echo 'read-only role unexpectedly holds a conversation mutation privilege' >&2
  exit 1
fi
if docker exec "$TARGET_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d melloa \
  -c "SET ROLE melloa_readonly; DELETE FROM melloa.conversation_threads;" \
  >/dev/null 2>&1; then
  echo 'read-only role unexpectedly mutated restored owner data' >&2
  exit 1
fi

verify_cleanup
trap - EXIT
run_owner_journey receipt
