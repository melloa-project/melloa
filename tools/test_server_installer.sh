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

grep --fixed-strings --quiet -- \
  "Next create the Guardian public handoff if it is not already beside this checkout:" \
  "$ROOT/infra/server/bootstrap-debian.sh"
grep --fixed-strings --quiet -- \
  "%q --print-input-checklist" \
  "$ROOT/infra/server/bootstrap-debian.sh"
grep --fixed-strings --quiet -- \
  "Then run the guided first install:" \
  "$ROOT/infra/server/bootstrap-debian.sh"

"$ROOT/infra/server/install.sh" --source "$ROOT" --root "$WORKDIR" >/dev/null

[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/codex")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/activate")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/configure")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/first-install")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/qualification-record")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/rollback")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/restore-drill")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/update")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/verify-owner-journey")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/self-change-enabled")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/usr/local/libexec/melloa/self-change-verify")" == 755 ]]
[[ "$(stat --format='%a' "$WORKDIR/etc/systemd/system/melloa-release-recovery.service")" == 644 ]]
grep --fixed-strings --quiet \
  "Before=melloa-self-change-planner.service melloa-self-change-applier.service" \
  "$WORKDIR/etc/systemd/system/melloa-release-recovery.service"
for worker_unit in melloa-self-change-planner.service melloa-self-change-applier.service; do
  grep --fixed-strings --quiet "Requires=melloa-release-recovery.service" \
    "$WORKDIR/etc/systemd/system/$worker_unit"
  grep --fixed-strings --quiet "After=melloa-release-recovery.service" \
    "$WORKDIR/etc/systemd/system/$worker_unit"
  grep --fixed-strings --quiet "ExecCondition=/usr/local/libexec/melloa/self-change-enabled" \
    "$WORKDIR/etc/systemd/system/$worker_unit"
done
grep --fixed-strings --quiet "MELLOA_SELF_CHANGE_ENABLED=false" \
  "$WORKDIR/etc/melloa/self-change.env"
grep --fixed-strings --quiet "MELLOA_CODEX_USE_API_KEY=false" \
  "$WORKDIR/etc/melloa/self-change.env"
MELLOA_SELF_CHANGE_ENABLED=true \
  "$WORKDIR/usr/local/libexec/melloa/self-change-enabled"
set +e
MELLOA_SELF_CHANGE_ENABLED=false \
  "$WORKDIR/usr/local/libexec/melloa/self-change-enabled" >/dev/null 2>&1
status=$?
set -e
[[ "$status" == 1 ]]
set +e
MELLOA_SELF_CHANGE_ENABLED=maybe \
  "$WORKDIR/usr/local/libexec/melloa/self-change-enabled" >/dev/null 2>&1
status=$?
set -e
[[ "$status" == 255 ]]
set +e
CREDENTIALS_DIRECTORY="$WORKDIR" MELLOA_SELF_CHANGE_ENABLED=false \
  "$WORKDIR/usr/local/libexec/melloa/self-change-plan" >/dev/null 2>&1
status=$?
set -e
[[ "$status" == 2 ]]
set +e
CREDENTIALS_DIRECTORY="$WORKDIR" MELLOA_SELF_CHANGE_ENABLED=false \
  "$WORKDIR/usr/local/libexec/melloa/self-change-apply" >/dev/null 2>&1
status=$?
set -e
[[ "$status" == 2 ]]
[[ "$(stat --format='%a' "$WORKDIR/etc/melloa/server.env")" == 600 ]]
[[ "$(stat --format='%a' "$WORKDIR/etc/melloa/private/codex-api-key")" == 600 ]]
[[ "$(stat --format='%a' "$WORKDIR/var/lib/melloa/applier-home/.gitconfig")" == 600 ]]
[[ "$(stat --format='%a' "$WORKDIR/opt/melloa/worker/src/melloa/__init__.py")" == 644 ]]
[[ -f "$WORKDIR/opt/melloa/worker/src/melloa/apps/telegram_pairing.py" ]]
grep --fixed-strings --quiet \
  'melloa-pair-telegram = "melloa.apps.telegram_pairing:main"' \
  "$WORKDIR/opt/melloa/worker/pyproject.toml"
cmp --silent \
  "$ROOT/infra/server/systemd/melloa-self-change-planner.service" \
  "$WORKDIR/etc/systemd/system/melloa-self-change-planner.service"
cmp --silent \
  <(git -C "$ROOT" ls-tree -r --name-only HEAD README.md pyproject.toml uv.lock src migrations | sort) \
  <(
    cd "$WORKDIR/opt/melloa/worker"
    find README.md pyproject.toml uv.lock src migrations -type f -printf '%p\n' | sort
  )

printf 'MELLOA_SELF_CHANGE_ENABLED=false\nMELLOA_CODEX_USE_API_KEY=false\n' \
  >"$WORKDIR/etc/melloa/self-change.env"
"$ROOT/infra/server/install.sh" --source "$ROOT" --root "$WORKDIR" >/dev/null
[[ "$(<"$WORKDIR/etc/melloa/self-change.env")" == \
  $'MELLOA_SELF_CHANGE_ENABLED=false\nMELLOA_CODEX_USE_API_KEY=false' ]]

mv "$WORKDIR/etc/melloa/server.env" "$WORKDIR/etc/melloa/server.env.owner-copy"
ln -s server.env.owner-copy "$WORKDIR/etc/melloa/server.env"
if "$ROOT/infra/server/install.sh" --source "$ROOT" --root "$WORKDIR" >/dev/null 2>&1; then
  echo "Installer accepted a symlinked owner configuration" >&2
  exit 1
fi

echo "Server service asset staging and owner-config preservation passed."
