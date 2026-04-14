# Nightshift Report — SPEC-BUG-048

**Date:** 2026-04-14
**Spec:** SPEC-BUG-048 — Missing vertical separator between brand and tab navigation
**Status:** done
**Agent:** claude-sonnet-4-6

## Summary

Inserted a 1px × 20px vertical separator `<span>` between the "Shipyard" brand text and the `<nav id="tab-nav">` element in the app bar.

## Changes

- `internal/web/ui/index.html` — added separator span immediately after `<strong>Shipyard</strong>`:
  ```html
  <span style="width:1px; height:20px; background:var(--border-default); flex-shrink:0;"></span>
  ```

## Acceptance Criteria

- [x] AC 1: Separator element visible between "Shipyard" and first tab
- [x] AC 2: Separator is 1px × 20px
- [x] AC 3: Color is `var(--border-default)`
- [x] AC 4: `go build ./...` passes

## Test Results

```
go vet ./...      — clean
go build ./...    — clean
go test ./internal/web/... — ok (3.413s)
```

No existing test assertions reference the separator; no test changes were required.

## Root Cause

The separator element was missing from the HTML. The `<header class="app-bar">` transitioned directly from `<strong>Shipyard</strong>` to `<nav id="tab-nav">` with no intervening divider element.
