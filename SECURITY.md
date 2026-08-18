# Security policy

Melloa handles personal data and model-proposed actions. Do not report suspected vulnerabilities, leaked credentials, personal data, host inventories, or exploit details in a public issue.

## Reporting

Use the repository's private GitHub security-advisory flow. Include the affected revision, boundary, prerequisites, impact, and a minimal synthetic reproduction. If private reporting is unavailable, contact the repository owner through an already verified private channel before sharing details.

Never include real owner messages, camera media, API keys, Guardian material, deployment values, or database exports in a report.

## Supported versions

`v0.2.0` is the evaluated owner-facing preview snapshot. The latest green `main` revision is also evaluated during ongoing development; neither surface carries a maintenance window or production-support promise. Architecture documents are not a claim that unimplemented or deployment-owned components are production-ready.

## Security boundaries

- Model output and external content are untrusted data.
- Deterministic policy authorizes exact actions.
- The main runtime has no Guardian mutation or signing authority.
- Public application ingress is unsupported in V1.
- Generated code, real credentials, and personal data are absent from synthetic development fixtures.
