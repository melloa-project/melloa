# Development

## Start with the owner journey

Read [product direction](../PRODUCT_DIRECTION.md) and
[trust boundaries](trust-boundaries.md). Existing behavior and tests are changeable. Explain a
material change as an owner-visible before/after and prefer subtraction while the reset checkpoint is
open.

For UI work, inspect the running interface at desktop and mobile widths. Component tests alone do not
establish product quality. For intelligence work after the reset, use capable real models and real
longitudinal conversations; fixtures establish mechanics only.

## Toolchain

- Python 3.13+ with dependencies locked in `uv.lock`
- uv 0.12.0
- Node.js 22 with the committed npm lock
- Docker for PostgreSQL integration and recovery checks
- Go 1.24+ only when the owner prepares a handoff in the separate Guardian repository

No model key, Telegram token, personal data, or private deployment repository is needed for local
verification. Put any local secret file outside the checkout with mode `0600`; never put secret
values in `.env`, command arguments, fixtures, or logs.

## Commands

```bash
make bootstrap       # install locked Python and web dependencies
make check           # migration manifest, lint, types, unit tests, and web build/tests
make integration     # PostgreSQL integration; requires Docker
make recovery        # encrypted clean-restore exercise; requires Docker
make preview         # requires owner-supplied GUARDIAN_STATUS and GUARDIAN_PUBLIC_KEY
```

The preview target verifies those two public Guardian inputs. It does not receive the Guardian
checkout, build or invoke `guardianctl`, choose private state paths, or remove Guardian state. Follow
[getting started](getting-started.md) for the disposable owner handoff.

Use the narrowest relevant checks while iterating, then run the complete affected gate. A green old
test is not a reason to retain rejected behavior; delete or rewrite it when product semantics change.

## Change discipline

- Keep Guardian read-only from this repository. Changes to its code or owner control path require a
  separately bounded task and review.
- Keep high-risk authorization, external disclosure, owner-data control, and recovery failures
  fail-closed.
- Prefer concrete code over ports, schemas, and adapters for hypothetical variants.
- Delete obsolete docs, tests, fixtures, and configuration with the behavior they supported. Git
  history is the archive.
- Do not regenerate broad evidence artifacts merely to make a diff look complete.
- Preserve unrelated owner changes in the worktree.

## Product evidence

Record real failures in owner language: forgotten context, repeated questions, bad interruptions,
missed connections, useless correctness, or a surprisingly valuable use of history. Prioritize those
observations over infrastructure completeness and test counts.
