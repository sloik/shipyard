# Nightshift Report — SPEC-BUG-050

**Date:** 2026-04-14
**Spec:** SPEC-BUG-050 — WS indicator dot 6px → 8px
**Status:** done
**Result:** success

## Summary

Fixed `.ws-indicator::before` dot size in `internal/web/ui/ds.css` from 6×6px to 8×8px to match UX-002 design specification.

## Changes

- `internal/web/ui/ds.css` line 721–727: changed `width: 6px; height: 6px` → `width: 8px; height: 8px` in `.ws-indicator::before`

## Acceptance Criteria

- [x] AC 1: `.ws-indicator::before` has `width: 8px; height: 8px` in `ds.css`
- [x] AC 2: Dot remains circular (`border-radius: 50%` unchanged)
- [x] AC 3: `go build ./...` passes — verified via `go vet ./... && go build ./... && go test ./internal/web/...` (ok, 3.11s)

## Verification

```
go vet ./...        → clean
go build ./...      → clean
go test ./internal/web/... → ok (3.110s)
```

## Root Cause

CSS typo: the dot dimension was set to 6px at initial implementation instead of the 8px specified in UX-002 (Pencil node `ihVJB` inside Indicator/Live component).
