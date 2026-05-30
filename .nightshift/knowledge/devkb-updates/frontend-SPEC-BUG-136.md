# DevKB Update — SPEC-BUG-136
**Target file:** frontend.md
**Section:** Long-running dashboards / polling budgets
**Date:** 2026-05-30

## Entry

### Long-running vanilla dashboards need route, visibility, and DOM budgets
**Problem:** A single-page dashboard that is left open for hours can keep polling hidden routes, prepending live rows, refreshing timestamps across all historical rows, and replacing large DOM regions even when payloads are unchanged.

**Root Cause:** Timers and WebSocket handlers often start globally at bootstrap, while render functions assume short sessions and unbounded DOM growth.

**Fix:** Gate polling through active route and `document.visibilityState`, prune live DOM rows to a fixed active budget without dropping stored data, scan timestamps only up to that budget, and add render signatures that skip `innerHTML` replacement when source state is unchanged.

**Prevention:** For operational dashboards, define explicit budgets for live rows and periodic scans, make every recurring timer route/visibility-aware, and record telemetry for row counts, render duration, and skipped renders.
