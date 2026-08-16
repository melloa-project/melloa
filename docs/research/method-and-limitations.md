# Research method and limitations

## Authority and scope

The supplied **Master Research Prompt: Design a Long-Lived Personal AI Operating System** is the requirements baseline. The suite preserves its distinction between Melloa (system/runtime) and Melli (persistent intelligence), its seven-year orientation, its Build now / Design for / Defer discipline, and its requirement to challenge the premise rather than merely elaborate it. The 16 August 2026 v0.2 decisions then adopt the naming lineage and promote the private Owner Console plus canonical conversation into V1; those decisions supersede conflicting product-priority wording without changing the original brief.

A verbatim copy is retained as [`master-research-brief.txt`](master-research-brief.txt). SHA-256: `a59d29c06c884f86064e5223e92f3b996771ca1d34bc5fc7baaea18e0c3abcd9`.

This deliverable is architecture and research, not production implementation. Tiny schemas and command examples illustrate contracts; they are not production code.

## Method

1. Extracted the explicit outputs, cross-cutting constraints, diagrams, final questions, and decision requirements from the master brief.
2. Defined precise vocabulary so system, intelligence, identity, memory, process, model, provider, capability, action, and policy do not collapse into one concept.
3. Developed three plausible architectures and evaluated complexity, security, observability, autonomy, cost, and migration path.
4. Researched primary specifications and official documentation for rapidly changing technologies, provider policies, protocols, hardware, security guidance, pricing, and APIs.
5. Selected the simplest V1 that preserves expensive-to-retrofit boundaries: provenance, policy enforcement, provider/framework neutrality, owner control, replay, and export.
6. Simulated independent security, reliability, simplicity, AI-research, privacy, open-source, cost, and future-maintainer reviews.
7. Produced ADRs, a ranked risk register, failure/recovery behavior, quantitative estimates, and explicit rejected ideas/revisit triggers.
8. Performed structural checks over navigation, local links, source anchors, Markdown fences, and Mermaid block types; the package includes a machine-readable validation report.

## Evidence policy

- Prefer protocol specifications, official documentation, vendor policy/pricing pages, standards bodies, and peer-reviewed research.
- Use named projects for collision research because the existence of those projects is the relevant fact.
- Mark prices and provider terms as dated snapshots.
- Treat vendor security claims as intended behavior, not independent verification.
- Keep architectural recommendations distinct from source facts; recommendations synthesize requirements, trade-offs, and evidence.

## Important limitations

- No production code, penetration test, physical camera test, provider contract review, load test, or long-running behavioral study was performed.
- Mermaid diagrams were structurally linted in the available environment; a full MkDocs/mermaid renderer was not available locally because external package installation was blocked. Render them in CI before publication.
- Hardware recommendations deliberately specify interfaces and classes rather than a final camera SKU. Validate firmware support, ONVIF behavior, low-light quality, and local-only operation at purchase time.
- Naming research is preliminary discovery, not trademark/legal clearance.
- Model pricing, capabilities, retention, and data-use policies can change between research and implementation. Recheck at each provider-policy release and before routing sensitive data.
- Cost ranges are scenario estimates, not quotes. They exclude developer labour and depend strongly on inference frequency, context/media volume, hardware, tariffs, and exchange rates.
- Intervention evaluation cannot guarantee causal conclusions. Many personal outcomes will remain confounded or inconclusive.
- The selected architecture reduces but cannot eliminate compromise, mistaken approval, model regression, privacy exposure, or data loss.

## Decision confidence

High confidence:

- keep Melloa, Melli, model, process, memory, and capability distinct;
- preserve provenance and correction semantics;
- enforce side effects outside model reasoning;
- keep an independent Guardian and owner-controlled recovery;
- avoid Kubernetes/Kafka/permanent agent swarms in V1;
- use selective local camera processing and bounded raw retention;
- require tested restore and open export.

Medium confidence, requiring implementation evidence:

- PostgreSQL jobs/outbox remain sufficient through the first year;
- Frigate is the best initial perception adapter rather than a thinner custom pipeline;
- the private Owner Console is the primary first-party client while Telegram remains an optional secondary adapter;
- Cedar is the right later policy evaluator;
- local models provide enough value on the blessed host to justify an always-on endpoint.

Low confidence until tested:

- which proactive interventions create durable owner benefit;
- exact camera event-classification accuracy in the real room;
- when a second persistent intelligence is worth its governance cost;
- the economics of local versus hosted frontier inference over several years.
