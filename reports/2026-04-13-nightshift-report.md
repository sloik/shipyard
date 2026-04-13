# Nightshift Run Report — 2026-04-13

## Summary

| Field | Value |
|---|---|
| Spec | SPEC-BUG-026 |
| Status | done |
| Duration | ~2 min |
| Agent | Claude Sonnet 4.6 (worktree) |
| Commit | `2da31ce` |

## Files Changed

| File | Change |
|---|---|
| `internal/web/ui/index.html` | +18 lines — offline/restarting aggregate banner in `renderToolSidebar()` |
| `internal/web/ui_layout_test.go` | +32 lines — 2 regression tests |
| `.nightshift/specs/SPEC-BUG-026-*.md` | status: ready → done |

## Test Results

```
go build ./...   PASS
go vet ./...     PASS
go test ./...    PASS  (7 packages)
```

## AC Checklist

- [x] AC1: Banner-level surface shown when ≥1 server offline/restarting
- [x] AC2: Aggregate message communicates state ("N servers offline, M restarting")
- [x] AC3: Banner absent when all servers online (gated by `offlineCount > 0 || restartingCount > 0`)
- [x] AC4: Regression tests added (`TestSPECBUG026_OfflineBannerMarkupBuilt`, `TestSPECBUG026_OfflineBannerGatedByCount`)
- [x] AC5: `go test ./...` passes
- [x] AC6: `go vet ./...` passes
- [x] AC7: `go build ./...` passes

## Discoveries

- None. Straightforward addition after the server group loop in `renderToolSidebar()`.
- Pattern mirrors existing conflict banner (top of sidebar); this banner sits at the bottom.

## Protocol Deviations

- Human review report was not written by the agent at run time. Written retroactively by parent session.

---

## SPEC-BUG-027

| Field | Value |
|---|---|
| Spec | SPEC-BUG-027 |
| Status | done |
| Duration | ~3 min |
| Agent | Claude Sonnet 4.6 (worktree) |
| Commit | `beb9ab9` |

## Files Changed

| File | Change |
|---|---|
| `internal/web/ui/ds.css` | +4 lines — `.server-card.is-restarting { border-color: var(--warning-fg); }` |
| `internal/web/ui/index.html` | +58 lines — dedicated restarting card branch in `renderServerCards()` |
| `internal/web/ui_layout_test.go` | +61 lines — 3 regression tests |
| `.nightshift/specs/SPEC-BUG-027-*.md` | status: ready → done |

## Test Results

```
go build ./...   PASS
go vet ./...     PASS
go test ./...    PASS  (7 packages)
```

## AC Checklist

- [x] AC1: Restarting card renders header pill (72XWK: warning pill top-right, not footer badge)
- [x] AC2: Centered waiting body (xdMRZ: spinner + "Waiting for process to start...")
- [x] AC3: Warning border via `.server-card.is-restarting` class (`var(--warning-fg)`)
- [x] AC4: 3 regression tests added (`RestartingCardHasIsRestartingClass`, `RestartingCardHasPill`, `RestartingCardHasCenteredBody`)
- [x] AC5: `go test ./...` passes
- [x] AC6: `go vet ./...` passes
- [x] AC7: `go build ./...` passes

## Discoveries

- The mini pill spinner (10px, warning-fg) reuses the `@keyframes spin` animation already defined in ds.css for `.spinner::before` — no new CSS required.
- `restart_count` is preserved in the restarting body as secondary text when > 0 (gap protocol acceptable gap).
- Online/crashed/stopped card rendering is fully preserved in the `else` branch — zero regressions.

## Protocol Deviations

- Agent wrote report to `.nightshift/reports/` (gitignored) instead of `reports/`. Appended retroactively by parent session.
