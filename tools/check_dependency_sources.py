#!/usr/bin/env python3
"""Reject dependency lock URLs outside reviewed public registries."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
URL_PATTERN = re.compile(r"https?://[^\s\"']+")
ALLOWED_HOSTS = {
    "uv.lock": frozenset({"files.pythonhosted.org", "pypi.org"}),
    "apps/web/package-lock.json": frozenset({"registry.npmjs.org"}),
}


def has_unapproved_source(relative_path: str, allowed_hosts: frozenset[str]) -> bool:
    lock_path = ROOT / relative_path
    if not lock_path.is_file():
        return True
    urls = URL_PATTERN.findall(lock_path.read_text(encoding="utf-8"))
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
