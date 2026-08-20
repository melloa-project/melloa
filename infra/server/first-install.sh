#!/usr/bin/env bash
set -euo pipefail
set +x

umask 077

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT"
ORIGIN="https://github.com/melloa-project/melloa.git"
DESTINATION_ROOT=/
SKIP_ACTIVATION=false
SKIP_VERIFICATION=false
STAGE=""
CA_FILE=""

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/first-install.sh [--source PATH] [--origin HTTPS_URL] [--ca-file PATH]
                                     [--root PATH] [--skip-activation]
                                     [--skip-verification]

Runs the reviewed first-owner server setup:
  1. install immutable host assets;
  2. collect private deployment values without printing secrets;
  3. generate model route JSON and secret files;
  4. pair the dedicated Telegram bot unless an owner ID is supplied by test input;
  5. install private configuration; and
  6. defer or configure optional self-change workers;
  7. activate the server unless --skip-activation is selected; and
  8. verify the first Telegram conversation unless --skip-verification is selected.

Secret values are accepted only through prompts in normal use. Environment answers exist to test
the setup path against a staging root and are not documented as an owner secret-passing interface.
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
    --root)
      [[ $# -ge 2 ]] || usage
      DESTINATION_ROOT="$2"
      SKIP_ACTIVATION=true
      shift 2
      ;;
    --skip-activation)
      SKIP_ACTIVATION=true
      shift
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
  echo "First owner setup failed: $1" >&2
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

cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  if [[ "$STAGE" == /tmp/melloa-first-install.* && -d "$STAGE" ]]; then
    rm -rf -- "$STAGE"
  fi
  if [[ "$STAGE" == /root/melloa-first-install.* && -d "$STAGE" ]]; then
    rm -rf -- "$STAGE"
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

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

env_answer() {
  local name="$1"
  if [[ -n "${!name+x}" ]]; then
    printf '%s' "${!name}"
    return 0
  fi
  return 1
}

prompt_text() {
  local name="$1"
  local prompt="$2"
  local default="${3:-}"
  local value
  if [[ -n "${!name+x}" ]]; then
    value="${!name}"
    [[ -n "$value" ]] || fail "$name cannot be empty"
    printf '%s' "$value"
    return 0
  fi
  if [[ ! -t 0 ]]; then
    [[ -n "$default" ]] || fail "$name is required when setup is not running interactively"
    printf '%s' "$default"
    return 0
  fi
  if [[ -n "$default" ]]; then
    printf '%s [%s]: ' "$prompt" "$default" >&2
    IFS= read -r value
    value="${value:-$default}"
  else
    printf '%s: ' "$prompt" >&2
    IFS= read -r value
  fi
  [[ -n "$value" ]] || fail "$prompt is required"
  printf '%s' "$value"
}

prompt_optional_text() {
  local name="$1"
  local prompt="$2"
  local default="${3:-}"
  local value
  if env_answer "$name"; then
    return 0
  fi
  [[ -t 0 ]] || {
    printf '%s' "$default"
    return 0
  }
  if [[ -n "$default" ]]; then
    printf '%s [%s]: ' "$prompt" "$default" >&2
  else
    printf '%s: ' "$prompt" >&2
  fi
  IFS= read -r value
  printf '%s' "${value:-$default}"
}

prompt_secret() {
  local name="$1"
  local prompt="$2"
  local value
  if [[ -n "${!name+x}" ]]; then
    value="${!name}"
    [[ -n "$value" ]] || fail "$name cannot be empty"
    printf '%s' "$value"
    return 0
  fi
  [[ -t 0 ]] || fail "$name is required when setup is not running interactively"
  printf '%s: ' "$prompt" >&2
  IFS= read -r -s value
  printf '\n' >&2
  [[ -n "$value" ]] || fail "$prompt is required"
  printf '%s' "$value"
}

validate_decimal() {
  local value="$1"
  local label="$2"
  [[ "$value" =~ ^[0-9]+([.][0-9]+)?$ ]] || fail "$label must be a non-negative decimal"
}

validate_integer() {
  local value="$1"
  local label="$2"
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || fail "$label must be a positive integer"
}

validate_bounded_integer() {
  local value="$1"
  local label="$2"
  local maximum="$3"
  validate_integer "$value" "$label"
  ((value <= maximum)) || fail "$label must be at most $maximum"
}

validate_plain_absolute_path() {
  local value="$1"
  local label="$2"
  [[ "$value" == /* && "$value" =~ ^/[A-Za-z0-9_./-]+$ && \
    "$value" != */../* && "$value" != */./* && "$value" != */.. && "$value" != */. ]] ||
    fail "$label must be a plain absolute path"
}

require_public_input_file() {
  local path="$1"
  local label="$2"
  local minimum_size="$3"
  local maximum_size="$4"
  local size
  [[ "$path" == /* && -f "$path" && ! -L "$path" && -r "$path" ]] ||
    fail "$label must be an absolute readable regular file, not a symlink"
  size="$(stat --format='%s' "$path")"
  ((size >= minimum_size && size <= maximum_size)) ||
    fail "$label has an invalid size"
}

validate_public_setup_inputs() {
  validate_plain_absolute_path "$backup_repository" "backup repository"
  require_public_input_file "$guardian_status_file" \
    "Guardian public status.json" 2 1048576
  require_public_input_file "$guardian_public_key_file" \
    "Guardian public.pem" 32 65536
  if [[ "$DESTINATION_ROOT" != / ]]; then
    return 0
  fi
  [[ -d "$backup_repository" && ! -L "$backup_repository" ]] ||
    fail "backup repository mount is unavailable; mount off-device storage at $backup_repository and rerun setup"
  findmnt --mountpoint "$backup_repository" >/dev/null ||
    fail "backup repository must be an explicit mount point; mount off-device storage at $backup_repository and rerun setup"
  [[ "$(stat --format='%d' "$backup_repository")" != "$(stat --format='%d' /)" ]] ||
    fail "backup repository must use storage independent from the server root filesystem"
}

validate_telegram_bot_token() {
  local value="$1"
  [[ "$value" =~ ^[0-9]{6,20}:[A-Za-z0-9_-]{30,128}$ ]] ||
    fail "Telegram bot token has an invalid format"
}

validate_telegram_owner_id() {
  local value="$1"
  [[ "$value" =~ ^[1-9][0-9]{0,18}$ ]] || fail "Telegram owner ID must be a positive integer"
  if ((${#value} == 19)); then
    [[ "$value" < 9223372036854775808 ]] || fail "Telegram owner ID is too large"
  fi
}

validate_model_token() {
  local value="$1"
  local label="$2"
  ((${#value} >= 1 && ${#value} <= 4096)) || fail "$label has an invalid length"
  [[ "$value" != *[[:space:]]* ]] || fail "$label must not contain whitespace"
}

validate_restic_password() {
  local value="$1"
  [[ "$value" =~ ^[A-Za-z0-9_-]{32,128}$ ]] ||
    fail "restic recovery password must contain 32-128 base64url-safe characters"
}

validate_github_token() {
  local value="$1"
  ((${#value} >= 20 && ${#value} <= 255)) || fail "GitHub token has an invalid length"
  [[ "$value" =~ ^[A-Za-z0-9_]+$ ]] || fail "GitHub token has an invalid format"
}

validate_codex_api_key() {
  local value="$1"
  ((${#value} >= 20 && ${#value} <= 4096)) || fail "Codex API key has an invalid length"
  [[ "$value" =~ ^[A-Za-z0-9._-]+$ ]] || fail "Codex API key has an invalid format"
}

validate_codex_model() {
  local value="$1"
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* && ${#value} -le 128 ]] ||
    fail "Codex model selection is invalid"
}

validate_display_name() {
  local value="$1"
  local label="$2"
  [[ -n "$value" && "$value" != *$'\n'* && "$value" != *$'\r'* && ${#value} -le 128 ]] ||
    fail "$label must be 1-128 characters"
}

validate_provider_id() {
  local value="$1"
  local label="$2"
  [[ "$value" =~ ^[a-z][a-z0-9_.-]{1,127}$ ]] ||
    fail "$label must be a lowercase provider ID such as provider.owner-capable"
}

validate_model_id() {
  local value="$1"
  local label="$2"
  [[ -n "$value" && "$value" != *$'\n'* && "$value" != *$'\r'* && ${#value} -le 256 ]] ||
    fail "$label must be 1-256 characters"
}

validate_model_base_url() {
  local value="$1"
  local label="$2"
  local location="$3"
  [[ -n "$value" && ${#value} -le 2048 && "$value" != *[[:space:]]* ]] ||
    fail "$label must be a non-empty HTTP base URL without whitespace"
  [[ "$value" != *'@'* && "$value" != *'?'* && "$value" != *'#'* ]] ||
    fail "$label cannot contain credentials, query, or fragment"
  case "$location" in
    approved_provider)
      [[ "$value" == https://* && "$value" != https:// && "$value" != https:///* ]] ||
        fail "$label for an approved provider must use HTTPS with a host"
      ;;
    *)
      fail "$label has an unsupported processing location"
      ;;
  esac
}

write_private_text() {
  local path="$1"
  local value="$2"
  install -m 0600 /dev/null "$path"
  printf '%s\n' "$value" >"$path"
}

route_environment_name() {
  local route="$1"
  local suffix="$2"
  local uppercase
  uppercase="$(printf '%s' "$route" | tr '[:lower:]' '[:upper:]')"
  printf 'MELLOA_SETUP_%s_%s' "$uppercase" "$suffix"
}

write_model_route() {
  local route="$1"
  local output="$2"
  local kind
  local display_name
  local provider_id
  local model_id
  local base_url
  local api_style
  local processing_location
  local max_input_tokens
  local max_output_tokens
  local estimated_max_cost_gbp
  local input_cost_gbp_per_million_tokens
  local output_cost_gbp_per_million_tokens
  local timeout_ms
  local health_timeout_ms
  local authorization_token_file=""
  local credential_name=""
  local token_label=""
  local token_prompt=""
  local token
  local allowed_sensitivities

  kind="$(
    prompt_text "$(route_environment_name "$route" ROUTE_KIND)" \
      "$route model route preset (openai or external)" \
      openai
  )"
  case "$kind" in
    openai)
      display_name="OpenAI $route model"
      provider_id="provider.openai-$route"
      model_id="$(
        prompt_text "$(route_environment_name "$route" MODEL_ID)" \
          "$route OpenAI model ID"
      )"
      validate_model_id "$model_id" "$route OpenAI model ID"
      base_url="https://api.openai.com/v1"
      validate_model_base_url "$base_url" "$route OpenAI base URL" approved_provider
      api_style=responses
      processing_location=approved_provider
      allowed_sensitivities='["public","internal","personal"]'
      credential_name="$route-token"
      authorization_token_file="/run/melloa/model-credentials/$credential_name"
      token_label="$route OpenAI API key"
      token_prompt="$route OpenAI API key"
      estimated_max_cost_gbp="$(
        prompt_text "$(route_environment_name "$route" ESTIMATED_MAX_COST_GBP)" \
          "$route maximum GBP cost per request"
      )"
      validate_decimal "$estimated_max_cost_gbp" "$route maximum GBP cost"
      input_cost_gbp_per_million_tokens="$(
        prompt_text "$(route_environment_name "$route" INPUT_COST_GBP_PER_MILLION_TOKENS)" \
          "$route input GBP per million tokens"
      )"
      validate_decimal \
        "$input_cost_gbp_per_million_tokens" \
        "$route input GBP per million tokens"
      output_cost_gbp_per_million_tokens="$(
        prompt_text "$(route_environment_name "$route" OUTPUT_COST_GBP_PER_MILLION_TOKENS)" \
          "$route output GBP per million tokens"
      )"
      validate_decimal \
        "$output_cost_gbp_per_million_tokens" \
        "$route output GBP per million tokens"
      ;;
    external)
      display_name="$(
        prompt_text "$(route_environment_name "$route" DISPLAY_NAME)" \
          "$route model display name" \
          "Owner-selected $route model"
      )"
      validate_display_name "$display_name" "$route model display name"
      provider_id="$(
        prompt_text "$(route_environment_name "$route" PROVIDER_ID)" \
          "$route model provider ID" \
          "provider.owner-$route"
      )"
      validate_provider_id "$provider_id" "$route model provider ID"
      model_id="$(
        prompt_text "$(route_environment_name "$route" MODEL_ID)" \
          "$route model ID"
      )"
      validate_model_id "$model_id" "$route model ID"
      base_url="$(
        prompt_text "$(route_environment_name "$route" BASE_URL)" \
          "$route model OpenAI-compatible base URL" \
          "https://api.openai.com/v1"
      )"
      validate_model_base_url "$base_url" "$route model base URL" approved_provider
      api_style="$(
        prompt_text "$(route_environment_name "$route" API_STYLE)" \
          "$route model API style (responses or chat_completions)" \
          responses
      )"
      [[ "$api_style" == responses || "$api_style" == chat_completions ]] ||
        fail "$route model API style must be responses or chat_completions"
      processing_location=approved_provider
      allowed_sensitivities='["public","internal","personal"]'
      credential_name="$route-token"
      authorization_token_file="/run/melloa/model-credentials/$credential_name"
      token_label="$route model bearer token"
      token_prompt="$route model bearer token"
      estimated_max_cost_gbp="$(
        prompt_text "$(route_environment_name "$route" ESTIMATED_MAX_COST_GBP)" \
          "$route maximum GBP cost per request"
      )"
      validate_decimal "$estimated_max_cost_gbp" "$route maximum GBP cost"
      input_cost_gbp_per_million_tokens="$(
        prompt_text "$(route_environment_name "$route" INPUT_COST_GBP_PER_MILLION_TOKENS)" \
          "$route input GBP per million tokens"
      )"
      validate_decimal \
        "$input_cost_gbp_per_million_tokens" \
        "$route input GBP per million tokens"
      output_cost_gbp_per_million_tokens="$(
        prompt_text "$(route_environment_name "$route" OUTPUT_COST_GBP_PER_MILLION_TOKENS)" \
          "$route output GBP per million tokens"
      )"
      validate_decimal \
        "$output_cost_gbp_per_million_tokens" \
        "$route output GBP per million tokens"
      ;;
    *)
      fail "$route model route preset must be openai or external"
      ;;
  esac

  max_input_tokens="$(
    prompt_text "$(route_environment_name "$route" MAX_INPUT_TOKENS)" \
      "$route model max input tokens" \
      16384
  )"
  max_output_tokens="$(
    prompt_text "$(route_environment_name "$route" MAX_OUTPUT_TOKENS)" \
      "$route model max output tokens" \
      2048
  )"
  timeout_ms="$(
    prompt_text "$(route_environment_name "$route" TIMEOUT_MS)" \
      "$route model request timeout in milliseconds" \
      60000
  )"
  health_timeout_ms="$(
    prompt_text "$(route_environment_name "$route" HEALTH_TIMEOUT_MS)" \
      "$route model health-check timeout in milliseconds" \
      5000
  )"
  validate_bounded_integer "$max_input_tokens" "$route max input tokens" 1000000
  validate_bounded_integer "$max_output_tokens" "$route max output tokens" 1000000
  validate_bounded_integer "$timeout_ms" "$route request timeout" 3600000
  validate_bounded_integer "$health_timeout_ms" "$route health timeout" 60000

  if [[ -n "$credential_name" ]]; then
    token="$(
      prompt_secret "$(route_environment_name "$route" TOKEN)" \
        "$token_prompt"
    )"
    validate_model_token "$token" "$token_label"
    write_private_text "$STAGE/$credential_name" "$token"
    unset token
    MODEL_CREDENTIAL_ARGS+=("--model-credential" "$credential_name=$STAGE/$credential_name")
  fi

  jq -n \
    --arg display_name "$display_name" \
    --arg provider_id "$provider_id" \
    --arg model_id "$model_id" \
    --arg base_url "$base_url" \
    --arg api_style "$api_style" \
    --arg processing_location "$processing_location" \
    --argjson allowed_sensitivities "$allowed_sensitivities" \
    --argjson max_input_tokens "$max_input_tokens" \
    --argjson max_output_tokens "$max_output_tokens" \
    --argjson estimated_max_cost_gbp "$estimated_max_cost_gbp" \
    --argjson input_cost_gbp_per_million_tokens "$input_cost_gbp_per_million_tokens" \
    --argjson output_cost_gbp_per_million_tokens "$output_cost_gbp_per_million_tokens" \
    --argjson timeout_ms "$timeout_ms" \
    --argjson health_timeout_ms "$health_timeout_ms" \
    --arg authorization_token_file "$authorization_token_file" \
    '{
      display_name: $display_name,
      provider_id: $provider_id,
      model_id: $model_id,
      base_url: $base_url,
      api_style: $api_style,
      processing_location: $processing_location,
      allowed_sensitivities: $allowed_sensitivities,
      max_input_tokens: $max_input_tokens,
      max_output_tokens: $max_output_tokens,
      estimated_max_cost_gbp: $estimated_max_cost_gbp,
      input_cost_gbp_per_million_tokens: $input_cost_gbp_per_million_tokens,
      output_cost_gbp_per_million_tokens: $output_cost_gbp_per_million_tokens,
      timeout_ms: $timeout_ms,
      health_timeout_ms: $health_timeout_ms
    } + (
      if $authorization_token_file == "" then
        {}
      else
        {authorization_token_file: $authorization_token_file}
      end
    )' >"$output"
  chmod 0600 "$output"
}

prompt_yes_no() {
  local name="$1"
  local prompt="$2"
  local default="$3"
  local value
  value="$(prompt_text "$name" "$prompt (yes or no)" "$default")"
  case "$value" in
    y|Y|yes|YES|true|TRUE) return 0 ;;
    n|N|no|NO|false|FALSE) return 1 ;;
    *) fail "$prompt must be answered yes or no" ;;
  esac
}

codex_self_change_tools_command() {
  local command_line
  local -a bootstrap_command=(
    sudo "$SOURCE/infra/server/bootstrap-debian.sh"
    --source "$SOURCE"
    --origin "$ORIGIN"
    --self-change-tools
  )
  if [[ -n "$CA_FILE" ]]; then
    bootstrap_command+=(--ca-file "$CA_FILE")
  fi
  printf -v command_line '%q ' "${bootstrap_command[@]}"
  printf '%s' "${command_line% }"
}

first_install_resume_command() {
  local command_line
  local -a first_install_command=(
    sudo /usr/local/libexec/melloa/first-install
    --source "$SOURCE"
    --origin "$ORIGIN"
  )
  if [[ -n "$CA_FILE" ]]; then
    first_install_command+=(--ca-file "$CA_FILE")
  fi
  printf -v command_line '%q ' "${first_install_command[@]}"
  printf '%s' "${command_line% }"
}

require_codex_self_change_tools() {
  local bootstrap_command
  local codex_exec_help
  local codex_help
  local codex_version
  local option
  local toolchain_lock
  [[ "$DESTINATION_ROOT" == / ]] || return 0
  require_command grep
  bootstrap_command="$(codex_self_change_tools_command)"
  toolchain_lock="$SOURCE/infra/server/toolchain.lock"
  [[ -f "$toolchain_lock" && ! -L "$toolchain_lock" ]] ||
    fail "optional self-change workers require the reviewed toolchain lock; rerun $bootstrap_command before enabling them"
  # shellcheck disable=SC1090
  source "$toolchain_lock"
  [[ -x /usr/local/bin/codex ]] ||
    fail "optional self-change workers require Codex CLI; rerun $bootstrap_command before enabling them"
  codex_version="$(/usr/local/bin/codex --version | awk 'NR == 1 {print $2}')" ||
    fail "optional self-change workers require a working Codex CLI; rerun $bootstrap_command before enabling them"
  [[ "$codex_version" == "$MELLOA_CODEX_CLI_VERSION" ]] ||
    fail "optional self-change workers require Codex CLI $MELLOA_CODEX_CLI_VERSION; rerun $bootstrap_command before enabling them"
  codex_help="$(/usr/local/bin/codex --help 2>&1)" ||
    fail "optional self-change workers require a working Codex CLI; rerun $bootstrap_command before enabling them"
  codex_exec_help="$(/usr/local/bin/codex exec --help 2>&1)" ||
    fail "optional self-change workers require a working Codex CLI exec path; rerun $bootstrap_command before enabling them"
  for option in --sandbox --ask-for-approval --oss --local-provider; do
    grep --fixed-strings --quiet -- "$option" <<<"$codex_help" ||
      fail "optional self-change workers require Codex CLI option $option; rerun $bootstrap_command before enabling them"
  done
  for option in --ephemeral --ignore-user-config; do
    grep --fixed-strings --quiet -- "$option" <<<"$codex_exec_help" ||
      fail "optional self-change workers require Codex CLI exec option $option; rerun $bootstrap_command before enabling them"
  done
}

activate_and_verify() {
  local activate_bin=/usr/local/libexec/melloa/activate
  local resume_command
  local verify_bin=/usr/local/libexec/melloa/verify-owner-journey
  local -a activate_args=("--source" "$SOURCE" "--origin" "$ORIGIN")
  [[ -x "$activate_bin" ]] || fail "installed activation command is unavailable"
  if prompt_yes_no MELLOA_SETUP_INITIALIZE_BACKUP \
    "Initialize the encrypted backup repository if it is empty" yes; then
    activate_args+=("--initialize-backup")
  fi
  if ! "$activate_bin" "${activate_args[@]}"; then
    resume_command="$(first_install_resume_command)"
    fail "activation failed; fix the reported cause, then rerun $resume_command. Existing private configuration will be reused"
  fi

  if [[ "$SKIP_VERIFICATION" == false ]]; then
    [[ -x "$verify_bin" ]] || fail "installed owner verification command is unavailable"
    if ! "$verify_bin" --source "$SOURCE"; then
      fail "owner verification failed; fix the reported cause or send the exact Telegram phrase, then rerun sudo /usr/local/libexec/melloa/verify-owner-journey"
    fi
    echo "First-owner setup finished. Telegram conversation has been verified." >&2
    cat >&2 <<'EOF'
Next qualification steps:
  1. In Telegram, send /status and then one ordinary message to Melli.
  2. Reboot the server, then run: sudo /usr/local/libexec/melloa/verify-owner-journey
  3. Prove the actual backup path: sudo /usr/local/libexec/melloa/restore-drill
  4. Rerun active verification: sudo /usr/local/libexec/melloa/verify-owner-journey

Keep using the installed update and rollback wrappers for later reviewed releases:
  sudo /usr/local/libexec/melloa/update
  sudo /usr/local/libexec/melloa/rollback
EOF
  else
    cat >&2 <<'EOF'
First-owner setup finished. Verification was skipped.
Before treating the server as usable, run:
  sudo /usr/local/libexec/melloa/verify-owner-journey
EOF
  fi
}

install_resume_build_ca() {
  local server_env="$1"
  local build_ca_destination
  local server_env_tmp
  [[ -n "$CA_FILE" ]] || return 0
  [[ -f "$server_env" && ! -L "$server_env" ]] ||
    fail "server environment file is unavailable; inspect $server_env before continuing"
  require_public_input_file "$CA_FILE" "build CA bundle" 32 1048576
  build_ca_destination="$(destination /etc/melloa/build-ca.pem)"
  if [[ -e "$build_ca_destination" || -L "$build_ca_destination" ]]; then
    [[ -f "$build_ca_destination" && ! -L "$build_ca_destination" ]] ||
      fail "existing build CA path is unsafe: $build_ca_destination"
  fi
  install -m 0644 "$CA_FILE" "$build_ca_destination"
  server_env_tmp="$(mktemp "${server_env%/*}/.server.env.XXXXXX")"
  awk -F= '
    $1 == "MELLOA_BUILD_CA_FILE" {
      print "MELLOA_BUILD_CA_FILE=/etc/melloa/build-ca.pem"
      count += 1
      next
    }
    { print }
    END { if (count != 1) exit 1 }
  ' "$server_env" >"$server_env_tmp" ||
    fail "MELLOA_BUILD_CA_FILE must occur exactly once in $server_env"
  chmod 0600 "$server_env_tmp"
  mv -f -- "$server_env_tmp" "$server_env"
  sync -f "$build_ca_destination"
  sync -f "$server_env"
  echo "Updated the installed public build CA bundle for future image builds." >&2
}

resume_existing_configuration() {
  local marker="$1"
  if [[ ! -e "$marker" && ! -L "$marker" ]]; then
    return 1
  fi
  [[ -f "$marker" && ! -L "$marker" ]] ||
    fail "existing configuration marker is unsafe; inspect $marker before continuing"
  jq -e '
    .contract_version == "1.0.0" and
    (.source_revision | type == "string" and test("^[0-9a-f]{40}$")) and
    (.backup_repository | type == "string" and startswith("/")) and
    (.configured_at | type == "string" and length > 0)
  ' "$marker" >/dev/null ||
    fail "existing configuration receipt is invalid; use a reviewed recovery procedure"

  install_resume_build_ca "$(destination /etc/melloa/server.env)"

  if [[ "$SKIP_ACTIVATION" == true ]]; then
    echo "Private configuration is already installed. Activation was skipped by request." >&2
    printf 'When ready, run: sudo /usr/local/libexec/melloa/activate --source %q --origin %q --initialize-backup\n' \
      "$SOURCE" "$ORIGIN" >&2
    echo "Then verify before treating the server as ready: sudo /usr/local/libexec/melloa/verify-owner-journey" >&2
    exit 0
  fi

  echo "Private configuration is already installed. Resuming activation and owner verification." >&2
  activate_and_verify
  exit 0
}

for command in awk chmod findmnt install jq mktemp mv rm stat sync tr; do
  require_command "$command"
done

[[ "$SOURCE" == /* && -d "$SOURCE" && ! -L "$SOURCE" ]] ||
  fail "source must be an absolute directory"
[[ "$DESTINATION_ROOT" == /* ]] || fail "setup root must be absolute"
if [[ -e "$DESTINATION_ROOT" && ( ! -d "$DESTINATION_ROOT" || -L "$DESTINATION_ROOT" ) ]]; then
  fail "setup root must be a directory, not a symlink"
fi
[[ "$ORIGIN" == https://* && "$ORIGIN" != *'@'* && "$ORIGIN" != *'?'* && "$ORIGIN" != *'#'* ]] ||
  fail "origin must be a credential-free HTTPS URL"
if [[ "$DESTINATION_ROOT" == / ]]; then
  ((EUID == 0)) || fail "setup must run as root"
fi
declare -a INSTALL_ARGS=(
  --source "$SOURCE"
  --origin "$ORIGIN"
  --root "$DESTINATION_ROOT"
  --guided-first-install
)
declare -a BUILD_CA_CONFIGURE_ARGS=()
if [[ -n "$CA_FILE" ]]; then
  apply_ca_file "$CA_FILE"
  INSTALL_ARGS+=(--ca-file "$CA_FILE")
  BUILD_CA_CONFIGURE_ARGS+=(--build-ca-file "$CA_FILE")
fi

"$SOURCE/infra/server/install.sh" "${INSTALL_ARGS[@]}"

readonly CONFIGURATION_MARKER="$(destination /etc/melloa/configuration.json)"
if resume_existing_configuration "$CONFIGURATION_MARKER"; then
  :
fi

if [[ "$DESTINATION_ROOT" == / && -d /root && ! -L /root ]]; then
  STAGE="$(mktemp -d /root/melloa-first-install.XXXXXX)"
else
  STAGE="$(mktemp -d /tmp/melloa-first-install.XXXXXX)"
fi
install -d -m 0700 "$STAGE"

echo "Melloa first-owner setup will now collect private values." >&2
echo "Secrets are written to temporary mode-0600 files and then copied into /etc/melloa/private." >&2

backup_repository="$(
  prompt_text MELLOA_SETUP_BACKUP_REPOSITORY \
    "Mounted off-device backup repository path" \
    /mnt/melloa-off-device-backup
)"
guardian_status_file="$(
  prompt_text MELLOA_SETUP_GUARDIAN_STATUS_FILE \
    "Guardian public status.json path from melloa-guardian make preview-state"
)"
guardian_public_key_file="$(
  prompt_text MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE \
    "Guardian public.pem path from melloa-guardian make preview-state"
)"
validate_public_setup_inputs
echo "Public path checks passed. Setup will now ask for private Telegram, model, and backup values." >&2
telegram_bot_token="$(
  prompt_secret MELLOA_SETUP_TELEGRAM_BOT_TOKEN \
    "Dedicated Telegram bot token"
)"
validate_telegram_bot_token "$telegram_bot_token"
write_private_text "$STAGE/telegram-bot-token" "$telegram_bot_token"
unset telegram_bot_token

telegram_owner_id="$(
  prompt_optional_text MELLOA_SETUP_TELEGRAM_OWNER_ID \
    "Already verified numeric Telegram owner ID (blank to pair now)"
)"
if [[ -z "$telegram_owner_id" ]]; then
  if [[ "$DESTINATION_ROOT" != / ]]; then
    fail "MELLOA_SETUP_TELEGRAM_OWNER_ID is required when setup uses a staging root"
  fi
  readonly PAIRING_BIN=/opt/melloa/worker/.venv/bin/melloa-pair-telegram
  [[ -x "$PAIRING_BIN" ]] || fail "Telegram pairing tool is unavailable; installer did not finish"
  telegram_owner_id="$("$PAIRING_BIN" --bot-token-file "$STAGE/telegram-bot-token")"
fi
validate_telegram_owner_id "$telegram_owner_id"

echo "Configure the two conversation model routes." >&2
echo "Use openai for the fixed OpenAI preset or external for another hosted OpenAI-compatible provider." >&2
declare -a MODEL_CREDENTIAL_ARGS=()
write_model_route capable "$STAGE/capable-model.json"
write_model_route economy "$STAGE/economy-model.json"
printf '{"owner_user_id":%s,"owner_chat_id":%s,"poll_timeout_seconds":20}\n' \
  "$telegram_owner_id" "$telegram_owner_id" >"$STAGE/telegram-owner.json"
chmod 0600 "$STAGE/telegram-owner.json"
if [[ "$DESTINATION_ROOT" == / ]]; then
  readonly DEPLOYMENT_CHECK_BIN=/opt/melloa/worker/.venv/bin/melloa
  [[ -x "$DEPLOYMENT_CHECK_BIN" ]] ||
    fail "deployment check tool is unavailable; installer did not finish"
  "$DEPLOYMENT_CHECK_BIN" deployment-check \
    --status "$guardian_status_file" \
    --public-key "$guardian_public_key_file" \
    --capable-model-config "$STAGE/capable-model.json" \
    --economy-model-config "$STAGE/economy-model.json" \
    --model-credential-source-root "$STAGE" \
    --telegram-owner-config "$STAGE/telegram-owner.json" \
    --telegram-bot-token-file "$STAGE/telegram-bot-token" \
    >/dev/null
  echo "Live Guardian, model, and Telegram checks passed before private configuration was installed." >&2
fi

restic_password="$(
  prompt_secret MELLOA_SETUP_RESTIC_PASSWORD \
    "Restic recovery password retained outside Melloa"
)"
validate_restic_password "$restic_password"
write_private_text "$STAGE/restic-password" "$restic_password"
unset restic_password

declare -a SELF_CHANGE_ARGS=(--self-change-disabled)
if prompt_yes_no MELLOA_SETUP_ENABLE_SELF_CHANGE \
  "Enable optional self-change workers during this first deployment" no; then
  require_codex_self_change_tools
  SELF_CHANGE_ARGS=()
  github_token="$(
    prompt_secret MELLOA_SETUP_GITHUB_TOKEN \
      "GitHub token with read/write access to this repository"
  )"
  validate_github_token "$github_token"
  write_private_text "$STAGE/github-token" "$github_token"
  unset github_token
  SELF_CHANGE_ARGS+=("--github-token-file" "$STAGE/github-token")

  codex_mode="$(
    prompt_text MELLOA_SETUP_CODEX_MODE \
      "Codex self-change planner credential mode (api-key or local)" \
      api-key
  )"
  codex_model="$(
    prompt_optional_text MELLOA_SETUP_CODEX_MODEL \
      "Optional Codex model override (blank for CLI default)"
  )"
  validate_codex_model "$codex_model"
  case "$codex_mode" in
    api-key)
      codex_api_key="$(
        prompt_secret MELLOA_SETUP_CODEX_API_KEY \
          "Codex API key for self-change planning"
      )"
      validate_codex_api_key "$codex_api_key"
      write_private_text "$STAGE/codex-api-key" "$codex_api_key"
      unset codex_api_key
      SELF_CHANGE_ARGS+=("--codex-api-key-file" "$STAGE/codex-api-key")
      ;;
    local)
      codex_local_provider="$(
        prompt_text MELLOA_SETUP_CODEX_LOCAL_PROVIDER \
          "Codex local provider (ollama or lmstudio)" \
          ollama
      )"
      [[ "$codex_local_provider" == ollama || "$codex_local_provider" == lmstudio ]] ||
        fail "Codex local provider must be ollama or lmstudio"
      SELF_CHANGE_ARGS+=("--codex-local-provider" "$codex_local_provider")
      ;;
    *)
      fail "Codex credential mode must be api-key or local"
      ;;
  esac
  if [[ -n "$codex_model" ]]; then
    SELF_CHANGE_ARGS+=("--codex-model" "$codex_model")
  fi
fi

readonly CONFIGURE_BIN="$(destination /usr/local/libexec/melloa/configure)"
[[ -x "$CONFIGURE_BIN" ]] || fail "installed configure command is unavailable"
"$CONFIGURE_BIN" \
  --source "$SOURCE" \
  --root "$DESTINATION_ROOT" \
  --backup-repository "$backup_repository" \
  --guardian-status-file "$guardian_status_file" \
  --guardian-public-key-file "$guardian_public_key_file" \
  --telegram-owner-id "$telegram_owner_id" \
  --telegram-bot-token-file "$STAGE/telegram-bot-token" \
  --capable-model-config-file "$STAGE/capable-model.json" \
  --economy-model-config-file "$STAGE/economy-model.json" \
  "${MODEL_CREDENTIAL_ARGS[@]}" \
  --restic-password-file "$STAGE/restic-password" \
  "${BUILD_CA_CONFIGURE_ARGS[@]}" \
  "${SELF_CHANGE_ARGS[@]}"

if [[ "$SKIP_ACTIVATION" == true ]]; then
  echo "Private configuration is installed. Activation was skipped by request." >&2
  printf 'When ready, run: sudo /usr/local/libexec/melloa/activate --source %q --origin %q --initialize-backup\n' \
    "$SOURCE" "$ORIGIN" >&2
  echo "Then verify before treating the server as ready: sudo /usr/local/libexec/melloa/verify-owner-journey" >&2
  exit 0
fi

activate_and_verify
