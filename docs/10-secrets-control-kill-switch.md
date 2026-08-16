# Credential, secret, control-plane, and kill-switch architecture

## Purpose

Prevent the autonomous plane from possessing broad, long-lived credentials or the privilege to remove its own ultimate shutdown mechanism.

## Secret taxonomy

| Class | Examples | Desired handling |
|---|---|---|
| Owner root/recovery | disk recovery, backup master key, Guardian signing key | offline or hardware-backed; never available to Melli |
| Host administration | root/SSH, firewall, systemd, LUKS | owner/Guardian only; hardware-backed MFA where practical |
| Release/CI | signing identity, registry publish, protected deployment | short-lived OIDC/keyless where possible; protected workflows |
| Provider accounts | LLM API keys, GitHub app, Telegram bot | scoped account/key; brokered use; rate/cost limits |
| Capability credentials | calendar OAuth, camera password, future smart-home token | least scopes; per capability; revocable; preferably short-lived |
| Database roles | migration, core runtime, worker, analytics, backup | separate users and grants; no shared superuser |
| Ephemeral leases | one worker/action token | minutes, exact purpose/resource, automatic revocation |

## V1 secret design

### Bootstrap

- Version encrypted configuration with SOPS using age recipients; SOPS supports age and external key services while keeping encrypted files reviewable in Git. [S20](research/primary-sources.md#S20)
- Store the age private key in the OS keyring or owner-controlled protected path; keep an offline recovery copy.
- Inject secrets at process start through a narrowly permissioned file descriptor/tmpfs file or broker API, not a committed `.env`.
- Never expose the Docker socket to autonomous containers.

### Runtime credential broker

The broker holds or accesses secrets and presents operation-specific interfaces:

```text
worker → action proposal → policy authorization
       → credential broker exercises API or issues short lease
       → adapter executes → lease revoked/expired
```

Preferred order:

1. Broker performs the external call and returns a typed result.
2. Broker exchanges a refresh credential for a short-lived access token bound to scopes.
3. Broker injects a one-operation credential into an ephemeral adapter.
4. Long-lived direct secret exposure is an exception requiring a documented threat decision.

### Database roles

- `melloa_migrate`: schema changes only, unavailable to normal runtime.
- `melloa_core`: application tables and approved functions.
- `melloa_worker`: job claim and operation-specific tables.
- `melloa_readonly`: owner analytics/export.
- `melloa_backup`: backup operations with a tested complete-data path.
- No runtime uses the PostgreSQL superuser.

## When to adopt OpenBao

OpenBao supports centrally managed and dynamic secrets with leases and revocation. [S19](research/primary-sources.md#S19) It is justified when Melloa has multiple hosts/environments, several workloads needing short-lived credentials, and enough rotation burden to outweigh another critical service.

It is not justified merely because secrets are important. V1 can be safer with fewer moving parts, SOPS-encrypted bootstrap material, scoped provider keys, and a small broker.

Adoption trigger:

- at least three independent hosts/environments;
- at least five rotating machine credentials or dynamic database/cloud roles;
- audited need for central lease revocation;
- owner has restored OpenBao and unsealed/recovered it in a drill.

## Guardian architecture

### Trust rule

The autonomous plane SHALL NOT have:

- root or passwordless sudo;
- write access to Guardian binaries, config, unit files, mode files, or signing keys;
- firewall administration;
- provider account administration needed to revoke/replace its own credentials;
- access to owner recovery keys;
- authority to merge/deploy Guardian changes.

### Implementation shape

A minimal root-owned host service and CLI:

```text
/usr/local/libexec/melloa-guardian
/etc/melloa-guardian/policy.toml        root:root 0600
/var/lib/melloa-guardian/mode           root:guardian-read 0640
/etc/systemd/system/melloa-*.service
nftables/egress sets
owner hardware/MFA credentials
```

The autonomous containers may read the current mode through a read-only mount or local Unix socket. They cannot modify it.

### Modes

| Mode | Effect |
|---|---|
| `normal` | Policy-authorized reads and actions proceed |
| `no-actions` | Ingestion/reasoning continue; all side effects denied except owner diagnostics |
| `read-only` | No external actions or memory/config mutations; inspection/export allowed |
| `offline` | External network egress removed; local ingestion may continue according to policy |
| `stopped` | Autonomous containers and scheduled jobs stopped |
| `recovery` | Database/app started with restricted owner-only recovery tooling; channels and model egress disabled |

Mode transitions are append-only audit events written by the Guardian or imported after recovery.

## Kill-switch channels

Use multiple independent layers:

1. **Logical:** owner CLI over local console or private network changes mode.
2. **Credential:** revoke provider/capability keys from separate owner accounts.
3. **Network:** Guardian removes autonomous egress or blocks a VLAN.
4. **Runtime:** systemd stops/disable containers and timers.
5. **Physical:** UPS/power or switch port can be disconnected; a camera privacy shutter/cutoff is visible.

The system should not rely on Melli acknowledging a chat command to stop itself.

## Approval and control authentication

- Owner account uses hardware-backed MFA/passkey where supported.
- Guardian remote access is restricted to the owner's private-network identity and local console.
- High-risk control changes require reauthentication and display the exact target state.
- Recovery codes and age/LUKS/backup keys are stored offline in at least two physically separate secure locations.
- Telegram is not a sufficient sole channel for Guardian control. It may request shutdown, but the Guardian independently authenticates or the owner uses the private control path.

## Secret rotation

Each credential record includes owner, purpose, scopes, created/last-used/expiry, rotation period, revocation method, and affected capabilities. Rotation runbook:

1. create narrower replacement credential;
2. test in staging or a single adapter;
3. atomically switch broker reference;
4. verify successful action and audit;
5. revoke old credential;
6. search logs/artifacts for accidental exposure;
7. record rotation event and next due date.

Critical provider keys should have account-level spend/rate limits in addition to Melloa budgets.

## Leakage prevention

- Secret values never enter prompts, model context, general traces, exception messages, or Git.
- Log processors apply structured field redaction, not fragile regex alone.
- Generated code receives synthetic test credentials and mocked services.
- A capability adapter can expose a stable secret reference but not a reveal operation.
- Backups include encrypted secret configuration only when the recovery design explicitly requires it; recovery keys are separate.

## Guardian change process

Guardian and governance-layer changes are a distinct class:

1. human-authored or agent-proposed PR;
2. mandatory owner review and protected CODEOWNER;
3. tests on a disposable host or VM;
4. signed release artifact;
5. owner installs using a separate deployment identity;
6. verify kill-switch behavior before re-enabling autonomy.

Melli may identify a needed change and prepare a proposal. It cannot merge or deploy it.

## Failure modes

- **Lost bootstrap key:** recover from offline copy; if none exists, encrypted secrets/backups may be unrecoverable by design.
- **Broker down:** side effects stop; ordinary local reads may continue.
- **Guardian process down:** host defaults should keep autonomous service restart and egress within safe settings; owner can use local systemd/firewall controls.
- **Owner account compromise:** attacker may approve actions or change controls; hardware MFA, alerts, separate recovery account, and action delay for critical changes reduce risk.
- **Autonomous container escape:** host kernel compromise may cross the boundary; rootless containers and later gVisor reduce but do not eliminate this. Independent provider revocation and physical control remain important.
- **Backup contains credentials:** access to backup plus recovery key becomes critical; maintain key separation and test inventory.

## Build now

- SOPS + age bootstrap, separate OS permissions, no giant `.env`.
- Runtime credential broker for Telegram and model provider calls.
- Distinct DB roles.
- Root-owned Guardian with all six modes.
- Separate owner authentication and offline recovery keys.
- Credential inventory, rotation, and revocation runbooks.

## Design for

- TPM/Secure Enclave-backed owner keys.
- OpenBao/dynamic secrets after the adoption trigger.
- Workload identity for remote capability nodes.
- Signed Guardian release and reproducible packages.

## Defer

- Autonomous secret reveal or rotation of root/recovery credentials.
- OpenBao cluster in V1.
- Guardian implemented as an LLM agent.
- Telegram-only emergency shutdown.
