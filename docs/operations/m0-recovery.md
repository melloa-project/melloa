# M0 encrypted backup and restore runbook

## Purpose

Prove that the initial PostgreSQL truth/audit spine can be exported, encrypted, integrity-checked, restored into a fresh database, and inspected through a read-only role. This synthetic drill is the M0 recovery gate; it is not the owner-specific production backup schedule.

## Prerequisites

- Docker daemon available to the current user;
- first-run access to the digest-pinned `pgvector/pgvector` and `restic/restic` images;
- enough temporary storage for two empty PostgreSQL containers and a small dump;
- no real credentials or personal data.

## Execute

```bash
make recovery
```

The harness performs these steps:

1. Creates an internal Docker network and source PostgreSQL 18 plus pgvector container.
2. Provisions the documented role groups and applies the M0 migration.
3. Inserts a synthetic canonical event and audit receipt.
4. Creates a custom-format logical dump without owner binding.
5. Generates an ephemeral random restic password in a mode-`0600` temporary directory.
6. Initializes a new encrypted restic repository and backs up the dump with network disabled, no cache, and the invoking user's UID/GID.
7. Runs `restic check` and scans every repository byte to ensure the known fixture marker is not plaintext; unreadable repository data fails closed.
8. Restores the dump into a second clean PostgreSQL container.
9. Confirms the exact synthetic marker through `melloa_readonly`.
10. Confirms the read-only role cannot delete canonical data.
11. Deletes both containers, the network, dump, encrypted repository, and generated password.

## Acceptance

The command must emit a JSON receipt with `pass` for:

- encrypted-repository plaintext scan;
- restic integrity check;
- fixture restoration;
- read-only mutation denial.

Any missing image, dump error, repository check error, absent fixture, unexpected plaintext, or successful read-only mutation fails the drill.

## Failure response

- Do not treat a successful backup command as a substitute for this restore.
- Preserve useful error output but never copy the ephemeral restic password or a real dump into an issue.
- If migration or ACL restoration fails, fix the migration/role contract and repeat from clean containers.
- If plaintext is found, stop and review the backup path before using it with any personal data.
- If read-only mutation succeeds, treat it as a release-blocking authority failure.

## Production boundary

A real installation additionally requires owner-controlled restic and age recovery-key custody, local and offsite repositories, retention policy, backup-expiry disclosure, scheduling, alerting, and a clean-host drill using the private deployment repository. Those values are not committed or inferred by this synthetic runbook.
