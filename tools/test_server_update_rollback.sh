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

cleanup() {
  if [[ "$WORKDIR" == /tmp/melloa-update-rollback-test.* && -d "$WORKDIR" ]]; then
    rm -rf -- "$WORKDIR"
  fi
}
trap cleanup EXIT HUP INT TERM

install -d -m 0700 \
  "$SOURCE/.git" \
  "$SOURCE/infra/server" \
  "$SOURCE/tools" \
  "$FAKEBIN"
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
EOF
chmod +x "$SOURCE/tools/server_release.sh"

cat >"$WORKDIR/activate" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'activate %s\n' "$*" >>"$MELLOA_UPDATE_ROLLBACK_FAKE_LOG"
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

PATH="$FAKEBIN:$PATH" \
MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_UPDATE_ACTIVATE_BIN="$WORKDIR/activate" \
MELLOA_UPDATE_VERIFY_BIN="$WORKDIR/verify-owner-journey" \
  "$ROOT/infra/server/update.sh" \
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

set +e
PATH="$FAKEBIN:$PATH" \
MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_UPDATE_ACTIVATE_BIN="$WORKDIR/activate-fail" \
MELLOA_UPDATE_VERIFY_BIN="$WORKDIR/verify-owner-journey" \
  "$ROOT/infra/server/update.sh" \
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
PATH="$FAKEBIN:$PATH" \
MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_UPDATE_ACTIVATE_BIN="$WORKDIR/activate" \
MELLOA_UPDATE_VERIFY_BIN="$WORKDIR/verify-fail" \
  "$ROOT/infra/server/update.sh" \
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

PATH="$FAKEBIN:$PATH" \
MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_ROLLBACK_VERIFY_BIN="$WORKDIR/verify-owner-journey" \
  "$ROOT/infra/server/rollback.sh" \
    --source "$SOURCE" \
    >"$WORKDIR/rollback-output.log" 2>&1

grep --fixed-strings --quiet \
  "server-release rollback --env-file /etc/melloa/server.env --state-dir /var/lib/melloa/release-state" \
  "$LOG"
grep --fixed-strings --quiet "Server rollback finished" "$WORKDIR/rollback-output.log"

set +e
PATH="$FAKEBIN:$PATH" \
MELLOA_UPDATE_ROLLBACK_FAKE_LOG="$LOG" \
MELLOA_ROLLBACK_VERIFY_BIN="$WORKDIR/verify-fail" \
  "$ROOT/infra/server/rollback.sh" \
    --source "$SOURCE" \
    >"$WORKDIR/rollback-verification-failed.log" 2>&1
status=$?
set -e
[[ "$status" == 1 ]]
grep --fixed-strings --quiet \
  "Server rollback failed: owner verification failed after rollback; run sudo /usr/local/libexec/melloa/verify-owner-journey" \
  "$WORKDIR/rollback-verification-failed.log"

echo "Server update and rollback wrapper checks passed."
