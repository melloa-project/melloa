#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-owner-verification-test.XXXXXX)"
readonly TARGET="$WORKDIR/target"
readonly FAKEBIN="$WORKDIR/fakebin"
readonly LOG="$WORKDIR/commands.log"
readonly QUERY_COUNT="$WORKDIR/query-count"
readonly PHRASE="Hello Melli, please reply to setup verification melloa_verify_testNonce123; it's me"

cleanup() {
  if [[ "$WORKDIR" == /tmp/melloa-owner-verification-test.* && -d "$WORKDIR" ]]; then
    rm -rf -- "$WORKDIR"
  fi
}
trap cleanup EXIT HUP INT TERM

install -d -m 0700 \
  "$TARGET/etc/melloa" \
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

PATH="$FAKEBIN:$PATH" \
MELLOA_VERIFY_FAKE_LOG="$LOG" \
MELLOA_VERIFY_QUERY_COUNT="$QUERY_COUNT" \
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
grep --fixed-strings --quiet "docker compose" "$LOG"
grep --fixed-strings --quiet -- "--set=verification_phrase=$PHRASE" "$LOG"
[[ "$(<"$QUERY_COUNT")" -ge 2 ]]

echo "Owner Telegram conversation verifier checks passed."
