#!/usr/bin/env bash
set -euo pipefail

readonly MELLOA_TOOLCHAIN_BIN=/opt/melloa/toolchain/bin
readonly CODEX_EXECUTABLE=/opt/melloa/toolchain/codex/bin/codex

export PATH="$MELLOA_TOOLCHAIN_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

if [[ ! -x "$CODEX_EXECUTABLE" ]]; then
  echo "Melloa private Codex executable is unavailable" >&2
  exit 2
fi

exec "$CODEX_EXECUTABLE" "$@"
