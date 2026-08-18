from __future__ import annotations

import json
from pathlib import Path

from tools.validate_spec import (
    is_ignored,
    validation_report_matches,
    validation_snapshot_matches,
)


def test_validation_ignores_local_test_artifacts(tmp_path: Path) -> None:
    ignored_paths = (
        ".coverage",
        "com1.txt",
        "src/melloa/__pycache__/domain.cpython-313.pyc",
        ".pytest_cache/v/cache/nodeids",
        "apps/web/node_modules/example/index.js",
        "site/index.html",
    )

    for relative in ignored_paths:
        assert is_ignored(tmp_path / relative, tmp_path)


def test_validation_keeps_release_files(tmp_path: Path) -> None:
    release_paths = (
        ".env.example",
        "README.md",
        "docs/index.md",
        "src/melloa/domain/events.py",
    )

    for relative in release_paths:
        assert not is_ignored(tmp_path / relative, tmp_path)


def test_validation_snapshot_ignores_generation_date_only(tmp_path: Path) -> None:
    snapshot = tmp_path / "validation.json"
    stored = {"generated_on": "2026-08-17", "file_count": 332, "errors": []}
    snapshot.write_text(json.dumps(stored), encoding="utf-8")

    current = {"generated_on": "2026-08-18", "file_count": 332, "errors": []}
    assert validation_snapshot_matches(snapshot, current)

    current["file_count"] = 333
    assert not validation_snapshot_matches(snapshot, current)


def test_validation_report_checks_live_package_statistics(tmp_path: Path) -> None:
    report = tmp_path / "VALIDATION.md"
    report.write_text(
        "\n".join(
            (
                "- Files inspected: **332**",
                "- Canonical Markdown files: **56**",
                "- Canonical Markdown word count: **61,437**",
                "- Mermaid blocks: **30**",
                "- Local Markdown links checked: **236**",
                "- MkDocs navigation targets checked: **50**",
                "- Primary-source anchors available: **67**",
                "- Source references found: **98**",
            )
        ),
        encoding="utf-8",
    )
    payload = {
        "file_count": 332,
        "markdown_file_count": 56,
        "markdown_word_count": 61437,
        "mermaid_block_count": 30,
        "local_link_count": 236,
        "nav_target_count": 50,
        "source_anchor_count": 67,
        "source_reference_count": 98,
    }

    assert validation_report_matches(report, payload)

    payload["file_count"] = 333
    assert not validation_report_matches(report, payload)
