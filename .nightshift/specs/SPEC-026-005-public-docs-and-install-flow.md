---
id: SPEC-026-005
priority: 5
layer: 3
type: feature
status: done
after: [SPEC-026-006]
parent: SPEC-026
nfrs: [NFR-003]
prior_attempts: []
created: 2026-03-31
---

# Public Docs and Install Flow

## Problem

The current README and documentation assume the reader is the maintainer. For a public release, Shipyard needs a README that explains what it is, how to install it, how to use it, and how to contribute. The install flow must be documented for multiple methods (manual download, building from source, potentially Homebrew).

## Requirements

- [ ] Rewrite README.md: what Shipyard is, architecture overview, screenshots/diagrams, quick start, usage, contributing link
- [ ] Document manual install: download .app, copy ShipyardBridge, configure Claude Desktop/Claude Code
- [ ] Document build-from-source: clone, build with Xcode, run
- [ ] Add architecture diagram (text-based, Mermaid, or ASCII) showing: Claude ↔ ShipyardBridge ↔ Shipyard.app ↔ child MCPs
- [ ] Document mcps.json format with examples for common child MCPs
- [ ] Document how to add a new child MCP (write mcps.json entry, restart Shipyard)
- [ ] Add troubleshooting section: common issues, how to check logs, how to verify the bridge is working

## Acceptance Criteria

- [ ] AC 1: README.md has sections: Overview, Architecture, Installation, Quick Start, Configuration, Adding MCPs, Troubleshooting, Contributing
- [ ] AC 2: A new user following the Quick Start guide can get Shipyard running with one child MCP within 10 minutes
- [ ] AC 3: Architecture diagram accurately shows the Claude → Bridge → App → Child MCP data flow
- [ ] AC 4: mcps.json format is documented with at least 2 example entries
- [ ] AC 5: Troubleshooting covers: bridge not connecting, child MCP not starting, socket permission errors, log file locations
- [ ] AC 6: Build-from-source instructions include Xcode version requirement and any SPM dependencies
- [ ] AC 7: No private paths, personal references, or internal tooling mentioned in any documentation

## Context

- Shipyard's audience is developers using Claude Desktop or Claude Code who want to manage multiple MCP servers
- The bridge is critical — without it, Claude can't talk to Shipyard. Install docs must make this clear
- Claude Desktop config (`claude_desktop_config.json`) and Claude Code config need specific Shipyard entries documented
- The README should be concise — detailed docs can go in a `docs/` directory if needed

## Scenarios

1. Developer finds Shipyard on GitHub → reads README → understands it's an MCP orchestrator → follows Quick Start → has it running in 10 min → Claude can call tools from child MCPs
2. Developer wants to add their own MCP server → reads "Adding MCPs" → writes mcps.json entry → restarts Shipyard → new MCP appears in gateway
3. Developer's setup breaks → checks Troubleshooting → finds "bridge not connecting" → follows steps → identifies socket path mismatch → fixes it

## Out of Scope

- Video tutorials
- Homebrew formula (document the intent, don't create the formula)
- Automated installer script
- Documentation website (GitHub README is sufficient for v1)

## Notes for the Agent

- This spec should be implemented LAST in the SPEC-026 series because it documents the final state
- Study existing README.md (if any) before rewriting
- Architecture diagram should use Mermaid syntax (GitHub renders it natively)
- Keep the Quick Start to under 5 steps
