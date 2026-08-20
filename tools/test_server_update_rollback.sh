#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-update-rollback-test.XXXXXX)"
readonly SOURCE="$WORKDIR/release-source"
readonly FAKEBIN="$WORKDIR/fakebin"
readonly LOG="$WORKDIR/commands.log"
readonly CURRENT_REVISION=1111111111111111111111111111111111111111
readonly TARGET_REVISION=2222222222222222222222222222222222222222
readonly ORIGIN=https://github.com/melloa-project/melloa.git
readonly BUILD_CA="$WORKDIR/build-ca.pem"
readonly RUNTIME_STATE="$WORKDIR/runtime-state"
readonly RELEASE_STATE="$WORKDIR/release-state"
readonly ACTIVE_REVISION_FILE="$RELEASE_STATE/active-revision"
readonly RELEASE_STATE_FILE="$RELEASE_STATE/release.json"
readonly MAINTENANCE_HISTORY_FILE="$RUNTIME_STATE/maintenance-history.jsonl"

cleanup() {
  local status=$?
  if ((status != 0)); then
    for output in \
      "$WORKDIR/update-output.log" \
      "$WORKDIR/update-activation-failed.log" \
      "$WORKDIR/update-verification-failed.log" \
      "$WORKDIR/rollback-output.log" \
      "$WORKDIR/rollback-verification-failed.log"; do
      if [[ -f "$output" ]]; then
        echo "--- $(basename "$output") ---" >&2
        sed -n '1,200p' "$output" >&2 || true
      fi
    done
    if [[ -f "$LOG" ]]; then
      echo "--- fake command log ---" >&2
      sed -n '1,240p' "$LOG" >&2 || true
    fi
  fi
  if [[ "$WORKDIR" == /tmp/melloa-update-rollback-test.* && -d "$WORKDIR" ]]; then
    if ((EUID == 0)); then
      rm -rf -- "$WORKDIR"
    else
      sudo -n rm -rf -- "$WORKDIR" 2>/dev/null || rm -rf -- "$WORKDIR"
    fi
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

run_server_wrapper() {
  local -a environment=(
    "PATH=$FAKEBIN:$PATH"
    "MELLOA_UPDATE_ROLLBACK_FAKE_LOG=$LOG"
  )
  for name in \
    MELLOA_UPDATE_ACTIVATE_BIN \
    MELLOA_UPDATE_VERIFY_BIN \
    MELLOA_ROLLBACK_VERIFY_BIN \
    MELLOA_ACTIVE_REVISION_FILE \
    MELLOA_RELEASE_STATE_FILE \
    MELLOA_MAINTENANCE_HISTORY_FILE \
    MELLOA_UPDATE_ROLLBACK_CURRENT_REVISION \
    MELLOA_UPDATE_ROLLBACK_TARGET_REVISION; do
    if [[ -n "${!name+x}" ]]; then
      environment+=("$name=${!name}")
    fi
  done
  if ((EUID == 0)); then
    env "${environment[@]}" "$@"
  else
    command -v sudo >/dev/null 2>&1 ||
      { echo "update/rollback wrapper test requires root or passwordless sudo" >&2; return 2; }
    sudo -n true >/dev/null 2>&1 ||
      { echo "update/rollback wrapper test requires root or passwordless sudo" >&2; return 2; }
    sudo -n env "${environment[@]}" "$@"
  fi
}

install -d -m 0700 \
  "$SOURCE/.git" \
  "$SOURCE/infra/server" \
  "$SOURCE/tools" \
  "$FAKEBIN" \
  "$RUNTIME_STATE" \
  "$RELEASE_STATE"
install -m 0666 /dev/null "$LOG"
printf '%s\n' "$CURRENT_REVISION" >"$ACTIVE_REVISION_FILE"
jq -n --arg revision "$CURRENT_REVISION" '{active: {revision: $revision}}' >"$RELEASE_STATE_FILE"
printf '%s\n' '-----BEGIN CERTIFICATE-----' 'update-ca-test' \
  '-----END CERTIFICATE-----' >"$BUILD_CA"

cat >"$SOURCE/infra/server/install.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'install %s\n' "$*" >>"$MELLOA_UPDATE_ROLLBACK_FAKE_LOG"
EOF
chmod +x "$SOURCE/infra/server/install.sh"

cat >"$SOURCE/tools/server_release.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'server-release %s\n' "$*" >>"$MELLOA_UPDATE_ROLLBACK_FAKE_LOG"
if [[ "$1" == rollback ]]; then
  printf '%s\n' "$MELLOA_UPDATE_ROLLBACK_CURRENT_REVISION" >"$MELLOA_ACTIVE_REVISION_FILE"
fi
EOF
chmod +x "$SOURCE/tools/server_release.sh"

cat >"$WORKDIR/activate" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'activate %s\n' "$*" >>"$MELLOA_UPDATE_ROLLBACK_FAKE_LOG"
printf '%s\n' "$MELLOA_UPDATE_ROLLBACK_TARGET_REVISION" >"$MELLOA_ACTIVE_REVISION_FILE"
EOF
chmod +x "$WORKDIR/activate"

cat >"$WORKDIR/activate-fail" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'activate-fail %s\n' "$*" >>"$MELLOA_UPDATE_ROLLBACK_FAKE_LOG"
exit 42
EOF
chmod +x "$WORKDIR/activate-fail"

cat >"$WORKDIR/verify-owner-journey" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'verify %s\n' "$*" >>"$MELLOA_UPDATE_ROLLBACK_FAKE_LOG"
EOF
chmod +x "$WORKDIR/verify-owner-journey"

cat >"$WORKDIR/verify-fail" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'verify-fail %s\n' "$*" >>"$MELLOA_UPDATE_ROLLBACK_FAKE_LOG"
exit 43
EOF
chmod +x "$WORKDIR/verify-fail"

cat >"$FAKEBIN/git" <<EOF
#!/usr/bin/env bash
set -euo pipefail
printf 'git %s\n' "\$*" >>"\$MELLOA_UPDATE_ROLLBACK_FAKE_LOG"
[[ "\$1" == -C && "\$2" == "$SOURCE" ]]
shift 2
case "\$1" in
  remote)
    [[ "\$2" == get-url && "\$3" == origin ]]
    printf '%s\n' "$ORIGIN"
    ;;
  symbolic-ref)
    [[ "\$2" == --quiet && "\$3" == --short && "\$4" == HEAD ]]
    printf 'main\n'
    ;;
  status)
    [[ "\$2" == --porcelain && "\$3" == --untracked-files=normal ]]
    ;;
  rev-parse)
    if [[ "\$2" == HEAD ]]; then
      printf '%s\n' "$CURRENT_REVISION"
    elif [[ "\$2" == refs/remotes/origin/main ]]; then
      printf '%s\n' "$TARGET_REVISION"
    else
      exit 64
    fi
    ;;
  fetch)
    [[ "\$2" == --quiet && "\$3" == --no-tags && "\$4" == origin && "\$5" == main ]]
    ;;
  reset)
    [[ "\$2" == --quiet && "\$3" == --hard && "\$4" == "$TARGET_REVISION" ]]
    ;;
  *)
    exit 64
    ;;
esac
EOF
chmod +x "$FAKEBIN/git"

MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_ACTIVE_REVISION_FILE="$ACTIVE_REVISION_FILE" \
MELLOA_RELEASE_STATE_FILE="$RELEASE_STATE_FILE" \
MELLOA_MAINTENANCE_HISTORY_FILE="$MAINTENANCE_HISTORY_FILE" \
MELLOA_UPDATE_ROLLBACK_CURRENT_REVISION="$CURRENT_REVISION" \
MELLOA_UPDATE_ROLLBACK_TARGET_REVISION="$TARGET_REVISION" \
MELLOA_UPDATE_ACTIVATE_BIN="$WORKDIR/activate" \
MELLOA_UPDATE_VERIFY_BIN="$WORKDIR/verify-owner-journey" \
  run_server_wrapper "$ROOT/infra/server/update.sh" \
    --source "$SOURCE" \
    --origin "$ORIGIN" \
    --ca-file "$BUILD_CA" \
    >"$WORKDIR/update-output.log" 2>&1

grep --fixed-strings --quiet "git -C $SOURCE fetch --quiet --no-tags origin main" "$LOG"
grep --fixed-strings --quiet "git -C $SOURCE reset --quiet --hard $TARGET_REVISION" "$LOG"
grep --fixed-strings --quiet "install --source $SOURCE --origin $ORIGIN --ca-file $BUILD_CA" "$LOG"
grep --fixed-strings --quiet "activate --source $SOURCE --origin $ORIGIN" "$LOG"
grep --fixed-strings --quiet "verify --source $SOURCE" "$LOG"
grep --fixed-strings --quiet "Server update finished" "$WORKDIR/update-output.log"
run_server_wrapper jq -s -e \
  --arg from "$CURRENT_REVISION" \
  --arg active "$TARGET_REVISION" \
  'length == 1 and
    .[0].operation == "update" and
    .[0].result == "verified" and
    .[0].from_revision == $from and
    .[0].active_revision == $active and
    .[0].verification_kind == "telegram_conversation"' \
  "$MAINTENANCE_HISTORY_FILE" >/dev/null

set +e
MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_ACTIVE_REVISION_FILE="$ACTIVE_REVISION_FILE" \
MELLOA_MAINTENANCE_HISTORY_FILE="$MAINTENANCE_HISTORY_FILE" \
MELLOA_UPDATE_ROLLBACK_CURRENT_REVISION="$CURRENT_REVISION" \
MELLOA_UPDATE_ROLLBACK_TARGET_REVISION="$TARGET_REVISION" \
MELLOA_UPDATE_ACTIVATE_BIN="$WORKDIR/activate-fail" \
MELLOA_UPDATE_VERIFY_BIN="$WORKDIR/verify-owner-journey" \
  run_server_wrapper "$ROOT/infra/server/update.sh" \
    --source "$SOURCE" \
    --origin "$ORIGIN" \
    --ca-file "$BUILD_CA" \
    >"$WORKDIR/update-activation-failed.log" 2>&1
status=$?
set -e
[[ "$status" == 1 ]]
grep --fixed-strings --quiet \
  "Server update failed: activation failed; fix the reported cause, run sudo systemctl start melloa-release-recovery.service" \
  "$WORKDIR/update-activation-failed.log"

set +e
MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_ACTIVE_REVISION_FILE="$ACTIVE_REVISION_FILE" \
MELLOA_MAINTENANCE_HISTORY_FILE="$MAINTENANCE_HISTORY_FILE" \
MELLOA_UPDATE_ROLLBACK_CURRENT_REVISION="$CURRENT_REVISION" \
MELLOA_UPDATE_ROLLBACK_TARGET_REVISION="$TARGET_REVISION" \
MELLOA_UPDATE_ACTIVATE_BIN="$WORKDIR/activate" \
MELLOA_UPDATE_VERIFY_BIN="$WORKDIR/verify-fail" \
  run_server_wrapper "$ROOT/infra/server/update.sh" \
    --source "$SOURCE" \
    --origin "$ORIGIN" \
    --ca-file "$BUILD_CA" \
    >"$WORKDIR/update-verification-failed.log" 2>&1
status=$?
set -e
[[ "$status" == 1 ]]
grep --fixed-strings --quiet \
  "Server update failed: owner verification failed after update; run sudo /usr/local/libexec/melloa/verify-owner-journey" \
  "$WORKDIR/update-verification-failed.log"

jq -n --arg revision "$TARGET_REVISION" '{active: {revision: $revision}}' >"$RELEASE_STATE_FILE"
rm -f "$ACTIVE_REVISION_FILE"
MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_ACTIVE_REVISION_FILE="$ACTIVE_REVISION_FILE" \
MELLOA_RELEASE_STATE_FILE="$RELEASE_STATE_FILE" \
MELLOA_MAINTENANCE_HISTORY_FILE="$MAINTENANCE_HISTORY_FILE" \
MELLOA_UPDATE_ROLLBACK_CURRENT_REVISION="$CURRENT_REVISION" \
MELLOA_UPDATE_ROLLBACK_TARGET_REVISION="$TARGET_REVISION" \
MELLOA_ROLLBACK_VERIFY_BIN="$WORKDIR/verify-owner-journey" \
  run_server_wrapper "$ROOT/infra/server/rollback.sh" \
    --source "$SOURCE" \
    >"$WORKDIR/rollback-output.log" 2>&1

grep --fixed-strings --quiet \
  "server-release rollback --env-file /etc/melloa/server.env --state-dir /var/lib/melloa/release-state" \
  "$LOG"
grep --fixed-strings --quiet "verify --source $SOURCE" "$LOG"
grep --fixed-strings --quiet "Server rollback finished" "$WORKDIR/rollback-output.log"
run_server_wrapper jq -s -e \
  --arg from "$TARGET_REVISION" \
  --arg active "$CURRENT_REVISION" \
  'length == 2 and
    .[1].operation == "rollback" and
    .[1].result == "verified" and
    .[1].from_revision == $from and
    .[1].active_revision == $active and
    .[1].verification_kind == "telegram_conversation"' \
  "$MAINTENANCE_HISTORY_FILE" >/dev/null

set +e
MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_ACTIVE_REVISION_FILE="$ACTIVE_REVISION_FILE" \
MELLOA_RELEASE_STATE_FILE="$RELEASE_STATE_FILE" \
MELLOA_MAINTENANCE_HISTORY_FILE="$MAINTENANCE_HISTORY_FILE" \
MELLOA_UPDATE_ROLLBACK_CURRENT_REVISION="$CURRENT_REVISION" \
MELLOA_UPDATE_ROLLBACK_TARGET_REVISION="$TARGET_REVISION" \
MELLOA_ROLLBACK_VERIFY_BIN="$WORKDIR/verify-fail" \
  run_server_wrapper "$ROOT/infra/server/rollback.sh" \
    --source "$SOURCE" \
    >"$WORKDIR/rollback-verification-failed.log" 2>&1
status=$?
set -e
[[ "$status" == 1 ]]
grep --fixed-strings --quiet \
  "Server rollback failed: owner verification failed after rollback; run sudo /usr/local/libexec/melloa/verify-owner-journey" \
  "$WORKDIR/rollback-verification-failed.log"

echo "Server update and rollback wrapper checks passed."
