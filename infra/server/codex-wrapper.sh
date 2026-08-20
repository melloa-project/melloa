#!/usr/bin/env bash
set -euo pipefail

readonly CODEX_EXECUTABLE=/usr/local/bin/codex

if [[ ! -x "$CODEX_EXECUTABLE" ]]; then
  echo "Codex executable is unavailable" >&2
  exit 2
fi

exec "$CODEX_EXECUTABLE" "$@"
