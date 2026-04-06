---
id: SPEC-013
priority: 13
type: nfr
status: draft
after: [SPEC-006]
created: 2026-04-06
---

# README.md — User-Facing Documentation

## Problem

Shipyard v2 has no README. Users who find the repo on GitHub have no way to understand what it does, how to install it, or how to use it. The SwiftUI v0.x README (if any) is outdated and references the wrong architecture.

## Goal

Write a comprehensive README.md that covers installation, quickstart, configuration, features, and development setup. The README is the primary onboarding surface for new users.

## Sections

### 1. Hero
- One-line pitch: "See every MCP call happening on your machine — and replay any of them without an LLM."
- Badge row: Go version, license, release version, test status

### 2. What is Shipyard?
- 2-3 sentence explanation: traffic-inspecting proxy + web dashboard for MCP
- Architecture diagram (text/mermaid): Client ↔ Shipyard proxy ↔ MCP servers, with web dashboard below

### 3. Features
- Traffic Timeline — real-time request/response capture
- Tool Browser — schema-driven forms, direct invocation without LLM
- Replay & History — one-click replay, edit-and-replay, response diff
- Multi-Server Management — config-based, auto-import from Claude Desktop/Code/Cursor
- Session Recording — VCR-like cassettes for CI
- Latency Profiling — P50/P95 stats, color-coded, per-tool/server
- Schema Change Detection — automatic alerts when tools/list changes

### 4. Quick Start
- **Wrap mode** (single server): `shipyard wrap --name filesystem -- npx -y @modelcontextprotocol/server-filesystem /tmp`
- **Config mode** (multi-server): `shipyard --config servers.json`
- Open `http://localhost:9417` in browser

### 5. Installation
- **GitHub Releases** — download binary for your platform
- **From source** — `go install github.com/sloik/shipyard/cmd/shipyard@latest`
- **Homebrew** — `brew install sloik/tap/shipyard` (future, note as planned)

### 6. Configuration Reference
- JSON config format with all fields documented
- Example `servers.json` with 2-3 servers
- CLI flags table: `--name`, `--port`, `--config`, `--schema-poll`

### 7. Auto-Import
- Explain that `shipyard --config` can auto-discover servers from Claude Desktop and Claude Code configs
- Show the auto-import flow

### 8. Development
- Prerequisites: Go 1.22+
- Build: `go build ./cmd/shipyard/`
- Test: `go test ./...`
- UI: embedded in binary, edit `internal/web/ui/` and rebuild

### 9. Architecture
- Link to ADRs in `docs/adr/`
- Brief: Go stdlib proxy, SQLite + JSONL capture, WebSocket dashboard, vanilla JS UI

### 10. License
- Reference LICENSE file

## Acceptance Criteria

- [ ] AC-1: README.md exists at repo root
- [ ] AC-2: Quick Start section lets a new user run Shipyard in under 2 minutes
- [ ] AC-3: All CLI flags and config options are documented
- [ ] AC-4: Architecture diagram is present (text-based, no external images)
- [ ] AC-5: Features list matches implemented Phase 0-4 capabilities
- [ ] AC-6: Installation section covers binary download and from-source

## Out of Scope

- Translated READMEs
- Video tutorials
- Hosted documentation site

## Target Files

- `README.md` (new)
