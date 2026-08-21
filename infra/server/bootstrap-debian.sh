#!/usr/bin/env bash
set -euo pipefail

umask 022

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly TOOLCHAIN_HELPERS="$ROOT/infra/server/toolchain.sh"
[[ -f "$TOOLCHAIN_HELPERS" && ! -L "$TOOLCHAIN_HELPERS" ]] || {
  echo "Melloa server bootstrap failed: toolchain helpers are unavailable" >&2
  exit 1
}
# shellcheck disable=SC1090
source "$TOOLCHAIN_HELPERS"
readonly MELLOA_TOOLCHAIN_DIR=/opt/melloa/toolchain
readonly MELLOA_TOOLCHAIN_BIN="$MELLOA_TOOLCHAIN_DIR/bin"
readonly MELLOA_HOST_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
readonly MELLOA_RUNTIME_PATH="$(melloa_runtime_path "$MELLOA_TOOLCHAIN_BIN")"
# Do not execute a pre-existing private toolchain before its root-ownership checks below.
export PATH="$MELLOA_HOST_PATH"
SOURCE="$ROOT"
ORIGIN="https://github.com/melloa-project/melloa.git"
CHECK_ONLY=false
CONTAINER_SMOKE=false
SELF_CHANGE_TOOLS=false
PRINT_HOST_PROFILE_OS_RELEASE=""
DOWNLOAD_DIR=""
CODEX_STAGING_DIR=""
CA_FILE=""
BOOTSTRAP_PHASE="initialization"

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/bootstrap-debian.sh [--source PATH] [--origin HTTPS_URL] [--ca-file PATH]
                                         [--self-change-tools] [--check]

Installs and verifies the minimum supported Melloa host toolchain on a supported amd64
systemd server. Compatible newer host tools are reused. The public entry point is
infra/server/bootstrap-linux.sh.
--check performs no package or tool installation.

--self-change-tools also installs and verifies Melloa's private, integrity-pinned Codex CLI
required by the bounded self-change workers used in the first-server proof.
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
    --print-host-profile)
      [[ $# -ge 2 ]] || usage
      PRINT_HOST_PROFILE_OS_RELEASE="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

fail() {
  echo "Melloa server bootstrap failed: $1" >&2
  exit 1
}

report_unexpected_failure() {
  local status=$?
  printf 'Melloa server bootstrap failed during: %s\n' "$BOOTSTRAP_PHASE" >&2
  printf '::error title=Melloa bootstrap failed::%s\n' "$BOOTSTRAP_PHASE" >&2
  return "$status"
}
trap report_unexpected_failure ERR

supported_hosts() {
  printf 'Debian 13 (trixie), Ubuntu 24.04 LTS (noble), or Pop!_OS 24.04 (noble)'
}

select_host_profile() {
  local os_release_file="$1"
  local host_codename
  local ubuntu_codename
  local ID=""
  local ID_LIKE=""
  local NAME=""
  local PRETTY_NAME=""
  local UBUNTU_CODENAME=""
  local VERSION_CODENAME=""
  local VERSION_ID=""

  [[ "$os_release_file" == /* && -f "$os_release_file" && -r "$os_release_file" ]] ||
    fail "os-release file must be an absolute readable regular file"

  # /etc/os-release is root-controlled host metadata and shell-compatible by contract. Debian may
  # expose it as a symlink to /usr/lib/os-release.
  # shellcheck disable=SC1090
  source "$os_release_file"

  ubuntu_codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
  host_codename="${VERSION_CODENAME:-$ubuntu_codename}"

  if [[ "$ID" == debian && "$VERSION_ID" == 13 && "$host_codename" == trixie ]]; then
    HOST_PROFILE=debian-13-trixie
    HOST_LABEL="Debian 13 (trixie)"
    HOST_DOCKER_APT_OS=debian
    HOST_DOCKER_APT_CODENAME=trixie
    return 0
  fi

  if [[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 && "$ubuntu_codename" == noble ]]; then
    HOST_PROFILE=ubuntu-24.04-noble
    HOST_LABEL="Ubuntu 24.04 LTS (noble)"
    HOST_DOCKER_APT_OS=ubuntu
    HOST_DOCKER_APT_CODENAME=noble
    return 0
  fi

  if [[ "$ID" == pop && "$VERSION_ID" == 24.04 && "$ubuntu_codename" == noble ]]; then
    HOST_PROFILE=pop-24.04-noble
    HOST_LABEL="Pop!_OS 24.04 (noble)"
    HOST_DOCKER_APT_OS=ubuntu
    HOST_DOCKER_APT_CODENAME=noble
    return 0
  fi

  fail "supported hosts are $(supported_hosts) on amd64 with systemd"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

cleanup() {
  if [[ "$DOWNLOAD_DIR" == /var/tmp/melloa-bootstrap.* && -d "$DOWNLOAD_DIR" ]]; then
    rm -rf -- "$DOWNLOAD_DIR"
  fi
  if [[ "$CODEX_STAGING_DIR" == "$MELLOA_TOOLCHAIN_DIR"/.codex.* && \
    -d "$CODEX_STAGING_DIR" && ! -L "$CODEX_STAGING_DIR" ]]; then
    rm -rf -- "$CODEX_STAGING_DIR"
  fi
}
trap cleanup EXIT HUP INT TERM

BOOTSTRAP_PHASE="validating bootstrap arguments"
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

readonly MELLOA_SUPPORTED_HOSTS MELLOA_SERVER_ARCHITECTURE MELLOA_DEBIAN_TEST_IMAGE
readonly MELLOA_UBUNTU_TEST_IMAGE MELLOA_DOCKER_APT_KEY_FINGERPRINT
readonly MELLOA_DOCKER_COMPOSE_MIN_VERSION MELLOA_PYTHON_MIN_VERSION MELLOA_PYTHON_VERSION
readonly MELLOA_NODE_MIN_VERSION MELLOA_NODE_VERSION MELLOA_NODE_SHA256 MELLOA_NPM_MIN_VERSION
readonly MELLOA_GO_VERSION MELLOA_GO_MIN_VERSION MELLOA_GO_SHA256
readonly MELLOA_UV_MIN_VERSION MELLOA_UV_VERSION MELLOA_UV_SHA256 MELLOA_CODEX_CLI_VERSION
readonly MELLOA_CODEX_NPM_INTEGRITY MELLOA_CODEX_LINUX_X64_NPM_INTEGRITY

for digest in "$MELLOA_NODE_SHA256" "$MELLOA_GO_SHA256" "$MELLOA_UV_SHA256"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "toolchain lock contains an invalid SHA-256"
done
[[ "$MELLOA_DOCKER_APT_KEY_FINGERPRINT" =~ ^[0-9A-F]{40}$ ]] ||
  fail "toolchain lock contains an invalid Docker key fingerprint"
[[ "$MELLOA_SUPPORTED_HOSTS" == *debian-13-trixie* && \
  "$MELLOA_SUPPORTED_HOSTS" == *ubuntu-24.04-noble* && \
  "$MELLOA_SUPPORTED_HOSTS" == *pop-24.04-noble* ]] ||
  fail "toolchain lock does not list the reviewed supported hosts"
for requirement in \
  "$MELLOA_DOCKER_COMPOSE_MIN_VERSION" \
  "$MELLOA_PYTHON_MIN_VERSION" \
  "$MELLOA_NODE_MIN_VERSION" \
  "$MELLOA_NPM_MIN_VERSION" \
  "$MELLOA_GO_MIN_VERSION" \
  "$MELLOA_UV_MIN_VERSION"; do
  melloa_normalize_version "$requirement" >/dev/null ||
    fail "toolchain lock contains an invalid minimum version"
done
melloa_python_version_is_supported "$MELLOA_PYTHON_VERSION" "$MELLOA_PYTHON_MIN_VERSION" ||
  fail "toolchain lock contains an invalid Python fallback version"
for specification in \
  "$MELLOA_NODE_VERSION:$MELLOA_NODE_MIN_VERSION" \
  "$MELLOA_GO_VERSION:$MELLOA_GO_MIN_VERSION" \
  "$MELLOA_UV_VERSION:$MELLOA_UV_MIN_VERSION"; do
  fallback_version="${specification%%:*}"
  minimum_version="${specification#*:}"
  melloa_version_at_least "$fallback_version" "$minimum_version" ||
    fail "toolchain lock fallback version is older than its supported minimum"
done

if [[ -n "$PRINT_HOST_PROFILE_OS_RELEASE" ]]; then
  BOOTSTRAP_PHASE="resolving requested host profile"
  select_host_profile "$PRINT_HOST_PROFILE_OS_RELEASE"
  printf '%s\t%s\t%s\t%s\n' \
    "$HOST_PROFILE" "$HOST_LABEL" "$HOST_DOCKER_APT_OS" "$HOST_DOCKER_APT_CODENAME"
  exit 0
fi

((EUID == 0)) || fail "bootstrap must run as root"
BOOTSTRAP_PHASE="resolving current host profile"
select_host_profile /etc/os-release
readonly HOST_PROFILE HOST_LABEL HOST_DOCKER_APT_OS HOST_DOCKER_APT_CODENAME
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

verify_toolchain_layout() {
  local mode
  local path
  for path in /opt/melloa "$MELLOA_TOOLCHAIN_DIR" "$MELLOA_TOOLCHAIN_BIN"; do
    [[ -d "$path" && ! -L "$path" ]] ||
      fail "Melloa toolchain path is unsafe: $path"
    [[ "$(stat --format='%u:%g' "$path")" == 0:0 ]] ||
      fail "Melloa toolchain path is not root-owned: $path"
    mode="$(stat --format='%a' "$path")"
    (((8#$mode & 0022) == 0)) ||
      fail "Melloa toolchain path is writable by non-root users: $path"
  done
}

ensure_toolchain_layout() {
  local path
  for path in /opt/melloa "$MELLOA_TOOLCHAIN_DIR" "$MELLOA_TOOLCHAIN_BIN"; do
    if [[ -e "$path" || -L "$path" ]]; then
      [[ -d "$path" && ! -L "$path" ]] ||
        fail "Melloa toolchain path is unsafe: $path"
    fi
    install -d -m 0755 "$path"
  done
  verify_toolchain_layout
}

link_selected_tool() {
  local name="$1"
  local executable="$2"
  melloa_link_tool "$MELLOA_TOOLCHAIN_BIN" "$name" "$executable" ||
    fail "could not safely select Melloa tool $name"
}

require_selected_tool() {
  local name="$1"
  melloa_tool_link_is_usable "$MELLOA_TOOLCHAIN_BIN" "$name" ||
    fail "Melloa-selected $name is unavailable; rerun bootstrap without --check"
}

verify_codex_cli_path() {
  local codex_executable="$1"
  local codex_help
  local codex_exec_help
  local option

  [[ -x "$codex_executable" ]] ||
    fail "Melloa's private Codex CLI is unavailable; rerun bootstrap with --self-change-tools"
  [[ "$("$codex_executable" --version)" == "codex-cli $MELLOA_CODEX_CLI_VERSION" ]] ||
    fail "Melloa's private Codex CLI does not match reviewed version $MELLOA_CODEX_CLI_VERSION"

  codex_help="$("$codex_executable" --help 2>&1)"
  codex_exec_help="$("$codex_executable" exec --help 2>&1)"
  for option in --sandbox --ask-for-approval --oss --local-provider; do
    grep --fixed-strings --quiet -- "$option" <<<"$codex_help" ||
      fail "Codex CLI does not support required option: $option"
  done
  for option in --ephemeral --ignore-user-config; do
    grep --fixed-strings --quiet -- "$option" <<<"$codex_exec_help" ||
      fail "Codex CLI exec does not support required option: $option"
  done
}

verify_codex_cli() {
  verify_codex_cli_path "$MELLOA_TOOLCHAIN_DIR/codex/bin/codex"
}

verify_toolchain() {
  local compose_version
  local go_version
  local node_version
  local npm_version
  local python_version
  local uv_version

  for command in bwrap docker git jq make rsync; do
    require_command "$command"
  done
  for command in node npm python3 uv go gofmt; do
    require_selected_tool "$command"
  done

  node_version="$("$MELLOA_TOOLCHAIN_BIN/node" --version 2>/dev/null || true)"
  melloa_version_at_least "$node_version" "$MELLOA_NODE_MIN_VERSION" ||
    fail "Node.js $MELLOA_NODE_MIN_VERSION or newer is required"
  npm_version="$("$MELLOA_TOOLCHAIN_BIN/npm" --version 2>/dev/null || true)"
  melloa_version_at_least "$npm_version" "$MELLOA_NPM_MIN_VERSION" ||
    fail "npm $MELLOA_NPM_MIN_VERSION or newer is required"
  uv_version="$("$MELLOA_TOOLCHAIN_BIN/uv" --version 2>/dev/null | awk 'NR == 1 {print $2}')"
  melloa_version_at_least "$uv_version" "$MELLOA_UV_MIN_VERSION" ||
    fail "uv $MELLOA_UV_MIN_VERSION or newer is required"
  python_version="$("$MELLOA_TOOLCHAIN_BIN/python3" -c 'import platform; print(platform.python_version())' 2>/dev/null || true)"
  melloa_python_version_is_supported "$python_version" "$MELLOA_PYTHON_MIN_VERSION" ||
    fail "Python $MELLOA_PYTHON_MIN_VERSION or newer within Python 3 is required"
  go_version="$("$MELLOA_TOOLCHAIN_BIN/go" env GOVERSION 2>/dev/null | sed 's/^go//')"
  melloa_version_at_least "$go_version" "$MELLOA_GO_MIN_VERSION" ||
    fail "Go $MELLOA_GO_MIN_VERSION or newer is required"
  compose_version="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
  melloa_version_at_least "$compose_version" "$MELLOA_DOCKER_COMPOSE_MIN_VERSION" ||
    fail "Docker Compose $MELLOA_DOCKER_COMPOSE_MIN_VERSION or newer is required"
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
  BOOTSTRAP_PHASE="verifying existing host toolchain"
  verify_toolchain_layout
  export PATH="$MELLOA_RUNTIME_PATH"
  verify_toolchain
  systemctl is-active --quiet docker.service || fail "Docker is not active"
  systemctl is-enabled --quiet docker.service || fail "Docker is not enabled for reboot"
  docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable"
  "$SOURCE/infra/server/preflight.sh" --source "$SOURCE" --origin "$ORIGIN"
  echo "Melloa server bootstrap check passed on $HOST_LABEL."
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
declare -a apt_options=(--quiet=2 -o Dpkg::Use-Pty=0)
declare -a npm_ca_option=()
if [[ -n "$CA_FILE" ]]; then
  apt_options+=(-o "Acquire::https::CaInfo=$CA_FILE")
  npm_ca_option+=(--cafile="$CA_FILE")
fi

docker_compose_is_supported() {
  local compose_version
  command -v docker >/dev/null 2>&1 || return 1
  compose_version="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
  melloa_version_at_least "$compose_version" "$MELLOA_DOCKER_COMPOSE_MIN_VERSION"
}

existing_docker_package_is_present() {
  local package
  for package in docker.io docker-compose docker-doc podman-docker containerd runc; do
    if [[ "$(dpkg-query --show --showformat='${db:Status-Abbrev}' \
      "$package" 2>/dev/null || true)" == ii* ]]; then
      return 0
    fi
  done
  return 1
}

docker_apt_source_exists() {
  melloa_docker_apt_source_exists / "$HOST_DOCKER_APT_OS" "$HOST_DOCKER_APT_CODENAME"
}

configure_docker_apt_source() {
  local expected_uri="https://download.docker.com/linux/$HOST_DOCKER_APT_OS"
  local docker_key="$DOWNLOAD_DIR/docker.asc"
  local docker_key_fingerprint

  if docker_apt_source_exists; then
    echo "Using the existing official Docker apt repository for $HOST_LABEL."
    return 0
  fi

  BOOTSTRAP_PHASE="fetching Docker repository key"
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --retry 3 \
    --output "$docker_key" "https://download.docker.com/linux/$HOST_DOCKER_APT_OS/gpg"
  install -d -m 0700 "$DOWNLOAD_DIR/gnupg"
  docker_key_fingerprint="$(
    GNUPGHOME="$DOWNLOAD_DIR/gnupg" gpg --batch --show-keys --with-colons "$docker_key" |
      awk -F: '$1 == "fpr" {print $10; exit}'
  )"
  [[ "$docker_key_fingerprint" == "$MELLOA_DOCKER_APT_KEY_FINGERPRINT" ]] ||
    fail "Docker repository signing key fingerprint changed"
  install -d -m 0755 /etc/apt/keyrings
  install -m 0644 "$docker_key" /etc/apt/keyrings/melloa-docker.asc
  printf '%s\n' \
    "deb [arch=amd64 signed-by=/etc/apt/keyrings/melloa-docker.asc] $expected_uri $HOST_DOCKER_APT_CODENAME stable" \
    >"$DOWNLOAD_DIR/melloa-docker.list"
  install -m 0644 "$DOWNLOAD_DIR/melloa-docker.list" /etc/apt/sources.list.d/melloa-docker.list
}

find_supported_host_python() {
  local directory
  local candidate
  local python_version

  for directory in /usr/local/sbin /usr/local/bin /usr/sbin /usr/bin /sbin /bin; do
    for candidate in "$directory"/python3 "$directory"/python3.[0-9]*; do
      [[ -x "$candidate" && ! -d "$candidate" ]] || continue
      python_version="$("$candidate" -c 'import platform; print(platform.python_version())' 2>/dev/null || true)"
      if melloa_python_version_is_supported "$python_version" "$MELLOA_PYTHON_MIN_VERSION"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  done
  return 1
}

install_managed_node() {
  local node_basename="node-v$MELLOA_NODE_VERSION-linux-x64"
  local node_dir="$MELLOA_TOOLCHAIN_DIR/$node_basename"
  local node_archive="$DOWNLOAD_DIR/$node_basename.tar.xz"

  if [[ -e "$node_dir" || -L "$node_dir" ]]; then
    [[ -d "$node_dir" && ! -L "$node_dir" && -x "$node_dir/bin/node" && \
      -x "$node_dir/bin/npm" ]] || fail "existing managed Node.js directory is unsafe"
    [[ "$("$node_dir/bin/node" --version)" == "v$MELLOA_NODE_VERSION" ]] ||
      fail "existing managed Node.js directory has the wrong version"
  else
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --retry 3 \
      --output "$node_archive" \
      "https://nodejs.org/dist/v$MELLOA_NODE_VERSION/$node_basename.tar.xz"
    printf '%s  %s\n' "$MELLOA_NODE_SHA256" "$(basename "$node_archive")" \
      >"$DOWNLOAD_DIR/node.sha256"
    (cd "$DOWNLOAD_DIR" && sha256sum --check node.sha256)
    tar --extract --file "$node_archive" --directory "$MELLOA_TOOLCHAIN_DIR"
    [[ -x "$node_dir/bin/node" && -x "$node_dir/bin/npm" ]] ||
      fail "Node.js archive did not contain the expected tools"
    chown -R root:root "$node_dir"
  fi
  link_selected_tool node "$node_dir/bin/node"
  link_selected_tool npm "$node_dir/bin/npm"
}

select_node_and_npm() {
  local host_node
  local host_npm
  local node_version
  local npm_version

  host_node="$(melloa_find_host_command "$MELLOA_HOST_PATH" node || true)"
  host_npm="$(melloa_find_host_command "$MELLOA_HOST_PATH" npm || true)"
  if [[ -n "$host_node" && -n "$host_npm" ]]; then
    node_version="$("$host_node" --version 2>/dev/null || true)"
    npm_version="$("$host_npm" --version 2>/dev/null || true)"
    if melloa_version_at_least "$node_version" "$MELLOA_NODE_MIN_VERSION" && \
      melloa_version_at_least "$npm_version" "$MELLOA_NPM_MIN_VERSION"; then
      link_selected_tool node "$host_node"
      link_selected_tool npm "$host_npm"
      return 0
    fi
  fi

  BOOTSTRAP_PHASE="installing managed Node.js"
  install_managed_node
}

install_managed_uv() {
  local uv_basename=uv-x86_64-unknown-linux-gnu
  local uv_dir="$MELLOA_TOOLCHAIN_DIR/uv-$MELLOA_UV_VERSION"
  local uv_archive="$DOWNLOAD_DIR/$uv_basename.tar.gz"

  if [[ -e "$uv_dir" || -L "$uv_dir" ]]; then
    [[ -d "$uv_dir" && ! -L "$uv_dir" && -x "$uv_dir/uv" && -x "$uv_dir/uvx" ]] ||
      fail "existing managed uv directory is unsafe"
    [[ "$("$uv_dir/uv" --version | awk 'NR == 1 {print $2}')" == "$MELLOA_UV_VERSION" ]] ||
      fail "existing managed uv directory has the wrong version"
  else
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --retry 3 \
      --output "$uv_archive" \
      "https://github.com/astral-sh/uv/releases/download/$MELLOA_UV_VERSION/$uv_basename.tar.gz"
    printf '%s  %s\n' "$MELLOA_UV_SHA256" "$(basename "$uv_archive")" \
      >"$DOWNLOAD_DIR/uv.sha256"
    (cd "$DOWNLOAD_DIR" && sha256sum --check uv.sha256)
    tar --extract --file "$uv_archive" --directory "$DOWNLOAD_DIR"
    [[ -x "$DOWNLOAD_DIR/$uv_basename/uv" && -x "$DOWNLOAD_DIR/$uv_basename/uvx" ]] ||
      fail "uv archive did not contain the expected tools"
    mv "$DOWNLOAD_DIR/$uv_basename" "$uv_dir"
    chown -R root:root "$uv_dir"
  fi
  link_selected_tool uv "$uv_dir/uv"
  link_selected_tool uvx "$uv_dir/uvx"
}

select_uv() {
  local host_uv
  local uv_version

  host_uv="$(melloa_find_host_command "$MELLOA_HOST_PATH" uv || true)"
  if [[ -n "$host_uv" ]]; then
    uv_version="$("$host_uv" --version 2>/dev/null | awk 'NR == 1 {print $2}')"
    if melloa_version_at_least "$uv_version" "$MELLOA_UV_MIN_VERSION"; then
      link_selected_tool uv "$host_uv"
      return 0
    fi
  fi

  BOOTSTRAP_PHASE="installing managed uv"
  install_managed_uv
}

install_managed_python() {
  local python_install_dir="$MELLOA_TOOLCHAIN_DIR/python"
  local python_dir="$python_install_dir/cpython-3.13-linux-x86_64-gnu"
  local python_install_output

  install -d -m 0755 "$python_install_dir"
  if [[ -e "$python_dir" || -L "$python_dir" ]]; then
    [[ -x "$python_dir/bin/python3.13" ]] || fail "existing managed Python is unsafe"
    [[ "$("$python_dir/bin/python3.13" -c 'import platform; print(platform.python_version())')" == \
      "$MELLOA_PYTHON_VERSION" ]] || fail "existing managed Python has the wrong version"
  else
    python_install_output="$(
      UV_PYTHON_DOWNLOADS=manual UV_SYSTEM_CERTS=true "$MELLOA_TOOLCHAIN_BIN/uv" --no-config \
        python install --install-dir "$python_install_dir" "$MELLOA_PYTHON_VERSION" 2>&1
    )" || {
      printf '%s\n' "$python_install_output" >&2
      printf '::error title=Managed Python install failed::%s\n' \
        "$(tr '\n' ' ' <<<"$python_install_output" | cut -c 1-800)" >&2
      exit 1
    }
    [[ -x "$python_dir/bin/python3.13" ]] || fail "managed Python installation failed"
  fi
  chown -R root:root "$python_install_dir"
  link_selected_tool python3 "$python_dir/bin/python3.13"
}

select_python() {
  local host_python

  host_python="$(find_supported_host_python || true)"
  if [[ -n "$host_python" ]]; then
    link_selected_tool python3 "$host_python"
    return 0
  fi

  BOOTSTRAP_PHASE="installing managed Python"
  install_managed_python
}

install_managed_go() {
  local go_basename="go$MELLOA_GO_VERSION.linux-amd64"
  local go_dir="$MELLOA_TOOLCHAIN_DIR/$go_basename"
  local go_archive="$DOWNLOAD_DIR/$go_basename.tar.gz"

  if [[ -e "$go_dir" || -L "$go_dir" ]]; then
    [[ -d "$go_dir" && ! -L "$go_dir" && -x "$go_dir/bin/go" && -x "$go_dir/bin/gofmt" ]] ||
      fail "existing managed Go directory is unsafe"
    [[ "$("$go_dir/bin/go" env GOVERSION)" == "go$MELLOA_GO_VERSION" ]] ||
      fail "existing managed Go directory has the wrong version"
  else
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location --retry 3 \
      --output "$go_archive" \
      "https://go.dev/dl/$go_basename.tar.gz"
    printf '%s  %s\n' "$MELLOA_GO_SHA256" "$(basename "$go_archive")" \
      >"$DOWNLOAD_DIR/go.sha256"
    (cd "$DOWNLOAD_DIR" && sha256sum --check go.sha256)
    tar --extract --file "$go_archive" --directory "$DOWNLOAD_DIR"
    [[ -x "$DOWNLOAD_DIR/go/bin/go" && -x "$DOWNLOAD_DIR/go/bin/gofmt" ]] ||
      fail "Go archive did not contain the expected tools"
    mv "$DOWNLOAD_DIR/go" "$go_dir"
    chown -R root:root "$go_dir"
  fi
  link_selected_tool go "$go_dir/bin/go"
  link_selected_tool gofmt "$go_dir/bin/gofmt"
}

select_go() {
  local host_go
  local host_gofmt
  local go_version

  host_go="$(melloa_find_host_command "$MELLOA_HOST_PATH" go || true)"
  host_gofmt="$(melloa_find_host_command "$MELLOA_HOST_PATH" gofmt || true)"
  if [[ -n "$host_go" && -n "$host_gofmt" ]]; then
    go_version="$("$host_go" env GOVERSION 2>/dev/null | sed 's/^go//')"
    if melloa_version_at_least "$go_version" "$MELLOA_GO_MIN_VERSION"; then
      link_selected_tool go "$host_go"
      link_selected_tool gofmt "$host_gofmt"
      return 0
    fi
  fi

  BOOTSTRAP_PHASE="installing managed Go"
  install_managed_go
}

install_codex_cli() {
  local codex_dir="$MELLOA_TOOLCHAIN_DIR/codex"
  local codex_executable="$codex_dir/bin/codex"
  local npm="$MELLOA_TOOLCHAIN_BIN/npm"
  local npm_registry=https://registry.npmjs.org
  local npm_user_config="$DOWNLOAD_DIR/npm-user.conf"
  local npm_global_config="$DOWNLOAD_DIR/npm-global.conf"
  local codex_package="@openai/codex@$MELLOA_CODEX_CLI_VERSION"
  local codex_platform_package="@openai/codex@$MELLOA_CODEX_CLI_VERSION-linux-x64"
  local codex_integrity
  local codex_platform_integrity

  secure_private_codex_dir() {
    local directory="$1"
    [[ -d "$directory" && ! -L "$directory" ]] ||
      fail "existing private Codex CLI directory is unsafe"
    chown -R root:root "$directory"
    chmod -R a+rX,go-w "$directory"
  }

  if [[ -x "$codex_executable" && \
    "$("$codex_executable" --version 2>/dev/null || true)" == "codex-cli $MELLOA_CODEX_CLI_VERSION" ]]; then
    secure_private_codex_dir "$codex_dir"
    verify_codex_cli
    return 0
  fi
  if [[ -e "$codex_dir" || -L "$codex_dir" ]]; then
    [[ -d "$codex_dir" && ! -L "$codex_dir" ]] ||
      fail "existing private Codex CLI directory is unsafe"
  fi

  install -m 0600 /dev/null "$npm_user_config"
  install -m 0600 /dev/null "$npm_global_config"
  codex_integrity="$(
    NPM_CONFIG_USERCONFIG="$npm_user_config" NPM_CONFIG_GLOBALCONFIG="$npm_global_config" \
      NPM_CONFIG_CACHE="$DOWNLOAD_DIR/npm-cache" "$npm" view --registry="$npm_registry" \
      "${npm_ca_option[@]}" "$codex_package" dist.integrity
  )"
  codex_platform_integrity="$(
    NPM_CONFIG_USERCONFIG="$npm_user_config" NPM_CONFIG_GLOBALCONFIG="$npm_global_config" \
      NPM_CONFIG_CACHE="$DOWNLOAD_DIR/npm-cache" "$npm" view --registry="$npm_registry" \
      "${npm_ca_option[@]}" "$codex_platform_package" dist.integrity
  )"
  [[ "$codex_integrity" == "$MELLOA_CODEX_NPM_INTEGRITY" ]] ||
    fail "Codex CLI npm integrity changed"
  [[ "$codex_platform_integrity" == "$MELLOA_CODEX_LINUX_X64_NPM_INTEGRITY" ]] ||
    fail "Codex CLI Linux binary npm integrity changed"

  CODEX_STAGING_DIR="$(mktemp -d "$MELLOA_TOOLCHAIN_DIR/.codex.XXXXXX")"
  NPM_CONFIG_USERCONFIG="$npm_user_config" NPM_CONFIG_GLOBALCONFIG="$npm_global_config" \
    NPM_CONFIG_CACHE="$DOWNLOAD_DIR/npm-cache" \
    "$npm" install --global --prefix "$CODEX_STAGING_DIR" --registry="$npm_registry" \
      "${npm_ca_option[@]}" --ignore-scripts --no-audit --no-fund --omit=dev "$codex_package"
  verify_codex_cli_path "$CODEX_STAGING_DIR/bin/codex"

  if [[ -d "$codex_dir" && ! -L "$codex_dir" ]]; then
    rm -rf -- "$codex_dir"
  fi
  mv "$CODEX_STAGING_DIR" "$codex_dir"
  CODEX_STAGING_DIR=""
  secure_private_codex_dir "$codex_dir"
  verify_codex_cli
}
BOOTSTRAP_PHASE="installing base apt prerequisites"
apt-get "${apt_options[@]}" update
apt-get "${apt_options[@]}" install --yes --no-install-recommends ca-certificates curl gnupg

DOWNLOAD_DIR="$(mktemp -d /var/tmp/melloa-bootstrap.XXXXXX)"
DOCKER_ALREADY_COMPATIBLE=false
if docker_compose_is_supported; then
  DOCKER_ALREADY_COMPATIBLE=true
elif command -v docker >/dev/null 2>&1 || existing_docker_package_is_present; then
  fail "existing Docker installation does not provide Docker Compose $MELLOA_DOCKER_COMPOSE_MIN_VERSION or newer; bootstrap will not replace an existing container toolchain. Upgrade Docker deliberately, then rerun bootstrap"
fi

if [[ "$DOCKER_ALREADY_COMPATIBLE" == false ]]; then
  configure_docker_apt_source
fi

BOOTSTRAP_PHASE="installing required host packages"
apt-get "${apt_options[@]}" update
declare -a host_packages=(
  bash bubblewrap coreutils findutils git grep jq make mawk passwd procps rsync sed systemd tar
  util-linux xz-utils
)
if [[ "$DOCKER_ALREADY_COMPATIBLE" == false ]]; then
  host_packages+=(docker-buildx-plugin docker-ce docker-ce-cli docker-compose-plugin)
fi
apt-get "${apt_options[@]}" install --yes --no-install-recommends "${host_packages[@]}"

ensure_toolchain_layout
select_node_and_npm

select_uv

select_python

select_go

export PATH="$MELLOA_RUNTIME_PATH"

if [[ "$SELF_CHANGE_TOOLS" == true ]]; then
  BOOTSTRAP_PHASE="installing private Codex CLI"
  install_codex_cli
fi

BOOTSTRAP_PHASE="verifying installed host toolchain"
verify_toolchain

if [[ "$CONTAINER_SMOKE" == true ]]; then
  echo "Disposable $HOST_LABEL bootstrap toolchain smoke test passed."
  exit 0
fi

systemctl enable --now containerd.service docker.service >/dev/null
systemctl is-active --quiet docker.service || fail "Docker did not become active"
systemctl is-enabled --quiet docker.service || fail "Docker is not enabled for reboot"
docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable after installation"
BOOTSTRAP_PHASE="running server preflight"
"$SOURCE/infra/server/preflight.sh" --source "$SOURCE" --origin "$ORIGIN"

echo "Melloa server prerequisites are installed and verified on $HOST_LABEL."
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
