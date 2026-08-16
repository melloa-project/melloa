# ADR-012: Use private networking and no public application ingress in V1

- **Status:** Accepted for V1
- **Date:** 2026-08-15

## Context

A one-owner deployment needs remote access but not public discovery. Telegram long polling and outbound provider calls eliminate inbound internet requirements. A domain, reverse proxy, certificates, and webhook endpoint would enlarge attack and operating surface.

## Decision

Bind owner/admin services to LAN/private interfaces and use Tailscale as the convenient default, with WireGuard-compatible migration. Keep host firewall default-deny. Camera VLAN has no internet. Generated sandboxes have default-deny egress. No public domain, port forwarding, or public reverse proxy is required.

## Alternatives considered

- Public HTTPS domain: universally reachable but creates patching, auth, WAF/rate-limit, certificate, and incident burden.
- Cloud VM control plane: available remotely but moves authority/data and adds account/IAM dependency.
- LAN only: smallest exposure but weak remote usability and recovery.

## Consequences

- Owner access depends on private-network client/control availability, with LAN/console recovery.
- Application authentication remains required; network membership alone is insufficient.
- Future public integrations require a new threat review and ingress architecture.

## Revisit when

A specific capability cannot use outbound polling/private relay, or multiple users/sites need a carefully authenticated public endpoint.
