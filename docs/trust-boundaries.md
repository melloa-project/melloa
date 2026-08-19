# Trust boundaries

This document contains the small set of constraints that should survive implementation rewrites.
It protects owner authority without granting immunity to the current architecture.

## Identity and continuity

- Melloa is the system. Melli is one persistent intelligence with a long-lived relationship to the
  owner; she is not a model, provider, prompt, worker, container, or client.
- Durable owner context must remain usable when a model or provider is replaced.
- Generated or retrieved content is evidence, not authority. A model result is untrusted until the
  application validates and contextualizes it.

## Independent owner control

Guardian is a separate, owner-controlled security boundary. Melloa and Melli may read a constrained,
signed status but may not:

- write Guardian state or configuration;
- possess its signing, root, recovery, or deployment credentials;
- deploy, disable, replace, or reconfigure Guardian;
- obtain ambient host, firewall, container-control, or credential-revocation authority;
- make ordinary application availability a prerequisite for emergency owner control.

Guardian should remain small, deterministic, independently reviewable, and useful when Melloa, its
database, its models, or its web interface are unavailable. The separate repository is the authority
for its concrete protocol and operations. Melloa's current read-only status contract lives in
[guardian-protocol.md](contracts/guardian-protocol.md).

## Actions and external effects

- Models may suggest actions; deterministic code authorizes and constrains effects.
- Authorization considers the exact action, destination, data, purpose, risk, reversibility, time,
  rate, and budget. Prompt text never grants permission.
- Untrusted web pages, messages, documents, tool output, or model output cannot modify policy or
  approve an action.
- High-risk, destructive, privileged, public, financial, legal, or otherwise hard-to-reverse actions
  require explicit narrow authority and, where appropriate, recent exact owner approval.
- If policy, credentials, or Guardian state cannot be verified, effects fail closed. Intelligence may
  degrade without bypassing authority.

This does not require a generic capability framework, provider dashboard, or permanent policy page.
A smaller concrete implementation is preferred until real actions justify more machinery.

## Owner data

- Private-by-default, single-owner deployment is the baseline. Application authentication remains
  required even on a private network.
- Secrets, recovery material, personal deployment values, and private owner data never belong in the
  source repository, prompts, general logs, or test fixtures.
- External transmission of personal or sensitive data is purpose-limited, explicit, and inspectable.
  A fallback must not silently broaden disclosure or cost.
- The owner can export canonical data in a documented, provider-independent form and can correct or
  delete personal content within honestly stated audit and backup limits.
- Backups and recovery-critical state are encrypted under owner-controlled keys kept separately from
  the application.

These rules protect owner control; they do not require the owner to operate memory records, audit
tables, provider routes, or retention jobs during ordinary use.

## Provenance and inspection

Preserve enough structured provenance to answer consequential questions:

- Why does Melli believe this and how confident is it?
- What owner correction or source changed it?
- What private data left the trust boundary, to whom, and why?
- What action occurred, under which authority, and with what outcome?

Do not expose hidden chain-of-thought. Do not retain exhaustive metadata merely because it can be
recorded. Inspection is contextual and progressively disclosed when it can change an owner decision.

## Simplification rule

No current service, schema, port, adapter, page, process, deployment choice, or test is itself a trust
boundary. Before preserving implementation complexity, identify the concrete unsafe failure that its
removal would create during near-term dogfooding. If the same invariant can be enforced more directly,
replace the implementation.
