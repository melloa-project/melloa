# Start Melloa locally

This is the shortest complete Melloa owner journey: start a private console, have a canonical conversation, inspect why the system responded, review owner-visible evidence, export your state, and stop cleanly.

The default local run is deliberately safe and truthful. It binds only to loopback, uses disposable process-local state, keeps Guardian separately signed in `offline` mode, makes no external model call, and labels the guided response as a fixed fixture rather than Melli. An explicit selector adds one reviewed on-device model without changing those authority or persistence boundaries.

The login screen and signed-in console identify this snapshot as **v0.2.0 preview**. The same system-status response reports milestone **M1** and architecture baseline **v0.2**. If those surfaces disagree, stop and update a clean checkout rather than trusting mixed release evidence.

## What you need

- Linux or macOS with Bash;
- Python 3.13 or newer;
- [uv](https://docs.astral.sh/uv/) 0.12.0;
- Node.js 22 or newer;
- Go 1.24 or newer;
- the public Melloa and Guardian repositories as sibling directories.

Docker, PostgreSQL, API keys, model downloads, Telegram, cameras, and private deployment state are not required for the default tour. The optional Melli path below additionally requires Ollama and the reviewed `qwen3:4b-instruct-2507-q4_K_M` model.

## Start the complete preview

From a new workspace:

```bash
git clone https://github.com/melloa-project/melloa.git
git clone https://github.com/melloa-project/melloa-guardian.git
cd melloa
make preview
```

The first run installs only locked dependencies, verifies and builds the independent Guardian, builds the production Owner Console, creates a private temporary credential, and starts the core and same-origin console.

When both services are ready, the terminal prints:

- the exact Owner Console URL;
- a one-run owner credential;
- the first action to take;
- the network, Guardian, model-disclosure, and persistence contract;
- what `Ctrl-C` will stop and remove.

Keep that terminal open. Do not browse directly to core port `8000`; use the Owner Console URL on port `8787` so browser and API traffic remain same-origin.

If `uv` reports `UnknownIssuer` on a managed network and your organization CA is already trusted by the operating system, retry with:

```bash
UV_SYSTEM_CERTS=true make preview
```

Do not disable TLS verification. An unexpected issuer is a reason to inspect the network trust path.

## Reach first value

1. Open the printed Owner Console URL.
2. Paste the printed value into **Owner credential** and choose **Open Owner Console**.
3. Choose **New conversation**, give it a title, and create it.
4. Choose **Fill a no-network tour message**. The action fills the composer but does not send anything automatically.
5. Review the text and choose **Send message**.

The response must be labelled **Guided tour fixture** and **Fixed fixture · no network**. It explicitly says that the fixed response did not interpret the message and does not represent Melli thinking. That honesty is part of the product contract: the tour proves canonical conversation, policy, provenance, and inspection without pretending a deterministic fixture is useful intelligence.

## Talk to Melli on this device

Install Ollama using its upstream instructions, then pull the reviewed model:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

The dated instruct tag avoids moving-alias drift and is suited to bounded structured conversation output.

Start the same product journey with the explicit model selector:

```bash
make preview PREVIEW_MODEL=ollama
```

The launcher queries Ollama's loopback OpenAI-compatible `/v1/models` endpoint and requires the exact `qwen3:4b-instruct-2507-q4_K_M` model ID. If Ollama is stopped or the model is absent, startup fails with the exact `ollama serve` or `ollama pull qwen3:4b-instruct-2507-q4_K_M` recovery command. It never treats an empty model list as healthy.

When startup succeeds, the terminal contract says that owner text and selected memory evidence are sent to the named model on this device, that no external-provider disclosure occurs, and that Melloa remains process-local and disposable. In the console, choose one of the **Eligible model required** starters, edit it, and send it. A successful reply is labelled **Melli**; **Why this response?** must show route `model.local.ollama-qwen`, provider `provider.ollama-local`, model `qwen3:4b-instruct-2507-q4_K_M`, location **Device**, and no external disclosure.

The deterministic route remains available only as a visibly labelled fallback. If Qwen's endpoint fails, times out, exceeds the response-size limit, or returns a completion that cannot decode to the required JSON object, the reply says **Guided tour fixture** rather than silently presenting fixture text as Melli. A decoded object that violates citation or evidence rules can instead be retried or leave an inspectably dead reply. Inspect **Route attempts** and the reply state for the redacted outcome.

## Understand why it happened

Choose **Why this response?** on the reply. The inspector shows:

- route, provider, and model identity;
- processing location and external-disclosure state;
- selected evidence and durable identifiers;
- decision and policy records;
- every attempted route;
- latency and available token/cost data.

Then open:

- **Providers** to see why the deterministic route is a fixture and which real routes would be eligible;
- **Timeline** for bounded content-free conversation, processing, model, delivery, and export evidence;
- **Activity** for the model-run ledger;
- **Operations** for the exact persistence, queue, retention, backup, and export state.

## Exercise owner control

Open **Settings → Owner session** to inspect the current authenticated session and the controls for other sessions.

Open **Operations → Export**, inspect the coverage and limitations, then choose **Download current ZIP**. Melloa builds and validates the package before delivery and removes its temporary server-side archive after the response. The downloaded ZIP is a portability package, not a backup or restore claim.

To validate an unpacked export from the repository terminal:

```bash
uv run melloa import-validate --bundle-dir <unzipped-export-directory>
```

## Stop and recover

Press `Ctrl-C` in the terminal running `make preview`. The launcher:

1. stops the Owner Console;
2. stops the core;
3. removes the temporary Guardian material, owner credential, logs, and process-local state;
4. confirms cleanup in the terminal.

If startup fails, the launcher stops anything it already started, removes disposable state, and reports the failing component with the relevant log tail.

Common recovery paths:

| Symptom | What to do |
|---|---|
| Guardian checkout not found | Clone `melloa-guardian` beside `melloa`, then rerun `make preview`. |
| Go, Node.js, Python, or uv is missing | Install the documented version and rerun the same command. |
| Port `8000` or `8787` is occupied | Stop the local process using that port, then rerun the command. |
| Console says the private core is unavailable | Return to the launcher terminal; it reports a stopped or unhealthy child and cleans up. |
| Guardian status is rejected | Stop. Rebuild the sibling Guardian checkout and start a fresh preview; never edit signed JSON. |
| `PREVIEW_MODEL=ollama` cannot reach the endpoint | Start Ollama with `ollama serve`, then rerun the same preview command. |
| Ollama does not list `qwen3:4b-instruct-2507-q4_K_M` | Run `ollama pull qwen3:4b-instruct-2507-q4_K_M`, then rerun the same preview command. |
| Browser mutation controls are locked | Re-enter the owner credential through **Unlock changes**; the CSRF proof exists only in page memory. |

### Prove durable recovery before keeping owner state

The first-run preview is intentionally disposable. PostgreSQL is the one canonical durable store when you move beyond the tour. Before keeping long-lived owner state, run the synthetic clean-restore proof:

```bash
make recovery
```

This Docker-backed gate creates a complete PostgreSQL owner journey, encrypts a logical snapshot with restic, restores it into a clean database, and verifies the restored conversation, explanation evidence, memory state, session/audit state, and read-only boundary through the authenticated owner API. It uses no personal data and does not turn the downloaded owner ZIP into a backup. Follow [Durable owner-state recovery](operations/m0-recovery.md) for the exact contract and the additional scheduling/key-custody work required by a real installation.

## Add real capability one boundary at a time

Once this path is familiar, use [Configure advanced local routes and durable state](run-current-mvp.md) to add one reviewed boundary at a time. The on-device Ollama route above is the canonical first addition; the advanced runbook exposes its individual process commands.

1. a local Ollama/Qwen model route;
2. PostgreSQL owner-state durability and the clean-restore proof;
3. an isolated, explicitly disclosed Codex CLI route;
4. the optional Telegram adapter.

After each addition, repeat the conversation and inspection loop and verify the new route, disclosure, authority, persistence, and failure behavior before combining integrations.
