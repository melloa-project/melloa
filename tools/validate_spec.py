#!/usr/bin/env python3
"""Standard-library structural validation for the Melloa specification suite."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CUSTOM_ANCHOR_RE = re.compile(r'<a\s+id=["\']([^"\']+)["\']\s*></a>', re.I)
SOURCE_REF_RE = re.compile(r"primary-sources\.md#(S\d{2})")
SOURCE_ANCHOR_RE = re.compile(r'<a\s+id=["\'](S\d{2})["\']\s*></a>', re.I)
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|FIXME|PLACEHOLDER)\b|lorem ipsum", re.I)
NAV_PATH_RE = re.compile(r"^\s*-\s+[^:]+:\s+([^#][^\s]+\.md)\s*$")
MERMAID_STARTS = {
    "flowchart", "graph", "sequenceDiagram", "stateDiagram", "stateDiagram-v2",
    "classDiagram", "erDiagram", "journey", "gantt", "timeline", "mindmap",
    "quadrantChart", "requirementDiagram", "C4Context", "C4Container",
    "C4Component", "C4Dynamic", "C4Deployment", "architecture-beta", "xychart-beta",
}
IGNORED_DIRECTORY_NAMES = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "dist",
    "htmlcov",
    "node_modules",
    "site",
}

@dataclass
class ValidationResult:
    generated_on: str
    root: str
    file_count: int
    markdown_file_count: int
    markdown_word_count: int
    mermaid_block_count: int
    source_reference_count: int
    source_anchor_count: int
    source_ids_used: list[str]
    source_ids_available: list[str]
    nav_target_count: int
    local_link_count: int
    master_brief_sha256: str
    expected_master_brief_sha256: str
    checks: dict[str, bool]
    errors: list[str]
    warnings: list[str]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def slugify_heading(text: str) -> str:
    text = re.sub(r"\s+#+\s*$", "", text.strip()).lower()
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"[^\w\-\s]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s\-]+", "-", text).strip("-")
    return text


def anchors_for_markdown(text: str) -> set[str]:
    anchors = set(CUSTOM_ANCHOR_RE.findall(text))
    counts: Counter[str] = Counter()
    in_fence = False
    fence = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            mark = stripped[:3]
            if not in_fence:
                in_fence, fence = True, mark
            elif mark == fence:
                in_fence, fence = False, ""
            continue
        if in_fence:
            continue
        m = HEADING_RE.match(line)
        if not m:
            continue
        base = slugify_heading(m.group(2))
        if not base:
            continue
        n = counts[base]
        anchors.add(base if n == 0 else f"{base}_{n}")
        counts[base] += 1
    return anchors


def is_ignored(path: Path, root: Path) -> bool:
    return any(part in IGNORED_DIRECTORY_NAMES for part in path.relative_to(root).parts)


def markdown_files(root: Path) -> list[Path]:
    generated = {root / "CONSOLIDATED.md", root / "VALIDATION.md"}
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file() and path not in generated and not is_ignored(path, root)
    )


def iter_mermaid_blocks(text: str) -> Iterable[str]:
    pattern = re.compile(r"```mermaid\s*\n(.*?)\n```", re.S)
    yield from (m.group(1) for m in pattern.finditer(text))


def resolve_link(source: Path, target: str) -> tuple[Path | None, str | None]:
    target = target.strip()
    if not target or target.startswith(("http://", "https://", "mailto:", "tel:")):
        return None, None
    if target.startswith("#"):
        return source, target[1:]
    path_part, sep, fragment = target.partition("#")
    target_path = (source.parent / path_part).resolve()
    return target_path, fragment if sep else None


def validate(root: Path, expected_hash: str) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    mdfiles = markdown_files(root)
    allfiles = sorted(
        path for path in root.rglob("*") if path.is_file() and not is_ignored(path, root)
    )
    texts = {p: p.read_text(encoding="utf-8", errors="replace") for p in mdfiles}
    anchor_cache = {p.resolve(): anchors_for_markdown(t) for p, t in texts.items()}

    # Code fences and placeholders.
    fence_ok = True
    placeholders_ok = True
    for p, text in texts.items():
        fence_count = sum(1 for line in text.splitlines() if line.lstrip().startswith("```"))
        if fence_count % 2:
            fence_ok = False
            errors.append(f"Unbalanced triple-backtick fences: {p.relative_to(root)}")
        if PLACEHOLDER_RE.search(text):
            placeholders_ok = False
            errors.append(f"Placeholder marker found: {p.relative_to(root)}")

    # Local links and fragments.
    local_link_count = 0
    local_links_ok = True
    for p, text in texts.items():
        for raw in LINK_RE.findall(text):
            resolved, fragment = resolve_link(p, raw)
            if resolved is None:
                continue
            local_link_count += 1
            if not resolved.exists():
                local_links_ok = False
                errors.append(f"Missing local link target in {p.relative_to(root)}: {raw}")
                continue
            if fragment and resolved.suffix.lower() == ".md":
                anchors = anchor_cache.get(resolved)
                if anchors is None:
                    anchors = anchors_for_markdown(resolved.read_text(encoding="utf-8", errors="replace"))
                    anchor_cache[resolved] = anchors
                if fragment not in anchors:
                    local_links_ok = False
                    errors.append(f"Missing fragment in {p.relative_to(root)}: {raw}")

    # MkDocs nav targets (simple, deterministic extraction).
    nav_ok = True
    nav_paths: list[str] = []
    mkdocs = root / "mkdocs.yml"
    for line in mkdocs.read_text(encoding="utf-8").splitlines():
        m = NAV_PATH_RE.match(line)
        if not m:
            continue
        rel = m.group(1)
        nav_paths.append(rel)
        if not (root / "docs" / rel).exists():
            nav_ok = False
            errors.append(f"Missing MkDocs nav target: {rel}")

    # Mermaid structure.
    mermaid_blocks: list[tuple[Path, str]] = []
    for p, text in texts.items():
        mermaid_blocks.extend((p, block) for block in iter_mermaid_blocks(text))
    mermaid_ok = True
    for idx, (p, block) in enumerate(mermaid_blocks, 1):
        lines = [line.strip() for line in block.splitlines() if line.strip() and not line.strip().startswith("%%")]
        if not lines:
            mermaid_ok = False
            errors.append(f"Empty Mermaid block #{idx} in {p.relative_to(root)}")
            continue
        first = lines[0].split()[0]
        if first not in MERMAID_STARTS:
            mermaid_ok = False
            errors.append(f"Unknown Mermaid directive '{first}' in {p.relative_to(root)} block #{idx}")
        if "-." in block and ".x->" in block:
            mermaid_ok = False
            errors.append(f"Known-invalid Mermaid cross-edge syntax in {p.relative_to(root)} block #{idx}")

    # Source references and anchors.
    all_text = "\n".join(texts.values())
    used = sorted(set(SOURCE_REF_RE.findall(all_text)))
    source_file = root / "docs" / "research" / "primary-sources.md"
    source_text = source_file.read_text(encoding="utf-8")
    available = sorted(set(SOURCE_ANCHOR_RE.findall(source_text)))
    missing_sources = sorted(set(used) - set(available))
    sources_ok = not missing_sources
    if missing_sources:
        errors.append("Missing source anchors: " + ", ".join(missing_sources))

    brief = root / "docs" / "research" / "master-research-brief.txt"
    actual_hash = sha256(brief)
    hash_ok = actual_hash == expected_hash
    if not hash_ok:
        errors.append(f"Master brief hash mismatch: {actual_hash}")

    # Quantitative sanity checks reproduced from the specification.
    # decimal GB: bitrate(Mbit/s) * seconds / 8 / 1000
    raw_2mbps_daily_gb = 2 * 86400 / 8 / 1000
    event_monthly_gb = 100 * 15 * 2 / 8 / 1000 * 30
    electricity_15w = 0.015 * 24 * 30 * 0.2611
    quantitative_ok = (
        abs(raw_2mbps_daily_gb - 21.6) < 1e-9
        and abs(event_monthly_gb - 11.25) < 1e-9
        and abs(electricity_15w - 2.81988) < 1e-5
    )
    if not quantitative_ok:
        errors.append("Quantitative sanity check failed")

    word_count = sum(len(re.findall(r"\b\w[\w’'\-]*\b", text, re.UNICODE)) for text in texts.values())
    checks = {
        "balanced_markdown_fences": fence_ok,
        "no_placeholder_markers": placeholders_ok,
        "local_links_and_fragments_resolve": local_links_ok,
        "mkdocs_nav_targets_exist": nav_ok,
        "mermaid_blocks_structurally_valid": mermaid_ok,
        "source_references_have_anchors": sources_ok,
        "master_brief_hash_matches": hash_ok,
        "quantitative_sanity_checks": quantitative_ok,
    }
    if all(checks.values()):
        warnings.append("Full MkDocs/JavaScript Mermaid rendering was not executed in this environment; run it in CI before publication.")
        warnings.append("External URLs were researched but are not network-probed by this local validator.")

    return ValidationResult(
        generated_on=str(date.today()),
        root=".",
        file_count=len(allfiles),
        markdown_file_count=len(mdfiles),
        markdown_word_count=word_count,
        mermaid_block_count=len(mermaid_blocks),
        source_reference_count=sum(len(SOURCE_REF_RE.findall(t)) for t in texts.values()),
        source_anchor_count=len(available),
        source_ids_used=used,
        source_ids_available=available,
        nav_target_count=len(nav_paths),
        local_link_count=local_link_count,
        master_brief_sha256=actual_hash,
        expected_master_brief_sha256=expected_hash,
        checks=checks,
        errors=errors,
        warnings=warnings,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    args = parser.parse_args()
    expected = "a59d29c06c884f86064e5223e92f3b996771ca1d34bc5fc7baaea18e0c3abcd9"
    result = validate(args.root.resolve(), expected)
    payload = asdict(result)
    if args.json_path:
        args.json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if not result.errors and all(result.checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
