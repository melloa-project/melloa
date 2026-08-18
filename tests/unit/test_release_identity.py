from __future__ import annotations

import json
import tomllib
from dataclasses import asdict
from pathlib import Path

import melloa
from melloa.release import CURRENT_RELEASE

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_canonical_release_identity_is_exact() -> None:
    assert asdict(CURRENT_RELEASE) == {
        "package_version": "0.2.0",
        "release_display": "v0.2.0 preview",
        "stage": "preview",
        "milestone": "M1",
        "architecture_baseline": "v0.2",
    }
    assert CURRENT_RELEASE.runtime_identifier == "melloa-core/0.2.0-preview"
    assert CURRENT_RELEASE.public_metadata() == {
        "version": "0.2.0",
        "display": "v0.2.0 preview",
        "stage": "preview",
        "milestone": "M1",
        "architecture_baseline": "v0.2",
    }
    assert melloa.__version__ == CURRENT_RELEASE.package_version


def test_repository_package_metadata_matches_canonical_release() -> None:
    with (_PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)
    with (_PROJECT_ROOT / "uv.lock").open("rb") as stream:
        uv_lock = tomllib.load(stream)
    web_package = json.loads(
        (_PROJECT_ROOT / "apps/web/package.json").read_text(encoding="utf-8")
    )
    web_lock = json.loads(
        (_PROJECT_ROOT / "apps/web/package-lock.json").read_text(encoding="utf-8")
    )
    uv_project = next(
        package
        for package in uv_lock["package"]
        if package["name"] == "melloa" and package.get("source") == {"editable": "."}
    )

    assert {
        "pyproject.toml": pyproject["project"]["version"],
        "uv.lock": uv_project["version"],
        "apps/web/package.json": web_package["version"],
        "apps/web/package-lock.json": web_lock["version"],
        "apps/web/package-lock.json root package": web_lock["packages"][""]["version"],
    } == {
        metadata_path: CURRENT_RELEASE.package_version
        for metadata_path in (
            "pyproject.toml",
            "uv.lock",
            "apps/web/package.json",
            "apps/web/package-lock.json",
            "apps/web/package-lock.json root package",
        )
    }
