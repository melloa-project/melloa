#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-first-install-test.XXXXXX)"
readonly INPUTS="$WORKDIR/inputs"
readonly TARGET="$WORKDIR/target"
readonly MOUNT_TARGET="$WORKDIR/mount-target"
readonly DEFAULT_MODEL_TARGET="$WORKDIR/default-model-target"
readonly BAD_TARGET="$WORKDIR/bad-target"
readonly BAD_MOUNT_TARGET="$WORKDIR/bad-mount-target"
readonly BAD_SECRET_TARGET="$WORKDIR/bad-secret-target"
readonly BAD_EXTERNAL_MISSING_TARGET="$WORKDIR/bad-external-missing-target"
readonly BAD_MODEL_TARGET="$WORKDIR/bad-model-target"
readonly BAD_COST_TARGET="$WORKDIR/bad-cost-target"
readonly BAD_DUPLICATE_TARGET="$WORKDIR/bad-duplicate-target"
readonly BAD_LOCAL_TARGET="$WORKDIR/bad-local-target"
readonly SELF_CHANGE_TARGET="$WORKDIR/self-change-target"
readonly CA_RESUME_TARGET="$WORKDIR/ca-resume-target"
readonly LOG="$WORKDIR/first-install.log"
readonly CHECKLIST_LOG="$WORKDIR/first-install-checklist.log"
readonly MOUNT_LOG="$WORKDIR/first-install-mount.log"
readonly DEFAULT_MODEL_LOG="$WORKDIR/first-install-default-model.log"
readonly RESUME_LOG="$WORKDIR/first-install-resume.log"
readonly SELF_CHANGE_LOG="$WORKDIR/first-install-self-change.log"
readonly CA_RESUME_SETUP_LOG="$WORKDIR/first-install-ca-resume-setup.log"
readonly CA_RESUME_LOG="$WORKDIR/first-install-ca-resume.log"
readonly BAD_LOG="$WORKDIR/first-install-bad-input.log"
readonly BAD_MOUNT_LOG="$WORKDIR/first-install-bad-mount.log"
readonly BAD_SECRET_LOG="$WORKDIR/first-install-bad-secret.log"
readonly BAD_EXTERNAL_MISSING_LOG="$WORKDIR/first-install-bad-external-missing.log"
readonly BAD_MODEL_LOG="$WORKDIR/first-install-bad-model.log"
readonly BAD_COST_LOG="$WORKDIR/first-install-bad-cost.log"
readonly BAD_DUPLICATE_LOG="$WORKDIR/first-install-bad-duplicate.log"
readonly BAD_LOCAL_LOG="$WORKDIR/first-install-bad-local.log"
readonly TEST_UID="$(id -u)"
readonly TEST_GID="$(id -g)"
readonly DEFAULT_GUARDIAN_ROOT="$WORKDIR/default-guardian"

select_backup_mount() {
  local candidate
  for candidate in /var/tmp /tmp /dev/shm /run /proc; do
    [[ -d "$candidate" && ! -L "$candidate" ]] || continue
    findmnt --mountpoint "$candidate" >/dev/null || continue
    [[ "$(stat --format='%d' "$candidate")" != "$(stat --format='%d' /)" ]] ||
      continue
    printf '%s' "$candidate"
    return 0
  done
  echo "No explicit backup-mount candidate is available for the first-install test" >&2
  return 2
}

cleanup() {
  if [[ "$WORKDIR" == /tmp/melloa-first-install-test.* && -d "$WORKDIR" ]]; then
    rm -rf -- "$WORKDIR"
  fi
}
trap cleanup EXIT HUP INT TERM

readonly REAL_BACKUP_MOUNT="$(select_backup_mount)"
readonly BAD_MOUNT_REPOSITORY="$WORKDIR/not-mounted-backup"

install -d -m 0700 "$INPUTS"
install -d -m 0700 "$DEFAULT_GUARDIAN_ROOT/state/local-preview"
install -d -m 0700 "$BAD_MOUNT_REPOSITORY"
printf '{"contract_version":"1.0.0"}\n' >"$INPUTS/status.json"
printf '%s\n' '-----BEGIN PUBLIC KEY-----' 'first-install-test' \
  '-----END PUBLIC KEY-----' >"$INPUTS/public.pem"
printf '{"contract_version":"1.0.0","source":"default-guardian"}\n' \
  >"$DEFAULT_GUARDIAN_ROOT/state/local-preview/status.json"
printf '%s\n' '-----BEGIN PUBLIC KEY-----' 'default-guardian-test' \
  '-----END PUBLIC KEY-----' >"$DEFAULT_GUARDIAN_ROOT/state/local-preview/public.pem"
printf '%s\n' '-----BEGIN CERTIFICATE-----' 'first-install-ca-test' \
  '-----END CERTIFICATE-----' >"$INPUTS/build-ca.pem"

"$ROOT/infra/server/first-install.sh" --print-input-checklist >"$CHECKLIST_LOG" 2>&1
grep --fixed-strings --quiet "Melloa first-owner setup input checklist" "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  'sudo infra/server/first-install.sh --source "$PWD"' \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "Debian 13 (trixie), Ubuntu 24.04 LTS (noble), or Pop!_OS 24.04 (noble) on amd64" \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "Backup repository: a mounted off-device directory, normally /mnt/melloa-off-device-backup." \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "findmnt --mountpoint /mnt/melloa-off-device-backup" \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "If findmnt prints nothing, configure and mount an already prepared disk, USB volume, or NAS" \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "Do not use a plain directory on the server root disk, and do not format a disk" \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet "@BotFather" "$CHECKLIST_LOG"
grep --fixed-strings --quiet "Default model IDs: capable gpt-5.6-terra; economy gpt-5.6-luna." \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet "Enable self-change for the first server proof." "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "Guardian calls this preview-state because it creates an offline public status projection." \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "Pass only status.json and public.pem to Melloa" \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "do not pass Guardian private keys, journals, locks, or control commands" \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "fine-grained GitHub personal access token scoped only to this repository" \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet \
  "Repository permissions -> Contents: Read and write." \
  "$CHECKLIST_LOG"
grep --fixed-strings --quiet "does not require root, prompt for secrets" \
  <("$ROOT/infra/server/first-install.sh" --help 2>&1)
grep --fixed-strings --quiet \
  "/change propose Add a focused unit test for one existing owner-visible /change command message." \
  "$ROOT/infra/server/first-install.sh"
grep --fixed-strings --quiet \
  "/change approve <change_id> <16-character proposal token>" \
  "$ROOT/infra/server/first-install.sh"
if grep --fixed-strings --quiet "Melloa first-owner setup will now collect private values." \
  "$CHECKLIST_LOG"; then
  echo "First-install input checklist started the installer" >&2
  exit 1
fi

MELLOA_TEST_GUARDIAN_ROOT="$DEFAULT_GUARDIAN_ROOT" \
MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
MELLOA_SETUP_CAPABLE_ROUTE_KIND=openai \
MELLOA_SETUP_CAPABLE_MODEL_ID=capable-test-model \
MELLOA_SETUP_CAPABLE_TOKEN=capable_first_install_secret \
MELLOA_SETUP_CAPABLE_ESTIMATED_MAX_COST_GBP=0.05 \
MELLOA_SETUP_CAPABLE_INPUT_COST_GBP_PER_MILLION_TOKENS=1.25 \
MELLOA_SETUP_CAPABLE_OUTPUT_COST_GBP_PER_MILLION_TOKENS=10 \
MELLOA_SETUP_ECONOMY_ROUTE_KIND=openai \
MELLOA_SETUP_ECONOMY_MODEL_ID=economy-test-model \
MELLOA_SETUP_ECONOMY_TOKEN=economy_first_install_secret \
MELLOA_SETUP_ECONOMY_ESTIMATED_MAX_COST_GBP=0.01 \
MELLOA_SETUP_ECONOMY_INPUT_COST_GBP_PER_MILLION_TOKENS=0.25 \
MELLOA_SETUP_ECONOMY_OUTPUT_COST_GBP_PER_MILLION_TOKENS=2 \
MELLOA_SETUP_RESTIC_PASSWORD=restic_first_install_secret_123456789 \
  "$ROOT/infra/server/first-install.sh" \
    --source "$ROOT" \
    --ca-file "$INPUTS/build-ca.pem" \
    --root "$TARGET" \
    --skip-activation \
    </dev/null \
    >"$LOG" 2>&1

readonly PRIVATE="$TARGET/etc/melloa/private"
[[ "$(stat --format='%a:%u:%g' "$PRIVATE")" == "700:$TEST_UID:$TEST_GID" ]]
[[ "$(jq -r .owner_user_id "$PRIVATE/telegram-owner.json")" == 5678 ]]
[[ "$(jq -r .model_id "$PRIVATE/capable-model.json")" == capable-test-model ]]
[[ "$(jq -r .provider_id "$PRIVATE/capable-model.json")" == provider.openai-capable ]]
[[ "$(jq -r .base_url "$PRIVATE/capable-model.json")" == https://api.openai.com/v1 ]]
[[ "$(jq -r .api_style "$PRIVATE/capable-model.json")" == responses ]]
[[ "$(jq -r .max_input_tokens "$PRIVATE/capable-model.json")" == 16384 ]]
[[ "$(jq -r .max_output_tokens "$PRIVATE/capable-model.json")" == 2048 ]]
[[ "$(jq -r .timeout_ms "$PRIVATE/capable-model.json")" == 60000 ]]
[[ "$(jq -r .health_timeout_ms "$PRIVATE/capable-model.json")" == 5000 ]]
[[ "$(jq -r .authorization_token_file "$PRIVATE/capable-model.json")" == \
  /run/melloa/model-credentials/capable-token ]]
[[ "$(jq -r .provider_id "$PRIVATE/economy-model.json")" == provider.openai-economy ]]
[[ "$(jq -r .base_url "$PRIVATE/economy-model.json")" == https://api.openai.com/v1 ]]
[[ "$(jq -r .processing_location "$PRIVATE/economy-model.json")" == approved_provider ]]
[[ "$(jq -r .authorization_token_file "$PRIVATE/economy-model.json")" == \
  /run/melloa/model-credentials/economy-token ]]
[[ "$(stat --format='%a:%u:%g' "$PRIVATE/model-credentials/capable-token")" == \
  "600:$TEST_UID:$TEST_GID" ]]
[[ "$(<"$PRIVATE/model-credentials/capable-token")" == capable_first_install_secret ]]
[[ "$(stat --format='%a:%u:%g' "$PRIVATE/model-credentials/economy-token")" == \
  "600:$TEST_UID:$TEST_GID" ]]
[[ "$(<"$PRIVATE/model-credentials/economy-token")" == economy_first_install_secret ]]
grep --fixed-strings --quiet \
  'MELLOA_BACKUP_REPOSITORY_DIR=/mnt/melloa-off-device-backup' \
  "$TARGET/etc/melloa/server.env"
grep --fixed-strings --quiet 'MELLOA_BUILD_CA_FILE=/etc/melloa/build-ca.pem' \
  "$TARGET/etc/melloa/server.env"
[[ "$(stat --format='%a:%u:%g' "$TARGET/etc/melloa/build-ca.pem")" == \
  "644:$TEST_UID:$TEST_GID" ]]
cmp --silent "$INPUTS/build-ca.pem" "$TARGET/etc/melloa/build-ca.pem"
grep --fixed-strings --quiet 'MELLOA_SELF_CHANGE_ENABLED=false' \
  "$TARGET/etc/melloa/self-change.env"
[[ "$(jq -r .codex_mode "$TARGET/etc/melloa/configuration.json")" == disabled ]]
[[ "$(wc -c <"$PRIVATE/git-credentials")" == 1 ]]
[[ "$(wc -c <"$PRIVATE/codex-api-key")" == 1 ]]
grep --fixed-strings --quiet "Public path checks passed." "$LOG"
grep --fixed-strings --quiet "Telegram bot input:" "$LOG"
grep --fixed-strings --quiet \
  "Create one dedicated bot with @BotFather using /newbot, then paste only the HTTP API token." \
  "$LOG"
grep --fixed-strings --quiet \
  "Do not send /start to the bot yet; if owner ID is blank, setup prints the exact pairing phrase." \
  "$LOG"
grep --fixed-strings --quiet \
  "Configure the capable model route: higher-quality replies when accuracy matters." \
  "$LOG"
grep --fixed-strings --quiet \
  "Choose external only for another hosted provider or router that documents:" \
  "$LOG"
grep --fixed-strings --quiet \
  "Do not guess zero prices; use the current provider pricing you reviewed for this account." \
  "$LOG"
grep --fixed-strings --quiet \
  "OpenAI preset defaults: capable uses gpt-5.6-terra; economy uses gpt-5.6-luna." \
  "$LOG"
grep --fixed-strings --quiet \
  "Use the current OpenAI pricing for capable-test-model, converted to GBP for this account and service tier." \
  "$LOG"
grep --fixed-strings --quiet \
  "Token limits and timeouts use setup defaults unless a staged environment override is supplied." \
  "$LOG"
grep --fixed-strings --quiet "Backup recovery password:" "$LOG"
grep --fixed-strings --quiet \
  "Enter a 32-128 character base64url-safe restic password that you keep outside this server and backup disk." \
  "$LOG"
grep --fixed-strings --quiet \
  "python3.13 -c 'import secrets; print(secrets.token_urlsafe(48))'" \
  "$LOG"
grep --fixed-strings --quiet "Bounded self-change setup:" "$LOG"
grep --fixed-strings --quiet \
  "The first server proof expects self-change workers enabled." \
  "$LOG"
grep --fixed-strings --quiet \
  "If enabled, use a fine-grained GitHub personal access token scoped only to this repository" \
  "$LOG"
grep --fixed-strings --quiet \
  "Repository permissions -> Contents: Read and write." \
  "$LOG"
grep --fixed-strings --quiet \
  "Use a Codex/OpenAI API key for the planner; do not paste a ChatGPT/Codex subscription login artifact." \
  "$LOG"
if grep --fixed-strings --quiet "model max input tokens" "$LOG"; then
  echo "First-install setup prompted for advanced model token defaults" >&2
  exit 1
fi
grep --fixed-strings --quiet \
  "When ready, run: sudo /usr/local/libexec/melloa/activate --source $ROOT --origin https://github.com/melloa-project/melloa.git --initialize-backup" \
  "$LOG"
grep --fixed-strings --quiet \
  "Then verify before relying on the server: sudo /usr/local/libexec/melloa/verify-owner-journey" \
  "$LOG"

MELLOA_TEST_VALIDATE_BACKUP_MOUNT=yes \
MELLOA_SETUP_BACKUP_REPOSITORY="$REAL_BACKUP_MOUNT" \
MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
MELLOA_SETUP_CAPABLE_ROUTE_KIND=openai \
MELLOA_SETUP_CAPABLE_MODEL_ID=mount-capable-test-model \
MELLOA_SETUP_CAPABLE_TOKEN=capable_mount_test_secret \
MELLOA_SETUP_CAPABLE_ESTIMATED_MAX_COST_GBP=0.05 \
MELLOA_SETUP_CAPABLE_INPUT_COST_GBP_PER_MILLION_TOKENS=1.25 \
MELLOA_SETUP_CAPABLE_OUTPUT_COST_GBP_PER_MILLION_TOKENS=10 \
MELLOA_SETUP_ECONOMY_ROUTE_KIND=openai \
MELLOA_SETUP_ECONOMY_MODEL_ID=mount-economy-test-model \
MELLOA_SETUP_ECONOMY_TOKEN=economy_mount_test_secret \
MELLOA_SETUP_ECONOMY_ESTIMATED_MAX_COST_GBP=0.01 \
MELLOA_SETUP_ECONOMY_INPUT_COST_GBP_PER_MILLION_TOKENS=0.25 \
MELLOA_SETUP_ECONOMY_OUTPUT_COST_GBP_PER_MILLION_TOKENS=2 \
MELLOA_SETUP_RESTIC_PASSWORD=restic_mount_test_secret_123456789 \
  "$ROOT/infra/server/first-install.sh" \
    --source "$ROOT" \
    --root "$MOUNT_TARGET" \
    --skip-activation \
    </dev/null \
    >"$MOUNT_LOG" 2>&1
grep --fixed-strings --quiet "Public path checks passed." "$MOUNT_LOG"
grep --fixed-strings --quiet \
  "MELLOA_BACKUP_REPOSITORY_DIR=$REAL_BACKUP_MOUNT" \
  "$MOUNT_TARGET/etc/melloa/server.env"

MELLOA_TEST_GUARDIAN_ROOT="$DEFAULT_GUARDIAN_ROOT" \
MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
MELLOA_SETUP_CAPABLE_ROUTE_KIND=openai \
MELLOA_SETUP_CAPABLE_TOKEN=capable_default_model_secret \
MELLOA_SETUP_CAPABLE_ESTIMATED_MAX_COST_GBP=0.05 \
MELLOA_SETUP_CAPABLE_INPUT_COST_GBP_PER_MILLION_TOKENS=1.25 \
MELLOA_SETUP_CAPABLE_OUTPUT_COST_GBP_PER_MILLION_TOKENS=10 \
MELLOA_SETUP_ECONOMY_ROUTE_KIND=openai \
MELLOA_SETUP_ECONOMY_TOKEN=economy_default_model_secret \
MELLOA_SETUP_ECONOMY_ESTIMATED_MAX_COST_GBP=0.01 \
MELLOA_SETUP_ECONOMY_INPUT_COST_GBP_PER_MILLION_TOKENS=0.25 \
MELLOA_SETUP_ECONOMY_OUTPUT_COST_GBP_PER_MILLION_TOKENS=2 \
MELLOA_SETUP_RESTIC_PASSWORD=restic_default_model_secret_123456789 \
  "$ROOT/infra/server/first-install.sh" \
    --source "$ROOT" \
    --root "$DEFAULT_MODEL_TARGET" \
    --skip-activation \
    </dev/null \
    >"$DEFAULT_MODEL_LOG" 2>&1
readonly DEFAULT_MODEL_PRIVATE="$DEFAULT_MODEL_TARGET/etc/melloa/private"
[[ "$(jq -r .model_id "$DEFAULT_MODEL_PRIVATE/capable-model.json")" == gpt-5.6-terra ]]
[[ "$(jq -r .model_id "$DEFAULT_MODEL_PRIVATE/economy-model.json")" == gpt-5.6-luna ]]
cmp --silent \
  "$DEFAULT_GUARDIAN_ROOT/state/local-preview/status.json" \
  "$DEFAULT_MODEL_TARGET/var/lib/melloa/guardian-handoff/status.json"
cmp --silent \
  "$DEFAULT_GUARDIAN_ROOT/state/local-preview/public.pem" \
  "$DEFAULT_MODEL_TARGET/var/lib/melloa/guardian-handoff/public.pem"
grep --fixed-strings --quiet \
  "Detected Guardian public handoff defaults from $DEFAULT_GUARDIAN_ROOT/state/local-preview." \
  "$DEFAULT_MODEL_LOG"
grep --fixed-strings --quiet \
  "OpenAI preset defaults: capable uses gpt-5.6-terra; economy uses gpt-5.6-luna." \
  "$DEFAULT_MODEL_LOG"
grep --fixed-strings --quiet \
  "Official OpenAI standard short-context reference for gpt-5.6-terra: USD 2.00 input / USD 12.00 output per 1M tokens before GBP conversion." \
  "$DEFAULT_MODEL_LOG"
grep --fixed-strings --quiet \
  "Official OpenAI standard short-context reference for gpt-5.6-luna: USD 0.20 input / USD 1.20 output per 1M tokens before GBP conversion." \
  "$DEFAULT_MODEL_LOG"
grep --fixed-strings --quiet \
  "Enter reviewed GBP values for your account, region, context length, and service tier; check developers.openai.com/api/docs/pricing if unsure." \
  "$DEFAULT_MODEL_LOG"

MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
MELLOA_SETUP_CAPABLE_ROUTE_KIND=openai \
MELLOA_SETUP_CAPABLE_MODEL_ID=self-change-capable-model \
MELLOA_SETUP_CAPABLE_TOKEN=capable_self_change_secret \
MELLOA_SETUP_CAPABLE_ESTIMATED_MAX_COST_GBP=0.05 \
MELLOA_SETUP_CAPABLE_INPUT_COST_GBP_PER_MILLION_TOKENS=1.25 \
MELLOA_SETUP_CAPABLE_OUTPUT_COST_GBP_PER_MILLION_TOKENS=10 \
MELLOA_SETUP_CAPABLE_MAX_INPUT_TOKENS=32768 \
MELLOA_SETUP_CAPABLE_TIMEOUT_MS=45000 \
MELLOA_SETUP_ECONOMY_ROUTE_KIND=openai \
MELLOA_SETUP_ECONOMY_MODEL_ID=self-change-economy-model \
MELLOA_SETUP_ECONOMY_TOKEN=economy_self_change_secret \
MELLOA_SETUP_ECONOMY_ESTIMATED_MAX_COST_GBP=0.01 \
MELLOA_SETUP_ECONOMY_INPUT_COST_GBP_PER_MILLION_TOKENS=0.25 \
MELLOA_SETUP_ECONOMY_OUTPUT_COST_GBP_PER_MILLION_TOKENS=2 \
MELLOA_SETUP_RESTIC_PASSWORD=restic_self_change_secret_123456789 \
MELLOA_SETUP_ENABLE_SELF_CHANGE=yes \
MELLOA_SETUP_GITHUB_TOKEN=githubpatfirstinstall1234567890 \
MELLOA_SETUP_CODEX_MODE=api-key \
MELLOA_SETUP_CODEX_MODEL=codex-first-install-test \
MELLOA_SETUP_CODEX_API_KEY=sk-first-install-codex-key-1234567890 \
  "$ROOT/infra/server/first-install.sh" \
    --source "$ROOT" \
    --root "$SELF_CHANGE_TARGET" \
    --skip-activation \
    </dev/null \
    >"$SELF_CHANGE_LOG" 2>&1

readonly SELF_CHANGE_PRIVATE="$SELF_CHANGE_TARGET/etc/melloa/private"
grep --fixed-strings --quiet 'MELLOA_SELF_CHANGE_ENABLED=true' \
  "$SELF_CHANGE_TARGET/etc/melloa/self-change.env"
grep --fixed-strings --quiet 'MELLOA_CODEX_USE_API_KEY=true' \
  "$SELF_CHANGE_TARGET/etc/melloa/self-change.env"
grep --fixed-strings --quiet 'MELLOA_CODEX_MODEL=codex-first-install-test' \
  "$SELF_CHANGE_TARGET/etc/melloa/self-change.env"
[[ "$(jq -r .codex_mode "$SELF_CHANGE_TARGET/etc/melloa/configuration.json")" == api_key ]]
[[ "$(jq -r .max_input_tokens "$SELF_CHANGE_PRIVATE/capable-model.json")" == 32768 ]]
[[ "$(jq -r .timeout_ms "$SELF_CHANGE_PRIVATE/capable-model.json")" == 45000 ]]
grep --fixed-strings --quiet \
  "If enabled, use a fine-grained GitHub personal access token scoped only to this repository" \
  "$SELF_CHANGE_LOG"
grep --fixed-strings --quiet \
  "Repository permissions -> Contents: Read and write." \
  "$SELF_CHANGE_LOG"
grep --fixed-strings --quiet \
  "Use a Codex/OpenAI API key for the planner; do not paste a ChatGPT/Codex subscription login artifact." \
  "$SELF_CHANGE_LOG"
grep --fixed-strings --quiet \
  'https://x-access-token:githubpatfirstinstall1234567890@github.com' \
  "$SELF_CHANGE_PRIVATE/git-credentials"
[[ "$(<"$SELF_CHANGE_PRIVATE/codex-api-key")" == sk-first-install-codex-key-1234567890 ]]
"$ROOT/infra/server/first-install.sh" \
  --source "$ROOT" \
  --root "$TARGET" \
  </dev/null \
  >"$RESUME_LOG" 2>&1
grep --fixed-strings --quiet \
  "Private configuration is already installed. Activation was skipped by request." \
  "$RESUME_LOG"
grep --fixed-strings --quiet \
  "When ready, run: sudo /usr/local/libexec/melloa/activate --source $ROOT --origin https://github.com/melloa-project/melloa.git --initialize-backup" \
  "$RESUME_LOG"
grep --fixed-strings --quiet \
  "Then verify before relying on the server: sudo /usr/local/libexec/melloa/verify-owner-journey" \
  "$RESUME_LOG"
if grep --fixed-strings --quiet "MELLOA_SETUP_BACKUP_REPOSITORY is required" "$RESUME_LOG"; then
  echo "First-install rerun prompted for setup inputs instead of resuming" >&2
  exit 1
fi

MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
MELLOA_SETUP_CAPABLE_ROUTE_KIND=openai \
MELLOA_SETUP_CAPABLE_MODEL_ID=ca-resume-capable-model \
MELLOA_SETUP_CAPABLE_TOKEN=capable_ca_resume_secret \
MELLOA_SETUP_CAPABLE_ESTIMATED_MAX_COST_GBP=0.05 \
MELLOA_SETUP_CAPABLE_INPUT_COST_GBP_PER_MILLION_TOKENS=1.25 \
MELLOA_SETUP_CAPABLE_OUTPUT_COST_GBP_PER_MILLION_TOKENS=10 \
MELLOA_SETUP_ECONOMY_ROUTE_KIND=openai \
MELLOA_SETUP_ECONOMY_MODEL_ID=ca-resume-economy-model \
MELLOA_SETUP_ECONOMY_TOKEN=economy_ca_resume_secret \
MELLOA_SETUP_ECONOMY_ESTIMATED_MAX_COST_GBP=0.01 \
MELLOA_SETUP_ECONOMY_INPUT_COST_GBP_PER_MILLION_TOKENS=0.25 \
MELLOA_SETUP_ECONOMY_OUTPUT_COST_GBP_PER_MILLION_TOKENS=2 \
MELLOA_SETUP_RESTIC_PASSWORD=restic_ca_resume_secret_123456789 \
  "$ROOT/infra/server/first-install.sh" \
    --source "$ROOT" \
    --root "$CA_RESUME_TARGET" \
    --skip-activation \
    </dev/null \
    >"$CA_RESUME_SETUP_LOG" 2>&1
grep --fixed-strings --quiet \
  'MELLOA_BUILD_CA_FILE=/etc/ssl/certs/ca-certificates.crt' \
  "$CA_RESUME_TARGET/etc/melloa/server.env"
[[ ! -e "$CA_RESUME_TARGET/etc/melloa/build-ca.pem" ]]
"$ROOT/infra/server/first-install.sh" \
  --source "$ROOT" \
  --ca-file "$INPUTS/build-ca.pem" \
  --root "$CA_RESUME_TARGET" \
  </dev/null \
  >"$CA_RESUME_LOG" 2>&1
grep --fixed-strings --quiet \
  "Updated the installed public build CA bundle for future image builds." \
  "$CA_RESUME_LOG"
grep --fixed-strings --quiet 'MELLOA_BUILD_CA_FILE=/etc/melloa/build-ca.pem' \
  "$CA_RESUME_TARGET/etc/melloa/server.env"
cmp --silent "$INPUTS/build-ca.pem" "$CA_RESUME_TARGET/etc/melloa/build-ca.pem"
if grep --fixed-strings --quiet "MELLOA_SETUP_BACKUP_REPOSITORY is required" "$CA_RESUME_LOG"; then
  echo "First-install CA recovery prompted for setup inputs instead of resuming" >&2
  exit 1
fi

for secret in \
  '123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
  capable_first_install_secret \
  economy_first_install_secret \
  restic_first_install_secret_123456789 \
  capable_mount_test_secret \
  economy_mount_test_secret \
  restic_mount_test_secret_123456789 \
  capable_default_model_secret \
  economy_default_model_secret \
  restic_default_model_secret_123456789 \
  capable_self_change_secret \
  economy_self_change_secret \
  restic_self_change_secret_123456789 \
  githubpatfirstinstall1234567890 \
  sk-first-install-codex-key-1234567890; do
  if grep --fixed-strings --quiet \
    "$secret" "$LOG" "$MOUNT_LOG" "$DEFAULT_MODEL_LOG" \
    "$SELF_CHANGE_LOG" "$CA_RESUME_SETUP_LOG"; then
    echo "First-install setup exposed a private input" >&2
    exit 1
  fi
done

if MELLOA_SETUP_BACKUP_REPOSITORY=relative-backup-path \
  MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
  MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
    "$ROOT/infra/server/first-install.sh" \
      --source "$ROOT" \
      --root "$BAD_TARGET" \
      --skip-activation \
      </dev/null \
      >"$BAD_LOG" 2>&1; then
  echo "First-install setup accepted an invalid backup repository path" >&2
  exit 1
fi
grep --fixed-strings --quiet "backup repository must be a plain absolute path" "$BAD_LOG"
if grep --fixed-strings --quiet "TELEGRAM_BOT_TOKEN is required" "$BAD_LOG"; then
  echo "First-install setup prompted for secrets before public path validation" >&2
  exit 1
fi

if MELLOA_TEST_VALIDATE_BACKUP_MOUNT=yes \
  MELLOA_SETUP_BACKUP_REPOSITORY="$BAD_MOUNT_REPOSITORY" \
  MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
  MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
    "$ROOT/infra/server/first-install.sh" \
      --source "$ROOT" \
      --root "$BAD_MOUNT_TARGET" \
      --skip-activation \
      </dev/null \
      >"$BAD_MOUNT_LOG" 2>&1; then
  echo "First-install setup accepted a backup repository that was not a mount point" >&2
  exit 1
fi
grep --fixed-strings --quiet \
  "backup repository must be an explicit mount point; mount off-device storage at $BAD_MOUNT_REPOSITORY and rerun setup" \
  "$BAD_MOUNT_LOG"
grep --fixed-strings --quiet \
  "backup repository must use storage independent from the server root filesystem; mount off-device storage at" \
  "$ROOT/infra/server/first-install.sh"
if grep --fixed-strings --quiet "TELEGRAM_BOT_TOKEN is required" "$BAD_MOUNT_LOG"; then
  echo "First-install setup prompted for secrets before backup mount validation" >&2
  exit 1
fi

if MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
  MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
  MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
  MELLOA_SETUP_TELEGRAM_BOT_TOKEN=not-a-token \
    "$ROOT/infra/server/first-install.sh" \
      --source "$ROOT" \
      --root "$BAD_SECRET_TARGET" \
      --skip-activation \
      </dev/null \
      >"$BAD_SECRET_LOG" 2>&1; then
  echo "First-install setup accepted an invalid Telegram token" >&2
  exit 1
fi
grep --fixed-strings --quiet "Telegram bot token has an invalid format" "$BAD_SECRET_LOG"
if grep --fixed-strings --quiet "Configure the two conversation model routes." "$BAD_SECRET_LOG"; then
  echo "First-install setup asked model questions before Telegram token validation" >&2
  exit 1
fi
if grep --fixed-strings --quiet "not-a-token" "$BAD_SECRET_LOG"; then
  echo "First-install setup exposed an invalid private input" >&2
  exit 1
fi

if MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
  MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
  MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
  MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
  MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
  MELLOA_SETUP_CAPABLE_ROUTE_KIND=external \
  MELLOA_SETUP_CAPABLE_MODEL_ID=capable-test-model \
    "$ROOT/infra/server/first-install.sh" \
      --source "$ROOT" \
      --root "$BAD_EXTERNAL_MISSING_TARGET" \
      --skip-activation \
      </dev/null \
      >"$BAD_EXTERNAL_MISSING_LOG" 2>&1; then
  echo "First-install setup accepted an external route without an explicit base URL" >&2
  exit 1
fi
grep --fixed-strings --quiet \
  "MELLOA_SETUP_CAPABLE_BASE_URL is required when setup is not running interactively" \
  "$BAD_EXTERNAL_MISSING_LOG"
if grep --fixed-strings --quiet "MELLOA_SETUP_CAPABLE_TOKEN is required" \
  "$BAD_EXTERNAL_MISSING_LOG"; then
  echo "First-install setup asked for a model token before external URL selection" >&2
  exit 1
fi
if grep --fixed-strings --quiet \
  '123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' "$BAD_EXTERNAL_MISSING_LOG"; then
  echo "First-install setup exposed a private input while reporting a missing external URL" >&2
  exit 1
fi

if MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
  MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
  MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
  MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
  MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
  MELLOA_SETUP_CAPABLE_ROUTE_KIND=external \
  MELLOA_SETUP_CAPABLE_MODEL_ID=capable-test-model \
  MELLOA_SETUP_CAPABLE_BASE_URL=http://capable.example/v1 \
    "$ROOT/infra/server/first-install.sh" \
      --source "$ROOT" \
      --root "$BAD_MODEL_TARGET" \
      --skip-activation \
      </dev/null \
      >"$BAD_MODEL_LOG" 2>&1; then
  echo "First-install setup accepted an invalid external model URL" >&2
  exit 1
fi
grep --fixed-strings --quiet \
  "capable model base URL for an approved provider must use HTTPS with a host" \
  "$BAD_MODEL_LOG"
if grep --fixed-strings --quiet "MELLOA_SETUP_CAPABLE_TOKEN is required" "$BAD_MODEL_LOG"; then
  echo "First-install setup asked for a model token before model URL validation" >&2
  exit 1
fi
if grep --fixed-strings --quiet \
  '123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' "$BAD_MODEL_LOG"; then
  echo "First-install setup exposed a private input while reporting a model URL error" >&2
  exit 1
fi

if MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
  MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
  MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
  MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
  MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
  MELLOA_SETUP_CAPABLE_ROUTE_KIND=openai \
  MELLOA_SETUP_CAPABLE_MODEL_ID=capable-test-model \
  MELLOA_SETUP_CAPABLE_ESTIMATED_MAX_COST_GBP=not-a-decimal \
    "$ROOT/infra/server/first-install.sh" \
      --source "$ROOT" \
      --root "$BAD_COST_TARGET" \
      --skip-activation \
      </dev/null \
      >"$BAD_COST_LOG" 2>&1; then
  echo "First-install setup accepted an invalid model cost" >&2
  exit 1
fi
grep --fixed-strings --quiet \
  "capable maximum GBP cost must be a non-negative decimal" \
  "$BAD_COST_LOG"
if grep --fixed-strings --quiet "MELLOA_SETUP_CAPABLE_TOKEN is required" "$BAD_COST_LOG"; then
  echo "First-install setup asked for a model token before model cost validation" >&2
  exit 1
fi
if grep --fixed-strings --quiet \
  '123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' "$BAD_COST_LOG"; then
  echo "First-install setup exposed a private input while reporting a model cost error" >&2
  exit 1
fi

if MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
  MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
  MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
  MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
  MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
  MELLOA_SETUP_CAPABLE_ROUTE_KIND=openai \
  MELLOA_SETUP_CAPABLE_MODEL_ID=duplicate-test-model \
  MELLOA_SETUP_CAPABLE_TOKEN=capable_duplicate_secret \
  MELLOA_SETUP_CAPABLE_ESTIMATED_MAX_COST_GBP=0.05 \
  MELLOA_SETUP_CAPABLE_INPUT_COST_GBP_PER_MILLION_TOKENS=1.25 \
  MELLOA_SETUP_CAPABLE_OUTPUT_COST_GBP_PER_MILLION_TOKENS=10 \
  MELLOA_SETUP_ECONOMY_ROUTE_KIND=openai \
  MELLOA_SETUP_ECONOMY_MODEL_ID=duplicate-test-model \
  MELLOA_SETUP_ECONOMY_TOKEN=economy_duplicate_secret \
  MELLOA_SETUP_ECONOMY_ESTIMATED_MAX_COST_GBP=0.01 \
  MELLOA_SETUP_ECONOMY_INPUT_COST_GBP_PER_MILLION_TOKENS=0.25 \
  MELLOA_SETUP_ECONOMY_OUTPUT_COST_GBP_PER_MILLION_TOKENS=2 \
    "$ROOT/infra/server/first-install.sh" \
      --source "$ROOT" \
      --root "$BAD_DUPLICATE_TARGET" \
      --skip-activation \
      </dev/null \
      >"$BAD_DUPLICATE_LOG" 2>&1; then
  echo "First-install setup accepted duplicate capable/economy model targets" >&2
  exit 1
fi
grep --fixed-strings --quiet \
  "capable and economy model targets must differ" \
  "$BAD_DUPLICATE_LOG"
if grep --fixed-strings --quiet "MELLOA_SETUP_RESTIC_PASSWORD is required" "$BAD_DUPLICATE_LOG"; then
  echo "First-install setup continued to backup recovery input after duplicate model targets" >&2
  exit 1
fi
for secret in capable_duplicate_secret economy_duplicate_secret; do
  if grep --fixed-strings --quiet "$secret" "$BAD_DUPLICATE_LOG"; then
    echo "First-install setup exposed a private input while reporting duplicate model targets" >&2
    exit 1
  fi
done

if MELLOA_SETUP_BACKUP_REPOSITORY=/mnt/melloa-off-device-backup \
  MELLOA_SETUP_GUARDIAN_STATUS_FILE="$INPUTS/status.json" \
  MELLOA_SETUP_GUARDIAN_PUBLIC_KEY_FILE="$INPUTS/public.pem" \
  MELLOA_SETUP_TELEGRAM_BOT_TOKEN='123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
  MELLOA_SETUP_TELEGRAM_OWNER_ID=5678 \
  MELLOA_SETUP_CAPABLE_ROUTE_KIND=openai \
  MELLOA_SETUP_CAPABLE_MODEL_ID=capable-test-model \
  MELLOA_SETUP_CAPABLE_TOKEN=capable_first_install_secret \
  MELLOA_SETUP_CAPABLE_ESTIMATED_MAX_COST_GBP=0.05 \
  MELLOA_SETUP_CAPABLE_INPUT_COST_GBP_PER_MILLION_TOKENS=1.25 \
  MELLOA_SETUP_CAPABLE_OUTPUT_COST_GBP_PER_MILLION_TOKENS=10 \
  MELLOA_SETUP_ECONOMY_ROUTE_KIND=ollama \
    "$ROOT/infra/server/first-install.sh" \
      --source "$ROOT" \
      --root "$BAD_LOCAL_TARGET" \
      --skip-activation \
      </dev/null \
      >"$BAD_LOCAL_LOG" 2>&1; then
  echo "First-install setup accepted an unproven local conversation route preset" >&2
  exit 1
fi
grep --fixed-strings --quiet \
  "economy model route preset must be openai, or external for a hosted OpenAI-compatible provider/router with reviewed URL, model, API style, token, and GBP prices" \
  "$BAD_LOCAL_LOG"
if grep --fixed-strings --quiet "MELLOA_SETUP_RESTIC_PASSWORD is required" "$BAD_LOCAL_LOG"; then
  echo "First-install setup continued after an unproven local conversation route preset" >&2
  exit 1
fi

echo "Guided first-owner setup generation and redaction checks passed."
