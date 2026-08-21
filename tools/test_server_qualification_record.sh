#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-qualification-record-test.XXXXXX)"
readonly TARGET="$WORKDIR/target"
readonly OUTPUT="$WORKDIR/output.log"
readonly SOURCE_REVISION=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
readonly PREVIOUS_REVISION=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
readonly UPDATE_FROM_REVISION=cccccccccccccccccccccccccccccccccccccccc
readonly SNAPSHOT=1111111111111111111111111111111111111111111111111111111111111111

cleanup() {
  local status=$?
  if ((status != 0)); then
    if [[ -f "$OUTPUT" ]]; then
      echo "--- qualification-record output ---" >&2
      sed -n '1,240p' "$OUTPUT" >&2
    fi
  fi
  if [[ "$WORKDIR" == /tmp/melloa-qualification-record-test.* && -d "$WORKDIR" ]]; then
    rm -rf -- "$WORKDIR"
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

install -d -m 0700 \
  "$TARGET/etc/melloa" \
  "$TARGET/var/lib/melloa/runtime-state" \
  "$TARGET/var/lib/melloa/release-state"
{
  printf 'MELLOA_SOURCE_REVISION=%s\n' "$SOURCE_REVISION"
  printf 'MELLOA_RUNTIME_STATE_DIR=/var/lib/melloa/runtime-state\n'
  printf 'MELLOA_RELEASE_STATE_DIR=/var/lib/melloa/release-state\n'
  printf 'MELLOA_BACKUP_REPOSITORY_DIR=/mnt/melloa-off-device-backup\n'
} >"$TARGET/etc/melloa/server.env"
{
  printf 'MELLOA_SELF_CHANGE_ENABLED=false\n'
  printf 'MELLOA_CODEX_USE_API_KEY=false\n'
  printf 'MELLOA_CODEX_MODEL=\n'
  printf 'MELLOA_CODEX_LOCAL_PROVIDER=\n'
} >"$TARGET/etc/melloa/self-change.env"
jq -n \
  --arg revision "$SOURCE_REVISION" \
  '{
    contract_version: "1.0.0",
    source_revision: $revision,
    backup_repository: "/mnt/melloa-off-device-backup",
    codex_mode: "disabled",
    configured_at: "2026-08-20T00:00:00Z"
  }' >"$TARGET/etc/melloa/configuration.json"
printf '%s\n' "$SOURCE_REVISION" \
  >"$TARGET/var/lib/melloa/release-state/active-revision"
jq -n \
  --arg revision "$SOURCE_REVISION" \
  --arg previous "$PREVIOUS_REVISION" \
  --arg app_id "sha256:$(printf '%064d' 2)" \
  --arg backup_id "sha256:$(printf '%064d' 3)" \
  --arg previous_app_id "sha256:$(printf '%064d' 4)" \
  --arg previous_backup_id "sha256:$(printf '%064d' 5)" \
  --arg snapshot "$SNAPSHOT" \
  '{
    contract_version: "1.0.0",
    active: {
      revision: $revision,
      app_image: ("melloa-local/server:" + $revision),
      backup_image: ("melloa-local/backup:" + $revision),
      app_image_id: $app_id,
      backup_image_id: $backup_id,
      activated_at: "2026-08-20T01:00:00Z"
    },
    previous: {
      revision: $previous,
      app_image: ("melloa-local/server:" + $previous),
      backup_image: ("melloa-local/backup:" + $previous),
      app_image_id: $previous_app_id,
      backup_image_id: $previous_backup_id,
      activated_at: "2026-08-19T01:00:00Z"
    },
    predeploy_snapshot: $snapshot
  }' >"$TARGET/var/lib/melloa/release-state/release.json"
jq -n \
  --arg snapshot "$SNAPSHOT" \
  '{
    contract_version: "1.0.0",
    result: "success",
    checked_at: "2026-08-20T02:00:00Z",
    completed_at: "2026-08-20T02:00:01Z",
    snapshot_id: $snapshot
  }' >"$TARGET/var/lib/melloa/runtime-state/backup-status.json"
jq -n \
  --arg revision "$SOURCE_REVISION" \
  --arg snapshot "$SNAPSHOT" \
  '{
    contract_version: "1.0.0",
    verification_kind: "telegram_conversation",
    verified_at: "2026-08-20T03:00:00Z",
    active_revision: $revision,
    backup_snapshot_id: $snapshot,
    response_message_id: "message_reply_00000000000000000000000000000001"
  }' >"$TARGET/var/lib/melloa/runtime-state/owner-verification-status.json"
jq -n \
  --arg revision "$SOURCE_REVISION" \
  --arg snapshot "$SNAPSHOT" \
  '{
    contract_version: "1.0.0",
    result: "success",
    drilled_at: "2026-08-20T02:30:00Z",
    requested_snapshot: "latest",
    backup_status_snapshot_id: $snapshot,
    source_revision: $revision,
    proofs: {
      migration_check: true,
      owner_identity: true,
      telegram_owner_binding: true,
      telegram_conversation: true,
      readonly_role_cannot_mutate: true
    }
  }' >"$TARGET/var/lib/melloa/runtime-state/restore-drill-status.json"
jq -cn \
  --arg revision "$SOURCE_REVISION" \
  --arg snapshot "$SNAPSHOT" \
  '{
    contract_version: "1.0.0",
    event: "deploy",
    outcome: "succeeded",
    revision: $revision,
    reason_code: "release.activated",
    snapshot_id: $snapshot,
    occurred_at: "2026-08-20T01:00:02Z"
  }' >"$TARGET/var/lib/melloa/release-state/history.jsonl"
jq -cn \
  --arg from "$PREVIOUS_REVISION" \
  --arg active "$UPDATE_FROM_REVISION" \
  '{
    contract_version: "1.0.0",
    operation: "update",
    result: "verified",
    completed_at: "2026-08-20T04:00:00Z",
    from_revision: $from,
    active_revision: $active,
    verification_kind: "telegram_conversation"
  }' >"$TARGET/var/lib/melloa/runtime-state/maintenance-history.jsonl"
jq -cn \
  --arg from "$UPDATE_FROM_REVISION" \
  --arg active "$SOURCE_REVISION" \
  '{
    contract_version: "1.0.0",
    operation: "rollback",
    result: "verified",
    completed_at: "2026-08-20T04:30:00Z",
    from_revision: $from,
    active_revision: $active,
    verification_kind: "telegram_conversation"
  }' >>"$TARGET/var/lib/melloa/runtime-state/maintenance-history.jsonl"

"$ROOT/infra/server/qualification-record.sh" \
  --source "$ROOT" \
  --root "$TARGET" \
  >"$OUTPUT"

grep --fixed-strings --quiet "Melloa private first-server qualification snapshot" "$OUTPUT"
grep --fixed-strings --quiet "configured_revision: $SOURCE_REVISION" "$OUTPUT"
grep --fixed-strings --quiet "backup_mount_check: not_checked_under_staging_root" "$OUTPUT"
grep --fixed-strings --quiet "active_revision: $SOURCE_REVISION" "$OUTPUT"
grep --fixed-strings --quiet "previous_revision: $PREVIOUS_REVISION" "$OUTPUT"
grep --fixed-strings --quiet "snapshot_prefix: ${SNAPSHOT:0:12}" "$OUTPUT"
grep --fixed-strings --quiet "restore_drill:" "$OUTPUT"
grep --fixed-strings --quiet "drilled_at: 2026-08-20T02:30:00Z" "$OUTPUT"
grep --fixed-strings --quiet "requested_snapshot: latest" "$OUTPUT"
grep --fixed-strings --quiet "telegram_conversation: true" "$OUTPUT"
grep --fixed-strings --quiet "readonly_role_cannot_mutate: true" "$OUTPUT"
grep --fixed-strings --quiet "verified_at: 2026-08-20T03:00:00Z" "$OUTPUT"
grep --fixed-strings --quiet "maintenance_history:" "$OUTPUT"
grep --fixed-strings --quiet \
  "update verified from=${PREVIOUS_REVISION:0:12} active=${UPDATE_FROM_REVISION:0:12} verification=telegram_conversation" \
  "$OUTPUT"
grep --fixed-strings --quiet \
  "rollback verified from=${UPDATE_FROM_REVISION:0:12} active=${SOURCE_REVISION:0:12} verification=telegram_conversation" \
  "$OUTPUT"
grep --fixed-strings --quiet "deploy succeeded revision=${SOURCE_REVISION:0:12}" "$OUTPUT"
grep --fixed-strings --quiet "Keep this output private" "$OUTPUT"
grep --fixed-strings --quiet "next_steps:" "$OUTPUT"
grep --fixed-strings --quiet "backup receipt: present" "$OUTPUT"
grep --fixed-strings --quiet "owner verification: present" "$OUTPUT"
grep --fixed-strings --quiet "restore drill: present" "$OUTPUT"
grep --fixed-strings --quiet \
  "self-change workers disabled: this is conversation-only and cannot qualify the first self-change server proof" \
  "$OUTPUT"
grep --fixed-strings --quiet "update evidence: present" "$OUTPUT"
grep --fixed-strings --quiet "rollback evidence: present" "$OUTPUT"
if grep --fixed-strings --quiet "/etc/melloa/private" "$OUTPUT"; then
  echo "Qualification record exposed private credential file paths" >&2
  exit 1
fi

rm -f "$TARGET/var/lib/melloa/runtime-state/owner-verification-status.json"
"$ROOT/infra/server/qualification-record.sh" \
  --source "$ROOT" \
  --root "$TARGET" \
  >"$OUTPUT"
grep --fixed-strings --quiet "status: missing" "$OUTPUT"
grep --fixed-strings --quiet "run: sudo /usr/local/libexec/melloa/verify-owner-journey" "$OUTPUT"
grep --fixed-strings --quiet \
  "owner verification missing: run sudo /usr/local/libexec/melloa/verify-owner-journey" \
  "$OUTPUT"

rm -f "$TARGET/var/lib/melloa/runtime-state/restore-drill-status.json"
"$ROOT/infra/server/qualification-record.sh" \
  --source "$ROOT" \
  --root "$TARGET" \
  >"$OUTPUT"
grep --fixed-strings --quiet "restore_drill:" "$OUTPUT"
grep --fixed-strings --quiet "run: sudo /usr/local/libexec/melloa/restore-drill" "$OUTPUT"
grep --fixed-strings --quiet \
  "restore drill missing: run sudo /usr/local/libexec/melloa/restore-drill" \
  "$OUTPUT"

echo "Server qualification record checks passed."
