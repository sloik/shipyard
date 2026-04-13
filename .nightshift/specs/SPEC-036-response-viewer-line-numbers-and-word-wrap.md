---
id: SPEC-036
template_version: 2
priority: 1
layer: 2
type: feature
status: done
after: [SPEC-BUG-034]
violates: []
prior_attempts: []
created: 2026-04-13
---

# Response viewer: line numbers and word wrap

## Problem

The JSON response viewer (`#tool-response-json`) renders each line as a plain `<div
class="json-line">` with `white-space: pre`, so:

- Lines have no number — impossible to reference a specific line in the output
- Long lines (e.g. large string values) overflow the panel horizontally rather than
  wrapping, making them unreadable without horizontal scroll

The UX-002 design file (frame `HqBpj`, updated 2026-04-13) specifies numbered lines in a
fixed-width gutter and word-wrapped content. The implementation must match this design.

## Root Cause

`highlightJSON()` emits bare escaped text inside `.json-line` with no line-number element.
`.json-line` in `ds.css` has `white-space: pre`, which prevents wrapping.

## Fix

Two-part change:

### 1. `highlightJSON` — add `ln`/`lc` spans

Replace the current line output:
```javascript
result += '<div class="json-line ' + cls + '">' + escapeHtml(line) + '</div>';
```
With:
```javascript
result += '<div class="json-line ' + cls + '">'
        + '<span class="ln">' + (i + 1) + '</span>'
        + '<span class="lc">' + escapeHtml(line) + '</span>'
        + '</div>';
```

### 2. `ds.css` — flex layout for `.json-line`, gutter + wrap styles

Replace `.json-line { white-space: pre; }` with:

```css
.json-line {
  display: flex;
  align-items: flex-start;
}

.json-line .ln {
  width: 32px;
  min-width: 32px;
  text-align: right;
  padding-right: 12px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  user-select: none;
  flex-shrink: 0;
}

.json-line .lc {
  flex: 1;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  min-width: 0;
}
```

Remove the `.json-viewer` top-level `white-space: pre-wrap; word-break: break-all` —
those properties are now on `.lc` where they belong.

### Scope

`highlightJSON` is called from three places:
1. Tool Browser response panel (`toolResponseBody` function, line ~2075)
2. History tab request/response detail panels (lines ~1006, 1023, 1029)
3. Diff view is **not** affected — its lines are generated separately and don't use
   `highlightJSON`

All three usages pick up the change automatically since it's in the shared function.
Line numbers will appear in both the Tool Browser response panel and History detail panels.

## Requirements

- [ ] R1: Each line in `highlightJSON` output has a `<span class="ln">N</span>` with the
  1-based line number.
- [ ] R2: Each line in `highlightJSON` output has a `<span class="lc">...</span>`
  wrapping the escaped content.
- [ ] R3: `.json-line .ln` is a fixed-width gutter (32px), right-aligned, muted color,
  `user-select: none` (excluded from text selection/copy).
- [ ] R4: `.json-line .lc` has `white-space: pre-wrap; overflow-wrap: break-word` so
  long lines wrap within the panel.
- [ ] R5: `.json-line` uses `display: flex; align-items: flex-start` so the line number
  stays top-aligned when the code wraps to multiple visual lines.
- [ ] R6: `.json-viewer` no longer carries `white-space: pre-wrap; word-break: break-all`
  at the container level (those properties moved to `.lc`).

## Acceptance Criteria

- [ ] AC 1: `highlightJSON` in `index.html` contains `class="ln"` and `class="lc"` inside
  the per-line template.
- [ ] AC 2: `.json-line` in `ds.css` has `display:flex` and `align-items:flex-start`.
- [ ] AC 3: `.json-line .ln` in `ds.css` has `user-select:none` and `width:32px`.
- [ ] AC 4: `.json-line .lc` in `ds.css` has `white-space:pre-wrap` and
  `overflow-wrap:break-word`.
- [ ] AC 5: `.json-line .lc` in `ds.css` has `min-width:0` (prevents flex child overflow).
- [ ] AC 6: `.json-line` in `ds.css` no longer has `white-space:pre` as a standalone rule.
- [ ] AC 7: No existing `go test ./...` test is broken by the change (layout tests check
  HTML structure — update any that assert the old plain-text `.json-line` format).
- [ ] AC 8: `go vet ./...` passes.
- [ ] AC 9: `go build ./...` passes.
- [ ] AC 10: `.shipyard-dev/verify-spec-036.sh` exits 0.

## Verification Script

Create `.shipyard-dev/verify-spec-036.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then echo "  PASS: $desc"; PASS=$((PASS+1))
  else echo "  FAIL: $desc"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-036 Verification ==="

grep -q 'class="ln"' internal/web/ui/index.html
check "highlightJSON emits class=\"ln\" span" $?

grep -q 'class="lc"' internal/web/ui/index.html
check "highlightJSON emits class=\"lc\" span" $?

grep -q 'display.*flex' internal/web/ui/ds.css
check ".json-line has display:flex" $?

grep -q 'user-select.*none' internal/web/ui/ds.css
check ".json-line .ln has user-select:none" $?

grep -q 'white-space.*pre-wrap' internal/web/ui/ds.css
check ".json-line .lc has white-space:pre-wrap" $?

grep -q 'overflow-wrap.*break-word' internal/web/ui/ds.css
check ".json-line .lc has overflow-wrap:break-word" $?

grep -q 'min-width.*0' internal/web/ui/ds.css
check ".json-line .lc has min-width:0" $?

# .json-line must NOT have standalone white-space:pre (check absence of that exact rule)
! grep -qP '\.json-line\s*\{[^}]*white-space:\s*pre[^-]' internal/web/ui/ds.css
check ".json-line no longer has standalone white-space:pre" $?

go test ./...
check "go test ./..." $?

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
```

## Context

### Target files

- `internal/web/ui/index.html`
  - `highlightJSON` function (~line 907): change the `result +=` line inside the for-loop
    to emit `<span class="ln">` and `<span class="lc">` inside each `.json-line`
  - No other JS changes needed — the function is shared across all usages

- `internal/web/ui/ds.css`
  - Section `17.` (JSON Viewer, ~line 1146): replace `.json-line { white-space: pre; }`
    with the flex + `.ln` + `.lc` rules above
  - Also remove `white-space: pre-wrap; word-break: break-all;` from `.json-viewer`
    (~line 1141) — those are now on `.lc`

- `internal/web/ui_layout_test.go`
  - Search for any test that asserts `json-line` content without `ln`/`lc` spans.
    If found, update the assertion to match the new structure. Grep for `json-line`
    in the test file before editing.

### What NOT to change

- The `jt-*` color classes remain on `.json-line` — they continue to control the line
  color via CSS inheritance to `.lc`
- The diff view (`leftHtml`/`rightHtml` builders around line 2670) does not use
  `highlightJSON` — leave those unchanged
- The `filterJsonLines` function works on `.json-line` elements — it should continue
  to work since the div structure is preserved; the filter hides/shows whole `.json-line`
  divs, which still works with the new inner structure

### Colour inheritance note

The `jt-*` colour classes (`color: var(--json-key)` etc.) are on the `.json-line` div.
With flex layout, `color` inherits into `.lc` (the content span) automatically — no
change needed. `.ln` uses its own explicit `color: var(--text-muted)` which overrides
the inherited `jt-*` colour, keeping line numbers always muted regardless of line type.

## Out of Scope

- Line numbers in the diff view (separate spec if desired)
- Line number width scaling for very large responses (32px handles up to 4-digit
  line counts, which covers all realistic MCP responses)
- Click-to-select-line behaviour
- Horizontal scroll as a fallback option (word wrap replaces it entirely)

## Gap Protocol

- Research-acceptable gaps: verifying `filterJsonLines` still works with new `.lc` inner
  span — read its implementation before deciding if a test update is needed
- Stop-immediately gaps: `go test` failures; `.json-line` colour stops working
- Max research subagents before stopping: 0
