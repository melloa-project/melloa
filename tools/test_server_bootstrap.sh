#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly BOOTSTRAP="$ROOT/infra/server/bootstrap-debian.sh"
readonly BOOTSTRAP_PUBLIC="$ROOT/infra/server/bootstrap-linux.sh"
readonly WORKDIR="$(mktemp -d /tmp/melloa-bootstrap-test.XXXXXX)"
CURRENT_PHASE="initial bootstrap smoke setup"
# shellcheck disable=SC1091
source "$ROOT/infra/server/toolchain.lock"

cleanup() {
  local status=$?
  if [[ "$status" != 0 ]]; then
    printf '::error title=Server bootstrap smoke failed::%s\n' "$CURRENT_PHASE" >&2
  fi
  if [[ "$WORKDIR" == /tmp/melloa-bootstrap-test.* && -d "$WORKDIR" ]]; then
    rm -rf -- "$WORKDIR"
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

CURRENT_PHASE="validating bootstrap lock and script invariants"
[[ "$MELLOA_SUPPORTED_HOSTS" == *debian-13-trixie* ]]
[[ "$MELLOA_SUPPORTED_HOSTS" == *ubuntu-24.04-noble* ]]
[[ "$MELLOA_SUPPORTED_HOSTS" == *pop-24.04-noble* ]]
[[ "$MELLOA_SERVER_ARCHITECTURE" == amd64 ]]
[[ "$MELLOA_DEBIAN_TEST_IMAGE" == debian:13-slim@sha256:* ]]
[[ "$MELLOA_UBUNTU_TEST_IMAGE" == ubuntu:24.04@sha256:* ]]
[[ "$MELLOA_DOCKER_COMPOSE_MIN_VERSION" == 2.27.0 ]]
[[ "$MELLOA_PYTHON_MIN_VERSION" == 3.13.3 ]]
[[ "$MELLOA_PYTHON_VERSION" =~ ^3\.13\.[0-9]+$ ]]
[[ "$MELLOA_NODE_MIN_VERSION" == 22.18.0 ]]
[[ "$MELLOA_NODE_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$MELLOA_GO_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$MELLOA_GO_MIN_VERSION" == "$MELLOA_GO_VERSION" ]]
[[ "$MELLOA_GO_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$MELLOA_UV_MIN_VERSION" == 0.12.0 ]]
[[ "$MELLOA_UV_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$MELLOA_CODEX_NPM_INTEGRITY" == sha512-* ]]
[[ "$MELLOA_CODEX_LINUX_X64_NPM_INTEGRITY" == sha512-* ]]
grep --fixed-strings --quiet -- "SELF_CHANGE_TOOLS=false" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- "--self-change-tools" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- "--print-host-profile" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- "supported hosts are" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- "UV_PYTHON_DOWNLOADS=manual" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- "MELLOA_TOOLCHAIN_DIR=/opt/melloa/toolchain" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- "melloa_version_at_least" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- "find_supported_host_python" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- "docker_apt_source_exists" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- "Melloa's private Codex CLI" \
  "$BOOTSTRAP"
! grep --fixed-strings --quiet -- "/usr/local/bin/codex" "$BOOTSTRAP"
! grep --fixed-strings --quiet -- "install_managed_link" "$BOOTSTRAP"
grep --fixed-strings --quiet -- "go.dev/dl/\$GO_BASENAME.tar.gz" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- 'if [[ "$SELF_CHANGE_TOOLS" == true ]]; then' \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- \
  "Next create the Guardian public handoff if it is not already beside this checkout:" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- \
  "%q --print-input-checklist" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- \
  "Then run the guided first install:" \
  "$BOOTSTRAP"
grep --fixed-strings --quiet -- \
  'exec "$ROOT/infra/server/bootstrap-debian.sh" "$@"' \
  "$BOOTSTRAP_PUBLIC"

cat >"$WORKDIR/debian.os-release" <<'EOF'
ID=debian
VERSION_ID=13
VERSION_CODENAME=trixie
EOF
ln --symbolic "$WORKDIR/debian.os-release" "$WORKDIR/debian-os-release-link"
cat >"$WORKDIR/ubuntu.os-release" <<'EOF'
ID=ubuntu
VERSION_ID=24.04
VERSION_CODENAME=noble
UBUNTU_CODENAME=noble
EOF
cat >"$WORKDIR/pop.os-release" <<'EOF'
ID=pop
ID_LIKE="ubuntu debian"
VERSION_ID=24.04
VERSION_CODENAME=noble
UBUNTU_CODENAME=noble
EOF

CURRENT_PHASE="resolving supported host profiles from os-release fixtures"
[[ "$("$BOOTSTRAP" --print-host-profile "$WORKDIR/debian.os-release")" == \
  $'debian-13-trixie\tDebian 13 (trixie)\tdebian\ttrixie' ]]
[[ "$("$BOOTSTRAP" --print-host-profile "$WORKDIR/debian-os-release-link")" == \
  $'debian-13-trixie\tDebian 13 (trixie)\tdebian\ttrixie' ]]
[[ "$("$BOOTSTRAP" --print-host-profile "$WORKDIR/ubuntu.os-release")" == \
  $'ubuntu-24.04-noble\tUbuntu 24.04 LTS (noble)\tubuntu\tnoble' ]]
[[ "$("$BOOTSTRAP" --print-host-profile "$WORKDIR/pop.os-release")" == \
  $'pop-24.04-noble\tPop!_OS 24.04 (noble)\tubuntu\tnoble' ]]

declare -a proxy_environment=()
for variable in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
  if [[ -n "${!variable:-}" ]]; then
    proxy_environment+=(--env "$variable")
  fi
done

host_ca="${MELLOA_BUILD_CA_FILE:-}"
if [[ -z "$host_ca" ]]; then
  for candidate in \
    /etc/ssl/certs/ca-certificates.crt \
    /etc/pki/tls/certs/ca-bundle.crt \
    /opt/bb/share/ssl/cert.pem; do
    if [[ -f "$candidate" ]]; then
      host_ca="$candidate"
      break
    fi
  done
fi
[[ -f "$host_ca" ]]

pull_image() {
  local image="$1"
  local image_available=false
  CURRENT_PHASE="pulling bootstrap smoke image $image"
  if docker image inspect "$image" >/dev/null 2>&1; then
    image_available=true
  else
    for _ in 1 2 3; do
      if docker pull --platform linux/amd64 "$image" >/dev/null; then
        image_available=true
        break
      fi
      sleep 5
    done
  fi
  if [[ "$image_available" != true ]]; then
    echo "Server bootstrap smoke test failed: unable to pull $image from Docker Hub after 3 attempts." >&2
    echo "Check Docker registry access, proxy/CA configuration, and Docker Hub availability, then rerun make server-bootstrap." >&2
    exit 1
  fi
}

run_container_smoke() {
  local image="$1"
  pull_image "$image"
  CURRENT_PHASE="running bootstrap container smoke for $image"
  docker run --rm --platform linux/amd64 \
    "${proxy_environment[@]}" \
    --volume "$host_ca:/run/melloa-bootstrap-ca.pem:ro" \
    --volume "$ROOT:/source:ro" \
    "$image" \
    /bin/bash /source/infra/server/bootstrap-linux.sh \
      --source /source \
      --ca-file /run/melloa-bootstrap-ca.pem \
      --container-smoke
}

run_container_smoke "$MELLOA_DEBIAN_TEST_IMAGE"
run_container_smoke "$MELLOA_UBUNTU_TEST_IMAGE"
