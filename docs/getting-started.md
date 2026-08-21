# Local disposable preview

This guide starts the loopback web preview on a development machine. Use it when you want to inspect
the current local interface or make code changes without touching a real server.

For first owner deployment, use [first-owner server deployment](server-deployment.md). That path
connects Telegram, configures hosted model routes, installs the persistent server runtime, and
exercises the bounded self-change loop.

## Requirements

- Linux or macOS with Bash
- Python 3.13+ and uv 0.12.0+
- Node.js 22+
- `melloa` and `melloa-guardian` checked out as sibling directories

The Melloa process does not need Go or the Guardian checkout. The owner uses Go 1.24+ in the
separate Guardian repository only to prepare this disposable public handoff.

Docker, PostgreSQL, API keys, Telegram, and personal data are not required for the disposable path.

## Prepare the Guardian handoff

Guardian owns preparation and cleanup. Starting from the Melloa checkout, enter the sibling
Guardian checkout, use its reviewed public preview-state operation, and export the two paths it
prints:

```bash
cd ../melloa-guardian
make preview-state
export GUARDIAN_STATUS="$PWD/state/local-preview/status.json"
export GUARDIAN_PUBLIC_KEY="$PWD/state/local-preview/public.pem"
```

See the Guardian repository's
[operations guide](https://github.com/melloa-project/melloa-guardian/blob/main/docs/OPERATIONS.md#public-handoff-for-the-disposable-melloa-preview)
for the receipts, non-overwrite behavior, public-only output, cleanup safeguards, and exact limits of
this static handoff. Melloa does not define or execute those operations.

## Start the disposable preview

In the same shell, move to the Melloa checkout and start the preview:

```bash
cd ../melloa
make preview
```

The launcher accepts only `GUARDIAN_STATUS` and `GUARDIAN_PUBLIC_KEY`. It verifies that projection
is signed and already `offline`, creates Melloa's temporary credential and logs, starts the core and
web interface on loopback, and prints the exact URL and owner credential. Keep the terminal open and
use the web URL on port `8787`; port `8000` is the private core API.

Without a model configuration, the interface is available for inspecting the owner boundary and data
controls. Conversation starts only when you explicitly configure a model for this disposable run.

Press `Ctrl-C` to stop both services and remove Melloa's disposable credential and logs. The
Guardian handoff remains untouched. Remove that public-only directory yourself when finished:

```bash
cd ../melloa-guardian
make preview-state-clean
```

## Optional disposable local model check

To exercise real model behavior in this baseline:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
make preview PREVIEW_MODEL=ollama
```

The launcher requires that exact local model and fails with a corrective message if Ollama is
unavailable. Owner text and selected context go only to this configured model on the device; they
are not disclosed to an external provider.

This model is only a local check. The first-owner server path is hosted-provider-first and does not
require local model hardware.

## Preview scope

The preview is intentionally temporary:

- Melloa's credential and logs are removed when the preview stops;
- the owner-supplied Guardian handoff remains owner-managed;
- Telegram, hosted model routes, the persistent server runtime, and self-change workers are not
  installed by this guide;
- the preview is for inspection and development, not long-lived owner history.

Do not put irreplaceable personal data into this disposable preview.

## Durable-state safety check

PostgreSQL is still the tested recovery authority for the existing durable implementation. Before a
change touches recovery-critical state, run:

```bash
make recovery
```

See [recovery](recovery.md) for what that test does and does not prove.
