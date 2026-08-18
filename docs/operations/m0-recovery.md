# Durable owner-state recovery

## Purpose

Prove that Melloa's canonical PostgreSQL owner state can be backed up, encrypted, restored into a clean database, and used again through the authenticated owner API. The drill covers the complete committed migration set and exercises conversation, explanation evidence, memory state, owner sessions, and audit state rather than checking a raw database marker.

PostgreSQL is the recovery authority because it owns the canonical relational state. The Owner Console ZIP is a portability package, not a database backup or import path. Guardian signing keys, provider credentials, and host recovery material remain independently owner-controlled and are never included in this backup.

The drill uses synthetic data and ephemeral credentials. It proves the repository's recovery mechanism; it does not claim that a particular installation has a schedule, offsite copy, retained key, or recent successful backup.

## Prerequisites

- the locked Python environment installed with `make bootstrap-python` or `make bootstrap`;
- Docker available to the current user;
- first-run access to the digest-pinned PostgreSQL/pgvector and restic images;
- enough temporary storage for two small PostgreSQL containers, one logical dump, and one encrypted repository;
- no real credentials or personal data.

## Execute

```bash
make recovery
```

The command creates and removes all fixture state itself. It does not use the disposable `make preview` state or an owner export.

## What the drill proves

1. Starts a clean source PostgreSQL 18 plus pgvector database and provisions the narrow role groups.
2. Applies every immutable migration in the checked migration manifest and rejects pending or changed migrations.
3. Uses the real PostgreSQL-backed runtime and authenticated owner API to create a canonical conversation and deterministic fixture turn, then records bounded identifiers for its explanation, memory, session, and audit evidence.
4. Creates a custom-format logical database dump without binding it to source-container ownership.
5. Generates an ephemeral mode-`0600` restic password, initializes an encrypted repository with networking disabled, backs up the dump, and runs `restic check`.
6. Scans the encrypted repository and fails if the known fixture marker appears in plaintext.
7. Restores the dump into a second clean PostgreSQL database with the documented roles and no source volume.
8. Reconstructs the PostgreSQL-backed runtime and authenticates through the same owner API used by the console.
9. Verifies the exact restored conversation, messages, turn explanation/model evidence, memory state, owner session/audit evidence, and migration set.
10. Confirms the read-only role still cannot mutate canonical state.
11. Removes both containers, network, dump, repository, password, and temporary expectations, verifies cleanup, and only then emits a bounded JSON receipt.

## Acceptance

The receipt must report success for:

- all committed migrations;
- restic encryption and integrity;
- clean logical restore;
- authenticated conversation and turn-explanation recovery;
- memory and audit/session recovery;
- read-only mutation denial;
- cleanup-safe execution.

The receipt must not contain the owner credential, browser session or CSRF tokens, message text, DSN, temporary paths, dump content, private hashes, or raw audit payloads. A successful dump or restic backup without the clean owner-API traversal is not recovery evidence.

## Failure response

- If migration apply/check or restore fails, preserve the error category but never publish the dump, restic password, or temporary expectation file.
- If expected owner state is missing, treat the backup as unusable even when `restic check` passed.
- If a fixture marker is visible in repository plaintext, stop and review the backup path before using it with owner data.
- If the read-only role can mutate restored data, treat it as a release-blocking authority failure.
- Repeat from fresh containers after correcting the cause; do not edit restored canonical rows by hand.

## Installation boundary

A real long-lived installation still needs owner-selected local and offsite restic destinations, redundant recovery-key custody, retention/pruning policy, scheduled execution, backup-age alerts, capacity monitoring, and periodic clean-host drills. Those deployment values do not belong in this public repository and are not inferred from a green synthetic receipt.
