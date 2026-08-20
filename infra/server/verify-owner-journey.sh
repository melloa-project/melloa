#!/usr/bin/env bash
set -euo pipefail
set +x

umask 077

SOURCE=/srv/melloa/release-source
DESTINATION_ROOT=/
TIMEOUT_SECONDS=300
POLL_SECONDS=2
PHRASE=""

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/verify-owner-journey.sh [--source PATH] [--root PATH]
                                           [--timeout SECONDS] [--poll-seconds SECONDS]
                                           [--phrase TEXT]

Verifies the first-owner server journey after activation. It checks the supervised host services,
the active containers, the latest encrypted backup receipt, then asks the owner to send one exact
Telegram message. The script proves Melloa itself accepted that Telegram message, completed a
conversation reply, and delivered that reply back through Telegram.
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
    --root)
      [[ $# -ge 2 ]] || usage
      DESTINATION_ROOT="$2"
      shift 2
      ;;
    --timeout)
      [[ $# -ge 2 ]] || usage
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --poll-seconds)
      [[ $# -ge 2 ]] || usage
      POLL_SECONDS="$2"
      shift 2
      ;;
    --phrase)
      [[ $# -ge 2 ]] || usage
      PHRASE="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

fail() {
  echo "First owner verification failed: $1" >&2
  exit 1
}

destination() {
  local path="$1"
  if [[ "$DESTINATION_ROOT" == / ]]; then
    printf '%s' "$path"
  else
    printf '%s%s' "$DESTINATION_ROOT" "$path"
  fi
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is unavailable: $1"
}

read_environment_value() {
  local file="$1"
  local key="$2"
  local count
  local value
  count="$(awk -F= -v key="$key" '$1 == key {count += 1} END {print count + 0}' "$file")"
  [[ "$count" == 1 ]] || fail "$key must occur exactly once in $file"
  value="$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print}' "$file")"
  [[ -n "$value" && "$value" != *$'\r'* && "$value" != *$'\n'* ]] ||
    fail "$key has an invalid value"
  printf '%s' "$value"
}

read_environment_path() {
  local file="$1"
  local key="$2"
  local value
  value="$(read_environment_value "$file" "$key")"
  [[ "$value" == /* && "$value" != *$'\t'* && "$value" != *' '* && \
    "$value" != */../* && "$value" != */./* && "$value" != */.. && "$value" != */. ]] ||
    fail "$key must be a plain absolute path"
  printf '%s' "$value"
}

read_self_change_value() {
  local file="$1"
  local key="$2"
  local count
  local value
  count="$(awk -F= -v key="$key" '$1 == key {count += 1} END {print count + 0}' "$file")"
  [[ "$count" == 1 ]] || fail "$key must occur exactly once in $file"
  value="$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print}' "$file")"
  [[ "$value" != *$'\r'* && "$value" != *$'\n'* ]] ||
    fail "$key has an invalid value"
  printf '%s' "$value"
}

validate_positive_integer() {
  local value="$1"
  local label="$2"
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || fail "$label must be a positive integer"
}

compose() {
  docker compose \
    --project-directory "$SOURCE" \
    --env-file "$ENV_FILE" \
    --file "$SOURCE/compose.server.yaml" \
    "$@"
}

container_id() {
  local service="$1"
  local id
  id="$(compose ps --quiet "$service")"
  [[ -n "$id" ]] || fail "$service container is unavailable"
  printf '%s' "$id"
}

require_container_running() {
  local service="$1"
  local required_health="${2:-}"
  local id
  local state
  local health
  id="$(container_id "$service")"
  state="$(docker inspect --format '{{.State.Status}}' "$id")"
  [[ "$state" == running ]] || fail "$service container is not running"
  if [[ -n "$required_health" ]]; then
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")"
    [[ "$health" == "$required_health" ]] ||
      fail "$service container health is ${health:-unreported}, expected $required_health"
  fi
}

run_sql() {
  local sql="$1"
  shift
  compose exec --no-TTY --user postgres postgres \
    psql \
      "$@" \
      --tuples-only \
      --no-align \
      --field-separator='|' \
      --username postgres \
      --dbname melloa \
      --command "$sql"
}

conversation_status() {
  local phrase="$1"
  run_sql "
    SELECT d.state,
           COALESCE(d.last_error_code, ''),
           d.sent_part_count::text,
           COALESCE(d.notice_code, ''),
           COALESCE(d.response_message_id, ''),
           COALESCE(reply.document #>> '{parts,0,text}', '')
      FROM melloa.telegram_deliveries AS d
      JOIN melloa.conversation_messages AS inbound
        ON inbound.message_id = d.inbound_message_id
      LEFT JOIN melloa.conversation_messages AS reply
        ON reply.message_id = d.response_message_id
     WHERE d.delivery_kind = 'conversation'
       AND inbound.source_client = 'client.telegram'
       AND inbound.document #>> '{parts,0,text}' = :'verification_phrase'
     ORDER BY d.created_at DESC, d.update_id DESC
     LIMIT 1;
  " --set=verification_phrase="$phrase"
}

write_verification_receipt() {
  local response_id="$1"
  local receipt_path
  local receipt_dir
  local temporary
  receipt_path="$(destination "$RUNTIME_STATE_DIR/owner-verification-status.json")"
  receipt_dir="${receipt_path%/*}"
  [[ -d "$receipt_dir" && ! -L "$receipt_dir" ]] ||
    fail "owner verification receipt directory is unavailable"
  temporary="$(mktemp "$receipt_dir/.owner-verification-status.XXXXXX")" ||
    fail "could not create owner verification receipt"
  jq -n \
    --arg verified_at "$(date --utc '+%Y-%m-%dT%H:%M:%SZ')" \
    --arg active_revision "$ACTIVE_REVISION" \
    --arg backup_snapshot_id "$SNAPSHOT" \
    --arg response_message_id "$response_id" \
    '{
      contract_version: "1.0.0",
      verification_kind: "telegram_conversation",
      verified_at: $verified_at,
      active_revision: $active_revision,
      backup_snapshot_id: $backup_snapshot_id,
      response_message_id: $response_message_id
    }' >"$temporary" ||
    fail "could not write owner verification receipt"
  chmod 0600 "$temporary" ||
    fail "could not protect owner verification receipt"
  sync -f "$temporary" ||
    fail "could not sync owner verification receipt"
  mv -f -- "$temporary" "$receipt_path" ||
    fail "could not publish owner verification receipt"
  sync -f "$receipt_path" ||
    fail "could not sync published owner verification receipt"
  echo "Owner verification receipt updated: $receipt_path"
}

diagnose_timeout() {
  local last="$1"
  local state=""
  local error=""
  local sent_parts=""
  local notice=""
  local response_id=""
  if [[ -z "$last" ]]; then
    cat >&2 <<EOF
No matching Telegram conversation was recorded.
Recovery:
  - confirm you sent the exact setup message to the dedicated bot's private chat;
  - confirm the bot has no webhook and no other long poller;
  - run: sudo docker compose --project-directory "$SOURCE" --env-file "$ENV_FILE" --file "$SOURCE/compose.server.yaml" logs --tail=120 melloa
  - then rerun: sudo /usr/local/libexec/melloa/verify-owner-journey
EOF
    return
  fi
  IFS='|' read -r state error sent_parts notice response_id _reply_text <<<"$last"
  cat >&2 <<EOF
The setup message was recorded but did not complete before the timeout.
Current delivery state:
  state=${state:-unknown}
  sent_parts=${sent_parts:-0}
  response_id=${response_id:-none}
  notice=${notice:-none}
  last_error=${error:-none}
Recovery:
  - send /status in Telegram and check the model and backup lines;
  - if the model is unavailable, fix the model endpoint/token and rerun activation;
  - if delivery failed, inspect the melloa container logs and rerun this verifier.
EOF
}

for command in awk chmod date docker jq mktemp mv sleep sync systemctl; do
  require_command "$command"
done
validate_positive_integer "$TIMEOUT_SECONDS" "timeout"
validate_positive_integer "$POLL_SECONDS" "poll interval"
((TIMEOUT_SECONDS <= 3600)) || fail "timeout must be at most 3600 seconds"
((POLL_SECONDS <= 60)) || fail "poll interval must be at most 60 seconds"

[[ "$SOURCE" == /* && -d "$SOURCE" && ! -L "$SOURCE" ]] ||
  fail "source must be an absolute directory"
[[ -f "$SOURCE/compose.server.yaml" && ! -L "$SOURCE/compose.server.yaml" ]] ||
  fail "source checkout is missing compose.server.yaml"
[[ "$DESTINATION_ROOT" == /* ]] || fail "verification root must be absolute"
if [[ -e "$DESTINATION_ROOT" && ( ! -d "$DESTINATION_ROOT" || -L "$DESTINATION_ROOT" ) ]]; then
  fail "verification root must be a directory, not a symlink"
fi
if [[ "$DESTINATION_ROOT" == / ]]; then
  ((EUID == 0)) || fail "verification must run as root"
fi

readonly ENV_FILE="$(destination /etc/melloa/server.env)"
readonly SELF_CHANGE_ENV="$(destination /etc/melloa/self-change.env)"
readonly CONFIGURATION_RECEIPT="$(destination /etc/melloa/configuration.json)"
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "server environment file is unavailable"
[[ -f "$SELF_CHANGE_ENV" && ! -L "$SELF_CHANGE_ENV" ]] ||
  fail "self-change environment file is unavailable"
[[ -f "$CONFIGURATION_RECEIPT" && ! -L "$CONFIGURATION_RECEIPT" ]] ||
  fail "configuration receipt is unavailable"
jq -e '.contract_version == "1.0.0"' "$CONFIGURATION_RECEIPT" >/dev/null ||
  fail "configuration receipt is invalid"

readonly RELEASE_STATE_DIR="$(read_environment_path "$ENV_FILE" MELLOA_RELEASE_STATE_DIR)"
readonly ACTIVE_REVISION_FILE="$(destination "$RELEASE_STATE_DIR/active-revision")"
readonly RELEASE_STATE_FILE="$(destination "$RELEASE_STATE_DIR/release.json")"
[[ -f "$ACTIVE_REVISION_FILE" && ! -L "$ACTIVE_REVISION_FILE" ]] ||
  fail "active release marker is unavailable"
readonly ACTIVE_REVISION="$(<"$ACTIVE_REVISION_FILE")"
[[ "$ACTIVE_REVISION" =~ ^[0-9a-f]{40}$ ]] || fail "active release marker is invalid"
[[ -f "$RELEASE_STATE_FILE" && ! -L "$RELEASE_STATE_FILE" ]] ||
  fail "release state receipt is unavailable"
jq -e --arg revision "$ACTIVE_REVISION" '
  .contract_version == "1.0.0" and
  (.active | type == "object") and
  .active.revision == $revision and
  (.active.app_image | type == "string" and length > 0) and
  (.active.backup_image | type == "string" and length > 0) and
  (.active.app_image_id | type == "string" and test("^sha256:[0-9a-f]{64}$")) and
  (.active.backup_image_id | type == "string" and test("^sha256:[0-9a-f]{64}$"))
' "$RELEASE_STATE_FILE" >/dev/null ||
  fail "release state receipt does not match the active release marker"
echo "Active release marker matches release state ${ACTIVE_REVISION:0:12}."

readonly SELF_CHANGE_ENABLED="$(read_self_change_value "$SELF_CHANGE_ENV" MELLOA_SELF_CHANGE_ENABLED)"
[[ "$SELF_CHANGE_ENABLED" == true || "$SELF_CHANGE_ENABLED" == false ]] ||
  fail "MELLOA_SELF_CHANGE_ENABLED must be true or false"
for service in melloa-release-recovery.service; do
  systemctl is-enabled --quiet "$service" || fail "$service is not enabled for reboot"
  systemctl is-active --quiet "$service" || fail "$service is not active"
done
if [[ "$SELF_CHANGE_ENABLED" == true ]]; then
  for service in \
    melloa-self-change-planner.service \
    melloa-self-change-applier.service; do
    systemctl is-enabled --quiet "$service" || fail "$service is not enabled for reboot"
    systemctl is-active --quiet "$service" || fail "$service is not active"
  done
  echo "Host services are enabled and active."
else
  for service in \
    melloa-self-change-planner.service \
    melloa-self-change-applier.service; do
    if systemctl is-enabled --quiet "$service"; then
      fail "$service is enabled even though optional self-change workers are disabled"
    fi
    if systemctl is-active --quiet "$service"; then
      fail "$service is active even though optional self-change workers are disabled"
    fi
  done
  echo "Host recovery service is enabled and active; optional self-change workers are disabled."
fi

compose config --quiet
require_container_running postgres healthy
require_container_running melloa healthy
require_container_running backup
echo "Persistent containers are running and Melloa is healthy."

readonly RUNTIME_STATE_DIR="$(read_environment_path "$ENV_FILE" MELLOA_RUNTIME_STATE_DIR)"
readonly BACKUP_STATUS_FILE="$(destination "$RUNTIME_STATE_DIR/backup-status.json")"
[[ -f "$BACKUP_STATUS_FILE" && ! -L "$BACKUP_STATUS_FILE" ]] ||
  fail "backup status receipt is unavailable"
readonly SNAPSHOT="$(
  jq -er 'select(.result == "success") | .snapshot_id' "$BACKUP_STATUS_FILE"
)" || fail "latest encrypted backup did not report success"
[[ "$SNAPSHOT" =~ ^[0-9a-f]{64}$ ]] || fail "latest backup snapshot ID is invalid"
echo "Latest encrypted backup succeeded: ${SNAPSHOT:0:12}."

if [[ -z "$PHRASE" ]]; then
  require_command python3.13
  PHRASE="$(
    python3.13 -c 'import secrets; print("Hello Melli, please reply to setup verification melloa_verify_" + secrets.token_urlsafe(12))'
  )"
fi
[[ -n "$PHRASE" && ${#PHRASE} -le 160 && "$PHRASE" != *$'\n'* && \
  "$PHRASE" != *$'\r'* ]] || fail "verification phrase must be 1-160 characters without newlines"

cat >&2 <<EOF
Open the paired Telegram chat with Melli and send exactly this message:

  $PHRASE

Waiting up to $TIMEOUT_SECONDS seconds for Melloa to accept it, produce a reply, and deliver it…
EOF

deadline=$(($(date +%s) + TIMEOUT_SECONDS))
last_status=""
while (($(date +%s) <= deadline)); do
  last_status="$(conversation_status "$PHRASE" || true)"
  if [[ -n "$last_status" ]]; then
    IFS='|' read -r state error sent_parts notice response_id reply_text <<<"$last_status"
    if [[ "$state" == sent && "$sent_parts" =~ ^[1-9][0-9]*$ && \
      -n "$response_id" && -z "$notice" && -n "$reply_text" ]]; then
      echo "Telegram conversation verified: Melloa accepted the message, generated a reply, and delivered it."
      write_verification_receipt "$response_id"
      echo "First owner deployment verification passed."
      exit 0
    fi
    if [[ "$state" == dead ]]; then
      diagnose_timeout "$last_status"
      exit 1
    fi
    if [[ -n "$notice" ]]; then
      diagnose_timeout "$last_status"
      exit 1
    fi
    if [[ -n "$error" ]]; then
      echo "Telegram delivery is retrying after: $error" >&2
    fi
  fi
  sleep "$POLL_SECONDS"
done

diagnose_timeout "$last_status"
exit 1
