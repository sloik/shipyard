---
id: SPEC-BUG-163
template_version: 7
priority: 3
layer: 1
type: refactor
status: in_progress
after: [SPEC-BUG-158]
provides: [parser-fuzz-regressions]
requires: [canonical-quality-command]
touches: [cmd/shipyard, cmd/shipyard-mcp, internal/auth, internal/web]
prior_attempts: []
nfrs: [SPEC-NFR-001]
created: 2026-07-18
stack: go
domain: code
output_type: code
devkb_required: [go.md, testing.md, architecture.md]
cortex_cites: []
karpathy_checklist: [simple, surgical, goal]
---

# Add Fuzz Tests for JSON-RPC, Config, Scope, and Query Parsers

## Problem

Shipyard accepts untrusted JSON-RPC, configuration, token-scope, filter, and query
inputs, but the repository has no Go fuzz targets. Conventional examples are extensive
yet do not continuously explore malformed nesting, boundary lengths, invalid encodings,
or parser invariant combinations. No parser crash was reproduced during this review;
the goal is to convert a broad input risk into durable regression seeds.

## Requirements

- [ ] R1: Add focused fuzz targets for JSON-RPC request/ID/params decoding, config decode/default/round-trip behavior, scope matching, and HTTP query/filter parsing.
- [ ] R2: Seed each target from existing regression and boundary tests rather than random-only corpora.
- [ ] R3: Assert parser-specific invariants: no panic/hang, bounded work, stable error shape, and round-trip/default preservation where applicable.
- [ ] R4: Persist every discovered crash/minimized input as a named regression seed before fixing implementation behavior.
- [ ] R5: Add a short deterministic seed-corpus CI run and document longer local fuzz commands.

## Acceptance Criteria

- [ ] AC1 (R1): At least one fuzz target exists in each relevant domain: CLI/config, JSON-RPC, auth scopes, and web query/filter parsing.
- [ ] AC2 (R2): Seeds include empty, null, truncated JSON, deeply nested/boundary input, Unicode, duplicate fields, unknown fields, wildcard scopes, invalid dates, and extreme pagination values where accepted by the target.
- [ ] AC3 (R3): Targets never panic or hang, and malformed JSON-RPC returns the repository's defined error envelope rather than partial success.
- [ ] AC4 (R3): Scope fuzz invariants prevent a narrower scope from authorizing an unrelated server/tool; config round-trip/default invariants are explicit.
- [ ] AC5 (R3): Input size/depth is bounded or the target demonstrates completion within the configured fuzz timeout.
- [ ] AC6 (R4): A documented workflow turns any fuzz failure into a checked-in `testdata/fuzz` seed and a deterministic regression test.
- [ ] AC7 (R5): CI runs all seed corpora via ordinary `go test`; documented 30-second focused fuzz commands pass for each target.
- [ ] AC8: Full ordinary/race suites and `make quality` remain green.

## Context

- Candidate packages: `cmd/shipyard`, `cmd/shipyard-mcp`, `internal/auth`, and `internal/web`.
- Start from existing config, JSON-RPC, scope, authz, and handler regression fixtures.
- Do not fuzz live child processes or browsers in this spec; keep targets pure or backed by lightweight in-memory dependencies.

## Scenarios

1. Fuzzer mutates a valid JSON-RPC request into malformed nesting -> parser returns bounded structured error, never panic.
2. Fuzzer combines wildcard and unrelated scope components -> authorization invariant remains deny-by-default.
3. Fuzzer finds a new crash -> minimized seed is committed -> ordinary `go test` reproduces it forever.

## Out of Scope

- Performance/load benchmarking of the full proxy.
- Browser DOM fuzzing.
- Network fuzzing against external MCP servers.
- Changing public parsing semantics without a separate reviewed decision.

## Documentation Impact

- Testing documentation — seed policy, local fuzz commands, and failure-to-regression workflow.

## Research Hints

- Read `Argo Home/DevKB/go.md`, `testing.md`, and `architecture.md`.
- Keep targets narrow and deterministic outside the fuzzed input; reset mutable state per iteration.
- Encode security invariants directly instead of checking only "did not panic."

## Validation Commands

```bash
go test ./cmd/shipyard ./cmd/shipyard-mcp ./internal/auth ./internal/web
go test -run=^$ -fuzz=Fuzz -fuzztime=30s ./cmd/shipyard
go test -run=^$ -fuzz=Fuzz -fuzztime=30s ./cmd/shipyard-mcp
go test -run=^$ -fuzz=Fuzz -fuzztime=30s ./internal/auth
go test -run=^$ -fuzz=Fuzz -fuzztime=30s ./internal/web
go test -race -count=1 -timeout 5m ./...
make quality
```
