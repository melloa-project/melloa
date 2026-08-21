#!/usr/bin/env bash
set -euo pipefail

umask 022

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT"
ORIGIN="https://github.com/melloa-project/melloa.git"
CHECK_ONLY=false
CONTAINER_SMOKE=false
SELF_CHANGE_TOOLS=false
DOWNLOAD_DIR=""
CA_FILE=""

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/bootstrap-debian.sh [--source PATH] [--origin HTTPS_URL] [--ca-file PATH]
                                         [--self-change-tools] [--check]

Installs and verifies the reviewed Melloa host toolchain on a fresh Debian 13 amd64
systemd server. --check performs no package or tool installation.

--self-change-tools also installs and verifies the pinned Codex CLI required by the
bounded self-change workers used in the first-server proof.
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
    --check)
      CHECK_ONLY=true
      shift
      ;;
    --ca-file)
      [[ $# -ge 2 ]] || usage
      CA_FILE="$2"
      shift 2
      ;;
    --container-smoke)
      CONTAINER_SMOKE=true
      shift
      ;;
    --self-change-tools)
      SELF_CHANGE_TOOLS=true
      shift
      ;;
    *)
      usage
      ;;
  esac
done

fail() {
  echo "Debian server bootstrap failed: $1" >&2
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

cleanup() {
  if [[ "$DOWNLOAD_DIR" == /var/tmp/melloa-bootstrap.* && -d "$DOWNLOAD_DIR" ]]; then
    rm -rf -- "$DOWNLOAD_DIR"
  fi
}
trap cleanup EXIT HUP INT TERM

((EUID == 0)) || fail "bootstrap must run as root"
[[ "$SOURCE" == /* && -d "$SOURCE" && ! -L "$SOURCE" ]] ||
  fail "source must be an absolute directory"
[[ "$ORIGIN" == https://* && "$ORIGIN" != *'@'* && "$ORIGIN" != *'?'* && \
  "$ORIGIN" != *'#'* ]] || fail "origin must be a credential-free HTTPS URL"
if [[ -n "$CA_FILE" ]]; then
  [[ "$CA_FILE" == /* && -f "$CA_FILE" && ! -L "$CA_FILE" && -r "$CA_FILE" ]] ||
    fail "CA bundle must be a readable regular file"
  export CURL_CA_BUNDLE="$CA_FILE"
  export GIT_SSL_CAINFO="$CA_FILE"
  export NODE_EXTRA_CA_CERTS="$CA_FILE"
  export SSL_CERT_FILE="$CA_FILE"
fi
readonly TOOLCHAIN_LOCK="$SOURCE/infra/server/toolchain.lock"
[[ -f "$TOOLCHAIN_LOCK" && ! -L "$TOOLCHAIN_LOCK" ]] || fail "toolchain lock is unavailable"
# shellcheck disable=SC1090
source "$TOOLCHAIN_LOCK"

readonly MELLOA_SERVER_OS_ID MELLOA_SERVER_OS_VERSION MELLOA_SERVER_OS_CODENAME
readonly MELLOA_SERVER_ARCHITECTURE MELLOA_DEBIAN_TEST_IMAGE
readonly MELLOA_DOCKER_APT_KEY_FINGERPRINT MELLOA_NODE_VERSION MELLOA_NODE_SHA256
readonly MELLOA_GO_MIN_VERSION MELLOA_UV_VERSION MELLOA_UV_SHA256 MELLOA_CODEX_CLI_VERSION
readonly MELLOA_CODEX_NPM_INTEGRITY MELLOA_CODEX_LINUX_X64_NPM_INTEGRITY

for digest in "$MELLOA_NODE_SHA256" "$MELLOA_UV_SHA256"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "toolchain lock contains an invalid SHA-256"
done
[[ "$MELLOA_DOCKER_APT_KEY_FINGERPRINT" =~ ^[0-9A-F]{40}$ ]] ||
  fail "toolchain lock contains an invalid Docker key fingerprint"

# /etc/os-release is root-controlled host metadata. Debian may expose it as a symlink.
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "$MELLOA_SERVER_OS_ID" ]] || fail "the selected target requires Debian"
[[ "${VERSION_ID:-}" == "$MELLOA_SERVER_OS_VERSION" ]] ||
  fail "the selected target requires Debian $MELLOA_SERVER_OS_VERSION"
[[ "${VERSION_CODENAME:-}" == "$MELLOA_SERVER_OS_CODENAME" ]] ||
  fail "the selected target requires Debian $MELLOA_SERVER_OS_CODENAME"
[[ "$(dpkg --print-architecture)" == "$MELLOA_SERVER_ARCHITECTURE" ]] ||
  fail "the selected target requires $MELLOA_SERVER_ARCHITECTURE"
[[ "$(uname -m)" == x86_64 ]] || fail "the selected target requires an x86_64 kernel"

if [[ "$CONTAINER_SMOKE" == true ]]; then
  [[ -f /.dockerenv ]] || fail "--container-smoke is restricted to the disposable Docker test"
  [[ "$CHECK_ONLY" == false ]] || usage
else
  [[ "$(</proc/1/comm)" == systemd ]] || fail "the selected target must boot with systemd"
fi

# apt uses the conventional lowercase proxy variables, while operators and CI commonly provide
# their uppercase equivalents. Preserve an explicitly supplied lowercase value.
if [[ -z "${http_proxy:-}" && -n "${HTTP_PROXY:-}" ]]; then
  export http_proxy="$HTTP_PROXY"
fi
if [[ -z "${https_proxy:-}" && -n "${HTTPS_PROXY:-}" ]]; then
  export https_proxy="$HTTPS_PROXY"
fi
if [[ -z "${no_proxy:-}" && -n "${NO_PROXY:-}" ]]; then
  export no_proxy="$NO_PROXY"
fi

verify_codex_cli() {
  local codex_help
  local codex_exec_help
  local option
  [[ -x /usr/local/bin/codex ]] || fail "Codex CLI must be installed at /usr/local/bin/codex"
  [[ "$(/usr/local/bin/codex --version)" == "codex-cli $MELLOA_CODEX_CLI_VERSION" ]] ||
    fail "Codex CLI does not match the reviewed version $MELLOA_CODEX_CLI_VERSION"

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

verify_toolchain() {
  local compose_version
  local go_version
  local python_version

  for command in bwrap docker git go jq make node npm python3.13 rsync uv; do
    require_command "$command"
  done
  [[ "$(node --version)" == "v$MELLOA_NODE_VERSION" ]] ||
    fail "Node.js does not match the reviewed version $MELLOA_NODE_VERSION"
  [[ "$(uv --version | awk 'NR == 1 {print $2}')" == "$MELLOA_UV_VERSION" ]] ||
    fail "uv does not match the reviewed version $MELLOA_UV_VERSION"
  python_version="$(python3.13 -c 'import platform; print(platform.python_version())')"
  version_at_least "$python_version" 3.13 || fail "Python 3.13 or newer is required"
  go_version="$(go env GOVERSION | sed 's/^go//')"
  version_at_least "$go_version" "$MELLOA_GO_MIN_VERSION" ||
    fail "Go $MELLOA_GO_MIN_VERSION or newer is required for the Guardian public handoff"
  compose_version="$(docker compose version --short | sed 's/^v//')"
  version_at_least "$compose_version" 2.27.0 || fail "Docker Compose 2.27 or newer is required"
  docker compose \
    --project-directory "$SOURCE" \
    --env-file "$SOURCE/infra/server/server.env.example" \
    --file "$SOURCE/compose.server.yaml" \
    config --quiet

  if [[ "$SELF_CHANGE_TOOLS" == true ]]; then
    verify_codex_cli
  fi
}

if [[ "$CHECK_ONLY" == true ]]; then
  verify_toolchain
  systemctl is-active --quiet docker.service || fail "Docker is not active"
  systemctl is-enabled --quiet docker.service || fail "Docker is not enabled for reboot"
  docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable"
  "$SOURCE/infra/server/preflight.sh" --source "$SOURCE" --origin "$ORIGIN"
  echo "Debian server bootstrap check passed."
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
declare -a apt_options=(--quiet=2 -o Dpkg::Use-Pty=0)
declare -a npm_ca_option=()
if [[ -n "$CA_FILE" ]]; then
  apt_options+=(-o "Acquire::https::CaInfo=$CA_FILE")
  npm_ca_option+=(--cafile="$CA_FILE")
fi
apt-get "${apt_options[@]}" update
apt-get "${apt_options[@]}" install --yes --no-install-recommends ca-certificates curl gnupg

for conflicting_package in docker.io docker-compose docker-doc podman-docker containerd runc; do
  if [[ "$(dpkg-query --show --showformat='${db:Status-Abbrev}' \
    "$conflicting_package" 2>/dev/null || true)" == ii* ]]; then
    fail "conflicting package is already installed on this fresh-host path: $conflicting_package"
  fi
done

DOWNLOAD_DIR="$(mktemp -d /var/tmp/melloa-bootstrap.XXXXXX)"
readonly DOCKER_KEY="$DOWNLOAD_DIR/docker.asc"
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --retry 3 \
  --output "$DOCKER_KEY" https://download.docker.com/linux/debian/gpg
install -d -m 0700 "$DOWNLOAD_DIR/gnupg"
readonly DOCKER_KEY_FINGERPRINT="$(
  GNUPGHOME="$DOWNLOAD_DIR/gnupg" gpg --batch --show-keys --with-colons "$DOCKER_KEY" |
    awk -F: '$1 == "fpr" {print $10; exit}'
)"
[[ "$DOCKER_KEY_FINGERPRINT" == "$MELLOA_DOCKER_APT_KEY_FINGERPRINT" ]] ||
  fail "Docker repository signing key fingerprint changed"
install -d -m 0755 /etc/apt/keyrings
install -m 0644 "$DOCKER_KEY" /etc/apt/keyrings/melloa-docker.asc
printf '%s\n' \
  "deb [arch=amd64 signed-by=/etc/apt/keyrings/melloa-docker.asc] https://download.docker.com/linux/debian trixie stable" \
  >"$DOWNLOAD_DIR/melloa-docker.list"
install -m 0644 "$DOWNLOAD_DIR/melloa-docker.list" /etc/apt/sources.list.d/melloa-docker.list

apt-get "${apt_options[@]}" update
apt-get "${apt_options[@]}" install --yes --no-install-recommends \
  bash bubblewrap coreutils docker-buildx-plugin docker-ce docker-ce-cli \
  docker-compose-plugin findutils git golang-go grep jq make mawk passwd procps python3.13 \
  python3.13-venv rsync sed systemd tar util-linux xz-utils

readonly TOOLCHAIN_DIR=/opt/melloa/toolchain
readonly NODE_BASENAME="node-v$MELLOA_NODE_VERSION-linux-x64"
readonly NODE_DIR="$TOOLCHAIN_DIR/$NODE_BASENAME"
install -d -m 0755 "$TOOLCHAIN_DIR"
if [[ -e "$NODE_DIR" || -L "$NODE_DIR" ]]; then
  [[ -d "$NODE_DIR" && ! -L "$NODE_DIR" && -x "$NODE_DIR/bin/node" ]] ||
    fail "existing managed Node.js directory is unsafe"
  [[ "$($NODE_DIR/bin/node --version)" == "v$MELLOA_NODE_VERSION" ]] ||
    fail "existing managed Node.js directory has the wrong version"
else
  readonly NODE_ARCHIVE="$DOWNLOAD_DIR/$NODE_BASENAME.tar.xz"
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --retry 3 \
    --output "$NODE_ARCHIVE" \
    "https://nodejs.org/dist/v$MELLOA_NODE_VERSION/$NODE_BASENAME.tar.xz"
  printf '%s  %s\n' "$MELLOA_NODE_SHA256" "$(basename "$NODE_ARCHIVE")" \
    >"$DOWNLOAD_DIR/node.sha256"
  (cd "$DOWNLOAD_DIR" && sha256sum --check node.sha256)
  tar --extract --file "$NODE_ARCHIVE" --directory "$TOOLCHAIN_DIR"
  [[ -x "$NODE_DIR/bin/node" && -x "$NODE_DIR/bin/npm" ]] ||
    fail "Node.js archive did not contain the expected tools"
  chown -R root:root "$NODE_DIR"
fi

install_managed_link() {
  local source="$1"
  local target="$2"
  if [[ -e "$target" || -L "$target" ]]; then
    [[ -L "$target" && "$(readlink -- "$target")" == "$source" ]] ||
      fail "existing command is not the reviewed Melloa tool: $target"
    return 0
  fi
  ln --symbolic "$source" "$target"
}

for command in node npm npx corepack; do
  install_managed_link "$NODE_DIR/bin/$command" "/usr/local/bin/$command"
done

if [[ -e /usr/local/bin/uv || -L /usr/local/bin/uv || \
  -e /usr/local/bin/uvx || -L /usr/local/bin/uvx ]]; then
  [[ -f /usr/local/bin/uv && ! -L /usr/local/bin/uv && \
    -f /usr/local/bin/uvx && ! -L /usr/local/bin/uvx && \
    "$(/usr/local/bin/uv --version | awk 'NR == 1 {print $2}')" == \
      "$MELLOA_UV_VERSION" ]] ||
    fail "existing uv installation is not the reviewed Melloa tool"
else
  readonly UV_BASENAME=uv-x86_64-unknown-linux-gnu
  readonly UV_ARCHIVE="$DOWNLOAD_DIR/$UV_BASENAME.tar.gz"
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --retry 3 \
    --output "$UV_ARCHIVE" \
    "https://github.com/astral-sh/uv/releases/download/$MELLOA_UV_VERSION/$UV_BASENAME.tar.gz"
  printf '%s  %s\n' "$MELLOA_UV_SHA256" "$(basename "$UV_ARCHIVE")" \
    >"$DOWNLOAD_DIR/uv.sha256"
  (cd "$DOWNLOAD_DIR" && sha256sum --check uv.sha256)
  tar --extract --file "$UV_ARCHIVE" --directory "$DOWNLOAD_DIR"
  install -m 0755 "$DOWNLOAD_DIR/$UV_BASENAME/uv" /usr/local/bin/uv
  install -m 0755 "$DOWNLOAD_DIR/$UV_BASENAME/uvx" /usr/local/bin/uvx
fi

if [[ "$SELF_CHANGE_TOOLS" == true ]]; then
  if [[ -e /usr/local/bin/codex || -L /usr/local/bin/codex ]]; then
    [[ -x /usr/local/bin/codex && \
      "$(/usr/local/bin/codex --version)" == "codex-cli $MELLOA_CODEX_CLI_VERSION" ]] ||
      fail "existing Codex CLI is not the reviewed version"
  else
    readonly NPM=/usr/local/bin/npm
    readonly NPM_REGISTRY=https://registry.npmjs.org
    readonly NPM_USER_CONFIG="$DOWNLOAD_DIR/npm-user.conf"
    readonly NPM_GLOBAL_CONFIG="$DOWNLOAD_DIR/npm-global.conf"
    readonly CODEX_PACKAGE="@openai/codex@$MELLOA_CODEX_CLI_VERSION"
    readonly CODEX_PLATFORM_PACKAGE="@openai/codex@$MELLOA_CODEX_CLI_VERSION-linux-x64"
    install -m 0600 /dev/null "$NPM_USER_CONFIG"
    install -m 0600 /dev/null "$NPM_GLOBAL_CONFIG"
    readonly CODEX_INTEGRITY="$(
      NPM_CONFIG_USERCONFIG="$NPM_USER_CONFIG" NPM_CONFIG_GLOBALCONFIG="$NPM_GLOBAL_CONFIG" \
        "$NPM" view --registry="$NPM_REGISTRY" "${npm_ca_option[@]}" \
          "$CODEX_PACKAGE" dist.integrity
    )"
    readonly CODEX_PLATFORM_INTEGRITY="$(
      NPM_CONFIG_USERCONFIG="$NPM_USER_CONFIG" NPM_CONFIG_GLOBALCONFIG="$NPM_GLOBAL_CONFIG" \
        "$NPM" view --registry="$NPM_REGISTRY" "${npm_ca_option[@]}" \
          "$CODEX_PLATFORM_PACKAGE" dist.integrity
    )"
    [[ "$CODEX_INTEGRITY" == "$MELLOA_CODEX_NPM_INTEGRITY" ]] ||
      fail "Codex CLI npm integrity changed"
    [[ "$CODEX_PLATFORM_INTEGRITY" == "$MELLOA_CODEX_LINUX_X64_NPM_INTEGRITY" ]] ||
      fail "Codex CLI Linux binary npm integrity changed"
    NPM_CONFIG_USERCONFIG="$NPM_USER_CONFIG" NPM_CONFIG_GLOBALCONFIG="$NPM_GLOBAL_CONFIG" \
      "$NPM" install --global --prefix /usr/local --registry="$NPM_REGISTRY" \
        "${npm_ca_option[@]}" --ignore-scripts --no-audit --no-fund --omit=dev "$CODEX_PACKAGE"
  fi
fi

verify_toolchain

if [[ "$CONTAINER_SMOKE" == true ]]; then
  echo "Disposable Debian bootstrap toolchain smoke test passed."
  exit 0
fi

systemctl enable --now containerd.service docker.service >/dev/null
systemctl is-active --quiet docker.service || fail "Docker did not become active"
systemctl is-enabled --quiet docker.service || fail "Docker is not enabled for reboot"
docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable after installation"
"$SOURCE/infra/server/preflight.sh" --source "$SOURCE" --origin "$ORIGIN"

echo "Debian server prerequisites are installed and verified."
echo "Next create the Guardian public handoff if it is not already beside this checkout:"
printf '  cd %q\n' "$(dirname "$SOURCE")"
echo "  git clone https://github.com/melloa-project/melloa-guardian.git"
echo "  cd melloa-guardian"
echo "  make preview-state"
printf '  cd %q\n' "$SOURCE"
echo "Then print the setup input checklist:"
printf '  %q --print-input-checklist\n' "$SOURCE/infra/server/first-install.sh"
echo "Then run the guided first install:"
printf '  sudo %q/infra/server/first-install.sh --source %q --origin %q' \
  "$SOURCE" "$SOURCE" "$ORIGIN"
if [[ -n "$CA_FILE" ]]; then
  printf ' --ca-file %q' "$CA_FILE"
fi
printf '\n'
if [[ "$SELF_CHANGE_TOOLS" == false ]]; then
  echo "Self-change proof requires rerunning bootstrap with --self-change-tools before those workers are enabled."
fi
