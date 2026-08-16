# Melloa

**Original research date:** 15 August 2026  
**Decision update:** 16 August 2026  
**Status:** Architecture v0.2 with M0 complete and M1 implementation in progress; not production-ready
**Scope:** A long-lived, owner-controlled personal AI operating system, with **Melloa** as the system and **Melli** as its primary persistent personal intelligence

This suite answers the master research brief by treating the enduring product as a closed loop:

> human goals → observations → interpretation → memory → policy-constrained reasoning → action → observed outcome → evaluation → evolution

The decisive recommendation remains a **local-first modular monolith with a durable event/provenance ledger**, explicit capability and policy boundaries, provider-neutral model routing, and an owner-controlled Guardian that the autonomous plane cannot disable.

## Implementation status

M0 provides strict versioned contracts, a deny-first policy evaluator, PostgreSQL 18 migrations and append-only audit controls, signed read-only Guardian status consumption, deterministic fake adapters, pinned CI, and an encrypted clean-restore drill. M1 now adds authenticated canonical conversation, durable leased retry/resume state for accepted inbound messages and exact-authority outbound delivery, durable turn and disclosure records, immutable memory correction/contestation, owner memory content deletion with durable tombstone evidence and canonical aggregate retention inventory, owner activity plus health/media inspection, provider-neutral routes for local OpenAI-compatible runtimes and an explicitly bounded experimental subscription-backed Codex CLI, an optional real Telegram Bot API channel, and a modern conversation-first Owner Console.

```bash
make bootstrap
make check
make integration
make recovery
```

The explicit `serve-mvp` command can route conversation through a configured local OpenAI-compatible endpoint or an optional experimental Codex CLI subscription route, and can enable Telegram Bot API long polling, private owner pairing, canonical text ingestion, and policy-authorized replies. Codex runs only from an exact configured executable with a private working directory and `CODEX_HOME`, fixed read-only/no-approval/ephemeral flags, visible external disclosure, and no Guardian, deterministic-policy, or capability authority. The deterministic model and Telegram fixtures remain visibly labelled no-network defaults. Application stores remain process-local by default; an explicit private core-role DSN enables partial PostgreSQL restart durability for canonical conversations/model provenance, memory correction history and content-deletion evidence, assembled audit append records, reply/delivery work, Telegram pairing authority, normalized intake receipts, poll offsets, and pre-submission reply recovery. `export-mvp` and `import-validate` provide a validated JSONL/schema/checksum ownership-export preview for canonical conversation, model-activity, and memory-inspection records, while truthfully excluding encryption, blobs, SQL snapshots, and production backup guarantees. Sessions, provider observations, Telegram challenge-send observation, attachment bytes, broad event/audit emission, and backup remain visibly ephemeral, incomplete, or unavailable. The web server binds loopback only and keeps browser/API traffic same-origin. The main runtime has no Guardian transition or signing API. Start with the canonical [run the current MVP](docs/run-current-mvp.md) guide; see also [M0 implementation evidence](docs/24-m0-implementation.md), [M1 implementation evidence](docs/25-m1-implementation.md), [development](docs/development.md), and [the recovery runbook](docs/operations/m0-recovery.md).

## v0.2 decisions

This release preserves the v0.1 research and makes three product decisions explicit:

1. **Meliorism is the guiding philosophy; Melloa is the system; Melli is the persistent intelligence.** `Otto` is reserved as an optional philosophical reference for a future identity or example, not a required V1 service or agent.
2. **A private Owner Console is mandatory in V1.** It is the first-party web interface for conversation, inspection, correction, health, media, costs, disclosures, and deployment history. It is reachable only over the private network or local LAN and still requires application authentication.
3. **Conversation is a channel-independent Melloa capability.** The Owner Console is the primary client. Telegram long polling remains an optional secondary remote transport rather than the system's identity, memory, or permanent interface.

The authoritative update and precedence rule are recorded in [v0.2 decisions](docs/23-v0.2-decisions.md), [ADR-013](docs/adr/ADR-013-melloa-naming-and-intellectual-lineage.md), and [ADR-014](docs/adr/ADR-014-private-owner-console-and-conversation.md).

## Start here

1. [v0.2 decisions](docs/23-v0.2-decisions.md)
2. [Executive vision](docs/01-executive-vision.md)
3. [Design principles and requirements](docs/02-design-principles-requirements.md)
4. [Precise conceptual model](docs/03-conceptual-model.md)
5. [Chosen V1 architecture](docs/05-chosen-v1-architecture.md)
6. [Owner Console, conversation, and clients](docs/12-telegram-clients.md)
7. [Final synthesis and implementation milestones](docs/22-final-synthesis.md)
8. [All diagrams](docs/diagrams.md)
9. [Requirement traceability](docs/00-traceability.md)
10. [Implementation agent instructions](AGENTS.md)
11. [Minimal implementation-agent prompt](IMPLEMENTATION_AGENT_PROMPT.md)
12. [Consolidated single-file edition](CONSOLIDATED.md)
13. [Validation report](VALIDATION.md)
14. [M0 implementation evidence](docs/24-m0-implementation.md)
15. [M1 implementation evidence](docs/25-m1-implementation.md)
16. [Run the current MVP](docs/run-current-mvp.md)
17. [Development and verification](docs/development.md)

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
- A full MkDocs/JavaScript Mermaid render remains a CI publication check; it was not available in the packaging environment.

## Source discipline

The original master brief remains the requirements baseline and is preserved verbatim. The v0.2 decision record is authoritative where it intentionally changes a v0.1 recommendation. Contemporary claims are grounded in [Primary sources](docs/research/primary-sources.md); re-verify prices, product details, and provider policies before purchasing or implementing.
