# DevKB Update — SPEC-BUG-144

**Target file:** `/Users/ed/Dropbox/Argo/DevKB/frontend.md`
**Section:** Traffic expanded detail state variants

## Proposed Entry

### Traffic expanded detail state variants need shell, panel, and control assertions

**Problem:** A traffic expanded detail can visually match the completed state while pending and error states drift: pending loses response-panel affordances, error lacks a danger-accent shell, or a resize handle changes dimensions without behavior coverage.

**Root Cause:** Source tests often pin the main completed branch but do not separately assert state-specific markup branches and control intent for empty/pending panels.

**Fix:** Add focused source-level tests for completed, pending, and error branches. Pin the row/detail shell classes, request/response header structure, active versus intentionally disabled copy controls, filter presence, resize handle dimensions, and resize event wiring.

**Prevention:** For split-view detail components, treat each visual state as a separate contract. State-specific styling should add classes to the row/detail shell while preserving the common request/response panel chrome and existing behavior hooks.
