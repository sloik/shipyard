---
id: SPEC-BUG-026
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: [UX-002, SPEC-BUG-017]
violates: [UX-002]
prior_attempts: []
created: 2026-04-12
---

# Tool Browser offline and restarting servers do not render the approved Phase 1 state banner

## Problem

The Tool Browser currently handles offline and restarting servers by dimming or
auto-collapsing the affected server group and appending inline `offline` /
`restarting` labels in the group header.

The approved Pencil design defines a dedicated sidebar state banner for this
condition:
- state frame: `R9sUx`
- banner node: `IpBia` (`offline-banner`)

That is a distinct state surface, not just a per-row label treatment.

## Reproduction

1. Open the Tools tab
2. Put one managed server offline or into restarting state
3. Observe the left sidebar
4. **Actual:** the affected server group is dimmed/collapsed and labeled inline
5. **Expected:** the sidebar includes the approved offline/restarting banner in
   addition to the server-group state treatment

## Root Cause

The sidebar renderer only maps offline/restarting state into `groupClass`,
header dots, and inline status text:

- `internal/web/ui/index.html`

There is no markup path for the design's dedicated `offline-banner` state.

## Requirements

- [ ] R1: The Tool Browser sidebar must render a dedicated offline/restarting
  banner when one or more servers are unavailable or restarting.
- [ ] R2: The banner must follow the Phase 1 warning/danger treatment defined in
  the Pencil state.
- [ ] R3: Existing per-group offline/restarting labels may remain, but they must
  not be the only state signal.

## Acceptance Criteria

- [ ] AC 1: When at least one tool server is offline or restarting, the sidebar
  shows a banner-level state surface.
- [ ] AC 2: The banner communicates aggregate server state consistent with the
  design rather than only inline row labels.
- [ ] AC 3: When all tool servers are online, the banner is absent.
- [ ] AC 4: Regression tests cover the offline/restarting banner rendering
  contract.
- [ ] AC 5: `go test ./...` passes.
- [ ] AC 6: `go vet ./...` passes.
- [ ] AC 7: `go build ./...` passes.

## Context

- Relevant implementation:
  - `internal/web/ui/index.html`
  - `internal/web/ui/ds.css`
  - `internal/web/ui_layout_test.go`
- Relevant design:
  - `.nightshift/specs/UX-002-dashboard-design.pen`
  - `R9sUx`
  - `IpBia`

## Out of Scope

- Changing backend server-status semantics
- Changing collapse behavior itself
- Redesigning the entire Tool Browser sidebar

## Research Hints

- The sidebar already has a conflict banner pattern; this fix likely needs a
  sibling state banner for availability problems.
- Keep the banner logic aggregate and derived from current server states.

## Gap Protocol

- Research-acceptable gaps:
  - exact copy when both offline and restarting states are present
- Stop-immediately gaps:
  - any fix that removes current server status indicators without replacement
  - any implementation that relies on backend API changes for a pure UI state
    presentation issue
- Max research subagents before stopping: 0
