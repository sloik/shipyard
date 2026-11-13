---
id: SPEC-BUG-180-001
template_version: 12
priority: 2
layer: 0
type: refactor
status: draft
parent: SPEC-BUG-180
after:
- SPEC-BUG-181
nfrs:
- SPEC-NFR-001
prior_attempts: []
attachments: []
created: 2026-10-03
---

# Bump the MCP conformance CLI pin once a stable release covers 2026-07-28

## Problem

`scripts/mcp-conformance.sh` pins `@modelcontextprotocol/conformance` 0.1.16, the latest stable release, which has no `2026-07-28` scenarios (go-sdk CI uses 0.2.0-alpha.11). The modern era is covered only by golden wire tests, and the script skips a modern server leg.

## Requirements

- [ ] R1: When a stable 0.2.x (or later) release supports `--spec-version 2026-07-28`, pin it and add a stateless modern server leg against the modern fixture, re-copying the pinned go-sdk `conformance/baseline.yml` if it changed.

## Acceptance Criteria

- [ ] AC1 (R1): `scripts/mcp-conformance.sh` runs a modern-era server leg under the new stable pin with zero Shipyard-added waivers.
- [ ] AC2: `go test -race -count=1 ./...` and `go vet ./...` pass.

## Context

- Origin: SPEC-BUG-181 run report (2026-10-03), § Suggested Follow-up Specs.
- Script: `scripts/mcp-conformance.sh`; waivers: `test/mcp-conformance/expected-failures.yml`.

## Out of Scope

- Adopting a pre-release (alpha) CLI pin.

## State rationale

```yaml
schema_version: 1
status: draft
reason: Suggested as a follow-up by the SPEC-BUG-181 run on 2026-10-03; not yet reviewed for promotion.
reconsider_when: A stable @modelcontextprotocol/conformance release supports --spec-version 2026-07-28.
evidence: []
provenance: authored
record: artifacts/20261003T173546Z-decision-state-rationale-authored-draft-suggested.json
```
