---
id: SPEC-BUG-185
template_version: 7
priority: 2
layer: 2
type: refactor
status: draft
parent: SPEC-BUG-180
after:
- SPEC-BUG-182
- SPEC-BUG-183
- SPEC-BUG-184
nfrs:
- SPEC-NFR-001
created: 2026-08-12
stack: go
devkb_required:
- go.md
- architecture.md
- testing.md
---

# Deterministic catalog caching and subscriptions

> Former ID: SPEC-BUG-176 (renumbered by SPEC-BUG-179 on 2026-10-03 to remove a duplicate ID).

## Problem

Modern list results require deterministic order and cache metadata, while long-lived change notifications now flow through `subscriptions/listen`. Shipyard aggregates mutable child catalogs and policy-filtered views without a formal cache/invalidation contract.

## Requirements

- [ ] Define stable namespaced ordering, pagination, `ttlMs`, and correct public/private `cacheScope` for each policy/auth view.
- [ ] Invalidate on child restart/schema/config/policy/auth changes without leaking a prior principal's catalog.
- [ ] Deliver changes only through modern subscriptions, retaining era-correct legacy notifications.
- [ ] Bound subscribers/cache entries and prove concurrent refresh is race-free.

## Acceptance Criteria

- [ ] AC1: Identical state yields byte-stable list ordering and cache fields across reconnects.
- [ ] AC2: Each invalidation source produces one correct update; unrelated subscribers receive none.
- [ ] AC3: Principal/policy separation, cancellation, slow consumer and restart tests pass under `-race`.

## Out of Scope

- General dashboard caching or new catalog features.


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
