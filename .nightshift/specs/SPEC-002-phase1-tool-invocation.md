---
id: SPEC-002
priority: 2
type: main
status: done
after: [SPEC-001]
created: 2026-04-04
---

# Phase 1: Traffic Timeline + Tool Invocation

## Problem

Phase 0 shows traffic passively. Developers still can't call a tool directly — the #1 MCP developer pain point. They must craft LLM prompts and hope the model picks the right tool.

## Goal

Add tool discovery and direct invocation to the web dashboard. Developers can browse available tools, see their schemas, fill in a form, and execute — no LLM required.

## Key Features

1. **Tool browser** — discover tools from connected servers via `tools/list`, display in sidebar grouped by server
2. **Schema-driven forms** — render JSON Schema as HTML form fields (string, number, boolean, enum, object, array)
3. **Direct execution** — send `tools/call` to the child MCP, display response in the dashboard
4. **Execution appears in traffic timeline** — UI-initiated calls are captured alongside passive traffic

## Acceptance Criteria

- [ ] AC-1: Dashboard sidebar lists all tools from all connected servers, grouped by server name
- [ ] AC-2: Clicking a tool shows its description and input schema
- [ ] AC-3: Form fields generated from JSON Schema — text inputs for strings, checkboxes for booleans, dropdowns for enums
- [ ] AC-4: "Execute" button sends `tools/call` to the correct child server and displays the response
- [ ] AC-5: Execution appears in the traffic timeline like any other call
- [ ] AC-6: Errors from the child server are displayed clearly (not swallowed)
- [ ] AC-7: Tool list refreshes when a server restarts or tools change

## Out of Scope

- Request replay (Phase 2)
- Saved request collections (deferred)
- Environment variable templating (deferred)
