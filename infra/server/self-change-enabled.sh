#!/usr/bin/env bash
set -euo pipefail

readonly ENABLED="${MELLOA_SELF_CHANGE_ENABLED:-}"

if [[ "$ENABLED" == true ]]; then
  exit 0
fi

if [[ "$ENABLED" == false ]]; then
  echo "Optional Melloa self-change workers are disabled by /etc/melloa/self-change.env." >&2
  exit 1
fi

echo "MELLOA_SELF_CHANGE_ENABLED must be true or false in /etc/melloa/self-change.env." >&2
exit 255
