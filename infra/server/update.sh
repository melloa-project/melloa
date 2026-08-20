#!/usr/bin/env bash
set -euo pipefail
set +x

umask 077

SOURCE=/srv/melloa/release-source
ORIGIN=https://github.com/melloa-project/melloa.git
SKIP_VERIFICATION=false
CA_FILE=""
ACTIVATE_BIN="${MELLOA_UPDATE_ACTIVATE_BIN:-/usr/local/libexec/melloa/activate}"
VERIFY_BIN="${MELLOA_UPDATE_VERIFY_BIN:-/usr/local/libexec/melloa/verify-owner-journey}"

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/update.sh [--source PATH] [--origin HTTPS_URL] [--ca-file PATH]
                              [--skip-verification]

Updates the managed release checkout to the current reviewed main branch, refreshes installed host
assets, activates the release through the normal backup-protected deployment path, then runs the
owner Telegram verifier unless --skip-verification is selected.
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
    --origin)
      [[ $# -ge 2 ]] || usage
      ORIGIN="$2"
      shift 2
      ;;
    --ca-file)
      [[ $# -ge 2 ]] || usage
      CA_FILE="$2"
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
  echo "Server update failed: $1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

apply_ca_file() {
  local path="$1"
  [[ "$path" == /* && -f "$path" && ! -L "$path" && -r "$path" ]] ||
    fail "CA bundle must be an absolute readable regular file, not a symlink"
  export CURL_CA_BUNDLE="$path"
  export GIT_SSL_CAINFO="$path"
  export NODE_EXTRA_CA_CERTS="$path"
  export SSL_CERT_FILE="$path"
}

configured_build_ca_file() {
  local count
  local value
  [[ -f /etc/melloa/server.env && ! -L /etc/melloa/server.env ]] || return 0
  count="$(awk -F= '$1 == "MELLOA_BUILD_CA_FILE" {count += 1} END {print count + 0}' \
    /etc/melloa/server.env)"
  [[ "$count" == 1 ]] || fail "MELLOA_BUILD_CA_FILE must occur exactly once in /etc/melloa/server.env"
  value="$(awk -F= '$1 == "MELLOA_BUILD_CA_FILE" {sub(/^[^=]*=/, ""); print}' \
    /etc/melloa/server.env)"
  [[ "$value" == /* && "$value" != *$'\t'* && "$value" != *' '* && \
    "$value" != */../* && "$value" != */./* && "$value" != */.. && "$value" != */. ]] ||
    fail "MELLOA_BUILD_CA_FILE must be a plain absolute path"
  printf '%s' "$value"
}

validate_revision() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || fail "$2 is not a full lowercase Git commit SHA"
}

for command in awk git; do
  require_command "$command"
done

((EUID == 0)) || fail "update must run as root"
[[ "$SOURCE" == /* && -d "$SOURCE/.git" && ! -L "$SOURCE" && ! -L "$SOURCE/.git" ]] ||
  fail "source must be the managed absolute Git checkout"
[[ "$ORIGIN" == https://* && "$ORIGIN" != *'@'* && "$ORIGIN" != *'?'* && "$ORIGIN" != *'#'* ]] ||
  fail "origin must be a credential-free HTTPS URL"
[[ "$(git -C "$SOURCE" remote get-url origin)" == "$ORIGIN" ]] ||
  fail "managed release checkout has the wrong origin"
[[ "$(git -C "$SOURCE" symbolic-ref --quiet --short HEAD)" == main ]] ||
  fail "managed release checkout must have main checked out"
[[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=normal)" ]] ||
  fail "managed release checkout is dirty; inspect /srv/melloa/release-source before updating"
if [[ -z "$CA_FILE" ]]; then
  CA_FILE="$(configured_build_ca_file)"
fi
declare -a INSTALL_ARGS=(--source "$SOURCE" --origin "$ORIGIN")
if [[ -n "$CA_FILE" ]]; then
  apply_ca_file "$CA_FILE"
  INSTALL_ARGS+=(--ca-file "$CA_FILE")
fi

current_revision="$(git -C "$SOURCE" rev-parse HEAD)"
validate_revision "$current_revision" "current revision"
git -C "$SOURCE" fetch --quiet --no-tags origin main
target_revision="$(git -C "$SOURCE" rev-parse refs/remotes/origin/main)"
validate_revision "$target_revision" "target revision"

if [[ "$current_revision" == "$target_revision" ]]; then
  echo "Managed release checkout is already at current main ${target_revision:0:12}; refreshing installed assets and activation."
else
  git -C "$SOURCE" reset --quiet --hard "$target_revision"
  echo "Managed release checkout updated from ${current_revision:0:12} to ${target_revision:0:12}."
fi

if ! "$SOURCE/infra/server/install.sh" "${INSTALL_ARGS[@]}"; then
  fail "host asset refresh failed; fix the reported cause and rerun sudo /usr/local/libexec/melloa/update"
fi
[[ -x "$ACTIVATE_BIN" ]] || fail "installed activation command is unavailable"
if ! "$ACTIVATE_BIN" --source "$SOURCE" --origin "$ORIGIN"; then
  fail "activation failed; fix the reported cause, run sudo systemctl start melloa-release-recovery.service, then run sudo /usr/local/libexec/melloa/verify-owner-journey before retrying the update"
fi

if [[ "$SKIP_VERIFICATION" == false ]]; then
  [[ -x "$VERIFY_BIN" ]] || fail "installed owner verification command is unavailable"
  if ! "$VERIFY_BIN" --source "$SOURCE"; then
    fail "owner verification failed after update; run sudo /usr/local/libexec/melloa/verify-owner-journey after fixing the reported cause, or run sudo /usr/local/libexec/melloa/rollback if the active release is bad"
  fi
  echo "Server update finished and Telegram conversation verification passed."
else
  echo "Server update finished. Verification was skipped; run sudo /usr/local/libexec/melloa/verify-owner-journey before treating the server as healthy."
fi
