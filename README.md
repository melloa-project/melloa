# Melloa

Melloa is the private, owner-controlled home of Melli: a persistent AI partner designed to know one
person better through time, remember useful history, follow through, and remain continuous when the
underlying model changes.

## Current status

Melloa is in an owner-experience reset. The existing `v0.2.0` preview proves private conversation,
model disclosure, owner-data controls, and an independent Guardian boundary, but it is not yet a
compelling daily-use partner. Without an explicitly configured model, conversation is unavailable;
the preview no longer substitutes a fixture response for Melli thinking.

The active work is subtractive: collapse the operations-console experience, remove speculative
architecture and preview machinery, and make conversation with Melli the unmistakable product.
There is no milestone implementation queue and no compatibility promise for preview behavior.

Read [the current product direction](PRODUCT_DIRECTION.md) before treating any existing code or test
as a requirement.

## Run the current baseline

The baseline requires Linux or macOS, Bash, Python 3.13+, uv 0.12.0, Node.js 22+, Go 1.24+, and the
Guardian repository beside this one:

```bash
git clone https://github.com/melloa-project/melloa.git
git clone https://github.com/melloa-project/melloa-guardian.git
cd melloa
make preview
```

The command builds the independently controlled Guardian, starts both services on loopback, prints
a disposable owner credential, and removes its temporary state on `Ctrl-C`. Follow
[the short baseline guide](docs/getting-started.md) for the honest limits of this path.

To exercise the one configured on-device model:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
make preview PREVIEW_MODEL=ollama
```

This remains disposable and is not the target owner experience.

## What must remain true

- Melloa is the system; Melli is the persistent intelligence, not a model or process.
- Guardian stays independently owner-controlled and outside Melloa's authority.
- Owner data is private by default and remains under owner control.
- Models cannot authorize their own external effects.
- Sensitive external disclosure is explicit.
- High-risk and irreversible actions fail closed behind deterministic constraints.

The concise, implementation-independent rules are in
[trust boundaries](docs/trust-boundaries.md).

## Work on Melloa

```bash
make bootstrap
make check
```

PostgreSQL and recovery checks additionally require Docker:

```bash
make integration
make recovery
```

See [development](docs/development.md). Product changes must be exercised as an actual owner journey
on desktop and mobile; passing fixture and contract tests is not product validation.

## Source status

No public source license has been selected. The repository may be readable, but reuse,
redistribution, and outside contributions require explicit license terms from the owner.
