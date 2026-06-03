# Nightshift Report — SPEC-BUG-146

**Spec:** SPEC-BUG-146 — Correct SPEC-BUG-018's disposition record (group collapse interactivity now exists)
**Type:** refactor (layer 3, record-only) | **Date:** 2026-06-03 | **Branch:** `nightshift/SPEC-BUG-146`
**Status:** COMPLETE

## Summary

SPEC-BUG-018 was closed `done` with a "Disposition: Invalidated" note claiming
Tool Browser server groups already expand/collapse on click. SPEC-BUG-145's run
established by static code inspection that this was factually wrong — before
SPEC-BUG-145 there was no `.tool-group-header` click handler and online groups
had no user-driven collapse path (only offline/restarting auto-collapse). This
record-only spec adds a dated correcting annotation to SPEC-BUG-018, preserving
the original disposition text additively and pointing to SPEC-BUG-145 (where
user-driven collapse was actually implemented) and SPEC-BUG-147 (cross-reload
persistence). No code or test changes.

## Exact Annotation Added

Inserted into `.nightshift/specs/SPEC-BUG-018-tool-browser-groups-not-collapsible.md`,
directly after the existing `## Disposition` paragraph (original text untouched):

```markdown
## Disposition Correction (2026-06-03, SPEC-BUG-146)

The "Invalidated — groups already collapse on click" disposition above was
**inaccurate** and is corrected here additively (the original text is preserved
for the historical record).

SPEC-BUG-145 established, by static code inspection of the Tool Browser
frontend, that before that fix there was **no `.tool-group-header` click
handler** and online groups had **no user-driven collapse path** — the only
Tools sidebar click handler targeted `.tool-item`, and `.is-collapsed` was
applied only at render time for offline/restarting groups (auto-collapse). The
reported bug in this spec was therefore real; user-driven expand/collapse did
not exist when this spec was marked invalidated.

User-driven group-collapse interactivity (the header-click toggle, per-server
collapse state, and chevron reflecting that state) was actually implemented by
**SPEC-BUG-145**, which is the authoritative record of the implemented behavior.
Cross-reload persistence of that collapse state is tracked separately by
**SPEC-BUG-147**.

This correction annotates the historical record only; it makes no code or test
changes and does not re-open or re-run this spec.
```

## Acceptance Criteria

| AC | Result | Notes |
|----|--------|-------|
| AC1 — SPEC-BUG-018 contains an annotation correcting the disposition and referencing SPEC-BUG-145 | PASS | Dated `## Disposition Correction` block added; references SPEC-BUG-145 and SPEC-BUG-147. |
| AC2 — No code or test changes (record-only) | PASS | `git diff --stat main..nightshift/SPEC-BUG-146` shows only the SPEC-BUG-018 markdown + this report. No `.go`/`.html`/`.css`/`.js`/test files. |

## Requirements

- R1 (SPEC-BUG-018 reflects that its disposition was inaccurate, pointing to SPEC-BUG-145): satisfied by the annotation.
- R2 (SPEC-BUG-145 remains authoritative; this only annotates the historical record): satisfied — original text preserved, annotation additive, no behavior/spec re-run.

## Gate Results

| Gate | Result |
|------|--------|
| `go vet ./...` | exit 0 |
| `go test ./...` | exit 0 (all packages `ok`) |
| `go build ./...` | exit 0 |

(Benign `ld: warning ... built for newer macOS version` toolchain version-skew
lines appear but are not build failures.)

## Note on unrelated worktree state

The worktree's working tree already contained two unrelated, uncommitted spec
status-normalization changes that were NOT made by this spec and were left
uncommitted (not staged):

- `.nightshift/specs/SPEC-NFR-001-zero-data-races.md` — `status: ongoing` → `status: active`
- `.nightshift/specs/UX-002-dashboard-design.md` — `status: in-progress` → `status: active`

These appear to be a board/kit status-normalization process. Staging was done
explicitly by path (`git add -f <file>`), never `git add -A`/`-a`, so these two
files are excluded from this spec's commits and do not affect the AC2 proof
(which compares commits via `main..branch`, not the working tree).

## Suggested Follow-up Specs

None. (SPEC-BUG-147 already tracks cross-reload persistence of collapse state.)
