#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly CHECKOUT="${1:-}"
readonly PYTHON_ENV="${MELLOA_VERIFIER_PYTHON_ENV:-}"
readonly NODE_MODULES="${MELLOA_VERIFIER_NODE_MODULES:-}"
readonly TOOLCHAIN_DIR=/opt/melloa/toolchain

fail() {
  echo "Self-change verification environment rejected" >&2
  exit 2
}

require_directory() {
  local path="$1"
  [[ "$path" == /* && -d "$path" && ! -L "$path" ]] || fail
}

require_directory "$CHECKOUT"
require_directory "$PYTHON_ENV"
require_directory "$NODE_MODULES"
require_directory "$TOOLCHAIN_DIR"
[[ -f "$CHECKOUT/Makefile" && ! -L "$CHECKOUT/Makefile" ]] || fail
[[ -d "$CHECKOUT/apps/web" && ! -L "$CHECKOUT/apps/web" ]] || fail
command -v bwrap >/dev/null 2>&1 || fail
command -v make >/dev/null 2>&1 || fail
command -v readlink >/dev/null 2>&1 || fail

declare -a RUNTIME_MOUNTS=(--ro-bind /usr /usr)

add_runtime_path() {
  local path="$1"
  local target
  if [[ -L "$path" ]]; then
    target="$(readlink -- "$path")"
    [[ -n "$target" && "$target" != *$'\n'* ]] || fail
    RUNTIME_MOUNTS+=(--symlink "$target" "$path")
  elif [[ -d "$path" ]]; then
    RUNTIME_MOUNTS+=(--ro-bind "$path" "$path")
  elif [[ -e "$path" ]]; then
    fail
  fi
}

for runtime_path in /bin /sbin /lib /lib64; do
  add_runtime_path "$runtime_path"
done

readonly VENV_TARGET="$CHECKOUT/.venv"
readonly MODULES_TARGET="$CHECKOUT/apps/web/node_modules"
[[ ! -e "$VENV_TARGET" && ! -e "$MODULES_TARGET" ]] || fail
install -d -m 0700 "$VENV_TARGET" "$MODULES_TARGET"

cleanup() {
  rmdir "$MODULES_TARGET" "$VENV_TARGET" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

readonly SANDBOX_PYTHON_ENV=/opt/melloa-verifier/.venv

bwrap \
  --die-with-parent \
  --new-session \
  --unshare-all \
  "${RUNTIME_MOUNTS[@]}" \
  --dev /dev \
  --proc /proc \
  --tmpfs /tmp \
  --dir /home \
  --dir /home/verifier \
  --dir /opt \
  --dir /opt/melloa-verifier \
  --bind "$CHECKOUT" "$CHECKOUT" \
  --ro-bind "$TOOLCHAIN_DIR" "$TOOLCHAIN_DIR" \
  --ro-bind "$PYTHON_ENV" "$SANDBOX_PYTHON_ENV" \
  --ro-bind "$PYTHON_ENV" "$VENV_TARGET" \
  --ro-bind "$NODE_MODULES" "$MODULES_TARGET" \
  --chdir "$CHECKOUT" \
  --setenv HOME /home/verifier \
  --setenv PATH "$SANDBOX_PYTHON_ENV/bin:/opt/melloa/toolchain/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  --setenv PYTHONPATH "$CHECKOUT/src" \
  --setenv UV_CACHE_DIR /tmp/uv-cache \
  --setenv UV_NO_PROGRESS 1 \
  --setenv UV_NO_SYNC 1 \
  --setenv UV_SYSTEM_CERTS 1 \
  --setenv npm_config_cache /tmp/npm-cache \
  /usr/bin/make check
