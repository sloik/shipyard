---
id: SPEC-BUG-184
template_version: 7
priority: 1
layer: 1
type: refactor
status: draft
parent: SPEC-BUG-180
after:
- SPEC-BUG-181
- SPEC-BUG-182
nfrs:
- SPEC-NFR-001
created: 2026-08-12
stack: go
devkb_required:
- go.md
- architecture.md
- testing.md
- security.md
---

# Make Shipyard `/mcp` stateless Streamable HTTP

> Former ID: SPEC-BUG-175 (renumbered by SPEC-BUG-179 on 2026-10-03 to remove a duplicate ID).

## Problem

The POST endpoint advertises legacy MCP, the authenticated path mints an unvalidated `Mcp-Session-Id`, required modern headers/body metadata and Origin are not checked, and the service binds all interfaces by default.

## Requirements

- [ ] Implement modern POST-only Streamable HTTP: discovery, per-request metadata/routing headers, JSON or request-scoped SSE, status/error rules and cancellation by stream close.
- [ ] Never mint/require/echo modern session IDs; ignore legacy session/replay headers on modern requests.
- [ ] Validate Origin, bind loopback by default, and require explicit configuration/auth for remote exposure.
- [ ] Preserve a clearly separated legacy path/era only if needed by verified clients.

## Acceptance Criteria

- [ ] AC1: Modern conformance passes for headers, body `_meta`, notification 202, errors, result/cache fields and GET/DELETE 405.
- [ ] AC2: Missing/mismatched routing headers are 400 `HeaderMismatch`; unsupported version advertises supported revisions.
- [ ] AC3: Invalid Origin is 403, default listener is 127.0.0.1, and auth tests cover audience/token behavior without `Mcp-Session-Id`.
- [ ] AC4: Authenticated and unauthenticated policy configurations remain captured and race-free.

## Out of Scope

- Legacy HTTP+SSE GET endpoints or stream replay.


## State rationale

```yaml
schema_version: 1
status: draft
reason: Drafted 2026-08-12 as a child of the MCP 2026 migration plan (SPEC-BUG-180); not yet reviewed for promotion.
reconsider_when: SPEC-BUG-180 is promoted and every spec this one depends on is done, or the plan is replanned.
evidence: []
provenance: authored
record: artifacts/20261003T153224Z-decision-state-rationale-authored-draft-drafted-2.json
```
