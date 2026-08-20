#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly CREDENTIALS_DIR="${CREDENTIALS_DIRECTORY:-}"
readonly SELF_CHANGE_ENABLED="${MELLOA_SELF_CHANGE_ENABLED:-}"

if [[ "$CREDENTIALS_DIR" != /* || ! -d "$CREDENTIALS_DIR" || \
  "$SELF_CHANGE_ENABLED" != true ]]; then
  echo "Self-change applier service configuration rejected" >&2
  exit 2
fi

exec /opt/melloa/worker/.venv/bin/melloa \
  self-change-apply \
  --dsn-file "$CREDENTIALS_DIR/applier-dsn" \
  --repository /srv/melloa/release-source \
  --work-root /var/lib/melloa/applying-work \
  --git-executable /usr/bin/git \
  --verifier-executable /usr/local/libexec/melloa/self-change-verify \
  --verifier-python-env /opt/melloa/verifier/.venv \
  --verifier-node-modules /opt/melloa/verifier/node_modules \
  --server-environment-file /etc/melloa/server.env \
  --release-state-dir /var/lib/melloa/release-state
