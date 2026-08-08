---
id: SPEC-BUG-164-001
priority: 1
layer: 1
type: bugfix
status: done
after: [SPEC-BUG-164]
nfrs: [SPEC-NFR-001]
technologies: [go]
created: 2026-08-08
---

# Per-tool managed-child response timeouts

## Problem

Shipyard waits a global 30 seconds for every child response. `lmac-run`'s
`mole_clean` needs up to 81 seconds, but increasing the global deadline would
make unrelated tool failures slower to detect.

## Requirements

- [x] R1: Extend a server's `tools.<tool-name>` config with an optional
  `response_timeout_seconds` integer.
- [x] R2: When dispatching `tools/call`, parse the requested tool name and use
  that tool's configured positive timeout for that request only.
- [x] R3: All unconfigured tools, malformed names, non-tool RPC methods, and
  non-positive values retain the 30-second default.
- [x] R4: Timeout selection remains race-safe under concurrent requests.

## Acceptance Criteria

- [x] AC-1: A configured tool receives its configured deadline while another
  tool on the same server retains 30 seconds.
- [x] AC-2: Invalid or absent per-tool timeout values retain 30 seconds.
- [x] AC-3: The timeout error names the effective duration.
- [x] AC-4: `go vet ./...`, `go build ./...`, and the focused race suite pass.
  The full test and full race commands retain the independently reproduced
  baseline failure in `cmd/shipyard/TestMain_ConfigMissingCommand`; the run
  report records the evidence and this spec introduced no additional failure.

## Context

- `cmd/shipyard/main.go` parses `ServerConfig` and its nested `ToolConfig`.
- `internal/proxy/manager.go` owns request dispatch and the current global
  `requestTimeout`.
- Tool name is supplied in the JSON-RPC params for `tools/call`; do not infer
  timeout from the child server name.

## Out of Scope

- Setting a timeout for `mole_clean` (SPEC-BUG-165-001).
- Changing Bridge HTTP client timeouts (SPEC-BUG-164).
- Retries or timeout changes for arbitrary JSON-RPC methods.

## Unblocked

On 2026-08-08, Serena successfully started `gopls` after the environment
repair and initialized the Shipyard workspace. Resume the preserved isolated
kickoff worktree with the normal evidence gate.
