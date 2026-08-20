#!/usr/bin/env bash
set -uo pipefail

umask 077

readonly BACKUP_TAG=melloa-database
readonly RELEASE_TAG=melloa-release
readonly DUMP_FILENAME=melloa.dump
readonly DATABASE_PASSWORD_FILE=/run/melloa/private/postgres-backup-password
readonly MIGRATION_PASSWORD_FILE=/run/melloa/private/postgres-migration-password
readonly PGPASS_PATH=/tmp/postgres-backup.pgpass
readonly RESTORE_PGPASS_PATH=/tmp/postgres-restore.pgpass
readonly STATUS_FILE="${MELLOA_BACKUP_STATUS_FILE:-/run/melloa/state/backup-status.json}"
readonly INTERVAL_SECONDS="${MELLOA_BACKUP_INTERVAL_SECONDS:-86400}"
readonly RETRY_SECONDS="${MELLOA_BACKUP_RETRY_SECONDS:-900}"
readonly DUMP_TIMEOUT_SECONDS="${MELLOA_BACKUP_DUMP_TIMEOUT_SECONDS:-1800}"

stop_requested=false

request_stop() {
  stop_requested=true
}
trap request_stop TERM INT

timestamp() {
  date --utc '+%Y-%m-%dT%H:%M:%SZ'
}

require_positive_integer() {
  local value="$1"
  local label="$2"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "$label must be a positive integer" >&2
    return 1
  fi
}

require_secret_file() {
  local path="$1"
  local label="$2"
  local mode
  local permissions
  if [[ ! -f "$path" || -L "$path" || ! -r "$path" ]]; then
    echo "$label must be a readable regular secret" >&2
    return 1
  fi
  mode="$(stat --format='%a' "$path")"
  if [[ ! "$mode" =~ ^[0-7]{3,4}$ ]]; then
    echo "$label has an invalid permission mode" >&2
    return 1
  fi
  permissions=$((8#$mode))
  if ((permissions & 0022)); then
    echo "$label must not be writable by its group or other users" >&2
    return 1
  fi
}

write_marker() {
  local result="$1"
  local checked_at="$2"
  local completed_at="${3:-}"
  local snapshot_id="${4:-}"
  local reason_code="${5:-}"
  local status_directory
  local temporary

  status_directory="$(dirname "$STATUS_FILE")"
  if [[ ! -d "$status_directory" || -L "$status_directory" || ! -w "$status_directory" ]]; then
    echo "Backup status directory is unavailable" >&2
    return 1
  fi
  temporary="$(mktemp "$status_directory/.backup-status.XXXXXX")" || return 1
  if [[ "$result" == success ]]; then
    printf '%s\n' \
      "{\"contract_version\":\"1.0.0\",\"result\":\"success\",\"checked_at\":\"$checked_at\",\"completed_at\":\"$completed_at\",\"snapshot_id\":\"$snapshot_id\"}" \
      >"$temporary"
  else
    printf '%s\n' \
      "{\"contract_version\":\"1.0.0\",\"result\":\"failed\",\"checked_at\":\"$checked_at\",\"completed_at\":null,\"snapshot_id\":null,\"reason_code\":\"$reason_code\"}" \
      >"$temporary"
  fi
  chmod 0600 "$temporary"
  mv -- "$temporary" "$STATUS_FILE"
}

fail_backup() {
  local reason_code="$1"
  echo "Scheduled backup failed: $reason_code" >&2
  write_marker failed "$(timestamp)" "" "" "$reason_code"
  return 1
}

prepare_pgpass() {
  local password
  require_secret_file "$DATABASE_PASSWORD_FILE" "Backup database password" || return 1
  password="$(<"$DATABASE_PASSWORD_FILE")"
  if [[ ! "$password" =~ ^[A-Za-z0-9_-]{32,128}$ ]]; then
    echo "Backup database password has an invalid format" >&2
    return 1
  fi
  install -m 0600 /dev/null "$PGPASS_PATH"
  printf 'postgres:5432:melloa:melloa_backup_login:%s\n' "$password" >"$PGPASS_PATH"
  unset password
}

validate_common_configuration() {
  require_positive_integer "$INTERVAL_SECONDS" "Backup interval" || return 1
  require_positive_integer "$RETRY_SECONDS" "Backup retry interval" || return 1
  require_positive_integer "$DUMP_TIMEOUT_SECONDS" "Database dump timeout" || return 1
  if [[ -z "${RESTIC_PASSWORD_FILE:-}" ]]; then
    echo "RESTIC_PASSWORD_FILE must name a protected secret" >&2
    return 1
  fi
  require_secret_file "$RESTIC_PASSWORD_FILE" "Restic password" || return 1
  if [[ "${RESTIC_REPOSITORY:-}" != /run/melloa/repository ]]; then
    echo "Restic repository must use the protected mounted path" >&2
    return 1
  fi
  if [[ ! -d "$RESTIC_REPOSITORY" || -L "$RESTIC_REPOSITORY" ]]; then
    echo "Restic repository mount is unavailable" >&2
    return 1
  fi
}

validate_writable_configuration() {
  validate_common_configuration || return 1
  if [[ ! -w "$RESTIC_REPOSITORY" ]]; then
    echo "Restic repository mount is not writable" >&2
    return 1
  fi
}

run_backup() {
  local snapshot_tag="${1:-$BACKUP_TAG}"
  local backup_output
  local completed_at
  local snapshot_id
  local -a pipeline_status

  if ! restic --no-cache snapshots --no-lock >/dev/null; then
    fail_backup backup.repository_unavailable
    return 1
  fi

  backup_output="$(mktemp /tmp/restic-backup.XXXXXX)" || {
    fail_backup backup.temporary_state_failed
    return 1
  }

  timeout --signal=TERM --kill-after=5s "$DUMP_TIMEOUT_SECONDS" \
    env PGCONNECT_TIMEOUT=5 PGPASSFILE="$PGPASS_PATH" \
    pg_dump \
      --host postgres \
      --port 5432 \
      --username melloa_backup_login \
      --dbname melloa \
      --schema melloa \
      --format custom \
      --no-owner \
      --lock-wait-timeout 30s |
    restic --no-cache backup \
      --host melloa-server \
      --tag "$snapshot_tag" \
      --stdin \
      --stdin-filename "$DUMP_FILENAME" \
      --json >"$backup_output"
  pipeline_status=("${PIPESTATUS[@]}")

  if ((pipeline_status[0] != 0)); then
    snapshot_id="$(
      sed -n 's/.*"snapshot_id":"\([0-9a-f]\{64\}\)".*/\1/p' "$backup_output" |
        tail -n 1
    )"
    if [[ "$snapshot_id" =~ ^[0-9a-f]{64}$ ]] &&
      ! restic --no-cache forget "$snapshot_id" --prune >/dev/null; then
      find /tmp -maxdepth 1 -type f -name 'restic-backup.*' -delete
      fail_backup backup.failed_snapshot_cleanup_failed
      return 1
    fi
    find /tmp -maxdepth 1 -type f -name 'restic-backup.*' -delete
    fail_backup backup.database_dump_failed
    return 1
  fi
  if ((pipeline_status[1] != 0)); then
    find /tmp -maxdepth 1 -type f -name 'restic-backup.*' -delete
    fail_backup backup.repository_write_failed
    return 1
  fi

  completed_at="$(timestamp)"
  snapshot_id="$(
    sed -n 's/.*"snapshot_id":"\([0-9a-f]\{64\}\)".*/\1/p' "$backup_output" | tail -n 1
  )"
  find /tmp -maxdepth 1 -type f -name 'restic-backup.*' -delete
  if [[ ! "$snapshot_id" =~ ^[0-9a-f]{64}$ ]]; then
    fail_backup backup.snapshot_receipt_invalid
    return 1
  fi

  if [[ "$snapshot_tag" == "$RELEASE_TAG" ]]; then
    if ! restic --no-cache forget \
      --tag "$RELEASE_TAG" \
      --keep-last 10 \
      --prune >/dev/null; then
      fail_backup backup.retention_failed
      return 1
    fi
  elif ! restic --no-cache forget \
      --tag "$BACKUP_TAG" \
      --keep-daily 14 \
      --keep-weekly 8 \
      --keep-monthly 12 \
      --prune >/dev/null; then
    fail_backup backup.retention_failed
    return 1
  fi
  if ! restic --no-cache check >/dev/null; then
    fail_backup backup.repository_check_failed
    return 1
  fi

  if ! write_marker success "$(timestamp)" "$completed_at" "$snapshot_id"; then
    echo "Backup succeeded but its owner status could not be recorded" >&2
    return 1
  fi
  echo "Scheduled encrypted database backup completed: ${snapshot_id:0:12}"
}

sleep_interruptibly() {
  local seconds="$1"
  sleep "$seconds" &
  wait "$!" || true
}

run_loop() {
  local delay
  if ! validate_writable_configuration || ! prepare_pgpass; then
    fail_backup backup.configuration_invalid || true
    return 2
  fi
  while [[ "$stop_requested" == false ]]; do
    if run_backup; then
      delay="$INTERVAL_SECONDS"
    else
      delay="$RETRY_SECONDS"
    fi
    [[ "$stop_requested" == true ]] && break
    sleep_interruptibly "$delay"
  done
}

run_once() {
  if ! validate_writable_configuration || ! prepare_pgpass; then
    fail_backup backup.configuration_invalid || true
    return 2
  fi
  run_backup
}

run_release_backup() {
  if ! validate_writable_configuration || ! prepare_pgpass; then
    fail_backup backup.configuration_invalid || true
    return 2
  fi
  run_backup "$RELEASE_TAG"
}

initialize_repository() {
  validate_writable_configuration || return 2
  restic --no-cache init
}

check_repository() {
  validate_common_configuration || return 2
  restic --no-cache snapshots --no-lock >/dev/null &&
    restic --no-cache check >/dev/null
}

restore_snapshot() {
  local snapshot="${1:-latest}"
  validate_common_configuration || return 2
  if [[ ! "$snapshot" =~ ^(latest|[0-9a-f]{8,64})$ ]]; then
    echo "Restore snapshot must be 'latest' or a restic snapshot ID" >&2
    return 2
  fi
  restic --no-cache --no-lock dump "$snapshot" "$DUMP_FILENAME"
}

restore_database() {
  local snapshot="${1:-latest}"
  local replace="${2:-false}"
  local password
  local -a pipeline_status
  validate_common_configuration || return 2
  if [[ ! "$snapshot" =~ ^(latest|[0-9a-f]{8,64})$ ]]; then
    echo "Restore snapshot must be 'latest' or a restic snapshot ID" >&2
    return 2
  fi
  require_secret_file "$MIGRATION_PASSWORD_FILE" \
    "Migration database password" || return 2
  password="$(<"$MIGRATION_PASSWORD_FILE")"
  if [[ ! "$password" =~ ^[A-Za-z0-9_-]{32,128}$ ]]; then
    echo "Migration database password has an invalid format" >&2
    return 2
  fi
  install -m 0600 /dev/null "$RESTORE_PGPASS_PATH"
  printf 'postgres:5432:melloa:melloa_migrator:%s\n' "$password" \
    >"$RESTORE_PGPASS_PATH"
  unset password

  if [[ "$replace" == true ]]; then
    if ! PGCONNECT_TIMEOUT=5 PGPASSFILE="$RESTORE_PGPASS_PATH" psql \
      --host postgres \
      --port 5432 \
      --username melloa_migrator \
      --dbname melloa \
      --set=ON_ERROR_STOP=1 \
      --command='DROP SCHEMA IF EXISTS melloa CASCADE'; then
      find /tmp -maxdepth 1 -type f -name 'postgres-restore.pgpass' -delete
      echo "Existing database state could not be cleared for restore" >&2
      return 1
    fi
  fi

  restic --no-cache --no-lock dump "$snapshot" "$DUMP_FILENAME" |
    PGCONNECT_TIMEOUT=5 PGPASSFILE="$RESTORE_PGPASS_PATH" pg_restore \
      --host postgres \
      --port 5432 \
      --username melloa_migrator \
      --dbname melloa \
      --no-owner \
      --exit-on-error
  pipeline_status=("${PIPESTATUS[@]}")
  find /tmp -maxdepth 1 -type f -name 'postgres-restore.pgpass' -delete
  if ((pipeline_status[0] != 0 || pipeline_status[1] != 0)); then
    echo "Encrypted database restore failed" >&2
    return 1
  fi
}

case "${1:-run}" in
  run)
    run_loop
    ;;
  once)
    run_once
    ;;
  release)
    run_release_backup
    ;;
  init)
    initialize_repository
    ;;
  check)
    check_repository
    ;;
  restore)
    restore_snapshot "${2:-latest}"
    ;;
  restore-database)
    restore_database "${2:-latest}"
    ;;
  restore-database-replace)
    restore_database "${2:-latest}" true
    ;;
  *)
    echo "Usage: melloa-backup [run|once|release|init|check|restore|restore-database|restore-database-replace]" >&2
    exit 2
    ;;
esac
