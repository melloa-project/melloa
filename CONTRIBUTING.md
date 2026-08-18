# Contributing

> **Contribution intake is paused:** this repository does not yet contain a public source license. Do not submit external code until the repository owner has added explicit license and contribution terms.

Current project-owned changes should follow [AGENTS.md](AGENTS.md) and the [pre-release compatibility process](docs/compatibility.md). These rules do not open outside contribution intake.

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

Project changes should describe risk class, data-flow changes, tests/evaluations, cost effect, migration implications, and rollback.
