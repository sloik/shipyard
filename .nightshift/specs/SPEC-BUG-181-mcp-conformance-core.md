---
id: SPEC-BUG-181
template_version: 7
priority: 1
layer: 0
type: refactor
status: in_progress
parent: SPEC-BUG-180
after: []
nfrs:
- SPEC-NFR-001
created: 2026-08-12
stack: go
devkb_required:
- go.md
- architecture.md
- testing.md
technologies:
- go
scope:
  write:
  - internal/**
  - cmd/**
  - test/**
  - scripts/**
  - docs/**
  - go.mod
  - go.sum
  - Makefile
---

# MCP 2026-07-28 conformance fixtures and compatibility core

> Former ID: SPEC-BUG-172 (renumbered by SPEC-BUG-179 on 2026-10-03 to remove a duplicate ID).

## Problem

Shipyard hand-codes JSON-RPC types and version strings. There is no shared modern/legacy validator or official conformance harness, so later transport changes cannot be proven safely.

## Known gaps (measured 2026-10-03 at 95bc5a1)

The gap suite (R3) must name each of these by ID:

- G1: Managed children are always initialized with protocol version
  `2025-03-26` (`internal/proxy/manager.go:352`), with no negotiation.
- G2: Shipyard's own initialize responses hard-code `2025-11-25` and never
  offer `2026-07-28` (`internal/auth/middleware.go:222`,
  `internal/web/server.go:2378`, `cmd/shipyard-mcp/main.go:22`).
- G3: The HTTP gateway always issues an `Mcp-Session-Id` header
  (`internal/auth/middleware.go:215`). Modern-era requests are stateless and
  must not depend on it.
- G4: No code reads or sets the `MCP-Protocol-Version` HTTP header.
- G5: The JSON-RPC envelope is hand-coded (`internal/proxy/proxy.go:122`).
  There is no shared modern/legacy validator for requests, results, and errors.
- G6: `_meta` fields have no explicit pass-through or capture handling.
- G7: `notifications/cancelled` is never handled or forwarded deliberately.

## Requirements

- [ ] R1: Adopt the official Go SDK `github.com/modelcontextprotocol/go-sdk`
  v1.8.0 or later for protocol types and version negotiation. Where a custom
  type is kept at the capture boundary, document why in the spec's resolution.
  (v1.8.0 supports `2026-07-28`, `2025-11-25`, `2025-06-18`, `2025-03-26` and
  `2024-11-05`; verified in `mcp/shared.go`.)
- [ ] R2: Add modern (`2026-07-28`) and legacy (`2025-11-25`) fixture clients
  and servers, plus golden cases for discovery, `_meta`, errors, result and
  cache fields, routing headers, cancellation, and session-header absence.
- [ ] R3: Add a gap suite, invoked separately from `go test ./...`, with one
  named case per known gap G1–G7. Each case fails while its gap exists. Later
  child specs (SPEC-BUG-182…185) turn their cases green. The gap suite is
  never wired into the default test run or CI as a required check.
- [ ] R4: Integrate the official MCP conformance CLI
  (`@modelcontextprotocol/conformance`), pinned to an exact version (0.1.16 or
  later stable), against the fixture servers and clients. Expected-failure
  waivers may only be copied verbatim from the pinned go-sdk's
  `conformance/baseline.yml`. Shipyard adds zero waivers of its own.
- [ ] R5: The shared core keeps raw envelopes and headers alongside any
  normalized view. Capture records stay byte-identical to what was received.
- [ ] R6: Record the new dependency's license, security posture, and the exact
  revision to roll back to.

## Acceptance Criteria

- [ ] AC1 (R2, R3): The fixtures exercise both eras. Running the gap suite
  reports exactly G1–G7 as failing, each with its gap ID in the test name.
- [ ] AC2 (R1, R5): `go test -race -count=1 ./...` and `go vet ./...` pass,
  and the existing capture and parser tests pass unchanged.
- [ ] AC3 (R4): The pinned conformance CLI runs against the fixture servers
  and clients through one documented command. Every failure is either listed
  in the pinned SDK's baseline or fixed. The waiver list contains no
  Shipyard-added entry.
- [ ] AC4 (R5): A test proves that a captured request/response pair keeps its
  raw bytes and headers after passing through the shared core.
- [ ] AC5 (R6): A dependency record under `docs/` names the SDK version,
  license, security notes, and the rollback revision (`95bc5a1` or the
  baseline the run starts from).
- [ ] AC6: Live gateway, bridge, and child behavior is unchanged. The existing
  smoke and integration tests pass with no edits to their assertions.

## Context

- Parent plan: `.nightshift/specs/SPEC-BUG-180-mcp-2026-dual-era-migration.md`.
  SPEC-BUG-180 is a `type: main` tracker that stays `planned`. This child
  starts first because it has no dependencies.
- Hand-coded protocol code: `internal/proxy/proxy.go`,
  `internal/proxy/manager.go`, `internal/auth/middleware.go`,
  `internal/web/server.go`, `cmd/shipyard-mcp/main.go`.
- Capture: `internal/capture/store.go` and its tests.
- Existing test child: `internal/teststubchild/main.go`.
- SDK reference: go-sdk v1.8.0 `conformance/` (everything-client,
  everything-server, `baseline.yml`) and `scripts/*-conformance.sh`.
- Build and test: `go build ./...`, `go test -race -count=1 ./...`,
  `go vet ./...`, `make lint`.
- DevKB: `go.md`, `architecture.md`, `testing.md`.

## Out of Scope

- Changing live gateway, bridge, or child behavior. Closing gaps G1–G7 belongs
  to SPEC-BUG-182…185.
- Upgrading `markitdown-mcp` or deciding on the Slack fork (SPEC-BUG-180 R4).


## Scope Amendments

| Date | Path or glob | Change (old → new) | Reason | Approved by |
| --- | --- | --- | --- | --- |
| 2026-10-03 | .nightshift/coverage-baseline.json | not writable → writable | `make coverage-check` requires reviewed coverage floors for the new `internal/mcpcore` and `internal/mcpfixture` packages | human:Lukasz |

## State rationale

```yaml
schema_version: 1
status: in_progress
reason: mechanical transition to 'in_progress' via run kickoff-20261003-bug181
reconsider_when: null
evidence: []
provenance: authored
record: artifacts/20261003T154754Z-status-transition-ready-in-progress-mechanical-transition-.json
```
