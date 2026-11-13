---
id: SPEC-BUG-187
template_version: 7
priority: 3
layer: 3
type: refactor
status: draft
parent: SPEC-BUG-180
after:
- SPEC-BUG-186
nfrs:
- SPEC-NFR-001
created: 2026-08-12
stack: go
devkb_required:
- go.md
- testing.md
- macos.md
---

# Evaluate and migrate Wails alpha to beta

> Former ID: SPEC-BUG-178 (renumbered by SPEC-BUG-179 on 2026-10-03 to remove a duplicate ID).

## Problem

Shipyard uses Wails v3 alpha2.117 while beta.7 is available. This GUI/runtime jump is high-risk and unrelated to MCP wire compliance, so it must not share the protocol migration's failure surface.

> Status note (2026-11-13): the premise above is out of date. `main` had already moved to Wails
> v3.0.0-beta.27, and Renovate PR #42 moved it to v3.1.0 on 2026-11-13 with CI and the Desktop
> Build green. That merge did not go through this spec: `wails3 task build` and
> `wails3 task darwin:package` were run locally, and the new build opened a copy of the live
> capture database headless without errors, but the desktop window, launchd start and restart,
> signing behaviour and a demonstrated rollback (AC1 to AC3) are not verified, and the new build
> is not yet deployed to the live gateway. A rollback binary built with beta.27 is kept at
> `archive/runtime/20261113-pre-wails31-rollback/shipyard`. This spec stays `draft`; whoever
> promotes it must restate the problem as "verify v3.1.0 live" instead of "migrate alpha to beta".

## Requirements

- [ ] Build a breaking-change inventory and an isolated beta proof against current desktop behavior and packaging/signing.
- [ ] Migrate only after the headless/bridge protocol rollout is stable; preserve a working alpha binary for rollback.
- [ ] Validate macOS window lifecycle, assets, browser fallback, bridge discovery, signing and launchd integration.

## Acceptance Criteria

- [ ] AC1: The beta build passes full/race/coverage gates and a documented desktop scenario matrix.
- [ ] AC2: Packaged binary identity, signing/ad-hoc behavior and launchd start/restart are live-verified.
- [ ] AC3: Performance/startup/binary-size changes are measured and rollback to alpha is demonstrated.

## Out of Scope

- MCP protocol changes and new UI features.


## State rationale

```yaml
schema_version: 1
status: draft
reason: Drafted 2026-08-12 as a child of the MCP 2026 migration plan (SPEC-BUG-180); not yet reviewed for promotion.
reconsider_when: SPEC-BUG-180 is promoted and every spec this one depends on is done, or the plan is replanned.
evidence: []
provenance: authored
record: artifacts/20261003T153225Z-decision-state-rationale-authored-draft-drafted-2.json
```
