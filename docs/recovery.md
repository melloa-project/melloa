# Recovery boundary

Owner-controlled recovery is a hard trust boundary. The current implementation uses PostgreSQL as
the canonical durable store and restic snapshots encrypted with an owner-controlled password.

Two checks cover different parts of that boundary:

```bash
make recovery
make server-runtime
```

`make recovery` is the small schema-level round trip. `make server-runtime` exercises the actual
scheduled container path: it seeds representative conversation, memory, session, and Telegram
route state; streams a custom PostgreSQL dump directly into restic; checks that the repository does
not expose a known private marker; records success and failure status; retries after a database
outage; destroys the source volume; and restores into a clean database as the migration role. The
recovered state is then verified through the authenticated API and storage adapters. It also takes
pre-release snapshots and verifies owner state after interrupted deployment, failed-candidate
automatic rollback, and explicit image rollback.

The server scheduler runs once at startup and daily thereafter. It uses a dedicated read-only
database login, retains 14 daily, 8 weekly, and 12 monthly snapshots, prunes, runs `restic check`,
and publishes an atomic mode-`0600` marker for Melli's `/status`. It never writes a plaintext dump
to disk and has neither a Docker socket nor an egress network. Pre-release snapshots use a separate
tag with the ten newest retained, so a candidate's startup backup cannot prune the snapshot needed
to recover that deployment.

These checks prove bounded mechanics with synthetic data. They do not prove a real installation has:

- its repository on genuinely independent off-device storage;
- an owner-held recovery-password copy outside the server and backup repository;
- backup failures observed through the real Telegram owner channel;
- a measured restore time;
- complete coverage after future data-model changes.

Normal startup refuses to initialize a missing repository. This makes a lost off-device mount fail
visibly instead of silently redirecting backups to the server disk. Repository initialization is an
explicit one-time `backup init` operation. Recovery into an empty target is exposed only through the
profile-gated `restore` service; it reads the encrypted repository without a lock and restores as
`melloa_migrator`, preserving schema ownership for later migrations.

Before keeping real owner state, the owner must establish the remaining operational pieces and
perform a clean restore from that installation's actual backup path. Recovery passwords stay outside
Melloa and outside the repository they decrypt. Guardian signing and recovery material is separately
controlled and is never included in a Melloa database backup.

Any change to durable owner state must either remain covered by this recovery path or explicitly
state why that state is safely rebuildable.
