# Capability, plugin, policy, and autonomy architecture

## Purpose

Provide a framework-neutral mechanism for adding integrations while maintaining least privilege, transparent permissions, deterministic authorization, budgets, and auditability.

## Core distinction

```text
Capability installed
    ≠ principal has a grant
    ≠ current policy allows this action
    ≠ approval has been given
    ≠ action is safe or useful
```

A capability describes what an adapter can do. A grant describes what a principal may request. Policy evaluates the exact context. Approval is a bounded owner decision. Autonomy is the set of actions that pass without new approval under current grants and policy.

## Capability manifest

Illustrative manifest:

```yaml
apiVersion: melloa.dev/v1alpha1
kind: Capability
metadata:
  name: telegram.owner-channel
  version: 1.2.0
spec:
  provider: telegram-bot-api
  operations:
    - name: messages.send
      inputSchema: schemas/telegram-send-v1.json
      outputSchema: schemas/telegram-result-v1.json
      sideEffects: [external_communication]
      defaultRisk: medium
      reversibility: partial
    - name: attachments.fetch
      sideEffects: [external_read, local_write]
      defaultRisk: low
  dataClasses:
    reads: [personal, sensitive]
    writes: [personal, sensitive]
  permissionsRequired:
    - secret: telegram.bot-token
    - network: api.telegram.org:443
  cost:
    model: rate_limited_external_api
  health:
    probe: telegram.getMe
  constraints:
    maxAttachmentBytes: 20000000
```

Every operation declares input/output schemas, side effects, required data classes, network destinations, credential needs, cost shape, reversibility, and health behavior.

## Capability runtime interface

Stable domain operations:

```text
describe() -> manifest
health() -> health record
plan(input) -> normalized action proposal, estimated side effects/cost
execute(authorized_action, credential_lease) -> typed result
compensate(action_result) -> compensation proposal, when supported
```

`plan` must not cause effects. `execute` requires an unexpired broker authorization bound to the canonical action hash.

## Protocol choices

### Internal V1

- Python typed interfaces inside the modular monolith.
- JSON Schema for external/event/action payloads.
- HTTP for process boundaries such as Frigate, local models, and future remote capabilities.
- PostgreSQL records for durable commands/results.

### MCP

MCP is useful as an adapter-facing discovery and invocation protocol. The current specification standardizes resources, prompts, and tools over JSON-RPC and explicitly warns that tool descriptions are untrusted and that the protocol itself cannot enforce security principles. [S01](research/primary-sources.md#S01)

Decision: support MCP **behind** the Melloa capability broker. Never treat “available via MCP” as permission or trust. Wrap each MCP server with a manifest, pinned identity, allowlisted operations, schemas, network policy, and risk classification. For HTTP MCP, follow its authorization guidance, audience binding, TLS, and prohibition on token passthrough. [S02](research/primary-sources.md#S02) [S03](research/primary-sources.md#S03)

### OpenAPI and gRPC

- OpenAPI is suitable for conventional HTTP capability APIs and human review.
- gRPC/protobuf becomes useful for high-rate or strongly typed remote nodes, but adds code generation and compatibility discipline.
- Direct library calls remain acceptable inside one release unit when the domain port is preserved.

Do not force every plugin through one protocol. The capability manifest and broker semantics are the stable architecture.

## Authorization request

```json
{
  "principal": "intelligence:melli",
  "delegated_execution": "worker:exec_123",
  "operation": "telegram.owner-channel/messages.send",
  "resource": "telegram:user:123456",
  "purpose": "goal:running-consistency",
  "action_hash": "sha256:...",
  "risk": {
    "level": "medium",
    "side_effects": ["external_communication"],
    "reversibility": "partial"
  },
  "data": {
    "input_classes": ["personal"],
    "output_classes": ["personal"],
    "external_destinations": ["api.telegram.org"]
  },
  "budget": {"estimated_gbp": 0.001, "rate_key": "proactive_message"},
  "context": {
    "time": "...",
    "quiet_hours": false,
    "owner_present": true,
    "confidence": 0.91
  }
}
```

Decision:

```text
deny | allow | require_approval
+ constraints
+ obligations
+ policy_version
+ explanation codes
+ expiry
```

Constraints might redact fields, cap spend, force a recipient, restrict egress, or require a sandbox. Obligations might require audit, owner notification, post-action verification, or rollback preparation.

## Policy layers

### Layer 1 — immutable platform prohibitions

Owned by the Guardian/release process, not writable by Melli. Examples:

- no attempt to bypass Melloa security or Guardian controls;
- no unapproved access to third-party systems;
- no exfiltration of device-only data;
- no execution of generated code on the host;
- no use of credentials outside declared operations.

### Layer 2 — owner governance policy

Owner-controlled classes such as:

- prohibited actions;
- actions always requiring approval;
- autonomous action classes;
- recipients and resources;
- data egress rules;
- financial, token, rate, and attention budgets;
- quiet hours and emergency behavior.

### Layer 3 — goal-specific policy

Constraints accepted with a goal or experiment, such as reminder frequency or eligible data sources.

### Layer 4 — dynamic risk and context

Device state, confidence, reversibility, anomaly signals, and current budget consumption. Dynamic context can tighten authority but should not silently broaden owner grants.

## Policy implementation

Start with a small typed application policy evaluator behind a stable port, with explicit deny-first rules and exhaustive tests. Cedar is a credible later/embedded implementation because it models `principal`, `action`, `resource`, and `context`, uses default deny, and lets forbid policies override permits. [S18](research/primary-sources.md#S18)

Do not expose Cedar or Rego syntax as the primary owner experience. The owner should edit understandable policy concepts and inspect generated/effective rules. Policy-as-code remains version-controlled and testable underneath.

## Risk model

| Level | Typical examples | Default treatment |
|---|---|---|
| R0 — read-only/local | query own event store, create internal analysis | autonomous, budgeted, audited |
| R1 — reversible internal | update derived index, change dashboard, create draft | autonomous with rollback and rate limits |
| R2 — external/reputational | send owner message, create PR, call third-party API | policy-specific; often autonomous to owner, approval for other humans |
| R3 — destructive/privileged | delete source data, expose service, change IAM, rotate critical secret | exact approval plus safeguards |
| R4 — irreversible/high consequence | financial transaction, legal commitment, safety-critical control | unsupported or multi-step owner-controlled process in early versions |

Risk is not one scalar. Classification also records sensitivity, reversibility, blast radius, externality, detectability, and credential privilege.

## Grants, leases, and approvals

### Grant

A durable, revocable statement that a principal may request operations within limits. Example: Melli may send up to five proactive messages/day to the owner, never to other Telegram users.

### Capability lease

A short-lived execution token issued to one worker for one operation class/resource/purpose. It carries limits and cannot be refreshed by the worker beyond policy.

### Credential lease

A broker-held reference or short-lived credential. Prefer the broker performing the API call so the secret never enters the worker. When direct access is unavoidable, inject the least-privilege token into an ephemeral process and revoke it afterward.

### Approval

A signed owner decision for an exact action hash, scope, constraints, and expiry. Editing the content, recipient, amount, public endpoint, or artifact invalidates approval.

## Budget and loop controls

Every execution has:

- maximum wall time;
- maximum model/tool steps;
- token/input/output budgets;
- provider and operation cost limits;
- retry cap and exponential backoff;
- deduplication key;
- recursion/delegation depth;
- maximum outbound messages/actions;
- circuit-breaker behavior.

Monthly global budgets cannot be the only defense. Per-run and per-capability limits stop rapid runaway loops before a monthly alert arrives.

## Taint and provenance policy

External content is tagged by origin and trust:

- owner-authored;
- trusted capability metadata;
- untrusted website/document/message;
- model-generated;
- sensor-derived;
- generated code;
- signed system artifact.

Taint affects what can be interpolated into prompts, written to memory, sent to tools, or used as authority. No text from a website, email, document, camera, tool result, or MCP description can modify policy or authorize an action.

## Health and revocation

The capability registry tracks:

- installed, enabled, degraded, quarantined, disabled;
- manifest and adapter versions;
- last successful health check;
- secret/credential status;
- policy grants;
- observed latency/error/cost;
- security advisories and forced minimum version.

The Guardian can revoke capability network access and credentials even if the core registry is compromised.

## Build now

- Manifest schema and typed operations for Telegram, model providers, camera evidence, filesystem/blob, and internal database queries.
- Deterministic action broker, deny/allow/approval decisions, exact-action hashes.
- Per-run/capability budgets and audit.
- Owner-readable policy UI/CLI for a small set of rules.
- Taint labels and external-data handling rules.

## Design for

- MCP/OpenAPI/gRPC adapters.
- Remote capability identity and signed manifests.
- Short-lived dynamic credentials and workload identity.
- Capability marketplace metadata without enabling a marketplace.

## Defer

- Universal automatic discovery and trust of arbitrary MCP servers.
- User-authored raw policy language as the only UX.
- Global autonomy slider.
- Long-lived broad credentials in workers.
- R4 financial/legal authority.
