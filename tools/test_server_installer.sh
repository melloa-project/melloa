#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-installer-test.XXXXXX)"

cleanup() {
  if [[ "$WORKDIR" == /tmp/melloa-installer-test.* && -d "$WORKDIR" ]]; then
    rm -rf -- "$WORKDIR"
  fi
}
trap cleanup EXIT HUP INT TERM

"$ROOT/infra/server/install.sh" --source "$ROOT" --root "$WORKDIR" >/dev/null

[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/codex")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/self-change-verify")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/etc/systemd/system/melloa-release-recovery.service")" == 644 ]]
[[ "$(stat --format='%a' "$WORKDIR/etc/melloa/server.env")" == 600 ]]
[[ "$(stat --format='%a' "$WORKDIR/etc/melloa/private/codex-api-key")" == 600 ]]
[[ "$(stat --format='%a' "$WORKDIR/var/lib/melloa/applier-home/.gitconfig")" == 600 ]]
[[ "$(stat --format='%a' "$WORKDIR/opt/melloa/worker/src/melloa/__init__.py")" == 644 ]]
cmp --silent \
  "$ROOT/infra/server/systemd/melloa-self-change-planner.service" \
  "$WORKDIR/etc/systemd/system/melloa-self-change-planner.service"
cmp --silent \
  <(git -C "$ROOT" ls-tree -r --name-only HEAD README.md pyproject.toml uv.lock src migrations | sort) \
  <(
    cd "$WORKDIR/opt/melloa/worker"
    find README.md pyproject.toml uv.lock src migrations -type f -printf '%p\n' | sort
  )

printf 'MELLOA_CODEX_USE_API_KEY=false\n' >"$WORKDIR/etc/melloa/self-change.env"
"$ROOT/infra/server/install.sh" --source "$ROOT" --root "$WORKDIR" >/dev/null
[[ "$(<"$WORKDIR/etc/melloa/self-change.env")" == MELLOA_CODEX_USE_API_KEY=false ]]

mv "$WORKDIR/etc/melloa/server.env" "$WORKDIR/etc/melloa/server.env.owner-copy"
ln -s server.env.owner-copy "$WORKDIR/etc/melloa/server.env"
if "$ROOT/infra/server/install.sh" --source "$ROOT" --root "$WORKDIR" >/dev/null 2>&1; then
  echo "Installer accepted a symlinked owner configuration" >&2
  exit 1
fi

echo "Server service asset staging and owner-config preservation passed."
