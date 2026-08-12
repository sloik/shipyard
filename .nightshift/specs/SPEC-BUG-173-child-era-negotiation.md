---
id: SPEC-BUG-173
template_version: 7
priority: 1
layer: 1
type: refactor
status: draft
parent: SPEC-BUG-171
after: [SPEC-BUG-172]
nfrs: [SPEC-NFR-001]
created: 2026-08-12
stack: go
devkb_required: ["go.md", "architecture.md", "testing.md"]
---

# Negotiate modern and legacy child MCP eras

## Problem

`internal/proxy/manager.go` initializes every child as `2025-03-26`, sends `notifications/initialized`, caches `initReady`, and sends later requests without modern `_meta`. Modern-only children cannot work and child restarts can retain stale negotiation state.

## Requirements

- [ ] Probe `server/discover` once per child process; modern requests carry required metadata and never initialize.
- [ ] Fall back deterministically to the existing legacy handshake only for recognized legacy behavior.
- [ ] Reset/reprobe era and capabilities on restart; reject hand-rolled/private dialects with actionable diagnostics.
- [ ] Normalize results for internal consumers without altering raw capture.

## Acceptance Criteria

- [ ] AC1: Modern and legacy stdio fixtures list/call concurrently through the manager.
- [ ] AC2: Restarting a child clears era/capability state and renegotiates exactly once.
- [ ] AC3: Unsupported version, malformed discovery and timeout failures are classified, captured and race-free.
- [ ] AC4: Live smokes cover FastMCP modern/legacy and the current markitdown legacy child.

## Out of Scope

- External client-facing bridge/HTTP behavior.

