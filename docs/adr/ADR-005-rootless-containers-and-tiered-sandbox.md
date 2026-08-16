# ADR-005: Use rootless containers and add stronger isolation only for hostile workloads

- **Status:** Accepted for V1
- **Date:** 2026-08-15

## Context

Core services need reproducible isolation. Future generated code must be treated as hostile. Kubernetes and microVM fleets are not justified before generated execution exists.

## Decision

Run normal services under rootless Docker Compose with non-root users, dropped capabilities, read-only filesystems where practical, separate networks/volumes, and no Docker socket. Generated code, when enabled, uses disposable rootless sandboxes with default-deny egress, no production data/secrets, hard quotas, and gVisor where compatible. Firecracker is a future stronger tier.

## Alternatives considered

- Host processes: fewer layers but weaker reproducibility/isolation.
- Rootful Docker with socket access: broad host-compromise path.
- Kubernetes: unnecessary control-plane burden for one host.
- Firecracker for everything: stronger isolation but substantial image/network/operations complexity.

## Consequences

- Rootless compatibility and filesystem/network constraints must be tested.
- Containers are not assumed to be a perfect security boundary.
- Generated-code features cannot launch until the stronger sandbox and policy path exist.

## Revisit when

Hostile workload frequency, multi-tenancy, regulatory needs, or kernel attack surface justifies microVMs/dedicated sandbox nodes.
