---
id: SPEC-BUG-176
template_version: 7
priority: 2
layer: 2
type: refactor
status: draft
parent: SPEC-BUG-171
after: [SPEC-BUG-173, SPEC-BUG-174, SPEC-BUG-175]
nfrs: [SPEC-NFR-001]
created: 2026-08-12
stack: go
devkb_required: ["go.md", "architecture.md", "testing.md"]
---

# Deterministic catalog caching and subscriptions

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

