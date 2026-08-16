#!/usr/bin/env bash
set -euo pipefail

readonly POSTGRES_IMAGE="${MELLOA_POSTGRES_IMAGE:-pgvector/pgvector:0.8.6-pg18-trixie@sha256:78bf48b801e792f99e3ac62b5036fd3876e9be48afda16c1e331af1c75ceb2ff}"
readonly RESTIC_IMAGE="${MELLOA_RESTIC_IMAGE:-restic/restic:0.19.1@sha256:136600b6ff6843d61d355f7f71f460a166429f35de6fd11b568fece3c9a4d510}"
readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RUN_UID="$(id -u)"
readonly RUN_GID="$(id -g)"
readonly RUN_ID="melloa-m0-$RANDOM-$$"
readonly SOURCE_CONTAINER="${RUN_ID}-source"
readonly TARGET_CONTAINER="${RUN_ID}-target"
readonly NETWORK="${RUN_ID}-network"
mkdir -p "$ROOT/.cache"
readonly WORKDIR="$(mktemp -d "$ROOT/.cache/m0-restore.XXXXXX")"

cleanup() {
  docker rm -f "$SOURCE_CONTAINER" "$TARGET_CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

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
    --security-opt no-new-privileges:true \
    --env POSTGRES_HOST_AUTH_METHOD=trust \
    --env POSTGRES_DB=melloa \
    "$POSTGRES_IMAGE" >/dev/null
  wait_for_postgres "$container"
}

apply_foundation() {
  local container="$1"
  docker cp "$ROOT/infra/postgres/init/001_roles.sql" "$container:/tmp/001_roles.sql"
  docker cp "$ROOT/migrations/0001_m0_foundation.sql" "$container:/tmp/0001_m0_foundation.sql"
  docker exec "$container" psql -v ON_ERROR_STOP=1 -U postgres -d melloa \
    --file /tmp/001_roles.sql >/dev/null
  docker exec "$container" psql -v ON_ERROR_STOP=1 -U postgres -d melloa \
    --file /tmp/0001_m0_foundation.sql >/dev/null
}

require_command docker
require_command openssl
umask 077
printf '%s' "$(openssl rand -hex 32)" >"$WORKDIR/restic-password"
mkdir -p "$WORKDIR/repository" "$WORKDIR/backup-input" "$WORKDIR/restore-output"

docker network create --internal "$NETWORK" >/dev/null
start_postgres "$SOURCE_CONTAINER"
apply_foundation "$SOURCE_CONTAINER"

docker exec --interactive "$SOURCE_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d melloa <<'SQL' >/dev/null
INSERT INTO melloa.canonical_events (
  event_id, event_type, schema_version, occurred_at, recorded_at,
  epistemic_status, sensitivity, trust_label, payload_hash, document
) VALUES (
  'event_00000000000000000000000000000001',
  'observation.restore_fixture.v1',
  '1.0.0',
  '2026-08-16T12:00:00Z',
  '2026-08-16T12:00:00Z',
  'observation',
  'internal',
  'trusted_system',
  'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  '{"marker":"fixture.restore-marker","synthetic":true}'::jsonb
);
INSERT INTO melloa.audit_events (
  audit_id, event_type, occurred_at, actor_id, action_name,
  previous_hash, record_hash, document
) VALUES (
  'audit_00000000000000000000000000000001',
  'audit.restore_fixture_appended.v1',
  '2026-08-16T12:00:00Z',
  'owner_00000000000000000000000000000001',
  'events.append',
  NULL,
  'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  '{"synthetic":true}'::jsonb
);
SQL

docker exec "$SOURCE_CONTAINER" pg_dump -U postgres -d melloa \
  --format=custom --no-owner --file=/tmp/melloa.dump
docker cp "$SOURCE_CONTAINER:/tmp/melloa.dump" "$WORKDIR/backup-input/melloa.dump"

docker run --rm --network none \
  --user "$RUN_UID:$RUN_GID" \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$WORKDIR/repository,target=/repository" \
  --mount "type=bind,source=$WORKDIR/restic-password,target=/run/secrets/restic-password,readonly" \
  --env RESTIC_REPOSITORY=/repository \
  --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  "$RESTIC_IMAGE" --no-cache init >/dev/null
docker run --rm --network none \
  --user "$RUN_UID:$RUN_GID" \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$WORKDIR/repository,target=/repository" \
  --mount "type=bind,source=$WORKDIR/backup-input,target=/data,readonly" \
  --mount "type=bind,source=$WORKDIR/restic-password,target=/run/secrets/restic-password,readonly" \
  --env RESTIC_REPOSITORY=/repository \
  --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  "$RESTIC_IMAGE" --no-cache backup /data/melloa.dump >/dev/null
docker run --rm --network none \
  --user "$RUN_UID:$RUN_GID" \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$WORKDIR/repository,target=/repository" \
  --mount "type=bind,source=$WORKDIR/restic-password,target=/run/secrets/restic-password,readonly" \
  --env RESTIC_REPOSITORY=/repository \
  --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  "$RESTIC_IMAGE" --no-cache check >/dev/null

plaintext_scan_status=0
grep -R --binary-files=text --quiet 'fixture.restore-marker' "$WORKDIR/repository" \
  || plaintext_scan_status=$?
if ((plaintext_scan_status == 0)); then
  echo 'restic repository exposed the plaintext fixture marker' >&2
  exit 1
elif ((plaintext_scan_status != 1)); then
  echo 'restic repository plaintext scan could not inspect every file' >&2
  exit 1
fi

docker run --rm --network none \
  --user "$RUN_UID:$RUN_GID" \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$WORKDIR/repository,target=/repository,readonly" \
  --mount "type=bind,source=$WORKDIR/restore-output,target=/restore" \
  --mount "type=bind,source=$WORKDIR/restic-password,target=/run/secrets/restic-password,readonly" \
  --env RESTIC_REPOSITORY=/repository \
  --env RESTIC_PASSWORD_FILE=/run/secrets/restic-password \
  "$RESTIC_IMAGE" --no-cache --no-lock restore latest --target /restore >/dev/null

readonly RESTORED_DUMP="$(find "$WORKDIR/restore-output" -name melloa.dump -type f -print -quit)"
if [[ -z "$RESTORED_DUMP" ]]; then
  echo 'restic restore did not produce the database dump' >&2
  exit 1
fi

start_postgres "$TARGET_CONTAINER"
docker cp "$ROOT/infra/postgres/init/001_roles.sql" "$TARGET_CONTAINER:/tmp/001_roles.sql"
docker exec "$TARGET_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d melloa \
  --file /tmp/001_roles.sql >/dev/null
docker cp "$RESTORED_DUMP" "$TARGET_CONTAINER:/tmp/melloa.dump"
docker exec "$TARGET_CONTAINER" pg_restore -U postgres -d melloa \
  --no-owner --exit-on-error /tmp/melloa.dump >/dev/null

readonly RESTORED_MARKER="$(docker exec "$TARGET_CONTAINER" psql -qAt -U postgres -d melloa \
  -c "SET ROLE melloa_readonly; SELECT document->>'marker' FROM melloa.canonical_events WHERE event_id = 'event_00000000000000000000000000000001';")"
if [[ "$RESTORED_MARKER" != 'fixture.restore-marker' ]]; then
  echo "restored fixture marker is incorrect: $RESTORED_MARKER" >&2
  exit 1
fi

if docker exec "$TARGET_CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d melloa \
  -c "SET ROLE melloa_readonly; DELETE FROM melloa.canonical_events;" >/dev/null 2>&1; then
  echo 'read-only role unexpectedly mutated restored canonical data' >&2
  exit 1
fi

cat <<JSON
{
  "drill": "m0-encrypted-clean-restore",
  "postgres_image": "$POSTGRES_IMAGE",
  "restic_image": "$RESTIC_IMAGE",
  "encrypted_repository_plaintext_scan": "pass",
  "restic_integrity_check": "pass",
  "fixture_restore": "pass",
  "read_only_mutation_denied": "pass"
}
JSON
