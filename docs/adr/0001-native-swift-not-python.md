# ADR 0001: Native Swift Application (Not Python/Electron)

**Status**: Accepted
**Date**: 2026-03-10 (Session 24)
**Deciders**: project maintainer, AI assistant

---

## Context

Shipyard needs to manage local MCP server processes with a GUI. The UI must include a menu bar icon, system notifications, Keychain access, and process lifecycle control.

Options considered:
1. **Native Swift/SwiftUI** — macOS app with full system integration
2. **Python + Tkinter/Qt** — cross-platform but non-native
3. **Electron** — web-based desktop app
4. **Python CLI only** — no GUI

## Decision

**Native Swift/SwiftUI (Option 1).**

## Rationale

| Criterion | Swift | Python GUI | Electron |
|-----------|-------|-----------|----------|
| Menu bar (MenuBarExtra) | Native | Hacky / limited | Possible via tray |
| Keychain access | SecurityFramework (native) | Subprocess to `security` CLI | Node keytar |
| Process management | Foundation.Process | subprocess | child_process |
| System notifications | UNUserNotificationCenter | osascript | Electron notification |
| App size | ~5 MB | ~50 MB (bundled Python) | ~150 MB |
| Feel on macOS | First-class citizen | Foreign | Adequate |
| Launch at login | ServiceManagement | LaunchAgent plist | LaunchAgent plist |

The decisive factors: MenuBarExtra is SwiftUI-native and impossible to replicate well outside Swift. Keychain integration is trivial in Swift, painful everywhere else. Single-machine personal tool — no cross-platform need.

## Consequences

### Positive
- First-class macOS experience (menu bar, notifications, Keychain)
- Small binary, fast startup
- Liquid Glass design language support (macOS 26)
- No runtime dependencies (no Python, no Node)

### Negative
- Requires Xcode for building (not portable)
- Swift-only codebase for long-term maintainability
- Agent-based development requires worktree isolation for Swift builds
- Can't easily port to other platforms (not a goal anyway)

---

*Accepted at project inception (Session 24).*
