#!/usr/bin/env python3
"""Reject dependency lock URLs outside reviewed public registries."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_HOSTS = {
    "uv.lock": frozenset({"files.pythonhosted.org", "pypi.org"}),
    "apps/web/package-lock.json": frozenset({"registry.npmjs.org"}),
}


def dependency_urls(lock_path: Path) -> tuple[str, ...]:
    """Return only artifact and registry URLs, excluding metadata links."""

    if lock_path.name == "package-lock.json":
        document = json.loads(lock_path.read_text(encoding="utf-8"))
        return tuple(_values_for_keys(document, frozenset({"resolved"})))
    if lock_path.name == "uv.lock":
        document = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        return tuple(_values_for_keys(document, frozenset({"git", "registry", "url"})))
    return ()


def _values_for_keys(value: Any, keys: frozenset[str]) -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in keys and isinstance(nested, str):
                matches.append(nested)
            else:
                matches.extend(_values_for_keys(nested, keys))
    elif isinstance(value, list):
        for nested in value:
            matches.extend(_values_for_keys(nested, keys))
    return matches


def has_unapproved_source(relative_path: str, allowed_hosts: frozenset[str]) -> bool:
    lock_path = ROOT / relative_path
    if not lock_path.is_file():
        return True
    try:
        urls = dependency_urls(lock_path)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, OSError):
        return True
    if not urls:
        return True
    return any(
        parsed.scheme != "https" or parsed.hostname not in allowed_hosts
        for parsed in (urlsplit(url) for url in urls)
    )


def main() -> int:
    failures = [
        relative_path
        for relative_path, allowed_hosts in ALLOWED_HOSTS.items()
        if has_unapproved_source(relative_path, allowed_hosts)
    ]
    for relative_path in failures:
        print(f"{relative_path}: dependency source is outside the public registry allowlist")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
