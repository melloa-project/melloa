# Recovery boundary

Owner-controlled recovery is a hard trust boundary. The current implementation uses PostgreSQL as
the canonical durable store and an encrypted restic snapshot for the clean-restore exercise.

Run the synthetic proof with:

```bash
make recovery
```

The test creates representative conversation, memory, session, and audit state; takes a PostgreSQL
logical snapshot; encrypts it; restores into a clean database; and verifies the recovered state
through the authenticated API. It also checks that temporary credentials, databases, and backup
material are removed before success is reported.

This proves that the checked-in schema and recovery harness can round-trip synthetic state. It does
not prove a real installation has:

- scheduled backups;
- off-device copies;
- safe owner key custody;
- monitored backup failures;
- a measured restore time;
- complete coverage after future data-model changes.

Before keeping real owner state, the owner must establish those operational pieces and perform a
clean restore from the actual backup path. Recovery keys stay outside Melloa and outside the backup
they decrypt. Guardian signing and recovery material is separately controlled and is never included
in a Melloa database backup.

Any change to durable owner state must either remain covered by this recovery path or explicitly
state why that state is safely rebuildable.
