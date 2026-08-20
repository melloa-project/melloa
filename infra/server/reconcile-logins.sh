#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly SECRET_DIR=/run/secrets
readonly PGPASS_PATH=/tmp/postgres-admin.pgpass

read_password() {
  local path="$1"
  local label="$2"
  local value
  if [[ ! -f "$path" || -L "$path" || ! -r "$path" ]]; then
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

cleanup() {
  find /tmp -maxdepth 1 -type f -name 'postgres-admin.pgpass' -delete
}
trap cleanup EXIT

admin_password="$(
  read_password "$SECRET_DIR/postgres_admin_password" "Administrative database password"
)"
app_password="$(
  read_password "$SECRET_DIR/postgres_app_password" "Application database password"
)"
migration_password="$(
  read_password "$SECRET_DIR/postgres_migration_password" "Migration database password"
)"
backup_password="$(
  read_password "$SECRET_DIR/postgres_backup_password" "Backup database password"
)"

install -m 0600 /dev/null "$PGPASS_PATH"
printf 'postgres:5432:melloa:postgres:%s\n' "$admin_password" >"$PGPASS_PATH"
unset admin_password

PGPASSFILE="$PGPASS_PATH" psql \
  --host postgres \
  --port 5432 \
  --username postgres \
  --dbname melloa \
  --set=ON_ERROR_STOP=1 <<SQL
SELECT format(
  'CREATE ROLE melloa_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
  '$app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_app')
\gexec

SELECT format('ALTER ROLE melloa_app PASSWORD %L', '$app_password')
\gexec

SELECT format(
  'CREATE ROLE melloa_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
  '$migration_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_migrator')
\gexec

SELECT format('ALTER ROLE melloa_migrator PASSWORD %L', '$migration_password')
\gexec

SELECT format(
  'CREATE ROLE melloa_backup_login LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L',
  '$backup_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_backup_login')
\gexec

SELECT format('ALTER ROLE melloa_backup_login PASSWORD %L', '$backup_password')
\gexec

GRANT melloa_core TO melloa_app;
GRANT melloa_migrate TO melloa_migrator;
GRANT melloa_backup TO melloa_backup_login;
GRANT CREATE ON DATABASE melloa TO melloa_migrate;
ALTER ROLE melloa_app SET role = 'melloa_core';
ALTER ROLE melloa_migrator SET role = 'melloa_migrate';
ALTER ROLE melloa_backup_login SET role = 'melloa_backup';
SQL

unset app_password migration_password backup_password
