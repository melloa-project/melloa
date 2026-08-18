# Preview compatibility and release process

Melloa `v0.2.0` is an owner-facing preview before a first stable implementation release. The exact prerelease tag and the latest green `main` revision are evaluated evidence snapshots, and no public source license has been selected. The project does not offer a stable public API, plugin SDK, database migration, export/import, deployment, or backward-compatibility guarantee.

## Current compatibility posture

- Source readability is not a reuse grant; outside contributions and redistribution remain unauthorized until explicit license terms are added.
- The current MVP is a preview, not a production deployment target.
- JSON Schemas, API routes, CLI commands, PostgreSQL migrations, export bundle layout, Owner Console contracts, and Guardian status consumption may change before a stable release.
- Released SQL migrations are immutable once published, but pre-release additive migrations may still be superseded by later migration or import tooling before stable compatibility is declared.
- Current export validation proves the checked-in preview bundle shape and checksums; it is not a backup, restore, or long-term archive promise.
- Compatibility evidence is tied to documented checks, generated manifests, changelog entries, and validation outputs at the tested revision.

## Versioning and supported revisions

Before 1.0, package versions, document versions, and tags identify evidence snapshots; they do not promise semantic-versioning compatibility or a maintenance window. The `v0.2.0` tag identifies the reviewed M1 preview snapshot on architecture baseline `v0.2`. Earlier commits and prerelease tags have no backport, security-update, or operational-support guarantee.

Do not silently change the meaning of an existing machine-readable contract, schema, export format, or migration. Give an incompatible shape a new version, preserve published SQL migrations unchanged, and provide migration or reset guidance. A tag does not create a support promise unless the owner publishes an explicit supported-version table and end date. Security reports for the evaluated revision follow the repository-root `SECURITY.md` policy.

## Change classification

Project changes should identify their compatibility class before merge or release:

- **Patch-compatible:** fixes behavior without changing public schemas, persisted shape, CLI/API contracts, docs promises, or owner workflows.
- **Additive:** adds a route, field, schema, migration, view, command, or document while preserving existing preview behavior.
- **Behavior-changing:** changes owner-visible behavior, policy decisions, audit evidence, retention, export shape, model routing, delivery semantics, or error handling.
- **Breaking:** requires data migration, changes a public contract, removes or renames fields/routes/commands, invalidates previous export validation, changes Guardian interpretation, or changes documented operational steps.

Breaking changes are allowed during the pre-release phase only when they are explicit, reviewed, and paired with migration or reset guidance appropriate to the affected data.

## Required evidence

For a compatibility-relevant change, update the narrowest accurate set of:

- `CHANGELOG.md` for owner-visible behavior and release notes;
- the relevant implementation or operations document for changed workflows and limitations;
- generated schemas, migration manifests, and validation evidence when contracts or migrations change;
- tests or replay fixtures that prove the intended old and new behavior;
- an ADR when a trust boundary, durable format, compatibility promise, or operational ownership changes.

When a change affects stored data, export records, policy decisions, audit records, or Guardian status interpretation, document the rollback or recovery path. If rollback is intentionally unsupported, say so directly and preserve enough evidence for inspection.

For a candidate evidence snapshot, run the repository gates from a clean checkout when practical:

```bash
make bootstrap
make check
make integration
make recovery
```

Record the exact revision, environment, commands, and failures. A skipped or environment-blocked gate is not a pass, and the synthetic recovery drill is not production backup evidence. Additional affected-surface checks remain required; passing these commands does not imply deployment support or production readiness.

## Stable-release gate

Before describing a release as stable or accepting outside contributions, the owner must:

- select and publish source license terms;
- define supported versions and security-reporting expectations;
- publish signed or checksummed release artifacts;
- document schema/API/export compatibility guarantees and breakage policy;
- prove migration, backup/restore, and import behavior against representative data;
- record known unsupported surfaces and production-readiness limits.

Until those gates are met, use `preview`, `current MVP`, or `pre-release` language for owner-facing artifacts and avoid implying a compatibility guarantee.
