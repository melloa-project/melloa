#!/usr/bin/env bash
set -euo pipefail
set +x

umask 077

export PATH=/opt/melloa/toolchain/bin:"${PATH:-/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin}"

SOURCE=/srv/melloa/release-source
DESTINATION_ROOT=/

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/qualification-record.sh [--source PATH] [--root PATH]

Prints a redacted first-server qualification snapshot from installed Melloa receipts. It does not
perform verification and does not read private credential files. Run the verifier, restore drill,
update, and rollback wrappers first; then keep this output in the owner's private deployment notes.
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
    *)
      usage
      ;;
  esac
done

fail() {
  echo "Qualification record failed: $1" >&2
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

snapshot_prefix() {
  local value="$1"
  if [[ "$value" =~ ^[0-9a-f]{64}$ ]]; then
    printf '%s' "${value:0:12}"
  else
    printf 'missing'
  fi
}

release_prefix() {
  local value="$1"
  if [[ "$value" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s' "${value:0:12}"
  else
    printf 'missing'
  fi
}

for command in awk date findmnt git jq stat; do
  require_command "$command"
done

[[ "$SOURCE" == /* && -d "$SOURCE" && ! -L "$SOURCE" ]] ||
  fail "source must be an absolute directory"
[[ "$DESTINATION_ROOT" == /* ]] || fail "qualification root must be absolute"
if [[ -e "$DESTINATION_ROOT" && ( ! -d "$DESTINATION_ROOT" || -L "$DESTINATION_ROOT" ) ]]; then
  fail "qualification root must be a directory, not a symlink"
fi
if [[ "$DESTINATION_ROOT" == / ]]; then
  ((EUID == 0)) || fail "qualification record must run as root"
fi

readonly ENV_FILE="$(destination /etc/melloa/server.env)"
readonly SELF_CHANGE_ENV="$(destination /etc/melloa/self-change.env)"
readonly CONFIGURATION_RECEIPT="$(destination /etc/melloa/configuration.json)"
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "server environment file is unavailable"
[[ -f "$SELF_CHANGE_ENV" && ! -L "$SELF_CHANGE_ENV" ]] ||
  fail "self-change environment file is unavailable"
[[ -f "$CONFIGURATION_RECEIPT" && ! -L "$CONFIGURATION_RECEIPT" ]] ||
  fail "configuration receipt is unavailable"
jq -e '
  .contract_version == "1.0.0" and
  (.source_revision | type == "string" and test("^[0-9a-f]{40}$")) and
  (.backup_repository | type == "string" and startswith("/")) and
  (.codex_mode | type == "string") and
  (.configured_at | type == "string" and length > 0)
' "$CONFIGURATION_RECEIPT" >/dev/null ||
  fail "configuration receipt is invalid"

readonly CONFIGURED_REVISION="$(jq -er .source_revision "$CONFIGURATION_RECEIPT")"
readonly CONFIGURED_AT="$(jq -er .configured_at "$CONFIGURATION_RECEIPT")"
readonly CONFIGURED_BACKUP_REPOSITORY="$(jq -er .backup_repository "$CONFIGURATION_RECEIPT")"
readonly CODEX_MODE="$(jq -er .codex_mode "$CONFIGURATION_RECEIPT")"
readonly ENV_SOURCE_REVISION="$(read_environment_value "$ENV_FILE" MELLOA_SOURCE_REVISION)"
readonly BACKUP_REPOSITORY_DIR="$(read_environment_path "$ENV_FILE" MELLOA_BACKUP_REPOSITORY_DIR)"
readonly RUNTIME_STATE_DIR="$(read_environment_path "$ENV_FILE" MELLOA_RUNTIME_STATE_DIR)"
readonly RELEASE_STATE_DIR="$(read_environment_path "$ENV_FILE" MELLOA_RELEASE_STATE_DIR)"
readonly SELF_CHANGE_ENABLED="$(read_self_change_value "$SELF_CHANGE_ENV" MELLOA_SELF_CHANGE_ENABLED)"
[[ "$SELF_CHANGE_ENABLED" == true || "$SELF_CHANGE_ENABLED" == false ]] ||
  fail "MELLOA_SELF_CHANGE_ENABLED must be true or false"

source_checkout_revision="$(git -C "$SOURCE" rev-parse HEAD 2>/dev/null || true)"
[[ "$source_checkout_revision" =~ ^[0-9a-f]{40}$ ]] || source_checkout_revision=unavailable

if [[ "$DESTINATION_ROOT" == / ]]; then
  if [[ -d "$BACKUP_REPOSITORY_DIR" && ! -L "$BACKUP_REPOSITORY_DIR" ]] &&
    findmnt --mountpoint "$BACKUP_REPOSITORY_DIR" >/dev/null; then
    if [[ "$(stat --format='%d' "$BACKUP_REPOSITORY_DIR")" != "$(stat --format='%d' /)" ]]; then
      backup_mount_check=explicit_mount_independent_from_root
    else
      backup_mount_check=explicit_mount_on_root_filesystem
    fi
  else
    backup_mount_check=missing_or_not_an_explicit_mount
  fi
else
  backup_mount_check=not_checked_under_staging_root
fi

release_active_revision=missing
release_activated_at=missing
release_previous_revision=none
release_predeploy_snapshot_prefix=none
readonly ACTIVE_REVISION_FILE="$(destination "$RELEASE_STATE_DIR/active-revision")"
readonly RELEASE_STATE_FILE="$(destination "$RELEASE_STATE_DIR/release.json")"
if [[ -L "$RELEASE_STATE_FILE" ]]; then
  fail "release state receipt must not be a symlink"
elif [[ -f "$RELEASE_STATE_FILE" ]]; then
  jq -e '
    def release:
      type == "object" and
      (.revision | type == "string" and test("^[0-9a-f]{40}$")) and
      (.app_image | type == "string" and length > 0) and
      (.backup_image | type == "string" and length > 0) and
      (.app_image_id | type == "string" and test("^sha256:[0-9a-f]{64}$")) and
      (.backup_image_id | type == "string" and test("^sha256:[0-9a-f]{64}$")) and
      (.activated_at | type == "string" and length > 0);
    .contract_version == "1.0.0" and
    (.active | release) and
    (.previous == null or (.previous | release)) and
    (.predeploy_snapshot == null or
      (.predeploy_snapshot | type == "string" and test("^[0-9a-f]{64}$")))
  ' "$RELEASE_STATE_FILE" >/dev/null ||
    fail "release state receipt is invalid"
  release_active_revision="$(jq -er .active.revision "$RELEASE_STATE_FILE")"
  release_activated_at="$(jq -er .active.activated_at "$RELEASE_STATE_FILE")"
  release_previous_revision="$(jq -r '.previous.revision // "none"' "$RELEASE_STATE_FILE")"
  release_predeploy_snapshot_prefix="$(
    snapshot_prefix "$(jq -r '.predeploy_snapshot // ""' "$RELEASE_STATE_FILE")"
  )"
  [[ "$release_predeploy_snapshot_prefix" != missing ]] || release_predeploy_snapshot_prefix=none
fi
if [[ -L "$ACTIVE_REVISION_FILE" ]]; then
  fail "active release marker must not be a symlink"
elif [[ -f "$ACTIVE_REVISION_FILE" ]]; then
  active_marker="$(<"$ACTIVE_REVISION_FILE")"
  [[ "$active_marker" =~ ^[0-9a-f]{40}$ ]] || fail "active release marker is invalid"
else
  active_marker=missing
fi

backup_result=missing
backup_checked_at=missing
backup_completed_at=missing
backup_snapshot_prefix=missing
backup_reason=none
readonly BACKUP_STATUS_FILE="$(destination "$RUNTIME_STATE_DIR/backup-status.json")"
if [[ -L "$BACKUP_STATUS_FILE" ]]; then
  fail "backup status receipt must not be a symlink"
elif [[ -f "$BACKUP_STATUS_FILE" ]]; then
  jq -e '
    .contract_version == "1.0.0" and
    (.result == "success" or .result == "failed") and
    (.checked_at | type == "string" and length > 0) and
    (if .result == "success" then
      (.completed_at | type == "string" and length > 0) and
      (.snapshot_id | type == "string" and test("^[0-9a-f]{64}$"))
    else
      .completed_at == null and .snapshot_id == null and
      (.reason_code | type == "string" and length > 0)
    end)
  ' "$BACKUP_STATUS_FILE" >/dev/null ||
    fail "backup status receipt is invalid"
  backup_result="$(jq -er .result "$BACKUP_STATUS_FILE")"
  backup_checked_at="$(jq -er .checked_at "$BACKUP_STATUS_FILE")"
  backup_completed_at="$(jq -r '.completed_at // "missing"' "$BACKUP_STATUS_FILE")"
  backup_snapshot_prefix="$(snapshot_prefix "$(jq -r '.snapshot_id // ""' "$BACKUP_STATUS_FILE")")"
  backup_reason="$(jq -r '.reason_code // "none"' "$BACKUP_STATUS_FILE")"
fi

restore_drill_status=missing
restore_drill_at=missing
restore_drill_requested_snapshot=missing
restore_drill_backup_snapshot_prefix=missing
restore_drill_source_revision=missing
restore_drill_migration_check=missing
restore_drill_owner_identity=missing
restore_drill_telegram_owner_binding=missing
restore_drill_telegram_conversation=missing
restore_drill_readonly_role=missing
readonly RESTORE_DRILL_STATUS_FILE="$(destination "$RUNTIME_STATE_DIR/restore-drill-status.json")"
if [[ -L "$RESTORE_DRILL_STATUS_FILE" ]]; then
  fail "restore-drill receipt must not be a symlink"
elif [[ -f "$RESTORE_DRILL_STATUS_FILE" ]]; then
  jq -e '
    .contract_version == "1.0.0" and
    .result == "success" and
    (.drilled_at | type == "string" and length > 0) and
    (.requested_snapshot | type == "string" and test("^(latest|[0-9a-f]{8,64})$")) and
    (.backup_status_snapshot_id == null or
      (.backup_status_snapshot_id | type == "string" and test("^[0-9a-f]{64}$"))) and
    (.source_revision | type == "string" and test("^[0-9a-f]{40}$")) and
    .proofs.migration_check == true and
    .proofs.owner_identity == true and
    .proofs.telegram_owner_binding == true and
    .proofs.telegram_conversation == true and
    .proofs.readonly_role_cannot_mutate == true
  ' "$RESTORE_DRILL_STATUS_FILE" >/dev/null ||
    fail "restore-drill receipt is invalid"
  restore_drill_status=present
  restore_drill_at="$(jq -er .drilled_at "$RESTORE_DRILL_STATUS_FILE")"
  restore_drill_requested_snapshot="$(jq -er .requested_snapshot "$RESTORE_DRILL_STATUS_FILE")"
  restore_drill_backup_snapshot_prefix="$(
    snapshot_prefix "$(jq -r '.backup_status_snapshot_id // ""' "$RESTORE_DRILL_STATUS_FILE")"
  )"
  restore_drill_source_revision="$(jq -er .source_revision "$RESTORE_DRILL_STATUS_FILE")"
  restore_drill_migration_check="$(jq -er .proofs.migration_check "$RESTORE_DRILL_STATUS_FILE")"
  restore_drill_owner_identity="$(jq -er .proofs.owner_identity "$RESTORE_DRILL_STATUS_FILE")"
  restore_drill_telegram_owner_binding="$(
    jq -er .proofs.telegram_owner_binding "$RESTORE_DRILL_STATUS_FILE"
  )"
  restore_drill_telegram_conversation="$(
    jq -er .proofs.telegram_conversation "$RESTORE_DRILL_STATUS_FILE"
  )"
  restore_drill_readonly_role="$(
    jq -er .proofs.readonly_role_cannot_mutate "$RESTORE_DRILL_STATUS_FILE"
  )"
fi

verification_status=missing
verification_at=missing
verification_revision=missing
verification_snapshot_prefix=missing
verification_response_id=missing
readonly VERIFICATION_RECEIPT_FILE="$(
  destination "$RUNTIME_STATE_DIR/owner-verification-status.json"
)"
if [[ -L "$VERIFICATION_RECEIPT_FILE" ]]; then
  fail "owner verification receipt must not be a symlink"
elif [[ -f "$VERIFICATION_RECEIPT_FILE" ]]; then
  jq -e '
    .contract_version == "1.0.0" and
    .verification_kind == "telegram_conversation" and
    (.verified_at | type == "string" and length > 0) and
    (.active_revision | type == "string" and test("^[0-9a-f]{40}$")) and
    (.backup_snapshot_id | type == "string" and test("^[0-9a-f]{64}$")) and
    (.response_message_id | type == "string" and length > 0)
  ' "$VERIFICATION_RECEIPT_FILE" >/dev/null ||
    fail "owner verification receipt is invalid"
  verification_status=present
  verification_at="$(jq -er .verified_at "$VERIFICATION_RECEIPT_FILE")"
  verification_revision="$(jq -er .active_revision "$VERIFICATION_RECEIPT_FILE")"
  verification_snapshot_prefix="$(
    snapshot_prefix "$(jq -er .backup_snapshot_id "$VERIFICATION_RECEIPT_FILE")"
  )"
  verification_response_id="$(jq -er .response_message_id "$VERIFICATION_RECEIPT_FILE")"
fi

readonly MAINTENANCE_HISTORY_FILE="$(destination "$RUNTIME_STATE_DIR/maintenance-history.jsonl")"
maintenance_update_verified=false
maintenance_rollback_verified=false
if [[ -L "$MAINTENANCE_HISTORY_FILE" ]]; then
  fail "maintenance history receipt must not be a symlink"
elif [[ -s "$MAINTENANCE_HISTORY_FILE" ]]; then
  jq -sr '
    def valid_event:
      .contract_version == "1.0.0" and
      (.operation == "update" or .operation == "rollback") and
      (.result == "verified" or .result == "verification_skipped") and
      (.completed_at | type == "string" and length > 0) and
      (.from_revision | type == "string" and test("^[0-9a-f]{40}$")) and
      (.active_revision | type == "string" and test("^[0-9a-f]{40}$")) and
      (.verification_kind == null or .verification_kind == "telegram_conversation");
    all(.[]; valid_event)
  ' "$MAINTENANCE_HISTORY_FILE" >/dev/null ||
    fail "maintenance history receipt is invalid"
  if jq -sr -e 'any(.[]; .operation == "update" and .result == "verified")' \
    "$MAINTENANCE_HISTORY_FILE" >/dev/null; then
    maintenance_update_verified=true
  fi
  if jq -sr -e 'any(.[]; .operation == "rollback" and .result == "verified")' \
    "$MAINTENANCE_HISTORY_FILE" >/dev/null; then
    maintenance_rollback_verified=true
  fi
fi

cat <<EOF
Melloa private first-server qualification snapshot
generated_at: $(date --utc '+%Y-%m-%dT%H:%M:%SZ')

configuration:
  source_checkout_revision: $source_checkout_revision
  configured_revision: $CONFIGURED_REVISION
  server_env_revision: $ENV_SOURCE_REVISION
  configured_at: $CONFIGURED_AT
  backup_repository: $CONFIGURED_BACKUP_REPOSITORY
  backup_repository_env: $BACKUP_REPOSITORY_DIR
  backup_mount_check: $backup_mount_check
  self_change_enabled: $SELF_CHANGE_ENABLED
  codex_mode: $CODEX_MODE

release:
  active_marker: $active_marker
  active_revision: $release_active_revision
  active_revision_prefix: $(release_prefix "$release_active_revision")
  activated_at: $release_activated_at
  previous_revision: $release_previous_revision
  predeploy_snapshot_prefix: $release_predeploy_snapshot_prefix

backup:
  result: $backup_result
  checked_at: $backup_checked_at
  completed_at: $backup_completed_at
  snapshot_prefix: $backup_snapshot_prefix
  reason: $backup_reason

restore_drill:
  status: $restore_drill_status
  drilled_at: $restore_drill_at
  source_revision: $restore_drill_source_revision
  requested_snapshot: $restore_drill_requested_snapshot
  backup_status_snapshot_prefix: $restore_drill_backup_snapshot_prefix
  migration_check: $restore_drill_migration_check
  owner_identity: $restore_drill_owner_identity
  telegram_owner_binding: $restore_drill_telegram_owner_binding
  telegram_conversation: $restore_drill_telegram_conversation
  readonly_role_cannot_mutate: $restore_drill_readonly_role

owner_verification:
  status: $verification_status
  verified_at: $verification_at
  active_revision: $verification_revision
  backup_snapshot_prefix: $verification_snapshot_prefix
  response_message_id: $verification_response_id

maintenance_history:
EOF

if [[ -s "$MAINTENANCE_HISTORY_FILE" ]]; then
  jq -sr '
    .[-10:][] |
    "  - \(.completed_at) \(.operation) \(.result) from=\(.from_revision[0:12]) active=\(.active_revision[0:12]) verification=" +
    (if .verification_kind == null then "skipped" else .verification_kind end)
  ' "$MAINTENANCE_HISTORY_FILE"
else
  echo "  - none"
fi

cat <<'EOF'

recent_release_history:
EOF

readonly RELEASE_HISTORY_FILE="$(destination "$RELEASE_STATE_DIR/history.jsonl")"
if [[ -L "$RELEASE_HISTORY_FILE" ]]; then
  fail "release history receipt must not be a symlink"
elif [[ -s "$RELEASE_HISTORY_FILE" ]]; then
  jq -sr '
    def valid_event:
      .contract_version == "1.0.0" and
      (.event == "deploy" or .event == "rollback") and
      (.outcome | type == "string" and length > 0) and
      (.revision | type == "string" and test("^[0-9a-f]{40}$")) and
      (.reason_code | type == "string" and length > 0) and
      (.snapshot_id == null or
        (.snapshot_id | type == "string" and test("^[0-9a-f]{64}$"))) and
      (.occurred_at | type == "string" and length > 0);
    if all(.[]; valid_event) then
      .[-10:][] |
      "  - \(.occurred_at) \(.event) \(.outcome) revision=\(.revision[0:12]) reason=\(.reason_code)" +
      (if .snapshot_id == null then "" else " snapshot=\(.snapshot_id[0:12])" end)
    else
      error("invalid release history receipt")
    end
  ' "$RELEASE_HISTORY_FILE" ||
    fail "release history receipt is invalid"
else
  echo "  - none"
fi

cat <<'EOF'

notes:
  - Keep this output private with the deployment notes; it intentionally omits secrets.
  - If owner_verification.status is missing, run: sudo /usr/local/libexec/melloa/verify-owner-journey
  - If restore_drill.status is missing, run: sudo /usr/local/libexec/melloa/restore-drill
  - If backup.result is not success, inspect /status and rerun the backup or restore-drill path.
EOF

cat <<'EOF'

next_steps:
EOF
if [[ "$backup_result" == success ]]; then
  echo "  - backup receipt: present"
else
  echo "  - backup receipt missing or failed: send /status in Telegram, fix the backup line, then run sudo /usr/local/libexec/melloa/verify-owner-journey"
fi
if [[ "$verification_status" == present ]]; then
  echo "  - owner verification: present"
else
  echo "  - owner verification missing: run sudo /usr/local/libexec/melloa/verify-owner-journey"
fi
if [[ "$restore_drill_status" == present ]]; then
  echo "  - restore drill: present"
else
  echo "  - restore drill missing: run sudo /usr/local/libexec/melloa/restore-drill"
fi
if [[ "$SELF_CHANGE_ENABLED" == true ]]; then
  echo "  - self-change workers: enabled; retain Telegram /change show <change_id> after State: deployed as the self-change proof"
else
  echo "  - self-change workers disabled: this is conversation-only and cannot qualify the first self-change server proof"
fi
if [[ "$maintenance_update_verified" == true ]]; then
  echo "  - update evidence: present"
else
  echo "  - update evidence missing: after a later reviewed main commit exists, run sudo /usr/local/libexec/melloa/update"
fi
if [[ "$maintenance_rollback_verified" == true ]]; then
  echo "  - rollback evidence: present"
else
  echo "  - rollback evidence missing: after update evidence exists, run sudo /usr/local/libexec/melloa/rollback"
fi
