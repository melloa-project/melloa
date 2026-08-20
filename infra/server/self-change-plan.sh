#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly CREDENTIALS_DIR="${CREDENTIALS_DIRECTORY:-}"
readonly SELF_CHANGE_ENABLED="${MELLOA_SELF_CHANGE_ENABLED:-}"
readonly USE_API_KEY="${MELLOA_CODEX_USE_API_KEY:-}"
readonly MODEL="${MELLOA_CODEX_MODEL:-}"
readonly LOCAL_PROVIDER="${MELLOA_CODEX_LOCAL_PROVIDER:-}"

fail() {
  echo "Self-change planner service configuration rejected" >&2
  exit 2
}

[[ "$CREDENTIALS_DIR" == /* && -d "$CREDENTIALS_DIR" ]] || fail
[[ "$SELF_CHANGE_ENABLED" == true ]] || fail
[[ "$MODEL" != *$'\n'* && ${#MODEL} -le 128 ]] || fail
[[ "$LOCAL_PROVIDER" == "" || "$LOCAL_PROVIDER" == ollama || "$LOCAL_PROVIDER" == lmstudio ]] || fail
[[ "$USE_API_KEY" == true || "$USE_API_KEY" == false ]] || fail
[[ "$LOCAL_PROVIDER" == "" || "$USE_API_KEY" == false ]] || fail

readonly AGENT_UID="$(id -u melloa-codex)"
readonly AGENT_GID="$(id -g melloa-codex)"
[[ "$AGENT_UID" =~ ^[1-9][0-9]*$ && "$AGENT_GID" =~ ^[1-9][0-9]*$ ]] || fail

declare -a command=(
  /opt/melloa/worker/.venv/bin/melloa
  self-change-plan
  --dsn-file "$CREDENTIALS_DIR/planner-dsn"
  --repository /srv/melloa/planning-source
  --work-root /var/lib/melloa/planning-work
  --codex-executable /usr/local/libexec/melloa/codex
  --git-executable /usr/bin/git
  --agent-uid "$AGENT_UID"
  --agent-gid "$AGENT_GID"
  --agent-home /var/lib/melloa/codex-agent
  --codex-home /var/lib/melloa/codex-agent/codex
)

if [[ "$USE_API_KEY" == true ]]; then
  [[ -f "$CREDENTIALS_DIR/codex-api-key" ]] || fail
  command+=(--openai-api-key-file "$CREDENTIALS_DIR/codex-api-key")
fi
[[ -z "$MODEL" ]] || command+=(--model "$MODEL")
[[ -z "$LOCAL_PROVIDER" ]] || command+=(--local-provider "$LOCAL_PROVIDER")

exec "${command[@]}"
