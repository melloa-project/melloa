# Persistent server runtime (engineering checkpoint)

This is the generic Linux container runtime intended to become Melloa's low-maintenance server
path. It is **not yet an owner deployment instruction** and does not change the repository's
`NOT READY` status. Automatic encrypted backup, release rollback, self-change policy, and real
deployed dogfooding are still required.

The runtime has three processes:

- PostgreSQL is reachable only on a private, internal container network;
- a one-shot migration container must finish before Melloa starts;
- Melloa exposes no host port and uses outbound Telegram long polling as the normal interface.

The Melloa process runs as the dedicated numeric UID/GID selected in the path-only environment
file (the template uses `10001:10001`), with a read-only root filesystem, no Linux
capabilities, bounded logs, and restart-on-failure/reboot behavior. A PostgreSQL connection loss
causes the process to request a supervised restart instead of remaining silently wedged.

## Private deployment inputs

Copy `server.env.example` outside the source checkout and replace only its paths, image tag,
commit, and private subnet. The environment file contains paths, never values. Every credential
and owner-specific JSON document is supplied as a separate regular file. Credential files read by
Melloa must be owned by that dedicated UID/GID and mode `0600`; private directories should be mode
`0700`.

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

That check builds the pinned runtime image, initializes least-privilege database logins, applies
all migrations, waits for health, restarts PostgreSQL, and proves the Melloa process restarts and
returns healthy. It is infrastructure evidence only—not real Telegram/provider dogfooding.
The existing `MELLOA_POSTGRES_IMAGE` override may name a locally cached copy of the exact pinned
database image when a registry is unavailable.
