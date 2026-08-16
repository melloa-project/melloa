# Deployment, networking, and infrastructure

## Purpose

Provide one reproducible, secure-enough deployment path for a technically sophisticated owner without turning a one-person system into a miniature cloud platform.

## Blessed V1 deployment

Melloa runs on one wired Linux mini-PC in the owner’s home. Rootless Docker Compose manages application containers; host-owned systemd units manage the Guardian, firewall, encrypted-secret bootstrap, backups, and selected health checks. Ansible establishes the host. No public domain or public reverse proxy is required.

Docker Compose is an appropriate declarative model for a small multi-container application and supports services, networks, volumes, configs, and secrets without a cluster control plane. [S40](research/primary-sources.md#S40) Ansible supplies idempotent host configuration and operational playbooks. [S41](research/primary-sources.md#S41)

## Physical and logical topology

| Zone | Members | Trust | Connectivity |
|---|---|---|---|
| Owner/admin | owner laptop/phone over local LAN or Tailscale | high, separately authenticated | Owner Console, admin API, Guardian SSH/CLI |
| Melloa core | core, workers, Postgres, local observability | trusted application, not root authority | selected outbound APIs; camera/perception; private clients |
| Perception | Frigate/go2rtc/detectors | handles untrusted media | camera VLAN ingress; structured candidate output to core |
| Camera VLAN | PoE camera(s) | low-trust embedded devices | NTP/DNS if needed; RTSP/ONVIF only to perception; no internet |
| Generated-code sandbox | disposable workloads | hostile-by-default | no ingress; default-deny egress; test fixtures only |
| Guardian | root-owned host unit and owner CLI | highest local control plane | can control services/firewall/credentials; not reachable by Melli capability API |
| External providers | LLM APIs, Telegram, GitHub, backup target | outside trust boundary | explicit TLS destinations and scoped credentials |

Tailscale is the convenient private-access default, using WireGuard-based encrypted connections and an identity/control layer. [S54](research/primary-sources.md#S54) Melloa must not make Tailscale identity semantics part of domain contracts; native WireGuard or another private network is an escape path. WireGuard itself is a compact VPN protocol rather than an application authorization system. [S55](research/primary-sources.md#S55)

## Host baseline

- Debian stable or Ubuntu LTS on x86-64.
- Full-disk encryption where unattended boot requirements permit, with documented recovery key storage.
- Separate unprivileged service users for rootless Docker and backup operations.
- SSH keys/passkeys, no password login, no routine root login.
- Host firewall default-deny inbound except SSH/Tailscale and explicitly required local services.
- Automatic security update download; controlled installation/reboot with health verification.
- SMART/NVMe monitoring, disk-space alerts, time synchronization, log rotation.
- UPS for areas with unreliable power or where camera/event continuity matters.

## Container layout

Suggested Compose projects or profiles:

```text
core:       melloa-core, melloa-web, melloa-worker, postgres
perception: frigate, go2rtc, detector adapter
observe:    otel-collector, optional local metrics/log UI
models:     optional local model server
sandbox:    created on demand, isolated network, disposable volumes
```

Rules:

- Pin images by digest for deployment; track human-readable version separately.
- Run as non-root, read-only root filesystem where practical, minimal capabilities, health checks, resource limits.
- Use named volumes with documented ownership and backup inclusion.
- Do not mount `/var/run/docker.sock` into an agent-accessible container.
- Do not make the Postgres port reachable from the LAN.
- Split networks so perception cannot access model-provider credentials and sandbox cannot access core state.
- Store generated artifacts in content-addressed volumes and pass references, not ambient shared directories.

## Ingress and egress matrix

| Source | Destination | V1 policy |
|---|---|---|
| Owner device | Owner Console/private API | Tailscale/LAN only; strong application authentication |
| Telegram cloud | host | none for long polling; core initiates outbound HTTPS |
| Core | Telegram Bot API | allow exact service; rate/cost/audit controls |
| Core/model gateway | approved model providers | destination and data-class policy; TLS; recorded egress manifest |
| Perception | camera | RTSP/ONVIF from camera VLAN only |
| Camera | internet | deny |
| Camera | core DB | deny |
| Sandbox | internet | deny by default; short-lived allowlist lease when tests require it |
| Sandbox | production DB/secrets | deny |
| Backup process | B2/offsite target | scheduled, scoped credentials, append/retention protection where possible |
| Melloa containers | Guardian control socket/credentials | deny |

Domain allowlists are an operational aid, not a complete defense: provider CDNs and DNS can change. The enforced unit should be a brokered capability plus network constraints, with fail-closed behavior for sensitive paths.

## Data volumes

- `postgres-data`: primary state; encrypted disk; logical backups and optional physical/WAL plan later.
- `blob-store`: content-addressed observations, clips, artifacts; per-object metadata and retention.
- `model-cache`: rebuildable, not part of irreplaceable backup.
- `telemetry`: local, redacted, short retention.
- `quarantine`: no-exec, size bounded, auto-expiring untrusted attachments.
- `exports`: owner-triggered, encrypted or protected, time-limited staging.

Each volume has an owner, sensitivity class, retention, backup policy, and restore test. “Persistent volume” is not synonymous with “must back up.”

## Cloud footprint

V1 cloud dependencies are services, not a second runtime:

- one or more model-provider APIs;
- Telegram Bot API;
- GitHub or another Git forge/CI service;
- Backblaze B2 or equivalent encrypted offsite backup;
- optional Tailscale coordination.

Melloa does not require a public domain, cloud VM, managed database, Kubernetes cluster, object-storage gateway, or cloud control plane. Cloud services may be replaced through adapters and exported data.

## Infrastructure as code

### Build now

- Docker Compose for application topology.
- Ansible for OS packages, users, firewall, Docker rootless setup, directories, systemd Guardian, backup timers, and health verification.
- SOPS-encrypted deployment configuration with age recipients.
- Versioned migration and rollback commands.

### Add OpenTofu when

Use OpenTofu only after Melloa owns nontrivial cloud resources whose lifecycle must be planned and reviewed: multiple environments, IAM roles, networking, compute, managed storage, or infrastructure dependencies. OpenTofu maintains declarative infrastructure state and planning, but a state file and cloud credentials are themselves sensitive operational assets. [S57](research/primary-sources.md#S57)

### Do not add Kubernetes merely because

- there are several containers;
- self-healing sounds desirable;
- a future multi-node topology is imaginable;
- generated services might exist someday.

Revisit a cluster orchestrator when there are multiple independently operated nodes, strict scheduling/isolation needs, many deployable services, or uptime requirements that exceed restore-on-one-host. Until then, it would create more control-plane state than value.

## Remote administration

- Primary: owner device over Tailscale/private LAN.
- Recovery: local keyboard/console or physical access.
- SSH restricted by host firewall and keys; no SSH capability is exposed to Melli.
- Guardian commands require owner-controlled credentials and may require a local confirmation for the highest-impact changes.
- The Owner Console and sensitive APIs bind only to loopback/private interfaces and use application authentication in addition to network membership.

## Growth path

1. **One host:** core, DB, perception, optional local model.
2. **Edge camera node:** move perception near the camera; signed event/blob upload; retain core authority centrally.
3. **Compute node:** move local model/sandbox to GPU-capable machine; use narrow APIs and workload identity.
4. **Second-site backup/recovery host:** tested restore, not active-active complexity.
5. **Distributed control only if justified:** introduce durable messaging/workflow engine and workload identities behind existing ports.

Migration thresholds must be measured. Examples: sustained job backlog beyond recovery objective; more than three independently upgraded nodes; inability to isolate noisy workloads; or availability requirements that a one-host restore cannot satisfy.

## Failure modes

- **Single-host failure:** deliberate V1 trade-off; clean-machine restore and spare/storage plan matter more than pseudo-HA.
- **Tailscale/control-plane outage:** local LAN and console still work; WireGuard-compatible migration path.
- **Firewall misconfiguration:** Guardian recovery console and versioned rules; apply with rollback timer.
- **Compose upgrade breaks state:** pin versions/digests, preflight backup, staging on restored data.
- **Disk fills from media/telemetry:** hard quotas, retention worker, reserved database headroom, alerts at multiple thresholds.
- **Compromised camera:** isolated VLAN, no internet, unique credentials, firmware updates, no trust in camera analytics.
- **Cloud credential compromise:** scoped token, provider-side limit, Guardian revocation, audit and rotation runbook.
- **DNS/provider change breaks allowlist:** health signal and controlled update, never silently broaden to unrestricted egress.

## Decision

One excellent local deployment is the product baseline. Portability comes from documented data formats, adapters, and explicit contracts—not by supporting every operating system and orchestrator in V1.
