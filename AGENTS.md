# Melloa implementation instructions

## Authority

The architecture suite in this repository is the implementation authority. Read it before making architectural changes. Where documents conflict, use this precedence order:

1. `docs/23-v0.2-decisions.md`
2. accepted ADRs in `docs/adr/`
3. `docs/22-final-synthesis.md` and the relevant subsystem specification
4. the retained master research brief

Record any deliberate architectural deviation as a new ADR rather than silently changing a boundary.

## Required boundaries

- Melloa is the system; Melli is a persistent intelligence, not a model, process, client, or service name.
- The private Owner Console and channel-neutral conversation are V1 requirements. Telegram is an optional secondary adapter.
- Models may propose actions but deterministic policy and capability controls authorize them.
- The Guardian is independently controlled. This repository may define its protocol and fakes, but must not weaken or absorb the Guardian trust boundary.
- Preserve provenance, uncertainty, correction history, structured decision records, data ownership, private networking, least privilege, and reversible deployment.
- Never commit credentials, personal data, corporate-only dependencies, machine-specific secrets, or plaintext deployment state.

## Working method

Implement the milestones in `docs/22-final-synthesis.md` in small, reviewable increments. Keep the repository runnable, tested, documented, and reproducible from a clean Linux environment. Use synthetic data and fake adapters until an integration milestone explicitly requires real hardware or credentials.

For each material change, update tests and the relevant documentation. Prefer the simplest design that preserves the documented long-term boundaries. Continue autonomously when the documents answer the question; stop only for a genuinely missing external credential, hardware dependency, permission, or owner policy decision.
