# Contributing

Read `AGENTS.md`, `docs/23-v0.2-decisions.md`, the relevant accepted ADRs, and `docs/24-m0-implementation.md` before changing architecture or runtime boundaries.

## Local checks

```bash
make bootstrap
make check
make integration
make recovery
```

The last two commands require Docker and use only synthetic data. No credential or personal deployment repository is required.

## Change discipline

- Keep domain state, provider adapters, clients, and the Guardian distinct.
- Add or update tests for every behavior change.
- Update schemas, migration manifests, runbooks, and diagrams with their implementation.
- Record trust-boundary, durable-store, public-contract, or operational-ownership changes in an ADR.
- Use additive migrations and never edit a migration after release.
- Do not commit credentials, personal data, host inventories, plaintext deployment state, or external tool output containing them.
- Keep actions pinned by full digest or commit in deployment and CI files.

Pull requests should describe risk class, data-flow changes, tests/evaluations, cost effect, migration implications, and rollback.
