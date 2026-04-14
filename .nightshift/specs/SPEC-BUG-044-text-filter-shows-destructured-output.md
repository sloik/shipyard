---
id: SPEC-BUG-044
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-BUG-005, SPEC-040]
violates: []
prior_attempts: []
created: 2026-04-14
---

# Text filter shows de-structured / raw-looking output instead of readable JSON

## Problem

When a text query is entered in the JSON filter input (Text mode), the viewer
hides individual `.json-line` rows that do not match. The remaining visible rows
are isolated fragments — bracket lines, structural tokens, and matching value
lines shown without their surrounding context. The result looks like broken /
raw output and is difficult to read.

After SPEC-040, each `.json-line` is a flex row `[line-num][content]`. The
`textContent` used for matching concatenates the line number digit(s) with the
JSON content (e.g. `"1{"`, `"2  \"content\": ["`) — so line-number digits
participate in matches, producing false positives and missed matches.

## Reproduction

1. Open the Tools tab, execute any tool that returns a JSON object.
2. Type a key name (e.g. `content`) in the "Filter JSON..." input.
3. **Observed:** isolated matching lines visible without parent brackets or
   surrounding structure; the output reads as a series of raw JSON fragments.
4. **Observed:** typing a single digit (e.g. `1`) matches every line whose
   line number starts with that digit rather than matching JSON content.
5. **Expected:** only JSON content is matched (line numbers excluded from
   match text); matched lines are shown in a way that preserves readable
   structure or context.

## Acceptance Criteria

- [ ] AC 1: The filter matches against JSON content text only — line number
  digits are excluded from the match string.
- [ ] AC 2: Matching lines remain visible; non-matching lines are hidden.
- [ ] AC 3: When a match is found, structural context lines (parent brackets,
  enclosing object/array braces) that are ancestors of the matching line
  remain visible so the output is valid-looking JSON.
- [ ] AC 4: Clearing the filter input restores all lines.
- [ ] AC 5: Filter works identically in the Tool Browser response panel, and
  in REQUEST / RESPONSE per-panel filters in the traffic timeline.
- [ ] AC 6: `go test -race -count=1 -timeout 5m ./...` passes.
- [ ] AC 7: `go vet ./...` passes.
- [ ] AC 8: `go build ./...` passes.
- [ ] AC 9: `ui_layout_test.go` contains a test verifying that line number
  text is not included in the match string (i.e. searching "1" does not
  match all lines, only lines whose content contains "1").

## Context

- Implementation: `internal/web/ui/index.html` — `filterJsonLines()` (~line
  1154). Also check `wireFilterInputs()` which calls it.
- Each `.json-line` after SPEC-040: flex row with `.ln` (line number) and
  `.lc` (line content) child elements. Match text should use `.lc` textContent,
  not the parent `.json-line` textContent.
- Test file: `internal/web/ui_layout_test.go`

## Out of Scope

- JQ expression evaluation (separate spec SPEC-041)
- Re-rendering filtered result as a new JSON tree (out of scope for this fix)
- Changing filter UI layout or mode-toggle buttons
