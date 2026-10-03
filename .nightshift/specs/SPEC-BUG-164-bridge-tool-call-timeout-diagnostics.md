---
id: SPEC-BUG-164
priority: 1
layer: 1
type: bugfix
status: done
after:
- SPEC-BUG-126
nfrs:
- SPEC-NFR-001
technologies:
- go
created: 2026-07-24
---

# Bridge tool-call timeout diagnostics

## Problem

The stdio Shipyard bridge gives every HTTP request a two-second client timeout.
Slow, valid child-tool calls (such as YouTube transcript retrieval) can therefore
time out while the gateway remains healthy. The bridge reports this timeout as
"Shipyard is not running or unreachable," conflating a reachable but slow call
with an unavailable gateway.

## Requirements

- [x] R1: Gateway metadata reads retain a short timeout.
- [x] R2: `POST /api/tools/call` has a separately scoped timeout suitable for
  normal managed-tool execution without affecting metadata reads.
- [x] R3: A tool-call timeout identifies the tool-call timeout rather than
  claiming that Shipyard is unreachable.
- [x] R4: A refused/unreachable gateway still reports the existing availability
  failure clearly.

## Acceptance Criteria

- [x] AC-1: A delayed `POST /api/tools/call` that exceeds the metadata timeout
  but is inside the tool-call timeout returns its normal tool result.
- [x] AC-2: A delayed `POST /api/tools/call` that exceeds the tool-call timeout
  returns a timeout-specific MCP error.
- [x] AC-3: An unreachable gateway continues to produce an availability error.
- [x] AC-4: `go test ./...`, `go vet ./...`, and `go build ./...` pass.
- [x] AC-5: `go test -race -count=1 ./...` reports no data races.

## Context

- Bridge entry point: `cmd/shipyard-mcp/main.go`
- Bridge tests: `cmd/shipyard-mcp/main_test.go`
- The live `lmac-run__yt_dlp` metadata and transcript calls passed on 2026-07-24.
- `DevKB/go.md` Entry 6 documents the known two-second timeout and misleading
  error condition.

## Out of Scope

- Changing child-server timeouts or yt-dlp behavior.
- Retrying tool calls automatically.
- Restarting the healthy Shipyard service.

## State rationale

```yaml
schema_version: 1
status: done
reason: Implemented and verified 2026-07-24. The bridge uses a 2s metadata client and a 5-minute tools/call client (cmd/shipyard-mcp/main.go lines 44-45), covered by TestInvokeTool_UsesLongerToolCallTimeoutThanMetadata and TestInvokeTool_ReportsToolCallTimeout. The spec file was never committed until 2026-10-03.
reconsider_when: null
evidence: []
provenance: authored
record: artifacts/20261003T155149Z-decision-state-rationale-authored-done-implemente.json
```
