#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT"
ORIGIN="https://github.com/melloa-project/melloa.git"
INSTALLED=false

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/preflight.sh [--source PATH] [--origin HTTPS_URL] [--installed]
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

version_at_least() {
  local actual="$1"
  local required="$2"
  [[ "$(printf '%s\n%s\n' "$required" "$actual" | sort -V | head -n 1)" == "$required" ]]
}

require_private_file() {
  local path="$1"
  local label="$2"
  local minimum_size="${3:-1}"
  local mode
  [[ -f "$path" && ! -L "$path" ]] || fail "$label must be a regular file"
  [[ "$(stat --format='%u' "$path")" == 0 ]] || fail "$label must be owned by root"
  mode="$(stat --format='%a' "$path")"
  ((8#$mode & 0077)) && fail "$label must be mode 0600 or stricter"
  [[ "$(stat --format='%s' "$path")" -ge "$minimum_size" ]] || fail "$label is empty"
}

[[ "$(uname -s)" == Linux ]] || fail "the persistent server path requires Linux"
[[ "$SOURCE" == /* && -d "$SOURCE" && ! -L "$SOURCE" ]] || fail "source must be an absolute directory"
[[ "$ORIGIN" == https://* && "$ORIGIN" != *'@'* && "$ORIGIN" != *'?'* && "$ORIGIN" != *'#'* ]] ||
  fail "origin must be a credential-free HTTPS URL"
[[ -f "$SOURCE/pyproject.toml" && -f "$SOURCE/uv.lock" ]] || fail "source checkout is incomplete"

for command in \
  awk basename bash bwrap chown codex docker find findmnt git grep head id install jq mktemp node \
  npm python3.13 rm rsync runuser sed sort stat sync systemctl systemd-analyze tar uname useradd \
  uv; do
  require_command "$command"
done

readonly SYSTEMD_VERSION="$(systemd-analyze --version | awk 'NR == 1 {print $2}')"
[[ "$SYSTEMD_VERSION" =~ ^[0-9]+$ ]] || fail "systemd version could not be determined"
((SYSTEMD_VERSION >= 249)) || fail "systemd 249 or newer is required"

readonly UV_VERSION="$(uv --version | awk 'NR == 1 {print $2}')"
[[ "$UV_VERSION" == 0.12.0 ]] || fail "uv 0.12.0 is required"
readonly PYTHON_VERSION="$(python3.13 -c 'import platform; print(platform.python_version())')"
version_at_least "$PYTHON_VERSION" 3.13 || fail "Python 3.13 or newer is required"
readonly NODE_VERSION="$(node --version | sed 's/^v//; s/+.*//')"
version_at_least "$NODE_VERSION" 22.0.0 || fail "Node.js 22 or newer is required"
readonly COMPOSE_VERSION="$(docker compose version --short | sed 's/^v//')"
version_at_least "$COMPOSE_VERSION" 2.27.0 || fail "Docker Compose 2.27 or newer is required"

readonly CODEX_HELP="$(codex exec --help 2>&1)"
[[ -x /usr/local/bin/codex ]] || fail "Codex CLI must be installed at /usr/local/bin/codex"
for option in --sandbox --ask-for-approval --ephemeral --ignore-user-config --oss --local-provider; do
  grep --fixed-strings --quiet -- "$option" <<<"$CODEX_HELP" ||
    fail "Codex CLI does not support required option: $option"
done

[[ -d "$SOURCE/.git" && ! -L "$SOURCE/.git" ]] || fail "source must be a Git checkout"
[[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=normal)" ]] ||
  fail "source checkout must be clean"
readonly REVISION="$(git -C "$SOURCE" rev-parse HEAD)"
[[ "$REVISION" =~ ^[0-9a-f]{40}$ ]] || fail "source revision is invalid"
[[ "$(git -C "$SOURCE" remote get-url origin)" == "$ORIGIN" ]] ||
  fail "source origin does not match the selected public origin"
readonly REMOTE_REVISION="$(
  GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 HOME=/nonexistent \
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

require_private_file /etc/melloa/server.env "server environment file"
require_private_file /etc/melloa/self-change.env "self-change environment file"
require_private_file /etc/melloa/private/database-change-planner-dsn "planner database DSN"
require_private_file /etc/melloa/private/database-change-applier-dsn "applier database DSN"
require_private_file /etc/melloa/private/git-credentials "Git credential"

readonly USE_API_KEY="$(awk -F= '$1 == "MELLOA_CODEX_USE_API_KEY" {print $2}' /etc/melloa/self-change.env)"
[[ "$USE_API_KEY" == true || "$USE_API_KEY" == false ]] ||
  fail "MELLOA_CODEX_USE_API_KEY must occur once as true or false"
if [[ "$USE_API_KEY" == true ]]; then
  require_private_file /etc/melloa/private/codex-api-key "Codex API key" 20
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

runuser -u melloa-codex -- \
  bwrap --die-with-parent --new-session --unshare-all \
    --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp /usr/bin/true ||
  fail "unprivileged Bubblewrap isolation is unavailable"

echo "Installed server preflight passed for $REVISION."
