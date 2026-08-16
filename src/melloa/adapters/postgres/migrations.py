"""Immutable SQL migration discovery, verification, and application."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.errors import UndefinedTable

_MIGRATION_NAME = re.compile(r"^[0-9]{4}_[a-z0-9_]+\.sql$")
_ADVISORY_LOCK_ID = 4_601_083_133_221


class MigrationIntegrityError(RuntimeError):
    """A migration differs from the committed immutable manifest."""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    digest: str


@dataclass(frozen=True)
class MigrationStatus:
    applied: tuple[str, ...]
    pending: tuple[str, ...]


def file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def discover_migrations(directory: Path, manifest_path: Path) -> tuple[Migration, ...]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("migrations")
    if not isinstance(expected, dict):
        raise MigrationIntegrityError("migration manifest must contain a migrations object")

    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        if _MIGRATION_NAME.fullmatch(path.name) is None:
            raise MigrationIntegrityError(f"invalid migration filename: {path.name}")
        digest = file_digest(path)
        if expected.get(path.name) != digest:
            raise MigrationIntegrityError(f"migration digest mismatch: {path.name}")
        migrations.append(Migration(path.stem, path, digest))

    names = {migration.path.name for migration in migrations}
    extra_manifest_entries = set(expected) - names
    if extra_manifest_entries:
        extras = ", ".join(sorted(extra_manifest_entries))
        raise MigrationIntegrityError(f"manifest references missing migrations: {extras}")
    return tuple(migrations)


def _applied_migrations(connection: psycopg.Connection[tuple[Any, ...]]) -> dict[str, str]:
    try:
        rows = connection.execute(
            "SELECT version, sha256 FROM melloa.schema_migrations ORDER BY version"
        ).fetchall()
    except UndefinedTable:
        connection.rollback()
        return {}
    return {str(version): str(digest) for version, digest in rows}


def migration_status(
    connection: psycopg.Connection[tuple[Any, ...]], migrations: tuple[Migration, ...]
) -> MigrationStatus:
    applied = _applied_migrations(connection)
    expected = {migration.version: migration.digest for migration in migrations}
    for version, digest in applied.items():
        if version not in expected:
            raise MigrationIntegrityError(f"database contains unknown migration: {version}")
        if expected[version] != digest:
            raise MigrationIntegrityError(f"database migration digest drift: {version}")
    pending = tuple(
        migration.version for migration in migrations if migration.version not in applied
    )
    return MigrationStatus(applied=tuple(applied), pending=pending)


def apply_migrations(
    connection: psycopg.Connection[tuple[Any, ...]], migrations: tuple[Migration, ...]
) -> MigrationStatus:
    lock_query = sql.SQL("SELECT pg_advisory_lock({})").format(sql.Literal(_ADVISORY_LOCK_ID))
    unlock_query = sql.SQL("SELECT pg_advisory_unlock({})").format(sql.Literal(_ADVISORY_LOCK_ID))
    connection.execute(lock_query)
    try:
        status = migration_status(connection, migrations)
        by_version = {migration.version: migration for migration in migrations}
        for version in status.pending:
            migration = by_version[version]
            with connection.transaction():
                connection.execute(migration.path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO melloa.schema_migrations (version, sha256) VALUES (%s, %s)",
                    (migration.version, migration.digest),
                )
        return migration_status(connection, migrations)
    finally:
        connection.execute(unlock_query)
