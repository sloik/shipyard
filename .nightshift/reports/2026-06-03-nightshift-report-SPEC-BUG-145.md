# Nightshift Report — SPEC-BUG-145

**Spec:** SPEC-BUG-145 — Tools tab loses server-group collapse state when the selected tool changes
**Type:** bugfix (layer 3) | **Date:** 2026-06-03 | **Branch:** `nightshift/SPEC-BUG-145`
**Status:** COMPLETE

## Summary

The Tool Browser sidebar re-renders whole-innerHTML on every tool selection
(the render signature includes the selected tool). Server-group collapse state
was not preserved across that re-render. Investigation revealed a deeper issue:
**user-driven group collapse interactivity did not exist at all** in the current
code — only render-time auto-collapse for offline/restarting groups. The fix
adds (a) a persistent per-server collapse store, (b) a group-header click handler
that toggles and records state, and (c) render logic that re-applies the retained
state, while preserving offline/restarting auto-collapse.

## Files Changed

| File | Change |
|------|--------|
| `internal/web/ui/index.html` | Added `userCollapsedGroups` state map; `data-server` attr on `.tool-group`; render now ORs retained state with offline/restarting auto-collapse; new header-click branch in the `toolGroups` click handler that toggles `.is-collapsed` on the single targeted group and records the state. |
| `internal/web/ui_layout_test.go` | New regression test `TestSPECBUG145_ToolGroupCollapseStateRetainedAcrossSelection` (source-scan style matching existing Tool Browser tests). |

## Design Decisions

- **Direct DOM class toggle on click, not re-render.** The render path early-returns
  when the signature is unchanged, and collapse state is intentionally NOT in the
  signature. Toggling `.is-collapsed` directly on the one clicked group gives AC3
  isolation (other groups untouched) and instant chevron feedback (CSS rotates the
  chevron via `.is-collapsed`). On a real tool-switch the signature changes, the
  sidebar re-renders, and `renderToolSidebar` re-applies retained state from the store.
- **`data-server` on the group element** so handler and render key on server name
  cleanly instead of parsing the mixed header text (status dots + badges).
- **R4 preserved:** offline/restarting still force-collapse via
  `(!isSelf && (isOffline || isRestarting)) || userCollapsedGroups[srvName]`.
- **No backend/storage persistence** (out of scope) — state is ephemeral, lost on
  full Tools reload, exactly as specified.

## Gate Results

| Gate | Result |
|------|--------|
| `gofmt -l` (changed .go) | clean (no output) |
| `go vet ./...` | exit 0 |
| `go test ./...` | all packages `ok` (incl. `internal/web` 7.46s) |
| `go build ./...` | exit 0 |

(The `ld: warning ... built for newer macOS version` lines are benign toolchain
version-skew warnings, not build failures.)

## Acceptance Criteria

| AC | Result | Notes |
|----|--------|-------|
| AC1 — folded group(s) stay folded after selecting a different tool | PASS | render re-applies `userCollapsedGroups[srvName]` |
| AC2 — user-expanded group stays expanded after selection change | PASS | store records `false`; render only collapses when stored true (or offline/restarting) |
| AC3 — toggling one group does not change others | PASS | click toggles `.is-collapsed` on the single targeted `.tool-group[data-server]` only |
| AC4 — chevron reflects retained state after selection change | PASS | chevron is CSS-driven by `.is-collapsed`, which render re-applies |
| AC5 — regression test covers retention across selection change | PASS | `TestSPECBUG145_ToolGroupCollapseStateRetainedAcrossSelection` |
| AC6 — `go test ./...` passes | PASS | all packages ok |
| AC7 — `go vet ./...` passes | PASS | exit 0 |
| AC8 — `go build ./...` passes | PASS | exit 0 |

## Discoveries / Blockers

- **SPEC-BUG-018 was closed (`status: done`) with a "Disposition: Invalidated" note,
  but interactivity was never implemented.** The disposition claims live users saw
  groups collapse on click, but static inspection confirms no `.tool-group-header`
  click handler existed — only offline/restarting auto-collapse. The "018" entries
  in git log are SPEC-018 (Wails v3 migration), unrelated; SPEC-BUG-018 has no
  commits. Consequently SPEC-BUG-145's premise ("interactivity already exists") was
  inaccurate, and this fix had to add the toggle in addition to retention. This is
  in-bounds: adding the toggle is not in 145's Out-of-Scope list and is the minimal
  precondition for the retention ACs. No blocker.

## Suggested Follow-up Specs

- (Optional) A spec to correct/annotate SPEC-BUG-018's disposition record now that
  collapse interactivity is genuinely implemented under SPEC-BUG-145, so the spec
  history is accurate for future readers.
- (Optional, explicitly out of scope here) Persist collapse state across Tools
  reload / app restart via local storage, if users want folds to survive reloads.
