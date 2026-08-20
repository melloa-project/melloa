#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-restore-drill-test.XXXXXX)"
readonly TARGET="$WORKDIR/target"
readonly FAKEBIN="$WORKDIR/fakebin"
readonly LOG="$WORKDIR/commands.log"
readonly STAGE="$WORKDIR/stage"
readonly MIGRATION_PASSWORD='migration_RESTORE_DRILL_TEST_123456789012345678901234'
readonly SOURCE_REVISION=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
readonly SNAPSHOT=1111111111111111111111111111111111111111111111111111111111111111

cleanup() {
  local status=$?
  if ((status != 0)); then
    if [[ -f "$WORKDIR/output.log" ]]; then
      echo "--- restore-drill output ---" >&2
      sed -n '1,200p' "$WORKDIR/output.log" >&2
    fi
    if [[ -f "$LOG" ]]; then
      echo "--- fake command log ---" >&2
      sed -n '1,200p' "$LOG" >&2
    fi
  fi
  if [[ "$WORKDIR" == /tmp/melloa-restore-drill-test.* && -d "$WORKDIR" ]]; then
    if ((EUID == 0)); then
      rm -rf -- "$WORKDIR"
    else
      sudo -n rm -rf -- "$WORKDIR" 2>/dev/null || rm -rf -- "$WORKDIR"
    fi
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

run_restore_drill() {
  local -a environment=(
    "PATH=$FAKEBIN:$PATH"
    "MELLOA_RESTORE_DRILL_FAKE_LOG=$LOG"
    "MELLOA_RESTORE_DRILL_FAKE_STAGE=$STAGE"
  )
  if [[ -n "${MELLOA_RESTORE_DRILL_FAIL_RESTORE+x}" ]]; then
    environment+=("MELLOA_RESTORE_DRILL_FAIL_RESTORE=$MELLOA_RESTORE_DRILL_FAIL_RESTORE")
  fi
  if ((EUID == 0)); then
    env "${environment[@]}" "$ROOT/infra/server/restore-drill.sh" "$@"
  else
    command -v sudo >/dev/null 2>&1 ||
      { echo "restore-drill wrapper test requires root or passwordless sudo" >&2; return 2; }
    sudo -n true >/dev/null 2>&1 ||
      { echo "restore-drill wrapper test requires root or passwordless sudo" >&2; return 2; }
    sudo -n env "${environment[@]}" "$ROOT/infra/server/restore-drill.sh" "$@"
  fi
}

install -d -m 0700 \
  "$TARGET/etc/melloa/private" \
  "$TARGET/backup-repository" \
  "$TARGET/runtime-state" \
  "$FAKEBIN"
install -m 0666 /dev/null "$LOG"
install -m 0600 /dev/null "$TARGET/etc/melloa/private/postgres-migration-password"
printf '%s\n' "$MIGRATION_PASSWORD" >"$TARGET/etc/melloa/private/postgres-migration-password"
jq -n \
  --arg snapshot "$SNAPSHOT" \
  '{
    contract_version: "1.0.0",
    result: "success",
    checked_at: "2026-08-20T02:00:00Z",
    completed_at: "2026-08-20T02:00:01Z",
    snapshot_id: $snapshot
  }' >"$TARGET/runtime-state/backup-status.json"
{
  printf 'MELLOA_COMPOSE_PROJECT_NAME=melloa-server\n'
  printf 'MELLOA_BACKUP_IMAGE=melloa-local/backup:test\n'
  printf 'MELLOA_SOURCE_REVISION=%s\n' "$SOURCE_REVISION"
  printf 'MELLOA_RUNTIME_UID=10001\n'
  printf 'MELLOA_RUNTIME_GID=10001\n'
  printf 'MELLOA_RUNTIME_STATE_DIR=%s\n' "$TARGET/runtime-state"
  printf 'MELLOA_STATE_SUBNET=172.30.37.0/28\n'
  printf 'MELLOA_DATABASE_ADDRESS=172.30.37.2\n'
  printf 'MELLOA_POSTGRES_MIGRATION_PASSWORD_FILE=%s\n' \
    "$TARGET/etc/melloa/private/postgres-migration-password"
  printf 'MELLOA_DATABASE_MIGRATION_DSN_FILE=%s\n' \
    "$TARGET/etc/melloa/private/database-migration-dsn"
  printf 'MELLOA_BACKUP_REPOSITORY_DIR=%s\n' "$TARGET/backup-repository"
} >"$TARGET/etc/melloa/server.env"

cat >"$FAKEBIN/findmnt" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == --mountpoint && -d "$2" ]]
EOF
chmod +x "$FAKEBIN/findmnt"

cat >"$FAKEBIN/chown" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'chown %s\n' "$*" >>"$MELLOA_RESTORE_DRILL_FAKE_LOG"
exit 0
EOF
chmod +x "$FAKEBIN/chown"

cat >"$FAKEBIN/mktemp" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == -d && "$2" == /var/tmp/melloa-restore-drill.XXXXXX ]]; then
  install -d -m 0700 "$MELLOA_RESTORE_DRILL_FAKE_STAGE"
  printf '%s\n' "$MELLOA_RESTORE_DRILL_FAKE_STAGE"
  exit 0
fi
if [[ "$1" == */.restore-drill-status.XXXXXX ]]; then
  output="${1%XXXXXX}test"
  install -m 0600 /dev/null "$output"
  printf '%s\n' "$output"
  exit 0
fi
echo "unexpected fake mktemp invocation: $*" >&2
exit 64
EOF
chmod +x "$FAKEBIN/mktemp"

cat >"$FAKEBIN/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\n' "$*" >>"$MELLOA_RESTORE_DRILL_FAKE_LOG"
if [[ "$1" == image && "$2" == inspect ]]; then
  exit 0
fi
if [[ "$1" == compose ]]; then
  shift
  if [[ " $* " == *" config --quiet "* ]]; then
    exit 0
  fi
  if [[ " $* " == *" up --detach postgres database-logins "* ]]; then
    exit 0
  fi
  if [[ " $* " == *" ps --all --quiet database-logins"* ]]; then
    printf 'database-logins-container\n'
    exit 0
  fi
  if [[ " $* " == *" run --rm --no-deps restore restore-database latest"* ]]; then
    if [[ "${MELLOA_RESTORE_DRILL_FAIL_RESTORE:-false}" == true ]]; then
      exit 55
    fi
    exit 0
  fi
  if [[ " $* " == *" run --rm --no-deps migrate migrate check"* ]]; then
    exit 0
  fi
  if [[ " $* " == *" exec --no-TTY --user postgres postgres psql "* ]]; then
    if [[ " $* " == *"has_table_privilege"* ]]; then
      printf 'f\n'
      exit 0
    fi
    if [[ " $* " == *"DELETE FROM melloa.conversation_threads"* ]]; then
      exit 1
    fi
    exit 0
  fi
  if [[ " $* " == *" down --volumes --remove-orphans "* ]]; then
    exit 0
  fi
fi
if [[ "$1" == inspect ]]; then
  if [[ "$3" == '{{.State.Status}}' ]]; then
    printf 'exited\n'
    exit 0
  fi
  if [[ "$3" == '{{.State.ExitCode}}' ]]; then
    printf '0\n'
    exit 0
  fi
fi
echo "unexpected fake docker invocation: $*" >&2
exit 64
EOF
chmod +x "$FAKEBIN/docker"

run_restore_drill \
  --source "$ROOT" \
  --env-file "$TARGET/etc/melloa/server.env" \
  >"$WORKDIR/output.log" 2>&1

grep --fixed-strings --quiet "Encrypted restore drill passed" "$WORKDIR/output.log"
grep --fixed-strings --quiet "Restore drill receipt updated:" "$WORKDIR/output.log"
grep --fixed-strings --quiet "run --rm --no-deps restore restore-database latest" "$LOG"
grep --fixed-strings --quiet "run --rm --no-deps migrate migrate check" "$LOG"
grep --fixed-strings --quiet "restored Telegram conversation proof is missing" "$LOG"
grep --fixed-strings --quiet "has_table_privilege" "$LOG"
if grep --fixed-strings --quiet "melloa-server --" "$LOG"; then
  echo "Restore drill used the active compose project" >&2
  exit 1
fi
readonly RESTORE_RECEIPT="$TARGET/runtime-state/restore-drill-status.json"
if ((EUID == 0)); then
  receipt_command=()
else
  receipt_command=(sudo -n)
fi
"${receipt_command[@]}" test -f "$RESTORE_RECEIPT"
"${receipt_command[@]}" test ! -L "$RESTORE_RECEIPT"
[[ "$("${receipt_command[@]}" stat --format='%a' "$RESTORE_RECEIPT")" == 600 ]]
"${receipt_command[@]}" jq -e \
  --arg revision "$SOURCE_REVISION" \
  --arg snapshot "$SNAPSHOT" \
  '{
    contract_version,
    result,
    requested_snapshot,
    backup_status_snapshot_id,
    source_revision,
    proofs
  } == {
    contract_version: "1.0.0",
    result: "success",
    requested_snapshot: "latest",
    backup_status_snapshot_id: $snapshot,
    source_revision: $revision,
    proofs: {
      migration_check: true,
      owner_identity: true,
      telegram_owner_binding: true,
      telegram_conversation: true,
      readonly_role_cannot_mutate: true
    }
  } and
  (.drilled_at | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"))' \
  "$RESTORE_RECEIPT" >/dev/null
if "${receipt_command[@]}" grep --fixed-strings --quiet "$MIGRATION_PASSWORD" "$RESTORE_RECEIPT"; then
  echo "Restore drill receipt exposed the migration password" >&2
  exit 1
fi

set +e
MELLOA_RESTORE_DRILL_FAIL_RESTORE=true \
  run_restore_drill \
  --source "$ROOT" \
  --env-file "$TARGET/etc/melloa/server.env" \
  >"$WORKDIR/failed-output.log" 2>&1
status=$?
set -e
[[ "$status" == 1 ]]
grep --fixed-strings --quiet \
  "Server restore drill failed: encrypted snapshot restore failed; active Melloa was not modified." \
  "$WORKDIR/failed-output.log"
grep --fixed-strings --quiet \
  "sudo /usr/local/libexec/melloa/verify-owner-journey" \
  "$WORKDIR/failed-output.log"

echo "Server restore-drill wrapper checks passed."
