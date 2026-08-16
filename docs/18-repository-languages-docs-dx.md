# Repository architecture, language choices, documentation, and developer experience

## Purpose

Keep one engineer able to understand and evolve Melloa years later, while making the open-source system reproducible and contribution-friendly from the beginning.

## Repository strategy

Use three repositories with explicit trust roles: the **Melloa application monorepo**, the separately protected **Guardian repository**, and the owner-private **deployment/configuration repository**.

- A monorepo makes cross-cutting schema, policy, capability, replay, documentation, and migration changes reviewable as one commit.
- Separate deployable processes can still come from one codebase.
- The Guardian is separated because repository write authority is a security boundary, not because polyrepos are inherently cleaner.
- A private deployment/config repository holds personal environment values and SOPS-encrypted secrets; the public repository contains safe examples.

## Concrete layout

```text
melloa/
├── apps/
│   ├── core/                 # owner API, application orchestration
│   ├── worker/               # jobs, reflection, retention, indexing
│   ├── cli/                  # owner/developer commands
│   └── web/                  # mandatory private Owner Console
├── domain/
│   ├── identity/
│   ├── events/
│   ├── memory/
│   ├── goals/
│   ├── policy/
│   ├── actions/
│   ├── interventions/
│   └── changes/
├── application/              # use cases; depends on domain and ports
├── ports/                    # model, store, capability, clock, audit contracts
├── adapters/
│   ├── postgres/
│   ├── filesystem/
│   ├── models/
│   ├── telegram/
│   ├── camera/
│   └── observability/
├── capabilities/
│   ├── sdk/
│   ├── telegram/
│   ├── camera/
│   └── examples/
├── schemas/
│   ├── events/
│   ├── capabilities/
│   ├── actions/
│   ├── exports/
│   └── compatibility/
├── policies/
│   ├── defaults/
│   ├── tests/
│   └── examples/
├── prompts/
│   ├── templates/
│   ├── schemas/
│   └── changelog/
├── evals/
│   ├── public/
│   ├── adversarial/
│   └── rubrics/
├── simulations/
│   ├── replay/
│   └── fixtures/
├── infra/
│   ├── compose/
│   ├── ansible/
│   ├── images/
│   └── opentofu/             # added only when justified
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contracts/
│   ├── security/
│   └── hardware/
├── docs/
│   ├── vision/
│   ├── concepts/
│   ├── architecture/
│   ├── security/
│   ├── deployment/
│   ├── hardware/
│   ├── integrations/
│   ├── operations/
│   ├── tutorials/
│   ├── ADRs/
│   └── research/
├── tools/
├── pyproject.toml
├── compose.yaml
├── mkdocs.yml
├── CONTRIBUTING.md
├── SECURITY.md
└── LICENSE

melloa-guardian/
├── guardian/                 # minimal host controller/CLI
├── systemd/
├── firewall/
├── recovery/
├── ansible/
├── tests/
├── docs/
└── SECURITY.md

melloa-deployment/            # private owner repository
├── inventory/                 # hosts and non-secret topology
├── config/                    # SOPS-encrypted deployment overlays
├── backups/                   # destinations and restore metadata, not backup payloads
├── runbooks/                  # owner-specific operational notes
└── README.md
```

## Dependency rules

1. `domain` imports only standard library and deliberately selected pure schema/value libraries.
2. `application` imports `domain` and `ports`, never concrete adapters.
3. `adapters` implement ports and may import external SDKs.
4. Capability adapters do not import core internals; they communicate through versioned contracts.
5. `apps` compose dependencies and contain transport/bootstrap code, not business rules.
6. `schemas` are versioned and cannot depend on one provider SDK.
7. `evals` and `simulations` may exercise public interfaces but do not become runtime dependencies.
8. Guardian has no dependency on Melli/model logic and accepts no arbitrary “agent command” channel.
9. Cross-domain imports are explicit; circular dependencies fail CI.
10. Every new dependency documents owner, purpose, license, security surface, and removal path.

## Language choices

### Python as the blessed application language

Use modern Python (3.13+ at implementation time) for domain/application logic, model adapters, data pipelines, evals, and most capability adapters. Reasons:

- strongest current ecosystem for AI/model/vision orchestration;
- rapid schema and integration development;
- shared language between runtime and evaluation tools;
- adequate performance when heavy work is in Postgres, FFmpeg/OpenCV, model runtimes, or separate processes;
- easier contribution than a multilingual core.

Use typing, Pydantic/data classes at boundaries, Ruff, mypy/pyright as selected, explicit async discipline, and profiling before optimization.

### SQL as a first-class language

PostgreSQL schemas, constraints, indexes, views, row roles, and migrations are architecture. Keep reviewed SQL visible rather than hiding all behavior behind an ORM.

### Guardian

Start with declarative systemd/nftables/Ansible and a minimal, auditable command wrapper. If a durable binary is justified, use Go for a small statically built owner CLI/daemon. Do not write a sprawling privileged shell framework; do not use Python dependency breadth inside the highest-trust component without need.

### Add only when the product requires it

- **TypeScript:** mandatory private Owner Console, generated schema clients, and browser tests.
- **Swift:** native iOS app/HealthKit/secure notification client.
- **Rust:** measured need for a high-assurance or high-performance daemon where ecosystem/support justify the cost.
- **C/C++:** existing CV/inference libraries or a profiled bottleneck, not core orchestration.

The blessed core should not require contributors to know five languages.

## APIs and contracts

Within the modular monolith, use typed in-process ports and application use cases. Across processes or trust boundaries:

- JSON over HTTP for owner/client and simple capability administration;
- canonical JSON/JSON Schema for durable event/export and broad plugin interoperability;
- PostgreSQL job/outbox for V1 asynchronous work;
- Unix sockets or loopback HTTP for local privileged helpers only with explicit authentication;
- gRPC/protobuf for high-throughput edge/model services when measurement justifies it;
- MCP only as an adapter for suitable third-party tool servers, never as the internal source of authority.

JSON Schema 2020-12 is a stable, machine-readable contract foundation for open event/plugin payloads. [S11](research/primary-sources.md#S11) If protobuf is introduced, use automated breaking-change checks such as Buf’s compatibility model. [S12](research/primary-sources.md#S12)

## Documentation architecture

Use MkDocs Material with version-controlled Markdown and Mermaid diagrams. Material supports diagram rendering through Mermaid integration while keeping diagrams reviewable as text. [S52](research/primary-sources.md#S52)

Every durable concept gets one canonical page. Documentation categories:

- vision and principles;
- conceptual vocabulary;
- current and target architecture;
- security/privacy threat model;
- integration and capability contracts;
- deployment and hardware guides;
- operations/runbooks;
- tutorials/reference;
- ADRs and rejected ideas;
- research sources and date-sensitive assumptions.

### Documentation gates

A pull request changing any of these must update its corresponding documentation:

- public schema or capability contract;
- trust boundary, egress, secret, or permission;
- operator procedure or failure mode;
- storage/retention/export behavior;
- user-visible command or policy;
- architecture decision or dependency.

Executable examples and command output are tested where practical. Diagrams must show authority/data boundaries, not decorative service boxes.

## ADR discipline

An ADR contains status, date, context, constraints, considered alternatives, decision, consequences, migration/reversal triggers, and links to evidence. Superseded ADRs remain visible. ADR numbers identify decisions, not implementation tickets.

## Developer experience

The blessed local commands should feel coherent even if implemented through Make/Task/CLI wrappers:

```bash
melloa doctor                 # prerequisites, ports, time, storage, secrets
melloa init                   # safe example config and owner identity
melloa up / down / status
melloa migrate --check
melloa test
melloa eval --suite smoke
melloa replay --scenario ...
melloa audit show --run ...
melloa costs report
melloa backup run / verify
melloa export create
melloa capability list
melloa policy explain <request>
```

Commands print exact changed resources and next recovery step. Destructive commands require an exact scope and produce a receipt. The CLI never hides Docker/Compose/Postgres so completely that an operator cannot diagnose them.

## Open-source baseline

- OSI-approved license selected before code acceptance.
- `SECURITY.md` with private vulnerability reporting and supported versions.
- Contributor guide, code of conduct, architecture map, dependency rules, and release process.
- Synthetic fixtures; no personal data in issues, tests, or default telemetry.
- Reproducible development container or documented environment, but no mandatory proprietary cloud IDE.
- Signed/checksummed releases, changelog, migration notes, SBOM, and compatibility policy.
- Public roadmap distinguishes committed work from exploration.
- One supported deployment; community alternatives are clearly labeled.

## Naming gate

`Melloa` and `Melli` are the adopted project and intelligence names for implementation. Preliminary research finds an occupied GitHub `melloa` namespace and existing similarly named assistant/AI projects, including MelliLabs, MelloAI, and Project MELLO. [S48](research/primary-sources.md#S48) [S49](research/primary-sources.md#S49) [S50](research/primary-sources.md#S50) [S51](research/primary-sources.md#S51) Before public release, perform jurisdiction-appropriate trademark counsel/search, package/registry/domain/social namespace review, pronunciation/accessibility review, and confusion testing. This is a release gate, not an architecture blocker.

## Build now

- Three-repository trust layout, monorepo dependency checks, Python/SQL/TypeScript toolchains, migration and schema discipline.
- Separate Guardian protection.
- MkDocs/Markdown/Mermaid, ADRs, runbooks, and source register.
- A small coherent CLI and synthetic open-source fixtures.

## Design for

- Stable capability SDK, generated schema clients, TypeScript/Swift clients, edge services, and compatible export/import.

## Defer

- Polyrepo proliferation, mandatory Nix, generated microservices, a plugin marketplace, and languages introduced without a measured domain need.
