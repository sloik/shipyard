---
id: SPEC-BUG-113
template_version: 2
priority: 2
layer: 2
type: feature
status: done
after: []
violates: []
prior_attempts: []
created: 2026-04-15
supersedes: [SPEC-BUG-063, SPEC-BUG-096, SPEC-BUG-097, SPEC-BUG-110]
---

# Replace pagination with infinite scroll

## Problem

The Traffic Timeline and History Requests views use traditional pagination (Prev/Next buttons, page numbers). This requires the user to click through pages to find entries. The UX should use infinite scroll with dynamic loading — new items load automatically as the user scrolls down.

**Supersedes:** SPEC-BUG-063 (pagination layout), SPEC-BUG-096 (pagination gap), SPEC-BUG-097 (pagination button color), SPEC-BUG-110 (pagination not sticky). All pagination styling specs become moot once pagination is replaced.

## Requirements

- [x] R1: Traffic Timeline uses infinite scroll instead of pagination
- [x] R2: History Requests uses infinite scroll instead of pagination
- [x] R3: Items load dynamically as user scrolls near the bottom (200px threshold via IntersectionObserver)
- [x] R4: A loading indicator appears while new items are fetched
- [x] R5: "Showing N of M" count remains visible as footer text after all items load
- [x] R6: Remove Prev/Next buttons and page number UI

## Acceptance Criteria

- [x] AC 1: Scrolling down in Traffic Timeline automatically loads the next batch of entries
- [x] AC 2: Scrolling down in History Requests automatically loads the next batch of entries
- [x] AC 3: A spinner or "Loading..." indicator appears during fetch
- [x] AC 4: Total count is still visible (trafficCount label + scroll-count-info footer)
- [x] AC 5: No pagination buttons, page numbers, or "Go to page" UI remains
- [x] AC 6: Performance: scrolling remains smooth with 1000+ rows loaded (append-only DOM, no full re-render)
- [x] AC 7: `go build ./...` passes

## Root Cause

The API used `?page=N&page_size=N` (1-indexed). The frontend JS maintained `currentPage`/`historyPage` state and replaced the whole table body on each load. Added `?offset=N` support to `QueryFilter` and `handleTraffic` (offset takes precedence over page when `UseOffset=true`). Frontend replaced Prev/Next with `IntersectionObserver` sentinel elements, append-only DOM updates, and `timelineOffset`/`historyOffset` state. CSS pagination section replaced with sentinel/spinner styles.

## Context

- Current: `.pagination` bar with Prev/Next, page numbers, "Showing 1-25 of N"
- Current API likely supports `?page=N&limit=25` — will need `?offset=N&limit=25` or similar for infinite scroll
- The `.pagination` CSS and elements can be removed entirely
- Loading indicator should match the existing Spinner/Default component (`MnylU`)
- IntersectionObserver is the preferred scroll-detection approach (vs scroll event listeners)

## Out of Scope

- Virtual scrolling / DOM recycling (can be a future optimization)
- Search/filter changes (those remain as-is)

## Code Pointers

- `internal/web/ui/index.html` — pagination HTML elements, JS fetch logic for timeline/history
- `internal/web/ui/ds.css` — `.pagination`, `.pagination-nav` rules (to be removed)
- Server-side: API handler for timeline data (needs offset/limit support)

## Gap Protocol

- Research-acceptable gaps: exact API pagination parameters, current page size
- Stop-immediately gaps: if API doesn't support offset-based pagination
- Max research subagents before stopping: 1
