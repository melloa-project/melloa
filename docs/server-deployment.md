# First-owner server deployment path

This is the canonical owner-facing path for the first dedicated home-server deployment attempt. It
does not change the repository readiness banner by itself: the path still needs to pass on the real
server, survive reboot, prove recovery, and be dogfooded before the root README can honestly say
ready.

## Supported starting point

Use a fresh Debian 13 (`trixie`) amd64 machine booted with systemd. The machine should be a
dedicated always-on server, not the owner's everyday laptop or desktop.

Before cloning Melloa, attach and mount backup storage that is independent from the server's root
disk. Keep the restic password somewhere the server and backup repository cannot both lose.

Choose the mount path before setup. The guided path defaults to
`/mnt/melloa-off-device-backup`, but any plain absolute path is acceptable if it is an explicit
mount on storage independent from `/`. The exact filesystem/device setup is host-specific; after
mounting it, verify the property Melloa will enforce:

```bash
sudo mkdir -p /mnt/melloa-off-device-backup
findmnt --mountpoint /mnt/melloa-off-device-backup
test "$(stat --format='%d' /mnt/melloa-off-device-backup)" != "$(stat --format='%d' /)"
```

If either check fails, fix the mount before running first install. Do not continue by creating an
ordinary directory on the server disk; Melloa will refuse it because that would make a disk loss take
both the live data and the backup repository.

## Values to have ready

The guided setup prompts for these values and writes the private files for you:

- a dedicated Telegram bot token from BotFather; setup can clear an existing webhook, but no other
  long poller should be using the bot;
- Guardian's public-only `status.json` and `public.pem` handoff files;
- capable and economy hosted OpenAI-compatible model choices: base URL, model ID, API style,
  bearer token, sensitivity approval, and reviewed GBP token/cost ceilings;
- a high-entropy base64url restic password retained away from this server and the backup repository.

Do not paste secret values into shell commands. The setup prompts read them without echoing and
stores them as owner-private files.

Generate and store the restic password before setup in a password manager or another owner-retained
place that is not the server and not the backup disk. If you need a command, run this on a trusted
machine and store the exact output:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

The setup accepts only 32-128 base64url-safe characters for that password. If the server and backup
repository are both lost, this retained password is what makes the encrypted backup restorable.

The first deployment defaults optional self-change workers off. If you intentionally enable them
during setup, also have a fine-grained GitHub token for this repository with contents read/write
access and either a Codex API key or an explicitly installed local Codex provider (`ollama` or
`lmstudio`). For the first owner conversation, choose the default `no` when setup asks about
self-change workers. When disabled, activation stops and disables those units, and the units
themselves are condition-gated so accidental manual starts are skipped.

The normal bootstrap does not install Codex CLI. If you deliberately want self-change workers
during the first deployment, rerun bootstrap with `--self-change-tools` before choosing `yes` in
first install.

For the first deployment, use one of these model prompt patterns:

- simplest hosted path: choose `openai` for both routes, use a stronger model ID for `capable`, a
  cheaper distinct model ID for `economy`, and enter the current GBP token prices and per-request
  ceilings you have reviewed for your account;
- alternate hosted path: choose `external` for a route only when you already have a reviewed
  OpenAI-compatible HTTPS provider, model ID, API style, bearer token, and price ceilings.

The guided first-owner path does not currently configure a local conversation model. Docker host
networking, model bind addresses, and disclosure classification need a separately tested path
before that option is safe to make owner-facing.

If the capable and economy targets resolve to the same base URL and model ID, setup refuses the
configuration. That is intentional: Melloa must not silently blur quality, cost, or disclosure
boundaries between routes just because the route labels differ.

## Install and activate

On the fresh server, clone Melloa and install the reviewed host prerequisites:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends ca-certificates git
git clone https://github.com/melloa-project/melloa.git
cd melloa
sudo infra/server/bootstrap-debian.sh --source "$PWD"
```

The bootstrap installs and verifies Docker, Compose, Python, Node.js, uv, and Go. Go is needed only
to create the public Guardian handoff used by this first deployment path.

If you deliberately plan to enable optional self-change workers during this first setup, prepare the
pinned Codex CLI before first install:

```bash
sudo infra/server/bootstrap-debian.sh --source "$PWD" --self-change-tools
```

If the server needs an owner-approved outbound TLS proxy or private CA, pass its public PEM bundle
to bootstrap with `--ca-file /absolute/path/to/ca.pem`, then pass the same flag to first install
below. Melloa copies that public CA bundle into `/etc/melloa/build-ca.pem` for future image builds
and update checks; it does not install it as a machine-wide trust root.

Create the public-only Guardian handoff beside the Melloa checkout:

```bash
cd ..
git clone https://github.com/melloa-project/melloa-guardian.git
cd melloa-guardian
make preview-state
cd ../melloa
```

`make preview-state` prints the two public paths the guided setup will ask for:

```text
.../melloa-guardian/state/local-preview/status.json
.../melloa-guardian/state/local-preview/public.pem
```

Only those two public files are passed to Melloa. Do not pass Guardian private keys, journals, lock
files, or control commands.

Then run the guided first install:

```bash
sudo infra/server/first-install.sh --source "$PWD"
```

If bootstrap used `--ca-file`, run:

```bash
sudo infra/server/first-install.sh --source "$PWD" --ca-file /absolute/path/to/ca.pem
```

The first-install step installs host assets, prompts for private values, generates model route
configuration, pairs the exact Telegram owner chat, initializes backup when approved, activates
Melloa, and then runs the final owner-journey verifier.

Before asking for Telegram, model, or backup secrets, setup checks that the backup repository path
is a plain absolute path and, on the real server, an explicit mount on storage independent from the
root filesystem. It also checks that the two Guardian handoff paths are readable public files. If
any of those fail, fix the path or mount and rerun the same command. As each secret is entered,
setup checks its expected syntax without printing the value, so a pasted wrong token fails before
later model or activation work. Model route prompts also reject malformed provider IDs, oversized
model IDs, non-HTTPS hosted endpoints, and malformed cost/timeout values before asking for the
model bearer token. After Telegram pairing and model prompts, setup performs a live read-only check
of the Guardian handoff, both model routes, the bot identity, and the paired private chat before it
writes permanent private configuration. If that check fails, fix the reported Telegram or model
input and rerun the same first-install command.

During Telegram pairing, setup removes any existing webhook from the dedicated bot and discards
stale pending updates before waiting for the owner. Send the exact `/start ...` phrase printed in
the terminal to the bot's private chat. During final verification, send the exact setup message
printed in the terminal. The verifier then checks Melloa's durable state to prove the message was
accepted by the real long-polling worker, answered by the configured model route, and delivered
back through Telegram.

## First conversation

After the verifier passes, continue in the same Telegram chat:

```text
/status
```

Then send the first ordinary message to Melli. Telegram is the normal owner interface; machine login
should be rare after setup.

Do not treat this as a completed deployment yet. The first real server still has to pass the reboot
verifier, restore drill, and a real later update/rollback path before the repository readiness
banner can change.

## Private qualification record

Keep a short private record from the first real server run. Do not paste raw logs publicly; verifier
output can contain the one-time Telegram phrases and provider errors can contain account-specific
details. Each successful owner verifier run updates this redacted local receipt without storing the
verification phrase or reply text:

```bash
sudo jq . /var/lib/melloa/runtime-state/owner-verification-status.json
```

For a fuller redacted snapshot of the installed release, backup receipt, restore-drill receipt,
latest owner verifier receipt, and recent release history, run:

```bash
sudo /usr/local/libexec/melloa/qualification-record
```

A sufficient private record is:

- the installed Melloa commit SHA from `git -C /srv/melloa/release-source rev-parse HEAD`;
- the backup mount path and confirmation that `findmnt --mountpoint` showed it as an explicit mount
  independent from `/`;
- the `verified_at`, `active_revision`, and `backup_snapshot_id` values from the verifier receipt
  after first install's Telegram verifier passed;
- the `/status` result after setup, including model route health and backup health;
- the verifier receipt values after reboot when
  `sudo /usr/local/libexec/melloa/verify-owner-journey` passed;
- the restore-drill receipt values printed by
  `sudo /usr/local/libexec/melloa/qualification-record`;
- the verifier receipt values after active verification passed again after the restore drill;
- after a later reviewed commit reaches `main`, the `maintenance_history` entries showing the
  verified update and rollback wrappers plus the final active owner-verifier receipt.

This record is owner evidence for changing the repository readiness banner later; it is not a
secret handoff file and Melloa does not need to read it.

## After reboot or maintenance

After rebooting the server, rerun the owner-facing verifier:

```bash
sudo /usr/local/libexec/melloa/verify-owner-journey
```

It checks enabled systemd services, running containers, the active release marker, the configured
backup repository mount, the latest encrypted backup receipt, and a fresh Telegram conversation
through Melloa's real worker.

## Backup and recovery

Backups run automatically after activation and then daily. `/status` reports backup health. A failed
backup remains visible until a complete backup and repository check succeeds.

Keep the restic password outside both Melloa and the backup repository. Without that password, the
encrypted backup repository cannot be restored.

The detailed restore boundary is in [recovery](recovery.md). Before treating this path as ready for
owner deployment, run the non-destructive server restore drill:

```bash
sudo /usr/local/libexec/melloa/restore-drill
```

It restores the latest encrypted snapshot into a separate temporary Docker Compose project and
database volume, runs migration check against that restored database, proves the restored owner
identity, Telegram binding, conversation proof, and read-only role boundary, writes a redacted local
receipt, and removes the temporary project before exit. It does not stop or overwrite the active
Melloa deployment. If it fails, fix the reported backup or migration issue and rerun the active
owner verifier before continuing.

Then rerun the owner-facing verifier against the active deployment:

```bash
sudo /usr/local/libexec/melloa/verify-owner-journey
```

## Updates and rollback

Do not update by editing containers, environment files, or database state directly. Use the installed
wrapper so host assets, images, release state, backup checks, and final Telegram verification stay in
one path:

```bash
sudo /usr/local/libexec/melloa/update
```

That command updates the managed `/srv/melloa/release-source` checkout to the current reviewed
`main`, refreshes installed host assets, activates through the normal backup-protected release path,
and then asks for one Telegram verification message. After a successful final verification it appends
a redacted `update` entry to the local maintenance history shown by
`sudo /usr/local/libexec/melloa/qualification-record`. If it fails, use the exact wrapper message
first; it names whether to rerun update, start boot recovery, verify the active deployment, or roll
back. If it fails after stopping owner-facing work, do not improvise; run:

```bash
sudo systemctl start melloa-release-recovery.service
sudo /usr/local/libexec/melloa/verify-owner-journey
```

Rollback proof requires a previous recorded release. Immediately after the first install there may
not be one: if `main` has not advanced, `update` can refresh the active deployment but it cannot
create a meaningful rollback target. For first-server qualification, run `update` after a later
reviewed commit has reached `main`, verify Telegram through that updated release, and only then run
the rollback wrapper below.

To roll back after a bad update:

```bash
sudo /usr/local/libexec/melloa/rollback
```

Rollback snapshots current owner data first and refuses an older release if its migration manifest
cannot accept the current database. It does not silently discard conversations after the update. The
rollback command also ends with the Telegram verifier and appends a redacted `rollback` entry to the
same local maintenance history when that verifier passes.

## If setup fails

Use the exact failing command's message first; the scripts are designed to say what must be fixed.
Activation failures include a phase-specific recovery or rerun command; follow that command before
rerunning first install or update.
Common recoveries:

- bootstrap rejects the host: use Debian 13 amd64 with systemd and remove conflicting Docker
  packages from the fresh-host path;
- Telegram pairing fails: stop any other long poller, confirm the dedicated bot token is valid, and
  retry; if setup reports the webhook still exists, remove it manually from the previous owner and
  rerun;
- model verification fails: check the base URL, token file, model ID, API style, and owner-reviewed
  cost/sensitivity limits;
- activation fails while building images: check Docker Hub/GHCR registry access and proxy/CA
  settings; if a private CA is required, rerun bootstrap and first install with the same
  `--ca-file`; if private configuration was already installed, rerunning first install updates the
  stored public build CA bundle, then resumes activation and verification without asking for the
  secrets again;
- backup verification fails: confirm the backup path is an explicit mount on storage independent
  from the root filesystem and that the restic password is the intended one;
- final Telegram verification times out: send the exact printed message to the paired private bot
  chat, inspect `/status`, then rerun
  `sudo /usr/local/libexec/melloa/verify-owner-journey`.

For implementation details, see the server technical reference in [infra/server](../infra/server/README.md).
