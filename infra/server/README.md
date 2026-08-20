# Persistent server runtime (engineering checkpoint)

Owner-facing installation instructions live in the canonical
[first-owner server deployment path](../../docs/server-deployment.md). This file is the technical
reference for the checked-in server runtime and the lower-level commands behind that guide.

This is the container runtime intended to become Melloa's low-maintenance server path. The first
qualification target is now one concrete host: a fresh Debian 13 (`trixie`) amd64 machine booted
with systemd. It is **not yet an owner deployment instruction** and does not change the
repository's `NOT READY` status. Real provider and off-device storage configuration, actual server
installation, reboot and recovery drills, and deployed dogfooding are still required.

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
owner-visible until a complete backup and repository check succeeds. A database dump is bounded to
30 minutes by default, so a frozen database cannot leave backup health silently stale forever; an
incomplete restic snapshot created while a dump fails is removed before the failure is reported.

## Selected host bootstrap

Start from a fresh Debian 13 amd64 server with root access and an independently mounted backup
volume. The bootstrap intentionally refuses other distributions, architectures, containers outside
its own disposable CI smoke test, conflicting distro Docker packages, and pre-existing commands it
does not own. On a minimal image, install only the two tools needed to obtain the reviewed checkout,
then run the checked-in bootstrap:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends ca-certificates git
git clone https://github.com/melloa-project/melloa.git
cd melloa
sudo infra/server/bootstrap-debian.sh --source "$PWD"
sudo infra/server/first-install.sh --source "$PWD"
```

The reviewed versions and artifact hashes live in `toolchain.lock`. The bootstrap verifies Docker's
repository signing-key fingerprint, installs Docker CE and Compose from its Debian repository,
installs checksum-pinned Node.js and uv artifacts, and installs Go for the public Guardian handoff
drill. It starts and enables Docker, then runs the normal clean/current-main build preflight. The
integrity-pinned Codex CLI npm packages are installed only when bootstrap is rerun with
`--self-change-tools` for explicitly enabled self-change workers. Bootstrap does not configure
secrets, initialize storage, or start Melloa. The guided
`first-install.sh` step installs host assets, prompts for the owner-private values, generates the
route JSON, pairs the Telegram bot, installs private configuration, initializes the encrypted backup
repository when approved, activates Melloa, and runs a final owner-journey verifier. That verifier
asks the owner to send one exact setup message in Telegram, then proves from Melloa's durable state
that the message was accepted, answered, and delivered back through Telegram. Rerun the bootstrap's
read-only host check with:

```bash
sudo infra/server/bootstrap-debian.sh --source "$PWD" --check
```

An owner-approved outbound TLS proxy can be supplied as a public PEM bundle with `--ca-file`; pass
the same flag to `first-install.sh`. The bootstrap uses that bundle for apt, curl, npm, and the
clean-main Git check. First install copies the public bundle into `/etc/melloa/build-ca.pem`, stores
that path in `server.env`, and update/preflight reuse it for Git, uv, npm, and Docker build
dependency fetches. If activation fails before that bundle was configured, rerunning first install
with `--ca-file` updates only that public build CA setting and resumes activation. It is not
installed as a new machine-wide trust root.

`make server-bootstrap` repeats the toolchain installation in a disposable digest-pinned Debian 13
container. That proves package and CLI compatibility, not systemd boot behavior; the real target
still has to pass the live qualification before the root README can say ready.

The pinned Codex CLI path uses a separate API key or an explicitly selected local provider. It does
not claim that unattended service operation can rely on an interactive ChatGPT subscription login.

## Guided first install inputs

`first-install.sh` is now the normal owner path after bootstrap. It runs the immutable asset
installer, collects private values through prompts, writes temporary mode-`0600` input files,
generates the capable/economy model JSON, runs exact Telegram owner pairing, calls the private
configuration transaction, and activates the server unless `--skip-activation` is selected for a
staged test. It resumes an already configured server through activation and verification instead of
overwriting owner state, and emits no secret values. After activation, it runs
`/usr/local/libexec/melloa/verify-owner-journey`; if the owner cannot complete the Telegram proof
immediately, rerun that command later.

Before invoking it, have these owner-controlled values ready:

- a dedicated Telegram bot token;
- the exact model IDs, base URLs, API style, token/cost ceilings, and bearer tokens for external
  OpenAI-compatible capable/economy routes;
- a high-entropy base64url restic password retained separately from this machine and the backup
  repository.

The guided first-owner path defaults optional self-change workers off. If the owner intentionally
enables them during setup, also prepare a fine-grained GitHub token for this repository with
contents read/write access and a separate OpenAI API key for Codex planning, or select an
explicitly installed `ollama`/`lmstudio` local Codex provider instead. First install refuses that
optional path on the real server unless bootstrap has prepared the pinned Codex CLI with
`--self-change-tools`. When disabled, activation stops and disables the planner/applier units, and
the units have an `ExecCondition` gate so an accidental manual start does not run the workers.

The current OpenAI chat route uses an API key with the Responses API; it does not claim to persist
an interactive ChatGPT or Codex subscription login. Official OpenAI documentation recommends the
[Responses API for new text generation](https://developers.openai.com/api/docs/guides/text) and
shows bearer-key authentication. Model availability, current pricing, and account access still
need owner confirmation. A hosted economy/router route uses its own owner-reviewed endpoint,
model ID, disclosure classification, price ceilings, and token.

Model JSON uses the schema described in the root README. For example, a credential-bearing route
contains the following path—not the token value itself:

```json
{
  "display_name": "Owner-selected capable model",
  "provider_id": "provider.owner-approved-capable",
  "model_id": "owner-selected-model-id",
  "base_url": "https://owner-reviewed-provider.example/v1",
  "api_style": "responses",
  "processing_location": "approved_provider",
  "allowed_sensitivities": ["public", "internal", "personal"],
  "max_input_tokens": 16384,
  "max_output_tokens": 2048,
  "estimated_max_cost_gbp": "REPLACE_WITH_REVIEWED_MAXIMUM",
  "input_cost_gbp_per_million_tokens": "REPLACE_WITH_CURRENT_RATE",
  "output_cost_gbp_per_million_tokens": "REPLACE_WITH_CURRENT_RATE",
  "timeout_ms": 60000,
  "health_timeout_ms": 5000,
  "authorization_token_file": "/run/melloa/model-credentials/capable-token"
}
```

The cost placeholders deliberately make this example fail validation. Replace all route, model,
sensitivity, and cost values from current owner-reviewed provider terms; setting real token rates
to zero would make the retained cost record inaccurate.

During guided setup, Melloa discovers the exact numeric Telegram owner ID without using a third-
party ID bot or copying it from Telegram metadata. The pairing step verifies that the supplied bot is
available for long polling, prints a random one-time `/start` phrase to the terminal, and waits for
that exact phrase in a one-to-one chat. Instructions go to the terminal while stdout contains only
the verified numeric ID. For manual recovery or debugging, the underlying command is:

```bash
TELEGRAM_OWNER_ID="$(
  sudo /opt/melloa/worker/.venv/bin/melloa-pair-telegram \
    --bot-token-file /owner-input/telegram-bot-token
)"
```

Use a dedicated bot with no other active long poller. The pairing command removes an existing
webhook from that dedicated bot and discards stale pending updates before waiting for the owner.
Before an owner is bound, unrelated pending updates have no authority and are discarded; the exact
pairing update is also acknowledged so it does not become the first conversation message after
activation. The bot token is read only from the owner-private file and never printed. Telegram bot
chats still are not end-to-end encrypted.

With those files ready and the public-only Guardian projection already prepared by Guardian, the
configuration transaction performed by `first-install.sh` has this lower-level shape:

```bash
sudo /usr/local/libexec/melloa/configure \
  --source "$PWD" \
  --backup-repository /mnt/melloa-off-device-backup \
  --guardian-status-file /owner-input/guardian/status.json \
  --guardian-public-key-file /owner-input/guardian/public.pem \
  --telegram-owner-id "$TELEGRAM_OWNER_ID" \
  --telegram-bot-token-file /owner-input/telegram-bot-token \
  --capable-model-config-file /owner-input/capable-model.json \
  --economy-model-config-file /owner-input/economy-model.json \
  --model-credential capable-token=/owner-input/capable-token \
  --model-credential economy-token=/owner-input/economy-token \
  --restic-password-file /owner-recovery/restic-password \
  --self-change-disabled
```

Input file paths may differ, but the installed paths remain fixed and auditable. To enable
self-change workers during configuration, replace `--self-change-disabled` with
`--github-token-file /owner-input/github-token` plus either
`--codex-api-key-file /owner-input/codex-api-key` or `--codex-local-provider ollama` (or
`lmstudio`) and ensure that provider is actually reachable from the host service. The two
conversation routes remain separately configured; Codex planning credentials are never mounted into
the Melloa application.
The guided first-owner conversation setup deliberately accepts only hosted OpenAI-compatible routes
until a local model path has explicit container-networking and recovery proof. Lower-level model
configuration still validates private-network endpoints for future reviewed use.

The path-only `server.env` is produced from `server.env.example`. Every credential and owner-
specific JSON document remains a separate regular file. Credential files read by Melloa or the
backup process are owned by the dedicated runtime UID/GID and mode `0600`; private directories are
mode `0700`.

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

Self-change planning and application use two additional DSNs and login roles. The planner can
claim requests and retain proposals but cannot alter approval or deployment evidence. The applier
can retain candidate/deployment state but cannot alter requests, proposals, or approvals. The
planner receives Codex credentials but no Git-push or container-control authority; the applier
receives Git/Docker release authority but refuses to start with Codex or OpenAI credentials in its
environment. Hardened unit definitions now make release recovery a required oneshot predecessor,
hide Docker and deployment state from the planner, and hide Codex state from the applier. The units
are installed by the host-asset installer and verified before activation, but the ordering still
needs to pass on the actual server after reboot.

`install.sh` is the host-asset installer called by `first-install.sh`. It requires a clean current
`main` checkout, the Node.js and uv versions in `toolchain.lock`, Python 3.13+, Docker Compose
2.27+, systemd 249+, and Bubblewrap. The installed preflight requires the pinned Codex CLI only
when self-change workers are enabled, and then verifies the exact sandbox, approval, ephemeral,
user-config, and local-provider controls used by the planner. The installer creates the dedicated
`melloa-codex` identity, separate
public planning and credential-bearing release clones, a fixed unprivileged `melloa-runtime`
identity, immutable worker/verifier dependencies, and root-owned launchers and units. It
deliberately does not start anything or overwrite an existing owner configuration:

```bash
sudo infra/server/install.sh --source "$PWD"
sudo infra/server/preflight.sh --source "$PWD" --installed
```

Those remain engineering commands, not supported owner deployment instructions. The installed
preflight validates every runtime-owned private input, requires the backup repository to be a mount
on storage independent from the root filesystem, and accepts either disabled self-change workers,
a private Codex API-key file, or an explicitly selected `ollama`/`lmstudio` local provider. It also
runs Bubblewrap as the dedicated coding UID and validates the installed units on the target host.

After that preflight passes, `activate.sh` provides the bounded first-activation transaction called
by `first-install.sh`. It builds the exact installed revision, verifies the signed Guardian handoff,
both live model routes, the bot identity, and the exact private Telegram chat before starting owner-
facing work. It refuses an absent backup repository unless the operator explicitly selects
`--initialize-backup`, starts boot recovery before the first release, proves one encrypted snapshot,
and only then enables the planner and applier if self-change workers were explicitly enabled:

```bash
sudo infra/server/activate.sh --source "$PWD" --initialize-backup
```

This remains an engineering command until the same sequence, a reboot, a real conversation, a
restore drill, and an update/rollback drill have succeeded on the target server. Activation
deliberately prints that the README is still not ready; a healthy synthetic or partial activation
cannot change that contract.

After a reboot or maintenance window, the owner-facing health proof is:

```bash
sudo /usr/local/libexec/melloa/verify-owner-journey
```

It verifies enabled systemd services, running containers, the latest encrypted backup receipt, the
active release marker, and a fresh Telegram conversation through Melloa's real long-polling worker.
On success it also updates `/var/lib/melloa/runtime-state/owner-verification-status.json` with a
redacted receipt containing the verification time, active revision, backup snapshot ID, and internal
reply message ID; it deliberately does not store the Telegram verification phrase or reply text.
`/usr/local/libexec/melloa/qualification-record` prints that receipt together with the installed
revision, backup receipt, restore-drill receipt, backup mount status, and recent release history
for private owner notes.

For a non-destructive restore proof against the installed encrypted repository:

```bash
sudo /usr/local/libexec/melloa/restore-drill
```

The drill restores into a separate temporary Compose project and volume, runs migration check, and
proves the restored owner identity, Telegram binding, conversation proof, and read-only role
boundary before writing `/var/lib/melloa/runtime-state/restore-drill-status.json` and removing the
temporary project. It does not stop or overwrite the active deployment.

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

## Release activation and rollback

`tools/server_release.sh` is the current engineering release path. It accepts only a full lowercase
Git commit SHA, builds from a clean checkout by default, verifies both OCI revision labels, records
the immutable local image IDs, and serializes operations with a protected host lock. The release
state directory is mounted read-only into Melloa; Telegram polling and conversation model work stay
held until the candidate revision matches its atomically written activation file. The root-owned
directory is execute-only to non-root processes and the non-secret revision marker is read-only;
release state, history, and the operation lock remain root-only. This lets the dedicated runtime UID
read exactly the marker without granting release authority or exposing deployment records.

For an existing installation, deployment stops owner-facing work, takes an exact encrypted
snapshot under a separate release-retention tag, and only then runs candidate migrations and health
checks. The ten newest release snapshots are protected from normal daily pruning. A migration or
health failure replaces the database from that snapshot and restarts the prior image. `HUP`, `INT`,
and `TERM` during the transaction take the same recovery path. Every mutating phase is also recorded
in an atomically replaced, filesystem-synchronized operation journal before it begins. The `recover`
command resumes a first deployment or restores the prior database and release after an uncatchable
termination. Owner-facing work stays held until the journal is durably cleared. Explicit rollback
first snapshots current data and refuses to start an older image unless that image's migration
manifest accepts the current schema; it does not silently discard post-deployment owner data.

Owner-facing maintenance should use the installed wrappers:

```bash
sudo /usr/local/libexec/melloa/update
sudo /usr/local/libexec/melloa/rollback
```

Both wrappers finish by running `/usr/local/libexec/melloa/verify-owner-journey` unless explicitly
skipped for a staged test or emergency diagnosis. The lower-level release commands remain available
for engineering inspection:

The operator-shaped commands currently exercised by the disposable proof are:

```bash
tools/server_release.sh deploy \
  --env-file /etc/melloa/server.env \
  --state-dir /var/lib/melloa/release-state
tools/server_release.sh status \
  --state-dir /var/lib/melloa/release-state
tools/server_release.sh recover \
  --env-file /etc/melloa/server.env \
  --state-dir /var/lib/melloa/release-state
tools/server_release.sh rollback \
  --env-file /etc/melloa/server.env \
  --state-dir /var/lib/melloa/release-state
```

These are not owner-facing installation instructions. The disposable proof sends an untrappable
`SIGKILL` during the pre-activation window, confirms that the durable operation journal remains,
invokes `recover`, and verifies both the previous release and owner data. The installed
`melloa-release-recovery.service` is now ordered before the planner and applier, but that ordering
still has to pass during the real dedicated-server reboot drill before the root README can change
from `NOT READY`.

## Mechanical verification

For a disposable local proof using only synthetic credentials and public Guardian fixtures:

```bash
make server-runtime
```

That check builds both pinned runtime images, reconciles least-privilege database logins, applies
all migrations, and proves application restart and PostgreSQL recovery. It also exercises the real
scheduler through success, database outage, retry, encrypted-at-rest inspection, destruction of the
source database, and clean recovery of conversation, memory, session, and Telegram route state. The
same proof kills a candidate release process with `SIGKILL` before activation, recovers from the
durable journal, injects a broken release, installs a healthy release, and rolls it back while
verifying owner data after every recovery. It is
infrastructure evidence only—not real off-device storage or Telegram/provider dogfooding.
The `MELLOA_POSTGRES_IMAGE` and `MELLOA_RESTIC_IMAGE` overrides may name locally cached copies of
the exact pinned images when a registry is unavailable.
