# Primary-source register

**Research cut-off:** 15 August 2026  
**Use:** Evidence for date-sensitive architectural claims. This is not a vendor endorsement list. Re-check prices, product support, model names, policies, and security guidance at implementation/purchase time.

The master brief is the requirements baseline. Sources below are predominantly specifications, official documentation, vendor policy/pricing pages, or peer-reviewed research. A few naming-collision entries are project sites/repositories because collision research necessarily concerns those projects.

## Protocols, contracts, events, and workflows

<a id="S01"></a>
### S01 — Model Context Protocol specification

- Source: [Model Context Protocol specification, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)
- Relevance: current protocol shape, JSON-RPC concepts, tools/resources, and versioning. Melloa treats MCP as an adapter boundary, not its authority or memory model.

<a id="S02"></a>
### S02 — MCP authorization

- Source: [MCP authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- Relevance: OAuth-based authorization discovery and resource-server behavior for remote MCP servers.

<a id="S03"></a>
### S03 — MCP security guidance

- Source: [MCP security best practices](https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices)
- Relevance: token audience binding, no token passthrough, least privilege, and security considerations. Melloa still enforces its own broker/policy boundary.

<a id="S04"></a>
### S04 — PostgreSQL 18 documentation

- Source: [PostgreSQL 18 documentation](https://www.postgresql.org/docs/18/)
- Relevance: primary relational store, transactions, roles, row security, JSON, full-text, locks, and operational behavior.

<a id="S05"></a>
### S05 — pgvector

- Source: [pgvector project and documentation](https://github.com/pgvector/pgvector)
- Relevance: exact and approximate vector search within PostgreSQL. Used only as a rebuildable semantic index.

<a id="S06"></a>
### S06 — Transactional outbox pattern

- Source: [AWS Prescriptive Guidance: transactional outbox pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html)
- Relevance: atomic state/outbox writes, at-least-once delivery, ordering and idempotency concerns.

<a id="S07"></a>
### S07 — PostgreSQL LISTEN

- Source: [PostgreSQL 18 `LISTEN`](https://www.postgresql.org/docs/18/sql-listen.html)
- Relevance: asynchronous notification behavior. Used as a wake-up hint, never as the durable queue.

<a id="S08"></a>
### S08 — NATS JetStream

- Source: [NATS JetStream concepts](https://docs.nats.io/nats-concepts/jetstream)
- Relevance: durable streams, replay, persistence, and consumer semantics; a credible post-V1 event-bus option if scale thresholds are crossed.

<a id="S09"></a>
### S09 — Temporal

- Source: [Temporal documentation](https://docs.temporal.io/)
- Relevance: durable workflow execution and recovery. Deferred until long-running workflows exceed the maintainability of PostgreSQL jobs/state machines.

<a id="S10"></a>
### S10 — CloudEvents

- Source: [CloudEvents specification project](https://cloudevents.io/)
- Relevance: interoperable event-envelope ideas. Melloa may borrow conventions without forcing all domain semantics into CloudEvents.

<a id="S11"></a>
### S11 — JSON Schema 2020-12

- Source: [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)
- Relevance: open, versioned payload validation for events, capabilities, exports, and configuration.

<a id="S12"></a>
### S12 — Buf breaking-change detection

- Source: [Buf breaking change detection](https://buf.build/docs/breaking/)
- Relevance: compatibility automation if protobuf/gRPC is introduced for edge or high-throughput services.

## Security, policy, and adversarial AI

<a id="S13"></a>
### S13 — OWASP Top 10 for LLM applications

- Source: [OWASP Top 10 for Large Language Model Applications](https://genai.owasp.org/llm-top-10/)
- Relevance: current classes of model/application security risk.

<a id="S14"></a>
### S14 — OWASP prompt injection

- Source: [OWASP LLM01: Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- Relevance: direct and indirect injection, multimodal/encoded inputs, and the fact that fine-tuning/RAG do not eliminate the problem.

<a id="S15"></a>
### S15 — MITRE ATLAS

- Source: [MITRE ATLAS](https://atlas.mitre.org/)
- Relevance: adversarial tactics and techniques for AI-enabled systems; used to structure attack scenarios.

<a id="S16"></a>
### S16 — NIST Generative AI profile

- Source: [NIST AI 600-1: Generative Artificial Intelligence Profile](https://doi.org/10.6028/NIST.AI.600-1)
- Relevance: risk framing and lifecycle controls for generative AI.

<a id="S17"></a>
### S17 — Open Policy Agent

- Source: [Open Policy Agent documentation](https://www.openpolicyagent.org/docs/latest/)
- Relevance: general-purpose policy-as-code alternative. Useful comparison; not selected as the only V1 policy/user model.

<a id="S18"></a>
### S18 — Cedar policy language

- Source: [Cedar policy language documentation](https://docs.cedarpolicy.com/)
- Relevance: authorization-focused policy model with explicit principal/action/resource/context concepts; credible future evaluator behind Melloa’s typed broker.

<a id="S19"></a>
### S19 — OpenBao

- Source: [OpenBao documentation](https://openbao.org/docs/)
- Relevance: open-source secret management and dynamic credentials. Deferred until operational scale justifies another critical service.

<a id="S20"></a>
### S20 — SOPS

- Source: [SOPS documentation](https://getsops.io/docs/)
- Relevance: encrypted configuration/secrets in Git, including age identities; selected for V1 bootstrap, not runtime ambient secret distribution.

<a id="S21"></a>
### S21 — Docker rootless mode

- Source: [Docker Engine rootless mode](https://docs.docker.com/engine/security/rootless/)
- Relevance: running daemon and containers without root privileges; one isolation layer, not a complete hostile-code security boundary.

<a id="S22"></a>
### S22 — gVisor

- Source: [gVisor documentation](https://gvisor.dev/docs/)
- Relevance: userspace application-kernel isolation for generated or untrusted workloads.

<a id="S56"></a>
### S56 — Firecracker

- Source: [Firecracker microVM project](https://github.com/firecracker-microvm/firecracker)
- Relevance: stronger microVM isolation tier; deferred because image/network/operations complexity is not justified in V1.

<a id="S37"></a>
### S37 — SLSA

- Source: [SLSA specification](https://slsa.dev/spec/)
- Relevance: vocabulary and controls for build provenance and supply-chain assurance.

<a id="S38"></a>
### S38 — Sigstore and cosign

- Source: [Sigstore documentation](https://docs.sigstore.dev/)
- Relevance: artifact signing, identity, transparency, and verification without a bespoke signing system.

<a id="S39"></a>
### S39 — GitHub rulesets

- Source: [GitHub: About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- Relevance: protected branch/tag behavior and required workflows for autonomous changes.

<a id="S63"></a>
### S63 — Pinning GitHub Actions

- Source: [GitHub security hardening for Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions)
- Relevance: pin third-party actions to full-length commit SHAs and minimize workflow token authority.

## Cameras, perception, and edge hardware

<a id="S23"></a>
### S23 — ONVIF Profile T

- Source: [ONVIF Profile T](https://www.onvif.org/profiles/profile-t/)
- Relevance: interoperable advanced video streaming features for IP cameras; selected over vendor-cloud lock-in.

<a id="S24"></a>
### S24 — RTSP

- Source: [RFC 7826: Real-Time Streaming Protocol Version 2.0](https://www.rfc-editor.org/rfc/rfc7826.html)
- Relevance: standard media-control protocol context for local camera streaming.

<a id="S28"></a>
### S28 — Frigate

- Source: [Frigate documentation](https://docs.frigate.video/)
- Relevance: local NVR/perception pipeline with motion filtering, object detection, and retention controls. Used behind a replaceable adapter.

<a id="S29"></a>
### S29 — go2rtc

- Source: [go2rtc project](https://github.com/AlexxIT/go2rtc)
- Relevance: local camera-stream restreaming/compatibility layer often paired with Frigate.

<a id="S30"></a>
### S30 — Raspberry Pi Camera Module 3

- Source: [Raspberry Pi Camera Module 3](https://www.raspberrypi.com/products/camera-module-3/)
- Relevance: 12-megapixel autofocus/HDR and NoIR edge-camera option; not the blessed core host.

<a id="S31"></a>
### S31 — Raspberry Pi AI HAT+

- Source: [Raspberry Pi AI HAT+](https://www.raspberrypi.com/products/ai-hat/)
- Relevance: low-power edge inference option. Purchase only when a measured edge workload benefits.

## Communication channels

<a id="S25"></a>
### S25 — Telegram Bot API

- Source: [Telegram Bot API](https://core.telegram.org/bots/api)
- Relevance: `getUpdates` long polling, webhooks, update offsets, attachments, commands, and proactive messages.

<a id="S26"></a>
### S26 — Telegram security model

- Source: [Telegram FAQ: security and Secret Chats](https://telegram.org/faq#q-how-secure-is-telegram)
- Relevance: distinction between cloud chats and end-to-end encrypted Secret Chats. Bot chats are not the root confidential-control channel.

<a id="S27"></a>
### S27 — Matrix specification

- Source: [Matrix specification](https://spec.matrix.org/latest/)
- Relevance: open/federated communication alternative with an ecosystem for end-to-end encryption; deferred due to homeserver/client/key complexity.

## Models, inference, provider policy, and pricing

<a id="S32"></a>
### S32 — llama.cpp

- Source: [llama.cpp](https://github.com/ggml-org/llama.cpp)
- Relevance: portable local inference endpoint and model-format ecosystem.

<a id="S33"></a>
### S33 — MLX-LM

- Source: [MLX-LM](https://github.com/ml-explore/mlx-lm)
- Relevance: local language-model inference/fine-tuning on Apple Silicon; useful for an optional Mac compute node.

<a id="S34"></a>
### S34 — vLLM

- Source: [vLLM documentation](https://docs.vllm.ai/)
- Relevance: high-throughput local/server inference where GPU workloads justify a dedicated model service.

<a id="S35"></a>
### S35 — OpenAI API pricing

- Source: [OpenAI API pricing](https://openai.com/api/pricing/)
- Relevance: date-sensitive example of the price spread among model tiers and batch processing. Routing remains provider-neutral.

<a id="S36"></a>
### S36 — Provider data-handling comparison

- Sources: [OpenAI data controls](https://platform.openai.com/docs/guides/your-data), [Anthropic Privacy Center](https://privacy.claude.com/), [Gemini API terms](https://ai.google.dev/gemini-api/terms), [Mistral terms and privacy](https://mistral.ai/terms/)
- Relevance: terms, retention, training use, and eligibility differ by product/account/region. Melloa stores versioned provider-policy snapshots.

<a id="S59"></a>
### S59 — OpenAI API data controls

- Source: [OpenAI API data controls](https://platform.openai.com/docs/guides/your-data)
- Relevance: API data use and retention controls; re-check endpoint and account eligibility before routing sensitive data.

<a id="S60"></a>
### S60 — Anthropic commercial/API retention

- Sources: [Anthropic: organization data retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data), [Anthropic: zero data retention eligibility](https://privacy.claude.com/en/articles/8956058-i-have-a-zero-data-retention-agreement-with-anthropic-what-products-does-it-apply-to)
- Relevance: standard retention, exceptions, and organization-specific ZDR are not interchangeable.

<a id="S61"></a>
### S61 — Gemini API data terms and logging

- Sources: [Gemini API Additional Terms](https://ai.google.dev/gemini-api/terms), [Gemini API data logging and sharing](https://ai.google.dev/gemini-api/docs/logs-policy)
- Relevance: paid/unpaid and regional terms differ; do not route private data based on a generic “Gemini” label.

<a id="S62"></a>
### S62 — Mistral data policy

- Sources: [Mistral terms](https://mistral.ai/terms/), [Mistral privacy policy](https://mistral.ai/terms/#privacy-policy)
- Relevance: vendor/account/product terms must be checked and recorded before eligibility is granted.

## Deployment, networking, observability, backup, and documentation

<a id="S40"></a>
### S40 — Docker Compose

- Source: [Docker Compose file reference](https://docs.docker.com/reference/compose-file/)
- Relevance: declarative services, networks, volumes, configs, and secrets for the blessed one-host topology.

<a id="S41"></a>
### S41 — Ansible

- Source: [Ansible documentation](https://docs.ansible.com/)
- Relevance: idempotent host bootstrap, firewall, users, systemd, backup timers, and runbooks.

<a id="S42"></a>
### S42 — restic

- Source: [restic documentation](https://restic.readthedocs.io/en/stable/)
- Relevance: encrypted, deduplicated snapshots, integrity checks, and multiple storage backends.

<a id="S43"></a>
### S43 — Backblaze B2 pricing

- Source: [Backblaze B2 Cloud Storage pricing](https://www.backblaze.com/cloud-storage/pricing)
- Relevance: current low-cost offsite-storage planning benchmark. Verify price and egress policy before deployment.

<a id="S44"></a>
### S44 — OpenTelemetry

- Source: [OpenTelemetry documentation](https://opentelemetry.io/docs/)
- Relevance: vendor-neutral traces, metrics, and logs. Domain/audit records remain separate durable state.

<a id="S45"></a>
### S45 — Ofgem energy price cap

- Source: [Ofgem energy price cap](https://www.ofgem.gov.uk/energy-price-cap)
- Relevance: electricity-unit-rate benchmark used for planning calculations; actual tariff varies.

<a id="S52"></a>
### S52 — Material for MkDocs diagrams

- Source: [Material for MkDocs: diagrams](https://squidfunk.github.io/mkdocs-material/reference/diagrams/)
- Relevance: version-controlled Mermaid diagrams in a maintainable documentation site.

<a id="S54"></a>
### S54 — Tailscale architecture

- Source: [Tailscale: What is Tailscale?](https://tailscale.com/kb/1151/what-is-tailscale)
- Relevance: convenient encrypted private networking and identity/control plane; kept replaceable.

<a id="S55"></a>
### S55 — WireGuard

- Source: [WireGuard](https://www.wireguard.com/)
- Relevance: compact underlying VPN protocol and self-managed escape path. Application authorization remains separate.

<a id="S57"></a>
### S57 — OpenTofu

- Source: [OpenTofu documentation](https://opentofu.org/docs/)
- Relevance: declarative cloud infrastructure only once Melloa owns enough cloud state to justify plans/state operations.

## Evaluation, experimentation, and future integrations

<a id="S46"></a>
### S46 — N-of-1 methodology conditions

- Source: [N-of-1 Randomized Intervention Trials in Health Psychology: systematic review and methodology critique](https://pmc.ncbi.nlm.nih.gov/articles/PMC6128372/)
- Relevance: repeated measurable outcomes, reversibility, washout/carryover, stability, and stakeholder burden constrain valid N-of-1 use.

<a id="S47"></a>
### S47 — CENT 2015

- Source: [CONSORT extension for reporting N-of-1 trials (CENT) 2015](https://www.bmj.com/content/350/bmj.h1738)
- Relevance: transparent protocol/reporting discipline and limits on causal claims.

<a id="S53"></a>
### S53 — Inspect AI

- Source: [Inspect AI documentation](https://inspect.aisi.org.uk/)
- Relevance: open-source, model-provider-neutral evaluation framework with tasks, solvers, scorers, tools, sandboxes, and logs.

<a id="S58"></a>
### S58 — Apple HealthKit

- Source: [Apple HealthKit documentation](https://developer.apple.com/documentation/healthkit)
- Relevance: future native health integration, authorization, and device-side data access; not an MVP requirement.

## Intellectual lineage

<a id="S64"></a>
### S64 — Meliorism

- Source: [1911 Encyclopædia Britannica: Meliorism](https://en.wikisource.org/wiki/1911_Encyclop%C3%A6dia_Britannica/Meliorism)
- Relevance: historical description of meliorism as the position that the world may be made better through rightly directed human effort. Used as Melloa's guiding philosophy, not a technical claim.

<a id="S65"></a>
### S65 — Man-Computer Symbiosis

- Source: [J. C. R. Licklider, Man-Computer Symbiosis](https://groups.csail.mit.edu/medg/people/psz/Licklider.html)
- Relevance: close human-machine cooperation in problem formulation, decision-making, goals, hypotheses, criteria, and evaluation; an intellectual ancestor of Melloa's owner/intelligence relationship.

<a id="S66"></a>
### S66 — The Extended Mind

- Source: [Andy Clark and David Chalmers, The Extended Mind](https://consc.net/papers/extended.html)
- Relevance: argues that external resources may participate in cognition; the Otto notebook example motivates a subtle naming reference without dictating a memory-agent architecture.

<a id="S67"></a>
### S67 — Augmenting Human Intellect

- Source: [Douglas Engelbart, Augmenting Human Intellect: A Conceptual Framework](https://dougengelbart.org/pubs/augment-3906.html)
- Relevance: augmentation, tools for improving human problem solving, and bootstrapping better capabilities; part of Melloa's intellectual lineage.

## Naming collision research

These checks are preliminary discovery, not legal clearance or a complete trademark search.

<a id="S48"></a>
### S48 — GitHub `melloa` namespace

- Source: [GitHub account/repository namespace search for `melloa`](https://github.com/melloa)
- Relevance: the exact GitHub namespace is already occupied; public naming/organization choices need alternatives.

<a id="S49"></a>
### S49 — MelliLabs / Melli

- Source: [MelliLabs](https://melli.com/)
- Relevance: existing proactive/speech-driven virtual-assistant branding creates likely search and product confusion.

<a id="S50"></a>
### S50 — MelloAI

- Source: [MelloAI](https://melloai.com/)
- Relevance: similar AI naming; confirm current project status, marks, and domain confusion before public launch.

<a id="S51"></a>
### S51 — Project MELLO

- Source: [Project MELLO](https://projectmello.com/)
- Relevance: additional close-name collision in the broader technology/AI search space.

## Source-use cautions

- A vendor’s documentation describes intended behavior, not proof that a deployment is secure.
- Pricing and product pages are snapshots, not contracts.
- Provider privacy terms may differ by endpoint, account, region, paid/unpaid status, safety classification, and negotiated agreement.
- Standards and protocols do not replace Melloa’s policy, provenance, identity, or operational controls.
- Naming checks require package registries, domains, company/trademark databases, counsel where appropriate, and confusion analysis before public adoption.
