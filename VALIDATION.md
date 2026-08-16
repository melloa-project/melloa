# Validation report — Melloa v0.2 and M0

**Generated:** 2026-08-16  
**Validated root:** `.`

## Result

All automated architecture checks and synthetic M0 acceptance gates passed. This is implementation evidence, not a production-readiness claim.

## Package statistics

- Files inspected: **186**
- Canonical Markdown files: **53**
- Canonical Markdown word count: **44,947**
- Mermaid blocks: **30**
- Local Markdown links checked: **200**
- MkDocs navigation targets checked: **48**
- Primary-source anchors available: **67**
- Source references found: **98**

## Checks

- PASS — `balanced_markdown_fences`
- PASS — `no_placeholder_markers`
- PASS — `local_links_and_fragments_resolve`
- PASS — `mkdocs_nav_targets_exist`
- PASS — `mermaid_blocks_structurally_valid`
- PASS — `source_references_have_anchors`
- PASS — `master_brief_hash_matches`
- PASS — `quantitative_sanity_checks`

## M0 acceptance gates

| Gate | Result |
|---|---|
| Python quality | PASS — Ruff, strict mypy, and 46 unit tests with 91.65% branch-aware coverage |
| Generated contracts | PASS — JSON Schemas and migration digest manifest match their sources |
| Owner Console | PASS — TypeScript check, three Node tests, and static build |
| PostgreSQL | PASS — PostgreSQL 18 migration apply/check and four integration tests |
| Recovery | PASS — encrypted restic repository scan, integrity check, clean restore, and denied read-only mutation |
| Guardian | PASS — Go formatting, vet, tests, build, deterministic transition journal, and signed projection |
| Guardian interoperability | PASS — Melloa independently verified stopped and offline Ed25519 projections and their receipt chain |
| Documentation | PASS — strict MkDocs build and architecture validator |

## Master research brief integrity

- Expected SHA-256: `a59d29c06c884f86064e5223e92f3b996771ca1d34bc5fc7baaea18e0c3abcd9`
- Actual SHA-256: `a59d29c06c884f86064e5223e92f3b996771ca1d34bc5fc7baaea18e0c3abcd9`

The original supplied research brief remains byte-for-byte unchanged.

## Errors

- None

## Remaining checks and decisions

- Browser-executed JavaScript Mermaid rendering was not exercised by the static MkDocs build.
- External URLs were researched but are not network-probed by this local validator.
- A source license must be owner-selected before accepting external code or publishing a release.
- Real console authentication, host recovery, and Guardian deployment remain owner-reviewed M1/deployment work.
