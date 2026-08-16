# ADR-008: Separate an owner-controlled Guardian from the autonomous plane

- **Status:** Accepted and non-negotiable for V1
- **Date:** 2026-08-15

## Context

An autonomous system must not hold the privileges needed to disable its own shutdown, expand its governance, erase audit, or preserve its credentials against the owner. A prompt instruction to “obey the kill switch” is not a security boundary.

## Decision

Run a minimal root-owned Guardian outside rootless Melloa containers. It owns signed/read-only operating modes, service stop/start, host egress rules, credential removal/revocation, and recovery entry. Owner authentication/recovery credentials are separate. Melli can observe mode and request changes but cannot modify Guardian code, configuration, repository, credentials, or state.

## Alternatives considered

- In-process kill switch: compromised process can bypass it.
- Container orchestrator permissions granted to Melli: broad privilege escalation.
- Cloud-only emergency control: unavailable during account/network compromise.
- Physical power switch only: useful last resort but too coarse for read-only/offline recovery.

## Consequences

- Guardian code and operations must remain small and independently reviewed.
- The owner needs a local/private authenticated path and recovery-key custody.
- Some incidents still require physical network/power isolation.
- Guardian availability can block actions; fail closed is intentional.

## Revisit when

Multiple sites/nodes require a distributed owner control plane. Preserve the invariant that autonomous credentials cannot remove ultimate owner authority.
