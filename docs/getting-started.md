# Start Melloa locally

This is the shortest complete Melloa owner journey: start a private console, have a canonical conversation, inspect why the system responded, review owner-visible evidence, export your state, and stop cleanly.

The local run is deliberately safe and truthful. It binds only to loopback, uses disposable process-local state, keeps Guardian separately signed in `offline` mode, makes no external model call, and labels the guided response as a fixed fixture rather than Melli.

## What you need

- Linux or macOS with Bash;
- Python 3.13 or newer;
- [uv](https://docs.astral.sh/uv/) 0.12.0;
- Node.js 22 or newer;
- Go 1.24 or newer;
- the public Melloa and Guardian repositories as sibling directories.

Docker, PostgreSQL, API keys, model downloads, Telegram, cameras, and private deployment state are not required.

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
| Browser mutation controls are locked | Re-enter the owner credential through **Unlock changes**; the CSRF proof exists only in page memory. |

## Add real capability one boundary at a time

Once this path is familiar, use [Configure advanced local routes and durable state](run-current-mvp.md) to add one reviewed boundary at a time:

1. a local Ollama/Qwen model route;
2. PostgreSQL restart durability;
3. an isolated, explicitly disclosed Codex CLI route;
4. the optional Telegram adapter.

After each addition, repeat the conversation and inspection loop and verify the new route, disclosure, authority, persistence, and failure behavior before combining integrations.
