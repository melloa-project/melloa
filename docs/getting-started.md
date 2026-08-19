# Run the current baseline

This guide starts the product that existed when the owner-experience reset began. It is useful for
inspecting and simplifying the current behavior. It is not evidence that Melli is already valuable.

## Requirements

- Linux or macOS with Bash
- Python 3.13+ and uv 0.12.0
- Node.js 22+
- Go 1.24+
- `melloa` and `melloa-guardian` checked out as sibling directories

Docker, PostgreSQL, API keys, Telegram, and personal data are not required for the disposable path.

## Start safely

From the Melloa checkout:

```bash
make preview
```

The launcher builds Guardian independently, creates temporary credentials, starts the core and web
interface on loopback, and prints the exact URL and owner credential. Keep the terminal open and use
the web URL on port `8787`; port `8000` is the private core API.

Without a model configuration, the interface is available for inspecting the owner boundary and
data controls, but conversation is unavailable. The preview does not manufacture a fallback answer.

Press `Ctrl-C` to stop both services and remove the disposable state.

## Talk through the on-device model

To exercise real model behavior in this baseline:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
make preview PREVIEW_MODEL=ollama
```

The launcher requires that exact local model and fails with a corrective message if Ollama is
unavailable. Owner text and selected context go only to this configured model on the device; they
are not disclosed to an external provider.

This model is a technical baseline, not a recommended quality ceiling or the target daily-use path.

## Current limitations

- all state is removed when the disposable preview stops;
- conversation is unavailable until an explicit model configuration passes preflight;
- the interface exposes too much provider, audit, operations, and memory-record detail;
- continuity, autonomous memory formation, goals, reflection, outcome learning, and calibrated
  initiative are not yet compelling owner experiences;
- the preview's screens and contracts may be removed during the reset.

Do not put real long-lived owner data into this disposable baseline.

## Durable-state safety check

PostgreSQL is still the tested recovery authority for the existing durable implementation. Before a
change touches recovery-critical state, run:

```bash
make recovery
```

See [recovery](recovery.md) for what that test does and does not prove.
