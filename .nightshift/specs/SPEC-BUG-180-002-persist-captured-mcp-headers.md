---
id: SPEC-BUG-180-002
template_version: 12
priority: 2
layer: 1
type: refactor
status: draft
parent: SPEC-BUG-180
after:
- SPEC-BUG-181
nfrs:
- SPEC-NFR-001
prior_attempts: []
attachments: []
created: 2026-10-03
---

# Persist captured MCP headers alongside payload bytes

## Problem

`mcpcore.Envelope` keeps raw headers, but `capture.Store` persists only payload bytes. The 2026-07-28 era routes on `Mcp-Method`, `Mcp-Name` and `Mcp-Protocol-Version`, so traffic inspection loses routing evidence.

## Requirements

- [ ] R1: `capture.Store` persists each captured request/response's headers alongside its payload bytes, byte-identically, with a migration for existing stores.

## Acceptance Criteria

- [ ] AC1 (R1): A captured pair read back from the store returns the same headers (names, values, multi-value order) that `mcpcore.Envelope` received.
- [ ] AC2: `go test -race -count=1 ./...` and `go vet ./...` pass.

## Context

- Origin: SPEC-BUG-181 run report (2026-10-03), § Suggested Follow-up Specs.
- Store: `internal/capture/store.go`; envelope: `internal/mcpcore/envelope.go`.

## Out of Scope

- Dashboard UI changes to display headers.

## State rationale

```yaml
schema_version: 1
status: draft
reason: Suggested as a follow-up by the SPEC-BUG-181 run on 2026-10-03; not yet reviewed for promotion.
reconsider_when: SPEC-BUG-181 is merged to main and the capture-schema migration approach is reviewed.
evidence: []
provenance: authored
record: artifacts/20261003T173547Z-decision-state-rationale-authored-draft-suggested.json
```
