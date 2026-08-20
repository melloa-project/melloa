#!/usr/bin/env bash
set -euo pipefail
set +x

umask 077

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT"
if [[ ! -f "$SOURCE/pyproject.toml" ]]; then
  SOURCE=/srv/melloa/release-source
fi
DESTINATION_ROOT=/
BACKUP_REPOSITORY=""
GUARDIAN_STATUS_FILE=""
GUARDIAN_PUBLIC_KEY_FILE=""
TELEGRAM_OWNER_ID=""
TELEGRAM_BOT_TOKEN_FILE=""
CAPABLE_MODEL_CONFIG_FILE=""
ECONOMY_MODEL_CONFIG_FILE=""
RESTIC_PASSWORD_FILE=""
GITHUB_TOKEN_FILE=""
CODEX_API_KEY_FILE=""
CODEX_LOCAL_PROVIDER=""
CODEX_MODEL=""
SELF_CHANGE_DISABLED=false
BUILD_CA_FILE=""
declare -a MODEL_CREDENTIAL_SPECS=()

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/configure.sh [--source PATH] [--root PATH]
  --backup-repository PATH
  --guardian-status-file PATH
  --guardian-public-key-file PATH
  --telegram-owner-id NUMERIC_ID
  --telegram-bot-token-file PATH
  --capable-model-config-file PATH
  --economy-model-config-file PATH
  --restic-password-file PATH
  [--model-credential NAME=PATH ...]
  (--self-change-disabled |
    --github-token-file PATH
    (--codex-api-key-file PATH | --codex-local-provider ollama|lmstudio))
  [--codex-model MODEL]
  [--build-ca-file PATH]

Installs a new server's private configuration without starting services. Secret values are read
only from owner-private files; command-line arguments contain paths and non-secret selections.
The independently retained restic password file is copied, never generated or replaced here.
When --build-ca-file is supplied, the public CA bundle is copied into /etc/melloa for future image
builds and update checks; it is not installed as a machine-wide trust root.
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
    --root)
      [[ $# -ge 2 ]] || usage
      DESTINATION_ROOT="$2"
      shift 2
      ;;
    --backup-repository)
      [[ $# -ge 2 ]] || usage
      BACKUP_REPOSITORY="$2"
      shift 2
      ;;
    --guardian-status-file)
      [[ $# -ge 2 ]] || usage
      GUARDIAN_STATUS_FILE="$2"
      shift 2
      ;;
    --guardian-public-key-file)
      [[ $# -ge 2 ]] || usage
      GUARDIAN_PUBLIC_KEY_FILE="$2"
      shift 2
      ;;
    --telegram-owner-id)
      [[ $# -ge 2 ]] || usage
      TELEGRAM_OWNER_ID="$2"
      shift 2
      ;;
    --telegram-bot-token-file)
      [[ $# -ge 2 ]] || usage
      TELEGRAM_BOT_TOKEN_FILE="$2"
      shift 2
      ;;
    --capable-model-config-file)
      [[ $# -ge 2 ]] || usage
      CAPABLE_MODEL_CONFIG_FILE="$2"
      shift 2
      ;;
    --economy-model-config-file)
      [[ $# -ge 2 ]] || usage
      ECONOMY_MODEL_CONFIG_FILE="$2"
      shift 2
      ;;
    --restic-password-file)
      [[ $# -ge 2 ]] || usage
      RESTIC_PASSWORD_FILE="$2"
      shift 2
      ;;
    --self-change-disabled)
      SELF_CHANGE_DISABLED=true
      shift
      ;;
    --github-token-file)
      [[ $# -ge 2 ]] || usage
      GITHUB_TOKEN_FILE="$2"
      shift 2
      ;;
    --model-credential)
      [[ $# -ge 2 ]] || usage
      MODEL_CREDENTIAL_SPECS+=("$2")
      shift 2
      ;;
    --codex-api-key-file)
      [[ $# -ge 2 ]] || usage
      CODEX_API_KEY_FILE="$2"
      shift 2
      ;;
    --codex-local-provider)
      [[ $# -ge 2 ]] || usage
      CODEX_LOCAL_PROVIDER="$2"
      shift 2
      ;;
    --codex-model)
      [[ $# -ge 2 ]] || usage
      CODEX_MODEL="$2"
      shift 2
      ;;
    --build-ca-file)
      [[ $# -ge 2 ]] || usage
      BUILD_CA_FILE="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

fail() {
  echo "Server configuration failed: $1" >&2
  exit 1
}

destination() {
  local path="$1"
  if [[ "$DESTINATION_ROOT" == / ]]; then
    printf '%s' "$path"
  else
    printf '%s%s' "$DESTINATION_ROOT" "$path"
  fi
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

require_source_file() {
  local path="$1"
  local label="$2"
  local minimum="$3"
  local maximum="$4"
  local private="$5"
  local mode
  local permissions
  local size
  [[ "$path" == /* && -f "$path" && ! -L "$path" && -r "$path" ]] ||
    fail "$label must be an absolute readable regular file, not a symlink"
  size="$(stat --format='%s' "$path")"
  ((size >= minimum && size <= maximum)) || fail "$label has an invalid size"
  if [[ "$private" == true ]]; then
    mode="$(stat --format='%a' "$path")"
    permissions=$((8#$mode))
    ((permissions & 0077)) && fail "$label must be owner-only"
    ((permissions & 0400)) || fail "$label must be owner-readable"
  fi
}

read_single_line_secret() {
  local path="$1"
  local label="$2"
  local minimum="$3"
  local maximum="$4"
  local value
  require_source_file "$path" "$label" "$minimum" "$maximum" true
  value="$(<"$path")"
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] ||
    fail "$label must contain exactly one line"
  ((${#value} >= minimum && ${#value} <= maximum)) || fail "$label has an invalid length"
  printf '%s' "$value"
}

validate_telegram_owner_id() {
  local value="$1"
  [[ "$value" =~ ^[1-9][0-9]{0,18}$ ]] || fail "Telegram owner ID must be a positive integer"
  if ((${#value} == 19)); then
    [[ "$value" < 9223372036854775808 ]] || fail "Telegram owner ID is too large"
  fi
}

validate_plain_path() {
  local value="$1"
  local label="$2"
  [[ "$value" == /* && "$value" =~ ^/[A-Za-z0-9_./-]+$ && \
    "$value" != */../* && "$value" != */./* && "$value" != */.. && "$value" != */. ]] ||
    fail "$label must be a plain absolute path"
}

model_target() {
  local path="$1"
  local label="$2"
  require_source_file "$path" "$label" 2 65536 true
  jq -er '
    select(type == "object") |
    [.provider_id, .model_id, .base_url] |
    select(all(.[]; type == "string" and length > 0)) |
    @json
  ' "$path" 2>/dev/null || fail "$label must identify one provider, model, and base URL"
}

model_credential_name() {
  local path="$1"
  local label="$2"
  local credential_path
  credential_path="$(
    jq -er '
      if .authorization_token_file == null then
        ""
      elif has("authorization_token_file") then
        .authorization_token_file | select(type == "string")
      else
        ""
      end
    ' "$path" 2>/dev/null
  )" || fail "$label has an invalid authorization token path"
  if [[ -z "$credential_path" ]]; then
    return 0
  fi
  [[ "$credential_path" =~ ^/run/melloa/model-credentials/([A-Za-z0-9][A-Za-z0-9._-]{0,63})$ ]] ||
    fail "$label authorization token must name one direct model credential"
  printf '%s' "${BASH_REMATCH[1]}"
}

write_private_text() {
  local path="$1"
  local value="$2"
  local mode="$3"
  local uid="$4"
  local gid="$5"
  install -m "$mode" /dev/null "$path"
  printf '%s\n' "$value" >"$path"
  set_owner "$path" "$uid" "$gid"
}

set_owner() {
  local path="$1"
  local uid="$2"
  local gid="$3"
  if [[ "$DESTINATION_ROOT" == / ]]; then
    chown "$uid:$gid" "$path"
  fi
}

install_owned_directory() {
  local path="$1"
  local mode="$2"
  local uid="$3"
  local gid="$4"
  install -d -m "$mode" "$path"
  set_owner "$path" "$uid" "$gid"
}

random_secret() {
  "$PYTHON_EXECUTABLE" -c 'import secrets; print(secrets.token_urlsafe(48))'
}

for command in awk basename chmod chown date find findmnt git id install jq mktemp mv \
  rm stat sync; do
  require_command "$command"
done
PYTHON_EXECUTABLE=python3.13
if [[ "$DESTINATION_ROOT" != / ]]; then
  PYTHON_EXECUTABLE=python3
fi
require_command "$PYTHON_EXECUTABLE"

[[ "$SOURCE" == /* && -d "$SOURCE/.git" && ! -L "$SOURCE" && ! -L "$SOURCE/.git" ]] ||
  fail "source must be an absolute Git checkout"
[[ "$DESTINATION_ROOT" == /* ]] || fail "configuration root must be absolute"
if [[ -e "$DESTINATION_ROOT" && ( ! -d "$DESTINATION_ROOT" || -L "$DESTINATION_ROOT" ) ]]; then
  fail "configuration root must be a directory, not a symlink"
fi
if [[ "$DESTINATION_ROOT" == / ]]; then
  ((EUID == 0)) || fail "server configuration must run as root"
fi

for required in \
  BACKUP_REPOSITORY GUARDIAN_STATUS_FILE GUARDIAN_PUBLIC_KEY_FILE TELEGRAM_OWNER_ID \
  TELEGRAM_BOT_TOKEN_FILE CAPABLE_MODEL_CONFIG_FILE ECONOMY_MODEL_CONFIG_FILE \
  RESTIC_PASSWORD_FILE; do
  [[ -n "${!required}" ]] || usage
done
if [[ "$SELF_CHANGE_DISABLED" == true ]]; then
  [[ -z "$GITHUB_TOKEN_FILE" && -z "$CODEX_API_KEY_FILE" && -z "$CODEX_LOCAL_PROVIDER" && \
    -z "$CODEX_MODEL" ]] ||
    fail "self-change credentials cannot be supplied when self-change is disabled"
else
  [[ -n "$GITHUB_TOKEN_FILE" ]] || usage
  if [[ -n "$CODEX_API_KEY_FILE" && -n "$CODEX_LOCAL_PROVIDER" ]] ||
    [[ -z "$CODEX_API_KEY_FILE" && -z "$CODEX_LOCAL_PROVIDER" ]]; then
    fail "select exactly one Codex API-key or local-provider mode"
  fi
fi
[[ -z "$CODEX_LOCAL_PROVIDER" || "$CODEX_LOCAL_PROVIDER" == ollama || \
  "$CODEX_LOCAL_PROVIDER" == lmstudio ]] || fail "Codex local provider must be ollama or lmstudio"
[[ "$CODEX_MODEL" != *$'\n'* && "$CODEX_MODEL" != *$'\r'* && ${#CODEX_MODEL} -le 128 ]] ||
  fail "Codex model selection is invalid"

validate_plain_path "$BACKUP_REPOSITORY" "backup repository"
validate_telegram_owner_id "$TELEGRAM_OWNER_ID"
require_source_file "$GUARDIAN_STATUS_FILE" "Guardian status" 2 1048576 false
require_source_file "$GUARDIAN_PUBLIC_KEY_FILE" "Guardian public key" 32 65536 false
if [[ -n "$BUILD_CA_FILE" ]]; then
  require_source_file "$BUILD_CA_FILE" "build CA bundle" 32 1048576 false
fi

telegram_token="$(
  read_single_line_secret "$TELEGRAM_BOT_TOKEN_FILE" "Telegram bot token" 37 149
)"
[[ "$telegram_token" =~ ^[0-9]{6,20}:[A-Za-z0-9_-]{30,128}$ ]] ||
  fail "Telegram bot token has an invalid format"

restic_password="$(
  read_single_line_secret "$RESTIC_PASSWORD_FILE" "restic recovery password" 32 128
)"
[[ "$restic_password" =~ ^[A-Za-z0-9_-]{32,128}$ ]] ||
  fail "restic recovery password must contain 32-128 base64url-safe characters"

github_token=""
if [[ "$SELF_CHANGE_DISABLED" == false ]]; then
  github_token="$(read_single_line_secret "$GITHUB_TOKEN_FILE" "GitHub token" 20 255)"
  [[ "$github_token" =~ ^[A-Za-z0-9_]+$ ]] || fail "GitHub token has an invalid format"
fi

codex_api_key=""
if [[ "$SELF_CHANGE_DISABLED" == false && -n "$CODEX_API_KEY_FILE" ]]; then
  codex_api_key="$(read_single_line_secret "$CODEX_API_KEY_FILE" "Codex API key" 20 4096)"
  [[ "$codex_api_key" =~ ^[A-Za-z0-9._-]{20,4096}$ ]] ||
    fail "Codex API key has an invalid format"
fi

declare -A MODEL_CREDENTIAL_SOURCES=()
declare -A MODEL_CREDENTIAL_VALUES=()
declare -A USED_MODEL_CREDENTIALS=()
for specification in "${MODEL_CREDENTIAL_SPECS[@]}"; do
  [[ "$specification" == *=* ]] || fail "model credential must use NAME=PATH"
  name="${specification%%=*}"
  path="${specification#*=}"
  [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ && -n "$path" ]] ||
    fail "model credential name is invalid"
  [[ -z "${MODEL_CREDENTIAL_SOURCES[$name]+configured}" ]] ||
    fail "model credential name is duplicated: $name"
  value="$(read_single_line_secret "$path" "model credential $name" 1 4096)"
  [[ "$value" != *[[:space:]]* ]] || fail "model credential $name contains whitespace"
  MODEL_CREDENTIAL_SOURCES[$name]="$path"
  MODEL_CREDENTIAL_VALUES[$name]="$value"
done

capable_target="$(model_target "$CAPABLE_MODEL_CONFIG_FILE" "capable model config")"
economy_target="$(model_target "$ECONOMY_MODEL_CONFIG_FILE" "economy model config")"
[[ "$capable_target" != "$economy_target" ]] || fail "capable and economy model targets must differ"
for route_and_path in \
  "capable:$CAPABLE_MODEL_CONFIG_FILE" \
  "economy:$ECONOMY_MODEL_CONFIG_FILE"; do
  route="${route_and_path%%:*}"
  config_path="${route_and_path#*:}"
  credential_name="$(model_credential_name "$config_path" "$route model config")"
  if [[ -n "$credential_name" ]]; then
    [[ -n "${MODEL_CREDENTIAL_SOURCES[$credential_name]+configured}" ]] ||
      fail "$route model credential was not supplied: $credential_name"
    USED_MODEL_CREDENTIALS[$credential_name]=true
  fi
done
for name in "${!MODEL_CREDENTIAL_SOURCES[@]}"; do
  [[ -n "${USED_MODEL_CREDENTIALS[$name]+used}" ]] ||
    fail "model credential is not referenced by either route: $name"
done

readonly CONFIG_DIR="$(destination /etc/melloa)"
readonly PRIVATE_DIR="$CONFIG_DIR/private"
readonly SERVER_ENV="$CONFIG_DIR/server.env"
readonly SELF_CHANGE_ENV="$CONFIG_DIR/self-change.env"
readonly CONFIGURATION_MARKER="$CONFIG_DIR/configuration.json"
readonly GUARDIAN_PARENT="$(destination /var/lib/melloa)"
readonly GUARDIAN_DIR="$GUARDIAN_PARENT/guardian-handoff"
readonly RELEASE_STATE_DIR="$GUARDIAN_PARENT/release-state"

[[ -d "$CONFIG_DIR" && ! -L "$CONFIG_DIR" ]] || fail "server assets are not installed"
for installed_file in "$SERVER_ENV" "$SELF_CHANGE_ENV"; do
  [[ -f "$installed_file" && ! -L "$installed_file" ]] ||
    fail "installed configuration template is unavailable: $installed_file"
done
if [[ -n "$BUILD_CA_FILE" && ( -e "$CONFIG_DIR/build-ca.pem" || -L "$CONFIG_DIR/build-ca.pem" ) ]]; then
  fail "build CA bundle is already installed; use a reviewed credential-rotation procedure"
fi
[[ -d "$PRIVATE_DIR" && ! -L "$PRIVATE_DIR" ]] || fail "installed private directory is unavailable"
[[ ! -e "$CONFIGURATION_MARKER" && ! -L "$CONFIGURATION_MARKER" ]] ||
  fail "server is already configured; use a reviewed credential-rotation procedure"

while IFS= read -r -d '' existing; do
  case "$(basename "$existing")" in
    codex-api-key|git-credentials)
      [[ -f "$existing" && ! -L "$existing" && ! -s "$existing" ]] ||
        fail "installed private skeleton was modified: $existing"
      ;;
    model-credentials)
      [[ -d "$existing" && ! -L "$existing" ]] ||
        fail "installed model credential path is invalid"
      [[ -z "$(find "$existing" -mindepth 1 -print -quit)" ]] ||
        fail "installed model credential directory is not empty"
      ;;
    *)
      fail "untracked private configuration already exists: $existing"
      ;;
  esac
done < <(find "$PRIVATE_DIR" -mindepth 1 -maxdepth 1 -print0)

if [[ "$DESTINATION_ROOT" == / ]]; then
  id melloa-runtime >/dev/null 2>&1 || fail "melloa-runtime system user is unavailable"
  [[ "$(id -u melloa-runtime)" == 10001 && "$(id -g melloa-runtime)" == 10001 ]] ||
    fail "melloa-runtime must use UID and GID 10001"
  [[ -d "$BACKUP_REPOSITORY" && ! -L "$BACKUP_REPOSITORY" ]] ||
    fail "backup repository mount is unavailable"
  findmnt --mountpoint "$BACKUP_REPOSITORY" >/dev/null ||
    fail "backup repository must be an explicit mount point"
  [[ "$(stat --format='%d' "$BACKUP_REPOSITORY")" != "$(stat --format='%d' /)" ]] ||
    fail "backup repository must use storage independent from the server root filesystem"
  if [[ -e "$RELEASE_STATE_DIR/release.json" ]]; then
    fail "an activated deployment cannot be reconfigured by the first-install tool"
  fi
fi

readonly RUNTIME_UID=10001
readonly RUNTIME_GID=10001
readonly REVISION="$(git -C "$SOURCE" rev-parse HEAD)"
[[ "$REVISION" =~ ^[0-9a-f]{40}$ ]] || fail "source revision is invalid"

STAGE="$(mktemp -d "$CONFIG_DIR/.configuration.XXXXXX")"
GUARDIAN_STAGE=""
PRIVATE_SWAPPED=false
GUARDIAN_SWAPPED=false
SERVER_ENV_SWAPPED=false
SELF_CHANGE_ENV_SWAPPED=false
BUILD_CA_INSTALLED=false
MARKER_INSTALLED=false
COMMITTED=false

cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  set +e
  if [[ "$COMMITTED" != true ]]; then
    if [[ "$MARKER_INSTALLED" == true ]]; then
      rm -f -- "$CONFIGURATION_MARKER"
    fi
    if [[ "$SELF_CHANGE_ENV_SWAPPED" == true && -f "$STAGE/self-change.env.original" ]]; then
      mv -f -- "$STAGE/self-change.env.original" "$SELF_CHANGE_ENV"
    fi
    if [[ "$SERVER_ENV_SWAPPED" == true && -f "$STAGE/server.env.original" ]]; then
      mv -f -- "$STAGE/server.env.original" "$SERVER_ENV"
    fi
    if [[ "$GUARDIAN_SWAPPED" == true && -d "$GUARDIAN_STAGE/original" ]]; then
      if [[ -e "$GUARDIAN_DIR" || -L "$GUARDIAN_DIR" ]]; then
        mv -- "$GUARDIAN_DIR" "$GUARDIAN_STAGE/failed"
      fi
      mv -- "$GUARDIAN_STAGE/original" "$GUARDIAN_DIR"
    fi
    if [[ "$BUILD_CA_INSTALLED" == true ]]; then
      rm -f -- "$CONFIG_DIR/build-ca.pem"
    fi
    if [[ "$PRIVATE_SWAPPED" == true && -d "$STAGE/private.original" ]]; then
      if [[ -e "$PRIVATE_DIR" || -L "$PRIVATE_DIR" ]]; then
        mv -- "$PRIVATE_DIR" "$STAGE/private.failed"
      fi
      mv -- "$STAGE/private.original" "$PRIVATE_DIR"
    fi
  fi
  if [[ "$STAGE" == "$CONFIG_DIR"/.configuration.* && -d "$STAGE" ]]; then
    rm -rf -- "$STAGE"
  fi
  if [[ -n "$GUARDIAN_STAGE" && "$GUARDIAN_STAGE" == "$GUARDIAN_PARENT"/.configuration-guardian.* && \
    -d "$GUARDIAN_STAGE" ]]; then
    rm -rf -- "$GUARDIAN_STAGE"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

install_owned_directory "$STAGE/private" 0700 0 0
install_owned_directory "$STAGE/private/model-credentials" \
  0700 "$RUNTIME_UID" "$RUNTIME_GID"

admin_password="$(random_secret)"
app_password="$(random_secret)"
migration_password="$(random_secret)"
backup_password="$(random_secret)"
planner_password="$(random_secret)"
applier_password="$(random_secret)"
owner_credential="$(random_secret)"

write_private_text "$STAGE/private/postgres-admin-password" "$admin_password" 0600 0 0
write_private_text "$STAGE/private/postgres-app-password" "$app_password" 0600 0 0
write_private_text "$STAGE/private/postgres-migration-password" "$migration_password" 0600 0 0
write_private_text "$STAGE/private/postgres-backup-password" \
  "$backup_password" 0600 "$RUNTIME_UID" "$RUNTIME_GID"
write_private_text "$STAGE/private/postgres-change-planner-password" \
  "$planner_password" 0600 0 0
write_private_text "$STAGE/private/postgres-change-applier-password" \
  "$applier_password" 0600 0 0
write_private_text "$STAGE/private/restic-password" \
  "$restic_password" 0600 "$RUNTIME_UID" "$RUNTIME_GID"
write_private_text "$STAGE/private/owner-credential" \
  "$owner_credential" 0600 "$RUNTIME_UID" "$RUNTIME_GID"

readonly DATABASE_ADDRESS=172.30.37.2
write_private_text "$STAGE/private/database-application-dsn" \
  "host=$DATABASE_ADDRESS port=5432 dbname=melloa user=melloa_app password=$app_password" \
  0600 "$RUNTIME_UID" "$RUNTIME_GID"
write_private_text "$STAGE/private/database-migration-dsn" \
  "host=$DATABASE_ADDRESS port=5432 dbname=melloa user=melloa_migrator password=$migration_password" \
  0600 "$RUNTIME_UID" "$RUNTIME_GID"
write_private_text "$STAGE/private/database-change-planner-dsn" \
  "host=$DATABASE_ADDRESS port=5432 dbname=melloa user=melloa_change_planner_login password=$planner_password" \
  0600 0 0
write_private_text "$STAGE/private/database-change-applier-dsn" \
  "host=$DATABASE_ADDRESS port=5432 dbname=melloa user=melloa_change_applier_login password=$applier_password" \
  0600 0 0

printf '{"owner_user_id":%s,"owner_chat_id":%s,"poll_timeout_seconds":20}\n' \
  "$TELEGRAM_OWNER_ID" "$TELEGRAM_OWNER_ID" >"$STAGE/private/telegram-owner.json"
chmod 0600 "$STAGE/private/telegram-owner.json"
set_owner "$STAGE/private/telegram-owner.json" "$RUNTIME_UID" "$RUNTIME_GID"
write_private_text "$STAGE/private/telegram-bot-token" \
  "$telegram_token" 0600 "$RUNTIME_UID" "$RUNTIME_GID"

install -m 0600 "$CAPABLE_MODEL_CONFIG_FILE" "$STAGE/private/capable-model.json"
install -m 0600 "$ECONOMY_MODEL_CONFIG_FILE" "$STAGE/private/economy-model.json"
set_owner "$STAGE/private/capable-model.json" "$RUNTIME_UID" "$RUNTIME_GID"
set_owner "$STAGE/private/economy-model.json" "$RUNTIME_UID" "$RUNTIME_GID"
for name in "${!MODEL_CREDENTIAL_SOURCES[@]}"; do
  write_private_text "$STAGE/private/model-credentials/$name" \
    "${MODEL_CREDENTIAL_VALUES[$name]}" 0600 "$RUNTIME_UID" "$RUNTIME_GID"
done
build_ca_runtime_file=/etc/ssl/certs/ca-certificates.crt
if [[ -n "$BUILD_CA_FILE" ]]; then
  build_ca_runtime_file=/etc/melloa/build-ca.pem
  install -m 0644 "$BUILD_CA_FILE" "$STAGE/build-ca.pem"
  set_owner "$STAGE/build-ca.pem" 0 0
fi

if [[ "$SELF_CHANGE_DISABLED" == false ]]; then
  write_private_text "$STAGE/private/git-credentials" \
    "https://x-access-token:$github_token@github.com" 0600 0 0
  write_private_text "$STAGE/private/codex-api-key" "$codex_api_key" 0600 0 0
else
  write_private_text "$STAGE/private/git-credentials" "" 0600 0 0
  write_private_text "$STAGE/private/codex-api-key" "" 0600 0 0
fi

unset admin_password app_password migration_password backup_password planner_password
unset applier_password owner_credential telegram_token restic_password github_token codex_api_key
for name in "${!MODEL_CREDENTIAL_VALUES[@]}"; do
  unset 'MODEL_CREDENTIAL_VALUES[$name]'
done

awk -F= -v revision="$REVISION" -v repository="$BACKUP_REPOSITORY" \
  -v build_ca="$build_ca_runtime_file" '
  BEGIN { image = backup_image = source = backup_repository = build_ca_count = 0 }
  $1 == "MELLOA_IMAGE" { print "MELLOA_IMAGE=melloa-local/server:" revision; image += 1; next }
  $1 == "MELLOA_BACKUP_IMAGE" {
    print "MELLOA_BACKUP_IMAGE=melloa-local/backup:" revision; backup_image += 1; next
  }
  $1 == "MELLOA_SOURCE_REVISION" {
    print "MELLOA_SOURCE_REVISION=" revision; source += 1; next
  }
  $1 == "MELLOA_BACKUP_REPOSITORY_DIR" {
    print "MELLOA_BACKUP_REPOSITORY_DIR=" repository; backup_repository += 1; next
  }
  $1 == "MELLOA_BUILD_CA_FILE" {
    print "MELLOA_BUILD_CA_FILE=" build_ca; build_ca_count += 1; next
  }
  { print }
  END {
    if (image != 1 || backup_image != 1 || source != 1 || backup_repository != 1 ||
        build_ca_count != 1) exit 1
  }
' "$SOURCE/infra/server/server.env.example" >"$STAGE/server.env"
chmod 0600 "$STAGE/server.env"
set_owner "$STAGE/server.env" 0 0

if [[ "$SELF_CHANGE_DISABLED" == true ]]; then
  printf 'MELLOA_SELF_CHANGE_ENABLED=false\nMELLOA_CODEX_USE_API_KEY=false\nMELLOA_CODEX_MODEL=\nMELLOA_CODEX_LOCAL_PROVIDER=\n' \
    >"$STAGE/self-change.env"
  codex_mode=disabled
elif [[ -n "$CODEX_API_KEY_FILE" ]]; then
  printf 'MELLOA_SELF_CHANGE_ENABLED=true\nMELLOA_CODEX_USE_API_KEY=true\nMELLOA_CODEX_MODEL=%s\nMELLOA_CODEX_LOCAL_PROVIDER=\n' \
    "$CODEX_MODEL" >"$STAGE/self-change.env"
  codex_mode=api_key
else
  printf 'MELLOA_SELF_CHANGE_ENABLED=true\nMELLOA_CODEX_USE_API_KEY=false\nMELLOA_CODEX_MODEL=%s\nMELLOA_CODEX_LOCAL_PROVIDER=%s\n' \
    "$CODEX_MODEL" "$CODEX_LOCAL_PROVIDER" >"$STAGE/self-change.env"
  codex_mode="$CODEX_LOCAL_PROVIDER"
fi
chmod 0600 "$STAGE/self-change.env"
set_owner "$STAGE/self-change.env" 0 0

jq -n \
  --arg revision "$REVISION" \
  --arg backup_repository "$BACKUP_REPOSITORY" \
  --arg codex_mode "$codex_mode" \
  --arg configured_at "$(date --utc '+%Y-%m-%dT%H:%M:%SZ')" \
  '{contract_version: "1.0.0", source_revision: $revision,
    backup_repository: $backup_repository, codex_mode: $codex_mode,
    configured_at: $configured_at}' >"$STAGE/configuration.json"
chmod 0600 "$STAGE/configuration.json"
set_owner "$STAGE/configuration.json" 0 0

install -m 0600 "$SERVER_ENV" "$STAGE/server.env.original"
install -m 0600 "$SELF_CHANGE_ENV" "$STAGE/self-change.env.original"
set_owner "$STAGE/server.env.original" 0 0
set_owner "$STAGE/self-change.env.original" 0 0

install -d -m 0755 "$GUARDIAN_PARENT"
GUARDIAN_STAGE="$(mktemp -d "$GUARDIAN_PARENT/.configuration-guardian.XXXXXX")"
install_owned_directory "$GUARDIAN_STAGE/new" 0700 "$RUNTIME_UID" "$RUNTIME_GID"
install -m 0400 "$GUARDIAN_STATUS_FILE" "$GUARDIAN_STAGE/new/status.json"
install -m 0400 "$GUARDIAN_PUBLIC_KEY_FILE" "$GUARDIAN_STAGE/new/public.pem"
set_owner "$GUARDIAN_STAGE/new/status.json" "$RUNTIME_UID" "$RUNTIME_GID"
set_owner "$GUARDIAN_STAGE/new/public.pem" "$RUNTIME_UID" "$RUNTIME_GID"

if [[ ! -d "$GUARDIAN_DIR" ]]; then
  install_owned_directory "$GUARDIAN_DIR" 0700 "$RUNTIME_UID" "$RUNTIME_GID"
fi
[[ ! -L "$GUARDIAN_DIR" && -z "$(find "$GUARDIAN_DIR" -mindepth 1 -print -quit)" ]] ||
  fail "Guardian handoff target is not an empty installed directory"

mv -- "$PRIVATE_DIR" "$STAGE/private.original"
PRIVATE_SWAPPED=true
mv -- "$STAGE/private" "$PRIVATE_DIR"
mv -- "$GUARDIAN_DIR" "$GUARDIAN_STAGE/original"
GUARDIAN_SWAPPED=true
mv -- "$GUARDIAN_STAGE/new" "$GUARDIAN_DIR"
if [[ -f "$STAGE/build-ca.pem" ]]; then
  mv -- "$STAGE/build-ca.pem" "$CONFIG_DIR/build-ca.pem"
  BUILD_CA_INSTALLED=true
fi
mv -f -- "$STAGE/server.env" "$SERVER_ENV"
SERVER_ENV_SWAPPED=true
mv -f -- "$STAGE/self-change.env" "$SELF_CHANGE_ENV"
SELF_CHANGE_ENV_SWAPPED=true
mv -- "$STAGE/configuration.json" "$CONFIGURATION_MARKER"
MARKER_INSTALLED=true

sync -f "$SERVER_ENV"
sync -f "$SELF_CHANGE_ENV"
if [[ "$BUILD_CA_INSTALLED" == true ]]; then
  sync -f "$CONFIG_DIR/build-ca.pem"
fi
sync -f "$CONFIGURATION_MARKER"
sync -f "$CONFIG_DIR"
sync -f "$GUARDIAN_DIR"
sync -f "$GUARDIAN_PARENT"

if [[ "$DESTINATION_ROOT" == / ]]; then
  chown "$RUNTIME_UID:$RUNTIME_GID" "$BACKUP_REPOSITORY"
  chmod 0700 "$BACKUP_REPOSITORY"
fi

COMMITTED=true
echo "Private server configuration installed for revision $REVISION; no service was started."
echo "Keep the source restic password outside this server and its backup repository."
