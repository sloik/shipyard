---
id: SPEC-BUG-037
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-036]
violates: []
prior_attempts: []
created: 2026-04-13
---

# JSON response viewer wraps at characters, not word boundaries

## Problem

SPEC-036 added word wrap to the response viewer but used `overflow-wrap: break-word`
on `.json-line .lc`. This property breaks lines at any character position, not at
word/token boundaries. Long JSON string values (URLs, identifiers, base64 fragments)
get split mid-word:

```
"value": "https://example.com/api/v1/users/ab
cdef1234"
```

Lines should wrap at natural word boundaries (spaces, after commas, after colons)
and only break mid-word if a single token is longer than the container.

## Root Cause

`overflow-wrap: break-word` is equivalent to `word-break: break-word` — it is a
last-resort break that fires at any character. Combined with `white-space: pre-wrap`,
it produces character-level breaks on dense JSON values that have no whitespace.

The correct property is `overflow-wrap: normal` (wrap at whitespace only) with
`word-break: normal` (no mid-word breaks). For the rare case where a single token
exceeds the container width, `overflow-wrap: anywhere` gives word-first priority
with character fallback — but `normal` is preferable for a developer tool where
seeing the full unbroken token is more useful than forced wrapping.

## Fix

In `ds.css`, in the `.json-line .lc` rule:

**Is:**
```css
.json-line .lc {
  flex: 1;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  min-width: 0;
}
```

**Should be:**
```css
.json-line .lc {
  flex: 1;
  white-space: pre-wrap;
  word-break: normal;
  overflow-wrap: normal;
  min-width: 0;
}
```

This wraps only at natural whitespace/punctuation boundaries. A single token longer
than the container will overflow its row rather than break mid-character.

## Requirements

- [ ] R1: JSON lines wrap at word boundaries (spaces, after commas/colons that are
  followed by a space), not at arbitrary character positions.
- [ ] R2: A single token that is longer than the container width overflows its row
  (visible via the viewer's `overflow: auto` scroll) rather than breaking mid-character.

## Acceptance Criteria

- [ ] AC 1: `.json-line .lc` in `ds.css` has `word-break: normal`.
- [ ] AC 2: `.json-line .lc` in `ds.css` has `overflow-wrap: normal`.
- [ ] AC 3: `.json-line .lc` in `ds.css` does NOT have `overflow-wrap: break-word`.
- [ ] AC 4: `go test ./...` passes.
- [ ] AC 5: `go vet ./...` passes.
- [ ] AC 6: `go build ./...` passes.
- [ ] AC 7: `.shipyard-dev/verify-spec-037.sh` exits 0.

## Verification Script

Create `.shipyard-dev/verify-spec-037.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  if [ "$2" = "0" ]; then echo "  PASS: $1"; PASS=$((PASS+1))
  else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-BUG-037 Verification ==="

grep -q 'word-break.*normal' internal/web/ui/ds.css
check ".json-line .lc has word-break:normal" $?

grep -q 'overflow-wrap.*normal' internal/web/ui/ds.css
check ".json-line .lc has overflow-wrap:normal" $?

! grep -q 'overflow-wrap.*break-word' internal/web/ui/ds.css
check ".json-line .lc does not have overflow-wrap:break-word" $?

go test ./...
check "go test ./..." $?

echo ""; echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
```

## Context

### Target file

- `internal/web/ui/ds.css` — `.json-line .lc` rule (added by SPEC-036):
  replace `overflow-wrap: break-word` with `word-break: normal; overflow-wrap: normal`

### No JS changes needed

The fix is CSS-only. `highlightJSON` output is unchanged.

## Out of Scope

- Handling tokens longer than the container width in any special way (overflow is
  acceptable; this is a developer tool)
- Changes to any other wrap behaviour in the app

## Gap Protocol

- Research-acceptable gaps: none — change is fully specified
- Stop-immediately gaps: `go test` failures
- Max research subagents before stopping: 0
