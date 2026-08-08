# Nightshift Report — SPEC-BUG-158

- Date: 2026-08-08
- Status: implementation complete; awaiting parent-owned integration and lifecycle finalization
- Branch: `nightshift/SPEC-BUG-158-unblock-20260808T1200Z`

## Summary

Established `make quality` as Shipyard's single blocking quality contract for
local development, Nightshift, and CI. The target checks canonical Go
formatting, pinned Staticcheck, `go vet`, GitHub Actions workflow syntax,
standalone and inline JavaScript syntax, zsh parseability, build, ordinary
tests, and the configured race suite.

The user-authorized bridge timeout/client refactor was reproduced unchanged
before this work. Its metadata and tool-call clients retain their distinct
timeouts, and its timeout-specific behavior is covered by tests. The five
pre-existing `shipyard-mcp` Staticcheck error-string findings were repaired to
lowercase; the bridge's new error strings follow the same Go convention.

## Changes

- Added a repository-owned pinned tools module for Staticcheck and actionlint.
- Added `format-check`, `lint`, `type-check`, `script-check`, `race`, `quality`,
  and `quality-self-test` Make targets.
- Updated CI to invoke only `make quality`; aligned Nightshift's meaningful
  lint/type/format/test gates and race contract.
- Added deterministic JavaScript/inline-script extraction and syntax checking,
  plus controlled invalid fixtures for Staticcheck, actionlint, JavaScript, and
  zsh.
- Ran `gofmt` over tracked Go sources and repaired Staticcheck findings without
  blanket rule or directory exclusions. `.staticcheck.conf` enables `all` and
  documents the narrow-suppression policy; it has no exceptions.
- Kept the bridge refactor's long tool-call timeout and timeout diagnostic,
  with regression tests for longer tool calls, deadline diagnostics, and server
  metadata decoding.

## Acceptance Criteria

- [x] AC1 — `make quality` runs formatting, analyzers, workflow/script syntax,
  build, ordinary tests, and `go test -race -count=1 -timeout 5m ./...`.
- [x] AC2 — `test -z "$(gofmt -l $(git ls-files '*.go'))"` passes.
- [x] AC3 — pinned Staticcheck runs clean on `./...`; its controlled bad
  fixture exits nonzero.
- [x] AC4 — actionlint, JavaScript/inline-script syntax, and `zsh -n` are
  blocking and their negative fixtures exit nonzero.
- [x] AC5 — Nightshift `lint`, `type_check`, `format`, and `test` are distinct,
  meaningful commands; `test` contains the race/count/timeout contract.
- [x] AC6 — CI invokes `make quality` rather than duplicating a divergent list.
- [x] AC7 — no blanket analyzer disable or whole-directory exclusion was added.
- [x] AC8 — module tidy/verify, ordinary tests, and the full race suite pass.

## Validation Evidence

All commands completed successfully in the isolated worktree:

```text
make quality
make quality-self-test
test -z "$(gofmt -l $(git ls-files '*.go'))"
go mod tidy -diff
go mod verify
(cd tools && go mod tidy -diff && go mod verify)
git diff --check
```

`make quality-self-test` confirmed that Staticcheck, actionlint, JavaScript
syntax, and zsh parsing each reject their committed invalid fixture. The Go
build/test commands emitted existing macOS linker deployment-target warnings,
but exited successfully; no test or race failure occurred.

## Suggested Follow-up Specs

None. The spec's explicitly out-of-scope security scanning and coverage work
already have follow-up specs (`SPEC-BUG-159` and `SPEC-BUG-160`), which this run
did not modify.
