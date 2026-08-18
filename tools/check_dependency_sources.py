#!/usr/bin/env python3
"""Reject dependency lock URLs outside reviewed public registries."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

try:
    from tools.dependency_source_policy import (
        approved_python_source_kind,
        is_approved_https_url,
        lowercase_sha256_content,
        supported_sri_hashes,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from dependency_source_policy import (
        approved_python_source_kind,
        is_approved_https_url,
        lowercase_sha256_content,
        supported_sri_hashes,
    )

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_HOSTS = {
    "uv.lock": frozenset({"files.pythonhosted.org", "pypi.org"}),
    "apps/web/package-lock.json": frozenset({"registry.npmjs.org"}),
}
_PYTHON_NAME_PATTERN = re.compile(r"[-_.]+")


def _python_name(name: str) -> str:
    return _PYTHON_NAME_PATTERN.sub("-", name).lower()


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


def is_approved_source_url(value: str, allowed_hosts: frozenset[str]) -> bool:
    """Accept only credential-free canonical HTTPS registry URLs."""

    return is_approved_https_url(value, allowed_hosts)


def _is_valid_uv_artifact(value: Any, allowed_hosts: frozenset[str]) -> bool:
    if not isinstance(value, dict):
        return False
    url = value.get("url")
    digest = value.get("hash")
    return (
        isinstance(url, str)
        and is_approved_source_url(url, allowed_hosts)
        and lowercase_sha256_content(digest) is not None
    )


def _has_invalid_uv_package_sources(
    document: dict[str, Any],
    allowed_hosts: frozenset[str],
) -> bool:
    if document.get("version") != 1 or document.get("revision") != 3:
        return True
    packages = document.get("package")
    if not isinstance(packages, list) or not packages:
        return True
    editable_roots = 0
    package_names: set[str] = set()
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            return True
        normalized_name = _python_name(package["name"])
        if normalized_name in package_names:
            return True
        package_names.add(normalized_name)
        source_kind = approved_python_source_kind(package.get("source"), allowed_hosts)
        if source_kind is None:
            return True
        if source_kind == "editable":
            if normalized_name != "melloa":
                return True
            editable_roots += 1
            continue
        if normalized_name == "melloa":
            return True
        artifacts: list[Any] = []
        if "sdist" in package:
            artifacts.append(package["sdist"])
        wheels = package.get("wheels", [])
        if not isinstance(wheels, list):
            return True
        artifacts.extend(wheels)
        if not artifacts:
            return True
        if any(not _is_valid_uv_artifact(artifact, allowed_hosts) for artifact in artifacts):
            return True
    return editable_roots != 1


def _has_invalid_npm_package_sources(
    document: dict[str, Any],
    allowed_hosts: frozenset[str],
) -> bool:
    if document.get("lockfileVersion") != 3:
        return True
    packages = document.get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        return True
    for package_path, package in packages.items():
        if not isinstance(package_path, str) or not isinstance(package, dict):
            return True
        if not package_path:
            continue
        resolved = package.get("resolved")
        if package.get("link") or not isinstance(resolved, str):
            return True
        if not is_approved_source_url(resolved, allowed_hosts):
            return True
        if supported_sri_hashes(package.get("integrity")) is None:
            return True
    return False


def has_unapproved_source(relative_path: str, allowed_hosts: frozenset[str]) -> bool:
    lock_path = ROOT / relative_path
    if not lock_path.is_file():
        return True
    try:
        if lock_path.name == "uv.lock":
            document = tomllib.loads(lock_path.read_text(encoding="utf-8"))
            if _has_invalid_uv_package_sources(document, allowed_hosts):
                return True
        elif lock_path.name == "package-lock.json":
            document = json.loads(lock_path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                return True
            if _has_invalid_npm_package_sources(document, allowed_hosts):
                return True
        urls = dependency_urls(lock_path)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, OSError, UnicodeError):
        return True
    if not urls:
        return True
    return any(not is_approved_source_url(url, allowed_hosts) for url in urls)


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
