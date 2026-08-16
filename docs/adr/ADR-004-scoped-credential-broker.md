# ADR-004: Broker scoped credentials; use SOPS and OS key storage for bootstrap

- **Status:** Accepted for V1
- **Date:** 2026-08-15

## Context

Melloa may eventually access deeply sensitive APIs. Giving an autonomous process a giant `.env` creates one catastrophic compromise domain. Running Vault/OpenBao on day one adds another critical availability and recovery service.

## Decision

Store bootstrap/deployment secrets encrypted with SOPS and age, with private identities in the owner-controlled OS/offline recovery path. A capability broker unwraps, mints, or supplies narrowly scoped credentials only after deterministic authorization. Adapters receive action-bound leases or handles, not the entire secret inventory. Use separate provider-side scopes, environments, budgets, and rotation.

## Alternatives considered

- Plain `.env`: easy but ambient, leak-prone, and overbroad.
- Cloud-only secret manager: ties local recovery to cloud/IAM and may expose a control plane.
- OpenBao/Vault immediately: powerful dynamic credentials, excessive operational burden before multi-node/dynamic need.

## Consequences

- Credential issuance/access is auditable.
- Some APIs with coarse tokens still create residual authority; network/budget controls compensate.
- Recovery-key custody and rotation runbooks become critical.
- Broker failure stops side effects rather than bypassing policy.

## Revisit when

Multiple hosts/workloads require identity-based dynamic secrets, rotation frequency becomes unmanageable, or short-lived credentials are broadly available. Introduce OpenBao/workload identity behind the existing broker interface.
