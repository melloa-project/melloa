# ADR-006: Treat documentation as infrastructure using MkDocs, Mermaid, and ADRs

- **Status:** Accepted for V1
- **Date:** 2026-08-15

## Context

A seven-year personal system will fail through forgotten rationale and tribal knowledge as readily as through code defects. Diagrams and operational knowledge must remain reviewable with source changes.

## Decision

Keep Markdown documentation in the monorepo, publish/build with MkDocs Material, draw architecture in Mermaid, and record significant choices as immutable/supersedable ADRs. PR gates require documentation for schema, trust, policy, data-flow, operation, and user-interface changes.

## Alternatives considered

- Wiki/Notion only: easy editing but weak version/PR coupling and export durability.
- Docusaurus: strong site platform, heavier JavaScript stack than needed.
- Sphinx: excellent for Python/API docs, less direct fit for broad architecture/operator prose.
- Image-only diagrams: hard to diff and become stale.

## Consequences

- Documentation build/link/diagram checks become CI responsibilities.
- Canonical pages and ownership must prevent duplication.
- Sensitive personal deployment details stay outside public docs.

## Revisit when

Large multi-version API documentation or a product web experience justifies another frontend. Preserve Markdown and ADR data for migration.
