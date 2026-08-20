#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-owner-verification-test.XXXXXX)"
readonly TARGET="$WORKDIR/target"
readonly FAKEBIN="$WORKDIR/fakebin"
readonly LOG="$WORKDIR/commands.log"
readonly QUERY_COUNT="$WORKDIR/query-count"
readonly PHRASE="Hello Melli, please reply to setup verification melloa_verify_testNonce123; it's me"
readonly BACKUP_REPOSITORY="$TARGET/mnt/melloa-off-device-backup"

cleanup() {
  local status=$?
  if ((status != 0)); then
    if [[ -f "$WORKDIR/output.log" ]]; then
      echo "--- owner verification output ---" >&2
      sed -n '1,200p' "$WORKDIR/output.log" >&2
    fi
    if [[ -f "$LOG" ]]; then
      echo "--- fake command log ---" >&2
      sed -n '1,200p' "$LOG" >&2
    fi
  fi
  if [[ "$WORKDIR" == /tmp/melloa-owner-verification-test.* && -d "$WORKDIR" ]]; then
    rm -rf -- "$WORKDIR"
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

install -d -m 0700 \
  "$TARGET/etc/melloa" \
  "$BACKUP_REPOSITORY" \
  "$TARGET/var/lib/melloa/runtime-state" \
  "$TARGET/var/lib/melloa/release-state" \
  "$FAKEBIN"
printf '{"contract_version":"1.0.0","backup_repository":"/mnt/melloa-off-device-backup"}\n' \
  >"$TARGET/etc/melloa/configuration.json"
printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n' \
  >"$TARGET/var/lib/melloa/release-state/active-revision"
jq -n \
  --arg revision aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --arg app_id "sha256:$(printf '%064d' 2)" \
  --arg backup_id "sha256:$(printf '%064d' 3)" \
  '{
    contract_version: "1.0.0",
    active: {
      revision: $revision,
      app_image: ("melloa-local/server:" + $revision),
      backup_image: ("melloa-local/backup:" + $revision),
      app_image_id: $app_id,
      backup_image_id: $backup_id,
      activated_at: "2026-08-20T00:00:00Z"
    },
    previous: null,
    predeploy_snapshot: null
  }' >"$TARGET/var/lib/melloa/release-state/release.json"
printf '{"result":"success","snapshot_id":"%064d"}\n' 1 \
  >"$TARGET/var/lib/melloa/runtime-state/backup-status.json"
{
  printf 'MELLOA_COMPOSE_PROJECT_NAME=melloa-server-test\n'
  printf 'MELLOA_SOURCE_REVISION=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
  printf 'MELLOA_RUNTIME_STATE_DIR=/var/lib/melloa/runtime-state\n'
  printf 'MELLOA_RELEASE_STATE_DIR=/var/lib/melloa/release-state\n'
  printf 'MELLOA_BACKUP_REPOSITORY_DIR=/mnt/melloa-off-device-backup\n'
} >"$TARGET/etc/melloa/server.env"
{
  printf 'MELLOA_SELF_CHANGE_ENABLED=false\n'
  printf 'MELLOA_CODEX_USE_API_KEY=false\n'
  printf 'MELLOA_CODEX_MODEL=\n'
  printf 'MELLOA_CODEX_LOCAL_PROVIDER=\n'
} >"$TARGET/etc/melloa/self-change.env"

cat >"$FAKEBIN/systemctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == is-enabled || "$1" == is-active ]]
if [[ "${*: -1}" == melloa-self-change-planner.service || \
  "${*: -1}" == melloa-self-change-applier.service ]]; then
  exit 1
fi
exit 0
EOF
chmod +x "$FAKEBIN/systemctl"

cat >"$FAKEBIN/findmnt" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == --mountpoint ]]
[[ "${MELLOA_VERIFY_FAIL_FINDMNT:-false}" != true ]]
[[ "$2" == "$MELLOA_VERIFY_BACKUP_REPOSITORY" ]]
EOF
chmod +x "$FAKEBIN/findmnt"

cat >"$FAKEBIN/stat" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == --format=%d ]]; then
  case "$2" in
    "$MELLOA_VERIFY_BACKUP_REPOSITORY")
      printf '200\n'
      ;;
    "$MELLOA_VERIFY_ROOT")
      printf '100\n'
      ;;
    *)
      /usr/bin/stat "$@"
      ;;
  esac
  exit 0
fi
/usr/bin/stat "$@"
EOF
chmod +x "$FAKEBIN/stat"

cat >"$FAKEBIN/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\n' "$*" >>"$MELLOA_VERIFY_FAKE_LOG"
if [[ "$1" == compose ]]; then
  shift
  if [[ " $* " == *" config --quiet "* ]]; then
    exit 0
  fi
  if [[ " $* " == *" ps --quiet postgres"* ]]; then
    printf 'postgres-container\n'
    exit 0
  fi
  if [[ " $* " == *" ps --quiet melloa"* ]]; then
    printf 'melloa-container\n'
    exit 0
  fi
  if [[ " $* " == *" ps --quiet backup"* ]]; then
    printf 'backup-container\n'
    exit 0
  fi
  if [[ " $* " == *" exec "* && " $* " == *" psql "* ]]; then
    count=0
    if [[ -f "$MELLOA_VERIFY_QUERY_COUNT" ]]; then
      count="$(<"$MELLOA_VERIFY_QUERY_COUNT")"
    fi
    count=$((count + 1))
    printf '%s\n' "$count" >"$MELLOA_VERIFY_QUERY_COUNT"
    if ((count >= 2)); then
      printf 'sent||1||message_reply_00000000000000000000000000000001|Synthetic installed reply.\n'
    fi
    exit 0
  fi
fi
if [[ "$1" == inspect ]]; then
  format="$3"
  target="${4:-}"
  if [[ "$format" == '{{.State.Status}}' ]]; then
    printf 'running\n'
    exit 0
  fi
  if [[ "$format" == '{{if .State.Health}}{{.State.Health.Status}}{{end}}' ]]; then
    if [[ "$target" == backup-container ]]; then
      printf '\n'
    else
      printf 'healthy\n'
    fi
    exit 0
  fi
fi
echo "unexpected fake docker invocation: $*" >&2
exit 64
EOF
chmod +x "$FAKEBIN/docker"

set +e
PATH="$FAKEBIN:$PATH" \
MELLOA_VERIFY_BACKUP_REPOSITORY="$BACKUP_REPOSITORY" \
MELLOA_VERIFY_FAIL_FINDMNT=true \
MELLOA_VERIFY_FAKE_LOG="$LOG" \
MELLOA_VERIFY_QUERY_COUNT="$QUERY_COUNT" \
MELLOA_VERIFY_ROOT="$TARGET" \
  "$ROOT/infra/server/verify-owner-journey.sh" \
    --source "$ROOT" \
    --root "$TARGET" \
    --phrase "$PHRASE" \
    --timeout 5 \
    --poll-seconds 1 \
    >"$WORKDIR/missing-mount-output.log" 2>&1
status=$?
set -e
[[ "$status" == 1 ]]
grep --fixed-strings --quiet \
  "backup repository must be an explicit mount point" \
  "$WORKDIR/missing-mount-output.log"
[[ ! -f "$TARGET/var/lib/melloa/runtime-state/owner-verification-status.json" ]]

PATH="$FAKEBIN:$PATH" \
MELLOA_VERIFY_BACKUP_REPOSITORY="$BACKUP_REPOSITORY" \
MELLOA_VERIFY_FAKE_LOG="$LOG" \
MELLOA_VERIFY_QUERY_COUNT="$QUERY_COUNT" \
MELLOA_VERIFY_ROOT="$TARGET" \
  "$ROOT/infra/server/verify-owner-journey.sh" \
    --source "$ROOT" \
    --root "$TARGET" \
    --phrase "$PHRASE" \
    --timeout 5 \
    --poll-seconds 1 \
    >"$WORKDIR/output.log" 2>&1

grep --fixed-strings --quiet "First owner deployment verification passed." \
  "$WORKDIR/output.log"
grep --fixed-strings --quiet "optional self-change workers are disabled" \
  "$WORKDIR/output.log"
grep --fixed-strings --quiet "Backup repository mount is explicit and independent" \
  "$WORKDIR/output.log"
grep --fixed-strings --quiet "Owner verification receipt updated:" \
  "$WORKDIR/output.log"
grep --fixed-strings --quiet "docker compose" "$LOG"
grep --fixed-strings --quiet -- "--set=verification_phrase=$PHRASE" "$LOG"
[[ "$(<"$QUERY_COUNT")" -ge 2 ]]
readonly RECEIPT="$TARGET/var/lib/melloa/runtime-state/owner-verification-status.json"
[[ -f "$RECEIPT" && ! -L "$RECEIPT" ]]
[[ "$(stat --format='%a' "$RECEIPT")" == 600 ]]
jq -e \
  --arg revision aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --arg snapshot "$(printf '%064d' 1)" \
  '{
    contract_version,
    verification_kind,
    active_revision,
    backup_snapshot_id,
    response_message_id
  } == {
    contract_version: "1.0.0",
    verification_kind: "telegram_conversation",
    active_revision: $revision,
    backup_snapshot_id: $snapshot,
    response_message_id: "message_reply_00000000000000000000000000000001"
  } and
  (.verified_at | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"))' \
  "$RECEIPT" >/dev/null
if grep --fixed-strings --quiet "$PHRASE" "$RECEIPT"; then
  echo "Owner verification receipt exposed the Telegram verification phrase" >&2
  exit 1
fi

echo "Owner Telegram conversation verifier checks passed."
