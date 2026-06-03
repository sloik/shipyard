# Nightshift Report — SPEC-BUG-148 (inline, parent-implemented)

**Date:** 2026-06-03
**Spec:** SPEC-BUG-148 — Tools tab: clicking expand/collapse on a group does not update the UI until a different tool is selected
**Outcome:** DONE (fixed, behaviorally verified)
**Mode:** Implemented inline by the parent after two background kickoff runs failed to API stream-idle timeouts (infra). User authorized inline implementation.

## Root cause (proven, not inferred)

Two handlers toggled `is-collapsed` on every group-header click, cancelling out:

1. `internal/web/ui/ds.js` — `handleToolGroupClick()` (Design System runtime, SPEC-005), wired at the **document** level. The *original, persistence-less* collapse toggle.
2. `internal/web/ui/index.html` — the SPEC-BUG-145 handler on `#tool-groups`, which toggles AND records `userCollapsedGroups` + persists (SPEC-BUG-147).

A single header click fired both → toggle on then off → **no visible change**. But the index.html handler still recorded `userCollapsedGroups`, so the next tool-selection re-render *did* render the fold — exactly the reported "switch tool then it refreshes."

Proven via headless-Chrome stack traces against the live `:9417`:
- `at HTMLDivElement.<anonymous> (index.html:2982)` — the 145 handler
- `at handleToolGroupClick (ds.js:311)` ← `at HTMLDocument.<anonymous> (ds.js:447)` — the ds.js duplicate

This also resolves the long-standing contradiction across 145/146/148: groups *were* foldable before 145 (via ds.js), they just weren't *retained* — which is precisely what SPEC-BUG-145 was filed to fix. 145 should have only *added persistence on top of ds.js's existing toggle*; instead it re-implemented the toggle, creating the duplication.

Why source-scan tests (145/147) reported 8/8 while the behavior was broken: they assert strings exist in `index.html`; they cannot see that `ds.js` *also* toggles. This bug class is invisible to source-scan.

## Fix

Single-owner: `index.html`'s handler (toggle + persist + render integration) is the sole owner. Removed the duplicate, persistence-less collapse handling from `ds.js`:
- Removed the document-level `.tool-group-header` delegation branch (replaced with an explanatory comment).
- Removed the now-orphaned `handleToolGroupClick()` function.

Safe because there is a single frontend: `index.html` loads `/ds.js` (verified), and `.tool-group` is rendered only inside `#tool-groups` with a single `handleToolGroupClick` caller — so the index.html handler is present wherever ds.js is (incl. the detachable Tools popout window, which loads the same index.html).

## Files changed

- `internal/web/ui/ds.js` — removed duplicate collapse handler (+3/−16)
- `internal/web/ui_layout_test.go` — new `TestSPECBUG148_SingleToolGroupCollapseToggleOwner`
- `.nightshift/specs/SPEC-BUG-148-...md` — root cause + status

`internal/web/ui/index.html` deliberately UNCHANGED (the render-time offline auto-collapse and the 145/147 handler are correct and stay the sole owner).

## Gates

- `gofmt -l`: clean
- `go vet ./...`: exit 0
- `go test -count=1 ./...`: all packages `ok` (incl. `internal/web`)
- `go build ./...`: exit 0
- SPEC-BUG-145 and SPEC-BUG-147 tests: still PASS (no regression)

## Acceptance criteria

Verified behaviorally with a headless-Chrome reproduction against a freshly-built instance (`:9418`), driving real clicks:

- AC1 (click expanded → tools hide immediately, no tool switch): PASS — exactly **1** is-collapsed toggle, `display:none`
- AC2 (click collapsed → tools show immediately): PASS
- AC3 (chevron reflects state at click): PASS (chevron rotation is CSS-driven off `.is-collapsed`, which now toggles once)
- AC4 (after toggle, tool-switch preserves state — 145 intact): PASS
- AC5 (after toggle, persists across reload — 147 intact): PASS
- AC6 (regression test): PASS — `TestSPECBUG148_*` (source-scan, asserts the duplicate is gone; **honest note:** source-scan cannot prove the runtime behavior — that is what the headless-Chrome matrix above proves)
- AC7/AC8/AC9 (`go test`/`go vet`/`go build`): PASS
- R5 (offline/restarting auto-collapse not regressed): structurally preserved — the fix is isolated to `ds.js`'s click handler; `index.html`'s render-time auto-collapse is byte-identical (git diff shows index.html unchanged). Not exercised behaviorally because the synthetic offline server reported `status:"online"` to the API; covered by the unchanged render condition + existing offline-state tests.

## Notes / lessons

- The real verification was behavioral (headless Chrome). The CI source-scan tests are the same methodology that gave 145/147 false greens here; the new test guards against the duplicate returning but is not proof of behavior.
- Scope: this corrected 145's overreach (re-implementing a toggle ds.js already had) without re-litigating 145.

## Suggested Follow-up Specs

- (Optional) Shipyard has no browser/DOM test harness, so interactive-UI regressions (like this double-toggle) escape the Go source-scan suite. Consider a lightweight headless-browser smoke test (Playwright via the system Chrome) for the Tool Browser's interactive behaviors (collapse, select, toggle). This would have caught SPEC-BUG-148 at merge time.
