---
id: SPEC-BUG-171
template_version: 7
priority: 1
layer: 0
type: main
status: planned
after: []
nfrs: [SPEC-NFR-001]
created: 2026-08-12
children: [SPEC-BUG-172, SPEC-BUG-173, SPEC-BUG-174, SPEC-BUG-175, SPEC-BUG-176, SPEC-BUG-177, SPEC-BUG-178]
---

# Shipyard dual-era MCP 2026-07-28 migration

## Problem

Shipyard is simultaneously an MCP client, stdio server, Streamable HTTP gateway, catalog cache and protocol inspector. Those surfaces hard-code legacy versions and initialization/session behavior. A single version-string change would break mixed children and external clients and would erase the very traffic visibility Shipyard exists to provide.

## Compatibility decision

Target modern `2026-07-28` plus legacy `2025-11-25` on every boundary where the official Go SDK supports both. Detect and cache the era per child process or external connection; never translate away raw captured evidence. Modern requests are stateless; Shipyard recording sessions remain explicit application data.

## Requirements

- [ ] Deliver the child specs in dependency order with official conformance fixtures before any live runtime replacement.
- [ ] Preserve all current live clients/children during rolling migration and diagnose unsupported/private dialects explicitly.
- [ ] Rebuild and deploy gateway/bridge atomically only after mixed modern/legacy tests pass.
- [ ] Decide the deployed third-party children: upgrade/replace `markitdown-mcp`; remove or separately adopt the crashed Slack fork.

## Acceptance Criteria

- [ ] AC1: All child specs are done with their evidence gates green.
- [ ] AC2: One modern HTTP server, one modern stdio server and one legacy stdio server list/call/restart successfully through Shipyard.
- [ ] AC3: New Claude and Codex sessions discover/call tools through the bridge; traffic capture retains request/response bodies, headers, era and errors.
- [ ] AC4: Launchd deploy and rollback are exercised without losing the prior binary/config.

## Rollout

SPEC-BUG-172 → 173 → 174/175 → 176 → 177 → optional 178 → rebuild/sign → isolated live smoke → atomic launchd deploy.

## Out of Scope

- Migrating child implementations inside this repo.
- Treating deprecated HTTP+SSE as a modern transport.
