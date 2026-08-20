from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS_SITE = ROOT / "docs-site"


def test_public_site_source_replaces_stale_preview_framing() -> None:
    homepage = (DOCS_SITE / "index.html").read_text(encoding="utf-8")

    assert "not ready for first owner deployment" in homepage
    assert "dedicated server" in homepage
    assert "Telegram owner chat" in homepage
    assert "Hosted model routes" in homepage
    assert "Bounded self-change" in homepage
    assert "local GPU or local model is not required" in homepage
    assert "old MkDocs architecture site was stale" in homepage

    stale_claims = [
        "v0.2.0 preview",
        "milestone M1",
        "architecture baseline",
        "Current release",
        "Start Melloa locally",
    ]
    for claim in stale_claims:
        assert claim not in homepage


def test_public_site_is_static_pages_source_not_mkdocs() -> None:
    workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")

    assert "path: docs-site" in workflow
    assert "mkdocs" not in workflow.lower()
    assert (DOCS_SITE / ".nojekyll").is_file()
    assert (DOCS_SITE / "404.html").is_file()
