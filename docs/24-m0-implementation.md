# M0 implementation: contracts and recovery

## Purpose

Map the first implementation milestone in [the final synthesis](22-final-synthesis.md#first-implementation-milestones) to current code, tests, operational evidence, and intentionally deferred integrations. This page describes implementation status; it does not supersede the architecture or accepted ADRs.

**Status:** Complete for the reviewed synthetic M0 scope on 2026-08-16. See the root `VALIDATION.md` report for the executed acceptance gates. Production deployment remains explicitly out of scope.

## Scope

M0 establishes the truth, authority, inspection, and recovery spine without real credentials, personal data, Telegram, camera hardware, model providers, or generated-code execution.

| M0 requirement | Implementation evidence | Verification |
|---|---|---|
| Reproducible repository | `pyproject.toml`, `uv.lock`, `.python-version`, `.nvmrc`, `apps/web/package-lock.json`, `Makefile` | `make bootstrap && make check` |
| Event envelope | `src/melloa/domain/events.py`, `schemas/events/event-envelope-v1.json` | contract, schema, hash, and uncertainty tests |
| Assertion/provenance model | `src/melloa/domain/memory.py`, `schemas/memory/` | correction, authority, self-edge, and validity tests |
| Owner/Melli identity | `src/melloa/domain/identity.py`, `schemas/identity/` | stable neutral IDs and naming-history tests |
| Policy request/decision | `src/melloa/domain/policy.py`, `schemas/actions/` | default-deny, exact-action, Guardian, privacy, risk, grant, and budget tests |
| PostgreSQL and durable work | `migrations/0001_m0_foundation.sql`, immutable digest manifest, `compose.yaml` | migration apply/check and PostgreSQL integration tests |
| Append-oriented audit | `src/melloa/domain/audit.py`, DB append-only and predecessor triggers | atomic event/audit, duplicate, conflict, and mutation tests |
| Guardian protocol and modes | `schemas/guardian/`, verified read-only adapter, separate `melloa-guardian` signer/CLI | signature, tamper, sequence, state-machine, file, and journal-chain tests |
| CI | digest/commit-pinned workflow under `.github/workflows/ci.yml` | deterministic, integration, docs, and recovery jobs |
| Encrypted backup/restore | `tools/m0_restore_drill.sh` with digest-pinned PostgreSQL and restic images | encrypted repository scan, `restic check`, clean restore, read-only mutation denial |
| Canonical conversation contracts | `src/melloa/domain/conversation.py`, `schemas/conversation/`, relational tables | schema generation and contract tests |
| Private Owner Console shell | `apps/web/` | TypeScript check, Node tests, static build; server binds loopback only |
| Synthetic adapters | `src/melloa/adapters/fakes/` | zero-cost/device-local model, authorized-only client, read-only Guardian tests |

M0 is complete only when every listed command succeeds on the reviewed revision. A narrow test cannot stand in for the restore or Guardian checks.

## Dependency direction

The Python package preserves the accepted dependency direction:

```text
apps → application → domain + ports ← adapters
```

- Domain contracts import no provider, database, web, camera, Telegram, or Guardian implementation.
- The core API receives a `GuardianStatusReader`; it has no transition interface.
- Fake adapters implement the same ports and use only synthetic data.
- PostgreSQL is an adapter and persistence authority, not imported into domain logic.
- The Owner Console is a client shell and contains no policy or identity authority.

## Contract invariants

### Epistemic provenance

- Interpretations and beliefs require confidence.
- Event payload hashes cover deterministic canonical JSON.
- Owner-confirmed assertions require owner-authored authority.
- Corrections are new assertion records targeting prior assertions.
- Provenance edges cannot self-reference.
- Canonical events, assertions, provenance edges, policy decisions, messages, model runs, actions, and audit are append-only in PostgreSQL.

### Identity and conversation

- Owner, persistent intelligence, event, worker, model, conversation, and action IDs are opaque neutral identifiers.
- `Melli` is a display name in naming history, never a database type or primary key.
- Threads, messages, turns, attachments, citations, corrections, action references, and delivery attempts are transport-independent.
- Telegram identifiers and browser sessions have no place in canonical identifiers.

### Authority

- Missing grant, stale Guardian sequence, missing policy data, budget exhaustion, and unsupported risk reduce authority.
- Tool text, model output, and external content cannot create a grant or approval.
- Approval binds the complete normalized action hash; changing content, target, purpose, resource, risk, destination, or data class changes the hash.
- Guardian control, governance changes, audit deletion, credential reveal, and host execution are platform-prohibited in the M0 evaluator.
- Device-only data cannot have an external destination.
- Executed side effects require a policy decision link and audit receipt obligation.

## Guardian boundary

The independently protected `melloa-guardian` repository owns signing and transitions. Its M0 implementation provides:

- Ed25519-signed status envelopes;
- all six required modes;
- deterministic, progressive state transitions;
- monotonic sequence and previous-receipt hash chaining;
- append-only JSONL receipt journal as the authority;
- atomic status projection and reconciliation after interrupted writes;
- strict private-key permissions;
- no dependency on Melloa, models, provider SDKs, or this repository at runtime.

The ordinary runtime receives a public key and read-only status file. Invalid or missing state returns HTTP 503 and leaves actions disabled. Host-specific systemd, firewall, credential revocation, and recovery wiring depend on an owner-reviewed host plan and are not invented from synthetic values.

## Private Owner Console boundary

The M0 shell exists to prevent a terminal-or-Telegram-only architecture from becoming entrenched. It renders the required V1 areas and states its limitations clearly:

- loopback-only server;
- no public ingress;
- no external actions;
- synthetic adapters only;
- application authentication integration remains an M1 gate;
- ordinary console code cannot mutate Guardian state;
- structured records, not hidden chain-of-thought, are the inspection contract.

The shell is not yet a usable conversation client and must not be exposed as though it were authenticated.

## Threat review

| Threat | M0 control | Residual risk |
|---|---|---|
| Model or tool claims authorization | typed request, deterministic deny-first evaluator, exact hash | evaluator defects; property and integration coverage must grow |
| Guardian status tampering | Ed25519 verification, size/type checks, receipt chain | compromised owner key or host kernel remains powerful |
| Runtime attempts Guardian mutation | no mutation port, no private key, separate repository | deployment permissions must preserve the documented file boundary |
| Event or audit rewrite | append-only triggers, narrow roles, audit predecessor trigger | database superuser can still tamper; backup/checkpoint trust domain remains necessary |
| Duplicate delivery | immutable ID comparison and idempotent exact duplicate handling | external side-effect deduplication arrives with real capabilities |
| Personal-data leak in development | synthetic fixtures, no credentials, no external model route | developer workstation and CI logs still require ordinary hygiene |
| Public exposure | loopback default and bind-address rejection | deployment firewall and application authentication remain required |
| Backup is unreadable or plaintext | restic encryption, integrity check, clean restore, plaintext-marker scan | owner key custody and offsite provider integration are deployment concerns |

## Retention, export, and observability

M0 stores only synthetic validation records. The schema nevertheless includes sensitivity, trust, retention policy, cost, external disclosure, evidence, correction, action, and audit fields so later milestones cannot bypass them. Raw camera media, embeddings, provider prompts, and personal content are absent.

The restore drill destroys its temporary containers, volumes, database dump, repository, and generated password. It emits only a non-sensitive pass/fail receipt. Canonical export and retention workers remain later implementation within the V1 boundary; M0 does not claim they exist.

## Reproduction

```bash
make bootstrap
make check
make integration
make recovery

cd ../melloa-guardian
make check
make build
```

The main integration and recovery commands require a functioning Docker daemon and network access to the two digest-pinned public images on first use. They never require real service credentials.

Cross-repository status compatibility can be repeated with disposable keys:

```bash
state="$(mktemp -d)"
guardian="../melloa-guardian/bin/guardianctl"
guardian_flags=(
  --status-file "$state/status.json"
  --audit-file "$state/audit.jsonl"
  --private-key-file "$state/private.pem"
  --public-key-file "$state/public.pem"
  --lock-file "$state/guardian.lock"
)

"$guardian" init --instance-id synthetic-guardian --key-id guardian.status-v1 "${guardian_flags[@]}"
uv run melloa guardian-status --status "$state/status.json" --public-key "$state/public.pem"
"$guardian" transition --mode offline --reason synthetic.owner_drill "${guardian_flags[@]}"
uv run melloa guardian-status --status "$state/status.json" --public-key "$state/public.pem"
```

Both Melloa reads must verify successfully; the second payload reports sequence `2`, mode `offline`, and the first receipt hash as its predecessor. These commands are a development drill only and grant no runtime Guardian mutation port.

## Remaining owner decisions

Before accepting external code contributions or making a public implementation release, the owner must select and record an OSI-approved source license. Before real host installation, the owner must also approve the concrete authentication/recovery design and bounded Guardian deployment plan for that host. Neither decision is guessed in M0.
