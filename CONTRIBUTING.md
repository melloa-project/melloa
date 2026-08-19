# Contributing

Melloa is not currently accepting outside contributions and has no public source license. This file
documents the expected change discipline for owner-authorized work.

Read [PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md), [AGENTS.md](AGENTS.md), and
[trust boundaries](docs/trust-boundaries.md) first. Old architecture documents, milestones, release
evidence, code, and tests are not a roadmap.

For a material change:

1. state what the owner can experience, accomplish, understand, or stop worrying about afterward;
2. remove concepts and paths that no longer earn their complexity;
3. preserve hard boundaries through the simplest concrete implementation;
4. exercise the real owner journey, including rendered desktop and mobile behavior when relevant;
5. use independent adversarial reviewers at major experience checkpoints;
6. update only current documentation and focused tests.

Run the checks proportionate to the change:

```bash
make check
make integration  # PostgreSQL changes
make recovery     # recovery-critical state changes
```

Never add credentials, personal data, private deployment state, machine-specific paths, or
Guardian authority to this repository.
