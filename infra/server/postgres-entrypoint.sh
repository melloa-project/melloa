#!/usr/bin/env bash
set -euo pipefail

readonly INIT_SECRET_DIR=/run/melloa-postgres-init

if [[ "${1:-}" == postgres && ! -s "${PGDATA:?}/PG_VERSION" ]]; then
  install -d -o postgres -g postgres -m 0700 "$INIT_SECRET_DIR"
  install -o postgres -g postgres -m 0400 \
    /run/secrets/postgres_app_password \
    "$INIT_SECRET_DIR/postgres_app_password"
  install -o postgres -g postgres -m 0400 \
    /run/secrets/postgres_migration_password \
    "$INIT_SECRET_DIR/postgres_migration_password"
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
