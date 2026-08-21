#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-toolchain-test.XXXXXX)"
# shellcheck disable=SC1091
source "$ROOT/infra/server/toolchain.sh"

cleanup() {
  local status=$?
  if [[ "$WORKDIR" == /tmp/melloa-toolchain-test.* && -d "$WORKDIR" ]]; then
    rm -rf -- "$WORKDIR"
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

make_fake_tool() {
  local path="$1"
  local output="$2"
  install -d -m 0755 "$(dirname "$path")"
  printf '#!/usr/bin/env bash\nprintf %%s\\n %q\n' "$output" >"$path"
  chmod 0755 "$path"
}

[[ "$(melloa_normalize_version v22.18.0)" == 22.18.0 ]]
[[ "$(melloa_normalize_version go1.27.0+reviewed)" == 1.27.0 ]]
melloa_version_at_least 24.1.2 22.18.0
melloa_version_at_least 22.18.0 22.18.0
! melloa_version_at_least 22.17.9 22.18.0
! melloa_version_at_least invalid 22.18.0
melloa_python_version_is_supported 3.14.1 3.13.3
melloa_python_version_is_supported 3.13.3 3.13.3
! melloa_python_version_is_supported 3.13.2 3.13.3
! melloa_python_version_is_supported 4.0.0 3.13.3

readonly HOST_BIN="$WORKDIR/host-bin"
readonly TOOLCHAIN_BIN="$WORKDIR/melloa-toolchain/bin"
make_fake_tool "$HOST_BIN/node" v24.1.2
make_fake_tool "$HOST_BIN/npm" 11.3.0

[[ "$(melloa_find_host_command "$HOST_BIN" node)" == "$HOST_BIN/node" ]]
! melloa_find_host_command "$HOST_BIN" go
! melloa_tool_link_is_usable "$TOOLCHAIN_BIN" node

melloa_link_tool "$TOOLCHAIN_BIN" node "$HOST_BIN/node"
melloa_link_tool "$TOOLCHAIN_BIN" npm "$HOST_BIN/npm"
melloa_tool_link_is_usable "$TOOLCHAIN_BIN" node
melloa_tool_link_is_usable "$TOOLCHAIN_BIN" npm
[[ "$(readlink "$TOOLCHAIN_BIN/node")" == "$HOST_BIN/node" ]]

# A second bootstrap selection must be idempotent: it refreshes only Melloa's own symlink and
# does not need to own or rewrite the host executable.
melloa_link_tool "$TOOLCHAIN_BIN" node "$HOST_BIN/node"
[[ "$(readlink "$TOOLCHAIN_BIN/node")" == "$HOST_BIN/node" ]]

install -m 0644 /dev/null "$TOOLCHAIN_BIN/blocked"
! melloa_link_tool "$TOOLCHAIN_BIN" blocked "$HOST_BIN/node"

readonly LIST_APT_ROOT="$WORKDIR/list-apt"
install -d -m 0755 "$LIST_APT_ROOT/etc/apt/sources.list.d"
printf '%s\n' \
  'deb [arch=amd64 signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/debian trixie stable' \
  >"$LIST_APT_ROOT/etc/apt/sources.list.d/docker.list"
melloa_docker_apt_source_exists "$LIST_APT_ROOT" debian trixie
! melloa_docker_apt_source_exists "$LIST_APT_ROOT" debian bookworm

readonly DEB822_APT_ROOT="$WORKDIR/deb822-apt"
install -d -m 0755 "$DEB822_APT_ROOT/etc/apt/sources.list.d"
printf '%s\n' \
  'Types: deb' \
  'URIs: https://download.docker.com/linux/ubuntu' \
  'Suites: noble' \
  'Components: stable' \
  'Signed-By: /usr/share/keyrings/docker.gpg' \
  >"$DEB822_APT_ROOT/etc/apt/sources.list.d/docker.sources"
melloa_docker_apt_source_exists "$DEB822_APT_ROOT" ubuntu noble
