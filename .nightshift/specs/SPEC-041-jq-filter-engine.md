---
id: SPEC-041
priority: 2
layer: 2
type: feature
status: done
after: [SPEC-BUG-005, SPEC-BUG-044]
prior_attempts: []
created: 2026-04-14
---

# JQ filter engine — evaluate jq expressions in the JSON viewer

## Problem

The JQ mode button exists in every JSON filter bar but shows only a toast:
`"JQ mode is not yet implemented"`. Users cannot query or transform JSON
responses using jq expressions. This makes it hard to extract specific fields
from large or nested MCP tool responses.

## Requirements

- [ ] R1: When JQ mode is active and the input contains a valid jq expression,
  evaluate the expression against the full raw JSON of that panel and replace
  the viewer content with the result, rendered as pretty-formatted highlighted
  JSON.
- [ ] R2: Evaluation is triggered live as the user types (debounced ≥ 200 ms
  to avoid evaluating on every keystroke).
- [ ] R3: If the expression is invalid or produces an error, display an inline
  error message in the viewer (do not crash or clear the original content
  permanently).
- [ ] R4: If the expression input is empty or the result equals the original
  JSON, restore the original highlighted viewer content.
- [ ] R5: Switching back to Text mode from JQ mode restores the original viewer
  content and clears any jq error state.
- [ ] R6: JQ mode works in all filter contexts: Tool Browser response panel,
  combined filter (traffic timeline), and per-panel REQUEST / RESPONSE filters.
- [ ] R7: The raw captured JSON is never modified — jq evaluation is display-only.

## Acceptance Criteria

- [ ] AC 1: Entering `.foo` in JQ mode for `{"foo": 1}` renders `1` in the viewer.
- [ ] AC 2: Entering `.foo.bar` for nested JSON renders the nested value.
- [ ] AC 3: Entering an invalid expression shows an inline error string, not a
  blank viewer.
- [ ] AC 4: Clearing the JQ input restores the original highlighted viewer content.
- [ ] AC 5: Switching from JQ → Text mode restores the original content.
- [ ] AC 6: Evaluation is debounced — rapid typing does not fire multiple
  evaluations per keystroke.
- [ ] AC 7: `go test -race -count=1 -timeout 5m ./...` passes.
- [ ] AC 8: `go vet ./...` passes.
- [ ] AC 9: `go build ./...` passes.
- [ ] AC 10: `ui_layout_test.go` contains a test verifying that the jq
  evaluation path produces non-empty output for a valid expression and an
  error message for an invalid one.

## Context

- Mode toggle wiring: `internal/web/ui/index.html` ~line 1225 —
  `if (mode === 'jq') { DS.toast(...) }` — this is where JQ handling must be
  added.
- Raw JSON source: each json-viewer is populated by `highlightJSON(payload)`
  where `payload` is the raw JSON string. The raw string must be accessible
  at filter time (store it as a `data-raw` attribute on the viewer element,
  or retrieve it from the entry object).
- Rendering result: reuse `highlightJSON()` to render the jq output so it
  matches the existing syntax-highlighted style.
- Client-side jq: use a self-contained JS jq implementation (e.g. `jq-web`,
  `jq.js`, or equivalent). It must work without a build step — either inline
  or loaded as a `<script>` within `index.html`. No new Go dependencies or
  backend endpoints for this spec.
- Test file: `internal/web/ui_layout_test.go`

## Notes for the Agent

- Vanilla JS only: `var`, `.then()`, no `async/await`, no `let`/`const`.
- The debounce helper may already exist in `ds.js` — grep before writing one.
- Store the raw JSON on the viewer element (e.g. `viewer.dataset.rawJson = payload`)
  when the viewer is first populated so the filter can access it without
  querying the server.
- Do NOT modify `highlightJSON()` — only call it on jq output.
- Do NOT fetch from the API during filter evaluation — everything is client-side.

## Out of Scope

- Server-side jq execution
- Saving or exporting jq expressions
- Syntax highlighting of the jq expression input itself
- jq streaming or multi-document output
