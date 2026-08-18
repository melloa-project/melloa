from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from tools.generate_dependency_sbom import (
    SbomError,
    build_sbom,
    check_sbom,
    rendered_sbom,
    write_sbom,
)


def _sri(value: bytes) -> str:
    return "sha512-" + base64.b64encode(value * 64).decode("ascii")


def _npm_package(name: str, version: str, *, integrity_byte: bytes) -> dict[str, str]:
    archive_name = name.rsplit("/", maxsplit=1)[-1]
    return {
        "version": version,
        "resolved": f"https://registry.npmjs.org/{name}/-/{archive_name}-{version}.tgz",
        "integrity": _sri(integrity_byte),
    }


def _write_project_fixture(root: Path) -> None:
    a_hash = "a" * 64
    b_hash = "b" * 64
    c_hash = "c" * 64
    d_hash = "d" * 64
    e_hash = "e" * 64
    (root / "apps/web").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        """
[build-system]
requires = ["editables==0.5", "hatchling==1.32.0"]
build-backend = "hatchling.build"

[project]
name = "melloa"
version = "0.0.1"
requires-python = ">=3.13"
dependencies = ["FastAPI[standard]>=0.116,<1"]

[dependency-groups]
build = ["editables==0.5", "hatchling==1.32.0"]
dev = ["pytest>=8,<9"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        """
version = 1
revision = 3
requires-python = ">=3.13"

[[package]]
name = "editables"
version = "0.5"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/f", hash = "sha256:{f_hash}" }

[[package]]
name = "FastAPI"
version = "0.116.2"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/a", hash = "sha256:{a_hash}" }
wheels = [
  { url = "https://files.pythonhosted.org/b", hash = "sha256:{b_hash}" },
]

[[package]]
name = "melloa"
version = "0.0.1"
source = { editable = "." }
dependencies = [{ name = "FastAPI", extra = ["standard"] }]

[package.dev-dependencies]
build = [{ name = "editables" }, { name = "hatchling" }]
dev = [{ name = "pytest" }]

[package.metadata]
requires-dist = [
    { name = "FastAPI", extras = ["standard"], specifier = ">=0.116,<1" },
]

[package.metadata.requires-dev]
build = [
    { name = "editables", specifier = "==0.5" },
    { name = "hatchling", specifier = "==1.32.0" },
]
dev = [{ name = "pytest", specifier = ">=8,<9" }]

[[package]]
name = "hatchling"
version = "1.32.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "packaging" }]
sdist = { url = "https://files.pythonhosted.org/d", hash = "sha256:{d_hash}" }

[[package]]
name = "packaging"
version = "26.3"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/e", hash = "sha256:{e_hash}" }

[[package]]
name = "pytest"
version = "8.4.2"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/c", hash = "sha256:{c_hash}" }
""".strip()
        .replace("{a_hash}", a_hash)
        .replace("{b_hash}", b_hash)
        .replace("{c_hash}", c_hash)
        .replace("{d_hash}", d_hash)
        .replace("{e_hash}", e_hash)
        .replace("{f_hash}", "f" * 64)
        + "\n",
        encoding="utf-8",
    )
    package_json = {
        "name": "@melloa/owner-console",
        "version": "0.1.0",
        "dependencies": {"child": "1.0.0", "parent": "2.0.0"},
        "devDependencies": {"@scope/pkg": "1.2.3"},
    }
    (root / "apps/web/package.json").write_text(
        json.dumps(package_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    root_lock = copy.deepcopy(package_json)
    scoped = _npm_package("@scope/pkg", "1.2.3", integrity_byte=b"s")
    scoped.update({"dev": True, "license": "MIT"})
    parent = _npm_package("parent", "2.0.0", integrity_byte=b"p")
    parent["dependencies"] = {"child": "2.0.0"}
    package_lock = {
        "name": package_json["name"],
        "version": package_json["version"],
        "lockfileVersion": 3,
        "packages": {
            "": root_lock,
            "node_modules/@scope/pkg": scoped,
            "node_modules/child": _npm_package(
                "child", "1.0.0", integrity_byte=b"c"
            ),
            "node_modules/parent": parent,
            "node_modules/parent/node_modules/child": _npm_package(
                "child", "2.0.0", integrity_byte=b"n"
            ),
        },
    }
    (root / "apps/web/package-lock.json").write_text(
        json.dumps(package_lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_guardian_fixture(root: Path, *, with_requirements: bool = True) -> None:
    root.mkdir()
    requirements = """

require (
    golang.org/x/sys v0.30.0
    golang.org/x/text v0.22.0 // indirect
)
""" if with_requirements else ""
    (root / "go.mod").write_text(
        "module github.com/melloa-project/melloa-guardian\n\ngo 1.24\n"
        + requirements,
        encoding="utf-8",
    )
    if with_requirements:
        content_sum = base64.b64encode(b"g" * 32).decode("ascii")
        go_mod_sum = base64.b64encode(b"m" * 32).decode("ascii")
        (root / "go.sum").write_text(
            "\n".join(
                [
                    f"golang.org/x/sys v0.30.0 h1:{content_sum}",
                    f"golang.org/x/sys v0.30.0/go.mod h1:{go_mod_sum}",
                    f"golang.org/x/text v0.22.0 h1:{content_sum}",
                    f"golang.org/x/text v0.22.0/go.mod h1:{go_mod_sum}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )


def _fixture_roots(tmp_path: Path, *, with_go_requirements: bool = True) -> tuple[Path, Path]:
    project_root = tmp_path / "melloa"
    guardian_root = tmp_path / "melloa-guardian"
    project_root.mkdir()
    _write_project_fixture(project_root)
    _write_guardian_fixture(guardian_root, with_requirements=with_go_requirements)
    return project_root, guardian_root


def test_dependency_sbom_is_deterministic_and_covers_all_roots_and_locks(
    tmp_path: Path,
) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path)

    first = build_sbom(project_root, guardian_root)
    second = build_sbom(project_root, guardian_root)

    assert first == second
    rendered = rendered_sbom(first)
    assert "timestamp" not in rendered
    assert "serialNumber" not in first
    assert str(tmp_path) not in rendered
    assert first["bomFormat"] == "CycloneDX"
    assert first["specVersion"] == "1.6"
    refs = [component["bom-ref"] for component in first["components"]]
    assert refs == sorted(refs)
    assert len(refs) == 14
    assert "urn:melloa:python-project:melloa" in refs
    assert "pkg:pypi/melloa@0.0.1" not in refs
    assert "urn:melloa:npm-lock:root" in refs
    assert "pkg:golang/github.com/melloa-project/melloa-guardian" in refs

    components = {component["bom-ref"]: component for component in first["components"]}
    python_root = components["urn:melloa:python-project:melloa"]
    assert python_root["type"] == "application"
    assert python_root["scope"] == "required"
    assert "purl" not in python_root
    assert components["pkg:pypi/fastapi@0.116.2"]["externalReferences"] == [
        {
            "hashes": [{"alg": "SHA-256", "content": "a" * 64}],
            "type": "distribution",
            "url": "https://files.pythonhosted.org/a",
        },
        {
            "hashes": [{"alg": "SHA-256", "content": "b" * 64}],
            "type": "distribution",
            "url": "https://files.pythonhosted.org/b",
        },
    ]
    hatchling = components["pkg:pypi/hatchling@1.32.0"]
    assert hatchling["scope"] == "optional"
    assert {item["name"]: item["value"] for item in hatchling["properties"]}[
        "melloa:dependency_groups"
    ] == "build"
    editables = components["pkg:pypi/editables@0.5"]
    assert {item["name"]: item["value"] for item in editables["properties"]}[
        "melloa:dependency_groups"
    ] == "build"
    npm_ref = "urn:melloa:npm-lock:node_modules%2F%40scope%2Fpkg"
    assert components[npm_ref]["purl"] == "pkg:npm/%40scope/pkg@1.2.3"
    assert components[npm_ref]["externalReferences"][0]["hashes"] == [
        {"alg": "SHA-512", "content": (b"s" * 64).hex()}
    ]
    assert "purl" not in components["urn:melloa:npm-lock:root"]
    child_refs = [ref for ref in refs if "node_modules%2Fchild" in ref]
    assert len(child_refs) == 2

    go_component = components["pkg:golang/golang.org/x/sys@v0.30.0"]
    assert go_component["hashes"] == [
        {"alg": "SHA-256", "content": (b"g" * 32).hex()}
    ]
    indirect = components["pkg:golang/golang.org/x/text@v0.22.0"]
    assert {"name": "melloa:go:indirect", "value": "true"} in indirect["properties"]

    dependencies = {item["ref"]: item["dependsOn"] for item in first["dependencies"]}
    assert set(dependencies["urn:melloa:public-projects"]) == {
        "urn:melloa:python-project:melloa",
        "urn:melloa:npm-lock:root",
        "pkg:golang/github.com/melloa-project/melloa-guardian",
    }
    assert dependencies["urn:melloa:npm-lock:node_modules%2Fparent"] == [
        "urn:melloa:npm-lock:node_modules%2Fparent%2Fnode_modules%2Fchild"
    ]
    assert dependencies["pkg:pypi/hatchling@1.32.0"] == [
        "pkg:pypi/packaging@26.3"
    ]

    properties = {item["name"]: item["value"] for item in first["metadata"]["properties"]}
    assert properties["melloa:python:build_coverage"] == (
        "pyproject build-system requirements are reconciled with the locked build "
        "dependency group and included from uv.lock."
    )
    assert properties["melloa:inventory:exclusions"] == (
        "CI actions, runner/OS toolchains, containers, and signed provenance are "
        "outside this committed-lock dependency inventory."
    )
    assert first["metadata"]["tools"]["components"][0]["version"] == "1.1.0"
    for label, path in (
        ("pyproject.toml", project_root / "pyproject.toml"),
        ("uv.lock", project_root / "uv.lock"),
        ("apps/web/package.json", project_root / "apps/web/package.json"),
        ("apps/web/package-lock.json", project_root / "apps/web/package-lock.json"),
        ("melloa-guardian/go.mod", guardian_root / "go.mod"),
        ("melloa-guardian/go.sum", guardian_root / "go.sum"),
    ):
        assert properties[f"melloa:lockfile:{label}:sha256"] == hashlib.sha256(
            path.read_bytes()
        ).hexdigest()


def test_dependency_sbom_check_rejects_missing_malformed_stale_and_drifted_output(
    tmp_path: Path,
) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path, with_go_requirements=False)
    output = tmp_path / "dist/dependencies.cdx.json"
    document = build_sbom(project_root, guardian_root)

    assert check_sbom(document, output) == f"{output}: dependency SBOM is missing"
    write_sbom(document, output)
    assert output.read_text(encoding="utf-8") == rendered_sbom(document)
    assert check_sbom(document, output) is None

    output.write_text(json.dumps(document) + "\n", encoding="utf-8")
    assert check_sbom(document, output) == (
        f"{output}: dependency SBOM is stale or non-canonical"
    )
    output.write_text("{}\n", encoding="utf-8")
    assert "dependency SBOM is malformed" in check_sbom(document, output)
    output.write_text("{invalid-json\n", encoding="utf-8")
    assert "dependency SBOM is malformed" in check_sbom(document, output)

    write_sbom(document, output)
    package_json = project_root / "apps/web/package.json"
    package_json.write_text(package_json.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    drifted = build_sbom(project_root, guardian_root)
    assert check_sbom(drifted, output) == (
        f"{output}: dependency SBOM is stale or non-canonical"
    )


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("pyproject.toml", "pyproject.toml is unreadable or malformed"),
        ("uv.lock", "uv.lock is unreadable or malformed"),
        ("apps/web/package.json", "package.json is unreadable or malformed"),
        ("apps/web/package-lock.json", "package-lock.json is unreadable or malformed"),
        ("../melloa-guardian/go.mod", "Guardian go.mod is required"),
        ("../melloa-guardian/go.sum", "Guardian go.sum is required"),
    ],
)
def test_dependency_sbom_fails_closed_on_missing_inputs(
    tmp_path: Path,
    relative_path: str,
    expected: str,
) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path)
    target = project_root / relative_path
    target.unlink()

    with pytest.raises(SbomError, match=expected.replace(".", r"\.")):
        build_sbom(project_root, guardian_root)


@pytest.mark.parametrize(
    ("relative_path", "malformed"),
    [
        ("pyproject.toml", "[project\n"),
        ("uv.lock", "version = [\n"),
        ("apps/web/package.json", "{\n"),
        ("apps/web/package-lock.json", "[]\n"),
        ("../melloa-guardian/go.mod", "module example.com/guardian\n\ngo\n"),
        ("../melloa-guardian/go.sum", "malformed\n"),
    ],
)
def test_dependency_sbom_fails_closed_on_malformed_inputs(
    tmp_path: Path,
    relative_path: str,
    malformed: str,
) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path)
    (project_root / relative_path).write_text(malformed, encoding="utf-8")

    with pytest.raises(SbomError):
        build_sbom(project_root, guardian_root)


@pytest.mark.parametrize(
    "directive",
    [
        "exclude example.com/unsafe v1.2.3",
        "replace example.com/unsafe => ../unsafe",
        "retract v1.2.3",
        "toolchain go1.24.6",
        "tool example.com/tool",
        "godebug default=go1.24",
        "use ../workspace-module",
    ],
)
def test_dependency_sbom_rejects_unsupported_guardian_directives(
    tmp_path: Path,
    directive: str,
) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path, with_go_requirements=False)
    go_mod = guardian_root / "go.mod"
    go_mod.write_text(go_mod.read_text(encoding="utf-8") + directive + "\n", encoding="utf-8")

    with pytest.raises(SbomError, match="unsupported directive"):
        build_sbom(project_root, guardian_root)


@pytest.mark.parametrize(
    "case",
    [
        "python-source",
        "python-source-control",
        "npm-source",
        "npm-source-control",
        "npm-integrity",
    ],
)
def test_dependency_sbom_rejects_unapproved_or_unhashed_artifacts(
    tmp_path: Path,
    case: str,
) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path)
    if case.startswith("python"):
        uv_lock = project_root / "uv.lock"
        original, replacement = (
            ("https://files.pythonhosted.org/a", "https://files.pythonhosted.org/a\\n")
            if case == "python-source-control"
            else ("https://pypi.org/simple", "https://mirror.example/simple")
        )
        uv_lock.write_text(
            uv_lock.read_text(encoding="utf-8").replace(original, replacement, 1),
            encoding="utf-8",
        )
    else:
        lock_path = project_root / "apps/web/package-lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        package = lock["packages"]["node_modules/child"]
        if case == "npm-source":
            package["resolved"] = "https://registry.example/child.tgz"
        elif case == "npm-source-control":
            package["resolved"] = "\nhttps://registry.npmjs.org/child/-/child-1.0.0.tgz"
        else:
            package["integrity"] = (
                "sha512-"
                + base64.b64encode(b"short").decode("ascii")
                + " md5-AAAAAAAAAAAAAAAAAAAAAA=="
            )
        lock_path.write_text(
            json.dumps(lock, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    with pytest.raises(SbomError, match=r"unapproved|malformed|Subresource Integrity"):
        build_sbom(project_root, guardian_root)


def test_dependency_sbom_rejects_manifest_lock_disagreement(tmp_path: Path) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path)
    package_json_path = project_root / "apps/web/package.json"
    package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    package_json["dependencies"]["parent"] = "9.9.9"
    package_json_path.write_text(
        json.dumps(package_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SbomError,
        match=r"package\.json and package-lock\.json dependencies",
    ):
        build_sbom(project_root, guardian_root)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("runtime-specifier", "runtime dependency constraints"),
        ("runtime-extra", "runtime dependency"),
        ("group-specifier", "dependency group constraints"),
        ("root-runtime-extra", "runtime dependency edges"),
        ("root-runtime-marker", "unsupported fields"),
        ("group-marker", "unsupported fields"),
        ("metadata-marker", "unsupported fields"),
        ("build-backend-swap", "build-backend"),
        ("build-backend-path", "unsupported fields"),
        ("build-pin-range", "exact Hatchling pin"),
        ("build-system-drift", "build-system and build dependency group"),
        ("build-group-drift", "build-system and build dependency group"),
        ("build-edge-missing", "dependency groups"),
        ("build-metadata-drift", "dependency group constraints"),
        ("build-version-drift", "build backend versions"),
        ("build-helper-version-drift", "build dependency editables"),
        ("build-closure-missing", "unresolved"),
        ("build-package-missing", "selected build backend"),
        ("build-helper-package-missing", "build dependency editables"),
        ("lock-revision-missing", "lock format version 1 revision 3"),
        ("lock-revision-drift", "lock format version 1 revision 3"),
        ("lock-requires-python-missing", "uv.lock requires-python"),
        ("lock-requires-python-drift", "requires-python"),
        ("lock-requires-python-non-string", "uv.lock requires-python"),
        ("root-source-extra", "unsupported source shape"),
        ("registry-source-git", "unsupported source shape"),
        ("registry-source-path", "unsupported source shape"),
        ("registry-source-directory", "unsupported source shape"),
        ("registry-source-url", "unsupported source shape"),
        ("registry-source-unknown", "unsupported source shape"),
    ],
)
def test_dependency_sbom_rejects_pyproject_uv_metadata_drift(
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path)
    pyproject_path = project_root / "pyproject.toml"
    uv_lock_path = project_root / "uv.lock"
    if mutation == "runtime-specifier":
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8").replace(
                "FastAPI[standard]>=0.116,<1",
                "FastAPI[standard]>=0.117,<1",
            ),
            encoding="utf-8",
        )
    elif mutation == "runtime-extra":
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8").replace(
                "FastAPI[standard]>=0.116,<1",
                "FastAPI[all]>=0.116,<1",
            ),
            encoding="utf-8",
        )
    elif mutation == "group-specifier":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                '{ name = "pytest", specifier = ">=8,<9" }',
                '{ name = "pytest", specifier = ">=8.1,<9" }',
            ),
            encoding="utf-8",
        )
    elif mutation == "root-runtime-extra":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                '{ name = "FastAPI", extra = ["standard"] }',
                '{ name = "FastAPI" }',
            ),
            encoding="utf-8",
        )
    elif mutation == "root-runtime-marker":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                '{ name = "FastAPI", extra = ["standard"] }',
                '{ name = "FastAPI", extra = ["standard"], marker = "python_version >= \'3.13\'" }',
            ),
            encoding="utf-8",
        )
    elif mutation == "group-marker":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                '{ name = "pytest" }',
                '{ name = "pytest", marker = "sys_platform == \'linux\'" }',
                1,
            ),
            encoding="utf-8",
        )
    elif mutation == "metadata-marker":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                '{ name = "FastAPI", extras = ["standard"], specifier = ">=0.116,<1" }',
                (
                    '{ name = "FastAPI", extras = ["standard"], '
                    'specifier = ">=0.116,<1", marker = "python_version >= \'3.13\'" }'
                ),
            ),
            encoding="utf-8",
        )
    elif mutation == "build-backend-swap":
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8").replace(
                'build-backend = "hatchling.build"',
                'build-backend = "setuptools.build_meta"',
            ),
            encoding="utf-8",
        )
    elif mutation == "build-backend-path":
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8").replace(
                'build-backend = "hatchling.build"\n',
                'build-backend = "hatchling.build"\nbackend-path = ["build_backend"]\n',
            ),
            encoding="utf-8",
        )
    elif mutation == "build-system-drift":
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8").replace(
                'requires = ["editables==0.5", "hatchling==1.32.0"]',
                'requires = ["editables==0.5", "hatchling==1.31.0"]',
                1,
            ),
            encoding="utf-8",
        )
    elif mutation == "build-pin-range":
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8").replace(
                "hatchling==1.32.0",
                "hatchling>=1.32,<2",
            ),
            encoding="utf-8",
        )
    elif mutation == "build-group-drift":
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8").replace(
                'build = ["editables==0.5", "hatchling==1.32.0"]',
                'build = ["editables==0.5", "hatchling==1.31.0"]',
            ),
            encoding="utf-8",
        )
    elif mutation == "build-edge-missing":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                'build = [{ name = "editables" }, { name = "hatchling" }]\n',
                "",
            ),
            encoding="utf-8",
        )
    elif mutation == "build-metadata-drift":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                '{ name = "hatchling", specifier = "==1.32.0" }',
                '{ name = "hatchling", specifier = "==1.31.0" }',
            ),
            encoding="utf-8",
        )
    elif mutation == "build-version-drift":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                'name = "hatchling"\nversion = "1.32.0"',
                'name = "hatchling"\nversion = "1.31.0"',
            ),
            encoding="utf-8",
        )
    elif mutation == "build-helper-version-drift":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                'name = "editables"\nversion = "0.5"',
                'name = "editables"\nversion = "0.4"',
            ),
            encoding="utf-8",
        )
    elif mutation == "build-closure-missing":
        e_hash = "e" * 64
        packaging_block = (
            "\n[[package]]\n"
            'name = "packaging"\n'
            'version = "26.3"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
            f'sdist = {{ url = "https://files.pythonhosted.org/e", hash = "sha256:{e_hash}" }}\n\n'
        )
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                packaging_block,
                "",
            ),
            encoding="utf-8",
        )
    elif mutation == "build-package-missing":
        d_hash = "d" * 64
        hatchling_block = (
            "\n[[package]]\n"
            'name = "hatchling"\n'
            'version = "1.32.0"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
            'dependencies = [{ name = "packaging" }]\n'
            f'sdist = {{ url = "https://files.pythonhosted.org/d", hash = "sha256:{d_hash}" }}\n\n'
        )
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                hatchling_block,
                "",
            ),
            encoding="utf-8",
        )
    elif mutation == "build-helper-package-missing":
        f_hash = "f" * 64
        editables_block = (
            "\n[[package]]\n"
            'name = "editables"\n'
            'version = "0.5"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
            f'sdist = {{ url = "https://files.pythonhosted.org/f", hash = "sha256:{f_hash}" }}\n\n'
        )
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                editables_block,
                "",
            ),
            encoding="utf-8",
        )
    elif mutation == "lock-revision-missing":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace("revision = 3\n", ""),
            encoding="utf-8",
        )
    elif mutation == "lock-revision-drift":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace("revision = 3", "revision = 2"),
            encoding="utf-8",
        )
    elif mutation == "lock-requires-python-missing":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace('requires-python = ">=3.13"\n', ""),
            encoding="utf-8",
        )
    elif mutation == "lock-requires-python-drift":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                'requires-python = ">=3.13"',
                'requires-python = ">=3.14"',
                1,
            ),
            encoding="utf-8",
        )
    elif mutation == "lock-requires-python-non-string":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                'requires-python = ">=3.13"',
                "requires-python = 313",
                1,
            ),
            encoding="utf-8",
        )
    elif mutation == "root-source-extra":
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                'source = { editable = "." }',
                'source = { editable = ".", path = "." }',
            ),
            encoding="utf-8",
        )
    elif mutation.startswith("registry-source-"):
        source_key = mutation.removeprefix("registry-source-")
        source_value = {
            "directory": '"../pkg"',
            "git": '"https://git.example.invalid/repo"',
            "path": '"../pkg"',
            "unknown": '"value"',
            "url": '"https://files.pythonhosted.org/pkg.tar.gz"',
        }[source_key]
        uv_lock_path.write_text(
            uv_lock_path.read_text(encoding="utf-8").replace(
                'source = { registry = "https://pypi.org/simple" }',
                (
                    'source = { registry = "https://pypi.org/simple", '
                    f"{source_key} = {source_value} }}"
                ),
                1,
            ),
            encoding="utf-8",
        )

    with pytest.raises(SbomError, match=expected):
        build_sbom(project_root, guardian_root)


def test_dependency_sbom_rejects_missing_uv_root_metadata(tmp_path: Path) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path)
    uv_lock_path = project_root / "uv.lock"
    contents = uv_lock_path.read_text(encoding="utf-8")
    contents = contents.replace(
        "[package.metadata.requires-dev]",
        "[package.fixture-metadata.requires-dev]",
    ).replace("[package.metadata]", "[package.fixture-metadata]")
    uv_lock_path.write_text(contents, encoding="utf-8")

    with pytest.raises(SbomError, match="root metadata must be a table"):
        build_sbom(project_root, guardian_root)


@pytest.mark.parametrize(
    "requirement",
    [
        "FastAPI>=0.116,<1 trailing-data",
        "FastAPI>=0.116,<1; python_version >= '3.13'",
    ],
)
def test_dependency_sbom_rejects_unsupported_requirement_syntax(
    tmp_path: Path,
    requirement: str,
) -> None:
    project_root, guardian_root = _fixture_roots(tmp_path)
    pyproject_path = project_root / "pyproject.toml"
    pyproject_path.write_text(
        pyproject_path.read_text(encoding="utf-8").replace(
            "FastAPI[standard]>=0.116,<1",
            requirement,
        ),
        encoding="utf-8",
    )

    with pytest.raises(SbomError, match="unsupported requirement"):
        build_sbom(project_root, guardian_root)
