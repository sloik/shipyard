# Nightshift Report — SPEC-BUG-164-001

**Status:** implementation complete; held for parent evidence-gate decision

## Outcome

The Serena transport recovery succeeded. The worker implemented and committed
per-tool managed-child response timeouts in `f017b6d`.

## Serena Recovery

The parent authorized installation of the standard Go language server. The
following completed successfully:

```text
go install golang.org/x/tools/gopls@latest
command -v gopls
/opt/homebrew/bin/gopls
gopls version
golang.org/x/tools/gopls v0.23.0
```

`/opt/homebrew/bin/gopls` is a symlink to the Go toolchain-installed binary at
`/Users/ed/go/bin/gopls`, so it is on the normal terminal PATH.

After the parent refreshed the Serena transport, the worker called the Serena
initial-instructions and project-activation tools. A symbolic overview of
`internal/proxy/manager.go` succeeded, confirming the Go language server is
available for this run.

## Implementation

- `ToolConfig` accepts optional `response_timeout_seconds` values.
- Configured positive durations are copied into the managed child at registration,
  so request-time reads are immutable and race-safe.
- Only a valid `tools/call` parameter object with a configured `name` uses the
  override. Other methods, malformed/missing names, missing tools, and
  non-positive values use the 30-second default.
- Timeout errors retain the selected effective duration.

## Validation

| Gate | Result |
| --- | --- |
| `go test ./internal/proxy` | pass |
| `go test -race -count=1 ./internal/proxy` | pass |
| focused config timeout test | pass |
| `go vet ./...` | pass |
| `go build ./...` | pass |
| `go test ./...` | fail: existing `cmd/shipyard` `TestMain_ConfigMissingCommand` expects exit code 1, got 0 |
| `go test -race -count=1 ./...` | same existing failure; no race reported |

The full-suite failure was reproduced before and after implementation and is
outside this spec's timeout behavior. No unrelated test was changed or skipped.

## Parent Action

The worktree is clean at implementation commit `f017b6d`. The parent should
apply the evidence gate and decide whether to merge while separately triaging
the existing `TestMain_ConfigMissingCommand` failure.

## Suggested Follow-up Specs

None.
