# DevKB Update — SPEC-BUG-140
**Target file:** frontend.md
**Section:** Vanilla dashboard controls / panel-local filter strips
**Date:** 2026-05-30

## Entry

### Restyle panel-local controls without changing behavior selectors
**Problem:** Traffic request/response filters needed to match a full-width
UX-002 strip with icon, bottom divider, compact typography, and local Text/JQ
toggle, but their filtering and mode state already worked independently.

**Root Cause:** The behavior-bearing `.json-filter.panel-filter` element also
inherited generic input-capsule chrome: full border, radius, larger input text,
and no icon slot. Replacing the outer class would have risked breaking existing
query selectors.

**Fix:** Keep `.json-filter.panel-filter` as the behavior hook and override its
presentation into a strip. Move the icon/input pair into a child label, add an
explicit spacer before the compact toggle, and pin the structure/CSS with
source-level UI tests.

**Prevention:** For vanilla JS dashboards, preserve selector contracts when
restyling already-wired controls. Add tests for both visual composition and
behavior ownership: icon/input/toggle order, bottom-only divider CSS, and
independent per-instance mode selectors.
