# SPEC-019 Review Findings

**Date:** 2026-03-27
**Reviewers:** Architecture Critic, DevKB Pattern Miner, Codebase Compatibility Reviewer (subagent teams)

---

## Critical Issues (must fix before implementation)

### C1: BridgeProtocol is incomplete

**Source:** Architecture Critic

The spec defines `BridgeProtocol` with only `callTool()` and `discoverTools()`, but HTTPBridge also needs `initialize()` and `disconnect()`. Without these in the protocol, ProcessManager can't handle lifecycle generically.

**Fix:** Add `initialize()`, `disconnect()`, and a `BridgeError` type to the protocol definition. Define clear error categories that both transports map into.

### C2: MCPConfig Codable model not specified

**Source:** Architecture + Codebase Compatibility

The spec references `MCPConfig.swift` but never defines the struct. Implementation will have to reverse-engineer from the JSON examples.

**Fix:** Add full Codable struct definition to the Design section. Recommend NOT forcing config entries into `MCPManifest` — create a separate `MCPConfig` model, convert to `MCPServer` directly.

### C3: Name collision blocks intentional transport override

**Source:** Architecture Critic

"Manifest wins" rule means if a user wants to upgrade a manifest MCP to HTTP (e.g., moving cortex to a remote deployment), they can't override via mcps.json. No mechanism for intentional transport upgrades.

**Fix:** Add opt-in override mechanism. Keep "manifest wins" as default, but allow config to declare `"override": true` to explicitly take priority.

---

## Major Issues (should fix)

### M1: ConfigFileWatcher + DirectoryWatcher race condition

**Source:** Architecture Critic

Both watchers mutate `registeredServers` on the MainActor, but if both fire within the debounce window, there's no coordination. Could cause duplicate entries or missed removals.

**Fix:** Registry should be the single point of mutation. Both watchers call into registry methods that handle dedup/merge atomically. Add a spec note about serialized access.

### M2: HTTPBridge should NOT be @MainActor

**Source:** Architecture Critic + DevKB Pattern Miner

URLSession networking on MainActor blocks UI. The spec shows `@MainActor final class HTTPBridge` — this is wrong for a network-heavy class.

**Fix:** HTTPBridge should be `nonisolated` or use a custom actor. State updates (sessionId, connection status) hop to MainActor only when needed.

### M3: Secrets in plaintext JSON

**Source:** Architecture Critic

The spec's examples show raw API keys and bearer tokens in `mcps.json`. The existing manifest system has `env_secret_keys` for Keychain resolution. Config-sourced MCPs should have equivalent protection.

**Fix:** Move Keychain integration from "Out of Scope" into Nice-to-Have (R-level requirement). Add `env_secret_keys` and `headers_secret_keys` fields to config format that resolve values from Keychain at runtime.

### M4: SSE streaming has no concrete contract

**Source:** Architecture Critic

Spec says "handle SSE responses" but provides no parser interface, no error frame handling, no streaming accumulation strategy.

**Fix:** Defer SSE to Phase 2 explicitly. Phase 1 HTTP should support JSON-only responses. Add concrete SSEParser interface to Phase 2 section.

### M5: HTTP timeout/retry strategy undefined

**Source:** Architecture Critic + Codebase Compatibility

No retry policy, no exponential backoff, no distinction between transient errors (timeout, DNS) and permanent errors (401, 403). 404 is handled (session expired), but other HTTP errors are not mapped.

**Fix:** Add error classification table (transient vs permanent) and retry policy to the HTTP transport section. Recommend exponential backoff for transient, fail-fast for permanent.

### M6: DispatchSource inside @MainActor crash risk

**Source:** DevKB Pattern Miner (swift.md #16)

`DispatchSource.makeFileSystemObjectSource` dispatches callbacks on a specified queue. If the callback crosses actor boundaries incorrectly, it can crash with `_dispatch_assert_queue_fail`. DirectoryWatcher already handles this — ConfigFileWatcher must follow the exact same pattern.

**Fix:** Spec should reference DirectoryWatcher's pattern explicitly and note the queue/actor boundary handling.

### M7: Bare command paths fail on macOS

**Source:** DevKB Pattern Miner (swift.md #4, #9)

Config-sourced MCPs will commonly use bare commands like `npx`, `python3`, `uvx`. These need `/usr/bin/env` wrapping or PATH resolution. Manifest MCPs typically use absolute paths, but config MCPs (copied from Claude Desktop) often use bare names.

**Fix:** Add a requirement for command resolution in ProcessManager: if command is not an absolute path, resolve via `which` or wrap with `/usr/bin/env`. Note this in the stdio transport section.

### M8: stdin pipe must be assigned before launch

**Source:** DevKB Pattern Miner (swift.md #10)

Foundation.Process requires `standardInput` to be set before `run()`. Config-sourced MCPs go through the same ProcessManager path, but if any code path skips stdin assignment, the child process exits immediately.

**Fix:** Add a spec note in the Phase 1 implementation that config-sourced stdio MCPs MUST go through the existing ProcessManager.start() path — no separate launch logic.

### M9: .tag() type mismatch in sidebar

**Source:** DevKB Pattern Miner (swift.md #11)

MainWindow uses `isShipyardSelected` boolean for Shipyard and `selectedServer` binding for child MCPs. When adding source-based sections, `.tag()` types must match the selection binding type or selection silently fails.

**Fix:** Note in Phase 3 implementation that all sidebar items must use consistent `.tag()` types matching the selection binding.

### M10: Watcher watches parent directory, not file

**Source:** Codebase Compatibility Reviewer

`DispatchSource.makeFileSystemObjectSource` watches file descriptors. For `mcps.json`, watching the file itself won't catch external edits that replace the file (new inode). Must watch the parent directory `~/.config/shipyard/` and filter for `mcps.json` changes.

**Fix:** Specify in the ConfigFileWatcher design that it watches the parent directory (not the file) and filters change events.

---

## Minor Issues / Improvements

### m1: MCPServer needs configCwd and disabled properties

Config-sourced MCPs need `cwd` stored somewhere. Options: on MCPManifest (add optional field) or on MCPServer directly. Recommend adding to MCPServer as optional config-specific properties.

### m2: HTTP MCPs have no process stats

Views that display PID, CPU, memory need null checks for HTTP MCPs. Add `isHTTP` computed property to MCPServer for cleaner branching.

### m3: Sidebar sorting is view-level only

Registry should remain flat (insertion order). Sorting by source + name is a view concern in MainWindow. Don't add sorting logic to MCPRegistry.

### m4: Test new files with XcodeWrite

All new `.swift` files must use `mcp__xcode__XcodeWrite` — using Write tool creates files invisible to the Xcode project. (DevKB xcode.md #5-6)

### m5: HTTP — curl first, code second

Before implementing HTTPBridge, manually test the target MCP server with curl to verify correct headers, response format, and session handling. (DevKB shell.md #18)

---

## DevKB Patterns Mapped to SPEC-019 Components

| Component | DevKB File | Entry | Risk if Ignored |
|-----------|-----------|-------|-----------------|
| ConfigFileWatcher | swift.md | #16 — DispatchSource inside @MainActor | Runtime crash |
| BridgeProtocol | swift.md | #7, #8 — non-Sendable refs crossing isolation | Compiler blocks Task closures |
| ProcessManager (config MCPs) | swift.md | #4 — bare commands need /usr/bin/env | Config MCPs fail to launch |
| ProcessManager (config MCPs) | swift.md | #9 — env must include PATH | Subprocess can't find dependencies |
| ProcessManager (config MCPs) | swift.md | #10 — stdin pipe before run() | Child exits immediately |
| Sidebar sections | swift.md | #11 — .tag() type must match selection | Silent selection failure |
| New Swift files | xcode.md | #5, #6 — XcodeWrite not Write | Files invisible to compiler |
| HTTPBridge | shell.md | #18 — curl first, code second | Wrong field names, wrong responses |
| All testing | swift.md | Testing syntax — `func test() async` not `async func test()` | Compilation error |

---

## Recommendations Summary

1. **Complete BridgeProtocol** — add `initialize()`, `disconnect()`, define `BridgeError`
2. **Define MCPConfig Codable model** explicitly in spec
3. **Add secret key resolution** — `env_secret_keys` / `headers_secret_keys`
4. **Specify watcher coordination** — both watchers funnel through MCPRegistry atomically
5. **Remove @MainActor from HTTPBridge** — use nonisolated + MainActor hops for state
6. **Add HTTP error/retry policy** — classify transient vs permanent, exponential backoff
7. **Add command resolution** for bare command names in config-sourced stdio MCPs
8. **Watch parent directory** for ConfigFileWatcher, not the file itself
9. **Defer SSE to Phase 2** explicitly — Phase 1 HTTP = JSON-only
10. **Add override mechanism** for config → manifest name collisions (opt-in)
