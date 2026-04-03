---
id: BUG-011
priority: 1
layer: 3
type: bug
status: done
after: []
created: 2026-03-27
---

# Gateway Response Format: Non-Dict Results Cause "Invalid response format" / "Failed to serialize result"

## Problem

Most `shipyard_gateway_call` invocations return "Invalid response format" or "Failed to serialize result" to Claude, even though the child MCP tool executes successfully (confirmed via Shipyard logs showing "done"). Only tools returning structured JSON dictionaries (e.g., `cortex_health`, `cortex_add`) work cleanly. All 12 `lmac-run` tools and most other gateway tools are unreachable from Cowork.

The bug is in ShipyardBridgeLib's response deserialization pipeline — it assumes all results are `[String: Any]` dictionaries, but MCP tool results can have other shapes (arrays, strings, wrapped content blocks that fail the cast, or the full JSON-RPC envelope leaking through from MCPBridge).

## Root Cause

There are **three fragility points** in the gateway response chain:

### Bug A: MCPBridge.routeStdoutLine — wrong fallback for non-dict results

**File:** `Shipyard/Services/MCPBridge.swift`, lines 162-168

```swift
} else if let result = json["result"] as? [String: Any] {
    continuation.resume(returning: JSONResponse(result))
} else {
    // Result might be an array or other type — wrap it
    continuation.resume(returning: JSONResponse(json))  // BUG: returns FULL JSON-RPC envelope
}
```

When `json["result"]` is not a `[String: Any]` (string, array, number, null), the fallback wraps the **entire JSON-RPC response** (including `jsonrpc`, `id`, `result` keys) as the return value. This pollutes downstream consumers with protocol envelope data. The `call()` method returns `response.dict` — so callers get `{"jsonrpc": "2.0", "id": N, "result": <actual>}` instead of just `<actual>`.

### Bug B: Handlers.handleShipyardGatewayCall — dict-only serialization

**File:** `ShipyardBridgeLib/Handlers.swift`, lines 157-168

```swift
guard let result = response["result"] else {
    return (nil, "Invalid response format")       // ← triggers when result is NSNull or absent
}

if let resultDict = result as? [String: Any],     // ← ONLY handles dicts
   let jsonData = try? JSONSerialization.data(withJSONObject: resultDict),
   let jsonStr = String(data: jsonData, encoding: .utf8) {
    return (jsonStr, nil)
}

return (nil, "Failed to serialize result")         // ← triggers for arrays, strings, numbers
```

This function hard-casts `result` to `[String: Any]`. Any non-dictionary result (array, string, number, boolean, null) falls through to "Failed to serialize result". Even when Bug A leaks the full JSON-RPC envelope (which IS a dict), the serialized output includes protocol noise.

### Bug C: Handlers error parsing — string-only check

**File:** `ShipyardBridgeLib/Handlers.swift`, line 153

```swift
if let error = response["error"] as? String {
```

The SocketServer's `errorResponse()` returns `{"error": "message string"}` — but if a child MCP's JSON-RPC error leaks through (format: `{"error": {"code": -32000, "message": "..."}}`), this cast fails silently. The error is ignored, `response["result"]` is nil, and we get "Invalid response format" instead of the actual error message.

## Requirements

- [ ] R1: `MCPBridge.routeStdoutLine` must extract the `result` field from JSON-RPC responses regardless of its type (dict, array, string, number, boolean, null), NOT wrap the entire envelope.
- [ ] R2: `Handlers.handleShipyardGatewayCall` must serialize ANY JSON-serializable result value, not only `[String: Any]` dictionaries.
- [ ] R3: `Handlers.handleShipyardGatewayCall` must handle `response["error"]` as both String (Shipyard format) and `[String: Any]` dict (JSON-RPC format).
- [ ] R4: Non-serializable edge cases must return a descriptive error rather than "Failed to serialize result".
- [ ] R5: Existing behavior for dict results (the common case) must remain unchanged — no regressions.

## Acceptance Criteria

- [ ] AC 1: A child MCP returning `{"result": {"content": [{"type": "text", "text": "hello"}]}}` works (dict — existing working case, no regression).
- [ ] AC 2: A child MCP returning `{"result": "plain string"}` is serialized and returned to Claude correctly (string result).
- [ ] AC 3: A child MCP returning `{"result": [1, 2, 3]}` is serialized and returned to Claude correctly (array result).
- [ ] AC 4: A child MCP returning `{"result": null}` returns an empty/null indicator rather than "Invalid response format".
- [ ] AC 5: A SocketServer error response `{"error": "message"}` is correctly extracted and returned as an error.
- [ ] AC 6: A JSON-RPC error `{"error": {"code": -32000, "message": "oops"}}` is correctly extracted and returned as an error.
- [ ] AC 7: The `MCPBridge.routeStdoutLine` non-dict fallback does NOT leak the JSON-RPC envelope (`jsonrpc`, `id` fields) into the returned result.
- [ ] AC 8: Build succeeds with zero errors.
- [ ] AC 9: Existing ShipyardBridgeLib tests pass (no regressions).

## Context

### Data flow (normal case):

```
Child MCP stdout → MCPBridge.routeStdoutLine() → JSONResponse.dict → MCPBridge.callTool() returns [String: Any]
  → SocketServer.handleGatewayCall() → successResponse(result) → {"result": ...} over Unix socket
  → ShipyardSocket.send() → [String: Any] → Handlers.handleShipyardGatewayCall()
  → serializes result to JSON string → MCPServer wraps in MCP content block → Claude
```

### Key files (in order of fix priority):

1. **`ShipyardBridgeLib/Handlers.swift`** — `handleShipyardGatewayCall()` (lines 146-169). Primary fix: replace `result as? [String: Any]` with generic `JSONSerialization.data(withJSONObject: result)`. Also fix error parsing (line 153) to handle dict errors.

2. **`Shipyard/Services/MCPBridge.swift`** — `routeStdoutLine()` (lines 162-168). Fix the else branch to extract `json["result"]` into a wrapper dict (e.g., `["_raw": json["result"]]`) instead of returning the full JSON-RPC envelope. OR change the return type so non-dict results are properly represented. Since `JSONResponse` wraps `[String: Any]`, a natural approach is `["_value": json["result"] ?? NSNull()]`.

3. **`ShipyardBridgeLib/MCPServer.swift`** — `handleToolCall()` (lines 374-417). No code changes expected here, but verify that the fixed result from Handlers flows correctly through the MCP content block wrapping.

### Testing approach:

- **Unit tests** in `ShipyardBridgeTests/` (SPM target, run via `swift test`):
  - Mock `ShipyardSocketProtocol` to return different response shapes
  - Test `handleShipyardGatewayCall` with dict, string, array, null, and error responses
  - Test error parsing for both string and dict error formats

- **Unit tests** in `ShipyardTests/` (Xcode target):
  - Test `MCPBridge.routeStdoutLine` with non-dict result lines
  - Verify non-dict results don't leak the JSON-RPC envelope

### Existing test infrastructure:

- `ShipyardBridgeLib/` tests are in `ShipyardBridgeTests/` (SPM: `swift test`)
- `shipyardSocket` is injectable via the `nonisolated(unsafe) var shipyardSocket` global — tests can substitute a mock
- `ShipyardSocketProtocol` defines the `send(method:params:timeout:)` contract

### Constants:

- `DEFAULT_TIMEOUT = 5.0` seconds
- `EXTENDED_TIMEOUT = 30.0` seconds (used for gateway_call)

## Fix Strategy

### Handlers.swift — handleShipyardGatewayCall (Bug B + C):

```swift
// Fix Bug C: handle both string and dict errors
if let error = response["error"] as? String {
    return (nil, error)
} else if let errorDict = response["error"] as? [String: Any],
          let errorMsg = errorDict["message"] as? String {
    return (nil, errorMsg)
}

guard let result = response["result"] else {
    return (nil, "Invalid response format")
}

// Fix Bug B: serialize ANY JSON-serializable value
if JSONSerialization.isValidJSONObject(["wrap": result]) {
    // result might not be a top-level container, so wrap it for serialization
    if let jsonData = try? JSONSerialization.data(withJSONObject: ["wrap": result]),
       let wrapper = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
       let unwrapped = wrapper["wrap"] {
        // Now re-serialize just the result
        if let resultData = try? JSONSerialization.data(withJSONObject:
            unwrapped is [String: Any] || unwrapped is [Any] ? unwrapped : ["_value": unwrapped]),
           let jsonStr = String(data: resultData, encoding: .utf8) {
            return (jsonStr, nil)
        }
    }
}

// Fallback: convert to string representation
return ("\(result)", nil)
```

**Note:** `JSONSerialization.data(withJSONObject:)` requires the top-level object to be an array or dictionary. Bare strings/numbers can't be serialized directly. The fix must handle this (wrap scalars in a container, or use String interpolation).

### MCPBridge.swift — routeStdoutLine (Bug A):

```swift
} else if let result = json["result"] as? [String: Any] {
    continuation.resume(returning: JSONResponse(result))
} else if json["result"] != nil || json.keys.contains("result") {
    // Non-dict result — wrap in a carrier dict so it survives the [String: Any] pipeline
    continuation.resume(returning: JSONResponse(["_raw_result": json["result"] ?? NSNull()]))
} else {
    // No result field at all — treat as empty
    continuation.resume(returning: JSONResponse([:]))
}
```

## Out of Scope

- Changing the `JSONResponse` type from `[String: Any]` to a richer enum (would be a larger refactor)
- Socket-level improvements (chunked reads, framing protocol)
- MCP spec compliance validation on child responses
- Response size limits or streaming
