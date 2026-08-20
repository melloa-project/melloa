# Melloa

Melloa is the private, owner-controlled home of Melli: a persistent AI partner designed to know one
person better through time, remember useful history, follow through, and remain continuous when the
underlying model changes.

> **Deployment readiness: NOT READY**
>
> Do not deploy this repository as your persistent Melli yet. The runnable path below is a disposable
> engineering baseline, not the low-maintenance server product described in “What ready means.”

If your immediate goal is the dedicated home-server path, start with the
[first-owner server deployment guide](docs/server-deployment.md), not the disposable preview below.
The current intended first-server shape is:

- Debian server, not the owner's laptop;
- Telegram bot chat as the normal owner interface;
- two hosted OpenAI-compatible conversation routes: one capable route and one cheaper economy route;
- no expected local model or GPU setup for the first deployment;
- bounded Codex/self-change workers explicitly enabled and proven before this repository can be
  called ready for owner deployment.

Codex CLI is not the normal conversation model route. The conversation path uses model-provider API
credentials entered during setup. Codex CLI is used by the bounded owner-approved self-change path:
`/change propose`, reviewable diff, exact Telegram approval token, commit, push, deploy, and
rollback evidence. The currently implemented unattended server credential modes are a Codex/OpenAI
API key or an explicitly configured local provider; an interactive ChatGPT/Codex subscription login
has not been qualified as server auth.

## Current status

Melloa is in an owner-experience reset. The existing `v0.2.0` preview proves private conversation,
model disclosure, owner-data controls, and consumption of a signed read-only Guardian projection,
but it is not yet a compelling daily-use partner. The preview does not prove host isolation or
timely Guardian enforcement. Without an explicitly configured model, conversation is unavailable;
the preview no longer substitutes a fixture response for Melli thinking.

The active work is subtractive: collapse the operations-console experience, remove speculative
architecture and preview machinery, and make conversation with Melli the unmistakable product.
There is no milestone implementation queue and no compatibility promise for preview behavior.

The main branch now has an exact-owner Telegram long-polling path with a PostgreSQL cursor,
canonical conversation continuity, restart-safe reply delivery, and explicit `capable`/`economy`
model routing. The selected route and actual model destination survive retries and are retained with
the conversation; Melloa never silently falls back across routes. A generic, unexposed container
runtime now gates startup on migrations and recovers from application or PostgreSQL restarts, but
it remains an [engineering checkpoint](infra/server/README.md), not a qualified owner deployment
path. It now streams automatic encrypted snapshots into an owner-mounted repository, reports backup
health through `/status`, and proves a clean restore of representative owner state. A release tool
now builds reviewed commits, holds Telegram and model work until atomic activation, takes an exact
pre-deploy snapshot, recovers interrupted or unhealthy candidates, and supports schema-checked
rollback. Its durable release journal now also survives an uncatchable process termination and
recovers through an installed boot-reconciliation unit. A Debian 13 bootstrap and guided
first-install wrapper now compose the prerequisite installation, private configuration prompts,
generated model route JSON, exact Telegram owner pairing, backup initialization, activation, and a
database-backed first Telegram conversation proof into one server path. This is still not a
qualified owner deployment: real provider selections, a real off-device repository and recovery-key
retention, live server installation, reboot/recovery drills, one owner-approved Codex/self-change
deployment, update/rollback evidence, and deployed dogfooding remain incomplete.

Read [the current product direction](PRODUCT_DIRECTION.md) before treating any existing code or test
as a requirement.

The current first-owner server deployment path is the
[server deployment guide](docs/server-deployment.md). It is intentionally still a qualification path,
not a readiness claim, until it has succeeded on the real dedicated server with reboot, recovery,
update/rollback, and dogfooding evidence.

## What “ready” means

This banner will change to **READY FOR OWNER DEPLOYMENT** only when this README also provides one
tested server installation and recovery path that:

- runs Melli persistently, survives reboots, restarts cleanly, and can roll back a failed release;
- gives the owner a simple private Telegram chat as the normal interface;
- supports deliberate routing across OpenAI/Codex-capable workflows and configurable cheaper or
  open models without pretending one model is Melli;
- proves the bounded owner-approved Codex self-change loop on the real server: explicit public-safe
  request, retained proposal diff, exact Telegram approval, verified commit/push/deploy, and a
  rollback path;
- needs machine login only for rare maintenance and makes failures visible from the owner interface;
- keeps a controlled, incremental path for connecting more owner services and data later.

Until every item is exercised as a real owner journey on a deployed machine, Melloa is not ready in
the sense used by this project or this README.

The banner at the top of this README is the authoritative answer. When the system is ready, it will
say **READY FOR OWNER DEPLOYMENT** and this README will contain the tested installation command,
first Telegram conversation, update, rollback, and recovery journey. If it still says `NOT READY`,
there is no supported persistent deployment to infer from lower-level engineering notes.

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

First follow the [short baseline guide](docs/getting-started.md) to create an owner-controlled,
public-only signed `offline` handoff. Then export only those two public paths and start Melloa:

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

Telegram bot chats are not end-to-end encrypted; “private” here means the bot accepts only the
configured numeric owner and one-to-one chat, not Secret Chat-level secrecy.

These mechanics are tested across PostgreSQL restart and recovery, but no real provider/server
journey has yet qualified them for the readiness banner above.

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
