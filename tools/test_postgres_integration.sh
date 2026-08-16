#!/usr/bin/env bash
set -euo pipefail

readonly POSTGRES_IMAGE="${MELLOA_POSTGRES_IMAGE:-pgvector/pgvector:0.8.6-pg18-trixie@sha256:78bf48b801e792f99e3ac62b5036fd3876e9be48afda16c1e331af1c75ceb2ff}"
readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CONTAINER="melloa-postgres-test-$RANDOM-$$"
readonly WORKDIR="$(mktemp -d)"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

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

docker run --detach --rm \
  --name "$CONTAINER" \
  --publish 127.0.0.1::5432 \
  --security-opt no-new-privileges:true \
  --env POSTGRES_HOST_AUTH_METHOD=trust \
  --env POSTGRES_DB=melloa \
  "$POSTGRES_IMAGE" >/dev/null

wait_for_postgres "$CONTAINER"
docker cp "$ROOT/infra/postgres/init/001_roles.sql" "$CONTAINER:/tmp/001_roles.sql"
docker exec "$CONTAINER" psql -v ON_ERROR_STOP=1 -U postgres -d melloa \
  --file /tmp/001_roles.sql >/dev/null

readonly PORT="$(docker port "$CONTAINER" 5432/tcp | sed 's/.*://')"
printf 'host=127.0.0.1 port=%s dbname=melloa user=postgres' "$PORT" >"$WORKDIR/dsn"
chmod 600 "$WORKDIR/dsn"

UV_CACHE_DIR="$ROOT/.cache/uv" uv run melloa migrate apply --dsn-file "$WORKDIR/dsn"
UV_CACHE_DIR="$ROOT/.cache/uv" uv run melloa migrate check --dsn-file "$WORKDIR/dsn"
MELLOA_TEST_DATABASE_DSN="$(cat "$WORKDIR/dsn")" \
  UV_CACHE_DIR="$ROOT/.cache/uv" \
  uv run pytest tests/integration/test_postgres.py -q --no-cov
