# Nightshift Report — SPEC-BUG-163

**Outcome:** done

## Summary

- Added four bounded, deterministic Go fuzz targets for configuration, JSON-RPC,
  authorization scope, and traffic query parsing.
- Added checked-in fuzz corpus seeds, including the minimized whitespace-query
  regression discovered while hardening the local test harness.
- CI now has an explicit deterministic seed-corpus step; README documents the
  local 30-second fuzz commands and seed-to-regression workflow.
- No live service, child process, browser, network target, or security bypass was used.

## Validation

- `go test ./cmd/shipyard ./cmd/shipyard-mcp ./internal/auth ./internal/web` — pass
- Four focused `go test -run=^$ -fuzz=... -fuzztime=30s` commands — pass
- `go test -race -count=1 -timeout 5m ./...` — pass
- `make quality` — pass

## Acceptance Criteria

- [x] AC1: Focused fuzz target in CLI/config, JSON-RPC, auth scope, and web query domains.
- [x] AC2: Seeds include empty/null/truncated JSON, nesting/boundary values, Unicode,
  duplicate fields, wildcard scope coverage, invalid dates, and extreme pagination.
- [x] AC3: Targets bound inputs; malformed JSON-RPC verifies the standard `-32700`
  error envelope without any request routing.
- [x] AC4: Scope target proves exact/narrow scopes deny unrelated server/tool pairs;
  config target checks decode/round-trip and server-order preservation.
- [x] AC5: Each target applies an explicit input bound and completed its 30-second run.
- [x] AC6: README documents minimizing failures, checking a named corpus seed into
  `testdata/fuzz`, and adding a deterministic regression test when needed.
- [x] AC7: Ordinary Go tests execute corpus seeds; CI names the seed-corpus run and
  README supplies all focused 30-second commands.
- [x] AC8: Full race suite and canonical quality gate passed.

## Verification Artifacts

- `.nightshift/reports/SPEC-BUG-163/verification.json`
- `.nightshift/reports/SPEC-BUG-163/verification.md`

## Suggested Follow-up Specs

(none)
