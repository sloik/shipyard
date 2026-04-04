# ADR-001: Cross-Platform Pivot (SwiftUI → Proxy + Web Dashboard)

**Status:** Accepted
**Date:** 2026-04-04
**Deciders:** Project maintainer, AI assistant

## Context

Shipyard v0.x was a native macOS SwiftUI app managing child MCP servers via a gateway pattern. After 27 specs and 19 bug fixes, it was functionally complete — but a strategic review (5-team research sprint, 2026-04-04) identified structural problems:

1. **macOS-only** — excludes Linux and Windows developers, capping the addressable market
2. **SwiftUI maintenance burden** — each feature added complexity; bugs begat bugs
3. **Single point of failure** — Shipyard being down broke the entire MCP stack
4. **Startup reliability issues** — semi-regular unavailability at session start

Meanwhile, MCP is a cross-platform protocol. Developers use Claude Code on macOS, Cursor on Windows, and Codex CLI on Linux. A macOS-only tool hits a ceiling.

## Decision

Pivot Shipyard from a macOS-only SwiftUI app to a **cross-platform proxy + web dashboard**:

- **Proxy:** lightweight CLI process that sits between MCP clients and servers, captures all JSON-RPC traffic, manages child server lifecycle
- **Dashboard:** local web UI served by the proxy at localhost, providing traffic timeline, tool browser, schema inspection, and request replay

The SwiftUI v0.x codebase is preserved on the `swiftui/v0` branch and the v0.0.1 GitHub release.

## Consequences

**Positive:**
- Runs on macOS, Linux, and Windows from day one
- Web UI is inherently shareable and extensible
- No Xcode/Swift 6 compilation overhead
- The proxy is the product, not the GUI chrome
- Smaller binary, faster startup, lower memory

**Negative:**
- Lose native macOS integrations (Keychain, menu bar, system notifications)
- Must reimplement proven UI patterns (tool browser, execution history) in web tech
- The SwiftUI codebase (~55k lines) is effectively archived

**Neutral:**
- Process management capability carries forward (proxy spawns child MCPs)
- Gateway routing pattern validated in v0.x informs v2 architecture
