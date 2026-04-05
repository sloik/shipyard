---
id: BUG-004
priority: 2
type: bug
status: done
after: [SPEC-002]
created: 2026-04-05
---

# BUG-004: JSON Syntax Highlighting — Color Mismatch & Missing Differentiation

## Screenshot

`docs/phase_1_feedback/002-json-rendering-filter.png`

## Problem

JSON payloads in the timeline detail panel (split view: REQUEST + RESPONSE) do not match the design system color tokens. Observed issues:

1. **Key vs string colors too similar** — both render in very close shades of blue (`--json-key: #79c0ff` vs `--json-string: #a5d6ff`). On screen they're nearly indistinguishable, making the JSON hard to scan.
2. **Response panel coloring** — the RESPONSE panel JSON appears to render with incorrect or inconsistent colors compared to the REQUEST panel and the design spec.
3. **Tool Browser response** — the tool response JSON viewer may have the same issue; needs verification after layout fix is applied.

## Expected (from design .pen file)

The design shows distinct coloring per token type:
- **Keys:** `$json-key` — blue (#79c0ff dark / #0550ae light)
- **Strings:** `$json-string` — lighter blue (#a5d6ff dark / #0a3069 light)
- **Numbers:** `$json-number` — orange (#db6d28 dark / #953800 light)
- **Booleans:** `$json-boolean` — gold (#d29922 dark / #6639ba light)
- **Brackets:** `$json-bracket` — gray (#8b949e dark / #656d76 light)

Each type should be clearly visually distinct. The design renders each JSON line as a separate text node with explicit fill colors — the implementation uses `highlightJSON()` with `.jt-*` CSS classes.

## Root Cause Candidates

1. `highlightJSON()` regex may not be classifying tokens correctly (e.g., treating keys as strings)
2. CSS specificity — a parent container's `color` may override `.jt-*` span colors
3. The `.code-body` or `.json-viewer` base `color: var(--text-primary)` may be winning over span colors
4. Response panel may have additional CSS from traffic direction styling (`.code-header[data-res-header]`) bleeding into the body

## Acceptance Criteria

- [ ] AC-1: JSON keys render visibly distinct from string values in both REQUEST and RESPONSE panels
- [ ] AC-2: Numbers render in orange (`--json-number`), booleans in gold (`--json-boolean`)
- [ ] AC-3: Brackets/punctuation render in muted gray (`--json-bracket`)
- [ ] AC-4: Tool Browser response JSON uses identical highlighting
- [ ] AC-5: Colors match design tokens exactly (verify with browser devtools color picker)

## Target Files

- `internal/web/ui/index.html` — `highlightJSON()` function
- `internal/web/ui/ds.css` — `.jt-*` classes, `.json-viewer`, `.code-body`
