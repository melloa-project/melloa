#!/usr/bin/env bash
set -uo pipefail

umask 077

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RELEASE_TIMEOUT="${MELLOA_RELEASE_HEALTH_TIMEOUT_SECONDS:-120}"
readonly RELEASE_POLL_SECONDS="${MELLOA_RELEASE_POLL_SECONDS:-1}"

COMMAND="${1:-}"
[[ $# -gt 0 ]] && shift
ENV_FILE=""
STATE_DIR=""
REVISION=""
APP_IMAGE=""
BACKUP_IMAGE=""
NO_BUILD=false

RECOVERY_MODE=""
RECOVERY_ACTIVE_JSON="null"
RECOVERY_STATE_JSON="null"
RECOVERY_REVISION=""
RECOVERY_APP_IMAGE=""
RECOVERY_BACKUP_IMAGE=""
RECOVERY_SNAPSHOT=""
RECOVERY_EVENT=""

usage() {
  cat >&2 <<'EOF'
Usage:
  tools/server_release.sh deploy --env-file PATH --state-dir PATH [--revision SHA --app-image IMAGE --backup-image IMAGE --no-build]
  tools/server_release.sh rollback --env-file PATH --state-dir PATH
  tools/server_release.sh status --state-dir PATH
EOF
  exit 2
}

while (($#)); do
  case "$1" in
    --env-file)
      [[ $# -ge 2 ]] || usage
      ENV_FILE="$2"
      shift 2
      ;;
    --state-dir)
      [[ $# -ge 2 ]] || usage
      STATE_DIR="$2"
      shift 2
      ;;
    --revision)
      [[ $# -ge 2 ]] || usage
      REVISION="$2"
      shift 2
      ;;
    --app-image)
      [[ $# -ge 2 ]] || usage
      APP_IMAGE="$2"
      shift 2
      ;;
    --backup-image)
      [[ $# -ge 2 ]] || usage
      BACKUP_IMAGE="$2"
      shift 2
      ;;
    --no-build)
      NO_BUILD=true
      shift
      ;;
    *)
      usage
      ;;
  esac
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required release command is unavailable: $1" >&2
    return 1
  fi
}

require_protected_file() {
  local path="$1"
  local label="$2"
  local mode
  local permissions
  if [[ ! -f "$path" || -L "$path" || ! -r "$path" ]]; then
    echo "$label must be a readable regular file, not a symlink" >&2
    return 1
  fi
  mode="$(stat --format='%a' "$path")"
  if [[ ! "$mode" =~ ^[0-7]{3,4}$ ]]; then
    echo "$label has an invalid permission mode" >&2
    return 1
  fi
  permissions=$((8#$mode))
  if ((permissions & 0022)); then
    echo "$label must not be writable by its group or other users" >&2
    return 1
  fi
}

validate_revision() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || {
    echo "Release revision must be a full lowercase Git commit SHA" >&2
    return 1
  }
}

validate_image_reference() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}$ ]] || {
    echo "Release image reference has an invalid format" >&2
    return 1
  }
}

validate_positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

prepare_state_dir() {
  if [[ ! "$STATE_DIR" == /* ]]; then
    echo "Release state directory must be an absolute path" >&2
    return 1
  fi
  if [[ -e "$STATE_DIR" && ( ! -d "$STATE_DIR" || -L "$STATE_DIR" ) ]]; then
    echo "Release state path must be a directory, not a symlink" >&2
    return 1
  fi
  install -d -m 0711 "$STATE_DIR"
  chmod 0711 "$STATE_DIR"
}

read_env_path() {
  local key="$1"
  local line
  local count
  count="$(awk -F= -v key="$key" '$1 == key {count += 1} END {print count + 0}' "$ENV_FILE")"
  if [[ "$count" != 1 ]]; then
    echo "$key must occur exactly once in the server environment file" >&2
    return 1
  fi
  line="$(awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print}' "$ENV_FILE")"
  if [[ ! "$line" == /* || "$line" == *$'\n'* ]]; then
    echo "$key must be a plain absolute path" >&2
    return 1
  fi
  printf '%s' "$line"
}

compose_release() {
  local revision="$1"
  local app_image="$2"
  local backup_image="$3"
  shift 3
  MELLOA_SOURCE_REVISION="$revision" \
  MELLOA_IMAGE="$app_image" \
  MELLOA_BACKUP_IMAGE="$backup_image" \
  MELLOA_RELEASE_STATE_DIR="$STATE_DIR" \
    docker compose \
      --project-directory "$ROOT" \
      --env-file "$ENV_FILE" \
      --file "$ROOT/compose.server.yaml" \
      "$@"
}

image_id() {
  docker image inspect --format '{{.Id}}' "$1"
}

verify_image() {
  local image="$1"
  local revision="$2"
  local label
  validate_image_reference "$image" || return 1
  if ! label="$(
    docker image inspect \
      --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
      "$image"
  )"; then
    echo "Release image is unavailable: $image" >&2
    return 1
  fi
  if [[ "$label" != "$revision" ]]; then
    echo "Release image revision label does not match the reviewed commit" >&2
    return 1
  fi
}

state_file() {
  printf '%s/release.json' "$STATE_DIR"
}

history_file() {
  printf '%s/history.jsonl' "$STATE_DIR"
}

load_state() {
  local path
  path="$(state_file)"
  if [[ ! -e "$path" ]]; then
    printf 'null'
    return 0
  fi
  require_protected_file "$path" "Release state" || return 1
  if [[ "$(stat --format='%s' "$path")" -gt 16384 ]]; then
    echo "Release state is unexpectedly large" >&2
    return 1
  fi
  if ! jq -e '
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
  ' "$path" >/dev/null; then
    echo "Release state contract is invalid" >&2
    return 1
  fi
  jq -c . "$path"
}

release_object() {
  local revision="$1"
  local app_image="$2"
  local backup_image="$3"
  local activated_at="$4"
  jq -cn \
    --arg revision "$revision" \
    --arg app_image "$app_image" \
    --arg backup_image "$backup_image" \
    --arg app_image_id "$(image_id "$app_image")" \
    --arg backup_image_id "$(image_id "$backup_image")" \
    --arg activated_at "$activated_at" \
    '{revision: $revision, app_image: $app_image, backup_image: $backup_image,
      app_image_id: $app_image_id, backup_image_id: $backup_image_id,
      activated_at: $activated_at}'
}

write_state() {
  local active_json="$1"
  local previous_json="$2"
  local predeploy_snapshot="${3:-}"
  local path
  local temporary
  path="$(state_file)"
  temporary="$(mktemp "$STATE_DIR/.release-state.XXXXXX")" || return 1
  jq -n \
    --argjson active "$active_json" \
    --argjson previous "$previous_json" \
    --arg snapshot "$predeploy_snapshot" \
    '{contract_version: "1.0.0", active: $active, previous: $previous,
      predeploy_snapshot: (if $snapshot == "" then null else $snapshot end)}' \
    >"$temporary" || return 1
  chmod 0600 "$temporary"
  mv -- "$temporary" "$path"
}

write_activation() {
  local revision="$1"
  local temporary
  temporary="$(mktemp "$STATE_DIR/.active-revision.XXXXXX")" || return 1
  printf '%s\n' "$revision" >"$temporary"
  chmod 0644 "$temporary"
  mv -- "$temporary" "$STATE_DIR/active-revision"
}

record_history() {
  local event="$1"
  local outcome="$2"
  local revision="$3"
  local reason_code="$4"
  local snapshot="${5:-}"
  local path
  local document
  path="$(history_file)"
  if [[ -e "$path" ]]; then
    require_protected_file "$path" "Release history" || return 1
  fi
  document="$(
    jq -cn \
      --arg event "$event" \
      --arg outcome "$outcome" \
      --arg revision "$revision" \
      --arg reason_code "$reason_code" \
      --arg snapshot "$snapshot" \
      --arg occurred_at "$(date --utc '+%Y-%m-%dT%H:%M:%SZ')" \
      '{contract_version: "1.0.0", event: $event, outcome: $outcome,
        revision: $revision, reason_code: $reason_code,
        snapshot_id: (if $snapshot == "" then null else $snapshot end),
        occurred_at: $occurred_at}'
  )" || return 1
  printf '%s\n' "$document" >>"$path"
  chmod 0600 "$path"
}

active_field() {
  local state_json="$1"
  local field="$2"
  jq -er ".active.$field" <<<"$state_json"
}

verify_recorded_release() {
  local release_json="$1"
  local app_image
  local backup_image
  app_image="$(jq -er .app_image <<<"$release_json")" || return 1
  backup_image="$(jq -er .backup_image <<<"$release_json")" || return 1
  verify_image "$app_image" "$(jq -er .revision <<<"$release_json")" || return 1
  verify_image "$backup_image" "$(jq -er .revision <<<"$release_json")" || return 1
  [[ "$(image_id "$app_image")" == "$(jq -er .app_image_id <<<"$release_json")" ]] || {
    echo "Recorded application image ID has drifted" >&2
    return 1
  }
  [[ "$(image_id "$backup_image")" == "$(jq -er .backup_image_id <<<"$release_json")" ]] || {
    echo "Recorded backup image ID has drifted" >&2
    return 1
  }
}

wait_for_release() {
  local revision="$1"
  local app_image="$2"
  local backup_image="$3"
  local expected_app_id
  local expected_backup_id
  local melloa_container
  local backup_container
  local migration_container
  local login_container
  local melloa_state
  local migration_state
  local login_state
  local elapsed=0
  expected_app_id="$(image_id "$app_image")" || return 1
  expected_backup_id="$(image_id "$backup_image")" || return 1
  while ((elapsed < RELEASE_TIMEOUT)); do
    melloa_container="$(compose_release "$revision" "$app_image" "$backup_image" ps --all --quiet melloa)"
    backup_container="$(compose_release "$revision" "$app_image" "$backup_image" ps --all --quiet backup)"
    migration_container="$(compose_release "$revision" "$app_image" "$backup_image" ps --all --quiet migrate)"
    login_container="$(compose_release "$revision" "$app_image" "$backup_image" ps --all --quiet database-logins)"
    melloa_state=""
    migration_state=""
    login_state=""
    [[ -z "$melloa_container" ]] || melloa_state="$(
      docker inspect --format '{{.State.Status}}' "$melloa_container"
    )"
    [[ -z "$migration_container" ]] || migration_state="$(
      docker inspect --format '{{.State.Status}}' "$migration_container"
    )"
    [[ -z "$login_container" ]] || login_state="$(
      docker inspect --format '{{.State.Status}}' "$login_container"
    )"
    if [[ "$melloa_state" == restarting || "$melloa_state" == dead ]] ||
      { [[ "$migration_state" == exited ]] &&
        [[ "$(docker inspect --format '{{.State.ExitCode}}' "$migration_container")" != 0 ]]; } ||
      { [[ "$login_state" == exited ]] &&
        [[ "$(docker inspect --format '{{.State.ExitCode}}' "$login_container")" != 0 ]]; }; then
      echo "Candidate release exited before activation" >&2
      return 1
    fi
    if [[ -n "$melloa_container" && -n "$backup_container" && -n "$migration_container" && -n "$login_container" ]] &&
      [[ "$melloa_state" == running ]] &&
      [[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$melloa_container")" == healthy ]] &&
      [[ "$(docker inspect --format '{{.Image}}' "$melloa_container")" == "$expected_app_id" ]] &&
      [[ "$(docker inspect --format '{{.State.Status}}' "$backup_container")" == running ]] &&
      [[ "$(docker inspect --format '{{.Image}}' "$backup_container")" == "$expected_backup_id" ]] &&
      [[ "$(docker inspect --format '{{.State.ExitCode}}' "$migration_container")" == 0 ]] &&
      [[ "$(docker inspect --format '{{.State.ExitCode}}' "$login_container")" == 0 ]]; then
      return 0
    fi
    sleep "$RELEASE_POLL_SECONDS"
    elapsed=$((elapsed + RELEASE_POLL_SECONDS))
  done
  echo "Candidate release did not become healthy before the deadline" >&2
  compose_release "$revision" "$app_image" "$backup_image" ps --all >&2 || true
  compose_release "$revision" "$app_image" "$backup_image" \
    logs --no-color --tail=120 melloa migrate database-logins >&2 || true
  return 1
}

backup_stopped_release() {
  local revision="$1"
  local app_image="$2"
  local backup_image="$3"
  local runtime_state_dir
  local marker
  runtime_state_dir="$(read_env_path MELLOA_RUNTIME_STATE_DIR)" || return 1
  marker="$runtime_state_dir/backup-status.json"
  if ! compose_release "$revision" "$app_image" "$backup_image" \
    run --rm --no-deps backup release >/dev/null; then
    echo "Pre-deployment encrypted backup failed" >&2
    return 1
  fi
  require_protected_file "$marker" "Backup status" || return 1
  if ! jq -e '.result == "success" and (.snapshot_id | test("^[0-9a-f]{64}$"))' \
    "$marker" >/dev/null; then
    echo "Pre-deployment backup did not produce a valid snapshot receipt" >&2
    return 1
  fi
  jq -er .snapshot_id "$marker"
}

start_release() {
  local revision="$1"
  local app_image="$2"
  local backup_image="$3"
  compose_release "$revision" "$app_image" "$backup_image" up --detach --no-build &&
    wait_for_release "$revision" "$app_image" "$backup_image" &&
    compose_release "$revision" "$app_image" "$backup_image" \
      run --rm --no-deps migrate migrate check >/dev/null
}

restart_active_after_abort() {
  local active_json="$1"
  [[ "$active_json" != null ]] || return 0
  local revision
  local app_image
  local backup_image
  revision="$(jq -er .revision <<<"$active_json")"
  app_image="$(jq -er .app_image <<<"$active_json")"
  backup_image="$(jq -er .backup_image <<<"$active_json")"
  write_activation "$revision" || return 1
  start_release "$revision" "$app_image" "$backup_image"
}

restore_release_files() {
  local state_json="$1"
  local path
  if [[ "$state_json" == null ]]; then
    path="$(state_file)"
    rm -f -- "$path" "$STATE_DIR/active-revision"
    return
  fi
  write_state \
    "$(jq -c .active <<<"$state_json")" \
    "$(jq -c .previous <<<"$state_json")" \
    "$(jq -r '.predeploy_snapshot // ""' <<<"$state_json")" &&
    write_activation "$(jq -er .active.revision <<<"$state_json")"
}

arm_recovery() {
  RECOVERY_MODE="$1"
  RECOVERY_ACTIVE_JSON="$2"
  RECOVERY_STATE_JSON="$3"
  RECOVERY_REVISION="$4"
  RECOVERY_APP_IMAGE="$5"
  RECOVERY_BACKUP_IMAGE="$6"
  RECOVERY_SNAPSHOT="${7:-}"
  RECOVERY_EVENT="$8"
}

disarm_recovery() {
  RECOVERY_MODE=""
}

recover_interrupted_operation() {
  local mode="$RECOVERY_MODE"
  [[ -n "$mode" ]] || return 0
  RECOVERY_MODE=""
  echo "Release operation was interrupted; recovering the last active release." >&2
  compose_release \
    "$RECOVERY_REVISION" \
    "$RECOVERY_APP_IMAGE" \
    "$RECOVERY_BACKUP_IMAGE" \
    stop melloa backup >/dev/null 2>&1 || true
  restore_release_files "$RECOVERY_STATE_JSON" || return 1
  if [[ "$mode" == restore-active ]]; then
    if [[ "$RECOVERY_ACTIVE_JSON" == null || -z "$RECOVERY_SNAPSHOT" ]]; then
      echo "Interrupted deployment has no previous snapshot to restore" >&2
      return 1
    fi
    if ! compose_release \
      "$RECOVERY_REVISION" \
      "$RECOVERY_APP_IMAGE" \
      "$RECOVERY_BACKUP_IMAGE" \
      run --rm --no-deps restore \
        restore-database-replace "$RECOVERY_SNAPSHOT" >/dev/null; then
      echo "Interrupted deployment could not restore its pre-deployment snapshot" >&2
      return 1
    fi
  fi
  if [[ "$RECOVERY_ACTIVE_JSON" != null ]] &&
    ! restart_active_after_abort "$RECOVERY_ACTIVE_JSON"; then
    echo "Interrupted release recovery could not restart the last active release" >&2
    return 1
  fi
  record_history \
    "$RECOVERY_EVENT" interrupted "$RECOVERY_REVISION" \
    release.operation_interrupted "$RECOVERY_SNAPSHOT" || true
  echo "The last active release has been recovered." >&2
}

release_exit_trap() {
  local status="$1"
  trap - EXIT HUP INT TERM
  if ((status != 0)) && [[ -n "$RECOVERY_MODE" ]]; then
    if ! recover_interrupted_operation; then
      echo "Automatic release recovery failed; keep the server isolated and inspect release status." >&2
      status=1
    fi
  fi
  exit "$status"
}

recover_failed_candidate() {
  local candidate_revision="$1"
  local candidate_app="$2"
  local candidate_backup="$3"
  local active_json="$4"
  local snapshot="$5"
  local state_json="$6"
  compose_release "$candidate_revision" "$candidate_app" "$candidate_backup" \
    stop melloa backup >/dev/null 2>&1 || true
  if [[ "$active_json" == null ]]; then
    restore_release_files "$state_json" || return 1
    record_history deploy failed "$candidate_revision" release.first_deploy_failed "$snapshot" || true
    disarm_recovery
    return 0
  fi
  if [[ -z "$snapshot" ]]; then
    echo "A previous release exists but no recovery snapshot is available" >&2
    return 1
  fi
  if ! compose_release "$candidate_revision" "$candidate_app" "$candidate_backup" \
    run --rm --no-deps restore restore-database-replace "$snapshot"; then
    echo "Automatic release rollback could not restore the pre-deployment database" >&2
    return 1
  fi
  restore_release_files "$state_json" || return 1
  if ! restart_active_after_abort "$active_json"; then
    echo "Pre-deployment state was restored but the previous release did not recover" >&2
    return 1
  fi
  record_history deploy rolled_back "$candidate_revision" release.candidate_unhealthy "$snapshot" || true
  echo "Candidate failed; the pre-deployment database and previous release were restored." >&2
  disarm_recovery
}

deploy_release() {
  local state_json
  local active_json
  local candidate_json
  local snapshot=""
  local head_revision

  if [[ -z "$REVISION" ]]; then
    REVISION="$(git -C "$ROOT" rev-parse HEAD)" || return 1
  fi
  validate_revision "$REVISION" || return 1
  APP_IMAGE="${APP_IMAGE:-melloa-local/server:$REVISION}"
  BACKUP_IMAGE="${BACKUP_IMAGE:-melloa-local/backup:$REVISION}"
  validate_image_reference "$APP_IMAGE" || return 1
  validate_image_reference "$BACKUP_IMAGE" || return 1

  if [[ "$NO_BUILD" == false ]]; then
    head_revision="$(git -C "$ROOT" rev-parse HEAD)" || return 1
    if [[ "$REVISION" != "$head_revision" ]]; then
      echo "Built release revision must equal the checked-out commit" >&2
      return 1
    fi
    if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]]; then
      echo "Release builds require a clean reviewed source checkout" >&2
      return 1
    fi
    if ! compose_release "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE" build melloa backup; then
      return 1
    fi
  fi
  verify_image "$APP_IMAGE" "$REVISION" || return 1
  verify_image "$BACKUP_IMAGE" "$REVISION" || return 1

  state_json="$(load_state)" || return 1
  active_json="$(jq -c 'if . == null then null else .active end' <<<"$state_json")"
  if [[ "$active_json" != null ]]; then
    verify_recorded_release "$active_json" || return 1
    if [[ "$(jq -er .revision <<<"$active_json")" == "$REVISION" ]] &&
      [[ "$(jq -er .app_image_id <<<"$active_json")" == "$(image_id "$APP_IMAGE")" ]] &&
      [[ "$(jq -er .backup_image_id <<<"$active_json")" == "$(image_id "$BACKUP_IMAGE")" ]]; then
      arm_recovery restart-active "$active_json" "$state_json" \
        "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE" "" deploy
      write_activation "$REVISION" || return 1
      start_release "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE" || return 1
      disarm_recovery
      echo "Release $REVISION is already active."
      return 0
    fi
    arm_recovery restart-active "$active_json" "$state_json" \
      "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE" "" deploy
    compose_release \
      "$(jq -er .revision <<<"$active_json")" \
      "$(jq -er .app_image <<<"$active_json")" \
      "$(jq -er .backup_image <<<"$active_json")" \
      stop melloa backup >/dev/null || return 1
    snapshot="$(
      backup_stopped_release \
        "$(jq -er .revision <<<"$active_json")" \
        "$(jq -er .app_image <<<"$active_json")" \
        "$(jq -er .backup_image <<<"$active_json")"
    )" || {
      record_history deploy failed "$REVISION" release.prebackup_failed || true
      if restart_active_after_abort "$active_json"; then
        disarm_recovery
      fi
      return 1
    }
  else
    compose_release "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE" \
      stop melloa backup >/dev/null 2>&1 || true
  fi

  if ! record_history deploy started "$REVISION" release.deploy_started "$snapshot"; then
    if [[ "$active_json" != null ]] && restart_active_after_abort "$active_json"; then
      disarm_recovery
    fi
    return 1
  fi
  arm_recovery \
    "$([[ "$active_json" == null ]] && printf stop-candidate || printf restore-active)" \
    "$active_json" "$state_json" "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE" \
    "$snapshot" deploy
  if ! start_release "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE"; then
    recover_failed_candidate \
      "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE" \
      "$active_json" "$snapshot" "$state_json" || true
    return 1
  fi

  candidate_json="$(
    release_object "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE" \
      "$(date --utc '+%Y-%m-%dT%H:%M:%SZ')"
  )" || return 1
  if ! write_state "$candidate_json" "$active_json" "$snapshot" ||
    ! write_activation "$REVISION"; then
    recover_failed_candidate \
      "$REVISION" "$APP_IMAGE" "$BACKUP_IMAGE" \
      "$active_json" "$snapshot" "$state_json" || true
    return 1
  fi
  disarm_recovery
  if ! record_history deploy succeeded "$REVISION" release.activated "$snapshot"; then
    echo "Release activated, but its success history could not be appended." >&2
  fi
  echo "Release $REVISION is healthy and active."
}

rollback_release() {
  local state_json
  local active_json
  local previous_json
  local active_revision
  local active_app
  local active_backup
  local previous_revision
  local previous_app
  local previous_backup
  local snapshot
  local replacement_state

  state_json="$(load_state)" || return 1
  if [[ "$state_json" == null || "$(jq -c .previous <<<"$state_json")" == null ]]; then
    echo "No previous release is available for rollback" >&2
    return 1
  fi
  active_json="$(jq -c .active <<<"$state_json")"
  previous_json="$(jq -c .previous <<<"$state_json")"
  verify_recorded_release "$active_json" || return 1
  verify_recorded_release "$previous_json" || return 1
  active_revision="$(jq -er .revision <<<"$active_json")"
  active_app="$(jq -er .app_image <<<"$active_json")"
  active_backup="$(jq -er .backup_image <<<"$active_json")"
  previous_revision="$(jq -er .revision <<<"$previous_json")"
  previous_app="$(jq -er .app_image <<<"$previous_json")"
  previous_backup="$(jq -er .backup_image <<<"$previous_json")"

  arm_recovery restart-active "$active_json" "$state_json" \
    "$previous_revision" "$previous_app" "$previous_backup" "" rollback
  compose_release "$active_revision" "$active_app" "$active_backup" \
    stop melloa backup >/dev/null || return 1
  snapshot="$(backup_stopped_release "$active_revision" "$active_app" "$active_backup")" || {
    if restart_active_after_abort "$active_json"; then
      disarm_recovery
    fi
    return 1
  }
  if ! compose_release "$previous_revision" "$previous_app" "$previous_backup" \
    run --rm --no-deps migrate migrate check >/dev/null; then
    echo "Previous release is not compatible with the current database; rollback refused." >&2
    record_history rollback refused "$previous_revision" release.schema_incompatible "$snapshot" || true
    if restart_active_after_abort "$active_json"; then
      disarm_recovery
    fi
    return 1
  fi
  if ! start_release "$previous_revision" "$previous_app" "$previous_backup"; then
    if restart_active_after_abort "$active_json"; then
      disarm_recovery
    fi
    return 1
  fi
  replacement_state="$(
    release_object "$previous_revision" "$previous_app" "$previous_backup" \
      "$(date --utc '+%Y-%m-%dT%H:%M:%SZ')"
  )" || return 1
  if ! write_state "$replacement_state" "$active_json" "$snapshot" ||
    ! write_activation "$previous_revision"; then
    return 1
  fi
  disarm_recovery
  if ! record_history \
    rollback succeeded "$previous_revision" release.rollback_activated "$snapshot"; then
    echo "Rollback activated, but its success history could not be appended." >&2
  fi
  echo "Rolled back to release $previous_revision without discarding owner data."
}

for required in docker jq flock awk stat mktemp date; do
  require_command "$required" || exit 2
done
validate_positive_integer "$RELEASE_TIMEOUT" || {
  echo "Release health timeout must be a positive integer" >&2
  exit 2
}
validate_positive_integer "$RELEASE_POLL_SECONDS" || {
  echo "Release poll interval must be a positive integer" >&2
  exit 2
}
[[ -n "$STATE_DIR" ]] || usage
prepare_state_dir || exit 2

exec 9>"$STATE_DIR/release.lock"
if ! flock --nonblock 9; then
  echo "Another release operation is already running" >&2
  exit 1
fi

trap 'release_exit_trap $?' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

case "$COMMAND" in
  deploy)
    [[ -n "$ENV_FILE" ]] || usage
    require_protected_file "$ENV_FILE" "Server environment file" || exit 2
    deploy_release
    ;;
  rollback)
    [[ -n "$ENV_FILE" ]] || usage
    require_protected_file "$ENV_FILE" "Server environment file" || exit 2
    rollback_release
    ;;
  status)
    load_state | jq .
    ;;
  *)
    usage
    ;;
esac
