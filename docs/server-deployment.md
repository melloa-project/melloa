# First-owner server deployment path

This is the canonical owner-facing path for the first dedicated home-server deployment. Follow it on
the real server and keep the evidence it asks for: first Telegram conversation, bounded self-change,
reboot verification, restore drill, update/rollback, and dogfooding.

The current gap is evidence, not a second hidden installation path. If something fails, fix the
reported cause, rerun the same step, and improve this guide or the setup scripts from the concrete
failure.

## Direction in plain terms

This path is meant to produce one persistent Melli you talk to from Telegram. It is not a local-model
project and it is not an operations console project.

The first deployment path is:

1. prepare a fresh Debian server;
2. mount off-device backup storage;
3. clone Melloa and bootstrap host prerequisites;
4. prepare Guardian's public-only handoff;
5. install the pinned Codex CLI toolchain for the bounded self-change workers;
6. run one guided setup command;
7. pair a dedicated Telegram bot;
8. enter two hosted OpenAI-compatible model routes:
   - `capable` for higher-quality replies;
   - `economy` for cheaper routine replies;
9. enable the bounded self-change workers during setup;
10. verify one real Telegram conversation through the installed worker;
11. complete one owner-approved `/change` proposal, approval, deploy, and rollback evidence path
    before treating the first server path as proven.

For this first path, assume hosted model APIs. You do not need Ollama, a GPU, or a local model. A
cheaper online provider is fine when it offers an owner-reviewed HTTPS OpenAI-compatible endpoint,
model ID, API style, bearer token, and token pricing. If a provider does not expose that shape,
use a reviewed compatible router or defer it.

Codex CLI is separate from normal Melli conversation. It is required for the bounded self-change
path: the owner asks for a public-safe source change from Telegram, reviews the exact diff, approves
the exact proposal token, and the worker may then test, commit, push, and deploy only that retained
diff. This is not arbitrary self-modification.

The currently implemented unattended Codex credential modes are:

- `api-key`: a Codex/OpenAI API key read from a private file by the planner;
- `local`: an explicitly installed `ollama` or `lmstudio` provider.

Because the first deployment is hosted-provider-first and does not assume local model hardware, use
`api-key` for the first self-change proof. Interactive ChatGPT/Codex subscription login is not the
supported unattended systemd service auth mode for this path.

## Fast path

The complete command spine is intentionally short:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends ca-certificates git
git clone https://github.com/melloa-project/melloa.git
cd melloa

# After attaching and mounting off-device backup storage:
sudo mkdir -p /mnt/melloa-off-device-backup
findmnt --mountpoint /mnt/melloa-off-device-backup
test "$(stat --format='%d' /mnt/melloa-off-device-backup)" != "$(stat --format='%d' /)"

sudo infra/server/bootstrap-debian.sh --source "$PWD" --self-change-tools

cd ..
git clone https://github.com/melloa-project/melloa-guardian.git
cd melloa-guardian
make preview-state
cd ../melloa

sudo infra/server/first-install.sh --source "$PWD"
```

When setup asks whether to enable self-change workers, answer `yes`. On a real interactive server
install, `yes` is the default. Choosing `no` can be useful for a deliberate conversation-only
bring-up, but that run skips the core self-change proof.

The rest of this document explains what must be ready before those commands and how to prove the
result afterward.

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
- two hosted OpenAI-compatible conversation model choices:
  - `capable`: the stronger model Melli should use when quality matters;
  - `economy`: a cheaper compatible model/provider for routine replies;
- for each model route: base URL, model ID, API style, bearer token, sensitivity approval, reviewed
  GBP token prices, and a per-request cost ceiling;
- a fine-grained GitHub token for this repository with contents read/write access, used only by the
  self-change applier after exact owner approval;
- a Codex/OpenAI API key for the self-change planner, unless you are deliberately exercising a
  separate local-provider path;
- a high-entropy base64url restic password retained away from this server and the backup repository.

Do not paste secret values into shell commands. The setup prompts read them without echoing and
stores them as owner-private files.

Use this worksheet before starting the server install:

| Setup prompt area | What to have ready | What to enter for this first path |
| --- | --- | --- |
| Backup repository | Mounted off-device directory, normally `/mnt/melloa-off-device-backup` | The exact mount path |
| Guardian handoff | Public `status.json` and `public.pem` from the sibling Guardian checkout | The two printed public file paths |
| Telegram | Dedicated BotFather bot token; no other long poller using the bot | The bot token, then the exact `/start ...` phrase printed by setup |
| Capable model route | Hosted OpenAI-compatible model for higher-quality replies | Usually `openai`, then the model ID, reviewed GBP prices, cost ceiling, and API key |
| Economy model route | Cheaper hosted OpenAI-compatible model/provider for routine replies | `openai` with a cheaper model, or `external` with explicit provider URL, API style, model ID, bearer token, and GBP prices |
| Restic recovery | 32-128 character base64url password stored away from this server and backup disk | The exact retained password |
| Self-change | GitHub repository token plus Codex/OpenAI API key | `yes`, `api-key`, optional model override blank unless reviewed |

For external hosted model routes, do not guess. The provider must give you an HTTPS
OpenAI-compatible base URL, exact model ID, whether to use `responses` or `chat_completions`,
bearer token, input price per million tokens, and output price per million tokens. If the provider
lists prices in another currency, convert them to GBP before setup so Melloa can retain one
auditable cost boundary. A cheaper frontier-lab or router provider is acceptable only when those
facts are explicit.

Generate and store the restic password before setup in a password manager or another owner-retained
place that is not the server and not the backup disk. If you need a command, run this on a trusted
machine and store the exact output:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

The setup accepts only 32-128 base64url-safe characters for that password. If the server and backup
repository are both lost, this retained password is what makes the encrypted backup restorable.

The first owner conversation does not need Codex CLI, but the first server path includes bounded
self-change. Bootstrap with `--self-change-tools` and choose `yes` when setup asks about
self-change workers. If you choose `no`, activation stops and disables those units, and the units
themselves are condition-gated so accidental manual starts are skipped; that is a conversation-only
bring-up.

For unattended tests and staged dry-runs, setup still defaults self-change to disabled unless
`MELLOA_SETUP_ENABLE_SELF_CHANGE=yes` is supplied. That noninteractive default is not the owner
server path.

When setup asks for the Codex self-change planner credential mode, choose `api-key` for this hosted
first path. The `local` mode is retained for separately tested `ollama` or `lmstudio` deployments,
not for the first home-server target described here.

For the model prompts, use one of these hosted patterns:

- simplest hosted path: choose `openai` for both routes, use a stronger model ID for `capable`, a
  cheaper distinct model ID for `economy`, and enter the current GBP token prices and per-request
  ceilings you have reviewed for your account;
- mixed hosted path: choose `openai` for `capable` and `external` for `economy` when the cheaper
  provider exposes a reviewed OpenAI-compatible HTTPS endpoint, model ID, API style, bearer token,
  and price ceilings;
- external hosted path: choose `external` for both routes only when both providers already meet the
  same compatibility and pricing requirements.

The guided first-owner path does not currently configure a local conversation model. Docker host
networking, model bind addresses, and disclosure classification need a separately tested path
before that option is safe to make owner-facing.

If the capable and economy targets resolve to the same base URL and model ID, setup refuses the
configuration. That is intentional: Melloa must not silently blur quality, cost, or disclosure
boundaries between routes just because the route labels differ.

## Install and activate

On the fresh server, clone Melloa and install the reviewed host prerequisites plus the pinned Codex
CLI required by the self-change workers:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends ca-certificates git
git clone https://github.com/melloa-project/melloa.git
cd melloa
sudo infra/server/bootstrap-debian.sh --source "$PWD" --self-change-tools
```

The bootstrap installs and verifies Docker, Compose, Python, Node.js, uv, Go, and the reviewed
Codex CLI. Go is needed only to create the public Guardian handoff used by this first deployment
path. Codex CLI is needed only by the self-change planner; it is not mounted into the normal
conversation worker and does not receive private chat history.

If you are doing a conversation-only bring-up and intentionally not exercising self-change yet, you
can omit `--self-change-tools`; run the self-change proof before treating the server path as
exercised.

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

The model prompts are intentionally explicit:

- choose `openai` for the fixed OpenAI HTTPS base URL and Responses API style;
- choose `external` for another hosted OpenAI-compatible provider or router;
- enter the exact model ID from that provider;
- enter reviewed token prices and a maximum GBP cost per request;
- enter the bearer token only when setup asks for the secret.

Do not enter guessed zero prices just to get through setup. The retained route record is what Melloa
uses to report and constrain model cost/disclosure boundaries.

The self-change prompts are intentionally separate from the conversation model prompts:

- answer `yes` to enabling self-change workers;
- enter the GitHub token only when setup asks for it;
- choose `api-key` for the Codex self-change planner credential mode;
- leave the optional Codex model override blank unless you have reviewed a specific model choice for
  this account;
- enter the Codex/OpenAI API key only when setup asks for the secret.

Do not paste a ChatGPT/Codex subscription login artifact into these prompts. The current server path
uses an API key for unattended planner service auth.

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

Treat the first conversation as the point where Melli is alive, not the end of the first deployment
proof. Next, prove self-change, reboot recovery, restore, and update/rollback.

## Self-change proof

After the first Telegram conversation works, prove the bounded self-change loop on the real server.
Use a small, public-safe request in the current allowed source/test area, not a private-memory
feature and not infrastructure, release, authentication, Guardian, Telegram binding, database,
migration, or self-change-policy work.

In Telegram:

```text
/change propose <one small public-safe source/test improvement>
```

For the first proof, prefer a tests-only request. Example shape:

```text
/change propose Add a focused unit test for one existing owner-visible /change command message.
```

Do not ask the self-change worker to alter deployment scripts, secrets, Guardian, Telegram pairing,
database roles, migrations, release policy, or self-change policy during this first proof.

Wait for the planner to return a proposal, then inspect it:

```text
/change
/change diff <change_id>
```

Approve only if the retained diff is exactly acceptable:

```text
/change approve <change_id> <16-character proposal token>
```

The applier may then test, commit, push, and deploy only that exact retained diff. After it
finishes, record:

- `/change show <change_id>` with `State: deployed`, the proposal digest, and the deployed revision;
- `sudo /usr/local/libexec/melloa/qualification-record` showing `self_change_enabled: true` and
  `codex_mode: api_key`;
- the remote `main` revision matching the deployed change;
- a fresh `sudo /usr/local/libexec/melloa/verify-owner-journey` after the self-change deployment;
- rollback evidence from the installed rollback wrapper when proving the full maintenance path.

If self-change was disabled during first install, this section cannot pass. Treat that server as a
conversation-only bring-up until you perform a reviewed reconfiguration path and rerun the evidence.

## Private first-run record

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
- the self-change receipt: `/change show <change_id>` after the approved change reaches
  `State: deployed`, including the proposal digest and deployed revision;
- the verifier receipt values after reboot when
  `sudo /usr/local/libexec/melloa/verify-owner-journey` passed;
- the restore-drill receipt values printed by
  `sudo /usr/local/libexec/melloa/qualification-record`;
- the verifier receipt values after active verification passed again after the restore drill;
- after a later reviewed commit reaches `main`, the `maintenance_history` entries showing the
  verified update and rollback wrappers plus the final active owner-verifier receipt.

This record is owner evidence for deciding what to fix next and when the first-server path has been
exercised end to end. It is not a secret handoff file and Melloa does not need to read it.

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

The detailed restore boundary is in [recovery](recovery.md). During the first server proof, run the
non-destructive server restore drill:

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
create a meaningful rollback target. For the first server proof, run `update` after a later reviewed
commit has reached `main`, verify Telegram through that updated release, and only then run the
rollback wrapper below.

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
