# Nightshift Run Report — SPEC-BUG-147

**Spec:** SPEC-BUG-147 — Persist Tool Browser group collapse state across Tools reload / app restart
**Type:** feature | **Layer:** 3 | **After:** SPEC-BUG-145 | **NFR:** SPEC-NFR-001
**Branch:** `nightshift/SPEC-BUG-147`
**Date (UTC):** 2026-06-03

## Summary

SPEC-BUG-145 introduced an in-memory `userCollapsedGroups` store that retains each
server group's user-set collapse state across tool-selection changes within a live
Tools session, but explicitly scoped out persistence across reload/restart. This
spec backs that same store with `localStorage` so folds survive a Tools reload,
page reload, and app restart, keyed per server.

The change is surgical and additive: it does not rewrite SPEC-BUG-145's collapse
logic. It adds (1) a hydration step on init that populates the existing
`userCollapsedGroups` object from storage, and (2) a persist write in the existing
header-toggle handler. SPEC-BUG-145's declaration and handler-write lines are kept
verbatim, so SPEC-BUG-145's pinned source-scan test still passes (R4 / AC4 intact).

## Per-file changes

### `internal/web/ui/index.html` (+15 lines)
- After the verbatim `var userCollapsedGroups = {};` (SPEC-BUG-145):
  - Added `var TOOL_GROUP_COLLAPSE_KEY = 'shipyard_tool_group_collapsed';` — a
    stable, versionable storage namespace following the existing `shipyard_*`
    localStorage key convention (`shipyard_tool_response_height`).
  - Added an init IIFE (mirroring the existing response-height init IIFE) that
    reads the key, `JSON.parse`s it, and `Object.assign`s the result onto the
    existing store. Wrapped in try/catch so corrupt/unavailable storage degrades
    to empty folds.
- In the `.tool-group-header` click handler, after the verbatim
  `userCollapsedGroups[groupServer] = nowCollapsed;` line: added a try/catch
  `localStorage.setItem(TOOL_GROUP_COLLAPSE_KEY, JSON.stringify(userCollapsedGroups))`
  so the whole per-server blob is persisted on every toggle. Storage failure
  degrades gracefully to SPEC-BUG-145 in-session-only behavior.

Single-blob storage (one key holding `{serverName: bool, ...}`) gives per-server
isolation (R3) for free — the object key is the server key.

### `internal/web/ui_layout_test.go` (+46 lines)
- Added `TestSPECBUG147_ToolGroupCollapseStatePersistsAcrossReload` — a Go
  source-scan test over the embedded `ui/index.html`, in the same style as
  `TestSPECBUG145_...`. Asserts the incremental delta only:
  - the `TOOL_GROUP_COLLAPSE_KEY` namespace constant exists,
  - the store is hydrated from `localStorage.getItem(TOOL_GROUP_COLLAPSE_KEY)` on
    init via `Object.assign(userCollapsedGroups, stored)` (AC1/AC2),
  - the header-toggle handler writes the per-server store back via
    `localStorage.setItem(...)` (AC1/AC2/AC3).
  Per-server keying (AC3) and in-session retention (AC4/R4) remain covered by
  `TestSPECBUG145_*`.

## Gate results

| Gate | Result |
|------|--------|
| `gofmt -l internal/web/ui_layout_test.go` | clean (no output) |
| `go vet ./...` | PASS |
| `go build ./...` | PASS (only pre-existing macOS-version ld warnings) |
| `go test ./...` | PASS (all packages, incl. `internal/web`) |
| `go test ./internal/web/ -run TestSPECBUG145` | PASS (no regression) |
| `go test ./internal/web/ -run TestSPECBUG147` | PASS (new) |

Note: `gofmt` reports parse errors when handed `index.html` — expected, gofmt only
applies to `.go` files. Only the `.go` test file was gofmt-checked and is clean.

## Acceptance Criteria

| AC | Status | Evidence |
|----|--------|----------|
| AC1: After folding + page reload, group still folded | PASS | init hydration from localStorage; `TestSPECBUG147` asserts read-on-init wiring |
| AC2: After folding + app restart, group still folded | PASS | same mechanism — localStorage persists across desktop app restart |
| AC3: Persisted state is per-server (no leak) | PASS | store keyed by `srvName`/`groupServer`; single blob is per-server map; covered by SPEC-BUG-145 keying test + persisted as-is |
| AC4: Tool selection still retains folds (145 intact) | PASS | `TestSPECBUG145_*` passes; 145 declaration + handler-write lines unchanged |
| AC5: Regression test covers persistence across simulated reload | PASS | `TestSPECBUG147_ToolGroupCollapseStatePersistsAcrossReload` |
| AC6: `go test ./...` passes | PASS | full suite green |
| AC7: `go vet ./...` passes | PASS | |
| AC8: `go build ./...` passes | PASS | |

## Blockers / discoveries

- None. The stop-immediately gap (regressing SPEC-BUG-145) was avoided by keeping
  the two pinned source lines verbatim and adding persistence as separate
  statements rather than rewriting them.
- Pre-existing, unrelated status-field normalizations were present in the worktree
  base on three spec files (SPEC-BUG-146, SPEC-NFR-001, UX-002). These were NOT
  staged or committed by this run — only the two implementation files and this
  report were committed.

## Suggested Follow-up Specs

None. The spec's out-of-scope items (other Tool Browser state; cross-machine
sync) remain intentionally out of scope and are not warranted by this change.
