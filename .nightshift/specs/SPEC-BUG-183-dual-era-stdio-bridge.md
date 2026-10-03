---
id: SPEC-BUG-183
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
---

# Make the Shipyard stdio bridge dual-era

> Former ID: SPEC-BUG-174 (renumbered by SPEC-BUG-179 on 2026-10-03 to remove a duplicate ID).

## Problem

`cmd/shipyard-mcp/main.go` only handles legacy initialize/list/call, discards notifications, omits modern result/cache fields, and emits list-changed independent of negotiated capabilities.

## Requirements

- [ ] Implement `server/discover`, modern per-request validation/errors, result envelopes and deterministic/cacheable catalogs.
- [ ] Retain legacy initialize behavior as a distinct era and never mix era-specific notifications.
- [ ] Implement modern cancellation and subscription-scoped change delivery; keep legacy `tools/list_changed` only when negotiated.
- [ ] Preserve namespacing, policy filtering, raw capture and current bridge process isolation.

## Acceptance Criteria

- [ ] AC1: Official modern and legacy clients discover/list/call the same bridge process and receive era-correct wire shapes.
- [ ] AC2: Modern calls work without initialize; invalid metadata/version returns spec errors.
- [ ] AC3: Catalog changes notify only subscribed/capable clients; pre-negotiation output is impossible.
- [ ] AC4: Current Claude/Codex bridge smoke and race/conformance suites pass.

## Out of Scope

- HTTP transport and child implementation updates.


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
