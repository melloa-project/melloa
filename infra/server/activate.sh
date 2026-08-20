#!/usr/bin/env bash
set -euo pipefail

umask 077

SOURCE=/srv/melloa/release-source
ORIGIN=https://github.com/melloa-project/melloa.git
INITIALIZE_BACKUP=false

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/activate.sh [--source PATH] [--origin HTTPS_URL] [--initialize-backup]

Builds and checks the exact installed revision, deploys it, proves one encrypted backup,
and enables boot recovery plus bounded self-change workers when configured. It is safe to rerun.
--initialize-backup is required only for a new, independently mounted restic repository.
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
    --initialize-backup)
      INITIALIZE_BACKUP=true
      shift
      ;;
    *)
      usage
      ;;
  esac
done

fail() {
  echo "Server activation failed: $1" >&2
  exit 1
}

activation_rerun_command() {
  local command_line
  local -a command=(
    sudo /usr/local/libexec/melloa/activate
    --source "$SOURCE"
    --origin "$ORIGIN"
  )
  if [[ "$INITIALIZE_BACKUP" == true ]]; then
    command+=(--initialize-backup)
  fi
  printf -v command_line '%q ' "${command[@]}"
  printf '%s' "${command_line% }"
}

((EUID == 0)) || fail "activation must run as root"
[[ "$SOURCE" == /* && -d "$SOURCE/.git" && ! -L "$SOURCE" && ! -L "$SOURCE/.git" ]] ||
  fail "source must be an absolute Git checkout"

readonly ENV_FILE=/etc/melloa/server.env
readonly SELF_CHANGE_ENV=/etc/melloa/self-change.env
readonly RELEASE_SOURCE=/srv/melloa/release-source
readonly STATE_DIR=/var/lib/melloa/release-state
readonly RUNTIME_STATE_DIR=/var/lib/melloa/runtime-state

"$SOURCE/infra/server/preflight.sh" --source "$SOURCE" --origin "$ORIGIN" --installed

readonly REVISION="$(git -C "$SOURCE" rev-parse HEAD)"
[[ "$(git -C "$RELEASE_SOURCE" rev-parse HEAD)" == "$REVISION" ]] ||
  fail "installed release checkout does not match the reviewed source"
readonly APP_IMAGE="melloa-local/server:$REVISION"
readonly BACKUP_IMAGE="melloa-local/backup:$REVISION"
BACKUP_STOPPED=false

compose() {
  MELLOA_SOURCE_REVISION="$REVISION" \
  MELLOA_IMAGE="$APP_IMAGE" \
  MELLOA_BACKUP_IMAGE="$BACKUP_IMAGE" \
  MELLOA_RELEASE_STATE_DIR="$STATE_DIR" \
    docker compose \
      --project-directory "$RELEASE_SOURCE" \
      --env-file "$ENV_FILE" \
      --file "$RELEASE_SOURCE/compose.server.yaml" \
      "$@"
}

ensure_backup_running() {
  if [[ "$BACKUP_STOPPED" == true ]]; then
    compose start backup >/dev/null || true
  fi
}

self_change_enabled() {
  local count
  local value
  [[ -f "$SELF_CHANGE_ENV" && ! -L "$SELF_CHANGE_ENV" ]] ||
    fail "self-change environment file is unavailable"
  count="$(awk -F= '$1 == "MELLOA_SELF_CHANGE_ENABLED" {count += 1} END {print count + 0}' \
    "$SELF_CHANGE_ENV")"
  [[ "$count" == 1 ]] || fail "MELLOA_SELF_CHANGE_ENABLED must occur exactly once"
  value="$(awk -F= '$1 == "MELLOA_SELF_CHANGE_ENABLED" {print $2}' "$SELF_CHANGE_ENV")"
  [[ "$value" == true || "$value" == false ]] ||
    fail "MELLOA_SELF_CHANGE_ENABLED must be true or false"
  printf '%s' "$value"
}

compose config --quiet
if ! compose build melloa backup; then
  fail "container image build failed; check Docker registry access, proxy/CA configuration, and rerun activation. If this server uses a private CA, rerun bootstrap and first install with --ca-file so /etc/melloa/build-ca.pem is configured"
fi
compose run --rm --no-deps melloa \
  deployment-check \
  --status /run/melloa/guardian/status.json \
  --public-key /run/melloa/guardian/public.pem \
  --capable-model-config /run/melloa/private/capable-model.json \
  --economy-model-config /run/melloa/private/economy-model.json \
  --telegram-owner-config /run/melloa/private/telegram-owner.json \
  --telegram-bot-token-file /run/melloa/private/telegram-bot-token ||
  fail "pre-activation live Guardian, model, or Telegram check failed; fix the reported cause, then rerun $(activation_rerun_command)"

if ! compose run --rm --no-deps backup check; then
  if [[ "$INITIALIZE_BACKUP" == false ]]; then
    fail "encrypted backup repository is not initialized; inspect its mount and rerun with --initialize-backup only for a new repository"
  fi
  compose run --rm --no-deps backup init
  compose run --rm --no-deps backup check ||
    fail "new encrypted backup repository did not pass its integrity check"
fi

systemctl enable melloa-release-recovery.service >/dev/null
systemctl start melloa-release-recovery.service

if ! "$RELEASE_SOURCE/tools/server_release.sh" deploy \
  --env-file "$ENV_FILE" \
  --state-dir "$STATE_DIR" \
  --revision "$REVISION" \
  --app-image "$APP_IMAGE" \
  --backup-image "$BACKUP_IMAGE" \
  --no-build; then
  fail "release deployment failed; run sudo systemctl start melloa-release-recovery.service, then rerun $(activation_rerun_command)"
fi

compose stop backup >/dev/null
BACKUP_STOPPED=true
trap ensure_backup_running EXIT
if ! compose run --rm --no-deps backup once; then
  fail "the first post-activation encrypted backup failed; fix the reported backup cause, run sudo systemctl start melloa-release-recovery.service, then rerun $(activation_rerun_command)"
fi
compose start backup >/dev/null
BACKUP_STOPPED=false
trap - EXIT
[[ -f "$RUNTIME_STATE_DIR/backup-status.json" && ! -L "$RUNTIME_STATE_DIR/backup-status.json" ]] ||
  fail "the first backup did not leave a protected status receipt"
readonly SNAPSHOT="$(jq -er 'select(.result == "success") | .snapshot_id' \
  "$RUNTIME_STATE_DIR/backup-status.json")"
[[ "$SNAPSHOT" =~ ^[0-9a-f]{64}$ ]] || fail "the first backup receipt is invalid"

systemctl enable \
  melloa-release-recovery.service >/dev/null
if [[ "$(self_change_enabled)" == true ]]; then
  systemctl enable \
    melloa-self-change-planner.service \
    melloa-self-change-applier.service >/dev/null
  systemctl restart \
    melloa-self-change-planner.service \
    melloa-self-change-applier.service
else
  systemctl disable --now \
    melloa-self-change-planner.service \
    melloa-self-change-applier.service >/dev/null 2>&1 || true
  echo "Self-change workers are disabled; this deployment remains conversation-only until self-change is enabled and exercised."
fi
sleep 2
for service in melloa-release-recovery.service; do
  systemctl is-active --quiet "$service" || fail "service did not remain active: $service"
  systemctl is-enabled --quiet "$service" || fail "service is not enabled for reboot: $service"
done
if [[ "$(self_change_enabled)" == true ]]; then
  for service in \
    melloa-self-change-planner.service \
    melloa-self-change-applier.service; do
    systemctl is-active --quiet "$service" || fail "service did not remain active: $service"
    systemctl is-enabled --quiet "$service" || fail "service is not enabled for reboot: $service"
  done
fi

echo "Server revision $REVISION is active with encrypted snapshot ${SNAPSHOT:0:12}."
echo "The deployed owner journey must still be exercised before README readiness can change."
