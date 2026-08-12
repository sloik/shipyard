---
id: SPEC-BUG-172
template_version: 7
priority: 1
layer: 0
type: refactor
status: draft
parent: SPEC-BUG-171
after: []
nfrs: [SPEC-NFR-001]
created: 2026-08-12
stack: go
devkb_required: ["go.md", "architecture.md", "testing.md"]
---

# MCP 2026-07-28 conformance fixtures and compatibility core

## Problem

Shipyard hand-codes JSON-RPC types and version strings. There is no shared modern/legacy validator or official conformance harness, so later transport changes cannot be proven safely.

## Requirements

- [ ] Adopt official Go SDK v1.7.0+ for protocol types/version negotiation, or document why a custom type is required at the capture boundary.
- [ ] Add modern and legacy fixture clients/servers plus golden cases for discovery, `_meta`, errors, result/cache fields, routing headers, cancellation and session-header absence.
- [ ] Integrate the official MCP conformance CLI with pinned version and zero project-owned expected-failure waivers.
- [ ] Preserve raw envelopes/headers alongside normalized views.

## Acceptance Criteria

- [ ] AC1: Fixtures prove both eras and fail on every known current Shipyard gap.
- [ ] AC2: `go test -race -count=1 ./...`, conformance and existing capture/parser tests pass after the shared core lands.
- [ ] AC3: A dependency/license/security record and exact rollback revision exist.

## Out of Scope

- Changing live gateway behavior.

