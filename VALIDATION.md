# Validation report — Melloa v0.2 current implementation

**Generated:** 2026-08-18

**Validated root:** `.`

## Result

All current automated architecture checks, deterministic core and web gates, PostgreSQL integration tests, Guardian checks, authenticated browser smoke, owner-export validation, and encrypted clean-restore acceptance gates passed. This is implementation evidence for the synthetic/local preview, not a production-readiness or personal-data deployment claim.

## Package statistics

- Files inspected: **352**
- Canonical Markdown files: **62**
- Canonical Markdown word count: **69,574**
- Mermaid blocks: **32**
- Local Markdown links checked: **248**
- MkDocs navigation targets checked: **54**
- Primary-source anchors available: **67**
- Source references found: **92**

## Architecture checks

- PASS — `balanced_markdown_fences`
- PASS — `no_placeholder_markers`
- PASS — `local_links_and_fragments_resolve`
- PASS — `mkdocs_nav_targets_exist`
- PASS — `mermaid_blocks_structurally_valid`
- PASS — `source_references_have_anchors`
- PASS — `master_brief_hash_matches`
- PASS — `quantitative_sanity_checks`

## Implementation acceptance gates

| Gate | Result |
|---|---|
| Python quality | PASS — Ruff, strict mypy across 83 source files, and 557 unit tests with 90.35% branch-aware coverage |
| Generated contracts | PASS — JSON Schemas and the ten-version migration digest manifest match their sources; release manifest matches a clean Git export |
| Owner Console | PASS — TypeScript check, 158 Vitest tests across 13 files, production build, and authenticated Playwright desktop/mobile journey |
| Owner journey | PASS — the canonical launcher creates signed offline Guardian state, starts the private core and production console, reports its contract and next action, then covers login, canonical conversation, synthetic route/provenance inspection, activity, memory inspection, owner ZIP export, audit timeline, retention/provider/settings views, responsive navigation, and verified cleanup |
| PostgreSQL | PASS — all ten migrations applied with none pending; 17 restart, role, idempotency, conversation, memory, delivery, Telegram-state, audit, and session integration tests passed |
| Owner export | PASS — canonical export and dry-run import validation; AES-256-GCM/Scrypt package encryption and decrypt-validate round trip |
| Recovery | PASS — all ten migrations, authenticated conversation/explanation/model evidence, memory correction/deletion, durable sessions/audit, encrypted restic integrity, clean PostgreSQL restore, post-restore owner API traversal, denied read-only mutation, and verified cleanup with a bounded receipt |
| Guardian | PASS — Go formatting, vet, tests, reproducible-path build, deterministic transition journal, and signed `stopped` → `offline` projection consumed read-only by Melloa |
| Documentation | PASS — strict MkDocs build and architecture validator |

The Docker acceptance gates used the exact digest-pinned pgvector/PostgreSQL and restic image contents declared by the repository. Where the local Docker daemon could not reach Docker Hub through the host proxy, those exact remote digests were verified and imported before running the unchanged harnesses.

## Master research brief integrity

- Expected SHA-256: `a59d29c06c884f86064e5223e92f3b996771ca1d34bc5fc7baaea18e0c3abcd9`
- Actual SHA-256: `a59d29c06c884f86064e5223e92f3b996771ca1d34bc5fc7baaea18e0c3abcd9`

The original supplied research brief remains byte-for-byte unchanged.

## Errors

- None in the executed gates.

## Remaining checks and decisions

- A public source license still requires an explicit repository-owner decision. Until then, the public code is readable but reuse, redistribution, and outside contributions are not authorized.
- Browser-executed Mermaid rendering was not exercised by the static MkDocs build.
- External documentation URLs are not network-probed by the architecture validator.
- Real Ollama, Codex subscription, Telegram Bot API, camera, private-network, host Guardian controls, and owner deployment overlays were not exercised by this no-network acceptance run.
- Production backup schedules, offsite recovery-key custody, private host recovery, and personal-data operation remain deployment work and cannot be inferred from synthetic clean-restore evidence.
