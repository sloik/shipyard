---
id: SPEC-023
priority: 2
layer: 3
type: feature
status: ready
after: []
prior_attempts: []
created: 2026-03-31
---

# Localization — String Catalog + Key Schema

## Problem

All user-visible strings in Shipyard are hardcoded English literals. SwiftUI `Text("Stop")` uses the literal as the lookup key, but there is no `Localizable.xcstrings` file, no key schema, and no discipline around which strings belong in localization. Adding a second language today would require manually hunting every string across 20 view files with no structure.

## Goal

1. Create `Localizable.xcstrings` as the single source of truth for all user-visible strings.
2. Define a canonical key schema that makes keys predictable, grep-friendly, and conflict-free.
3. Migrate all in-scope strings from hardcoded literals to keyed references.
4. Establish a clear rule for what is and isn't localized so future work stays consistent.

---

## Key Schema (Normative)

### Structure

```
<screen>.<component>.<description>
```

All three segments are required. Segments use `lowerCamelCase`. No abbreviations.

| Segment | Description | Examples |
|---------|-------------|---------|
| `screen` | Top-level area of the app | `servers`, `gateway`, `settings`, `logs`, `about`, `configEditor`, `execution`, `common`, `error` |
| `component` | Sub-area or view component within the screen | `row`, `detail`, `toolbar`, `empty`, `header`, `sheet`, `form`, `sidebar` |
| `description` | What the string is used for | `title`, `label`, `button`, `placeholder`, `hint`, `message`, `tooltip` |

### Rules

1. **Three segments, always.** No two-segment keys (`servers.title`) and no four-segment keys (`servers.row.stop.label`). If a description word is needed, fold it into the third segment (`servers.row.stopButton`, not `servers.row.stop.button`).

2. **`common` for reuse.** Strings used in 3 or more places belong in `common`: `common.action.copy`, `common.action.cancel`, `common.action.save`, `common.action.close`, `common.action.dismiss`, `common.state.loading`, `common.state.unknown`.

3. **`error` screen for service errors.** Errors from services (ProcessManager, MCPRegistry, etc.) that surface to the user via alerts or inline messages use the `error` screen:
   ```
   error.<service>.<errorType>
   ```
   Examples: `error.process.startFailed`, `error.process.stopFailed`, `error.config.parseFailed`, `error.gateway.callFailed`.

4. **No keys for log messages.** `appLogger.log(...)` calls, `os.Logger` calls, and any string that only appears in console/log files are NOT localized. They stay as plain string literals.

5. **No keys for developer-facing strings.** Internal identifiers, UserDefaults keys, notification names, URL strings, JSON keys — never in the catalog.

6. **No keys for format strings used only in code.** Date formats, regex patterns, file paths — not in the catalog.

7. **Interpolated strings use `%@` / `%lld` placeholders.** String Catalog handles substitution natively. Example key value: `"Starting server %@"` with key `servers.detail.startingMessage`.

8. **Plural forms use String Catalog's built-in plural support.** Do not create separate keys like `servers.row.restartCount.singular` — use one key with plural variants in the catalog.

### Key Examples by Screen

```
// servers screen
servers.row.stopButton           = "Stop"
servers.row.startButton          = "Start"
servers.row.restartButton        = "Restart"
servers.row.editInConfigButton   = "Edit in Config…"
servers.row.statusRunning        = "Running"
servers.row.statusIdle           = "Idle"
servers.row.statusError          = "Error"
servers.row.statusStarting       = "Starting"
servers.row.pendingRemovalBadge  = "REMOVED"
servers.row.pendingRemovalHint   = "Removed from mcps.json. Stop to finish removal."
servers.row.depIssuesLabel       = "%lld dep issue"     // plural form
servers.detail.pidLabel          = "PID"
servers.detail.memoryLabel       = "Memory"
servers.detail.uptimeLabel       = "Uptime"
servers.detail.toolCountLabel    = "Tools"
servers.sidebar.shipyardSection  = "Shipyard"
servers.sidebar.manifestSection  = "Auto-Discovered"
servers.sidebar.configSection    = "From Config"

// gateway screen
gateway.empty.message            = "No tools discovered yet"
gateway.empty.hint               = "Start a server to see its tools here"
gateway.toolbar.searchPlaceholder = "Search tools…"
gateway.row.callButton           = "Call"
gateway.sheet.title              = "Call Tool"
gateway.sheet.submitButton       = "Send"
gateway.sheet.cancelButton       = "Cancel"
gateway.sheet.resultLabel        = "Result"

// settings screen
settings.autoStart.title         = "Auto-Start"
settings.autoStart.toggleLabel   = "Restore running servers on launch"
settings.autoStart.delayLabel    = "Delay between starts"
settings.autoStart.delayUnit     = "seconds"
settings.config.title            = "Config File"
settings.config.pathLabel        = "mcps.json path"
settings.config.openButton       = "Open in Editor"
settings.config.reloadButton     = "Reload Config"
settings.config.parseErrorLabel  = "Config parse error"
settings.secrets.title           = "Secrets"
settings.about.title             = "About"

// logs screen
logs.toolbar.clearButton         = "Clear"
logs.toolbar.searchPlaceholder   = "Filter logs…"
logs.empty.message               = "No log entries yet"
logs.entry.copyButton            = "Copy"

// configEditor screen
configEditor.sheet.title         = "Edit mcps.json"
configEditor.sheet.saveButton    = "Save"
configEditor.sheet.cancelButton  = "Cancel"
configEditor.sheet.loadError     = "Failed to load config file"
configEditor.sheet.saveSuccess   = "Saved"

// execution screen
execution.panel.title            = "Execution Queue"
execution.row.pendingLabel       = "Pending"
execution.row.runningLabel       = "Running"
execution.row.completedLabel     = "Completed"
execution.row.failedLabel        = "Failed"
execution.detail.requestLabel    = "Request"
execution.detail.responseLabel   = "Response"
execution.detail.durationLabel   = "Duration"

// about screen
about.version.label              = "Version"
about.buildLabel                 = "Build"

// common
common.action.copy               = "Copy"
common.action.cancel             = "Cancel"
common.action.save               = "Save"
common.action.close              = "Close"
common.action.dismiss            = "Dismiss"
common.action.retry              = "Retry"
common.state.loading             = "Loading…"
common.state.unknown             = "Unknown"
common.state.notAvailable        = "N/A"

// error
error.process.startFailed        = "Failed to start %@"
error.process.stopFailed         = "Failed to stop %@"
error.process.restartFailed      = "Failed to restart %@"
error.config.parseFailed         = "Config file is invalid: %@"
error.config.saveFailed          = "Failed to save config: %@"
error.gateway.callFailed         = "Tool call failed: %@"
error.autoStart.restoreFailed    = "Could not restore %@"
```

---

## File

**Location:** `Shipyard/Shipyard/Resources/Localizable.xcstrings`

String Catalog format (Xcode 15+). Source language: `en`. The file is managed by Xcode — add new keys in Xcode's String Catalog editor or directly in the JSON.

---

## Swift Usage Pattern

### In SwiftUI views — `Text`

SwiftUI `Text` accepts `LocalizedStringKey` automatically. Pass the key as a string literal:

```swift
// Correct — SwiftUI resolves the key at runtime
Text("servers.row.stopButton")

// Also correct for labels
Label("servers.row.stopButton", systemImage: "stop.fill")
Button("servers.row.stopButton") { ... }
```

### In non-View contexts — `String(localized:)`

For strings passed to non-SwiftUI APIs (alert messages, `.help()`, error descriptions surfaced to the UI):

```swift
// Correct
let message = String(localized: "error.process.startFailed")
Text(verbatim: server.manifest.name)   // verbatim = do NOT look up in catalog

// Incorrect — plain string init does not localize
let message = "error.process.startFailed"  // ← stays as a raw key string
```

### Interpolated strings

```swift
// String Catalog entry: "error.process.startFailed" = "Failed to start %@"
let message = String(localized: "error.process.startFailed \(server.manifest.name)")
// OR use String(format:) with the localized format string:
let fmt = String(localized: "error.process.startFailed")
let message = String(format: fmt, server.manifest.name)
```

### Identifiers and dynamic content — use `Text(verbatim:)`

Server names, file paths, JSON keys, PIDs, memory values — always `verbatim`:

```swift
Text(verbatim: server.manifest.name)   // name is a proper noun, not a string key
Text(verbatim: "\(server.pid ?? 0)")
```

---

## What Is In Scope

| ✅ Localize | ❌ Do NOT localize |
|------------|------------------|
| Button labels | Log/console messages (`appLogger`, `os.Logger`) |
| Tab names, section headers | UserDefaults keys |
| Status labels (Running, Idle, Error…) | Notification names |
| Tooltip / `.help()` text | JSON field names |
| Empty state messages | File paths |
| Alert titles and messages | URL strings |
| Error messages shown in UI | Internal identifiers |
| Form field labels and placeholders | Regex patterns |
| Badge/pill text | Server names (proper nouns) |
| Settings labels | Format strings used only in logs |

---

## Migration Approach

The agent should process views in this order (most user-facing first):

### Phase 1 — Core UI (servers, gateway)
- `MCPRowView.swift`
- `MainWindow.swift`
- `GatewayView.swift`
- `ToolExecutionSheet.swift`

### Phase 2 — Settings + Config
- `SettingsView.swift`
- `SecretsView.swift`
- `ConfigView.swift`
- `ConfigEditorSheet.swift`

### Phase 3 — Secondary screens
- `ExecutionDetailView.swift`
- `ExecutionQueuePanelView.swift`
- `ExecutionQueueRowView.swift`
- `SystemLogView.swift`
- `LogViewer.swift`
- `AboutView.swift`

### Phase 4 — Service error strings
- `ProcessManager.swift`
- `MCPRegistry.swift`
- `ConfigFileWatcher.swift`
- `AutoStartManager.swift`
- `HTTPBridge.swift`

### Per-file migration steps

For each file:
1. Grep for string literals used in Text, Label, Button, `.help()`, alert `.message`, and error descriptions
2. Apply the key schema to assign a key for each string
3. Add the key + English value to `Localizable.xcstrings`
4. Replace the literal with the key in source: `Text("Stop")` → `Text("servers.row.stopButton")`
5. For service errors currently returned as `LocalizedError.errorDescription` strings — replace with `String(localized: "error.<service>.<type>")` where the string surfaces in the UI

---

## Requirements

- [ ] R1: `Localizable.xcstrings` created at `Shipyard/Shipyard/Resources/Localizable.xcstrings`, source language `en`, registered in the Xcode target
- [ ] R2: All user-visible strings in Phase 1–3 view files replaced with keyed references
- [ ] R3: User-surfaced error description strings in Phase 4 service files replaced with keyed references
- [ ] R4: No log messages, internal identifiers, or developer-facing strings added to the catalog
- [ ] R5: All keys follow the three-segment hierarchical dot schema defined above
- [ ] R6: Strings used in 3+ places use `common.*` keys (not duplicated across screens)
- [ ] R7: Proper nouns (server names, file paths, version strings) use `Text(verbatim:)` or `String(verbatim:)` — not passed as `LocalizedStringKey`
- [ ] R8: Interpolated strings use `%@` / `%lld` substitution in the catalog, not string concatenation with localized fragments
- [ ] R9: The catalog compiles without warnings in Xcode; build succeeds with zero errors
- [ ] R10: Existing tests pass; no behavioral regressions

---

## Acceptance Criteria

- [ ] AC 1: `Localizable.xcstrings` exists and is listed in the Xcode target's resource build phase
- [ ] AC 2: Switching the Mac's language to a non-English locale with the English values still present does not break the UI — all strings fall back to the English values in the catalog
- [ ] AC 3: `grep -r '"Stop"' Shipyard/Views/` returns zero results (spot-check: hardcoded literals are gone)
- [ ] AC 4: `grep -r '"Start"' Shipyard/Views/` returns zero results
- [ ] AC 5: Every key in the catalog matches the schema regex `^[a-z][a-zA-Z]+\.[a-z][a-zA-Z]+\.[a-z][a-zA-Z]+$`
- [ ] AC 6: No log strings appear in the catalog (spot-check `grep "autostart" Localizable.xcstrings` returns zero)
- [ ] AC 7: Build succeeds with zero errors; all existing tests pass

---

## Out of Scope

- Translation into any non-English language (this spec creates the infrastructure; translations follow separately)
- RTL layout support
- Locale-specific date/number formatting (separate concern)
- Automated string extraction tooling (e.g. `genstrings` or third-party tools) — manual migration per file is correct for this codebase size
- In-app language switcher
