# Onboarding, operations, and roadmap

## Purpose

Define the reproducible path from an empty machine to a useful V1, the operational procedures that keep it understandable, and a milestone sequence that validates value before adding autonomy and sensors.

## Prerequisite profiles

### Minimum setup

- x86-64 Linux machine with 16 GB RAM, 200 GB free SSD, and a reliable network;
- owner laptop/phone on the same private network;
- Git, Ansible, rootless Docker/Compose support;
- one hosted model API key with a small budget;
- A modern browser for the private Owner Console;
- USB or separate local backup target.

No Telegram account, camera, public domain, cloud VM, Kubernetes, GPU, or native app is required for the minimum synthetic/local setup.

### Recommended setup

- dedicated wired mini-PC, 32 GB RAM, 1 TB NVMe;
- full-disk encryption, UPS, Tailscale/private remote access;
- PoE ONVIF Profile T camera on an isolated VLAN;
- 1–2 TB USB backup disk and encrypted B2/equivalent offsite repository;
- GitHub account/repository with protected main and CI;
- separate provider credentials for development and production.

### Advanced setup

- separate edge/perception node or GPU/model node;
- managed switch with VLANs and firewall rules;
- hardware-backed owner keys;
- second recovery host, PITR, stricter egress proxy;
- native mobile client or additional capabilities;
- OpenTofu for nontrivial cloud infrastructure.

Advanced is not “better” until requirements justify it.

## Installation journey

The exact commands will evolve with implementation, but the product contract is:

### 1. Prepare the host

1. Install supported Debian/Ubuntu LTS, set hostname/timezone/NTP, patch it, and enable disk encryption as appropriate.
2. Create an owner admin account and a separate unprivileged Melloa service account.
3. Configure SSH keys and disable password/root remote login.
4. Attach local backup storage and document device identifiers.
5. Install Git and Ansible; run the signed/pinned bootstrap playbook.

### 2. Establish private access and network zones

1. Join Tailscale or configure the chosen private WireGuard path.
2. Apply host default-deny firewall rules with an automatic rollback timer.
3. Verify the owner can reach the private admin endpoint and local console recovery remains possible.
4. When adding a camera, create the camera VLAN and verify it cannot reach the internet or core database.

### 3. Clone and inspect

```bash
git clone <melloa-upstream-or-fork>
cd melloa
git verify-commit <release-or-pinned-commit>
less SECURITY.md
less docs/deployment/blessed-v1.md
melloa doctor
```

The installer shows every dependency, port, external endpoint, directory, data class, and credential before changing the host.

### 4. Initialize owner and deployment configuration

```bash
melloa init --deployment home
melloa identity create-owner
melloa identity create-intelligence --working-name Melli
```

Initialization creates stable IDs, safe sample policy, retention defaults, cost ceilings, quiet hours, and an explicit list of disabled capabilities. It does not invent goals on the owner’s behalf.

### 5. Configure secrets

1. Generate an age recipient whose private identity is held in the owner OS keyring/offline recovery path.
2. Add a model token through `melloa secret set`; add a Telegram token only when enabling that optional adapter. Secrets produce a SOPS-encrypted file or broker entry.
3. Confirm secrets are absent from process arguments, Git diff, logs, and container images.
4. Configure low provider-side spend limits and narrow API scopes.

### 6. Start the state layer

```bash
melloa up --profile core --no-actions
melloa migrate --check
melloa migrate apply
melloa status --deep
```

Run in Guardian `no-actions`/offline mode first. Verify Postgres roles, event append, audit linkage, jobs, and schema version.

### 7. Open and verify the private Owner Console

1. Open the private console through the local LAN or Tailscale address and complete owner authentication.
2. Start a conversation, inspect its canonical message/turn record, and verify cited provenance and a correction flow.
3. Inspect system health, cost/disclosure, and Guardian status without granting the core Guardian authority.
4. Optionally enable Telegram, create/configure the bot using Telegram’s owner tooling.
2. Start long polling.
3. Send `/start`; the local console shows a one-time pairing code and exact numeric user/chat IDs.
4. Confirm pairing locally; reject all other senders/groups.
5. Test text, duplicate update, denied action, approval expiry, and token-revocation paths.

### 8. Validate reasoning and memory

- Use deterministic fake-model smoke tests first.
- Enable one provider route for public/internal data.
- Enter a correction and verify observation → interpretation → belief → confirmation links.
- Inspect the disclosure and cost records.
- Run a replay against the smoke scenario.

### 9. Install and test Guardian

- Install the independently controlled systemd unit/CLI from its protected source.
- Verify `no-actions`, `read-only`, `offline`, and `stopped` modes.
- Verify Melloa containers cannot alter Guardian files, firewall, or credentials.
- Revoke a test provider token and confirm the capability degrades safely.

### 10. Configure backups and prove restoration

```bash
melloa backup init --local ...
melloa backup init --offsite ...
melloa backup run
melloa backup verify
```

Restore to a clean VM or spare disk, start read-only, and verify identity/policy/audit/blob samples. Do not declare installation complete before this succeeds.

### 11. Enable ordinary actions

After reviewing policies, switch from `no-actions` to normal operation. Start with conversation, memory, status, and owner-only notifications; no third-party messages or self-deployment.

### 12. Add camera later

1. Mount the PoE camera in the owner’s private space with consent and visible status.
2. Change unique credentials, update firmware, disable vendor cloud/P2P and unnecessary services.
3. Configure ONVIF/RTSP to perception only.
4. Calibrate day/night/occlusion scenarios using local candidate events.
5. Confirm camera-off and retention deletion behavior.
6. Enable cloud image escalation only after reviewing the data-class route.

## Operational runbooks

Each runbook includes prerequisites, impact, exact commands, validation, rollback, data-risk notes, and an incident/change record.

### Upgrade Melloa

- Read release/ADR/migration notes; verify signature and digest.
- Run backup and restore compatibility check.
- Replay representative history and run policy/eval gates.
- Deploy in `no-actions` or staging; run health checks.
- Canary changed workflows, then promote or roll back to previous digest/config.

### Replace a camera

- Disable camera capability and preserve the last heartbeat/error.
- Put new device on isolated provisioning network; update firmware and credentials.
- Configure profile/stream, time, bitrate, and low-light settings.
- Rebind the physical sensor identity rather than silently reusing evidence identity.
- Recalibrate zones/classification and verify deletion/retention.

### Rotate an API key

- Create a new narrowly scoped key and provider-side budget.
- Insert through broker/SOPS; test with one capability.
- Switch atomically; revoke old key; verify no failed queue storm.
- Record rotation, scope, and any exposure investigation.

### Restore backup

Follow the clean-host, Postgres-only, offline/read-only, integrity, index-rebuild, adapter-by-adapter procedure in the reliability specification. Record actual RPO/RTO.

### Migrate database

- Restore a representative copy, run compatibility and timing tests.
- Use expand/migrate/contract; snapshot first.
- Stop affected writers or use a safe online pattern.
- Validate row counts, constraints, provenance links, and replay.
- Do not contract/remove old fields until all readers are upgraded and rollback window ends.

### Debug missing events

Trace: source heartbeat → raw/candidate evidence → validation/quarantine → durable ingestion/deduplication → job state → interpretation → projection/index. Check clock, queue quotas, retention, source permissions, and dead-letter state. Never create a synthetic “observed” event to hide a gap.

### Debug an agent run

Open the run graph: retrieval manifest, model route/version, prompt version, schema attempts, policy request/decision, capability receipts, cost, and outcome. Reproduce in replay with side effects disabled. Avoid turning on unbounded raw debug logging.

### Disable a plugin/capability

- Revoke new grants and credential leases.
- Stop its worker/adapter.
- Drain or expire queued work deliberately.
- Preserve audit and source data according to retention.
- Verify no route still references the capability.

### Inspect costs

Report month/day by provider, model, goal, capability, periodic loop, and failed/retried run. Compare estimate vs billed provider data. Pause experiments before owner-requested core functions.

### Roll back a deployment

- Guardian enters `no-actions` if side-effect correctness is uncertain.
- Deploy previous signed image/config.
- Do not reverse incompatible data blindly; use migration recovery plan.
- Replay the incident, document root cause, and add regression cases.

### Emergency shutdown

1. Owner invokes Guardian locally/private path or physical network/power control.
2. Guardian sets `stopped`, blocks egress, stops Melloa/perception/sandbox workloads, and revokes/removes credentials.
3. Preserve disks/logs unless immediate privacy risk requires disconnecting storage.
4. Do not restart in normal mode; inspect from recovery environment/read-only copy.
5. Rotate possibly exposed credentials and review actions/egress before recovery.

## Roadmap principles

- Each phase must create direct owner value and operational evidence.
- Add one new authority/data boundary at a time.
- Camera follows trustworthy text/memory/policy foundations, not the reverse.
- Self-modifying software follows replay, CI, rollback, and Guardian—not before.
- A capability is complete only with security, retention, observability, test, and runbook paths.

## Milestones

### Phase 0 — architecture skeleton

**Outcome:** reproducible repo, docs, schemas, DB, Guardian modes, audit, CI, backup/restore.

Exit criteria: clean install; schema/event append; policy deny; cost/audit trail; restored system boots read-only.

### Phase 1 — private owner conversation and provenance memory

**Outcome:** canonical conversation, private Owner Console, one owner, model gateway, correction-aware memory, structured decision records, disclosure/cost records, and optional Telegram long polling.

Exit criteria: useful daily conversation; cited memory; provider outage fallback; no external side effects beyond owner messages.

### Phase 2 — reflection and intervention discipline

**Outcome:** daily digest, weekly review, explicit goals/hypotheses/interventions, proactivity budgets, owner feedback.

Exit criteria: at least one intervention is stopped or changed based on evidence; notification burden is measured.

### Phase 3 — camera observation

**Outcome:** PoE camera, local segmentation/detection, probabilistic events, retention controls, selective escalation.

Exit criteria: calibrated error profile, no continuous cloud stream, camera-off/deletion verified, missed intervals visible.

### Phase 4 — controlled software creation

**Outcome:** isolated worktree/sandbox, coding adapter, CI/evals, signed artifact, staging/canary/rollback.

Exit criteria: Melli creates and retires one low-risk internal tool with owner-visible benefit evidence and no governance authority.

### Phase 5 — additional capabilities

Add HealthKit, calendar, computer context, files, voice, or environmental sensors one at a time based on goal value. Each requires a data contract, policy profile, threat review, and deletion/export path.

### Phase 6 — measured distribution

Split edge/model/workflow components only after actual scale, isolation, or availability data crosses documented thresholds.

## First 30, 90, and 365 days

### First 30 days

- Freeze vocabulary and the event/provenance/capability contracts.
- Build host bootstrap, Postgres, canonical conversation, private Owner Console shell, audit, policy broker skeleton, model adapter, cost ceilings, Guardian modes, optional Telegram pairing, and backup restore.
- Use only conversation/status/memory correction; collect operator friction and failure data.
- Publish ADRs and threat model before adding camera.

### First 90 days

- Daily/weekly reflection with quiet-hour/frequency budgets.
- Replay/eval harness and private correction-derived regression set.
- Goal/hypothesis/intervention records and one reversible N-of-1-style experiment.
- Add camera locally only after retention/network/perception tests.
- Complete first security incident simulation and second restore drill.

### First 365 days

- Prove months of reliable provenance, correction, cost, and intervention history.
- Introduce controlled generated-code workflow for low-risk internal artifacts.
- Add at most a few high-value capabilities, not an integration catalogue.
- Reassess database/job/event thresholds, local model economics, hardware, and client needs using observed data.
- Perform independent security/privacy review, name clearance, release compatibility policy, and open-source V1 release only if operations are reproducible.

## Explicitly not in the first year unless evidence changes

Kubernetes, public SaaS/multi-tenancy, autonomous financial transactions, autonomous cloud IAM, permanent multi-agent society, continuous multi-camera cloud video, generalized voice surveillance, marketplace, and a native mobile app before the channel contract proves stable.
