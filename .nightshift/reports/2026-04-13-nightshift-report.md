# Nightshift Report — 2026-04-13

---

## SPEC-BUG-027: Servers view restarting card does not match approved state

**Date:** 2026-04-13
**Spec:** SPEC-BUG-027
**Status:** done
**Model:** claude-sonnet-4-6

---

### Summary

| Field | Value |
|-------|-------|
| Spec | SPEC-BUG-027 |
| Type | bugfix |
| Files changed | 3 |
| Tests added | 3 |
| Build | pass |
| Vet | pass |
| Test | pass |

---

### Files Changed

- `internal/web/ui/ds.css` — added `.server-card.is-restarting { border-color: var(--warning-fg); }` after the `is-crashed` rule (AC3)
- `internal/web/ui/index.html` — `renderServerCards()`: added `is-restarting` class branch to card class assignment; wrapped existing card body in `else` branch; added dedicated restarting card composition with warning-bordered header (name + dot on left, 72XWK pill on right), and xdMRZ centered waiting body with spinner + "Waiting for process to start..." text (AC1, AC2, R1, R2, R3)
- `internal/web/ui_layout_test.go` — added 3 tests under `// SPEC-BUG-027` block (AC4)

---

### Test Results

```
ok  github.com/sloik/shipyard/cmd/shipyard       5.136s
ok  github.com/sloik/shipyard/internal/web       2.322s
(all other packages cached/pass)
```

---

### AC Checklist

- [x] AC1: Restarting server card renders a state-specific header pill (border-radius:100px, warning-subtle background) — not only a footer badge
- [x] AC2: Restarting card includes centered waiting body with "Waiting for process to start..." text
- [x] AC3: Restarting state uses warning border (`is-restarting` class → `border-color: var(--warning-fg)`)
- [x] AC4: Regression tests cover restarting-card rendering (3 tests added)
- [x] AC5: `go test ./...` passes
- [x] AC6: `go vet ./...` passes
- [x] AC7: `go build ./...` passes

---

### Discoveries

- The old restarting code path was entirely inside the actions row as `<span class="badge badge-warning">Restarting...</span>`. No class on the card, no separate header, no body treatment.
- The `@keyframes spin` animation was already present in ds.css (used by `.spinner::before`), so the mini pill spinner reuses it at no cost.
- The existing `statusDot` variable (computed for all states) is unused in the restarting branch — this is intentional; the restarting header builds its own inline dot.
- Restart count secondary text in the waiting body is gated on `s.restart_count > 0`, consistent with the spec's acceptable gap note.

---

## SPEC-BUG-015: Desktop Servers view stays empty despite /api/servers returning data

**Date:** 2026-04-13
**Spec:** SPEC-BUG-015
**Status:** done
**Model:** claude-sonnet-4-6

---

### Summary

| Field | Value |
|-------|-------|
| Spec | SPEC-BUG-015 |
| Type | bugfix |
| Files changed | 3 |
| Tests added | 3 new + 1 updated |
| Build | pass |
| Vet | pass |
| Test | pass |

---

### Files Changed

- `internal/web/ui/index.html` — Option A: fixed `resolveAPIURL()` stub to prefix `desktopBridgeConfig.api_base` when available, making desktop API fetches absolute (`http://127.0.0.1:PORT/api/servers`) instead of relative; Option B: updated `loadServers()` catch handler to surface fetch errors in the `#servers-empty` `.empty-desc` element instead of failing silently
- `internal/web/ui_layout_test.go` — updated `TestSPECBUG016_DesktopBridgeConfigBootstrap` to check for `desktopBridgeConfig.api_base` instead of the old `return path;` stub; added 3 new tests under `// SPEC-BUG-015` block (AC4)
- `.nightshift/specs/SPEC-BUG-015-desktop-servers-view-stays-empty-despite-api-data.md` — status set to `done`, Implementation Notes updated with full account of both attempts

---

### Test Results

```
ok  github.com/sloik/shipyard/cmd/shipyard       4.976s
ok  github.com/sloik/shipyard/internal/web       2.393s
(all other packages cached/pass)
```

---

### AC Checklist

- [x] AC1: `resolveAPIURL()` now uses `desktopBridgeConfig.api_base` to build absolute URLs for desktop fetches
- [x] AC2: In desktop mode with non-empty `/api/servers`, `loadServers()` hides `#servers-empty` and shows `#servers-grid` + `#servers-action-bar`
- [x] AC3: Empty state shown only when `/api/servers` is truly empty
- [x] AC4: 3 new regression tests added (LoadServersHidesEmptyState, LoadServersShowsEmptyState, ResolveAPIURLUsesApiBase)
- [x] AC5: Implementation Notes updated with full account of attempt 1 (pointerup hook, disproved), attempt 2 (resolveAPIURL fix, primary fix), and Wails webview nuance
- [x] AC6: `go test ./...` passes
- [x] Live validation required: Łukasz must test in the built Wails app to confirm the fix resolves the Servers view populating correctly

---

### Root Cause

`resolveAPIURL(path)` was an unfinished stub that always returned `path` unchanged. In Wails v2 on macOS, the webview uses a custom URL scheme (not `http:`), so `usesDesktopAssetOrigin()` returns `true` and `appFetch` routes through `loadDesktopBridgeConfig()` → `resolveAPIURL()`. With the stub, relative URLs like `/api/servers` would be resolved against the custom scheme origin, which is unreliable.

By contrast, WebSocket URLs already used `resolveWebSocketURL()` which correctly read `desktopBridgeConfig.ws_base` and built absolute `ws://127.0.0.1:PORT` URLs. The fix mirrors this pattern for API fetches: `resolveAPIURL()` now reads `desktopBridgeConfig.api_base` and builds `http://127.0.0.1:PORT/api/servers`.

### Discoveries

- The `pointerup` same-route refresh hook (Attempt 1) is still present as a cheap guard and is not harmful, but it did not address the underlying fetch failure.
- The `resolveAPIURL` → `resolveWebSocketURL` asymmetry was the key diagnostic clue. Both functions exist for the same purpose; only the WebSocket version was implemented.
- Silent `console.error` in `loadServers().catch()` meant failures were completely invisible in Wails (no developer console accessible to users). Option B fix surfaces errors in the empty-state UI element.
