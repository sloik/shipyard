# DevKB Update — SPEC-BUG-139
**Target file:** frontend.md
**Section:** Vanilla dashboard controls / composed filter bars
**Date:** 2026-05-30

## Entry

### Keep composed controls wired through stable behavior classes
**Problem:** A shared dashboard JSON filter needed a new visual composition
while preserving existing Text/JQ behavior for two viewers and leaving
per-panel filters independent.

**Root Cause:** The same `.json-filter` class carried both behavior ownership
and visual capsule styling. Changing it directly would risk either preserving
the old look or breaking query selectors used by filter wiring.

**Fix:** Keep the behavior-bearing outer element as `.json-filter` and add a
more specific composition class (`.json-filter-bar`) that resets container
styling. Put visual styling on child elements such as `.json-filter-input`,
`.json-filter-spacer`, and `.json-filter-match-count`.

**Prevention:** For vanilla JS dashboards, separate behavior classes from
presentation classes when restyling shared controls. Regression tests should
assert both DOM structure and selector contracts for shared vs per-panel
control instances.
