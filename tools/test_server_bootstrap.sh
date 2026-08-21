#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/infra/server/toolchain.lock"

[[ "$MELLOA_SERVER_OS_ID" == debian ]]
[[ "$MELLOA_SERVER_OS_VERSION" == 13 ]]
[[ "$MELLOA_SERVER_OS_CODENAME" == trixie ]]
[[ "$MELLOA_SERVER_ARCHITECTURE" == amd64 ]]
[[ "$MELLOA_NODE_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$MELLOA_GO_MIN_VERSION" == 1.24 ]]
[[ "$MELLOA_UV_SHA256" =~ ^[0-9a-f]{64}$ ]]
[[ "$MELLOA_CODEX_NPM_INTEGRITY" == sha512-* ]]
[[ "$MELLOA_CODEX_LINUX_X64_NPM_INTEGRITY" == sha512-* ]]
grep --fixed-strings --quiet -- "SELF_CHANGE_TOOLS=false" \
  "$ROOT/infra/server/bootstrap-debian.sh"
grep --fixed-strings --quiet -- "--self-change-tools" \
  "$ROOT/infra/server/bootstrap-debian.sh"
grep --fixed-strings --quiet -- 'if [[ "$SELF_CHANGE_TOOLS" == true ]]; then' \
  "$ROOT/infra/server/bootstrap-debian.sh"
grep --fixed-strings --quiet -- \
  "Next create the Guardian public handoff if it is not already beside this checkout:" \
  "$ROOT/infra/server/bootstrap-debian.sh"
grep --fixed-strings --quiet -- \
  "%q --print-input-checklist" \
  "$ROOT/infra/server/bootstrap-debian.sh"
grep --fixed-strings --quiet -- \
  "Then run the guided first install:" \
  "$ROOT/infra/server/bootstrap-debian.sh"

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

image_available=false
if docker image inspect "$MELLOA_DEBIAN_TEST_IMAGE" >/dev/null 2>&1; then
  image_available=true
else
  for _ in 1 2 3; do
    if docker pull --platform linux/amd64 "$MELLOA_DEBIAN_TEST_IMAGE" >/dev/null; then
      image_available=true
      break
    fi
    sleep 5
  done
fi
if [[ "$image_available" != true ]]; then
  echo "Server bootstrap smoke test failed: unable to pull $MELLOA_DEBIAN_TEST_IMAGE from Docker Hub after 3 attempts." >&2
  echo "Check Docker registry access, proxy/CA configuration, and Docker Hub availability, then rerun make server-bootstrap." >&2
  exit 1
fi

docker run --rm --platform linux/amd64 \
  "${proxy_environment[@]}" \
  --volume "$host_ca:/run/melloa-bootstrap-ca.pem:ro" \
  --volume "$ROOT:/source:ro" \
  "$MELLOA_DEBIAN_TEST_IMAGE" \
  /bin/bash /source/infra/server/bootstrap-debian.sh \
    --source /source \
    --ca-file /run/melloa-bootstrap-ca.pem \
    --container-smoke
