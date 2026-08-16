#!/usr/bin/env python3
"""Regenerate the immutable migration digest manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from melloa.adapters.postgres.migrations import file_digest

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
MANIFEST = MIGRATIONS / "manifest.json"


def rendered_manifest() -> str:
    payload = {
        "manifest_version": "1.0.0",
        "migrations": {
            path.name: file_digest(path)
            for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_manifest()
    if args.check:
        if not MANIFEST.exists() or MANIFEST.read_text(encoding="utf-8") != expected:
            print("Migration manifest is stale")
            return 1
    else:
        MANIFEST.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
