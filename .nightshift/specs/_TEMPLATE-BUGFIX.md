# Bug Report Template

Copy this template to report and fix a bug. Fill in all sections. Save as `specs/BUG-NNN-short-title.md`.

---

```markdown
---
id: BUG-001
template_version: 2
priority: 1          # Bugs default to priority 1 (highest). Deprioritize only if explicitly deferred.
layer: 2             # Layer of the feature that contains the bug
type: bugfix
status: draft        # draft | ready | in_progress | done | blocked
after: []            # Soft dependencies: list of spec IDs (if any)
violates: [SPEC-XXX] # REQUIRED: list of spec IDs this bug violates (e.g., [SPEC-012, SPEC-015])
prior_attempts: []   # Previous attempts to fix this bug (e.g., [BUG-001-sqlite-memory-leak])
created: 2026-03-26
---

# [Title: One-Line Description of the Bug]

## Problem

What is the bug? What does the user experience? Why does it matter?

**Violated spec:** SPEC-XXX (name)
**Violated criteria:** AC N — description of what should happen but doesn't

Example:
> When the JSON editor displays a validation error, the editor area bounces/resizes. This is jarring for users and violates the spec's requirement that the UI should be stable during validation.

**Violated spec:** SPEC-010 (JSON Editor & Response Viewer)
**Violated criteria:** AC 3 — editor should be usable without jarring layout shifts

## Reproduction

Step-by-step instructions to reproduce the bug. Include:
- Initial state
- Actions the user takes
- What they see (actual behavior)
- What they expected to see (desired behavior)

Example:
1. Open Gateway tab → click ▶ on any tool → JSON tab
2. Type valid JSON: `{ "file": "test" }` — editor is stable
3. Delete the closing `}` — error message appears: "Invalid JSON: ..."
4. **Actual:** Editor area visibly shrinks when error appears (jars the view)
5. **Expected:** Error message appears without changing the editor size

## Root Cause

**Leave blank.** The implementation agent investigates and fills this in during the
Nightshift run. Do NOT include root cause hypotheses, fix suggestions, or solution
strategies in the bug spec — that is the agent's job, not the spec author's.

## Requirements

Specific, testable requirements for the fix. Each maps to one or more acceptance criteria below.

- [ ] Requirement 1
- [ ] Requirement 2
- [ ] Requirement 3

Example:
- [ ] The validation error area has fixed, reserved height
- [ ] Toggling between valid/invalid JSON does NOT resize the editor frame
- [ ] Error area remains accessible (readable, clickable) at all times

## Acceptance Criteria

Concrete, verifiable conditions. These become test cases. **Always include:** "the violated AC from the parent spec now passes."

- [ ] AC 1: Typing valid JSON, then invalid, then valid again does NOT cause editor resize
- [ ] AC 2: Error area has fixed height (24–30pt), always reserved (empty when no error)
- [ ] AC 3: The violated AC from SPEC-XXX (AC N) now passes
- [ ] AC 4: No regressions — all existing tests pass
- [ ] AC 5: Tests cover: valid JSON, invalid JSON, toggle cycle, empty input, large objects

## Context

Relevant background, links to the violated spec, pointers to code that contains the bug.

- See spec: [SPEC-010](../specs/SPEC-010-json-editor.md) — what the editor is supposed to do
- Bug occurs in: `src/components/JsonEditor.tsx` (lines 45–60)
- Related code: `src/hooks/useValidation.ts` — validation error logic
- Existing test fixtures: `src/__tests__/fixtures/jsonSamples.json`

## Out of Scope

What this bug fix does NOT cover.

- Improving error message wording (future)
- Syntax highlighting in the editor (separate spec)
- Validation performance optimization (future spec)

## Code Pointers

File paths and line numbers where the bug manifests. **No fix suggestions** — just
point the agent to the right files. The agent reads the code and investigates.

- Bug area: `path/to/file.ext` (lines N–M)
- Related code: `path/to/other.ext`
- Test file: `path/to/test_file.ext`
- Violated spec: `specs/SPEC-XXX-name.md`

## Gap Protocol

Optional — defaults to standard gap protocol (see Nightshift-Coordinator-And-Observability.md Section 3.3).

- Research-acceptable gaps: [e.g., "understanding layout behavior", "existing CSS patterns"]
- Stop-immediately gaps: [e.g., "root cause unclear after investigation", "fix requires API change"]
- Max research subagents before stopping: 3 (default)
```

---

## Filing a Bug Report

### File Naming

- Save as `specs/BUG-NNN-short-title.md`
- Example: `specs/BUG-001-json-editor-bounces.md`
- Use the bug ID in the filename for easy lookup
- **Note:** Bug IDs use `BUG-NNN` format, not `SPEC-NNN`, to distinguish them from feature/refactor specs

### Setting Priority

Bugs default to priority 1 (highest). Only deprioritize if:

- The bug affects an edge case that rarely occurs
- The workaround is simple and well-known
- The fix would take longer than the impact justifies

In those rare cases, set priority 2–5 explicitly and document the reasoning in the spec.

**Key principle:** Every bug violates an existing spec's acceptance criteria. If it violates the spec, it's high-priority by default.

### The `violates:` Field (REQUIRED)

Every bug must list the spec IDs it violates:

```yaml
violates: [SPEC-010]        # Single spec
violates: [SPEC-010, SPEC-015]  # Multiple specs
```

This field is mandatory. A bug without a parent spec is a smell — either:

1. The original spec was incomplete (AC should have caught this)
2. The bug is actually a new feature request (should be filed as SPEC-NNN instead)
3. There's a missing spec (write it first, then file the bug against it)

### Spec Without Parent = Write the Parent First

If you find a bug but the relevant spec doesn't exist, **don't file a bug spec**. Write the feature spec first. Once that spec is done, then if there's still a gap between spec and implementation, file the bug against it.

This enforces: **Specs are the source of truth.** Bugs reference specs. If there's no spec, there's no clear definition of "broken," so write the spec first.

### Setting Layer

Use the same layer as the feature that contains the bug. Example:

- Bug in Layer 2 feature → Layer 2 bug
- Bug in Layer 0 foundation → Layer 0 bug

Layer determines when the bug gets fixed (relative to other work). Foundation bugs take priority over feature bugs.

### After Selecting from Task Queue

The selection algorithm in LOOP.md prioritizes bugs first (by type == "bugfix"), then by layer, then by priority. So a Layer 2 bug with priority 5 will be selected before a Layer 2 feature with priority 1.

---

## Example: Complete Bug Spec

```markdown
---
id: BUG-002
template_version: 2
priority: 1
layer: 2
type: bugfix
status: ready
after: [SPEC-012]
violates: [SPEC-012]
prior_attempts: []
created: 2026-03-26
---

# JSON Editor Bounces When Validation Error Appears/Disappears

## Problem

In the Tool Execution Sheet's JSON tab (SPEC-010/012), the text editor area resizes vertically when the validation error message appears or disappears. This causes the content to jump/bounce, which is jarring for users.

**Violated spec:** SPEC-012 (JSON Editor & Response Viewer)
**Violated criteria:** AC 3 — the editor should be usable without jarring layout shifts. AC 6 — validation display shouldn't cause layout instability.

## Reproduction

1. Open Gateway tab → click ▶ on any tool → JSON tab
2. Type valid JSON: `{ "file": "test" }` — no error shown
3. Delete the closing `}` — error appears: "Invalid JSON: ..."
4. **Actual:** Editor area visibly shrinks/bounces when error appears
5. **Expected:** Error message appears without changing editor size
6. Re-add `}` — error disappears, editor bounces again (same problem in reverse)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Validation message area has fixed reserved space
- [ ] R2: Editor frame does not change when validation state changes
- [ ] R3: Error is always visible when present

## Acceptance Criteria

- [ ] AC 1: Typing valid → invalid → valid JSON does NOT cause editor resize
- [ ] AC 2: Error area has fixed height (24–30pt), always reserved
- [ ] AC 3: AC 3 and AC 6 from SPEC-012 now pass
- [ ] AC 4: Build succeeds; all tests pass
- [ ] AC 5: No regressions — pre-existing JSON editor tests still pass

## Context

- See spec: [SPEC-012](../specs/SPEC-012-json-editor-response.md)
- Bug occurs in: `src/components/sheets/ToolSheet/JsonEditor.tsx` (lines 40–75)
- Error rendering: `src/components/ErrorDisplay.tsx`
- Test file: `src/__tests__/JsonEditor.test.tsx`

## Out of Scope

- Improving error message wording (future)
- Error styling/colors (design task)
- Syntax highlighting (separate feature)

## Code Pointers

- Bug area: `src/components/sheets/ToolSheet/JsonEditor.tsx` (lines 40–75)
- Related code: `src/components/ErrorDisplay.tsx`
- Test file: `src/__tests__/JsonEditor.test.tsx`
```

---

## Checklist Before Marking as "ready"

- [ ] Bug clearly references the violated spec (`violates:` field)
- [ ] Reproduction steps are clear and include expected vs actual behavior
- [ ] Requirements map to acceptance criteria
- [ ] AC includes "the violated AC from the parent spec now passes"
- [ ] AC includes "no regressions"
- [ ] Layer is set correctly (same as feature containing the bug)
- [ ] Priority is 1 unless explicitly deprioritized with reasoning
- [ ] Context includes links to the spec and relevant code files
- [ ] Out of scope section is filled (prevent scope creep)
- [ ] Someone reviewed the bug report for clarity (optional but recommended)

---

> A well-written bug report is the difference between a 5-minute fix and a 5-hour investigation.
