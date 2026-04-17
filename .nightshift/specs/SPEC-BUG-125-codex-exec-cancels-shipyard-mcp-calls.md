---
id: SPEC-BUG-125
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-019, SPEC-044]
violates: [SPEC-019, SPEC-044]
prior_attempts: []
created: 2026-04-17
completed: 2026-04-17
root_cause: |
  The failure was not caused by the Shipyard bridge transport or the Shipyard gateway.
  Raw stdio JSON-RPC calls against ShipyardBridge succeeded, interactive Codex sessions
  succeeded, and fresh `codex exec --ephemeral --json` began succeeding as soon as the
  exact Shipyard-exposed tools used in the run had explicit
  `mcp_servers.shipyard.tools.<tool>.approval_mode = "approve"` entries in
  `~/.codex/config.toml`.

  A server-wide Shipyard approval setting was insufficient for the failing path.
  Codex `exec` needed per-tool approval configuration for the namespaced tools it was
  asked to call (`shipyard__status`, `lmstudio__lms_status`, etc.). Once those entries
  were present, the same fresh non-interactive `codex exec` flows succeeded without any
  Shipyard bridge code changes.
---

# Fresh `codex exec` Sessions Cancel Shipyard MCP Tool Calls

## Problem

Shipyard's MCP bridge works in an interactive Codex session, but a fresh non-interactive
`codex exec --ephemeral` process sees the `shipyard` MCP registration and then fails at the
actual tool-call step with `user cancelled MCP tool call`. This blocks the remaining
"Codex CLI end-to-end" verification path and means Shipyard cannot currently be treated as
working from Codex's non-interactive execution mode.

**Violated spec:** SPEC-019 (Shipyard MCP Bridge for External Clients)  
**Violated criteria:** AC 3 — a namespaced tool call such as `lmstudio__...` is routed to the
correct Shipyard-managed server and returns the child MCP result. AC 9 — documentation shows
how to register the new bridge in Claude CLI and Codex using one MCP entry.

**Violated spec:** SPEC-044 (Shipyard Self-Server — Expose Shipyard as a First-Class Server)  
**Violated criteria:** AC 4 — `tools/call` / MCP invocation of `shipyard__status` returns a
successful result with child server summary.

## Reproduction

Initial state:
- Shipyard desktop/app backend is running on `http://127.0.0.1:9417`
- `mcp__shipyard__shipyard_status` works in an already-open interactive Codex session
- `codex mcp list` shows `shipyard` enabled from `~/.codex/config.toml`

Steps:
1. Verify Codex has the Shipyard bridge configured:
   `codex mcp list`
2. Run a fresh non-interactive Codex process:
   `codex exec --skip-git-repo-check --ephemeral --json -C /tmp/some-dir -s workspace-write "Use the available MCP tools to call the Shipyard status tool exactly once and then stop. Report the result in one sentence."`
3. Watch the JSONL stream for the MCP tool call.
4. **Actual:** the process starts an MCP tool call against server `shipyard`, tool
   `shipyard_status`, then completes it with:
   `error.message = "user cancelled MCP tool call"`
5. Repeat with a prompt that calls the LM Studio tool exposed through Shipyard.
6. **Actual:** the same fresh `codex exec` path cancels the MCP call instead of returning a
   live result from Shipyard / LM Studio.
7. **Expected:** a fresh `codex exec` process can call Shipyard bridge tools successfully and
   receive the actual status payload, just like the interactive Codex session.

Observed evidence from 2026-04-17:
- `codex mcp list` showed `shipyard` enabled with command
  `/Users/ed/Dropbox/Developer/Repos/shipyard/.shipyard-dev/bin/ShipyardBridge`
- Interactive session call worked: `mcp__shipyard__shipyard_status`
- Direct raw stdio smoke test against `./.shipyard-dev/bin/ShipyardBridge --api-base http://127.0.0.1:9417`
  succeeded for `initialize`, `tools/list`, and `tools/call` with `shipyard__status`
- Fresh `codex exec --json` emitted:
  `{"type":"item.completed","item":{"type":"mcp_tool_call","server":"shipyard","tool":"shipyard_status","error":{"message":"user cancelled MCP tool call"},"status":"failed"}}`

## Root Cause

The failing path was a Codex client approval/configuration assumption, not a broken
Shipyard MCP bridge.

Evidence gathered on 2026-04-17:

- Direct stdio smoke test against `ShipyardBridge` succeeded for `initialize`,
  `tools/list`, and `tools/call`
- Interactive Codex could already call `mcp__shipyard__shipyard_status`
- Fresh `codex exec --ephemeral --json` runs now succeed for both:
  - `shipyard__status`
  - `lmstudio__lms_status`
- The stable difference is the presence of explicit per-tool approval entries in
  `~/.codex/config.toml` under `mcp_servers.shipyard.tools.<tool>.approval_mode = "approve"`

That means the required repo-side fix is documentation plus a reproducible verification
script for the working Codex path, not a change to `cmd/shipyard-mcp`.

## Requirements

- [x] R1: A fresh `codex exec` process must be able to call `shipyard_status` through the
  configured Shipyard bridge and receive a normal result instead of `user cancelled MCP tool call`
- [x] R2: The same fresh `codex exec` path must be able to call a child MCP tool exposed through
  Shipyard (for example LM Studio status) and receive the child result
- [x] R3: The fix must identify whether the failure is caused by Shipyard bridge behavior,
  Shipyard gateway responses, or a Codex compatibility assumption in the bridge/docs, and encode
  that understanding in tests or docs rather than relying on manual knowledge
- [x] R4: The documented Codex registration / verification flow in this repo must match the
  behavior that actually works after the fix

## Acceptance Criteria

- [x] AC 1: Running a fresh `codex exec --ephemeral --json ...` process that calls the Shipyard
  status tool completes with a successful MCP tool result, not `user cancelled MCP tool call`
- [x] AC 2: Running a fresh `codex exec --ephemeral --json ...` process that calls a child tool
  exposed through Shipyard completes with a successful MCP tool result
- [x] AC 3: AC 3 and AC 9 from SPEC-019 now pass for the documented Codex path
- [x] AC 4: AC 4 from SPEC-044 now passes for the Codex path that calls Shipyard status
- [x] AC 5: The repo contains an automated regression test, smoke test, or documented reproducible
  verification script that covers the failing `codex exec` path explicitly
- [x] AC 6: No regressions — existing Shipyard bridge tests still pass, including `go test ./...`
  and `go build ./...`

## Context

- Existing bridge implementation:
  - `cmd/shipyard-mcp/main.go`
- Parent specs:
  - `.nightshift/specs/SPEC-019-shipyard-mcp-bridge.md`
  - `.nightshift/specs/SPEC-044-shipyard-self-server.md`
- Existing docs:
  - `README.md`
  - `.argo/README.md`
- Verification script:
  - `.shipyard-dev/verify-spec-125.sh`
- Relevant local evidence gathered on 2026-04-17:
  - `codex mcp list` showed the bridge enabled from `~/.codex/config.toml`
  - Interactive Codex session could call `mcp__shipyard__shipyard_status`
  - Direct JSON-RPC stdio calls to `ShipyardBridge` returned valid results outside Codex
  - Fresh `codex exec --json` process failed the actual MCP call with `user cancelled MCP tool call`
- Useful external/local context for investigation:
  - `~/.codex/config.toml`
  - `~/.codex/log/codex-tui.log`

## Out of Scope

- Adding new Shipyard management tools
- Reworking the MCP naming scheme
- Broad Codex feature work unrelated to the Shipyard bridge compatibility path
- Claude Desktop / Claude Code bridge setup changes unless they are needed for parity docs

## Code Pointers

- Bridge entry point: `cmd/shipyard-mcp/main.go`
- Bridge tests: `cmd/shipyard-mcp/main_test.go`
- Gateway/server behavior: `internal/web/server.go`
- Parent bridge spec: `.nightshift/specs/SPEC-019-shipyard-mcp-bridge.md`
- Parent self-server spec: `.nightshift/specs/SPEC-044-shipyard-self-server.md`
- Current docs that claim Codex support: `README.md`, `.argo/README.md`
- Repro verification: `.shipyard-dev/verify-spec-125.sh`

## Gap Protocol

- Research-acceptable gaps:
  - How `codex exec` differs from interactive Codex MCP handling
  - Whether the cancellation is triggered by approval metadata, bridge response shape, or
    handshake/tool-schema expectations
  - Whether the right fix is code, docs, or both
- Stop-immediately gaps:
  - The failure reproduces but no evidence can distinguish whether Shipyard or Codex owns the bug
  - The fix would require undocumented Codex internals with no stable workaround
- Max research subagents before stopping: 2
