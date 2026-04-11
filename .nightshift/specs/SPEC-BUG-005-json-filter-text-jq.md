---
id: SPEC-BUG-005
priority: 3
type: bug
status: done
after: [SPEC-002]
created: 2026-04-05
---

# SPEC-BUG-005: JSON Filter (Text/JQ Toggle) — Non-Functional in Timeline & Tool Browser

## Screenshot

`docs/phase_1_feedback/002-json-rendering-filter.png`

## Problem

The Text/JQ filter toggle appears in the timeline detail panel but is non-functional:

1. **Text filter mode** — the "Filter JSON..." input renders but typing in it does nothing (no filtering of visible JSON lines)
2. **JQ filter mode** — clicking "JQ" toggles the button styling but has no implementation behind it
3. **Per-panel filters** — the individual REQUEST/RESPONSE panel filter inputs (`panel-filter` class) render but are also non-functional
4. **Tool Browser** — the filter bar was missing entirely from the tool response section (added in cd84c19 but still non-functional)

## Expected Behavior

### Text Mode
- Typing in the filter input should live-filter the visible JSON lines
- Only lines containing the search string (case-insensitive) should remain visible
- Matched text should be highlighted within the JSON
- Clearing the input restores all lines

### JQ Mode (stretch)
- User enters a jq expression (e.g., `.content[0].text`, `.tools | length`)
- The JSON is filtered/transformed by the expression
- Result replaces the viewer content (or shows below)
- This may require a client-side jq implementation (e.g., jq-web/wasm) or a backend endpoint

## Acceptance Criteria

- [ ] AC-1: Text filter mode works — typing filters visible JSON lines in real time
- [ ] AC-2: Filter works independently on REQUEST and RESPONSE panels (per-panel inputs)
- [ ] AC-3: Combined filter applies to both panels simultaneously
- [ ] AC-4: Tool Browser response filter works identically
- [ ] AC-5: JQ mode — at minimum, show "JQ not yet implemented" message; ideally evaluate simple expressions

## Target Files

- `internal/web/ui/index.html` — filter event handlers, JSON line filtering logic
- `internal/web/ui/ds.js` — if filter behavior is centralized there
