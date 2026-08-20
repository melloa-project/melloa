#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly WORKDIR="$(mktemp -d /tmp/melloa-configuration-test.XXXXXX)"
readonly INPUTS="$WORKDIR/inputs"
readonly TARGET="$WORKDIR/target"
readonly LOCAL_TARGET="$WORKDIR/local-target"
readonly DUPLICATE_TARGET="$WORKDIR/duplicate-target"
readonly DISABLED_TARGET="$WORKDIR/disabled-target"
readonly TEST_UID="$(id -u)"
readonly TEST_GID="$(id -g)"

cleanup() {
  if [[ "$WORKDIR" == /tmp/melloa-configuration-test.* && -d "$WORKDIR" ]]; then
    rm -rf -- "$WORKDIR"
  fi
}
trap cleanup EXIT HUP INT TERM

private_input() {
  local name="$1"
  local value="$2"
  install -m 0600 /dev/null "$INPUTS/$name"
  printf '%s\n' "$value" >"$INPUTS/$name"
}

install -d -m 0700 "$INPUTS"
"$ROOT/infra/server/install.sh" --source "$ROOT" --root "$TARGET" >/dev/null

private_input telegram-token '123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456'
private_input restic-password 'restic_configuration_test_password_123456789'
private_input github-token 'github_pat_configuration_test_123456789'
private_input codex-api-key 'sk-configuration-test-1234567890'
private_input capable-token 'capable_configuration_test_token'
private_input economy-token 'economy_configuration_test_token'
private_input capable-model.json '{
  "display_name":"Capable test",
  "provider_id":"provider.capable-test",
  "model_id":"capable-test",
  "base_url":"https://capable.example/v1",
  "processing_location":"approved_provider",
  "allowed_sensitivities":["personal"],
  "authorization_token_file":"/run/melloa/model-credentials/capable-token"
}'
private_input economy-model.json '{
  "display_name":"Economy test",
  "provider_id":"provider.economy-test",
  "model_id":"economy-test",
  "base_url":"https://economy.example/v1",
  "processing_location":"approved_provider",
  "allowed_sensitivities":["personal"],
  "authorization_token_file":"/run/melloa/model-credentials/economy-token"
}'
private_input duplicate-capable-model.json '{
  "display_name":"Duplicate capable test",
  "provider_id":"provider.duplicate-capable-test",
  "model_id":"duplicate-test",
  "base_url":"https://duplicate.example/v1",
  "processing_location":"approved_provider",
  "allowed_sensitivities":["personal"],
  "authorization_token_file":"/run/melloa/model-credentials/capable-token"
}'
private_input duplicate-economy-model.json '{
  "display_name":"Duplicate economy test",
  "provider_id":"provider.duplicate-economy-test",
  "model_id":"duplicate-test",
  "base_url":"https://duplicate.example/v1",
  "processing_location":"approved_provider",
  "allowed_sensitivities":["personal"],
  "authorization_token_file":"/run/melloa/model-credentials/economy-token"
}'
private_input local-capable-model.json '{
  "display_name":"Local capable test",
  "provider_id":"provider.local-capable-test",
  "model_id":"local-capable-test",
  "base_url":"http://127.0.0.1:11434/v1",
  "processing_location":"device",
  "allowed_sensitivities":["personal"]
}'
private_input local-economy-model.json '{
  "display_name":"Local economy test",
  "provider_id":"provider.local-economy-test",
  "model_id":"local-economy-test",
  "base_url":"http://127.0.0.1:1234/v1",
  "processing_location":"device",
  "allowed_sensitivities":["personal"]
}'
printf '{"contract_version":"1.0.0"}\n' >"$INPUTS/status.json"
printf '%s\n' '-----BEGIN PUBLIC KEY-----' 'configuration-test' \
  '-----END PUBLIC KEY-----' >"$INPUTS/public.pem"
printf '%s\n' '-----BEGIN CERTIFICATE-----' 'configuration-ca-test' \
  '-----END CERTIFICATE-----' >"$INPUTS/build-ca.pem"

"$ROOT/infra/server/configure.sh" \
  --source "$ROOT" \
  --root "$TARGET" \
  --backup-repository /mnt/melloa-off-device-backup \
  --guardian-status-file "$INPUTS/status.json" \
  --guardian-public-key-file "$INPUTS/public.pem" \
  --telegram-owner-id 5678 \
  --telegram-bot-token-file "$INPUTS/telegram-token" \
  --capable-model-config-file "$INPUTS/capable-model.json" \
  --economy-model-config-file "$INPUTS/economy-model.json" \
  --model-credential "capable-token=$INPUTS/capable-token" \
  --model-credential "economy-token=$INPUTS/economy-token" \
  --restic-password-file "$INPUTS/restic-password" \
  --github-token-file "$INPUTS/github-token" \
  --build-ca-file "$INPUTS/build-ca.pem" \
  --codex-api-key-file "$INPUTS/codex-api-key" \
  >"$WORKDIR/configure.log"

readonly PRIVATE="$TARGET/etc/melloa/private"
[[ "$(stat --format='%a:%u:%g' "$PRIVATE")" == "700:$TEST_UID:$TEST_GID" ]]
[[ "$(stat --format='%a:%u:%g' "$PRIVATE/owner-credential")" == \
  "600:$TEST_UID:$TEST_GID" ]]
[[ "$(stat --format='%a:%u:%g' "$PRIVATE/database-change-planner-dsn")" == \
  "600:$TEST_UID:$TEST_GID" ]]
[[ "$(stat --format='%a:%u:%g' "$PRIVATE/model-credentials")" == \
  "700:$TEST_UID:$TEST_GID" ]]
[[ "$(stat --format='%a:%u:%g' "$PRIVATE/model-credentials/capable-token")" == \
  "600:$TEST_UID:$TEST_GID" ]]
[[ "$(jq -r .owner_user_id "$PRIVATE/telegram-owner.json")" == 5678 ]]
[[ "$(jq -r .owner_chat_id "$PRIVATE/telegram-owner.json")" == 5678 ]]
grep --fixed-strings --quiet \
  'MELLOA_BACKUP_REPOSITORY_DIR=/mnt/melloa-off-device-backup' \
  "$TARGET/etc/melloa/server.env"
grep --fixed-strings --quiet 'MELLOA_BUILD_CA_FILE=/etc/melloa/build-ca.pem' \
  "$TARGET/etc/melloa/server.env"
[[ "$(stat --format='%a:%u:%g' "$TARGET/etc/melloa/build-ca.pem")" == \
  "644:$TEST_UID:$TEST_GID" ]]
cmp --silent "$INPUTS/build-ca.pem" "$TARGET/etc/melloa/build-ca.pem"
grep --fixed-strings --quiet 'MELLOA_SELF_CHANGE_ENABLED=true' \
  "$TARGET/etc/melloa/self-change.env"
grep --fixed-strings --quiet 'MELLOA_CODEX_USE_API_KEY=true' \
  "$TARGET/etc/melloa/self-change.env"
grep --fixed-strings --quiet \
  'https://x-access-token:github_pat_configuration_test_123456789@github.com' \
  "$PRIVATE/git-credentials"
[[ "$(stat --format='%a:%u:%g' "$TARGET/var/lib/melloa/guardian-handoff/status.json")" == \
  "400:$TEST_UID:$TEST_GID" ]]
[[ "$(jq -r .contract_version "$TARGET/etc/melloa/configuration.json")" == 1.0.0 ]]

if "$ROOT/infra/server/configure.sh" \
  --source "$ROOT" \
  --root "$TARGET" \
  --backup-repository /mnt/melloa-off-device-backup \
  --guardian-status-file "$INPUTS/status.json" \
  --guardian-public-key-file "$INPUTS/public.pem" \
  --telegram-owner-id 5678 \
  --telegram-bot-token-file "$INPUTS/telegram-token" \
  --capable-model-config-file "$INPUTS/capable-model.json" \
  --economy-model-config-file "$INPUTS/economy-model.json" \
  --model-credential "capable-token=$INPUTS/capable-token" \
  --model-credential "economy-token=$INPUTS/economy-token" \
  --restic-password-file "$INPUTS/restic-password" \
  --github-token-file "$INPUTS/github-token" \
  --codex-api-key-file "$INPUTS/codex-api-key" \
  >/dev/null 2>&1; then
  echo "Configurator overwrote an existing private deployment" >&2
  exit 1
fi

for secret in \
  '123456789:abcdefghijklmnopqrstuvwxyz_ABCD123456' \
  'restic_configuration_test_password_123456789' \
  'github_pat_configuration_test_123456789' \
  'sk-configuration-test-1234567890'; do
  if grep --fixed-strings --quiet "$secret" "$WORKDIR/configure.log"; then
    echo "Configurator exposed a private input" >&2
    exit 1
  fi
done

"$ROOT/infra/server/install.sh" --source "$ROOT" --root "$DUPLICATE_TARGET" >/dev/null
if "$ROOT/infra/server/configure.sh" \
  --source "$ROOT" \
  --root "$DUPLICATE_TARGET" \
  --backup-repository /mnt/melloa-off-device-backup \
  --guardian-status-file "$INPUTS/status.json" \
  --guardian-public-key-file "$INPUTS/public.pem" \
  --telegram-owner-id 5678 \
  --telegram-bot-token-file "$INPUTS/telegram-token" \
  --capable-model-config-file "$INPUTS/duplicate-capable-model.json" \
  --economy-model-config-file "$INPUTS/duplicate-economy-model.json" \
  --model-credential "capable-token=$INPUTS/capable-token" \
  --model-credential "economy-token=$INPUTS/economy-token" \
  --restic-password-file "$INPUTS/restic-password" \
  --self-change-disabled \
  >"$WORKDIR/configure-duplicate.log" 2>&1; then
  echo "Configurator accepted duplicate capable/economy model targets" >&2
  exit 1
fi
grep --fixed-strings --quiet \
  "capable and economy model targets must differ" \
  "$WORKDIR/configure-duplicate.log"
if grep --fixed-strings --quiet 'restic_configuration_test_password_123456789' \
  "$WORKDIR/configure-duplicate.log"; then
  echo "Configurator exposed a private input while reporting duplicate model targets" >&2
  exit 1
fi

"$ROOT/infra/server/install.sh" --source "$ROOT" --root "$LOCAL_TARGET" >/dev/null
"$ROOT/infra/server/configure.sh" \
  --source "$ROOT" \
  --root "$LOCAL_TARGET" \
  --backup-repository /mnt/melloa-off-device-backup \
  --guardian-status-file "$INPUTS/status.json" \
  --guardian-public-key-file "$INPUTS/public.pem" \
  --telegram-owner-id 5678 \
  --telegram-bot-token-file "$INPUTS/telegram-token" \
  --capable-model-config-file "$INPUTS/local-capable-model.json" \
  --economy-model-config-file "$INPUTS/local-economy-model.json" \
  --restic-password-file "$INPUTS/restic-password" \
  --github-token-file "$INPUTS/github-token" \
  --codex-local-provider ollama \
  >/dev/null
[[ "$(<"$LOCAL_TARGET/etc/melloa/self-change.env")" == \
  $'MELLOA_SELF_CHANGE_ENABLED=true\nMELLOA_CODEX_USE_API_KEY=false\nMELLOA_CODEX_MODEL=\nMELLOA_CODEX_LOCAL_PROVIDER=ollama' ]]
[[ "$(jq -r .codex_mode "$LOCAL_TARGET/etc/melloa/configuration.json")" == ollama ]]
[[ -z "$(find "$LOCAL_TARGET/etc/melloa/private/model-credentials" -mindepth 1 -print -quit)" ]]

"$ROOT/infra/server/install.sh" --source "$ROOT" --root "$DISABLED_TARGET" >/dev/null
"$ROOT/infra/server/configure.sh" \
  --source "$ROOT" \
  --root "$DISABLED_TARGET" \
  --backup-repository /mnt/melloa-off-device-backup \
  --guardian-status-file "$INPUTS/status.json" \
  --guardian-public-key-file "$INPUTS/public.pem" \
  --telegram-owner-id 5678 \
  --telegram-bot-token-file "$INPUTS/telegram-token" \
  --capable-model-config-file "$INPUTS/capable-model.json" \
  --economy-model-config-file "$INPUTS/economy-model.json" \
  --model-credential "capable-token=$INPUTS/capable-token" \
  --model-credential "economy-token=$INPUTS/economy-token" \
  --restic-password-file "$INPUTS/restic-password" \
  --self-change-disabled \
  >/dev/null
[[ "$(<"$DISABLED_TARGET/etc/melloa/self-change.env")" == \
  $'MELLOA_SELF_CHANGE_ENABLED=false\nMELLOA_CODEX_USE_API_KEY=false\nMELLOA_CODEX_MODEL=\nMELLOA_CODEX_LOCAL_PROVIDER=' ]]
[[ "$(jq -r .codex_mode "$DISABLED_TARGET/etc/melloa/configuration.json")" == disabled ]]
[[ "$(wc -c <"$DISABLED_TARGET/etc/melloa/private/git-credentials")" == 1 ]]
[[ "$(wc -c <"$DISABLED_TARGET/etc/melloa/private/codex-api-key")" == 1 ]]

echo "Private first-install configuration and non-overwrite checks passed."
