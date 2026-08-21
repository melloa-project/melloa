#!/usr/bin/env bash
set -euo pipefail
set +x

umask 077

export PATH=/opt/melloa/toolchain/bin:"${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

SOURCE=/srv/melloa/release-source
SKIP_VERIFICATION=false
VERIFY_BIN="${MELLOA_ROLLBACK_VERIFY_BIN:-/usr/local/libexec/melloa/verify-owner-journey}"
ACTIVE_REVISION_FILE="${MELLOA_ACTIVE_REVISION_FILE:-/var/lib/melloa/release-state/active-revision}"
RELEASE_STATE_FILE="${MELLOA_RELEASE_STATE_FILE:-/var/lib/melloa/release-state/release.json}"
MAINTENANCE_HISTORY_FILE="$(
  printf '%s' "${MELLOA_MAINTENANCE_HISTORY_FILE:-/var/lib/melloa/runtime-state/maintenance-history.jsonl}"
)"

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

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

validate_revision() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || fail "$2 is not a full lowercase Git commit SHA"
}

validate_plain_absolute_path() {
  local path="$1"
  [[ "$path" == /*/* && "$path" != *$'\t'* && "$path" != *' '* && \
    "$path" != */../* && "$path" != */./* && "$path" != */.. && "$path" != */. ]] ||
    fail "$2 must be a plain absolute path"
}

read_active_revision() {
  local revision
  validate_plain_absolute_path "$ACTIVE_REVISION_FILE" "active revision file"
  validate_plain_absolute_path "$RELEASE_STATE_FILE" "release state receipt file"
  if [[ -L "$ACTIVE_REVISION_FILE" ]]; then
    fail "active release marker must not be a symlink"
  elif [[ -f "$ACTIVE_REVISION_FILE" ]]; then
    revision="$(<"$ACTIVE_REVISION_FILE")"
  else
    [[ -f "$RELEASE_STATE_FILE" && ! -L "$RELEASE_STATE_FILE" ]] ||
      fail "release state receipt is unavailable"
    revision="$(jq -er '.active.revision' "$RELEASE_STATE_FILE")" ||
      fail "release state receipt is invalid"
  fi
  validate_revision "$revision" "active release revision"
  printf '%s' "$revision"
}

write_maintenance_receipt() {
  local operation="$1"
  local result="$2"
  local from_revision="$3"
  local active_revision="$4"
  local verification_kind="$5"
  local receipt_dir
  local completed_at
  local receipt

  [[ "$operation" == rollback ]] || fail "maintenance operation is invalid"
  [[ "$result" == verified || "$result" == verification_skipped ]] ||
    fail "maintenance result is invalid"
  validate_revision "$from_revision" "maintenance from revision"
  validate_revision "$active_revision" "maintenance active revision"
  [[ "$verification_kind" == "" || "$verification_kind" == telegram_conversation ]] ||
    fail "maintenance verification kind is invalid"
  validate_plain_absolute_path "$MAINTENANCE_HISTORY_FILE" "maintenance history file"
  receipt_dir="${MAINTENANCE_HISTORY_FILE%/*}"
  [[ -d "$receipt_dir" && ! -L "$receipt_dir" ]] ||
    fail "runtime state directory is unavailable for the maintenance receipt"
  [[ ! -L "$MAINTENANCE_HISTORY_FILE" ]] || fail "maintenance history receipt must not be a symlink"

  completed_at="$(date --utc '+%Y-%m-%dT%H:%M:%SZ')"
  receipt="$(
    jq -cn \
      --arg operation "$operation" \
      --arg result "$result" \
      --arg completed_at "$completed_at" \
      --arg from_revision "$from_revision" \
      --arg active_revision "$active_revision" \
      --arg verification_kind "$verification_kind" \
      '{
        contract_version: "1.0.0",
        operation: $operation,
        result: $result,
        completed_at: $completed_at,
        from_revision: $from_revision,
        active_revision: $active_revision,
        verification_kind: (if $verification_kind == "" then null else $verification_kind end)
      }'
  )"
  printf '%s\n' "$receipt" >>"$MAINTENANCE_HISTORY_FILE" ||
    fail "could not write maintenance receipt"
  chmod 0600 "$MAINTENANCE_HISTORY_FILE" || fail "could not protect maintenance receipt"
}

for command in date jq; do
  require_command "$command"
done

((EUID == 0)) || fail "rollback must run as root"
[[ "$SOURCE" == /* && -d "$SOURCE/.git" && ! -L "$SOURCE" && ! -L "$SOURCE/.git" ]] ||
  fail "source must be the managed absolute Git checkout"
[[ -x "$SOURCE/tools/server_release.sh" ]] || fail "server release tool is unavailable"

from_revision="$(read_active_revision)"
if ! "$SOURCE/tools/server_release.sh" rollback \
  --env-file /etc/melloa/server.env \
  --state-dir /var/lib/melloa/release-state; then
  fail "release rollback failed; fix the reported cause, run sudo systemctl start melloa-release-recovery.service, then run sudo /usr/local/libexec/melloa/verify-owner-journey"
fi
active_revision="$(read_active_revision)"

if [[ "$SKIP_VERIFICATION" == false ]]; then
  [[ -x "$VERIFY_BIN" ]] || fail "installed owner verification command is unavailable"
  if ! "$VERIFY_BIN" --source "$SOURCE"; then
    fail "owner verification failed after rollback; run sudo /usr/local/libexec/melloa/verify-owner-journey after fixing the reported cause"
  fi
  write_maintenance_receipt rollback verified "$from_revision" "$active_revision" telegram_conversation
  echo "Server rollback finished and Telegram conversation verification passed."
else
  write_maintenance_receipt rollback verification_skipped "$from_revision" "$active_revision" ""
  echo "Server rollback finished. Verification was skipped; run sudo /usr/local/libexec/melloa/verify-owner-journey before treating the server as healthy."
fi
