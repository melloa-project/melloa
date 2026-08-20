#!/usr/bin/env bash
set -euo pipefail
set +x

umask 077

SOURCE=/srv/melloa/release-source
SKIP_VERIFICATION=false
VERIFY_BIN="${MELLOA_ROLLBACK_VERIFY_BIN:-/usr/local/libexec/melloa/verify-owner-journey}"

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/rollback.sh [--source PATH] [--skip-verification]

Rolls back to the previous recorded Melloa release through the backup-protected release tool, then
runs the owner Telegram verifier unless --skip-verification is selected. Rollback refuses to start
an older release when its migration manifest is incompatible with current owner data.
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
    --skip-verification)
      SKIP_VERIFICATION=true
      shift
      ;;
    *)
      usage
      ;;
  esac
done

fail() {
  echo "Server rollback failed: $1" >&2
  exit 1
}

((EUID == 0)) || fail "rollback must run as root"
[[ "$SOURCE" == /* && -d "$SOURCE/.git" && ! -L "$SOURCE" && ! -L "$SOURCE/.git" ]] ||
  fail "source must be the managed absolute Git checkout"
[[ -x "$SOURCE/tools/server_release.sh" ]] || fail "server release tool is unavailable"

if ! "$SOURCE/tools/server_release.sh" rollback \
  --env-file /etc/melloa/server.env \
  --state-dir /var/lib/melloa/release-state; then
  fail "release rollback failed; fix the reported cause, run sudo systemctl start melloa-release-recovery.service, then run sudo /usr/local/libexec/melloa/verify-owner-journey"
fi

if [[ "$SKIP_VERIFICATION" == false ]]; then
  [[ -x "$VERIFY_BIN" ]] || fail "installed owner verification command is unavailable"
  if ! "$VERIFY_BIN" --source "$SOURCE"; then
    fail "owner verification failed after rollback; run sudo /usr/local/libexec/melloa/verify-owner-journey after fixing the reported cause"
  fi
  echo "Server rollback finished and Telegram conversation verification passed."
else
  echo "Server rollback finished. Verification was skipped; run sudo /usr/local/libexec/melloa/verify-owner-journey before treating the server as healthy."
fi
