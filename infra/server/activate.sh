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
and enables boot recovery plus the self-change workers. It is safe to rerun.
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

((EUID == 0)) || fail "activation must run as root"
[[ "$SOURCE" == /* && -d "$SOURCE/.git" && ! -L "$SOURCE" && ! -L "$SOURCE/.git" ]] ||
  fail "source must be an absolute Git checkout"

readonly ENV_FILE=/etc/melloa/server.env
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

compose config --quiet
compose build melloa backup
compose run --rm --no-deps melloa \
  deployment-check \
  --status /run/melloa/guardian/status.json \
  --public-key /run/melloa/guardian/public.pem \
  --capable-model-config /run/melloa/private/capable-model.json \
  --economy-model-config /run/melloa/private/economy-model.json \
  --telegram-owner-config /run/melloa/private/telegram-owner.json \
  --telegram-bot-token-file /run/melloa/private/telegram-bot-token

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

"$RELEASE_SOURCE/tools/server_release.sh" deploy \
  --env-file "$ENV_FILE" \
  --state-dir "$STATE_DIR" \
  --revision "$REVISION" \
  --app-image "$APP_IMAGE" \
  --backup-image "$BACKUP_IMAGE" \
  --no-build

compose stop backup >/dev/null
BACKUP_STOPPED=true
trap ensure_backup_running EXIT
if ! compose run --rm --no-deps backup once; then
  fail "the first post-activation encrypted backup failed"
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
  melloa-self-change-planner.service \
  melloa-self-change-applier.service >/dev/null
systemctl restart \
  melloa-self-change-planner.service \
  melloa-self-change-applier.service
sleep 2
for service in \
  melloa-release-recovery.service \
  melloa-self-change-planner.service \
  melloa-self-change-applier.service; do
  systemctl is-active --quiet "$service" || fail "service did not remain active: $service"
  systemctl is-enabled --quiet "$service" || fail "service is not enabled for reboot: $service"
done

echo "Server revision $REVISION is active with encrypted snapshot ${SNAPSHOT:0:12}."
echo "The deployed owner journey must still be exercised before README readiness can change."
