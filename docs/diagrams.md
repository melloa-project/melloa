# Architecture diagrams

These diagrams are design artifacts, not decorative overview pictures. They show data, authority, trust, lifecycle, and migration boundaries. Mermaid source is kept in version control.

## 1. Top-level system architecture

```mermaid
flowchart TB
  Human[Owner] -->|conversation, inspection, corrections, approvals| Console[Private Owner Console]
  Human -->|optional remote messages| Clients[Telegram and future clients]
  Env[Environment] --> Sensors[Sensors and integrations]
  Sensors --> Detect[Cheap local detection and normalization]
  Detect --> Events[Canonical observations and events]
  Console --> Events
  Clients --> Events
  Events --> Memory[Provenance and memory]
  Memory --> Reason[Melli policy-aware reasoning]
  Reason --> Proposals[Action or change proposals]
  Proposals --> Broker[Deterministic capability broker]
  Broker -->|authorized| Capabilities[Capabilities and communication]
  Broker -->|denied or approval| Human
  Capabilities --> Env
  Capabilities --> Outcomes[Results and observed consequences]
  Outcomes --> Evaluate[Evaluation and learning]
  Evaluate --> Memory
  Evaluate --> Changes[Configuration or software change pipeline]
  Changes --> Capabilities
  Guardian[Owner-only Guardian] -. constrain, revoke, stop .-> Broker
  Guardian -. constrain, revoke, stop .-> Capabilities
  Broker --x Guardian
```

## 2. Trust boundaries

```mermaid
flowchart TB
  subgraph External[Boundary A: external and untrusted]
    Web[Web, email, documents]
    Chat[Optional Telegram and future external channels]
    Providers[Model and cloud providers]
    Embedded[Camera and embedded devices]
  end

  subgraph Intake[Boundary B: low-trust intake]
    Quarantine[Attachment quarantine]
    Perception[Perception pipeline]
    Validation[Schema, size, identity, taint validation]
  end

  subgraph Autonomous[Boundary C: autonomous Melloa plane]
    Console[Private Owner Console]
    Core[Core and Melli runs]
    ModelGateway[Model gateway]
    Broker[Capability broker]
    Data[(Scoped Postgres and blobs)]
  end

  subgraph Sandboxed[Boundary D: hostile generated code]
    Sandbox[Disposable rootless and gVisor sandbox]
  end

  subgraph Control[Boundary E: owner-only control]
    Guardian[Guardian]
    RootKeys[Recovery and root credentials]
    Host[Firewall and systemd]
  end

  External --> Intake --> Core
  Console --> Core
  Core --> ModelGateway --> Providers
  Core --> Broker --> Data
  Core --> Sandbox
  Guardian --> Host
  Guardian --> RootKeys
  Guardian -. mode and revocation .-> Autonomous
  Autonomous --x Control
  Sandboxed --x Control
```

## 3. Control plane versus autonomous plane

```mermaid
flowchart LR
  subgraph OwnerPlane[Owner control plane]
    Owner[Owner]
    Guardian[Guardian CLI and service]
    PolicyRoot[Root policies and approval rules]
    CredentialRoot[Credential and recovery root]
    NetworkRoot[Host firewall and workload control]
  end

  subgraph AutoPlane[Autonomous plane]
    Melli[Melli]
    Scheduler[Workers and periodic loops]
    Broker[Capability broker]
    Adapters[Capability adapters]
    Runtime[Rootless containers]
  end

  Owner --> Guardian
  Owner --> PolicyRoot
  Guardian --> NetworkRoot
  Guardian --> CredentialRoot
  PolicyRoot -->|read-only policy bundle| Broker
  CredentialRoot -->|scoped leases| Broker
  NetworkRoot -->|start, stop, egress modes| Runtime
  Melli --> Broker --> Adapters
  Scheduler --> Melli
  AutoPlane --x OwnerPlane
```

## 4. Event ingestion flow

```mermaid
flowchart LR
  Source[Source] --> Adapter[Source adapter]
  Adapter --> Validate[Identity, schema, size, hash]
  Validate --> Classify[Sensitivity, trust and taint]
  Classify --> Raw[Immutable observation]
  Raw --> Outbox[Transactional job or outbox]
  Outbox --> Worker[Idempotent consumer]
  Worker --> Interpret[Interpretation with confidence]
  Interpret --> Link[Evidence and provenance links]
  Link --> Project[Current projections]
  Link --> Index[Full-text and vector indexes]
  Worker -->|failure| Dead[Visible retry or dead-letter state]
  Dead --> Replay[Operator or policy replay]
```

## 5. Camera perception pipeline

```mermaid
flowchart LR
  Camera[PoE camera RTSP stream] --> Ring[Local short ring buffer]
  Ring --> Motion[Motion and scene change]
  Motion --> Segment[Event segmentation]
  Segment --> Frames[Selective frames or short clip]
  Frames --> Detector[Local object and person detector]
  Detector --> Gate{Enough confidence and value?}
  Gate -->|yes, local adequate| Event[Candidate event plus evidence]
  Gate -->|uncertain, eligible data| Vision[Stronger local or cloud vision model]
  Gate -->|low value| Expire[Expire candidate]
  Vision --> Event
  Event --> Core[Canonical observation and interpretation]
  Core --> Retain[Retention by sensitivity and value]
  Core --> Ask[Ask owner when uncertainty matters]
```

## 6. Model-routing architecture

```mermaid
flowchart TB
  Task[Model task request] --> Requirements[Modality, quality, latency, context]
  Requirements --> Privacy[Sensitivity and provider eligibility]
  Privacy --> Budget[Per-run and monthly budget]
  Budget --> Router[Deterministic routing policy]
  Router --> T0[Tier 0: no model]
  Router --> T1[Tier 1: tiny or local model]
  Router --> T2[Tier 2: medium model]
  Router --> T3[Tier 3: frontier model]
  T0 --> Validate[Typed result and evidence]
  T1 --> Validate
  T2 --> Validate
  T3 --> Validate
  Validate --> Good{Schema and quality adequate?}
  Good -->|yes| Result[Result with route, cost and disclosure record]
  Good -->|no and eligible| Fallback[Bounded repair or fallback]
  Fallback --> Router
  Good -->|no route| Abstain[Abstain or ask owner]
```

## 7. Memory layers

```mermaid
flowchart TB
  Evidence[Raw evidence and source reference] --> Observation[Observation]
  Observation --> Interpretation[Interpretation with model and confidence]
  Interpretation --> Assertion[Assertion or hypothesis]
  Assertion --> Belief[Current belief projection]
  Belief --> Confirmed[Owner-confirmed fact or preference]
  Assertion --> Correction[Correction, dispute or supersession]
  Confirmed --> Correction
  Correction --> Belief

  Observation --> Episodic[Episodic memory]
  Belief --> Semantic[Semantic memory]
  Goals[Goals and policies] --> Working[Working context]
  Episodic --> Working
  Semantic --> Working
  Working --> Retrieval[Retrieval manifest]
  Retrieval --> Reasoning[Reasoning run]
  Observation --> Archive[Archive and retention]
  Semantic --> Vector[Rebuildable vector index]
```

## 8. Autonomous software-development loop

```mermaid
flowchart TB
  Need[Need or hypothesis detected] --> Proposal[Durable change proposal]
  Proposal --> Risk[Risk and authority classification]
  Risk --> Sandbox[Isolated worktree and sandbox]
  Sandbox --> Implement[Implementation]
  Implement --> Tests[Unit, integration, policy and security tests]
  Tests --> Replay[Historical replay and agent evals]
  Replay --> PR[Pull request with evidence]
  PR --> Gate{Risk-dependent review gate}
  Gate -->|rejected| Revise[Revise or abandon]
  Revise --> Proposal
  Gate -->|approved| Build[Signed artifact and SBOM]
  Build --> Stage[Staging]
  Stage --> Canary[Limited canary]
  Canary --> Observe[Observe guardrails and intended outcome]
  Observe --> Decide{Promote, modify or roll back?}
  Decide -->|promote| Prod[Production]
  Decide -->|modify| Proposal
  Decide -->|rollback| Rollback[Previous digest and config]
```

## 9. V1 deployment architecture

```mermaid
flowchart TB
  Owner[Owner device] -->|Tailscale or LAN| Console[Private Owner Console]
  Console --> API[Melloa core API]
  Telegram[Optional Telegram Bot API] <-->|outbound HTTPS long polling| TG[Telegram adapter]
  TG --> API

  subgraph MiniPC[Wired Linux mini-PC]
    subgraph Compose[Rootless Docker Compose]
      Console --> API
      API --> DB[(PostgreSQL and pgvector)]
      Worker[Melloa worker] --> DB
      API --> Broker[Capability broker]
      API --> Gateway[Model gateway]
      Perception[Frigate or perception adapter] --> API
      API --> Blobs[(Content-addressed blobs)]
      OTel[OpenTelemetry collector] -. telemetry .- API
      OTel -. telemetry .- Worker
    end
    Guardian[Guardian: systemd, firewall and revoke]
    Backup[restic backup]
  end

  Camera[PoE ONVIF and RTSP camera] --> Perception
  Gateway -->|eligible calls| Models[Approved model APIs]
  Backup --> DB
  Backup --> Blobs
  Backup -->|encrypted| Offsite[Offsite backup]
  Guardian -. stop and constrain .-> Compose
  Compose --x Guardian
```

## 10. Credential flow

```mermaid
sequenceDiagram
  participant Owner
  participant Root as Owner keyring or SOPS root
  participant Broker as Credential broker
  participant Policy
  participant Adapter as Capability adapter
  participant Provider
  participant Audit

  Owner->>Root: provision scoped provider credential
  Root->>Broker: encrypted reference or wrapped secret
  Adapter->>Broker: request lease for exact authorized action
  Broker->>Policy: verify actor, action, scope, budget, mode
  Policy-->>Broker: allow with constraints or deny
  Broker->>Broker: unwrap or mint short-lived scoped lease
  Broker-->>Adapter: lease bound to capability and action
  Adapter->>Provider: execute over approved destination
  Provider-->>Adapter: result or receipt
  Adapter->>Audit: action, lease reference, result, cost
  Adapter->>Broker: close or revoke lease
  Note over Adapter,Provider: Melli never receives a general secret bundle
```

## 11. Kill-switch architecture

```mermaid
flowchart LR
  Owner[Owner local or private authenticated path] --> Guardian[Guardian]
  Physical[Physical network or power cutoff] --> Host[Host and network]
  Guardian --> Mode[Signed mode: normal, no-actions, read-only, offline, stopped]
  Guardian --> Firewall[Block external egress]
  Guardian --> Revoke[Remove or revoke credentials]
  Guardian --> Services[Stop rootless workloads]
  Guardian --> Recovery[Start recovery and diagnostics]
  Mode --> Core[Melloa core reads mode only]
  Firewall --> Core
  Revoke --> Broker[Capability broker]
  Services --> Runtime[Autonomous runtime]
  Core --x Guardian
  Runtime --x Guardian
```

## 12. Permission and capability architecture

```mermaid
flowchart TB
  Install[Plugin installed] --> Declared[Declared capabilities, schemas, risk and data classes]
  Declared --> Disabled[Disabled by default]
  Owner[Owner] --> Grant[Capability grant with scope, expiry and budget]
  Grant --> Registry[Capability registry]
  Proposal[Action proposal] --> Canonical[Canonical exact action]
  Canonical --> Request[Authorization request]
  Registry --> Request
  Policy[Versioned policy] --> Decision[Decision engine]
  Request --> Decision
  Guardian[Guardian mode] --> Decision
  Decision --> Deny[Deny with reason]
  Decision --> Approve[Require exact owner approval]
  Decision --> Allow[Allow with obligations]
  Approve --> Bound[Approval bound to action hash and expiry]
  Bound --> Decision
  Allow --> Lease[Scoped credential and resource lease]
  Lease --> Execute[Capability execution]
  Execute --> Receipt[Result, side effects and audit receipt]
```

## 13. Goal hierarchy

```mermaid
flowchart TB
  Values[Values and non-negotiable constraints] --> Objectives[Long-term objectives]
  Objectives --> Goals[Current goals]
  Goals --> Strategies[Strategies]
  Strategies --> Hypotheses[Hypotheses]
  Hypotheses --> Experiments[Experiments or interventions]
  Experiments --> Actions[Actions]
  Actions --> Outcomes[Observed outcomes]
  Outcomes --> Evaluation[Evaluation with uncertainty and burden]
  Evaluation --> Strategies
  Evaluation --> Goals
  Conflicts[Competing goals and guardrails] --> Goals
  Owner[Owner review and override] --> Values
  Owner --> Goals
  Owner --> Experiments
```

## 14. Periodic reasoning loops

```mermaid
flowchart LR
  Continuous[Continuous: capture, validate, detect] --> Minutes[Minutes: interpret and update context]
  Minutes --> Daily[Daily: summarize new evidence and goal relevance]
  Daily --> Weekly[Weekly: patterns, intervention review, permission and cost anomalies]
  Weekly --> Monthly[Monthly: strategy, retention, archive, cost and capability review]
  Monthly --> Occasional[Occasional: propose new tool or integration]
  Occasional --> Change[Controlled change pipeline]
  Change --> Continuous
  Noop[No-op is a valid output] -. applies .-> Daily
  Noop -. applies .-> Weekly
  Budgets[Token, cost, interruption and freshness budgets] --> Daily
  Budgets --> Weekly
  Budgets --> Monthly
```

## 15. Data lifecycle

```mermaid
stateDiagram-v2
  [*] --> Collected
  Collected --> Quarantined: untrusted or invalid pending review
  Collected --> Active: validated and classified
  Quarantined --> Deleted: expiry or rejection
  Quarantined --> Active: validated and promoted
  Active --> Derived: interpretation, summary, embedding or projection
  Active --> Archived: lower-access retention tier
  Derived --> Superseded: correction or new version
  Superseded --> Archived
  Active --> DeletionPending: owner request or TTL
  Derived --> DeletionPending: source deletion or TTL
  Archived --> DeletionPending: retention expiry
  DeletionPending --> Deleted: primary stores erased and receipts written
  Deleted --> BackupExpiry: encrypted backup copies age out
  BackupExpiry --> [*]
```

## 16. Plugin and module interface

```mermaid
classDiagram
  class CapabilityManifest {
    +name
    +version
    +provider
    +actions
    +inputSchemas
    +outputSchemas
    +permissions
    +riskLevels
    +dataClasses
    +costModel
    +healthContract
  }
  class CapabilityAdapter {
    +describe()
    +validate(action)
    +execute(authorization, lease)
    +health()
    +close()
  }
  class CapabilityBroker {
    +authorize(request)
    +leaseCredential(decision)
    +recordReceipt(result)
  }
  class PolicyDecision {
    +effect
    +reason
    +constraints
    +obligations
    +approvalRequirement
    +policyVersion
  }
  class EventEnvelope {
    +id
    +type
    +schemaVersion
    +source
    +occurredAt
    +sensitivity
    +provenance
    +payload
  }
  CapabilityManifest --> CapabilityAdapter
  CapabilityBroker --> CapabilityAdapter
  CapabilityBroker --> PolicyDecision
  CapabilityAdapter --> EventEnvelope
```

## 17. Network topology

```mermaid
flowchart TB
  Internet((Internet))
  OwnerDevice[Owner laptop or phone]
  Router[Router and firewall]

  subgraph Admin[Admin network]
    OwnerDevice
  end

  subgraph Server[Server VLAN]
    MiniPC[Melloa mini-PC]
    Core[Core and DB]
    Guardian[Guardian]
    MiniPC --> Core
    MiniPC --> Guardian
  end

  subgraph Cameras[Camera VLAN]
    Cam[PoE camera]
  end

  subgraph SandboxNet[Sandbox network]
    Sandbox[Disposable sandbox]
  end

  OwnerDevice -->|Tailscale or LAN plus app auth| Console[Private Owner Console]
  Console --> Core
  OwnerDevice -->|separate owner auth| Guardian
  Cam -->|RTSP and ONVIF only| MiniPC
  Cam --x Internet
  Core -->|explicit HTTPS egress| Internet
  Sandbox -->|default deny; temporary allowlist| Internet
  Sandbox --x Core
  Router --> Admin
  Router --> Server
  Router --> Cameras
```

## 18. CI and CD flow

```mermaid
flowchart LR
  Branch[Agent or human branch] --> Static[Format, type, lint, secret scan]
  Static --> Unit[Unit and property tests]
  Unit --> Contract[Schema and migration compatibility]
  Contract --> Security[Dependency, license and security checks]
  Security --> Replay[Replay and model evals]
  Replay --> PR[Evidence-rich pull request]
  PR --> Review{CODEOWNERS and risk gate}
  Review -->|reject| Branch
  Review -->|approve| Build[Build pinned image]
  Build --> SBOM[SBOM, provenance and signature]
  SBOM --> Stage[Staging on scrubbed or replay data]
  Stage --> Canary[Bounded canary]
  Canary --> Metrics[Guardrails, costs and outcomes]
  Metrics -->|pass| Promote[Promote exact digest]
  Metrics -->|fail| Rollback[Automatic or owner rollback]
```

## 19. Threat model

```mermaid
flowchart TB
  Attacker[Internet or local attacker]
  MaliciousData[Malicious web, message, document or visible text]
  Supply[Compromised dependency or contributor]
  Provider[Compromised provider account or model]
  LostDevice[Stolen owner device]
  Agent[Compromised autonomous agent]

  Inputs[Untrusted input boundary]
  Build[Build and supply chain]
  Auth[Owner and capability auth]
  Secrets[Secrets and credential broker]
  Data[Personal data and memory]
  Actions[External side effects]
  Guardian[Guardian]

  MaliciousData --> Inputs --> Agent
  Supply --> Build --> Agent
  Provider --> Agent
  LostDevice --> Auth
  Attacker --> Inputs
  Attacker --> Auth
  Agent --> Secrets
  Agent --> Data
  Agent --> Actions

  Controls[Validation, taint, policy, sandbox, egress, scopes, audit] --> Inputs
  Controls --> Build
  Controls --> Auth
  Controls --> Secrets
  Controls --> Actions
  Guardian -. revoke and stop .-> Agent
  Agent --x Guardian
```

## 20. Onboarding flow

```mermaid
flowchart TB
  Empty[Empty supported Linux machine] --> Host[Patch, users, disk, SSH and time]
  Host --> Network[Private access and firewall]
  Network --> Clone[Clone and verify pinned release]
  Clone --> Doctor[Run doctor and inspect planned changes]
  Doctor --> Init[Create owner and Melli identities]
  Init --> Secrets[Configure age, SOPS and scoped API keys]
  Secrets --> Core[Start Postgres and core in no-actions mode]
  Core --> Migrate[Run migrations and deep health check]
  Migrate --> Console[Authenticate to private Owner Console]
  Console --> Validate[Conversation, fake model, policy denial, correction and audit tests]
  Validate --> Telegram[Optionally pair exact Telegram owner IDs locally]
  Telegram --> Guardian[Install and exercise independent Guardian]
  Guardian --> Backup[Backup and restore on clean machine]
  Backup --> Actions[Enable conservative ordinary actions]
  Actions --> Camera[Optionally add isolated and calibrated camera]
```

## 21. Realistic room-event to intervention sequence

```mermaid
sequenceDiagram
  participant Cam as Camera
  participant P as Perception
  participant Core as Core
  participant DB as Event and memory store
  participant Melli
  participant Policy
  participant Owner
  participant Change as Change pipeline

  Cam->>P: scene changes
  P->>P: segment and run local detector
  P->>Core: person entered candidate, confidence and evidence hashes
  Core->>DB: append observation and interpretation
  Core->>Melli: assess immediate relevance
  Melli->>Policy: no external action proposal
  Policy-->>Melli: allowed
  Melli->>DB: record decision and evidence IDs

  Note over DB,Melli: Daily reflection later
  Melli->>DB: retrieve recent routine events and corrections
  Melli->>DB: write uncertain pattern hypothesis
  Melli->>Owner: propose bounded reminder experiment
  Owner-->>Melli: approve exact experiment
  Melli->>Policy: request schedule and owner-only message capability
  Policy-->>Melli: allow with budget and expiry
  Melli->>Change: implement and test low-risk workflow
  Change-->>Melli: signed canary artifact
  Melli->>Policy: deploy canary request
  Policy-->>Melli: allow reversible internal class
  Melli->>DB: intervention and deployment records
  Note over Cam,DB: Outcomes arrive over subsequent days
  Melli->>DB: evaluate observed behavior, owner feedback and confounders
  Melli->>Owner: report useful, harmful or inconclusive result
```

## 22. Provenance entity relationships

```mermaid
erDiagram
  SOURCE ||--o{ OBSERVATION : emits
  OBSERVATION ||--o{ EVIDENCE_LINK : has
  BLOB ||--o{ EVIDENCE_LINK : referenced_by
  OBSERVATION ||--o{ INTERPRETATION : interpreted_as
  MODEL_RUN ||--o{ INTERPRETATION : produced
  INTERPRETATION ||--o{ ASSERTION : supports
  ASSERTION ||--o{ ASSERTION_EVIDENCE : justified_by
  OBSERVATION ||--o{ ASSERTION_EVIDENCE : evidence_for
  ASSERTION ||--o{ ASSERTION_RELATION : supersedes_or_disputes
  ASSERTION ||--o{ BELIEF_PROJECTION : projects
  OWNER_CONFIRMATION ||--o{ ASSERTION : confirms_or_corrects
  GOAL ||--o{ HYPOTHESIS : motivates
  HYPOTHESIS ||--o{ INTERVENTION : tested_by
  INTERVENTION ||--o{ ACTION : contains
  ACTION ||--|| POLICY_DECISION : authorized_by
  ACTION ||--o{ OUTCOME : produces
  OUTCOME ||--o{ EVALUATION : assessed_by
  CHANGE_PROPOSAL ||--o{ DEPLOYMENT : becomes
  DEPLOYMENT ||--o{ OUTCOME : observed_through
```

## 23. Guardian state machine

```mermaid
stateDiagram-v2
  [*] --> Stopped
  Stopped --> Offline: owner starts local-only services
  Offline --> ReadOnly: permit reads and local analysis
  ReadOnly --> NoActions: permit state updates but no side effects
  NoActions --> Normal: owner enables policy-bounded actions
  Normal --> NoActions: suspicious action or owner pause
  Normal --> Offline: provider or network incident
  Normal --> Stopped: emergency stop
  NoActions --> ReadOnly: integrity or migration incident
  Offline --> Stopped: host or credential incident
  ReadOnly --> Stopped: recovery escalation
  Stopped --> Recovery: owner enters isolated diagnostics
  Recovery --> Stopped: repair complete, restart requires explicit transition
  note right of Normal
    Melli cannot change Guardian state.
    Core consumes signed/read-only mode.
  end note
```

## 24. Replay and simulation architecture

```mermaid
flowchart LR
  Snapshot[Historical state snapshot] --> Engine[Replay engine]
  Events[Versioned event stream] --> Engine
  Clock[Virtual clock] --> Engine
  Policy[Policy version under test] --> Engine
  Route[Model or prompt under test] --> Engine
  FakeCaps[Simulated capability receipts] --> Engine
  Engine --> Runs[Candidate runs with side effects disabled]
  Runs --> Compare[Compare decisions, calls, cost, latency and privacy]
  Baseline[Baseline expectations and distributions] --> Compare
  Compare --> Gate{Release thresholds}
  Gate -->|pass| Evidence[Attach evidence to change proposal]
  Gate -->|fail| Diagnose[Failure clusters and regression cases]
  Diagnose --> Route
```

## 25. Identity continuity and worker lifecycle

```mermaid
flowchart TB
  Melloa[Melloa runtime and deployment] --> Registry[Persistent intelligence registry]
  Registry --> Melli[Melli identity]
  Melli --> Memory[Long-term memory and relationships]
  Melli --> Goals[Goals, values and policies]
  Melli --> History[Change and interaction history]
  Melli --> Session[Reasoning run]
  Session --> ModelA[Foundation model A]
  Session --> ModelB[Foundation model B]
  Session --> Worker[Ephemeral specialist worker]
  Worker --> Tools[Scoped tools and context]
  Worker --> Result[Result and evidence]
  Result --> Session
  ModelA -. replaceable .-> Session
  ModelB -. replaceable .-> Session
  Session -. terminates .-> Melli
  note right of Melli
    Identity does not equal model,
    process, session or provider.
  end note
```

## 26. Schema evolution and replay

```mermaid
flowchart TB
  V1[Event schema v1] --> Envelope[Stable envelope and immutable payload version]
  V2[Event schema v2] --> Envelope
  Envelope --> Store[(Canonical store)]
  Store --> Reader1[v1 reader or adapter]
  Store --> Reader2[v2 reader]
  V1 --> Upcast[Explicit v1 to v2 upcaster]
  Upcast --> Reader2
  Store --> Replay[Replay harness]
  Replay --> Projection[Rebuild current projection and indexes]
  Projection --> Verify[Compatibility and semantic invariant checks]
  Verify --> Deploy[Deploy new readers]
  Deploy --> Contract[Later contract or retire old field]
  Raw[Preserved source evidence where justified] --> Replay
```

## Diagram maintenance rules

- Update a diagram in the same pull request as the boundary it documents.
- Use direction and labels to show authority, not only connectivity.
- Mark forbidden paths and external trust explicitly.
- Do not show a future component as if it exists in V1.
- Keep canonical component names consistent with the conceptual model.
- Render diagrams in CI or at least parse-check Mermaid fences before release.
