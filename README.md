# Melloa

**Original research date:** 15 August 2026  
**Decision update:** 16 August 2026  
**Status:** Architecture v0.2 with M0 complete and an owner-facing M1 preview; not production-ready

**Scope:** A long-lived, owner-controlled personal AI operating system, with **Melloa** as the system and **Melli** as its primary persistent personal intelligence

> **License status:** No public source license has been selected yet. The code is readable, but reuse, redistribution, and outside contributions are not authorized until the repository owner adds explicit license terms.

Melloa is a local-first system for building a durable relationship between an owner and a personal intelligence without giving a model ambient authority. Conversations, memory, provenance, policy, and recovery belong to the owner and survive changes in models, providers, workers, and interfaces.

## Run it locally

The current preview gives you a private Owner Console, a canonical conversation with Melli, visible route and disclosure evidence, inspectable memory, owner export, and a separately signed Guardian status. Its safe default is loopback-only, uses synthetic data, and makes no model-provider or Telegram network call.

You need Python 3.13+, [uv 0.12.0](https://docs.astral.sh/uv/), Node.js 22+, Go 1.24+, Bash, and the public `melloa` and `melloa-guardian` repositories as siblings. Docker, API keys, Telegram, Ollama, cameras, and private deployment state are not required for the default path.

```bash
git clone https://github.com/melloa-project/melloa.git
git clone https://github.com/melloa-project/melloa-guardian.git
cd melloa
make bootstrap
```

If `uv` reports `UnknownIssuer` on a managed network and the organization CA is already trusted by your system, retry with `UV_SYSTEM_CERTS=true make bootstrap`. Do not disable TLS verification; an unexpected issuer is a reason to stop and inspect the network trust path.

Continue with **[Run the current MVP](docs/run-current-mvp.md)**. The guide starts with a first-run route map, creates only disposable credentials and Guardian state, then walks through login, conversation, inspection, export, and cleanup.

Contributors can verify the checkout with:

```bash
make check
make integration
make recovery
```

The last two commands require Docker and use only synthetic data. No private repository or real credential is a build dependency.

## Why it exists

Melloa treats the enduring product as a closed loop:

> human goals → observations → interpretation → memory → policy-constrained reasoning → action → observed outcome → evaluation → evolution

The decisive recommendation remains a **local-first modular monolith with a durable event/provenance ledger**, explicit capability and policy boundaries, provider-neutral model routing, and an owner-controlled Guardian that the autonomous plane cannot disable.

## Implementation status

M0 provides strict versioned contracts, deny-first policy, PostgreSQL 18 migrations and append-only audit controls, signed read-only Guardian status consumption, deterministic fake adapters, pinned CI, and an encrypted clean-restore drill.

The M1 preview adds authenticated channel-neutral conversation, durable retry/resume records, model-route and disclosure inspection, correction-aware memory with content-deletion tombstones, retention and health views, owner export, optional local OpenAI-compatible routing, a bounded experimental Codex CLI route, optional Telegram long polling, and a responsive Owner Console. Defaults remain visibly synthetic and process-local; optional PostgreSQL supplies only the restart-durability boundaries the runtime reports. Backup, broader audit coverage, production host controls, camera capture, and several lifecycle controls remain incomplete.

The main runtime receives no Guardian signing key, transition command, or host-control authority. The complete implemented boundaries and remaining gates live in [M0 implementation evidence](docs/24-m0-implementation.md), [M1 implementation evidence](docs/25-m1-implementation.md), the [M1 implementation threat review](docs/26-m1-threat-review.md), the [M1 observability and operational-evidence design](docs/27-m1-observability-operational-evidence.md), [current MVP operations](docs/operations/current-mvp.md), and [the recovery runbook](docs/operations/m0-recovery.md).

## v0.2 decisions

This release preserves the v0.1 research and makes three product decisions explicit:

1. **Meliorism is the guiding philosophy; Melloa is the system; Melli is the persistent intelligence.** `Otto` is reserved as an optional philosophical reference for a future identity or example, not a required V1 service or agent.
2. **A private Owner Console is mandatory in V1.** It is the first-party web interface for conversation, inspection, correction, health, media, costs, disclosures, and deployment history. It is reachable only over the private network or local LAN and still requires application authentication.
3. **Conversation is a channel-independent Melloa capability.** The Owner Console is the primary client. Telegram long polling remains an optional secondary remote transport rather than the system's identity, memory, or permanent interface.

The authoritative update and precedence rule are recorded in [v0.2 decisions](docs/23-v0.2-decisions.md), [ADR-013](docs/adr/ADR-013-melloa-naming-and-intellectual-lineage.md), and [ADR-014](docs/adr/ADR-014-private-owner-console-and-conversation.md).

## Learn progressively

1. **Use it:** [run the current MVP](docs/run-current-mvp.md), then use [development and verification](docs/development.md) when you want to contribute.
2. **Understand the idea:** read the [executive vision](docs/01-executive-vision.md), [design principles](docs/02-design-principles-requirements.md), and [conceptual model](docs/03-conceptual-model.md).
3. **Understand the boundaries:** read the [v0.2 decisions](docs/23-v0.2-decisions.md), [chosen V1 architecture](docs/05-chosen-v1-architecture.md), and [Owner Console and client architecture](docs/12-telegram-clients.md).
4. **Go deeper:** use the [final synthesis](docs/22-final-synthesis.md), [diagram catalogue](docs/diagrams.md), [ADRs](docs/adr/index.md), and [requirement traceability](docs/00-traceability.md).
5. **Inspect evidence:** see the [validation report](VALIDATION.md), [M0 evidence](docs/24-m0-implementation.md), [M1 evidence](docs/25-m1-implementation.md), [M1 threat review](docs/26-m1-threat-review.md), and [M1 observability acceptance design](docs/27-m1-observability-operational-evidence.md).

The [consolidated edition](CONSOLIDATED.md) supports linear offline reading. Project-owned work follows the [pre-release compatibility process](docs/compatibility.md) and [AGENTS.md](AGENTS.md). These rules do not open outside contribution intake while the license decision remains unresolved.

## Decision in one page

| Concern | V1 decision | Deliberately deferred |
|---|---|---|
| Shape | Modular monolith plus independently controlled Guardian | Microservice fleet, service mesh |
| Host | Wired x86-64 Linux mini-PC, 16–32 GB RAM, 1 TB NVMe | Raspberry Pi as the core server; GPU workstation |
| Deployment | Rootless Docker Compose; systemd-owned Guardian; Ansible bootstrap | Kubernetes, Nomad, public cloud control plane |
| Primary state | PostgreSQL 18; append-oriented provenance/event records plus ordinary relational projections | Pure event sourcing; graph database |
| Semantic retrieval | `pgvector` as a rebuildable index | Standalone vector database as “memory” |
| Async work | PostgreSQL jobs/outbox; polling as truth, `LISTEN/NOTIFY` as a wake-up hint | Kafka, NATS, Temporal until thresholds are crossed |
| Blobs | Content-addressed local filesystem; encrypted `restic` backups | MinIO cluster, permanent raw-video archive |
| Reasoning | Provider-neutral model gateway and per-task routing | One fixed provider/model; local-only ideology |
| Agents | One persistent Melli, ephemeral specialist workers | Permanent multi-agent society without distinct authority domains |
| Policy | Deterministic capability broker, typed policy decision, exact-action approvals | LLM self-policing; universal approval prompts |
| Secrets | SOPS + age/OS keyring for bootstrap; scoped credential broker | Giant `.env`; Vault/OpenBao before justified |
| Generated code | Isolated worktree, tests/evals, PR, canary, rollback; stronger sandbox when enabled | Host root, Docker socket, autonomous governance changes |
| Camera | Wired PoE ONVIF Profile T/RTSP camera on isolated VLAN; local cheap detection | Continuous cloud video; Wi-Fi-only cloud camera |
| First-party client | Private Owner Console with canonical conversation and inspection | Public web application; native mobile app |
| Secondary channel | Optional Telegram Bot API long polling with one paired owner | Telegram as permanent trusted UI; public webhook |
| Private access | Tailscale as convenient default; WireGuard-compatible escape path | Public domain and reverse proxy in V1 |
| Observability | Structured decision/audit records plus redacted OpenTelemetry | Raw hidden chain-of-thought or personal-data dumping into telemetry |
| Backups | Encrypted local/offsite `restic`; documented restore drills | “Backup succeeded” without restoration tests |
| Documentation | MkDocs Material, Mermaid, ADRs, runbooks | Wiki-only tribal knowledge |

## V1 acceptance bar

V1 is useful only when all of these are true:

- Melli can converse with the owner through the private Owner Console and remember information with visible provenance.
- Telegram can be enabled as a replaceable secondary channel without changing identity or conversation semantics.
- The owner can inspect observations, interpretations, beliefs, decision records, actions, costs, external disclosures, media, and system health.
- Camera-derived claims are probabilistic interpretations, not silently promoted to facts.
- Every action goes through deterministic authorization independent of the model.
- An owner-only mechanism can place the autonomous plane in `no-actions`, `read-only`, `offline`, or `stopped` mode.
- Backups have been restored on a clean machine.
- A historical event stream can be replayed against a proposed model/prompt change.
- The system can fail closed on dangerous actions and fail useful on ordinary outages.

## Package and validation

- The modular files under `docs/` are canonical. `CONSOLIDATED.md` is generated by `tools/build_consolidated.py` for linear reading.
- `tools/validate_spec.py` checks local links and fragments, MkDocs navigation, Markdown fences, source anchors, Mermaid block directives, the retained brief hash, unfinished-draft markers, and key arithmetic.
- `VALIDATION.md` and `validation.json` record the executed architecture checks. `MANIFEST.sha256` covers release files except itself and transient build state.
- `make check` performs strict MkDocs and architecture validation. CI also exercises the authenticated production Owner Console journey, captures responsive visual evidence, verifies PostgreSQL and encrypted recovery, and publishes the validated docs site from `main`.

## Source discipline

The original master brief remains the requirements baseline and is preserved verbatim. The v0.2 decision record is authoritative where it intentionally changes a v0.1 recommendation. Contemporary claims are grounded in [Primary sources](docs/research/primary-sources.md); re-verify prices, product details, and provider policies before purchasing or implementing.
