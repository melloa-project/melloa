#!/usr/bin/env python3
"""Build the single-file reading edition from the canonical modular Markdown suite."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUTPUT = ROOT / "CONSOLIDATED.md"

ORDER = [
    DOCS / "index.md",
    DOCS / "23-v0.2-decisions.md",
    DOCS / "00-traceability.md",
    *[DOCS / f"{i:02d}-{name}.md" for i, name in [
        (1, "executive-vision"),
        (2, "design-principles-requirements"),
        (3, "conceptual-model"),
        (4, "alternative-architectures"),
        (5, "chosen-v1-architecture"),
        (6, "events-memory-data"),
        (7, "agents-models-goals"),
        (8, "capabilities-policy-autonomy"),
        (9, "security-threat-injection"),
        (10, "secrets-control-kill-switch"),
        (11, "camera-perception-hardware"),
        (12, "telegram-clients"),
        (13, "self-modification-git-ci"),
        (14, "deployment-networking-infrastructure"),
        (15, "observability-reliability-dr"),
        (16, "privacy-retention-export-cost"),
        (17, "testing-evaluation-simulation"),
        (18, "repository-languages-docs-dx"),
        (19, "onboarding-runbooks-roadmap"),
        (20, "risk-register"),
        (21, "reviewers-open-questions-rejected"),
        (22, "final-synthesis"),
    ]],
    DOCS / "diagrams.md",
    DOCS / "adr" / "index.md",
    *sorted((DOCS / "adr").glob("ADR-*.md")),
    DOCS / "research" / "method-and-limitations.md",
    DOCS / "research" / "primary-sources.md",
]

LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})(\s+.*)$")


def doc_anchor(path: Path) -> str:
    rel = path.relative_to(DOCS).with_suffix("")
    return "doc-" + re.sub(r"[^a-z0-9]+", "-", str(rel).lower()).strip("-")


ANCHORS = {p.resolve(): doc_anchor(p) for p in ORDER}
BRIEF = (DOCS / "research" / "master-research-brief.txt").resolve()


def rewrite_link(source: Path, label: str, raw_target: str) -> str:
    target = raw_target.strip()
    if not target or target.startswith(("http://", "https://", "mailto:", "tel:")):
        return f"[{label}]({raw_target})"
    if target.startswith("#"):
        return f"[{label}]({target})"
    path_part, sep, fragment = target.partition("#")
    resolved = (source.parent / path_part).resolve()
    if resolved == BRIEF:
        return f"[{label}](docs/research/master-research-brief.txt)"
    if resolved in ANCHORS:
        destination = f"#{fragment}" if sep and fragment else f"#{ANCHORS[resolved]}"
        return f"[{label}]({destination})"
    # Preserve paths that intentionally point outside the canonical document set.
    return f"[{label}]({raw_target})"


def transform(source: Path, text: str) -> str:
    out: list[str] = []
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
            out.append(line)
            continue
        if not in_fence:
            m = HEADING_RE.match(line)
            if m:
                hashes, rest = m.groups()
                line = (hashes + "#" if len(hashes) < 6 else hashes) + rest
            line = LINK_RE.sub(lambda m: rewrite_link(source, m.group(1), m.group(2)), line)
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def title_for(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").title()


def main() -> None:
    missing = [p for p in ORDER if not p.exists()]
    if missing:
        raise SystemExit("Missing source files: " + ", ".join(map(str, missing)))

    contents = [
        "# Melloa Architecture Specification v0.2 — Consolidated Edition",
        "",
        "**Original research date:** 15 August 2026  ",
        "**Decision update:** 16 August 2026  ",
        "**Status:** Recommended architecture and research baseline; not production implementation  ",
        "**Canonical form:** The modular Markdown suite in `melloa-architecture-spec-v0.2/`; this file is a generated reading edition.",
        "",
        "The supplied master research brief is preserved verbatim in the packaged suite. The v0.2 adopted decisions are authoritative where they intentionally supersede v0.1 product-priority wording. Contemporary facts, provider policies, prices, and named technologies are dated research snapshots and must be revalidated at implementation time.",
        "",
        "## Contents",
        "",
    ]
    for path in ORDER:
        contents.append(f"- [{title_for(path)}](#{ANCHORS[path.resolve()]})")
    contents.extend(["", "---", ""])

    for idx, path in enumerate(ORDER):
        contents.append(f'<a id="{ANCHORS[path.resolve()]}"></a>')
        contents.append("")
        contents.append(transform(path, path.read_text(encoding="utf-8", errors="replace")).rstrip())
        if idx != len(ORDER) - 1:
            contents.extend(["", "---", ""])

    OUTPUT.write_text("\n".join(contents).rstrip() + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
