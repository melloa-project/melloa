# Requirement traceability

## Purpose

This matrix maps the requested specification suite to concrete documents. Several topics are intentionally combined where splitting them would create navigation overhead without a separate decision boundary.

| Requested output | Primary document(s) |
|---|---|
| Executive Vision | [01](01-executive-vision.md) |
| Design Principles | [02](02-design-principles-requirements.md) |
| Requirements and Non-Requirements | [02](02-design-principles-requirements.md) |
| Architecture Overview | [05](05-chosen-v1-architecture.md), [diagrams](diagrams.md) |
| Alternative Architectures | [04](04-alternative-architectures.md) |
| Chosen Architecture and Rationale | [05](05-chosen-v1-architecture.md) |
| Sensor and Perception Architecture | [11](11-camera-perception-hardware.md) |
| Agent and Reasoning Architecture | [07](07-agents-models-goals.md) |
| Model Routing Architecture | [07](07-agents-models-goals.md) |
| Event System Specification | [06](06-events-memory-data.md) |
| Memory Architecture | [06](06-events-memory-data.md) |
| Goal and Policy Model | [07](07-agents-models-goals.md), [08](08-capabilities-policy-autonomy.md) |
| Capability / Plugin System | [08](08-capabilities-policy-autonomy.md) |
| Autonomy Model | [08](08-capabilities-policy-autonomy.md) |
| Security Architecture | [09](09-security-threat-injection.md), [10](10-secrets-control-kill-switch.md) |
| Threat Model | [09](09-security-threat-injection.md), [20](20-risk-register.md) |
| Prompt-Injection Defense | [09](09-security-threat-injection.md) |
| Credential and Secret Management | [10](10-secrets-control-kill-switch.md) |
| Control Plane / Kill Switch | [10](10-secrets-control-kill-switch.md) |
| Self-Modification Architecture | [13](13-self-modification-git-ci.md) |
| Deployment Architecture | [14](14-deployment-networking-infrastructure.md) |
| Local Infrastructure | [14](14-deployment-networking-infrastructure.md) |
| Cloud Infrastructure | [14](14-deployment-networking-infrastructure.md) |
| Networking | [14](14-deployment-networking-infrastructure.md) |
| Hardware Specification | [11](11-camera-perception-hardware.md) |
| Camera Setup Guide | [11](11-camera-perception-hardware.md) |
| Owner Console, Conversation, and Telegram Clients | [12](12-telegram-clients.md), [23](23-v0.2-decisions.md) |
| Observability | [15](15-observability-reliability-dr.md) |
| Reliability and Failure Recovery | [15](15-observability-reliability-dr.md) |
| Backup and Disaster Recovery | [15](15-observability-reliability-dr.md) |
| Data Privacy and Retention | [16](16-privacy-retention-export-cost.md) |
| Cost Model | [16](16-privacy-retention-export-cost.md) |
| Repository Architecture | [18](18-repository-languages-docs-dx.md) |
| Language and Technology Choices | [18](18-repository-languages-docs-dx.md) |
| Testing and Evaluation | [17](17-testing-evaluation-simulation.md) |
| Documentation Architecture | [18](18-repository-languages-docs-dx.md) |
| Developer Experience | [18](18-repository-languages-docs-dx.md) |
| Onboarding Guide | [19](19-onboarding-runbooks-roadmap.md) |
| Operations / Runbooks | [19](19-onboarding-runbooks-roadmap.md) |
| Roadmap | [19](19-onboarding-runbooks-roadmap.md), [22](22-final-synthesis.md) |
| Architectural Decision Records | [ADR directory](adr/index.md) |
| Open Questions | [21](21-reviewers-open-questions-rejected.md) |
| Rejected Ideas | [21](21-reviewers-open-questions-rejected.md) |
| Risk Register | [20](20-risk-register.md) |
| Mandatory diagrams | [Diagram catalogue](diagrams.md) |
| Naming and intellectual lineage | [03](03-conceptual-model.md), [23](23-v0.2-decisions.md), [ADR-013](adr/ADR-013-melloa-naming-and-intellectual-lineage.md) |
| Final ten questions, V1, milestones | [22](22-final-synthesis.md) |
| v0.2 adopted decisions | [23](23-v0.2-decisions.md), [ADR-014](adr/ADR-014-private-owner-console-and-conversation.md) |

## Cross-cutting document pattern

Each design document distinguishes:

- **Build now:** necessary for a useful, safe V1.
- **Design for:** boundary or contract that should exist now because later migration would be expensive.
- **Defer:** an explicit choice not to implement yet.

Trade-offs, failure modes, security, operations, cost, and future evolution are included where they materially differ. The suite does not copy the same template mechanically into every page; it preserves the decision logic instead.
