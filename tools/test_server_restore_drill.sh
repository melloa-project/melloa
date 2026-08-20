#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-restore-drill-test.XXXXXX)"
readonly TARGET="$WORKDIR/target"
readonly FAKEBIN="$WORKDIR/fakebin"
readonly LOG="$WORKDIR/commands.log"
readonly STAGE="$WORKDIR/stage"
readonly MIGRATION_PASSWORD='migration_RESTORE_DRILL_TEST_123456789012345678901234'

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
    rm -rf -- "$WORKDIR"
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

install -d -m 0700 "$TARGET/etc/melloa/private" "$TARGET/backup-repository" "$FAKEBIN"
install -m 0600 /dev/null "$TARGET/etc/melloa/private/postgres-migration-password"
printf '%s\n' "$MIGRATION_PASSWORD" >"$TARGET/etc/melloa/private/postgres-migration-password"
{
  printf 'MELLOA_COMPOSE_PROJECT_NAME=melloa-server\n'
  printf 'MELLOA_BACKUP_IMAGE=melloa-local/backup:test\n'
  printf 'MELLOA_RUNTIME_UID=10001\n'
  printf 'MELLOA_RUNTIME_GID=10001\n'
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
[[ "$1" == -d && "$2" == /var/tmp/melloa-restore-drill.XXXXXX ]]
install -d -m 0700 "$MELLOA_RESTORE_DRILL_FAKE_STAGE"
printf '%s\n' "$MELLOA_RESTORE_DRILL_FAKE_STAGE"
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

PATH="$FAKEBIN:$PATH" \
MELLOA_RESTORE_DRILL_FAKE_LOG="$LOG" \
MELLOA_RESTORE_DRILL_FAKE_STAGE="$STAGE" \
  "$ROOT/infra/server/restore-drill.sh" \
    --source "$ROOT" \
    --env-file "$TARGET/etc/melloa/server.env" \
    >"$WORKDIR/output.log" 2>&1

grep --fixed-strings --quiet "Encrypted restore drill passed" "$WORKDIR/output.log"
grep --fixed-strings --quiet "run --rm --no-deps restore restore-database latest" "$LOG"
grep --fixed-strings --quiet "run --rm --no-deps migrate migrate check" "$LOG"
grep --fixed-strings --quiet "restored Telegram conversation proof is missing" "$LOG"
grep --fixed-strings --quiet "has_table_privilege" "$LOG"
if grep --fixed-strings --quiet "melloa-server --" "$LOG"; then
  echo "Restore drill used the active compose project" >&2
  exit 1
fi

set +e
PATH="$FAKEBIN:$PATH" \
MELLOA_RESTORE_DRILL_FAKE_LOG="$LOG" \
MELLOA_RESTORE_DRILL_FAKE_STAGE="$STAGE" \
MELLOA_RESTORE_DRILL_FAIL_RESTORE=true \
  "$ROOT/infra/server/restore-drill.sh" \
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
