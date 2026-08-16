# Self-modification, Git, and delivery architecture

## Purpose

Make software creation and system evolution a controlled, observable capability rather than a privileged exception. Melli may identify a need, implement a change, and evaluate its effects, but it must not gain the authority to rewrite the controls that bound it.

## The five classes of change

Melloa must not use the vague phrase “self-modification” for all adaptation. The control level depends on what changes.

| Class | Examples | Default V1 authority | Required evidence |
|---|---|---|---|
| Runtime learning | new memory, confidence update, intervention outcome, temporary threshold | autonomous within retention and epistemic policy | provenance, validation, correction path |
| Configuration evolution | prompt route, schedule, low-risk feature flag, notification budget | autonomous only for bounded/reversible settings; otherwise approval | typed diff, bounds, rollback value, evaluation window |
| Software evolution | application code, schema-compatible adapter, dashboard | autonomous proposal and implementation; merge/deploy according to risk | tests, replay eval, security scan, review, canary, rollback |
| Infrastructure evolution | new service, network rule, database, cloud resource | proposal only in V1; owner approves exact plan | IaC plan, cost bound, threat impact, recovery plan |
| Governance evolution | policy engine, permission grant, Guardian, identity root, approval rules | never autonomous | independent owner-controlled path and human review |

A model may recommend any class. Recommendation is not authority.

## Lifecycle

```text
need or hypothesis
  -> change proposal
  -> policy and impact classification
  -> isolated worktree/sandbox
  -> implementation
  -> deterministic tests + replay + agent evals
  -> dependency/security/license checks
  -> pull request with evidence
  -> risk-dependent review gate
  -> staging
  -> limited canary
  -> observe outcome and regressions
  -> promote, revise, or roll back
```

The proposal is a durable object containing purpose, affected goals, predicted benefit, data/permission changes, implementation plan, evaluation plan, cost ceiling, expiry/review date, and rollback procedure. “The code passed tests” does not establish that the intervention helped the owner.

## Autonomy matrix

| Change | Melli may implement? | Melli may merge? | Melli may deploy? |
|---|---:|---:|---:|
| Documentation or tests with no runtime effect | yes | yes after CI, subject to repository rules | n/a |
| Reversible internal dashboard | yes | yes after CI and policy | canary within preset resource/egress budget |
| Prompt/template update | yes | after replay/eval thresholds | canary with automatic rollback |
| New read-only capability using an already granted scope | yes | owner or policy depending sensitivity | limited canary |
| New outbound message type | yes | owner review | only after exact recipient/content policy |
| Database additive migration | yes | owner review in V1 | supervised, with backup/rehearsal |
| Destructive migration | proposal only | owner | owner-supervised |
| New public ingress, IAM, credential scope, or spend authority | proposal only | owner | owner-controlled infrastructure path |
| Guardian, policy root, audit deletion, or kill-switch change | no autonomous implementation in protected trust domain | owner-only | owner-only |

The owner may later relax gates for proven classes, but policy changes themselves remain governed.

## Development sandbox

Generated code runs in a disposable environment with:

- rootless user namespace;
- read-only base image and bounded writable scratch volume;
- no host Docker socket, home directory, SSH agent, keyring, camera network, or production database credentials;
- seccomp/AppArmor and dropped Linux capabilities;
- CPU, memory, process, disk, wall-clock, token, and cost quotas;
- default-deny egress with temporary destination-specific leases;
- synthetic or explicitly approved replay data rather than live personal data by default;
- immutable input manifest and captured output hashes.

Docker rootless mode reduces daemon and container privileges, but it is not a complete hostile-code boundary. [S21](research/primary-sources.md#S21) When generated code execution is enabled, use gVisor for an additional userspace-kernel boundary where compatible. [S22](research/primary-sources.md#S22) Firecracker microVMs are a later option for higher-risk, multi-tenant, or stronger kernel-isolation requirements; they add image, networking, startup, and operational complexity. [S56](research/primary-sources.md#S56)

## Git model

### Repositories and trust domains

- `melloa` is the main monorepo for core, capabilities, schemas, docs, policies that the autonomous plane may propose changes to, evaluations, and deployment manifests.
- `melloa-guardian` is a separate, owner-controlled repository or at minimum a separately protected trust domain. Autonomous credentials cannot push, approve, or modify its deployment.
- Personal configuration and encrypted secrets may live in a private deployment repository, distinct from the public upstream project.

### Branch and review flow

1. Create a disposable Git worktree from a pinned clean base commit.
2. Use a branch named for a durable change ID, not an opaque agent session.
3. Commit small, reviewable changes and include generated-by metadata in a trailer, without pretending the model is a legal identity.
4. Open a pull request containing proposal, risk class, data-flow change, tests/evals, cost effect, migration and rollback notes.
5. Required checks and CODEOWNERS protect sensitive paths.
6. Merge through a server-side protected branch/ruleset; the agent cannot bypass checks. GitHub rulesets can impose branch/tag protections and required workflows. [S39](research/primary-sources.md#S39)
7. Produce a versioned artifact, SBOM, checksums, and provenance record.
8. Deploy only the exact reviewed artifact digest.

Third-party GitHub Actions should be pinned to full commit SHAs; mutable tags are not a sufficient supply-chain boundary. [S63](research/primary-sources.md#S63)

## CI/CD gates

### Deterministic gates

- formatting, linting, type checking, unit tests;
- schema compatibility and migration checks;
- dependency vulnerability and license scan;
- secret scan;
- container build with non-root user and minimal base;
- software bill of materials;
- policy tests and forbidden-path checks;
- reproducible or at least traceable build metadata;
- signature/attestation verification before deployment.

SLSA provides a useful vocabulary for increasing build provenance assurance, and Sigstore/cosign can sign and verify artifacts without inventing a bespoke signing protocol. [S37](research/primary-sources.md#S37) [S38](research/primary-sources.md#S38)

### Probabilistic gates

- replay of representative historical event traces;
- prompt/model regression suite;
- adversarial prompt-injection cases;
- expected tool-call and policy-decision comparisons;
- cost, latency, and proactivity-budget deltas;
- multiple stochastic runs with distributions rather than a single pass/fail sample;
- manual inspection of a small redacted sample for high-impact changes.

A probabilistic gate may block promotion, but it cannot replace deterministic authorization.

## Deployment and rollback

- Staging uses a scrubbed/replayed dataset and separate credentials.
- Canary targets one bounded workflow, plugin, or percentage of eligible events—not the whole system.
- Promotion is based on predeclared success and guardrail metrics.
- Automatic rollback triggers include policy-denial spikes, action error rate, cost/latency ceiling, notification excess, malformed output, or owner emergency stop.
- Retain the previous image and configuration.
- Database changes use expand/migrate/contract. Code rollback is never assumed to reverse a destructive migration.
- Every rollout has an expiry/review task; experiments do not silently become permanent infrastructure.

## Architecture-change discipline

A change that alters trust boundaries, durable schemas, primary stores, public interfaces, or operational ownership requires an ADR. The agent may draft the ADR and competing alternatives. The owner approves decisions that alter governance or irreversible architecture.

## Failure modes

- **Generated tests fit the implementation rather than the requirement:** independent replay/evaluation and owner-visible acceptance criteria.
- **Sandbox escape:** no production credentials or host control, gVisor for hostile workloads, rapid Guardian shutdown, patched runtime.
- **Dependency substitution or malicious package:** lockfiles, private allowlist where useful, provenance, SBOM, network restriction, review new dependencies.
- **CI compromise:** pinned actions, least-privilege tokens, protected environments, artifact signature verification.
- **Canary has no representative data:** explicit eligibility and minimum sample threshold; do not infer success from silence.
- **Rollback fails after schema change:** rehearse migration, snapshot first, expand/contract pattern, restore procedure.
- **Agent optimizes for passing its own evals:** independently maintained guardrails and owner feedback; periodically refresh hidden test cases.

## Build now

- Durable change proposal schema and risk classification.
- Protected Git flow, CODEOWNERS, required checks, pinned CI actions.
- Deterministic test/eval manifest and artifact digest deployment.
- Staging and rollback for ordinary application changes.
- Explicit prohibition on autonomous Guardian/governance/IAM changes.

## Design for

- gVisor-backed generated-code runner, signed artifacts, SBOMs, canary controller, and replay-driven promotion.
- Provider-neutral coding-agent adapter.
- A capability for generating software that receives narrowly scoped build/test resources, not host administration.

## Defer

- Fully autonomous merge/deployment of high-impact changes, Firecracker fleet, production cloud resource creation, autonomous dependency upgrades without evidence, and any agent path to modify the Guardian.
