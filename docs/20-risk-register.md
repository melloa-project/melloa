# Ranked risk register

## Purpose

Track the threats most likely to destroy Melloa’s security, usefulness, maintainability, or owner trust. Rankings are initial judgments for V1 and must be revisited after incidents, capability grants, and architecture changes.

**Scale:** Probability (P) and Impact (I) are Low/Medium/High. Rank combines likelihood, severity, and difficulty of detection. Residual risk assumes listed mitigations are implemented.

| Rank | Risk | P | I | Detection / leading indicators | Principal mitigation | Residual |
|---:|---|:---:|:---:|---|---|:---:|
| 1 | Compromised autonomous agent or prompt injection causes unauthorized action | H | H | unusual tool sequences, policy denials, egress anomaly, new destinations, canary alerts | deterministic broker, exact-action authorization, taint labels, least privilege, sandbox, egress limits, Guardian | M |
| 2 | Privacy leak to provider, logs, backup, recipient, or contributor | M | H | disclosure manifest, DLP/redaction tests, audit review, provider/billing mismatch | sensitivity routing, local processing, minimization, encrypted stores, recipient binding, telemetry redaction | M |
| 3 | Incorrect long-term memory silently becomes “fact” | H | H | correction/contradiction rate, unsupported belief review, owner trust incidents | observation/interpretation/belief/confirmation separation, provenance, confidence, supersession, stale review | M |
| 4 | Owner loses trust after a harmful, creepy, or inexplicable action | M | H | dismissals, shutdowns, correction spikes, feedback, unexplained action audit | conservative proactivity, visible rationale/evidence, reversible actions, consent, incident review | M |
| 5 | Complexity outgrows one maintainer | H | H | upgrade time, flaky tests, runbook gaps, dependency count, modules bypassing contracts | modular monolith, one blessed path, dependency rules, ADRs, delete/defer aggressively | M |
| 6 | Data loss or unusable backups erase years of history | M | H | backup age/check failures, restore drill result, key-recovery test | encrypted 3-2-1-style copies, monthly clean restore, documented RPO/RTO, export | L-M |
| 7 | Over-optimization of a bad/vague goal harms owner | M | H | goal conflict, metric gaming, deteriorating guardrails, owner feedback | explicit values/constraints, multi-objective review, experiments, stop conditions, human goal control | M |
| 8 | Autonomous deployment corrupts data or service | M | H | canary regression, migration mismatch, error/action spike, rollback failure | isolated implementation, CI/replay/security gates, signed artifact, canary, expand/contract, Guardian | M |
| 9 | Runaway model/tool loop creates cost or actions | H | M-H | token/tool/step rate, queue growth, bill anomaly | per-run and monthly ceilings, circuit breakers, bounded retries, action quotas, provider budgets | L-M |
| 10 | Model regression changes behavior without visible code change | H | M-H | eval distribution shift, provider/version fingerprint, correction/denial spike | pin routes/versions where possible, model registry, replay gates, canary, fallback | M |
| 11 | Dependency or CI supply-chain compromise | M | H | provenance/signature failure, unexpected dependency/network access, advisories | lock/pin full SHAs, SBOM, SLSA-style provenance, Sigstore, minimal CI tokens, rebuild/rotate | M |
| 12 | Camera hallucination/missed event drives a false conclusion | H | M-H | calibration set, confidence/unknown rate, owner corrections, sensor disagreement | probabilistic interpretations, evidence frames, no absence inference, ask/abstain, local calibration | M |
| 13 | Stolen phone/Telegram account enables owner impersonation | M | H | new session/security alert, unusual command, pairing mismatch | Telegram limited role, exact IDs, local pairing, critical Guardian path separate, quick channel disable | M |
| 14 | Credential sprawl or a giant ambient secret bundle expands blast radius | M | H | secret access inventory, unused/stale grants, broad scopes | brokered scoped credentials, short leases, SOPS/keyring bootstrap, rotation, separate roles | M |
| 15 | Notification fatigue makes proactivity useless | H | M | ignore/dismiss rate, messages/day, quiet-hour attempts, repeated topics | interruption budget, batching, cooldowns, owner usefulness feedback, automatic stop | L-M |
| 16 | Framework/provider obsolescence or lock-in blocks evolution | M | M-H | adapter leakage, proprietary state, unportable prompts/evals | stable ports/schemas, canonical export, provider-neutral gateway, framework escape ADR | L-M |
| 17 | Camera or home hardware is brittle/offline | H | M | heartbeat, reconnect count, temperature/disk/network metrics | wired PoE, spare/replacement runbook, UPS optional, missed-period markers | L-M |
| 18 | Backup/recovery keys or owner root credentials are lost | L-M | H | recovery drill failure, single-copy key inventory | offline redundant key custody, periodic recovery test, documented ownership succession | L-M |
| 19 | Permission/grant set becomes stale and overbroad | H | M-H | unused grants, scope diff, expiry misses, capability inventory | expiries, least privilege, periodic recertification, no implicit grants on install | L-M |
| 20 | Audit/telemetry contains sensitive payloads or is incomplete | M | M-H | redaction tests, missing side-effect linkage, label cardinality, export scan | separate audit/telemetry, reference IDs/hashes, pre-export redaction, mandatory action linkage | L-M |
| 21 | Event schema/migration loses meaning over years | M | H | compatibility gate, replay failure, orphaned provenance, unknown enum/version | immutable envelopes, version adapters, expand/contract, raw preservation where justified | L-M |
| 22 | External service outage removes core usefulness | H | M | provider/channel health, queued age, fallback use | local capture/memory, provider adapters, graceful degradation, TTL, private local UI path | L |
| 23 | Third-party data is collected or shared without adequate consent | M | H | source/person labels, disclosure review, complaints | private-space scope, consent indicators, stricter third-party classification, deletion and no cloud by default | M |
| 24 | Malicious contributor or maintainer bypasses protections | L-M | H | anomalous code/CI rule change, review bypass, signing failure | protected branches, CODEOWNERS, independent Guardian repo, signed releases, least-privilege maintainer roles | M |
| 25 | Local network malware reaches camera/core | M | H | firewall/IDS anomalies, unexpected connections, host integrity alerts | VLANs, patching, host firewall, no camera internet, narrow service ports, credential rotation | M |
| 26 | Generated code exfiltrates private data or escapes sandbox | M | H | denied egress, sandbox syscall/resource anomaly, unexpected file access | no live data/secrets by default, rootless + gVisor, quotas, default-deny egress, disposable environment | M |
| 27 | Retention/deletion fails, creating a hidden life-log | M | M-H | storage growth, overdue objects, deletion receipt gaps | hard TTLs/quotas, retention worker, owner dashboard, backup expiry disclosure | L-M |
| 28 | Cost accounting is incomplete or provider bill diverges | M | M | unallocated calls, invoice reconciliation, unknown model route | mandatory invocation ledger, provider budget, billing reconciliation, fail closed on unknown priced route | L |
| 29 | Naming/trademark collision harms public release | M | M | registry/domain/trademark search and counsel | keep launch branding reversible; clearance gate before substantial public brand investment | L-M |
| 30 | Project becomes surveillance/productivity theatre without measurable benefit | H | H | no intervention outcomes, unused data, growing integrations, owner burden | value milestone gates, reject capabilities without goal/evaluation path, periodic deletion/simplicity review | M |

## Risk ownership and triggers

| Risk family | Operational owner | Re-review trigger |
|---|---|---|
| Policy, prompt injection, capability security | security/governance owner | new write capability, new untrusted source, model/tool protocol change |
| Memory and epistemic integrity | Melloa architecture owner | new memory class, correction incident, schema migration |
| Privacy and consent | privacy owner | new sensor/provider/recipient, retention change, public release |
| Reliability and recovery | operator/SRE owner | failed backup/restore, new host/site, dependency change |
| Self-modification and supply chain | repository owner | autonomous merge class expanded, new CI runner/coding agent |
| Goal/intervention harm | human owner | new long-term goal, health/financial domain, unexpected outcome |
| Cost | operator/owner | monthly spend >80% budget, new multimodal/local GPU route |

For a one-person deployment, the same human may hold all roles. The labels force perspective changes and explicit review rather than organizational ceremony.

## Top risk treatment priorities before camera or self-deployment

1. Demonstrate a policy denial cannot be bypassed by model output or tool text.
2. Demonstrate every side effect has an exact authorization and audit receipt.
3. Demonstrate correction-aware memory and unsupported-belief inspection.
4. Restore the system and keys on a clean machine.
5. Reconcile model calls and external disclosures to provider/billing records.
6. Exercise Guardian stop/egress revocation independently of Melloa.
7. Calibrate proactivity and camera error before trusting behavioral conclusions.

## Residual-risk statement

No architecture can make an autonomous, sensor-rich personal system risk-free. In particular, a compromised owner device, malicious model/provider, novel sandbox escape, or mistaken human approval may still cause harm. The objective is to reduce blast radius, create timely detection and recovery, and avoid granting authority that the system has not earned.
