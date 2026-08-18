#!/usr/bin/env python3
"""Generate or verify a deterministic CycloneDX SBOM from reviewed lockfiles."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import quote

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
DEFAULT_GUARDIAN_ROOT = ROOT.parent / "melloa-guardian"
DEFAULT_OUTPUT = ROOT / "dist/melloa-dependency-sbom.cdx.json"
GENERATOR_VERSION = "1.1.0"
_PYTHON_NAME_PATTERN = re.compile(r"[-_.]+")
_PYTHON_PACKAGE_FRAGMENT = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_PYTHON_PACKAGE_PATTERN = re.compile(_PYTHON_PACKAGE_FRAGMENT)
_PYTHON_VERSION_FRAGMENT = r"[A-Za-z0-9](?:[A-Za-z0-9.*+!_-]*[A-Za-z0-9*+!_-])?"
_PYTHON_SPECIFIER_FRAGMENT = (
    rf"(?:~=|===|==|!=|<=|>=|<|>)[ \t]*{_PYTHON_VERSION_FRAGMENT}"
)
_PYTHON_REQUIREMENT_PATTERN = re.compile(
    rf"(?P<name>{_PYTHON_PACKAGE_FRAGMENT})"
    rf"(?:\[(?P<extras>{_PYTHON_PACKAGE_FRAGMENT}"
    rf"(?:[ \t]*,[ \t]*{_PYTHON_PACKAGE_FRAGMENT})*)\])?"
    rf"[ \t]*(?P<specifier>{_PYTHON_SPECIFIER_FRAGMENT}"
    rf"(?:[ \t]*,[ \t]*{_PYTHON_SPECIFIER_FRAGMENT})*)?"
)
_PYTHON_EXACT_PIN_PATTERN = re.compile(rf"=={_PYTHON_VERSION_FRAGMENT}")
_ALLOWED_PYTHON_HOSTS = frozenset({"files.pythonhosted.org", "pypi.org"})
_ALLOWED_NPM_HOSTS = frozenset({"registry.npmjs.org"})


class SbomError(ValueError):
    """A lockfile or generated SBOM is incomplete or malformed."""


class PythonRequirement(NamedTuple):
    name: str
    extras: tuple[str, ...]
    specifier: str


def _read_toml(path: Path, label: str) -> dict[str, Any]:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise SbomError(f"{label} is unreadable or malformed: {error}") from error
    if not isinstance(document, dict):
        raise SbomError(f"{label} must contain a TOML table")
    return document


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SbomError(f"{label} is unreadable or malformed: {error}") from error
    if not isinstance(document, dict):
        raise SbomError(f"{label} must contain a JSON object")
    return document


def _file_digest(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise SbomError(f"{label} is unreadable: {error}") from error


def _required_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise SbomError(f"{context} must be a non-empty string")
    return value


def _is_approved_https_url(value: str, allowed_hosts: frozenset[str]) -> bool:
    return is_approved_https_url(value, allowed_hosts)


def _python_name(name: str) -> str:
    return _PYTHON_NAME_PATTERN.sub("-", name).lower()


def _normalize_extras(values: Any, context: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw_values = values.split(",")
    elif isinstance(values, list):
        raw_values = values
    else:
        raise SbomError(f"{context} extras must be strings")
    extras: set[str] = set()
    for value in raw_values:
        extra = _required_string(value.strip() if isinstance(value, str) else value, context)
        if _PYTHON_PACKAGE_PATTERN.fullmatch(extra) is None:
            raise SbomError(f"{context} contains an unsupported extra: {extra}")
        normalized = _python_name(extra)
        if normalized in extras:
            raise SbomError(f"{context} contains duplicate extras")
        extras.add(normalized)
    return tuple(sorted(extras))


def _python_requirement(value: str, context: str) -> PythonRequirement:
    match = _PYTHON_REQUIREMENT_PATTERN.fullmatch(value)
    if match is None:
        raise SbomError(f"{context} contains an unsupported requirement: {value}")
    specifier = re.sub(r"[ \t]+", "", match.group("specifier") or "")
    return PythonRequirement(
        _python_name(match.group("name")),
        _normalize_extras(
            match.group("extras"),
            f"{context} {match.group('name')}",
        ),
        specifier,
    )


def _python_requirements(values: Any, context: str) -> set[PythonRequirement]:
    if not isinstance(values, list):
        raise SbomError(f"{context} must be a list")
    requirements: set[PythonRequirement] = set()
    names: set[str] = set()
    for value in values:
        requirement = _python_requirement(
            _required_string(value, f"{context} entry"),
            context,
        )
        if requirement.name in names:
            raise SbomError(f"{context} contains duplicate requirements")
        names.add(requirement.name)
        requirements.add(requirement)
    return requirements


def _metadata_requirement(value: Any, context: str) -> PythonRequirement:
    if not isinstance(value, dict):
        raise SbomError(f"{context} entries must be tables")
    unsupported_fields = set(value) - {"name", "extras", "specifier"}
    if unsupported_fields:
        raise SbomError(
            f"{context} contains unsupported fields: {sorted(unsupported_fields)}"
        )
    name = _required_string(value.get("name"), f"{context} name")
    if "extras" in value and not isinstance(value["extras"], list):
        raise SbomError(f"{context} extras must be a list")
    extras = _normalize_extras(value.get("extras"), f"{context} extras")
    specifier = value.get("specifier", "")
    if not isinstance(specifier, str):
        raise SbomError(f"{context} specifier must be a string")
    rendered = name
    if extras:
        rendered += f"[{','.join(extras)}]"
    rendered += specifier
    return _python_requirement(
        rendered,
        context,
    )


def _metadata_requirements(values: Any, context: str) -> set[PythonRequirement]:
    if not isinstance(values, list):
        raise SbomError(f"{context} must be a list")
    requirements: set[PythonRequirement] = set()
    names: set[str] = set()
    for value in values:
        requirement = _metadata_requirement(value, context)
        if requirement.name in names:
            raise SbomError(f"{context} contains duplicate requirements")
        names.add(requirement.name)
        requirements.add(requirement)
    return requirements


def _dependency_edge_requirements(values: Any, context: str) -> set[PythonRequirement]:
    if not isinstance(values, list):
        raise SbomError(f"{context} must be a list")
    requirements: set[PythonRequirement] = set()
    names: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise SbomError(f"{context} entries must be tables")
        unsupported_fields = set(value) - {"extra", "name"}
        if unsupported_fields:
            raise SbomError(
                f"{context} contains unsupported fields: {sorted(unsupported_fields)}"
            )
        name = _python_name(_required_string(value.get("name"), f"{context} name"))
        if name in names:
            raise SbomError(f"{context} contains duplicate requirements")
        names.add(name)
        if "extra" in value and not isinstance(value["extra"], list):
            raise SbomError(f"{context} extra must be a list")
        requirements.add(
            PythonRequirement(
                name,
                _normalize_extras(value.get("extra"), f"{context} extras"),
                "",
            )
        )
    return requirements


def _without_specifiers(requirements: set[PythonRequirement]) -> set[PythonRequirement]:
    return {
        PythonRequirement(requirement.name, requirement.extras, "")
        for requirement in requirements
    }


def _dependency_names(values: Any, context: str) -> set[str]:
    if values is None:
        return set()
    if not isinstance(values, list):
        raise SbomError(f"{context} must be a list")
    names: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            raise SbomError(f"{context} entries must be tables")
        names.add(_python_name(_required_string(value.get("name"), f"{context} name")))
    return names


def _closure(seeds: set[str], graph: dict[str, set[str]]) -> set[str]:
    selected: set[str] = set()
    pending = list(seeds)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        pending.extend(graph.get(name, set()) - selected)
    return selected


def _distribution_reference(
    artifact: Any,
    *,
    context: str,
    allowed_hosts: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        raise SbomError(f"{context} must be a table")
    url = _required_string(artifact.get("url"), f"{context} URL")
    if not _is_approved_https_url(url, allowed_hosts):
        raise SbomError(f"{context} uses an unapproved distribution source")
    digest = _required_string(artifact.get("hash"), f"{context} hash")
    digest_content = lowercase_sha256_content(digest)
    if digest_content is None:
        raise SbomError(f"{context} must carry a lowercase SHA-256 lock hash")
    return {
        "type": "distribution",
        "url": url,
        "hashes": [{"alg": "SHA-256", "content": digest_content}],
    }


def _python_inventory(
    project_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str, str]:
    pyproject = _read_toml(project_root / "pyproject.toml", "pyproject.toml")
    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise SbomError("pyproject.toml has no [project] table")
    project_name = _required_string(project.get("name"), "project name")
    project_version = _required_string(project.get("version"), "project version")
    project_requires_python = _required_string(
        project.get("requires-python"),
        "project requires-python",
    )
    build_system = pyproject.get("build-system")
    if not isinstance(build_system, dict):
        raise SbomError("pyproject.toml has no [build-system] table")
    unsupported_build_fields = set(build_system) - {"requires", "build-backend"}
    if unsupported_build_fields:
        raise SbomError(
            "pyproject.toml build-system contains unsupported fields: "
            f"{sorted(unsupported_build_fields)}"
        )
    build_backend = _required_string(
        build_system.get("build-backend"),
        "build-system build-backend",
    )
    if build_backend != "hatchling.build":
        raise SbomError("pyproject.toml build-system build-backend must be hatchling.build")
    build_system_requirements = _python_requirements(
        build_system.get("requires"),
        "build-system requires",
    )
    build_requirement = next(
        (
            requirement
            for requirement in build_system_requirements
            if requirement.name == "hatchling"
        ),
        None,
    )
    if build_requirement is None:
        raise SbomError("pyproject.toml build-system must contain an exact Hatchling pin")
    for requirement in build_system_requirements:
        if requirement.extras or "*" in requirement.specifier:
            raise SbomError("pyproject.toml build-system requirements must be exact pins")
        if _PYTHON_EXACT_PIN_PATTERN.fullmatch(requirement.specifier) is None:
            if requirement.name == "hatchling":
                raise SbomError(
                    "pyproject.toml build-system must contain an exact Hatchling pin"
                )
            raise SbomError("pyproject.toml build-system requirements must be exact pins")
    declared_runtime_requirements = _python_requirements(
        project.get("dependencies", []),
        "project dependencies",
    )
    declared_runtime = {requirement.name for requirement in declared_runtime_requirements}
    declared_group_requirements: dict[str, set[PythonRequirement]] = {}
    dependency_groups = pyproject.get("dependency-groups", {})
    if not isinstance(dependency_groups, dict):
        raise SbomError("pyproject dependency-groups must be a table")
    for group_name, requirements in dependency_groups.items():
        declared_group_requirements[str(group_name)] = _python_requirements(
            requirements,
            f"dependency group {group_name}",
        )
    declared_groups = {
        group: {requirement.name for requirement in requirements}
        for group, requirements in declared_group_requirements.items()
    }
    if declared_group_requirements.get("build") != build_system_requirements:
        raise SbomError("pyproject.toml build-system and build dependency group disagree")

    lock = _read_toml(project_root / "uv.lock", "uv.lock")
    if lock.get("version") != 1 or lock.get("revision") != 3:
        raise SbomError("uv.lock must use supported lock format version 1 revision 3")
    lock_requires_python = _required_string(
        lock.get("requires-python"),
        "uv.lock requires-python",
    )
    if lock_requires_python != project_requires_python:
        raise SbomError("pyproject.toml and uv.lock requires-python disagree")
    packages = lock.get("package")
    if not isinstance(packages, list) or not packages:
        raise SbomError("uv.lock must contain at least one package")
    by_name: dict[str, dict[str, Any]] = {}
    graph: dict[str, set[str]] = {}
    root_package: dict[str, Any] | None = None
    for package in packages:
        if not isinstance(package, dict):
            raise SbomError("uv.lock package entries must be tables")
        name = _required_string(package.get("name"), "uv.lock package name")
        normalized_name = _python_name(name)
        _required_string(package.get("version"), f"uv.lock version for {name}")
        if normalized_name in by_name:
            raise SbomError(f"uv.lock has multiple versions of {normalized_name}")
        by_name[normalized_name] = package
        graph[normalized_name] = _dependency_names(
            package.get("dependencies", []),
            f"uv.lock dependencies for {name}",
        )
        source = package.get("source")
        if isinstance(source, dict) and source.get("editable") == ".":
            if root_package is not None:
                raise SbomError("uv.lock has multiple editable project roots")
            root_package = package
    if root_package is None:
        raise SbomError("uv.lock has no editable project root")
    root_name = _python_name(_required_string(root_package.get("name"), "uv.lock root name"))
    if root_name != _python_name(project_name):
        raise SbomError("pyproject.toml and uv.lock project names disagree")
    if root_package.get("version") != project_version:
        raise SbomError("pyproject.toml and uv.lock project versions disagree")
    for requirement in build_system_requirements:
        locked_build_package = by_name.get(requirement.name)
        if locked_build_package is None:
            if requirement.name == build_requirement.name:
                raise SbomError("uv.lock has no package for the selected build backend")
            raise SbomError(
                f"uv.lock has no package for build dependency {requirement.name}"
            )
        if locked_build_package.get("version") != requirement.specifier.removeprefix("=="):
            if requirement.name == build_requirement.name:
                raise SbomError("pyproject.toml and uv.lock build backend versions disagree")
            raise SbomError(
                f"pyproject.toml and uv.lock build dependency {requirement.name} "
                "versions disagree"
            )
    if graph[root_name] != declared_runtime:
        raise SbomError("pyproject.toml and uv.lock runtime dependencies disagree")
    locked_runtime_edges = _dependency_edge_requirements(
        root_package.get("dependencies"),
        "uv.lock root runtime dependencies",
    )
    if locked_runtime_edges != _without_specifiers(declared_runtime_requirements):
        raise SbomError("pyproject.toml and uv.lock runtime dependency edges disagree")

    metadata = root_package.get("metadata")
    if not isinstance(metadata, dict):
        raise SbomError("uv.lock root metadata must be a table")
    locked_runtime_requirements = _metadata_requirements(
        metadata.get("requires-dist"),
        "uv.lock metadata requires-dist",
    )
    if locked_runtime_requirements != declared_runtime_requirements:
        raise SbomError(
            "pyproject.toml and uv.lock runtime dependency constraints or extras disagree"
        )

    locked_groups = root_package.get("dev-dependencies", {})
    if not isinstance(locked_groups, dict):
        raise SbomError("uv.lock root dev-dependencies must be a table")
    normalized_locked_groups = {
        str(group): _dependency_names(values, f"uv.lock dependency group {group}")
        for group, values in locked_groups.items()
    }
    if normalized_locked_groups != declared_groups:
        raise SbomError("pyproject.toml and uv.lock dependency groups disagree")
    normalized_locked_group_edges = {
        str(group): _dependency_edge_requirements(values, f"uv.lock dependency group {group}")
        for group, values in locked_groups.items()
    }
    declared_group_edges = {
        group: _without_specifiers(requirements)
        for group, requirements in declared_group_requirements.items()
    }
    if normalized_locked_group_edges != declared_group_edges:
        raise SbomError("pyproject.toml and uv.lock dependency group edges disagree")
    locked_group_metadata = metadata.get("requires-dev")
    if not isinstance(locked_group_metadata, dict):
        raise SbomError("uv.lock root metadata requires-dev must be a table")
    normalized_group_metadata = {
        str(group): _metadata_requirements(values, f"uv.lock metadata requires-dev {group}")
        for group, values in locked_group_metadata.items()
    }
    if normalized_group_metadata != declared_group_requirements:
        raise SbomError(
            "pyproject.toml and uv.lock dependency group constraints or extras disagree"
        )
    for package_name, dependencies in graph.items():
        missing = dependencies - by_name.keys()
        if missing:
            raise SbomError(
                f"uv.lock dependencies for {package_name} are unresolved: {sorted(missing)}"
            )

    runtime_packages = _closure(declared_runtime, graph)
    group_packages = {
        group: _closure(seeds, graph) for group, seeds in normalized_locked_groups.items()
    }
    components: list[dict[str, Any]] = []
    refs: dict[str, str] = {}
    for normalized_name, package in by_name.items():
        name = _required_string(package.get("name"), "uv.lock package name")
        version = _required_string(package.get("version"), f"uv.lock version for {name}")
        if normalized_name == root_name:
            bom_ref = f"urn:melloa:python-project:{quote(normalized_name, safe='')}"
        else:
            bom_ref = f"pkg:pypi/{quote(normalized_name, safe='')}@{quote(version, safe='')}"
        refs[normalized_name] = bom_ref
        groups = sorted(
            group for group, selected in group_packages.items() if normalized_name in selected
        )
        if normalized_name in runtime_packages:
            groups.insert(0, "runtime")
        if normalized_name == root_name:
            groups.insert(0, "project-root")
        component: dict[str, Any] = {
            "type": "application" if normalized_name == root_name else "library",
            "bom-ref": bom_ref,
            "name": name,
            "version": version,
            "scope": "required"
            if normalized_name == root_name or normalized_name in runtime_packages
            else "optional",
            "properties": [
                {"name": "melloa:ecosystem", "value": "python"},
                {"name": "melloa:source_lockfile", "value": "uv.lock"},
                {"name": "melloa:dependency_groups", "value": ",".join(groups)},
            ],
        }
        source = package.get("source")
        if not isinstance(source, dict):
            raise SbomError(f"uv.lock package {name} has no source table")
        source_kind = approved_python_source_kind(source, _ALLOWED_PYTHON_HOSTS)
        if source_kind == "editable":
            component["properties"].append(
                {"name": "melloa:source", "value": "repository-root"}
            )
        else:
            if source_kind != "registry" and set(source) != {"registry"}:
                raise SbomError(f"uv.lock package {name} has unsupported source shape")
            if source_kind != "registry":
                raise SbomError(f"uv.lock package {name} uses an unapproved registry")
            component["purl"] = bom_ref
            artifacts: list[Any] = []
            if "sdist" in package:
                artifacts.append(package["sdist"])
            wheels = package.get("wheels", [])
            if not isinstance(wheels, list):
                raise SbomError(f"uv.lock wheels for {name} must be a list")
            artifacts.extend(wheels)
            if not artifacts:
                raise SbomError(f"uv.lock package {name} has no hashed artifacts")
            references = [
                _distribution_reference(
                    artifact,
                    context=f"uv.lock artifact for {name}",
                    allowed_hosts=_ALLOWED_PYTHON_HOSTS,
                )
                for artifact in artifacts
            ]
            references.sort(key=lambda item: (item["url"], item["hashes"][0]["content"]))
            component["externalReferences"] = references
        components.append(component)

    dependencies = [
        {
            "ref": refs[name],
            "dependsOn": sorted(refs[dependency] for dependency in graph[name]),
        }
        for name in sorted(by_name)
    ]
    root_direct = declared_runtime | set().union(*normalized_locked_groups.values())
    missing_root_direct = root_direct - by_name.keys()
    if missing_root_direct:
        raise SbomError(
            f"uv.lock root direct dependencies are unresolved: {sorted(missing_root_direct)}"
        )
    root_ref = refs[root_name]
    root_dependency = next(item for item in dependencies if item["ref"] == root_ref)
    root_dependency["dependsOn"] = sorted(refs[name] for name in root_direct)
    return components, dependencies, root_ref, project_name, project_version


def _npm_name_from_lock_path(lock_path: str) -> str:
    if "node_modules/" not in lock_path:
        raise SbomError(f"unsupported npm lock path: {lock_path}")
    return lock_path.rsplit("node_modules/", maxsplit=1)[-1]


def _npm_purl(name: str, version: str) -> str:
    return f"pkg:npm/{quote(name.lower(), safe='/')}@{quote(version, safe='')}"


def _sri_hashes(integrity: str, context: str) -> list[dict[str, str]]:
    parsed = supported_sri_hashes(integrity)
    if parsed is None:
        raise SbomError(f"{context} has no supported Subresource Integrity hash")
    return [{"alg": algorithm, "content": digest} for algorithm, digest in parsed]


def _npm_ref(package_path: str) -> str:
    label = "root" if not package_path else quote(package_path, safe="")
    return f"urn:melloa:npm-lock:{label}"


def _npm_dependency_names(package: dict[str, Any], context: str) -> set[str]:
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        values = package.get(key, {})
        if not isinstance(values, dict):
            raise SbomError(f"{context} {key} must be an object")
        names.update(str(name) for name in values)
    return names


def _resolve_npm_dependency(
    package_path: str,
    dependency_name: str,
    packages: dict[str, Any],
) -> str | None:
    base = package_path
    while True:
        candidate = (
            f"{base}/node_modules/{dependency_name}"
            if base
            else f"node_modules/{dependency_name}"
        )
        if candidate in packages:
            return candidate
        marker = base.rfind("/node_modules/")
        if marker < 0:
            if not base:
                return None
            base = ""
        else:
            base = base[:marker]


def _npm_inventory(
    project_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    package_json = _read_json(project_root / "apps/web/package.json", "package.json")
    lock = _read_json(
        project_root / "apps/web/package-lock.json",
        "package-lock.json",
    )
    if lock.get("lockfileVersion") != 3:
        raise SbomError("package-lock.json must use supported lockfileVersion 3")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or not packages:
        raise SbomError("package-lock.json must contain a packages object")
    root_package = packages.get("")
    if not isinstance(root_package, dict):
        raise SbomError("package-lock.json has no root package")
    root_name = _required_string(root_package.get("name"), "npm root name")
    root_version = _required_string(root_package.get("version"), "npm root version")
    if lock.get("name") != root_name or lock.get("version") != root_version:
        raise SbomError("package-lock.json top-level and root identities disagree")
    if package_json.get("name") != root_name or package_json.get("version") != root_version:
        raise SbomError("package.json and package-lock.json root identities disagree")
    for key in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    ):
        declared = package_json.get(key, {})
        locked = root_package.get(key, {})
        if not isinstance(declared, dict) or not isinstance(locked, dict) or declared != locked:
            raise SbomError(f"package.json and package-lock.json {key} disagree")

    refs = {str(package_path): _npm_ref(str(package_path)) for package_path in packages}
    components: list[dict[str, Any]] = []
    for raw_path, raw_package in packages.items():
        package_path = str(raw_path)
        if not isinstance(raw_package, dict):
            raise SbomError(f"npm package {package_path or '<root>'} must be an object")
        if raw_package.get("link"):
            raise SbomError(f"npm linked package {package_path} is not supported")
        if not package_path:
            name = root_name
            version = root_version
        else:
            name = _npm_name_from_lock_path(package_path)
            version = _required_string(
                raw_package.get("version"),
                f"npm version for {name}",
            )
        component: dict[str, Any] = {
            "type": "application" if not package_path else "library",
            "bom-ref": refs[package_path],
            "name": name,
            "version": version,
            "scope": "optional" if raw_package.get("dev") else "required",
            "properties": [
                {"name": "melloa:ecosystem", "value": "npm"},
                {
                    "name": "melloa:source_lockfile",
                    "value": "apps/web/package-lock.json",
                },
                {"name": "melloa:package_path", "value": package_path or "<root>"},
            ],
        }
        if package_path:
            component["purl"] = _npm_purl(name, version)
        else:
            component["properties"].append(
                {"name": "melloa:source", "value": "repository-root"}
            )
        for flag in ("dev", "optional", "peer"):
            if raw_package.get(flag):
                component["properties"].append(
                    {"name": f"melloa:npm:{flag}", "value": "true"}
                )
        license_value = raw_package.get("license")
        if isinstance(license_value, str):
            component["properties"].append(
                {"name": "melloa:npm:license", "value": license_value}
            )
        if package_path:
            resolved = _required_string(
                raw_package.get("resolved"),
                f"npm resolved URL for {name}",
            )
            if not _is_approved_https_url(resolved, _ALLOWED_NPM_HOSTS):
                raise SbomError(f"npm package {name} uses an unapproved source")
            integrity = _required_string(
                raw_package.get("integrity"),
                f"npm integrity for {name}",
            )
            component["externalReferences"] = [
                {
                    "type": "distribution",
                    "url": resolved,
                    "hashes": _sri_hashes(integrity, f"npm package {name}"),
                }
            ]
        components.append(component)

    dependencies: list[dict[str, Any]] = []
    for raw_path, raw_package in packages.items():
        package_path = str(raw_path)
        dependency_paths: set[str] = set()
        for dependency_name in _npm_dependency_names(raw_package, package_path or "npm root"):
            resolved_path = _resolve_npm_dependency(package_path, dependency_name, packages)
            optional_dependencies = raw_package.get("optionalDependencies", {})
            peer_metadata = raw_package.get("peerDependenciesMeta", {})
            peer_optional = (
                isinstance(peer_metadata, dict)
                and isinstance(peer_metadata.get(dependency_name), dict)
                and peer_metadata[dependency_name].get("optional") is True
            )
            if resolved_path is None and (
                dependency_name in optional_dependencies or peer_optional
            ):
                continue
            if resolved_path is None:
                raise SbomError(
                    f"package-lock.json dependency {dependency_name} from "
                    f"{package_path or '<root>'} is unresolved"
                )
            dependency_paths.add(resolved_path)
        dependencies.append(
            {
                "ref": refs[package_path],
                "dependsOn": sorted(refs[path] for path in dependency_paths),
            }
        )
    return components, dependencies, refs[""]


def _go_requirements(go_mod: Path) -> tuple[str, str, list[tuple[str, str, bool]]]:
    try:
        lines = go_mod.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise SbomError(f"Guardian go.mod is unreadable: {error}") from error
    module_name: str | None = None
    go_version: str | None = None
    requirements: list[tuple[str, str, bool]] = []
    in_require_block = False
    for raw_line in lines:
        content, _separator, comment = raw_line.partition("//")
        line = content.strip()
        if not line:
            continue
        fields = line.split()
        if in_require_block:
            if line == ")":
                in_require_block = False
                continue
            if len(fields) != 2:
                raise SbomError("Guardian go.mod has a malformed require entry")
            requirements.append((fields[0], fields[1], comment.strip() == "indirect"))
            continue
        if fields[0] == "module":
            if len(fields) != 2 or module_name is not None:
                raise SbomError("Guardian go.mod has a malformed module directive")
            module_name = fields[1]
            continue
        if fields[0] == "go":
            if len(fields) != 2 or go_version is not None:
                raise SbomError("Guardian go.mod has a malformed go directive")
            go_version = fields[1]
            continue
        if fields == ["require", "("]:
            in_require_block = True
            continue
        if fields[0] == "require":
            if len(fields) != 3:
                raise SbomError("Guardian go.mod has a malformed require directive")
            requirements.append((fields[1], fields[2], comment.strip() == "indirect"))
            continue
        raise SbomError(f"Guardian go.mod has unsupported directive: {fields[0]}")
    if in_require_block:
        raise SbomError("Guardian go.mod has an unterminated require block")
    if module_name is None or go_version is None:
        raise SbomError("Guardian go.mod must declare one module and Go version")
    if len({module for module, _version, _indirect in requirements}) != len(requirements):
        raise SbomError("Guardian go.mod has duplicate requirements")
    return module_name, go_version, requirements


def _go_sums(go_sum: Path, required: bool) -> dict[tuple[str, str], str]:
    if not go_sum.exists():
        if required:
            raise SbomError("Guardian go.sum is required for declared modules")
        return {}
    try:
        lines = go_sum.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise SbomError(f"Guardian go.sum is unreadable: {error}") from error
    sums: dict[tuple[str, str], str] = {}
    for line in lines:
        fields = line.split()
        if len(fields) != 3:
            raise SbomError("Guardian go.sum has a malformed entry")
        module, version, checksum = fields
        if version.endswith("/go.mod"):
            continue
        if not checksum.startswith("h1:"):
            raise SbomError("Guardian go.sum has an unsupported checksum")
        try:
            digest = base64.b64decode(checksum.removeprefix("h1:"), validate=True)
        except (binascii.Error, ValueError) as error:
            raise SbomError("Guardian go.sum has a malformed h1 checksum") from error
        if len(digest) != 32:
            raise SbomError("Guardian go.sum h1 checksum is not SHA-256 sized")
        key = (module, version)
        if key in sums and sums[key] != digest.hex():
            raise SbomError("Guardian go.sum has conflicting checksums")
        sums[key] = digest.hex()
    return sums


def _go_inventory(
    guardian_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, list[dict[str, str]]]:
    go_mod = guardian_root / "go.mod"
    if not go_mod.is_file():
        raise SbomError("Guardian go.mod is required")
    module_name, go_version, requirements = _go_requirements(go_mod)
    sums = _go_sums(guardian_root / "go.sum", required=bool(requirements))
    root_ref = f"pkg:golang/{quote(module_name, safe='/')}"
    components: list[dict[str, Any]] = [
        {
            "type": "application",
            "bom-ref": root_ref,
            "name": module_name.rsplit("/", maxsplit=1)[-1],
            "group": module_name.rsplit("/", maxsplit=1)[0],
            "purl": root_ref,
            "properties": [
                {"name": "melloa:ecosystem", "value": "go"},
                {"name": "melloa:source_lockfile", "value": "melloa-guardian/go.mod"},
                {"name": "melloa:go_version", "value": go_version},
            ],
        }
    ]
    dependency_refs: list[str] = []
    for module, version, indirect in requirements:
        digest = sums.get((module, version))
        if digest is None:
            raise SbomError(f"Guardian go.sum has no content checksum for {module}@{version}")
        purl = f"pkg:golang/{quote(module, safe='/')}@{quote(version, safe='')}"
        components.append(
            {
                "type": "library",
                "bom-ref": purl,
                "name": module,
                "version": version,
                "purl": purl,
                "hashes": [{"alg": "SHA-256", "content": digest}],
                "properties": [
                    {"name": "melloa:ecosystem", "value": "go"},
                    {"name": "melloa:source_lockfile", "value": "melloa-guardian/go.mod"},
                    {"name": "melloa:go:indirect", "value": str(indirect).lower()},
                ],
            }
        )
        dependency_refs.append(purl)
    dependencies = [
        {"ref": root_ref, "dependsOn": sorted(dependency_refs)},
        *({"ref": ref, "dependsOn": []} for ref in sorted(dependency_refs)),
    ]
    properties = [
        {"name": "melloa:guardian:module", "value": module_name},
        {"name": "melloa:guardian:go_version", "value": go_version},
        {"name": "melloa:guardian:requires_count", "value": str(len(requirements))},
        {
            "name": "melloa:guardian:coverage_limit",
            "value": "Go standard-library packages are not enumerated by module lockfiles.",
        },
    ]
    return components, dependencies, root_ref, properties


def build_sbom(project_root: Path, guardian_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    guardian_root = guardian_root.resolve()
    python, python_dependencies, python_root, project_name, project_version = (
        _python_inventory(project_root)
    )
    npm, npm_dependencies, npm_root = _npm_inventory(project_root)
    go, go_dependencies, go_root, guardian_properties = _go_inventory(guardian_root)
    components = sorted(
        [*python, *npm, *go],
        key=lambda component: component["bom-ref"],
    )
    dependencies = [
        {
            "ref": "urn:melloa:public-projects",
            "dependsOn": sorted((python_root, npm_root, go_root)),
        },
        *python_dependencies,
        *npm_dependencies,
        *go_dependencies,
    ]
    dependencies.sort(key=lambda item: item["ref"])
    lockfiles = (
        ("pyproject.toml", project_root / "pyproject.toml"),
        ("uv.lock", project_root / "uv.lock"),
        ("apps/web/package.json", project_root / "apps/web/package.json"),
        (
            "apps/web/package-lock.json",
            project_root / "apps/web/package-lock.json",
        ),
        ("melloa-guardian/go.mod", guardian_root / "go.mod"),
    )
    properties = [
        {"name": "melloa:source", "value": "reviewed-lockfiles"},
        {
            "name": "melloa:python:coverage_limit",
            "value": "uv.lock marker branches are inventoried as a platform union.",
        },
        {
            "name": "melloa:python:build_coverage",
            "value": (
                "pyproject build-system requirements are reconciled with the locked build "
                "dependency group and included from uv.lock."
            ),
        },
        {
            "name": "melloa:inventory:exclusions",
            "value": (
                "CI actions, runner/OS toolchains, containers, and signed provenance are "
                "outside this committed-lock dependency inventory."
            ),
        },
        {
            "name": "melloa:npm:coverage_limit",
            "value": (
                "package-lock packages include runtime, development, peer, "
                "and optional scope."
            ),
        },
        *guardian_properties,
        *(
            {
                "name": f"melloa:lockfile:{label}:sha256",
                "value": _file_digest(path, label),
            }
            for label, path in lockfiles
        ),
    ]
    go_sum = guardian_root / "go.sum"
    if go_sum.exists():
        properties.append(
            {
                "name": "melloa:lockfile:melloa-guardian/go.sum:sha256",
                "value": _file_digest(go_sum, "Guardian go.sum"),
            }
        )
    properties.sort(key=lambda item: item["name"])
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": "urn:melloa:public-projects",
                "name": f"{project_name}-public-projects",
                "version": project_version,
            },
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "melloa-generate-dependency-sbom",
                        "version": GENERATOR_VERSION,
                    }
                ]
            },
            "properties": properties,
        },
        "components": components,
        "dependencies": dependencies,
    }
    _validate_sbom_document(document)
    return document


def _validate_sbom_document(document: Any) -> None:
    if not isinstance(document, dict):
        raise SbomError("SBOM root must be a JSON object")
    if document.get("bomFormat") != "CycloneDX" or document.get("specVersion") != "1.6":
        raise SbomError("SBOM must be CycloneDX 1.6")
    if document.get("version") != 1:
        raise SbomError("SBOM document version must be 1")
    components = document.get("components")
    dependencies = document.get("dependencies")
    metadata = document.get("metadata")
    if not isinstance(components, list) or not isinstance(dependencies, list):
        raise SbomError("SBOM components and dependencies must be arrays")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("component"), dict):
        raise SbomError("SBOM metadata must identify the aggregate root")
    refs = {
        _required_string(component.get("bom-ref"), "SBOM component bom-ref")
        for component in components
        if isinstance(component, dict)
    }
    if len(refs) != len(components):
        raise SbomError("SBOM component bom-ref values must be unique")
    root_ref = _required_string(
        metadata["component"].get("bom-ref"),
        "SBOM metadata root bom-ref",
    )
    known_refs = refs | {root_ref}
    dependency_refs: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise SbomError("SBOM dependency entries must be objects")
        dependency_ref = _required_string(dependency.get("ref"), "SBOM dependency ref")
        depends_on = dependency.get("dependsOn")
        if dependency_ref not in known_refs or not isinstance(depends_on, list):
            raise SbomError("SBOM dependency graph references unknown components")
        if dependency_ref in dependency_refs:
            raise SbomError("SBOM dependency graph contains duplicate component entries")
        if any(item not in known_refs for item in depends_on):
            raise SbomError("SBOM dependency graph contains an unknown dependency")
        dependency_refs.add(dependency_ref)
    if dependency_refs != known_refs:
        raise SbomError("SBOM dependency graph must cover every component")


def rendered_sbom(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_sbom(document: dict[str, Any], output: Path) -> None:
    _validate_sbom_document(document)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered_sbom(document), encoding="utf-8")


def check_sbom(document: dict[str, Any], output: Path) -> str | None:
    if not output.is_file():
        return f"{output}: dependency SBOM is missing"
    try:
        rendered = output.read_text(encoding="utf-8")
        existing = json.loads(rendered)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return f"{output}: dependency SBOM is malformed: {error}"
    try:
        _validate_sbom_document(existing)
    except SbomError as error:
        return f"{output}: dependency SBOM is malformed: {error}"
    if existing != document or rendered != rendered_sbom(document):
        return f"{output}: dependency SBOM is stale or non-canonical"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="Melloa repository root containing pyproject.toml and lockfiles.",
    )
    parser.add_argument(
        "--guardian-root",
        type=Path,
        default=DEFAULT_GUARDIAN_ROOT,
        help="melloa-guardian root containing go.mod and, when required, go.sum.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination CycloneDX JSON path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail unless the output is canonical and current for all lock inputs.",
    )
    args = parser.parse_args(argv)
    try:
        document = build_sbom(args.project_root, args.guardian_root)
        if args.check:
            failure = check_sbom(document, args.output)
            if failure is not None:
                print(failure, file=sys.stderr)
                return 1
        else:
            write_sbom(document, args.output)
    except (OSError, SbomError) as error:
        print(f"dependency SBOM generation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
