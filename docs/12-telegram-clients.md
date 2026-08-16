# Private Owner Console, conversation, and client architecture

## Purpose

Define Melloa's first-party conversation and inspection experience without confusing a client, transport, model context, or messaging account with Melli's identity or durable memory.

## Decision

Build a **canonical conversation service** and a **private Owner Console** in V1. The console is the primary client. It runs as part of the Melloa deployment, is available only through the local LAN or private network, and requires application authentication in addition to network membership.

Support Telegram Bot API long polling as an **optional secondary remote adapter**. It is useful for concise conversation, proactive notifications, and approvals while away from the console, but it is not the source of identity, conversation truth, memory, or root control. [S25](research/primary-sources.md#S25) [S26](research/primary-sources.md#S26)

## Canonical conversation model

A client submits or renders Melloa-owned records:

```text
ConversationThread
  id
  owner_id
  intelligence_id
  title and status
  sensitivity and retention policy
  created_at and updated_at

ConversationMessage
  id and thread_id
  author principal and source client
  content parts and attachment references
  reply/citation/correction links
  delivery state
  created_at and observed_at

ConversationTurn
  triggering message IDs
  retrieval manifest and evidence IDs
  model/prompt/runtime versions
  structured decision record
  proposed and executed actions
  output message IDs
  cost, latency, disclosure, and outcome references
```

Telegram chat IDs, browser session IDs, provider request IDs, and model context windows remain adapter/runtime metadata. They never become the canonical conversation identifier.

## Owner Console V1 areas

### Conversation

- direct text conversation with Melli;
- streamed or incremental responses where supported;
- attachments under explicit type, size, sensitivity, and retention policy;
- cited memory and evidence links;
- owner corrections, disputes, confirmations, and follow-up questions;
- visible pending approvals and action proposals.

### Timeline and provenance

- chronological observations, interpretations, beliefs, corrections, decisions, actions, deployments, and outcomes;
- confidence, alternatives, evidence, source, model/detector/prompt version, and supersession history;
- filters by time, capability, goal, data class, and intelligence.

### Memory

- search and inspect memories with provenance;
- distinguish observation, interpretation, belief, and owner-confirmed fact;
- correct, dispute, expire, delete, or change retention where permitted;
- show which conversations, events, and decisions used a memory.

### Runs and decisions

For each reasoning or automation run, show:

- trigger and selected inputs;
- retrieval manifest and evidence IDs;
- model/provider, prompt, policy, code, and schema versions;
- concise structured rationale, assumptions, uncertainty, alternatives, and selected plan;
- tool/capability requests, policy decisions, approvals, credential-lease references, and action receipts;
- costs, latency, external disclosures, retries, failures, and observed outcomes.

This is an auditable decision record, not raw hidden chain-of-thought. Melloa must not rely on private internal reasoning traces for reproducibility or trust.

### Media

- camera-event frames and clips retained under policy;
- event boundaries, interpretation confidence, retention expiry, and disclosure history;
- correction and deletion controls;
- camera health and missing-interval visibility.

### Operations

- application, worker, database, queue, provider, camera, storage, backup, and deployment health;
- costs, request budgets, rate limits, loop breakers, and external data disclosures;
- installed capabilities, grants, policies, quiet hours, notification budgets, and pending approvals;
- recent migrations, software versions, canaries, rollbacks, and recovery evidence.

### Guardian boundary

The console may display Guardian mode and health through a read-only/status contract. High-impact Guardian changes use a separately authenticated owner path controlled by the Guardian repository and host. The ordinary Melloa backend cannot grant itself Guardian authority.

## Authentication and network exposure

- Bind the console/API only to loopback, LAN, or the private network; no public ingress in V1.
- Require application authentication; Tailscale or LAN membership alone is insufficient.
- Use secure, short-lived sessions and CSRF protection for browser actions.
- Require recent reauthentication for high-impact approvals, exports, deletions, policy changes, and Guardian handoff.
- Keep a local recovery path when the private-network control plane is unavailable.
- Redact sensitive content from browser notifications, logs, telemetry labels, and URL parameters.

The exact V1 authentication implementation should be selected during implementation from maintained components that support local/private deployment and strong owner authentication. The domain contract depends on an authenticated owner principal, not one identity vendor.

## Client adapter contract

```text
ClientAdapter
  receive() -> authenticated inbound message event
  send(authorized message) -> delivery result
  edit/delete/reply() -> optional transport operations
  fetch_attachment(reference) -> quarantined blob
  capabilities() -> media, limits, interactivity, security profile
  health() -> status and rate limits
```

The domain sees normalized messages and delivery records. Client-specific identifiers stay in adapter metadata.

## Telegram secondary adapter

### Processing

1. Call `getUpdates` with a positive long-poll timeout.
2. Validate update schema and size.
3. Confirm the exact paired owner user and private chat before downloading attachments.
4. Persist an immutable inbound observation and deduplication key using `update_id`.
5. Quarantine and hash permitted attachments.
6. Append the normalized message to the canonical conversation.
7. Pass every side-effecting request through the capability broker.
8. Advance the offset only after durable ingestion.

### Default restrictions

| Data or action | Telegram default |
|---|---|
| Ordinary owner conversation | allowed when channel sensitivity policy permits |
| Concise reminders, status, and approvals | allowed within notification and preview policy |
| Raw room frames or clips | denied unless explicitly requested and approved for that data class |
| Highly sensitive memory detail | minimal notification with private-console link |
| Secrets and recovery codes | always denied |
| Guardian root changes | not authorized solely through Telegram |
| Full export or archive | never attached; use private/local transfer |

Telegram outages or disablement must not prevent local conversation, sensing, memory, reasoning, or Guardian operation.

## Alternatives

- **Public web application:** rejected for V1 because it adds internet ingress, public authentication, rate-limiting, certificate, patching, and incident-response burdens without need.
- **Telegram as the primary UI:** rejected because it cannot provide the required high-trust inspection, media, provenance, policy, and operations experience.
- **Native mobile application:** valuable later for local authentication, HealthKit, notifications, and device integration, but unnecessary before the conversation and client contracts stabilize.
- **Matrix or another messaging system:** possible future adapters; they do not replace the first-party console.

## Failure modes

- **Console unavailable:** core ingestion and queued work continue; CLI and Guardian paths remain available; no authorization bypass.
- **Session theft:** revoke sessions, require reauthentication, preserve audit, and keep Guardian credentials separate.
- **Telegram token leak:** disable adapter egress, revoke token, rotate broker secret, and re-pair.
- **Duplicate message:** deduplicate using canonical/client IDs and idempotency keys.
- **Malicious attachment:** reject or quarantine before parser/model access; treat contents as untrusted data.
- **Incorrect decision explanation:** retain evidence and deterministic metadata; structured rationale is a model-produced artifact and not privileged truth.

## Build now

- Canonical thread/message/turn/delivery records and channel-independent application use cases.
- Private Owner Console shell and authenticated conversation.
- Timeline, provenance, memory correction, run/decision, media, health, cost, and disclosure views sufficient for V1 milestones.
- Read-only Guardian status integration and clear handoff to the separate Guardian control path.
- Fake client adapter and deterministic fixtures for development and replay.
- Optional Telegram long-polling adapter with pairing, allowlist, durable offsets, attachment quarantine, and conservative sensitivity policy.

## Design for

- Additional messaging clients, native mobile applications, voice, local displays, and accessibility features.
- Stronger passkey/hardware-backed authentication and delegated multi-device sessions.
- Multiple persistent intelligences and explicitly partitioned conversations.
- Client-specific redaction, notification preview, and offline synchronization policies.

## Defer

- Public web ingress, multi-user tenancy, group bots, third-party recipients, native mobile release, and raw hidden chain-of-thought capture.
