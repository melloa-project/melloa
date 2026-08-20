#!/usr/bin/env bash
set -euo pipefail
set +x

umask 077

SOURCE=/srv/melloa/release-source
ENV_FILE=/etc/melloa/server.env
DRILL_SUBNET=172.30.39.0/28
DRILL_DATABASE_ADDRESS=172.30.39.2
SNAPSHOT=latest
STAGE=""
DRILL_ENV_FILE=""
PROJECT=""

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/restore-drill.sh [--source PATH] [--env-file PATH]
                                     [--snapshot latest|SNAPSHOT_ID]
                                     [--subnet CIDR] [--database-address IP]

Restores an encrypted Melloa backup into a separate temporary Docker Compose project and database
volume, then runs migration check against that restored database. It does not stop or overwrite the
active Melloa deployment. Temporary containers, networks, and volumes are removed before exit.
EOF
  exit 2
}

while (($#)); do
  case "$1" in
    --source)
      [[ $# -ge 2 ]] || usage
      SOURCE="$2"
      shift 2
      ;;
    --env-file)
      [[ $# -ge 2 ]] || usage
      ENV_FILE="$2"
      shift 2
      ;;
    --snapshot)
      [[ $# -ge 2 ]] || usage
      SNAPSHOT="$2"
      shift 2
      ;;
    --subnet)
      [[ $# -ge 2 ]] || usage
      DRILL_SUBNET="$2"
      shift 2
      ;;
    --database-address)
      [[ $# -ge 2 ]] || usage
      DRILL_DATABASE_ADDRESS="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

fail() {
  echo "Server restore drill failed: $1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

read_environment_value() {
  local file="$1"
  local key="$2"
  local count
  local value
  count="$(awk -F= -v key="$key" '$1 == key {count += 1} END {print count + 0}' "$file")"
  [[ "$count" == 1 ]] || fail "$key must occur exactly once in $file"
  value="$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print}' "$file")"
  [[ -n "$value" && "$value" != *$'\r'* && "$value" != *$'\n'* ]] ||
    fail "$key has an invalid value"
  printf '%s' "$value"
}

read_environment_path() {
  local file="$1"
  local key="$2"
  local value
  value="$(read_environment_value "$file" "$key")"
  [[ "$value" == /* && "$value" != *$'\t'* && "$value" != *' '* && \
    "$value" != */../* && "$value" != */./* && "$value" != */.. && "$value" != */. ]] ||
    fail "$key must be a plain absolute path"
  printf '%s' "$value"
}

require_private_file() {
  local path="$1"
  local label="$2"
  local mode
  local permissions
  [[ -f "$path" && ! -L "$path" && -r "$path" ]] ||
    fail "$label must be a readable regular file"
  mode="$(stat --format='%a' "$path")"
  permissions=$((8#$mode))
  if ((permissions & 0077)); then
    fail "$label must be owner-only"
  fi
}

compose() {
  docker compose \
    --project-directory "$SOURCE" \
    --env-file "$DRILL_ENV_FILE" \
    --file "$SOURCE/compose.server.yaml" \
    "$@"
}

cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [[ "$PROJECT" == melloa-restore-drill-* && -n "$DRILL_ENV_FILE" && -f "$DRILL_ENV_FILE" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  if [[ "$STAGE" == /var/tmp/melloa-restore-drill.* && -d "$STAGE" ]]; then
    rm -rf -- "$STAGE"
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

wait_for_database_logins() {
  local container
  local state
  container="$(compose ps --all --quiet database-logins)"
  [[ -n "$container" ]] || fail "database login reconciliation container is unavailable"
  for _ in $(seq 1 120); do
    state="$(docker inspect --format '{{.State.Status}}' "$container")"
    if [[ "$state" == exited ]]; then
      [[ "$(docker inspect --format '{{.State.ExitCode}}' "$container")" == 0 ]] ||
        fail "database login reconciliation failed in the restore drill"
      return 0
    fi
    sleep 1
  done
  compose ps --all >&2 || true
  compose logs --no-color --tail=120 postgres database-logins >&2 || true
  fail "database login reconciliation did not complete in the restore drill"
}

for command in awk chmod chown date docker findmnt install mktemp rm seq sleep stat; do
  require_command "$command"
done

((EUID == 0)) || fail "restore drill must run as root"
[[ "$SOURCE" == /* && -d "$SOURCE" && ! -L "$SOURCE" ]] ||
  fail "source must be an absolute directory"
[[ -f "$SOURCE/compose.server.yaml" && ! -L "$SOURCE/compose.server.yaml" ]] ||
  fail "source checkout is missing compose.server.yaml"
[[ "$ENV_FILE" == /* && -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] ||
  fail "server environment file is unavailable"
[[ "$SNAPSHOT" =~ ^(latest|[0-9a-f]{8,64})$ ]] ||
  fail "snapshot must be latest or a restic snapshot ID"
[[ "$DRILL_SUBNET" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]] ||
  fail "restore-drill subnet must be an IPv4 CIDR"
[[ "$DRILL_DATABASE_ADDRESS" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
  fail "restore-drill database address must be an IPv4 address"

readonly RUNTIME_UID="$(read_environment_value "$ENV_FILE" MELLOA_RUNTIME_UID)"
readonly RUNTIME_GID="$(read_environment_value "$ENV_FILE" MELLOA_RUNTIME_GID)"
[[ "$RUNTIME_UID" =~ ^[1-9][0-9]*$ && "$RUNTIME_GID" =~ ^[1-9][0-9]*$ ]] ||
  fail "runtime UID/GID are invalid"
readonly BACKUP_IMAGE="$(read_environment_value "$ENV_FILE" MELLOA_BACKUP_IMAGE)"
docker image inspect "$BACKUP_IMAGE" >/dev/null ||
  fail "configured backup image is not available locally; run activation before the restore drill"
readonly MIGRATION_PASSWORD_FILE="$(
  read_environment_path "$ENV_FILE" MELLOA_POSTGRES_MIGRATION_PASSWORD_FILE
)"
readonly BACKUP_REPOSITORY_DIR="$(read_environment_path "$ENV_FILE" MELLOA_BACKUP_REPOSITORY_DIR)"
require_private_file "$MIGRATION_PASSWORD_FILE" "migration database password"
[[ -d "$BACKUP_REPOSITORY_DIR" && ! -L "$BACKUP_REPOSITORY_DIR" ]] ||
  fail "backup repository directory is unavailable"
findmnt --mountpoint "$BACKUP_REPOSITORY_DIR" >/dev/null ||
  fail "backup repository directory must be an explicit mount point"

STAGE="$(mktemp -d /var/tmp/melloa-restore-drill.XXXXXX)"
PROJECT="melloa-restore-drill-$(date +%Y%m%d%H%M%S)-$$"
DRILL_ENV_FILE="$STAGE/server.env"
readonly DRILL_MIGRATION_DSN="$STAGE/database-migration-dsn"
MIGRATION_PASSWORD="$(<"$MIGRATION_PASSWORD_FILE")"
[[ "$MIGRATION_PASSWORD" =~ ^[A-Za-z0-9_-]{32,128}$ ]] ||
  fail "migration database password has an invalid format"
install -m 0600 /dev/null "$DRILL_MIGRATION_DSN"
printf 'host=%s port=5432 dbname=melloa user=melloa_migrator password=%s\n' \
  "$DRILL_DATABASE_ADDRESS" "$MIGRATION_PASSWORD" >"$DRILL_MIGRATION_DSN"
unset MIGRATION_PASSWORD
chown "$RUNTIME_UID:$RUNTIME_GID" "$DRILL_MIGRATION_DSN"

awk -F= \
  -v project="$PROJECT" \
  -v subnet="$DRILL_SUBNET" \
  -v database="$DRILL_DATABASE_ADDRESS" \
  -v migration_dsn="$DRILL_MIGRATION_DSN" '
  $1 == "MELLOA_COMPOSE_PROJECT_NAME" { print "MELLOA_COMPOSE_PROJECT_NAME=" project; next }
  $1 == "MELLOA_STATE_SUBNET" { print "MELLOA_STATE_SUBNET=" subnet; next }
  $1 == "MELLOA_DATABASE_ADDRESS" { print "MELLOA_DATABASE_ADDRESS=" database; next }
  $1 == "MELLOA_DATABASE_MIGRATION_DSN_FILE" {
    print "MELLOA_DATABASE_MIGRATION_DSN_FILE=" migration_dsn; next
  }
  { print }
' "$ENV_FILE" >"$DRILL_ENV_FILE"
chmod 0600 "$DRILL_ENV_FILE"

compose config --quiet ||
  fail "restore-drill compose configuration failed; active Melloa was not modified"
echo "Starting temporary restore-drill database project $PROJECT."
compose up --detach postgres database-logins >/dev/null ||
  fail "temporary restore-drill database did not start; active Melloa was not modified"
wait_for_database_logins
compose run --rm --no-deps restore restore-database "$SNAPSHOT" >/dev/null ||
  fail "encrypted snapshot restore failed; active Melloa was not modified. Fix the reported backup issue, then run sudo /usr/local/libexec/melloa/verify-owner-journey to confirm the active deployment"
compose run --rm --no-deps migrate migrate check >/dev/null ||
  fail "restored database failed migration check; active Melloa was not modified. Do not treat backups as proven until restore-drill passes"
echo "Encrypted restore drill passed using snapshot $SNAPSHOT."
