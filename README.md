# Melloa

Melloa is the private, owner-controlled home of Melli: a persistent AI partner designed to know one
person better through time, remember useful history, follow through, and remain continuous when the
underlying model changes.

## Start here: first-owner home server

If your goal is to run Melli on a dedicated home server, use the public setup path:

- [Run Melloa on a home server](https://melloa-project.github.io/melloa/)
- [Deploy the server](https://melloa-project.github.io/melloa/deploy/)
- [Repository server deployment guide](docs/server-deployment.md)

The current first-server path is:

- Debian server, not the owner's laptop;
- Telegram bot chat as the normal owner interface;
- two hosted OpenAI-compatible conversation routes: one capable route and one cheaper economy route;
- no expected local model or GPU setup;
- automatic exact-owner Telegram pairing during guided setup;
- encrypted off-device backup setup and restore proof;
- bounded Codex/self-change workers enabled as part of the first server path.

The smallest loop is Telegram message → routed hosted-model reply → owner-approved self-change →
restart, rollback, and restore proof. Melloa should prove that loop before adopting a broad
multi-agent harness or gateway stack.

Command spine:

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

Before running `first-install.sh`, have that off-device backup path mounted, a dedicated Telegram
bot token, two hosted model route choices with reviewed pricing, a restic password retained away
from the server, a GitHub token for this repository, and a Codex/OpenAI API key for the bounded
planner worker. The public deploy page explains each input and the exact setup prompts.

## Evidence status

The path is implemented and covered by local/CI checks, including bootstrap smoke tests, guided setup
tests, Telegram verifier tests, backup/restore wrapper tests, Pages deployment, and visual smoke
checks. The remaining evidence is the owner's real dedicated-server run: live provider choices,
off-device backup retention, first Telegram conversation, reboot verification, restore drill,
owner-approved self-change deployment, update/rollback proof, and dogfooding.

That distinction is important, but it should not block the first manual deployment attempt. The
current job is to follow the guide, capture the concrete failures, and use the bounded self-change
loop to improve the path.

Codex CLI is not the normal conversation model route. The conversation path uses model-provider API
credentials entered during setup. Codex CLI is used by the bounded owner-approved self-change path:
`/change propose`, reviewable diff, exact Telegram approval token, commit, push, deploy, and
rollback evidence. The currently implemented unattended server credential modes are a Codex/OpenAI
API key or an explicitly configured local provider; an interactive ChatGPT/Codex subscription login
is not supported as unattended server auth for this path.

If Codex CLI becomes the preferred economics for ordinary conversation, that should be implemented
as a separate conversation adapter with no source checkout, no file-write authority, no release
credentials, and its own unattended-service proof. It should not reuse the confined self-change
planner.

## Current status

Melloa is in an owner-experience reset. The active work is subtractive: collapse the
operations-console experience, remove speculative architecture and preview machinery, and make
conversation with Melli the unmistakable product. There is no milestone implementation queue and no
compatibility promise for preview behavior.

The main branch now has an exact-owner Telegram long-polling path with a PostgreSQL cursor,
canonical conversation continuity, restart-safe reply delivery, and explicit `capable`/`economy`
model routing. The selected route and actual model destination survive retries and are retained with
the conversation; Melloa never silently falls back across routes. The server runtime gates startup
on migrations, restarts cleanly after application or PostgreSQL failure, streams encrypted snapshots
into an owner-mounted repository, reports backup health through `/status`, and has restore-drill,
update, rollback, and boot-reconciliation wrappers. A Debian 13 bootstrap and guided first-install
wrapper now compose prerequisite installation, private configuration prompts, generated model route
JSON, exact Telegram owner pairing, backup initialization, activation, and a database-backed first
Telegram conversation proof into one server path.

Read [the current product direction](PRODUCT_DIRECTION.md) before treating any existing code or test
as a requirement.

The public project website is a Starlight site in [docs-site](docs-site), deployed by the Pages
workflow. It is the owner-facing setup path; the old MkDocs architecture bundle is not active
guidance.

The current fork/adopt decision is conservative: use Hermes, OpenClaw-style gateways, AgentTeams,
and similar systems as references, but do not fork them as the Melloa runtime foundation until the
one-owner recoverable self-change loop is proven on a real server.

## What the first real server run must prove

The first manual server deployment should produce evidence that:

- runs Melli persistently, survives reboots, restarts cleanly, and can roll back a failed release;
- gives the owner a simple private Telegram chat as the normal interface;
- supports deliberate routing across capable and cheaper hosted model routes without pretending one
  model is Melli;
- proves the bounded owner-approved Codex self-change loop: explicit public-safe request, retained
  proposal diff, exact Telegram approval, verified commit/push/deploy, and rollback path;
- needs machine login only for rare maintenance and makes failures visible from the owner interface;
- keeps a controlled, incremental path for connecting more owner services and data later.

## Disposable local preview, not server setup

This section is for inspecting the current local baseline on a development machine. It is not the
dedicated-server path, does not connect Telegram, and should not be used as the owner deployment
guide. Use [the server deployment guide](docs/server-deployment.md) for the Telegram/server path.

Melloa requires Linux or macOS, Bash, Python 3.13+, uv 0.12.0, and Node.js 22+. Preparing the
separate Guardian handoff additionally requires Go 1.24+ and the Guardian repository beside this
one:

```bash
git clone https://github.com/melloa-project/melloa.git
git clone https://github.com/melloa-project/melloa-guardian.git
```

For local preview only, follow the [local disposable preview guide](docs/getting-started.md) to
create an owner-controlled, public-only signed `offline` handoff. Then export only those two public
paths and start Melloa:

```bash
cd melloa-guardian
make preview-state
export GUARDIAN_STATUS="$PWD/state/local-preview/status.json"
export GUARDIAN_PUBLIC_KEY="$PWD/state/local-preview/public.pem"
cd ../melloa
make preview
```

Or, if the Guardian handoff already exists:

```bash
cd melloa
export GUARDIAN_STATUS=/absolute/path/to/status.json
export GUARDIAN_PUBLIC_KEY=/absolute/path/to/public.pem
make preview
```

Melloa verifies the handoff, starts both services on loopback, prints a disposable owner credential,
and removes only its own credential and logs on `Ctrl-C`. Only the status and public-key paths are
passed; no Guardian private key, journal, lock, CLI argument, or mutation command is passed. Melloa
does not remove the supplied handoff.

To exercise one disposable on-device model in the local preview:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
make preview PREVIEW_MODEL=ollama
```

This remains disposable and is not the target first-server experience. The first-server guide uses
hosted OpenAI-compatible provider routes instead of assuming local model hardware.

## Current Telegram model controls

The server integration now requires two distinct model config files whenever Telegram is enabled.
The guided first-owner setup generates these files from prompts:

- `--capable-model-config` can target an OpenAI-compatible Responses API by setting
  `"api_style": "responses"`; this is the bounded path intended for a capable OpenAI model;
- `--economy-model-config` can target a cheaper hosted router or a private/local compatible model;
  for first deployment, prefer a hosted OpenAI-compatible endpoint with reviewed pricing and a
  bearer token. Local model configuration remains lower-level engineering material.

Each file declares its exact endpoint, model, processing location, sensitivity allowance, token and
cost ceilings, timeout, and optional owner-only token file. External owner context is sent only to
the explicitly selected route. API requests ask the provider not to store responses, and a route
outage is reported rather than triggering a different provider or cost boundary.

In the exact-owner private Telegram chat:

- `/model` reports the saved route;
- `/model economy` and `/model capable` change the route for later messages;
- `/think …` uses the capable route once without changing the saved route;
- `/status` reports the selected route and health of both configured targets.

Telegram bot chats are not end-to-end encrypted; "private" here means the bot accepts only the
configured numeric owner and one-to-one chat, not Secret Chat-level secrecy.

These mechanics are tested across PostgreSQL restart and recovery. The first real server run still
needs live provider, backup, reboot, restore, update/rollback, and self-change evidence.

## What must remain true

- Melloa is the system; Melli is the persistent intelligence, not a model or process.
- Guardian stays independently owner-controlled and outside Melloa's authority.
- Owner data is private by default and remains under owner control.
- Models cannot authorize their own external effects.
- Sensitive external disclosure is explicit.
- High-risk and irreversible actions fail closed behind deterministic constraints.

The concise, implementation-independent rules are in
[trust boundaries](docs/trust-boundaries.md).

The current readable portability copy and its exclusions are documented in
[owner export](docs/owner-export.md).

## Work on Melloa

```bash
make bootstrap
make check
```

PostgreSQL and recovery checks additionally require Docker:

```bash
make integration
make recovery
```

See [development](docs/development.md). Product changes must be exercised as an actual owner journey
on desktop and mobile; passing fixture and contract tests is not product validation.

## Source status

No public source license has been selected. The repository may be readable, but reuse,
redistribution, and outside contributions require explicit license terms from the owner.
