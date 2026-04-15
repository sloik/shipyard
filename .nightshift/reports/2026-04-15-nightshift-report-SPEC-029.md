# Nightshift Report — SPEC-029

**Date:** 2026-04-15
**Spec:** SPEC-029 Toggle Behavior, Gateway Integration & MCP Compliance
**Status:** Done
**Commit:** feat(SPEC-029): toggle sync, MCP compliance, built-in tool toggles

---

## Summary

SPEC-029 fixed behavioral gaps left by SPEC-028: toggle sync correctness, MCP protocol compliance (error codes, capabilities), and Shipyard built-in tool toggleability.

## Changes Made

### Go — MCP Protocol Compliance

**R7: `listChanged: true` in initialize responses**
- `internal/auth/middleware.go`: Changed `listChanged: false` → `true`
- `cmd/shipyard-mcp/main.go`: Same change in the bridge's initialize handler

**R10: `-32602` error code for disabled tools**
- `internal/auth/middleware.go`: Changed `-32601` "disabled" message → `-32602` "Unknown tool: {name}" for both server-disabled and tool-disabled cases
- Also added shipyard tool-level gateway policy check in the auth path (was previously only in passthrough path)
- `internal/web/server.go`: Same error code change in the passthrough (`handleMCPPassthrough`) path

**R9: Verified** — `tools/list` exclusion of disabled tools was already correctly implemented by SPEC-028. No changes needed.

**R8/R11/R13: `notifications/tools/list_changed`** — Architecture limitation noted. The MCP transport is HTTP stateless (POST /mcp), so proactive server-to-client notifications are not possible without SSE. Setting `listChanged: true` is the correct signal; clients will re-fetch on their next `tools/list` call. The WebSocket hub already broadcasts `toggle_changed` to browser UI clients. A future spec would add SSE transport to enable real MCP notifications.

### JavaScript/HTML — UI Changes

**R12: Shipyard built-in tool toggles**
- Removed the `is_self` guard that blocked toggle buttons for Shipyard's own tools
- Added `canToggleTool = isSelf || srvEnabledState` logic — is_self tools always have functional toggles (their server is always enabled)
- Detail panel toggle now shows for all tools including is_self (no `style.display='none'` for isSelf)

**R1: Sidebar ↔ detail panel sync without re-render**
- `toggleDetailPanelTool()` now uses `document.querySelector('[data-server="..."][data-tool="..."]')` to find and update the sidebar button directly, eliminating the `renderToolSidebar()` re-render call

**R2: WebSocket `toggle_changed` targeted DOM updates**
- Server toggle: updates in-memory state, re-renders sidebar (necessary — all rows change opacity), also updates detail panel in-place if current tool is on that server
- Tool toggle: finds the sidebar button by data attributes and updates classes/opacity directly; falls back to full re-render only if button not found

**R3: Optimistic UI with toast on failure**
- Both `toggleTool()` and `toggleDetailPanelTool()` now call `showToast('Failed to update toggle', 'error')` on API failure before reverting state
- Added `showToast()` function and `#toast-container` HTML element (CSS already existed in ds.css)

**R4/R5/R6: Disabled tool detail panel visual state**
- Added `#disabled-tool-banner` element between conflict section and parameters
- Added `updateDetailPanelDisabledState(effectiveEnabled, serverEnabled, isSelf)` function
- Banner shows "This tool is disabled. Enable it to execute." for tool-level disable
- Banner shows "Server is disabled. Enable the server first." for server-level disable
- Execute button label changes to "Tool Disabled" when disabled (was hint text only)
- Form inputs (`input`, `textarea`, `select`) get `disabled` attribute when tool is disabled
- State applied both at initial render and via WebSocket `toggle_changed` events (R5)

**CSS**
- Added `.disabled-tool-banner` to `ds.css`: warning-style banner with `var(--warning-fg)` border and text

### Tests

**Updated SPEC-028 tests** (3 tests changed to match new behavior):
- `TestSPEC028_GatewayErrorOnDisabledToolCall`: expects -32602 + "Unknown tool" (was -32601 + "disabled")
- `TestSPEC028_GatewayErrorOnDisabledServerCall`: same
- `TestSPEC028_UIExecuteButtonDisabledHint`: expects "Tool Disabled" label (was "Tool is disabled" hint text)

**New SPEC-029 tests** (9 new tests):
- `TestSPEC029_GatewayInitListChangedCapability` (web/server_test.go) — documents that auth path is covered by auth test
- `TestSPEC029_GatewayDisabledToolCallReturns32602` — -32602 and "Unknown tool" from passthrough handler
- `TestSPEC029_GatewayToolsListExcludesDisabled` — disabled tool absent from tools/list
- `TestSPEC029_UIDisabledBannerPresent` — banner element + messages present in HTML
- `TestSPEC029_UIShipyardToolHasToggle` — canToggleTool variable present, old guard message absent
- `TestSPEC029_UIToastFunctionPresent` — showToast + toast-container + error message present
- `TestSPEC029_AuthInitializeListChanged` (auth/middleware_test.go) — listChanged=true in auth handler
- `TestSPEC029_AuthDisabledToolCallReturns32602` — -32602 "Unknown tool" from auth handler
- `TestSPEC029_BridgeInitializeListChanged` (cmd/shipyard-mcp/main_test.go) — listChanged=true in bridge

## Acceptance Criteria Coverage

| AC | Status | How Verified |
|---|---|---|
| AC 1 (sidebar→detail sync) | Done | Code review: direct DOM update in toggleTool() |
| AC 2 (detail→sidebar sync) | Done | Code review: querySelector in toggleDetailPanelTool() |
| AC 3 (WebSocket multi-tab) | Done | Code review: targeted WS handler |
| AC 4 (toast on failure) | Done | TestSPEC029_UIToastFunctionPresent |
| AC 5 (disabled banner on disable) | Done | TestSPEC029_UIDisabledBannerPresent |
| AC 6 (server disabled message) | Done | TestSPEC029_UIDisabledBannerPresent |
| AC 7 (re-enable restores state) | Done | Code review: effectiveEnabled path |
| AC 8 (listChanged: true) | Done | TestSPEC029_AuthInitializeListChanged, TestSPEC029_BridgeInitializeListChanged |
| AC 9 (notifications sent) | Partial | listChanged=true set; proactive push blocked by HTTP transport |
| AC 10 (tools/list excludes) | Done | TestSPEC029_GatewayToolsListExcludesDisabled |
| AC 11 (-32602 Unknown tool) | Done | TestSPEC029_GatewayDisabledToolCallReturns32602, TestSPEC029_AuthDisabledToolCallReturns32602 |
| AC 12 (re-enable notification) | Partial | Same transport limitation as AC 9 |
| AC 13 (one notification on server disable) | Partial | Same transport limitation |
| AC 14 (shipyard tool toggles work) | Done | TestSPEC029_UIShipyardToolHasToggle |
| AC 15 (shipyard tool excluded when disabled) | Done | Covered by gatewayCatalog logic (already filtered is_self tools by policy) |
| AC 16 (no server-level toggle for shipyard) | Done | handleServerEnabledPUT returns 400 for "shipyard" |
| AC 17 (shipyard tools default enabled) | Done | gateway/policy.go default=true |

## Known Gaps

**AC 9/12/13 (MCP notifications):** The `notifications/tools/list_changed` notification cannot be sent proactively over the current HTTP transport. This requires SSE or WebSocket MCP transport. The `listChanged: true` capability is correctly declared, which tells compliant clients to re-fetch `tools/list` when they notice the list may have changed. A future spec should add SSE transport to `/mcp` to enable real proactive notifications.

## Build & Test Results

```
go build ./cmd/shipyard/   ✓
go build ./cmd/shipyard-mcp/   ✓
go vet ./...   ✓
go test ./...   ✓ (all 11 packages pass)
```
