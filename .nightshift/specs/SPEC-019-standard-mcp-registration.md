---
id: SPEC-019
priority: 1
layer: 3
type: feature
status: done
after: []
created: 2026-03-27
---

# Standard MCP Registration — Universal MCP Proxy

## Problem Statement

Shipyard currently only discovers MCPs via a custom `manifest.json` format in a single hardcoded directory (`~/mcp-servers/*/manifest.json`). This means:

1. **Only locally-managed MCPs work.** Any third-party MCP (npm packages, pip-installed servers, remote HTTP servers) must have a custom manifest written for it.
2. **No standard config format.** Claude Desktop uses `{"command": "...", "args": [...], "env": {...}}` — a widely adopted convention. Shipyard can't import these.
3. **No remote MCPs.** The MCP standard defines Streamable HTTP transport for remote servers. Shipyard only supports stdio (local subprocesses).
4. **Not a complete proxy.** Shipyard's vision (ADR 0003) is "Claude connects to Shipyard; Shipyard handles everything else." Without standard registration and remote transport support, it's limited to a local orchestrator.

**Goal:** Make Shipyard a universal MCP proxy — register any MCP using the standard config format, support all MCP transports, while keeping the existing manifest.json auto-discovery intact.

## Vision

```
┌───────────────────────────────────-──────────────┐
│                   Shipyard                       │
│                                                  │
│  ┌───────────-───┐  ┌──────────────────────────┐ │
│  │ manifest.json │  │  mcps.json (standard)    │ │
│  │ auto-discover │  │  stdio + streamable HTTP │ │
│  └──────┬─────-──┘  └────────────┬─────────────┘ │
│         │                       │                │
│         ▼                       ▼                │
│  ┌──────────────────────────────────────-────┐   │
│  │          Unified MCPRegistry              │   │
│  │  (all MCPs, all transports, one list)     │   │
│  └──────────────────┬────────────────────-───┘   │
│                     │                            │
│         ┌───────────┼───────────┐                │
│         ▼           ▼           ▼                │
│     ┌───────┐  ┌────────┐  ┌──────────┐          │
│     │ stdio │  │ stdio  │  │ HTTP     │          │
│     │bridge │  │ bridge │  │ bridge   │          │
│     └───┬───┘  └───┬────┘  └────┬─────┘          │
│         │          │            │                │
└─────────┼──────────┼────────────┼────────────────┘
          ▼          ▼            ▼
      cortex     lmstudio    remote-api
    (manifest)   (manifest)   (mcps.json)
```

---

## Design

### Config File: `mcps.json`

**Location:** `~/.config/shipyard/mcps.json`

The file follows the Claude Desktop convention with extensions for Streamable HTTP:

```json
{
  "mcpServers": {
    "my-python-mcp": {
      "transport": "stdio",
      "command": "/opt/homebrew/bin/python3",
      "args": ["server.py"],
      "cwd": "~/projects/my-mcp",
      "env": {
        "API_KEY": "sk-...",
        "PYTHONUNBUFFERED": "1"
      },
      "disabled": false
    },
    "npx-filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/Documents"]
    },
    "remote-api": {
      "transport": "streamable-http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer tok_..."
      }
    }
  }
}
```

**Field reference:**

| Field | Type | Required | Transport | Description |
|-------|------|----------|-----------|-------------|
| `transport` | string | No (default: `"stdio"`) | all | `"stdio"` or `"streamable-http"` |
| `command` | string | Yes (stdio) | stdio | Executable path or command name |
| `args` | [string] | No | stdio | Command arguments |
| `cwd` | string | No | stdio | Working directory (default: directory of command) |
| `env` | {string: string} | No | stdio | Additional environment variables (merged with system env) |
| `disabled` | bool | No | all | If `true`, server is registered but not started/connected. Default: `false` |
| `url` | string | Yes (HTTP) | streamable-http | MCP endpoint URL |
| `headers` | {string: string} | No | streamable-http | HTTP headers (auth, custom headers) |
| `env_secret_keys` | [string] | No | stdio | Keys in `env` whose values are resolved from Keychain at runtime |
| `headers_secret_keys` | [string] | No | streamable-http | Keys in `headers` whose values are resolved from Keychain at runtime |
| `override` | bool | No | all | If `true`, this config entry takes priority over a manifest MCP with the same name. Default: `false` |

**Compatibility note:** When `transport` is omitted, it defaults to `"stdio"`. This makes the format directly compatible with Claude Desktop's config — users can copy-paste server entries from `claude_desktop_config.json` without modification.

### Config Model: `MCPConfig`

**New file:** `Shipyard/Models/MCPConfig.swift`

Config entries should NOT be forced into `MCPManifest`. The config format is simpler and lacks fields like `version`, `health_check`, `install`. Instead, define a separate Codable model and convert to `MCPServer` directly:

```swift
/// Root model for ~/.config/shipyard/mcps.json
struct MCPConfig: Codable, Sendable {
    let mcpServers: [String: ServerEntry]

    struct ServerEntry: Codable, Sendable {
        let transport: String?        // "stdio" (default) or "streamable-http"
        let command: String?          // stdio: executable path or command name
        let args: [String]?           // stdio: command arguments
        let cwd: String?              // stdio: working directory
        let env: [String: String]?    // stdio: additional environment variables
        let envSecretKeys: [String]?  // stdio: keys resolved from Keychain at runtime
        let url: String?              // HTTP: endpoint URL
        let headers: [String: String]? // HTTP: custom headers (auth, etc.)
        let headersSecretKeys: [String]? // HTTP: header keys resolved from Keychain
        let disabled: Bool?           // all: registered but not started (default: false)
        let override: Bool?           // all: if true, takes priority over manifest with same name

        enum CodingKeys: String, CodingKey {
            case transport, command, args, cwd, env
            case envSecretKeys = "env_secret_keys"
            case url, headers
            case headersSecretKeys = "headers_secret_keys"
            case disabled
            case override = "override"
        }
    }
}
```

**Validation rules:**
- If `transport` is `"stdio"` or omitted: `command` is required, `url` is ignored
- If `transport` is `"streamable-http"`: `url` is required, `command`/`args`/`cwd` are ignored
- Unknown `transport` values → log warning, skip entry
- Duplicate keys in JSON → last value wins (standard JSON behavior)

### Transport: stdio (existing + enhanced)

Stdio MCPs work exactly as today — Shipyard launches a subprocess, communicates via stdin/stdout with newline-delimited JSON-RPC.

**What changes:**
- `MCPManifest` gains an optional `cwd` field (working directory for the process)
- Config-sourced MCPs are converted to `MCPServer` objects (see MCPConfig model above) — NOT forced into `MCPManifest`
- `ProcessManager` uses `cwd` when launching the process (falls back to command's directory)
- **Command resolution:** Config-sourced MCPs commonly use bare commands (`npx`, `python3`, `uvx`) copied from Claude Desktop. `ProcessManager` must resolve bare commands: if `command` is not an absolute path, wrap with `/usr/bin/env` or resolve via `which`. (DevKB swift.md #4: bare commands fail without PATH resolution.)

**What stays the same:**
- Config-sourced stdio MCPs MUST go through the existing `ProcessManager.start()` path — no separate launch logic. This ensures stdin pipe assignment, environment merging, and process monitoring are consistent. (DevKB swift.md #10: stdin pipe must be assigned before `run()`.)

### Transport: Streamable HTTP (new)

Per the [MCP specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#streamable-http):

- Client sends JSON-RPC messages via **HTTP POST** to the MCP endpoint URL
- Server responds with either `application/json` (single response) or `text/event-stream` (SSE stream)
- Client can **HTTP GET** the endpoint to listen for server-initiated messages
- Session management via `MCP-Session-Id` header
- Protocol version via `MCP-Protocol-Version` header

**New component: `HTTPBridge`**

A new bridge class parallel to `MCPBridge`, conforming to `BridgeProtocol` over HTTP.

**⚠️ NOT @MainActor.** URLSession networking must not block the main thread. Use `nonisolated` class with explicit `@MainActor` hops only for state updates (connection status on MCPServer).

```swift
/// HTTP transport bridge — conforms to BridgeProtocol.
/// NOT @MainActor — network calls run off main thread.
/// State updates (sessionId, connection status) hop to MainActor when needed.
final class HTTPBridge: BridgeProtocol, Sendable {
    let mcpName: String
    let endpointURL: URL
    let customHeaders: [String: String]

    // Thread-safe state (OSAllocatedUnfairLock or actor-isolated)
    private let state: OSAllocatedUnfairLock<HTTPBridgeState>

    struct HTTPBridgeState {
        var sessionId: String?
        var isInitialized: Bool = false
    }

    func initialize() async throws -> [String: Any]
    func callTool(name: String, arguments: [String: Any]) async throws -> [String: Any]
    func discoverTools() async throws -> [[String: Any]]
    func disconnect() async
}
```

**Key behaviors:**
- On connect: POST `InitializeRequest`, store `MCP-Session-Id` from response header
- On tool call: POST `tools/call`, include `MCP-Session-Id` and `MCP-Protocol-Version` headers
- On disconnect: DELETE endpoint with session header (per MCP spec)
- Timeout: configurable, default 30s (same as stdio)
- Error handling: map HTTP errors to `BridgeError` (see BridgeProtocol section)

**Response handling (phased):**
- **Phase 1:** JSON-only (`application/json`). If server returns `text/event-stream`, throw unsupported error.
- **Phase 2:** Add SSE parsing via `SSEParser` (see Phase 2 section).

**Error classification and retry policy:**

| HTTP Status | Classification | Action |
|-------------|---------------|--------|
| 200 | Success | Parse response |
| 404 | Session expired | Re-initialize session, retry once |
| 401, 403 | Auth failure (permanent) | Fail fast, report to UI |
| 408, 429, 502, 503, 504 | Transient | Retry with exponential backoff (max 3 retries, 1s/2s/4s) |
| Other 4xx | Client error (permanent) | Fail fast, report to UI |
| Other 5xx | Server error (transient) | Retry with backoff |
| DNS/Connection refused | Network error (transient) | Retry with backoff |
| Timeout | Transient | Retry with backoff |

**No subprocess.** HTTP MCPs are remote servers — `ProcessManager` doesn't manage their processes. `MCPServer.state` reflects connection status (`.running` = connected, `.idle` = disconnected, `.error` = connection failed).

### Unified MCPRegistry

Both sources feed into the same registry:

```
discover()   — scans ~/mcp-servers/*/manifest.json (existing)
loadConfig() — reads ~/.config/shipyard/mcps.json (new)
     │                    │
     ▼                    ▼
   MCPServer           MCPServer
  (source: .manifest) (source: .config)
     │                    │
     └────────┬───────────┘
              ▼
     registeredServers: [MCPServer]
```

**MCPServer gains:**

```swift
enum MCPSource: String, Codable {
    case manifest    // auto-discovered from manifest.json
    case config      // loaded from mcps.json
    case synthetic   // Shipyard itself (SPEC-008)
}

enum MCPTransport: String, Codable {
    case stdio
    case streamableHTTP = "streamable-http"
}
```

- `source` property — distinguishes origin for UI display and lifecycle
- `transport` property — determines which bridge type to use

**Name collision handling:**
- **Default:** If both manifest.json and mcps.json define an MCP with the same name, the manifest.json version wins (existing takes priority). Log a warning.
- **Override:** If the config entry sets `"override": true`, the config version takes priority. This allows intentional transport upgrades (e.g., moving an MCP from local stdio to remote HTTP) without removing the manifest. Log an info message noting the override.

### Config File Watching

`ConfigFileWatcher` (new) — watches `mcps.json` for changes using the same `DispatchSource` pattern as `DirectoryWatcher`.

**⚠️ Watch the parent directory** (`~/.config/shipyard/`), NOT the file itself. External editors often write a new file and rename it (new inode), which invalidates file-level watchers. Watching the parent directory catches all edit patterns. Filter events to only reload when `mcps.json` changes.

**⚠️ DispatchSource + @MainActor:** Follow the exact pattern from `DirectoryWatcher` for queue/actor boundary handling. DispatchSource callbacks must dispatch to MainActor explicitly — do NOT assume MainActor isolation in the callback. (DevKB swift.md #16: DispatchSource inside @MainActor can crash with `_dispatch_assert_queue_fail` if not handled correctly.)

**Behavior:**
- On change: call `MCPRegistry.reloadConfig()` — the registry handles merge/dedup atomically
- Debounce: 1 second (same as directory watcher)
- On first load: create default empty `mcps.json` if it doesn't exist
- On parse error: log error, keep existing servers, don't crash

**Watcher coordination:** Both `DirectoryWatcher` and `ConfigFileWatcher` mutate the registry. All mutations go through `MCPRegistry` methods which run on `@MainActor` — this serializes access. Neither watcher should directly manipulate `registeredServers`.

### ProcessManager Changes

`ProcessManager` needs to handle two bridge types:

```swift
// Existing
func bridge(for server: MCPServer) -> MCPBridge?

// New — returns either type
func stdioBridge(for server: MCPServer) -> MCPBridge?
func httpBridge(for server: MCPServer) -> HTTPBridge?
```

For gateway calls, `SocketServer.handleGatewayCall()` checks the server's transport and uses the appropriate bridge. The `callTool` interface is the same for both.

**Required:** Define a `BridgeProtocol` that both `MCPBridge` and `HTTPBridge` conform to:

```swift
/// Transport-agnostic interface for MCP communication.
/// Both MCPBridge (stdio) and HTTPBridge conform to this.
protocol BridgeProtocol: Sendable {
    var mcpName: String { get }

    /// Initialize the MCP connection (stdio: send initialize request; HTTP: POST initialize + store session)
    func initialize() async throws -> [String: Any]

    /// Call a tool by name with arguments, return result dict
    func callTool(name: String, arguments: [String: Any]) async throws -> [String: Any]

    /// Discover available tools (tools/list)
    func discoverTools() async throws -> [[String: Any]]

    /// Clean up connection (stdio: no-op or send shutdown; HTTP: DELETE session)
    func disconnect() async
}

/// Unified error type for both transports.
enum BridgeError: LocalizedError {
    // Shared
    case notInitialized(String)          // bridge used before initialize()
    case serializationFailed(String)     // JSON encode/decode failure
    case timeout(String, TimeInterval)   // operation timed out

    // Stdio-specific
    case processNotRunning(String)       // child process exited
    case stdioPipeClosed(String)         // stdin/stdout pipe broken

    // HTTP-specific
    case httpError(String, Int, String)  // (mcpName, statusCode, message)
    case sessionExpired(String)          // 404 — session gone, needs re-init
    case connectionFailed(String, String) // (mcpName, underlying error description)

    // Transient vs permanent classification for retry logic
    var isTransient: Bool {
        switch self {
        case .timeout, .sessionExpired, .connectionFailed: return true
        default: return false
        }
    }
}
```

This keeps `SocketServer` transport-agnostic — it calls `bridge.callTool()` without knowing the transport. **This is the required approach** (not alternative).

### Sidebar Ordering

The Servers tab sidebar has a defined ordering (updates SPEC-008 AC 7):

```
1. Shipyard          (always first — synthetic server, pinned)
2. Manifest MCPs     (alphabetical by name)
3. Config MCPs       (alphabetical by name)
```

**Implementation:** `MainWindow.swift` `serversView` currently renders Shipyard first (hardcoded), then `registry.registeredServers` in insertion order. Change to:
- Split `registeredServers` by `source` property (`.manifest` vs `.config`)
- Sort each group alphabetically by `manifest.name`
- Render: Shipyard → manifest group → config group
- Visual section headers are optional (nice-to-have) — the source badge on each row is sufficient

### UI Changes

**Servers tab:**
- Config-sourced MCPs show a small badge or icon indicating "from config" vs "auto-discovered"
- HTTP MCPs show connection status instead of PID/memory (no local process)
- Start/Stop for HTTP MCPs means connect/disconnect (initialize/terminate session)
- Sidebar ordering: Shipyard → Manifest MCPs (alphabetical) → Config MCPs (alphabetical)

**Settings → MCPs (new section):**
- Shows path to `mcps.json`
- "Open in Editor" button (reveals in Finder or opens in default JSON editor)
- "Reload Config" button
- Display parse errors if config is invalid

**Add MCP dialog (nice-to-have, post-MVP):**
- Form to add a new MCP entry to mcps.json
- Fields: name, transport (picker), command/args/env or URL/headers
- Writes to mcps.json → config watcher picks it up → appears in registry

---

## Requirements

### Must Have (MVP)

- [ ] R1: `mcps.json` config file at `~/.config/shipyard/mcps.json` is loaded on startup
- [ ] R2: Stdio MCPs defined in `mcps.json` are registered, started, and accessible via gateway — same as manifest MCPs
- [ ] R3: Config format is compatible with Claude Desktop's `mcpServers` syntax (copy-paste works)
- [ ] R4: `transport` field defaults to `"stdio"` when omitted
- [ ] R5: `cwd` field sets the working directory for stdio subprocess launch
- [ ] R6: `env` field merges with system environment (config values override)
- [ ] R7: `disabled: true` registers the server but does not start it
- [ ] R8: Config-sourced and manifest-sourced MCPs appear in the same unified registry/UI
- [ ] R8a: Sidebar ordering: Shipyard (first) → Manifest MCPs (alphabetical) → Config MCPs (alphabetical)
- [ ] R9: Name collisions (same name in both sources) resolved: manifest wins, warning logged
- [ ] R10: Config file is watched for changes (add/remove/edit MCPs without restart)
- [ ] R11: Config parse errors are logged and displayed in UI — don't crash, keep existing servers
- [ ] R12: Streamable HTTP transport: connect to remote MCP via HTTP POST/GET per MCP spec
- [ ] R13: HTTP MCPs: send `MCP-Protocol-Version` and `MCP-Session-Id` headers as required by spec
- [ ] R14: HTTP MCPs: handle `application/json` responses (Phase 1); `text/event-stream` SSE parsing deferred to Phase 2 (R23)
- [ ] R15: HTTP MCPs: session management (store session ID, send on subsequent requests, handle 404 = session expired)
- [ ] R16: HTTP MCPs: validate `Origin` header protections when connecting to localhost servers
- [ ] R17: `BridgeProtocol` abstraction with `initialize()`, `callTool()`, `discoverTools()`, `disconnect()` — both bridges conform
- [ ] R18: Gateway tool discovery and forwarding works identically for both transports
- [ ] R19: Existing manifest.json auto-discovery unchanged — zero regressions
- [ ] R20: Default empty `mcps.json` created on first launch if file doesn't exist
- [ ] R20a: Config-sourced stdio MCPs with bare commands (`npx`, `python3`) are resolved via `/usr/bin/env` or PATH lookup
- [ ] R20b: Config `override: true` allows config entry to take priority over manifest with same name
- [ ] R20c: HTTP error retry policy: transient errors (timeout, 5xx, DNS) retry with exponential backoff (max 3, 1s/2s/4s); permanent errors (4xx except 404/408/429) fail fast
- [ ] R20d: `HTTPBridge` does NOT run on MainActor — network calls are off main thread

### Nice to Have (Post-MVP)

- [ ] R21: "Add MCP" UI dialog in Settings that writes to mcps.json
- [ ] R22: Import from Claude Desktop config (read `~/Library/Application Support/Claude/claude_desktop_config.json`, offer to import)
- [ ] R23: SSE response support for HTTP MCPs (Phase 2 — `text/event-stream` parsing via `SSEParser`)
- [ ] R24: Per-server timeout configuration in mcps.json
- [ ] R25: Health check configuration for config-sourced MCPs
- [ ] R26: Keychain integration for config secrets (`env_secret_keys`, `headers_secret_keys`) — resolve values from macOS Keychain at runtime instead of storing plaintext in mcps.json
- [ ] R27: SSE backward compatibility (connect to legacy HTTP+SSE servers per MCP spec backwards compatibility section)

---

## Acceptance Criteria

### Config Loading

- [ ] AC 1: On startup, Shipyard reads `~/.config/shipyard/mcps.json` and registers all defined MCPs
- [ ] AC 2: A stdio MCP in mcps.json with `command` + `args` starts and its tools appear in the Gateway tab
- [ ] AC 3: Omitting `transport` defaults to `"stdio"` — Claude Desktop config entries work without modification
- [ ] AC 4: `disabled: true` registers the MCP in the Servers tab (grayed out) but does not start it
- [ ] AC 5: If mcps.json doesn't exist, Shipyard creates a default `{"mcpServers": {}}` file
- [ ] AC 6: If mcps.json has a parse error, Shipyard logs the error and continues with manifest-sourced MCPs

### Config Watching

- [ ] AC 7: Adding a new entry to mcps.json while Shipyard is running registers the new MCP within ~2 seconds
- [ ] AC 8: Removing an entry stops the MCP and removes it from the registry
- [ ] AC 9: Editing an entry (e.g., changing args) flags "config changed, restart to apply" or auto-restarts

### Unified Registry

- [ ] AC 10: Manifest-sourced and config-sourced MCPs appear in the same Servers tab list
- [ ] AC 11: Config-sourced MCPs show a visual indicator (badge/icon) distinguishing them from manifest MCPs
- [ ] AC 11a: Sidebar order is: Shipyard → Manifest MCPs (alphabetical) → Config MCPs (alphabetical)
- [ ] AC 12: If both sources define the same name, manifest wins and a warning appears in logs

### Stdio Transport (from config)

- [ ] AC 13: A config-sourced stdio MCP starts its subprocess correctly with the specified command/args/env
- [ ] AC 14: `cwd` sets the working directory for the subprocess
- [ ] AC 15: `env` values are merged with system environment (config overrides conflicts)
- [ ] AC 16: Tool calls via gateway work identically to manifest-sourced MCPs

### Streamable HTTP Transport

- [ ] AC 17: An HTTP MCP connects to the specified URL and completes MCP initialization handshake
- [ ] AC 18: Tool discovery (`tools/list`) works over HTTP and tools appear in Gateway tab
- [ ] AC 19: Tool calls route through HTTP POST and return results to Claude
- [ ] AC 20: Phase 1: JSON-only HTTP responses. If server returns `text/event-stream`, throw unsupported error. Phase 2: SSE parsing via `SSEParser`
- [ ] AC 21: Session ID is stored from initialization response and sent on all subsequent requests
- [ ] AC 22: HTTP 404 response triggers session re-initialization
- [ ] AC 23: `headers` from config are included in all HTTP requests (e.g., Authorization)
- [ ] AC 24: Connection errors (timeout, DNS, refused) are reported clearly in UI and logs

### BridgeProtocol

- [ ] AC 25: Both `MCPBridge` and `HTTPBridge` conform to `BridgeProtocol` (including `initialize()` and `disconnect()`)
- [ ] AC 26: `SocketServer.handleGatewayCall()` is transport-agnostic — uses protocol, not concrete type
- [ ] AC 26a: `HTTPBridge` does NOT use `@MainActor` — network calls execute off main thread
- [ ] AC 26b: Config entry with `override: true` takes priority over manifest MCP with same name
- [ ] AC 26c: Config-sourced stdio MCPs with bare commands (e.g., `npx`) launch successfully via PATH resolution
- [ ] AC 26d: HTTP transient errors (timeout, 5xx) retry with exponential backoff; permanent errors (401, 403) fail immediately

### Build & Test

- [ ] AC 27: Build succeeds with zero errors
- [ ] AC 28: All existing tests pass (no regressions)
- [ ] AC 29: New unit tests for config loading, config watching, HTTP bridge, and BridgeProtocol

---

## Implementation Plan

### Phase 1: Config Loading + Stdio (foundation)

**New files:**
- `Shipyard/Models/MCPConfig.swift` — Codable model for mcps.json (see MCPConfig section above)
- `Shipyard/Services/ConfigFileWatcher.swift` — DispatchSource file watcher (watch parent dir, not file — see Config File Watching section)

**Modified files:**
- `MCPManifest.swift` — add `cwd` field, `MCPSource` enum, `MCPTransport` enum
- `MCPServer.swift` — add `source`, `transport`, optional `configCwd`, `disabled` properties; add `isHTTP` computed property
- `MCPRegistry.swift` — add `loadConfig()` / `reloadConfig()`, merge config + manifest servers, handle `override` flag
- `ProcessManager.swift` — use `cwd` when launching, handle config-sourced servers, resolve bare commands via `/usr/bin/env`
- `ShipyardApp.swift` — call `loadConfig()` on startup, set up config watcher

**DevKB to read before Phase 1:**
- `swift.md` — #4 (bare commands), #9 (env PATH), #10 (stdin pipe), #16 (DispatchSource @MainActor)
- `xcode.md` — #5, #6 (XcodeWrite for new files)

**Tests:**
- Config parsing (valid, empty, malformed, missing file)
- Config → MCPServer creation (stdio)
- Registry merge (manifest + config, name collision, override)
- Config watcher (add/remove/edit detection)
- Bare command resolution (npx → /usr/bin/env npx)

### Phase 2: Streamable HTTP Transport

**New files:**
- `Shipyard/Services/HTTPBridge.swift` — HTTP transport (NOT @MainActor, uses nonisolated URLSession)
- `Shipyard/Services/BridgeProtocol.swift` — shared protocol + `BridgeError` enum
- `Shipyard/Services/SSEParser.swift` — Server-Sent Events parser (deferred to Phase 2b — Phase 2a is JSON-only)

**Modified files:**
- `MCPBridge.swift` — conform to `BridgeProtocol` (add `initialize()` wrapper, `disconnect()` no-op)
- `ProcessManager.swift` — manage HTTP bridges alongside stdio bridges (dual dictionaries)
- `SocketServer.swift` — use `BridgeProtocol` for gateway calls (transport-agnostic)
- `GatewayRegistry.swift` — handle HTTP-sourced tools the same as stdio

**DevKB to read before Phase 2:**
- `swift.md` — #7, #8 (non-Sendable crossing isolation), #16 (actor boundaries)
- `shell.md` — #18 (curl target MCP server first before coding HTTPBridge)

**Pre-implementation step:** Before writing HTTPBridge code, manually test the target HTTP MCP with `curl` to verify response format, headers, and session handling.

**Tests:**
- HTTPBridge initialization handshake (mock HTTP server)
- Tool call over HTTP (JSON response)
- Session management (store ID, handle 404 re-init)
- Error retry policy (transient vs permanent)
- BridgeProtocol conformance for both bridge types
- Phase 2b: SSE streaming response parsing

### Phase 3: UI + Polish

**Modified files:**
- `MCPRowView.swift` — source badge (config vs manifest), HTTP connection status (no PID/memory for HTTP MCPs — use `isHTTP` computed property)
- `MainWindow.swift` — sidebar sorting: split by source, sort alphabetically, render Shipyard → Manifest → Config. **⚠️ `.tag()` types must match the selection binding type** (DevKB swift.md #11 — mismatched tag types cause silent selection failure)
- `SettingsView.swift` — mcps.json section (path, open, reload, errors)
- `GatewayView.swift` — HTTP MCPs show connect/disconnect instead of start/stop

**Nice-to-have:**
- Add MCP dialog (writes to mcps.json)
- Import from Claude Desktop config

---

## Context

### Related specs & reviews:

- `SPEC-019-review-findings.md` — full review findings (3 critical, 10 major issues, DevKB pattern mapping table). **Read this before implementation** — contains pitfall-to-component mapping that prevents known failure patterns.

### Key files:

- `Shipyard/Models/MCPManifest.swift` — current manifest model (Codable struct)
- `Shipyard/Models/MCPServer.swift` — server model (`@Observable @MainActor`)
- `Shipyard/Services/MCPRegistry.swift` — discovery + registration
- `Shipyard/Services/MCPBridge.swift` — stdio JSON-RPC bridge
- `Shipyard/Services/ProcessManager.swift` — subprocess lifecycle
- `Shipyard/Services/DirectoryWatcher.swift` — FSEvents watcher (pattern for ConfigFileWatcher)
- `Shipyard/Services/SocketServer.swift` — gateway call routing

### MCP Specification Reference:

- [Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) — stdio + Streamable HTTP spec
- Streamable HTTP replaces deprecated HTTP+SSE (2024-11-05)
- Two official transports: stdio (local) and Streamable HTTP (remote)
- JSON-RPC 2.0 over both transports, UTF-8 encoded

### Existing patterns to reuse:

- `DirectoryWatcher` — DispatchSource file watching (copy pattern for ConfigFileWatcher)
- `MCPManifest.load(from:)` — JSON decode pattern (use for config loading)
- `MCPBridge` — stdio bridge (conform to new BridgeProtocol)
- `ProcessManager.bridge(for:)` — bridge lookup (extend for HTTP bridges)

### Testing:

- Xcode target: `ShipyardTests/` (Swift Testing, `@Test`, `@Suite`)
- SPM target: `ShipyardBridgeTests/` (for bridge-level tests)
- New .swift files MUST use `mcp__xcode__XcodeWrite` (Xcode project registration)
- Build: `mcp__xcode__BuildProject(tabIdentifier: "windowtab1")`

---

## Review History

- **2026-03-27** — Three-agent review (architecture critic, DevKB pattern miner, codebase compatibility). Findings: `SPEC-019-review-findings.md`. Applied: complete BridgeProtocol, MCPConfig model, HTTPBridge off MainActor, retry policy, command resolution, override mechanism, ConfigFileWatcher parent-dir pattern, SSE deferred to Phase 2b. See findings doc for full DevKB pattern mapping.

---

## Out of Scope

- Migrating existing manifest.json MCPs to mcps.json (both coexist forever)
- WebSocket transport (not in MCP standard)
- MCP marketplace / registry browser
- Multi-user / shared config files
- Config file encryption
