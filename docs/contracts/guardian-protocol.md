# Guardian read-only protocol

## Authority

The protocol is defined in the main repository so the runtime can consume a stable contract. Signing, transitions, audit journal, owner authentication, host control, and deployment remain in the separately protected `melloa-guardian` repository.

Melloa has one port:

```text
GuardianStatusReader.read_status() -> cryptographically verified status
```

There is deliberately no `set_mode`, `transition`, `stop`, firewall, credential-revocation, or generic command method.

## Version 1 envelope

The independently owned Guardian repository defines the signed Ed25519 envelope. Melloa accepts
only a verified payload containing:

- protocol version;
- stable Guardian installation ID;
- exact mode;
- monotonic positive sequence;
- UTC transition time;
- qualified reason code;
- previous receipt hash after genesis.

The signing and receipt-hash domain separators are documented in the Guardian repository. The main adapter verifies the signature over the original payload bytes before parsing the payload. It does not reserialize untrusted JSON and then claim that the result was signed.

## Modes

| Mode | Runtime interpretation |
|---|---|
| `normal` | policy-bounded actions may be evaluated |
| `no-actions` | side effects denied; ingestion and reasoning may continue |
| `read-only` | mutations and side effects denied; inspection remains |
| `offline` | external destinations denied |
| `stopped` | normal readiness denied |
| `recovery` | normal readiness denied; owner recovery path only |

A status sequence mismatch denies the request. An invalid signature or unreadable file produces no fallback mode and no action authority.

## File contract

The deployment mounts only the signed status projection and public key into the autonomous plane, read-only. The adapter rejects symlinks, non-regular files, oversized documents, wrong key types, malformed envelopes, unsupported versions, invalid signatures, and invalid payloads.

The private signing key, receipt journal, lock, CLI, repository credentials, systemd controls, firewall controls, and recovery material are outside the mount and outside Melloa's credentials.

## Observation continuity

After its first successful read, one `FileGuardianStatusReader` pins the exact public-key document,
Guardian installation ID, key ID, sequence, and receipt for the lifetime of that reader. It accepts
an exact repeated receipt. It rejects a lower sequence, a different receipt at the same sequence, an
identity or key change, and a directly consecutive receipt whose predecessor is not the last receipt
observed. A jump of more than one sequence remains valid because Melloa may legitimately miss
intermediate Guardian transitions. A rejected read does not replace the last good observation.

This is rollback and fork detection within one running reader, not a proof of freshness after a
restart. On a new process's first read, an older but validly signed projection is indistinguishable
from the current projection unless the deployment supplies a separately trusted persistent anchor.
This protocol version does not define such an anchor. Signature verification therefore proves
authenticity, while deployment controls and the process-lifetime checks provide the currently stated
freshness protection.
