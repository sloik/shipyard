# Nightshift Report — SPEC-BUG-037

**Date:** 2026-04-13
**Spec:** SPEC-BUG-037 — JSON viewer character wrap not word wrap
**Type:** bugfix | **Layer:** 2 | **Priority:** 1
**Status:** COMPLETE

---

## Summary

Single-line CSS fix. The `.json-line .lc` rule in `internal/web/ui/ds.css` had `overflow-wrap: break-word`, which caused JSON string values (URLs, identifiers, base64 fragments) to break at arbitrary character positions. Replaced with `word-break: normal; overflow-wrap: normal` so long tokens overflow their row rather than splitting mid-character.

---

## Changes Made

### `internal/web/ui/ds.css` (line 1160)

Before:
```css
.json-line .lc {
  flex: 1;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  min-width: 0;
}
```

After:
```css
.json-line .lc {
  flex: 1;
  white-space: pre-wrap;
  word-break: normal;
  overflow-wrap: normal;
  min-width: 0;
}
```

### `.shipyard-dev/verify-spec-037.sh` (new file)

Created verification script as specified. Checks AC1–AC3 with grep, runs `go test ./...` for AC4.

---

## Acceptance Criteria

| AC | Description | Result |
|----|-------------|--------|
| AC1 | `.json-line .lc` has `word-break: normal` | PASS |
| AC2 | `.json-line .lc` has `overflow-wrap: normal` | PASS |
| AC3 | `.json-line .lc` does NOT have `overflow-wrap: break-word` | PASS |
| AC4 | `go test ./...` passes | PASS |
| AC5 | `go vet ./...` passes | PASS |
| AC6 | `go build ./...` passes | PASS |
| AC7 | `.shipyard-dev/verify-spec-037.sh` exits 0 | PASS (4/4 checks) |

---

## Verification Output

```
=== SPEC-BUG-037 Verification ===
  PASS: .json-line .lc has word-break:normal
  PASS: .json-line .lc has overflow-wrap:normal
  PASS: .json-line .lc does not have overflow-wrap:break-word
  PASS: go test ./...

Results: 4 passed, 0 failed
```

---

## Notes

- CSS-only change. No Go, JS, or other files touched.
- No other wrap behaviour in the app was modified.
- `word-break: normal` + `overflow-wrap: normal` + `white-space: pre-wrap` means: JSON lines wrap at spaces/punctuation (natural word boundaries), and a single token longer than the container width will overflow its row rather than break.

---

## Human Review Checklist

- [ ] Visual spot-check: open a JSON response in the viewer, confirm no mid-word breaks on long values
- [ ] Spot-check with a URL value (e.g. `"url": "https://very-long-domain.example.com/path/to/resource"`) — should overflow, not break mid-character
- [ ] Confirm no regression on normal-length JSON values
