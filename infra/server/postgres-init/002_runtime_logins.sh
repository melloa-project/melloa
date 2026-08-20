#!/usr/bin/env bash
set -euo pipefail

read_password() {
  local path="$1"
  local label="$2"
  local value
  if [[ ! -f "$path" || ! -r "$path" ]]; then
    echo "$label must be a readable regular Docker secret" >&2
    return 1
  fi
  value="$(<"$path")"
  if [[ ! "$value" =~ ^[A-Za-z0-9_-]{32,128}$ ]]; then
    echo "$label must contain 32-128 base64url-safe characters" >&2
    return 1
  fi
  printf '%s' "$value"
}

readonly INIT_SECRET_DIR=/run/melloa-postgres-init

cleanup() {
  rm -f \
    "$INIT_SECRET_DIR/postgres_app_password" \
    "$INIT_SECRET_DIR/postgres_migration_password"
  rmdir "$INIT_SECRET_DIR" 2>/dev/null || true
}
trap cleanup EXIT

app_password="$(
  read_password "$INIT_SECRET_DIR/postgres_app_password" "Application database password"
)"
migration_password="$(
  read_password "$INIT_SECRET_DIR/postgres_migration_password" "Migration database password"
)"

psql \
  --set=ON_ERROR_STOP=1 \
  --set=app_password="$app_password" \
  --set=migration_password="$migration_password" \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" <<'SQL'
SELECT format(
  'CREATE ROLE melloa_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
  :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_app')
\gexec

SELECT format('ALTER ROLE melloa_app PASSWORD %L', :'app_password')
\gexec

SELECT format(
  'CREATE ROLE melloa_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
  :'migration_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_migrator')
\gexec

SELECT format('ALTER ROLE melloa_migrator PASSWORD %L', :'migration_password')
\gexec

GRANT melloa_core TO melloa_app;
GRANT melloa_migrate TO melloa_migrator;
GRANT CREATE ON DATABASE melloa TO melloa_migrate;
ALTER ROLE melloa_app SET role = 'melloa_core';
ALTER ROLE melloa_migrator SET role = 'melloa_migrate';
SQL

unset app_password migration_password
