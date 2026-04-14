---
id: SPEC-BUG-040
template_version: 2
priority: 2
layer: 2
type: bugfix
status: in_progress
after: [UX-002, SPEC-BUG-039]
violates: [UX-002]
prior_attempts: []
created: 2026-04-13
---

# Response header has a Retry button not present in the approved design

## Problem

The response header implementation (`internal/web/ui/index.html`) includes a Retry
button (`#tool-response-retry`) in the response header row:

```html
<button class="btn btn-default btn-sm" id="tool-response-retry">Retry</button>
```

The approved design frame `Q9lu4` (respHeader) defines exactly two top-level children:

- `uo10d` (respTitle) — Response label + status badge
- `Eurmv` (respMeta) — latency pill + Copy button

There is no Retry button anywhere in the respHeader frame. The extra button clutters
the header and deviates from the approved layout.

**Violated spec:** UX-002 (dashboard design)
**Violated criteria:** respHeader (Q9lu4) must contain only respTitle and respMeta;
no additional controls

## Reproduction

1. Open the Tools tab
2. Select any tool and execute it
3. Observe the response header

4. **Actual:** header shows "Copy" and "Retry" buttons on the right
5. **Expected:** header shows only the latency pill and "Copy" button on the right
   (no Retry)

## Root Cause

(To be filled by agent.)

A Retry button was added during implementation that has no counterpart in the design.
It is wired in JS as `toolResponseRetry` (line ~1531) and `resetToolResponseMeta`
disables/enables it alongside the copy button.

## Requirements

- [ ] R1: The Retry button element (`#tool-response-retry`) is removed from the
  response header HTML.
- [ ] R2: All JS references to `toolResponseRetry` are removed, including the
  `var` declaration and any `.disabled`, `.addEventListener`, and
  `resetToolResponseMeta` references.
- [ ] R3: No other response-section functionality is affected by the removal.

## Acceptance Criteria

- [ ] AC 1: The response header contains no Retry button element.
- [ ] AC 2: No JS reference to `toolResponseRetry` or `#tool-response-retry` remains.
- [ ] AC 3: `resetToolResponseMeta()` still resets copy and latency state correctly.
- [ ] AC 4: Execute a tool — the response renders; no JS errors in console.
- [ ] AC 5: `ui_layout_test.go` contains a test asserting the response header does
  not contain a Retry button.
- [ ] AC 6: `go test ./...` passes.
- [ ] AC 7: `go vet ./...` passes.
- [ ] AC 8: `go build ./...` passes.

## Context

- Design frame: `Q9lu4` (respHeader) — no Retry button present
- Implementation: `internal/web/ui/index.html` line ~217
- JS var: `toolResponseRetry` line ~1531
- JS usage: `resetToolResponseMeta()` line ~1587–1588 (disables/enables it)
- Test file: `internal/web/ui_layout_test.go`

## Notes for the Agent

- Search for ALL occurrences of `toolResponseRetry` and `tool-response-retry` in
  `index.html` before removing — there may be event listeners beyond what is
  visible in the reset function.
- The JS conventions for this project: `var`, `.then()`, no `async/await`, no
  `let`/`const`.
- After this spec, the right-hand side of the response header will be:
  latency pill → Copy button (per SPEC-BUG-039 which this spec depends on).

## Out of Scope

- Adding a Retry action elsewhere in the UI (separate product decision)
- Changing Execute button behaviour
- Restructuring the response section beyond removing the button

## Gap Protocol

- Research-acceptable gaps: any secondary event listeners on the Retry button
- Stop-immediately gaps: any change to the Execute or Copy button wiring
- Max research subagents before stopping: 0
