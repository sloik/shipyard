---
id: SPEC-BUG-177
template_version: 3
priority: 2
layer: 1
type: bugfix
status: done
after: []
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-09-24
---

# runChild loses child output written just before the child exits

## Problem

`internal/proxy/proxy.go` `runChild()` read the child's stdout/stderr from
`cmd.StdoutPipe()`/`cmd.StderrPipe()` in goroutines, then called `cmd.Wait()`
before those goroutines finished. The `os/exec` docs say this is incorrect:
`Wait` closes those pipes as soon as the process exits, so any lines the child
wrote just before exiting that had not yet been read were lost. They were
never forwarded to the MCP client and never captured.

Symptom: `TestRunChild_NonZeroExitReturnsError` (the child prints one JSON-RPC
line and then runs `exit 7`) timed out in `waitForStoreCount` in about 2 of
~30 full `go test ./internal/proxy/` runs, and never when run alone. It was
found while working on SPEC-BUG-173/174.

A slowed-down reader makes the loss happen every time: with a 2 ms-per-write
output, a child that prints 40 lines and exits had only 0–31 of them
forwarded.

## Requirements

- [x] R1: All output a child writes before exiting is forwarded and captured
  before `runChild` returns.
- [x] R2: Keep the `inputWriter.detach(childStdin)` ordering after the child
  exits.
- [x] R3: A child, or an orphaned grandchild, that never closes its stdout
  cannot hang shutdown. Context cancellation still kills the child.

## Acceptance Criteria

- [x] AC1: `go test -race -count=50 -run TestRunChild_NonZeroExitReturnsError
  ./internal/proxy/` passes.
- [x] AC2: The full `./internal/proxy/` package passes 20 repeated runs with no
  timeouts.
- [x] AC3: A regression test covers a child that writes and exits immediately.
- [x] AC4: `go test -race ./...` and `go vet ./...` pass.

## Resolution — 2026-09-24

A plain reorder (`wg.Wait()` before `cmd.Wait()`) would hang whenever an
orphaned grandchild inherits the child's stdout (for example `npx` or shell
wrappers), because the readers would never see EOF. Instead:

- `cmdStdoutPipe`/`cmdStderrPipe` now return a `childOutputPipe` (an
  `io.Pipe`) that is set as `cmd.Stdout`/`cmd.Stderr`. With an `io.Writer`,
  `exec` copies the output itself and `cmd.Wait()` returns only after that
  copy reaches EOF. `runChild` then closes the writer, so the readers drain
  everything before `wg.Wait()` returns.
- `cmd.WaitDelay = childOutputWaitDelay` (2s) caps that copy after the child
  exits or the context is done. An orphan holding the pipe open costs at most
  2s instead of hanging. When the child itself exited cleanly,
  `exec.ErrWaitDelay` is logged and mapped to a clean exit.
- Each reader goroutine closes its pipe on return, so a reader that stops
  early (for example on a write error) cannot block `exec`'s copy.
- The test seams keep their signatures. `TestRunChild_PipeFailures` still
  injects creation errors.

Tests (new file `internal/proxy/proxy_childexit_test.go`):

- `TestSPECBUG177_ChildOutputDrainedAfterImmediateExit`: 40 lines followed by
  `exit 3`, with a slow writer. All 40 lines are forwarded and captured. This
  test failed on every run before the fix.
- `TestSPECBUG177_OrphanHoldingStdoutDoesNotHang`: `sleep 30 &` keeps stdout
  open. `runChild` returns within the wait delay.
- `TestSPECBUG177_ContextCancelStopsSilentChild`: cancelling the context
  stops a child that never exits.

Verification: AC1 passed 50/50 with `-race`; AC2 passed 20/20 (plus 3 runs
with `-race`); `go test -race` and `go vet` pass for `./internal/...` and
`cmd/shipyard-mcp`; `go vet -tags server ./cmd/shipyard` passes; the Tool
Browser, Servers and Traffic headless smoke harnesses all pass against a
fresh build.

## Code Pointers

- `internal/proxy/proxy.go`: `childOutputPipe`, `cmdStdoutPipe`,
  `cmdStderrPipe`, `runChild()`
- `internal/proxy/proxy_childexit_test.go`
