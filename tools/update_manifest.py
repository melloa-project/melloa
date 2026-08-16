#!/usr/bin/env python3
"""Generate or verify the repository release-file SHA-256 manifest."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "MANIFEST.sha256"
IGNORED_DIRECTORIES = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "htmlcov",
    "node_modules",
    "site",
}
IGNORED_FILES = {".coverage"}


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        path != OUTPUT
        and path.name not in IGNORED_FILES
        and not any(part in IGNORED_DIRECTORIES for part in relative.parts)
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rendered_manifest() -> str:
    files = sorted(path for path in ROOT.rglob("*") if path.is_file() and included(path))
    return "".join(f"{digest(path)}  ./{path.relative_to(ROOT).as_posix()}\n" for path in files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = rendered_manifest()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            print("MANIFEST.sha256 is stale")
            return 1
    else:
        OUTPUT.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
