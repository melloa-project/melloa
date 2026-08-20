#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT"
ORIGIN="https://github.com/melloa-project/melloa.git"
INSTALLED=false
CA_FILE=""

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/preflight.sh [--source PATH] [--origin HTTPS_URL] [--ca-file PATH] [--installed]
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
    --installed)
      INSTALLED=true
      shift
      ;;
    *)
      usage
      ;;
  esac
done

fail() {
  echo "Server preflight failed: $1" >&2
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

version_at_least() {
  local actual="$1"
  local required="$2"
  [[ "$(printf '%s\n%s\n' "$required" "$actual" | sort -V | head -n 1)" == "$required" ]]
}

require_private_file() {
  local path="$1"
  local label="$2"
  local minimum_size="${3:-1}"
  local expected_uid="${4:-0}"
  local expected_gid="${5:-0}"
  local mode
  local permissions
  [[ -f "$path" && ! -L "$path" ]] || fail "$label must be a regular file"
  [[ "$(stat --format='%u' "$path")" == "$expected_uid" ]] ||
    fail "$label has the wrong owner"
  [[ "$(stat --format='%g' "$path")" == "$expected_gid" ]] ||
    fail "$label has the wrong group"
  mode="$(stat --format='%a' "$path")"
  permissions=$((8#$mode))
  ((permissions & 0177)) && fail "$label must be mode 0600 or 0400"
  ((permissions & 0400)) || fail "$label must be owner-readable"
  [[ "$(stat --format='%s' "$path")" -ge "$minimum_size" ]] || fail "$label is empty"
}

require_private_directory() {
  local path="$1"
  local label="$2"
  local expected_uid="$3"
  local expected_gid="$4"
  local mode
  [[ -d "$path" && ! -L "$path" ]] || fail "$label must be a directory"
  [[ "$(stat --format='%u' "$path")" == "$expected_uid" ]] ||
    fail "$label has the wrong owner"
  [[ "$(stat --format='%g' "$path")" == "$expected_gid" ]] ||
    fail "$label has the wrong group"
  mode="$(stat --format='%a' "$path")"
  ((8#$mode & 0077)) && fail "$label must be owner-only"
}

read_environment_value() {
  local key="$1"
  local count
  local value
  count="$(awk -F= -v key="$key" '$1 == key {count += 1} END {print count + 0}' \
    /etc/melloa/server.env)"
  [[ "$count" == 1 ]] || fail "$key must occur exactly once in the server environment file"
  value="$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print}' \
    /etc/melloa/server.env)"
  [[ -n "$value" && "$value" != *$'\r'* && "$value" != *$'\n'* ]] ||
    fail "$key has an invalid value"
  printf '%s' "$value"
}

read_environment_path() {
  local key="$1"
  local value
  value="$(read_environment_value "$key")"
  [[ "$value" == /* && "$value" != *$'\t'* && "$value" != *' '* && \
    "$value" != */../* && "$value" != */./* && "$value" != */.. && "$value" != */. ]] ||
    fail "$key must be a plain absolute path"
  printf '%s' "$value"
}

read_private_environment_path() {
  local key="$1"
  local value
  value="$(read_environment_path "$key")"
  [[ "$value" == /etc/melloa/private/* ]] ||
    fail "$key must remain below /etc/melloa/private"
  printf '%s' "$value"
}

read_self_change_value() {
  local key="$1"
  local count
  local value
  count="$(awk -F= -v key="$key" '$1 == key {count += 1} END {print count + 0}' \
    /etc/melloa/self-change.env)"
  [[ "$count" == 1 ]] || fail "$key must occur exactly once in the self-change environment file"
  value="$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print}' \
    /etc/melloa/self-change.env)"
  [[ "$value" != *$'\r'* && "$value" != *$'\n'* ]] ||
    fail "$key has an invalid value"
  printf '%s' "$value"
}

require_password_file() {
  local path="$1"
  local label="$2"
  local uid="$3"
  local gid="$4"
  local value
  require_private_file "$path" "$label" 32 "$uid" "$gid"
  value="$(<"$path")"
  [[ "$value" =~ ^[A-Za-z0-9_-]{32,128}$ ]] ||
    fail "$label must contain 32-128 base64url-safe characters"
}

[[ "$(uname -s)" == Linux ]] || fail "the persistent server path requires Linux"
[[ "$SOURCE" == /* && -d "$SOURCE" && ! -L "$SOURCE" ]] || fail "source must be an absolute directory"
[[ "$ORIGIN" == https://* && "$ORIGIN" != *'@'* && "$ORIGIN" != *'?'* && "$ORIGIN" != *'#'* ]] ||
  fail "origin must be a credential-free HTTPS URL"
[[ -f "$SOURCE/pyproject.toml" && -f "$SOURCE/uv.lock" ]] || fail "source checkout is incomplete"
readonly TOOLCHAIN_LOCK="$SOURCE/infra/server/toolchain.lock"
[[ -f "$TOOLCHAIN_LOCK" && ! -L "$TOOLCHAIN_LOCK" ]] || fail "toolchain lock is unavailable"
# shellcheck disable=SC1090
source "$TOOLCHAIN_LOCK"

for command in \
  awk basename bash bwrap chown docker find findmnt getent git grep groupadd head id install \
  flock jq make mktemp node npm python3.13 rm rsync runuser sed sha256sum sort stat sync \
  systemctl systemd-analyze tar timeout uname useradd uv wc; do
  require_command "$command"
done

readonly SYSTEMD_VERSION="$(systemd-analyze --version | awk 'NR == 1 {print $2}')"
[[ "$SYSTEMD_VERSION" =~ ^[0-9]+$ ]] || fail "systemd version could not be determined"
((SYSTEMD_VERSION >= 249)) || fail "systemd 249 or newer is required"

readonly UV_VERSION="$(uv --version | awk 'NR == 1 {print $2}')"
[[ "$UV_VERSION" == "$MELLOA_UV_VERSION" ]] ||
  fail "uv $MELLOA_UV_VERSION is required"
readonly PYTHON_VERSION="$(python3.13 -c 'import platform; print(platform.python_version())')"
version_at_least "$PYTHON_VERSION" 3.13 || fail "Python 3.13 or newer is required"
readonly NODE_VERSION="$(node --version | sed 's/^v//; s/+.*//')"
[[ "$NODE_VERSION" == "$MELLOA_NODE_VERSION" ]] ||
  fail "Node.js $MELLOA_NODE_VERSION is required"
readonly COMPOSE_VERSION="$(docker compose version --short | sed 's/^v//')"
version_at_least "$COMPOSE_VERSION" 2.27.0 || fail "Docker Compose 2.27 or newer is required"

verify_codex_cli() {
  local codex_exec_help
  local codex_help
  local codex_version
  local option
  [[ -x /usr/local/bin/codex ]] || fail "Codex CLI must be installed at /usr/local/bin/codex"
  codex_version="$(/usr/local/bin/codex --version | awk 'NR == 1 {print $2}')"
  [[ "$codex_version" == "$MELLOA_CODEX_CLI_VERSION" ]] ||
    fail "Codex CLI $MELLOA_CODEX_CLI_VERSION is required"

  codex_help="$(/usr/local/bin/codex --help 2>&1)"
  codex_exec_help="$(/usr/local/bin/codex exec --help 2>&1)"
  for option in --sandbox --ask-for-approval --oss --local-provider; do
    grep --fixed-strings --quiet -- "$option" <<<"$codex_help" ||
      fail "Codex CLI does not support required option: $option"
  done
  for option in --ephemeral --ignore-user-config; do
    grep --fixed-strings --quiet -- "$option" <<<"$codex_exec_help" ||
      fail "Codex CLI exec does not support required option: $option"
  done
}

[[ -d "$SOURCE/.git" && ! -L "$SOURCE/.git" ]] || fail "source must be a Git checkout"
[[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=normal)" ]] ||
  fail "source checkout must be clean"
readonly REVISION="$(git -C "$SOURCE" rev-parse HEAD)"
[[ "$REVISION" =~ ^[0-9a-f]{40}$ ]] || fail "source revision is invalid"
[[ "$(git -C "$SOURCE" remote get-url origin)" == "$ORIGIN" ]] ||
  fail "source origin does not match the selected public origin"

if [[ -z "$CA_FILE" && "$INSTALLED" == true && -f /etc/melloa/server.env && \
  ! -L /etc/melloa/server.env ]]; then
  CA_FILE="$(read_environment_path MELLOA_BUILD_CA_FILE)"
fi
if [[ -n "$CA_FILE" ]]; then
  apply_ca_file "$CA_FILE"
fi

readonly REMOTE_REVISION="$(
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 \
    git ls-remote --refs "$ORIGIN" refs/heads/main |
    awk 'NR == 1 && $2 == "refs/heads/main" {print $1}'
)"
[[ "$REMOTE_REVISION" == "$REVISION" ]] || fail "source is not the current remote main revision"

if [[ "$INSTALLED" == false ]]; then
  echo "Server build preflight passed for $REVISION."
  exit 0
fi

((EUID == 0)) || fail "installed-server preflight must run as root"
docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable"
id melloa-codex >/dev/null 2>&1 || fail "melloa-codex system user is unavailable"
id melloa-runtime >/dev/null 2>&1 || fail "melloa-runtime system user is unavailable"
readonly RUNTIME_UID="$(id -u melloa-runtime)"
readonly RUNTIME_GID="$(id -g melloa-runtime)"
[[ "$RUNTIME_UID" == 10001 && "$RUNTIME_GID" == 10001 ]] ||
  fail "melloa-runtime must use UID and GID 10001"

require_private_file /etc/melloa/server.env "server environment file"
require_private_file /etc/melloa/self-change.env "self-change environment file"
require_private_file /etc/melloa/configuration.json "configuration receipt"
require_private_file /etc/melloa/private/database-change-planner-dsn "planner database DSN"
require_private_file /etc/melloa/private/database-change-applier-dsn "applier database DSN"

[[ "$(read_environment_value MELLOA_RUNTIME_UID)" == "$RUNTIME_UID" ]] ||
  fail "MELLOA_RUNTIME_UID does not match melloa-runtime"
[[ "$(read_environment_value MELLOA_RUNTIME_GID)" == "$RUNTIME_GID" ]] ||
  fail "MELLOA_RUNTIME_GID does not match melloa-runtime"
[[ "$(read_environment_value MELLOA_EGRESS_INTERNAL)" == false ]] ||
  fail "MELLOA_EGRESS_INTERNAL must be false for Telegram and hosted model access"

for specification in \
  MELLOA_POSTGRES_ADMIN_PASSWORD_FILE:administrative-database-password \
  MELLOA_POSTGRES_APP_PASSWORD_FILE:application-database-password \
  MELLOA_POSTGRES_MIGRATION_PASSWORD_FILE:migration-database-password \
  MELLOA_POSTGRES_CHANGE_PLANNER_PASSWORD_FILE:planner-database-password \
  MELLOA_POSTGRES_CHANGE_APPLIER_PASSWORD_FILE:applier-database-password; do
  key="${specification%%:*}"
  label="${specification#*:}"
  require_password_file "$(read_private_environment_path "$key")" "$label" 0 0
done
require_password_file \
  "$(read_private_environment_path MELLOA_POSTGRES_BACKUP_PASSWORD_FILE)" \
  "backup database password" "$RUNTIME_UID" "$RUNTIME_GID"
require_private_file \
  "$(read_private_environment_path MELLOA_RESTIC_PASSWORD_FILE)" \
  "restic password" 16 "$RUNTIME_UID" "$RUNTIME_GID"

for specification in \
  MELLOA_DATABASE_APPLICATION_DSN_FILE:application-database-DSN \
  MELLOA_DATABASE_MIGRATION_DSN_FILE:migration-database-DSN \
  MELLOA_OWNER_CREDENTIAL_FILE:owner-credential \
  MELLOA_TELEGRAM_OWNER_CONFIG_FILE:Telegram-owner-config \
  MELLOA_TELEGRAM_BOT_TOKEN_FILE:Telegram-bot-token \
  MELLOA_CAPABLE_MODEL_CONFIG_FILE:capable-model-config \
  MELLOA_ECONOMY_MODEL_CONFIG_FILE:economy-model-config; do
  key="${specification%%:*}"
  label="${specification#*:}"
  require_private_file \
    "$(read_private_environment_path "$key")" "$label" 1 "$RUNTIME_UID" "$RUNTIME_GID"
done

readonly MODEL_CREDENTIALS_DIR="$(read_private_environment_path MELLOA_MODEL_CREDENTIALS_DIR)"
[[ "$MODEL_CREDENTIALS_DIR" == /etc/melloa/private/model-credentials ]] ||
  fail "model credentials must use the installed private directory"
require_private_directory \
  "$MODEL_CREDENTIALS_DIR" "model credentials directory" "$RUNTIME_UID" "$RUNTIME_GID"
while IFS= read -r -d '' credential; do
  require_private_file "$credential" "model credential" 1 "$RUNTIME_UID" "$RUNTIME_GID"
done < <(find "$MODEL_CREDENTIALS_DIR" -mindepth 1 -maxdepth 1 -print0)

readonly RUNTIME_STATE_DIR="$(read_environment_path MELLOA_RUNTIME_STATE_DIR)"
[[ "$RUNTIME_STATE_DIR" == /var/lib/melloa/runtime-state ]] ||
  fail "runtime state must use the installed private directory"
require_private_directory \
  "$RUNTIME_STATE_DIR" "runtime state directory" "$RUNTIME_UID" "$RUNTIME_GID"
readonly BACKUP_REPOSITORY_DIR="$(read_environment_path MELLOA_BACKUP_REPOSITORY_DIR)"
if ! jq -e \
  --arg backup_repository "$BACKUP_REPOSITORY_DIR" '
    .contract_version == "1.0.0" and
    (.source_revision | type == "string" and test("^[0-9a-f]{40}$")) and
    .backup_repository == $backup_repository and
    (.codex_mode == "disabled" or .codex_mode == "api_key" or
      .codex_mode == "ollama" or .codex_mode == "lmstudio") and
    (.configured_at | type == "string" and length > 0)
  ' /etc/melloa/configuration.json >/dev/null; then
  fail "configuration receipt is invalid or names a different backup repository"
fi
require_private_directory \
  "$BACKUP_REPOSITORY_DIR" "backup repository directory" "$RUNTIME_UID" "$RUNTIME_GID"
findmnt --mountpoint "$BACKUP_REPOSITORY_DIR" >/dev/null ||
  fail "backup repository directory must be an explicit mount point"
[[ "$(stat --format='%d' "$BACKUP_REPOSITORY_DIR")" != "$(stat --format='%d' /)" ]] ||
  fail "backup repository must be on storage independent from the server root filesystem"

readonly GUARDIAN_HANDOFF_DIR="$(read_environment_path MELLOA_GUARDIAN_HANDOFF_DIR)"
[[ "$GUARDIAN_HANDOFF_DIR" == /var/lib/melloa/guardian-handoff ]] ||
  fail "Guardian handoff must use the installed read-only directory"
[[ -d "$GUARDIAN_HANDOFF_DIR" && ! -L "$GUARDIAN_HANDOFF_DIR" ]] ||
  fail "Guardian handoff directory is unavailable"
for guardian_file in status.json public.pem; do
  [[ -f "$GUARDIAN_HANDOFF_DIR/$guardian_file" && ! -L "$GUARDIAN_HANDOFF_DIR/$guardian_file" ]] ||
    fail "Guardian handoff $guardian_file is unavailable"
  runuser -u melloa-runtime -- test -r "$GUARDIAN_HANDOFF_DIR/$guardian_file" ||
    fail "Guardian handoff $guardian_file is not readable by melloa-runtime"
done
[[ "$(find "$GUARDIAN_HANDOFF_DIR" -mindepth 1 -maxdepth 1 -printf '.\n' | wc -l)" == 2 ]] ||
  fail "Guardian handoff directory must contain only status.json and public.pem"

readonly BUILD_CA_FILE="$(read_environment_path MELLOA_BUILD_CA_FILE)"
[[ -f "$BUILD_CA_FILE" && ! -L "$BUILD_CA_FILE" && -r "$BUILD_CA_FILE" ]] ||
  fail "build CA bundle must be a readable regular file"

[[ "$(read_private_environment_path MELLOA_DATABASE_CHANGE_PLANNER_DSN_FILE)" == \
  /etc/melloa/private/database-change-planner-dsn ]] ||
  fail "planner DSN must use the systemd credential path"
[[ "$(read_private_environment_path MELLOA_DATABASE_CHANGE_APPLIER_DSN_FILE)" == \
  /etc/melloa/private/database-change-applier-dsn ]] ||
  fail "applier DSN must use the systemd credential path"

readonly RELEASE_STATE_DIR="$(read_environment_path MELLOA_RELEASE_STATE_DIR)"
[[ "$RELEASE_STATE_DIR" == /var/lib/melloa/release-state ]] ||
  fail "release state directory must use the installed protected path"

readonly SELF_CHANGE_ENABLED="$(read_self_change_value MELLOA_SELF_CHANGE_ENABLED)"
[[ "$SELF_CHANGE_ENABLED" == true || "$SELF_CHANGE_ENABLED" == false ]] ||
  fail "MELLOA_SELF_CHANGE_ENABLED must occur once as true or false"
readonly USE_API_KEY="$(read_self_change_value MELLOA_CODEX_USE_API_KEY)"
[[ "$USE_API_KEY" == true || "$USE_API_KEY" == false ]] ||
  fail "MELLOA_CODEX_USE_API_KEY must occur once as true or false"
readonly LOCAL_PROVIDER="$(read_self_change_value MELLOA_CODEX_LOCAL_PROVIDER)"
if [[ "$SELF_CHANGE_ENABLED" == false ]]; then
  [[ "$USE_API_KEY" == false ]] || fail "disabled self-change cannot use an API key"
  [[ -z "$LOCAL_PROVIDER" ]] || fail "disabled self-change cannot select a local provider"
  [[ "$(jq -r .codex_mode /etc/melloa/configuration.json)" == disabled ]] ||
    fail "configuration receipt does not match disabled self-change"
elif [[ "$USE_API_KEY" == true ]]; then
  verify_codex_cli
  require_private_file /etc/melloa/private/git-credentials "Git credential" 20
  require_private_file /etc/melloa/private/codex-api-key "Codex API key" 20
  [[ -z "$LOCAL_PROVIDER" ]] || fail "API-key Codex mode cannot select a local provider"
  [[ "$(jq -r .codex_mode /etc/melloa/configuration.json)" == api_key ]] ||
    fail "configuration receipt does not match Codex API-key mode"
else
  verify_codex_cli
  require_private_file /etc/melloa/private/git-credentials "Git credential" 20
  [[ "$LOCAL_PROVIDER" == ollama || "$LOCAL_PROVIDER" == lmstudio ]] ||
    fail "non-key Codex mode requires ollama or lmstudio"
  [[ "$(jq -r .codex_mode /etc/melloa/configuration.json)" == "$LOCAL_PROVIDER" ]] ||
    fail "configuration receipt does not match the Codex local provider"
fi

for directory in \
  /opt/melloa/worker/.venv \
  /opt/melloa/verifier/.venv \
  /opt/melloa/verifier/node_modules \
  /srv/melloa/planning-source/.git \
  /srv/melloa/release-source/.git \
  /var/lib/melloa/codex-agent/codex \
  /var/lib/melloa/planning-work \
  /var/lib/melloa/applying-work \
  /var/lib/melloa/release-state; do
  [[ -d "$directory" && ! -L "$directory" ]] || fail "installed directory is unavailable: $directory"
done

for unit in \
  melloa-release-recovery.service \
  melloa-self-change-planner.service \
  melloa-self-change-applier.service; do
  [[ -f "/etc/systemd/system/$unit" && ! -L "/etc/systemd/system/$unit" ]] ||
    fail "installed systemd unit is unavailable: $unit"
done
systemd-analyze verify \
  /etc/systemd/system/melloa-release-recovery.service \
  /etc/systemd/system/melloa-self-change-planner.service \
  /etc/systemd/system/melloa-self-change-applier.service >/dev/null

MELLOA_SOURCE_REVISION="$REVISION" \
MELLOA_IMAGE="melloa-local/server:$REVISION" \
MELLOA_BACKUP_IMAGE="melloa-local/backup:$REVISION" \
  docker compose \
    --project-directory "$SOURCE" \
    --env-file /etc/melloa/server.env \
    --file "$SOURCE/compose.server.yaml" \
    config --quiet

runuser -u melloa-codex -- \
  bwrap --die-with-parent --new-session --unshare-all \
    --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp /usr/bin/true ||
  fail "unprivileged Bubblewrap isolation is unavailable"

echo "Installed server preflight passed for $REVISION."
