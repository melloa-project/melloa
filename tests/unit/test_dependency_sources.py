from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from tools import check_dependency_sources
from tools.check_dependency_sources import dependency_urls, is_approved_source_url

_UV_SHA256 = "a" * 64


def _sri(value: bytes = b"s") -> str:
    return "sha512-" + base64.b64encode(value * 64).decode("ascii")


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


@pytest.mark.parametrize(
    "value",
    [
        "http://registry.npmjs.org/example.tgz",
        "https://user:secret@registry.npmjs.org/example.tgz",
        "https://registry.npmjs.org:443/example.tgz",
        "https://registry.npmjs.org/example.tgz?download=1",
        "https://registry.npmjs.org/example.tgz#checksum",
        "https://registry.example/example.tgz",
        "https://registry.npmjs.org:not-a-port/example.tgz",
        "HTTPS://registry.npmjs.org/example.tgz",
        "https://REGISTRY.NPMJS.ORG/example.tgz",
        "https://[registry.npmjs.org/example.tgz",
        "\x00https://registry.npmjs.org/example.tgz",
        "\nhttps://registry.npmjs.org/example.tgz",
        "https://registry.npmjs.org/example.tgz\n",
        "https://registry.npmjs.org/example\tname.tgz",
        "https://registry.npmjs.org/example name.tgz",
    ],
)
def test_source_url_policy_rejects_noncanonical_or_credentialed_urls(value: str) -> None:
    assert not is_approved_source_url(value, frozenset({"registry.npmjs.org"}))


def test_source_url_policy_accepts_exact_reviewed_registry_url() -> None:
    assert is_approved_source_url(
        "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
        frozenset({"registry.npmjs.org"}),
    )


@pytest.mark.parametrize(
    ("relative_path", "document", "allowed_hosts"),
    [
        (
            "apps/web/package-lock.json",
            json.dumps(
                {
                    "lockfileVersion": 3,
                    "packages": {
                        "": {},
                        "node_modules/example": {
                            "resolved": (
                                "https://user:secret@registry.npmjs.org/example.tgz"
                            ),
                            "integrity": _sri(),
                        }
                    }
                }
            ),
            frozenset({"registry.npmjs.org"}),
        ),
        (
            "uv.lock",
            f"""
version = 1
revision = 3
[[package]]
name = "example"
version = "1.0.0"
source = {{ registry = "https://user:secret@pypi.org/simple" }}
sdist = {{ url = "https://files.pythonhosted.org/e", hash = "sha256:{_UV_SHA256}" }}
""".strip(),
            frozenset({"files.pythonhosted.org", "pypi.org"}),
        ),
    ],
)
def test_dependency_source_gate_rejects_credentialed_lock_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    document: str,
    allowed_hosts: frozenset[str],
) -> None:
    lock_path = tmp_path / relative_path
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(document, encoding="utf-8")
    monkeypatch.setattr(check_dependency_sources, "ROOT", tmp_path)

    assert check_dependency_sources.has_unapproved_source(relative_path, allowed_hosts)


def test_dependency_source_gate_fails_closed_on_non_utf8_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "uv.lock"
    lock_path.write_bytes(b"\xff")
    monkeypatch.setattr(check_dependency_sources, "ROOT", tmp_path)

    assert check_dependency_sources.has_unapproved_source(
        "uv.lock",
        frozenset({"files.pythonhosted.org", "pypi.org"}),
    )


def test_dependency_source_gate_accepts_exact_uv_package_source_shapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "uv.lock").write_text(
        f"""
version = 1
revision = 3

[[package]]
name = "melloa"
version = "0.0.1"
source = {{ editable = "." }}

[[package]]
name = "example"
version = "1.0.0"
source = {{ registry = "https://pypi.org/simple" }}
sdist = {{ url = "https://files.pythonhosted.org/e", hash = "sha256:{_UV_SHA256}" }}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_dependency_sources, "ROOT", tmp_path)

    assert not check_dependency_sources.has_unapproved_source(
        "uv.lock",
        frozenset({"files.pythonhosted.org", "pypi.org"}),
    )


def test_dependency_source_gate_rejects_second_normalized_melloa_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "uv.lock").write_text(
        f"""
version = 1
revision = 3

[[package]]
name = "melloa"
version = "0.0.1"
source = {{ editable = "." }}

[[package]]
name = "Melloa"
version = "9.9.9"
source = {{ registry = "https://pypi.org/simple" }}
sdist = {{ url = "https://files.pythonhosted.org/e", hash = "sha256:{_UV_SHA256}" }}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_dependency_sources, "ROOT", tmp_path)

    assert check_dependency_sources.has_unapproved_source(
        "uv.lock",
        frozenset({"files.pythonhosted.org", "pypi.org"}),
    )


@pytest.mark.parametrize(
    "artifact",
    [
        '{ url = "https://files.pythonhosted.org/example.tar.gz" }',
        (
            '{ url = "https://files.pythonhosted.org/example.tar.gz", '
            'hash = "sha256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" }'
        ),
        (
            '{ url = "https://files.pythonhosted.org/example.tar.gz", '
            'hash = "sha512:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }'
        ),
        (
            '{ url = "file:///tmp/example.tar.gz", '
            'hash = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }'
        ),
    ],
)
def test_dependency_source_gate_rejects_uv_packages_without_approved_sha256_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    (tmp_path / "uv.lock").write_text(
        f"""
version = 1
revision = 3

[[package]]
name = "melloa"
version = "0.0.1"
source = {{ editable = "." }}

[[package]]
name = "example"
version = "1.0.0"
source = {{ registry = "https://pypi.org/simple" }}
sdist = {artifact}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_dependency_sources, "ROOT", tmp_path)

    assert check_dependency_sources.has_unapproved_source(
        "uv.lock",
        frozenset({"files.pythonhosted.org", "pypi.org"}),
    )


@pytest.mark.parametrize(
    "source",
    [
        '{ directory = "../attacker-controlled-package" }',
        '{ path = "../attacker-controlled-package" }',
        '{ git = "https://pypi.org/attacker/repository" }',
        '{ url = "https://files.pythonhosted.org/attacker.whl" }',
        (
            '{ registry = "https://pypi.org/simple", '
            'directory = "../attacker-controlled-package" }'
        ),
        "{ registry = 7 }",
    ],
)
def test_dependency_source_gate_rejects_unsupported_uv_package_source_shapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    (tmp_path / "uv.lock").write_text(
        f"""
version = 1
revision = 3

[[package]]
name = "melloa"
version = "0.0.1"
source = {{ editable = "." }}

[[package]]
name = "example"
version = "1.0.0"
source = {source}
sdist = {{ url = "https://files.pythonhosted.org/e", hash = "sha256:{_UV_SHA256}" }}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_dependency_sources, "ROOT", tmp_path)

    assert check_dependency_sources.has_unapproved_source(
        "uv.lock",
        frozenset({"files.pythonhosted.org", "pypi.org"}),
    )


def test_dependency_source_gate_rejects_local_npm_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "apps/web/package-lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {},
                    "node_modules/local-package": {
                        "link": True,
                        "resolved": "https://registry.npmjs.org/local-package.tgz",
                        "integrity": _sri(),
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_dependency_sources, "ROOT", tmp_path)

    assert check_dependency_sources.has_unapproved_source(
        "apps/web/package-lock.json",
        frozenset({"registry.npmjs.org"}),
    )


def test_dependency_source_gate_accepts_exact_npm_package_sources_and_integrity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / "apps/web/package-lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {},
                    "node_modules/example": {
                        "resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
                        "integrity": _sri(),
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_dependency_sources, "ROOT", tmp_path)

    assert not check_dependency_sources.has_unapproved_source(
        "apps/web/package-lock.json",
        frozenset({"registry.npmjs.org"}),
    )


@pytest.mark.parametrize(
    "package",
    [
        {
            "resolved": "file:../local-package",
            "integrity": _sri(),
        },
        {
            "resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
        },
        {
            "resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
            "integrity": "sha512-not-base64",
        },
        {
            "resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
            "integrity": "md5-AAAAAAAAAAAAAAAAAAAAAA==",
        },
        {
            "resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz",
            "integrity": _sri() + " md5-AAAAAAAAAAAAAAAAAAAAAA==",
        },
    ],
)
def test_dependency_source_gate_rejects_npm_local_or_malformed_integrity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    package: dict[str, str],
) -> None:
    lock_path = tmp_path / "apps/web/package-lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {},
                    "node_modules/example": package,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_dependency_sources, "ROOT", tmp_path)

    assert check_dependency_sources.has_unapproved_source(
        "apps/web/package-lock.json",
        frozenset({"registry.npmjs.org"}),
    )
