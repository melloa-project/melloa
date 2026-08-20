# Persistent server runtime (engineering checkpoint)

This is the generic Linux container runtime intended to become Melloa's low-maintenance server
path. It is **not yet an owner deployment instruction** and does not change the repository's
`NOT READY` status. Release rollback, self-change policy, real provider and off-device storage
configuration, and deployed dogfooding are still required.

The runtime has five bounded roles:

- PostgreSQL is reachable only on a private, internal container network;
- a one-shot administrative container reconciles three password logins, including existing volumes;
- a one-shot migration container must finish before Melloa starts;
- a separate read-only backup container streams PostgreSQL snapshots into encrypted storage; and
- Melloa exposes no host port and uses outbound Telegram long polling as the normal interface.

The Melloa process runs as the dedicated numeric UID/GID selected in the path-only environment
file (the template uses `10001:10001`), with a read-only root filesystem, no Linux
capabilities, bounded logs, and restart-on-failure/reboot behavior. A PostgreSQL connection loss
causes the process to request a supervised restart instead of remaining silently wedged.

The backup container has no Docker socket or egress network. It connects with a dedicated
non-writing database role, creates no plaintext dump file, and sends the dump stream directly to a
pinned restic binary. It runs immediately and then daily, retains 14 daily, 8 weekly, and 12 monthly
snapshots, prunes superseded data, checks the repository, and atomically updates the protected
status file read by Melli's `/status` response. A failure is retried after 15 minutes and remains
owner-visible until a complete backup and repository check succeeds.

## Private deployment inputs

Copy `server.env.example` outside the source checkout and replace only its paths, image tag,
commit, and private subnet. The environment file contains paths, never values. Every credential
and owner-specific JSON document is supplied as a separate regular file. Credential files read by
Melloa or the backup process must be owned by that dedicated UID/GID and mode `0600`; private
directories should be mode `0700`.

The build receives the host CA bundle as a BuildKit secret so a server with an owner-approved
outbound TLS proxy can still download locked dependencies. The bundle is not copied into the
image; a normal public-PKI host can keep the template's `/etc/ssl/certs/ca-certificates.crt` path.

The two database DSN files use distinct login roles. With the default private network they have
this shape, with the generated password written directly into the private file rather than a shell
history or environment variable:

```text
host=172.30.37.2 port=5432 dbname=melloa user=melloa_app password=REDACTED
host=172.30.37.2 port=5432 dbname=melloa user=melloa_migrator password=REDACTED
```

The backup database password is a third independent secret. The scheduler converts it to a
mode-`0600` `.pgpass` in container tmpfs, so the password does not appear in process arguments or
environment metadata. Its `melloa_backup_login` can read backup-covered state and sequences but
cannot mutate owner data.

`MELLOA_BACKUP_REPOSITORY_DIR` must point at storage mounted independently from the server disk.
Melloa deliberately does not initialize an absent repository during normal startup: losing the
off-device mount therefore produces a failed status instead of silently creating a local backup in
the underlying directory. The owner initializes it once with the `backup init` command and keeps a
separate recovery copy of `MELLOA_RESTIC_PASSWORD_FILE` outside both Melloa and the repository.
Recovery into an empty database uses the profile-gated `restore` service, which decrypts the chosen
snapshot and restores as the least-privilege migrator so schema ownership remains valid. See
[the recovery boundary](../../docs/recovery.md).

The Guardian handoff directory must contain only the owner-supplied `status.json` and `public.pem`
projection expected by the existing read-only Guardian contract. Melloa receives no Guardian
private key, mutation command, deployment credential, or container authority.

Model config files use the existing bounded format. An external OpenAI capable route uses
`"api_style": "responses"`, `"base_url": "https://api.openai.com/v1"`, an explicit model ID,
approved-provider processing, current owner-reviewed token/cost ceilings, and an
`authorization_token_file` below `/run/melloa/model-credentials/`. [Official OpenAI model
guidance](https://developers.openai.com/api/docs/models) currently recommends [GPT-5.6
Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol) for complex reasoning and coding,
and the [text generation guide](https://developers.openai.com/api/docs/guides/text) recommends the
Responses API for new text-generation applications. The deployment owner must still confirm
account availability and current pricing before selecting it. The economy route may instead name
a compatible hosted router or a private model endpoint. Neither route silently falls back to the
other.

Telegram bot chats are not end-to-end encrypted. Exact owner/chat binding prevents other Telegram
users from operating Melloa, but it does not provide Secret Chat privacy.

## Mechanical verification

For a disposable local proof using only synthetic credentials and public Guardian fixtures:

```bash
make server-runtime
```

That check builds both pinned runtime images, reconciles least-privilege database logins, applies
all migrations, and proves application restart and PostgreSQL recovery. It also exercises the real
scheduler through success, database outage, retry, encrypted-at-rest inspection, destruction of the
source database, and clean recovery of conversation, memory, session, and Telegram route state.
It is infrastructure evidence only—not real off-device storage or Telegram/provider dogfooding.
The `MELLOA_POSTGRES_IMAGE` and `MELLOA_RESTIC_IMAGE` overrides may name locally cached copies of
the exact pinned images when a registry is unavailable.
