from __future__ import annotations

import json
from pathlib import Path

from tools.check_dependency_sources import dependency_urls


def test_npm_dependency_urls_ignore_funding_metadata(tmp_path: Path) -> None:
    lock_path = tmp_path / "package-lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "packages": {
                    "node_modules/example": {
                        "resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
                        "funding": "https://github.com/sponsors/example",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert dependency_urls(lock_path) == (
        "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
    )


def test_npm_dependency_urls_include_unapproved_artifact_source(tmp_path: Path) -> None:
    lock_path = tmp_path / "package-lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "packages": {
                    "node_modules/example": {
                        "resolved": "https://packages.example.invalid/example.tgz",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert dependency_urls(lock_path) == (
        "https://packages.example.invalid/example.tgz",
    )


def test_uv_dependency_urls_include_registry_artifact_and_git_sources(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(
        """
version = 1

[[package]]
name = "registry-package"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/package.tar.gz" }

[[package]]
name = "git-package"
version = "1.0.0"
source = { git = "https://git.example.invalid/repository" }
""".strip(),
        encoding="utf-8",
    )

    assert dependency_urls(lock_path) == (
        "https://pypi.org/simple",
        "https://files.pythonhosted.org/package.tar.gz",
        "https://git.example.invalid/repository",
    )
