from __future__ import annotations

import json

import pytest

from melloa.adapters.postgres.migrations import (
    MigrationIntegrityError,
    discover_migrations,
    file_digest,
)


def test_migration_manifest_detects_tampering(tmp_path) -> None:
    migration_directory = tmp_path / "migrations"
    migration_directory.mkdir()
    migration = migration_directory / "0001_example.sql"
    migration.write_text("SELECT 1;\n", encoding="utf-8")
    manifest = migration_directory / "manifest.json"
    manifest.write_text(
        json.dumps({"migrations": {migration.name: file_digest(migration)}}),
        encoding="utf-8",
    )
    assert discover_migrations(migration_directory, manifest)[0].version == "0001_example"

    migration.write_text("SELECT 2;\n", encoding="utf-8")
    with pytest.raises(MigrationIntegrityError, match="digest mismatch"):
        discover_migrations(migration_directory, manifest)
