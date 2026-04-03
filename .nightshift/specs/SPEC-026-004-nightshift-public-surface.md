---
id: SPEC-026-004
priority: 4
layer: 3
type: feature
status: ready
after: [SPEC-026-009]
parent: SPEC-026
nfrs: [NFR-003]
prior_attempts: []
created: 2026-03-31
---

# Nightshift Public Surface

## Problem

The `.nightshift/` directory contains internal specs, private metrics, failure persistence data, and orchestration files that are useful for the maintainer but confusing or irrelevant for public contributors. The public repo should expose only what contributors need: the spec format, how to propose changes, and how the spec-driven workflow operates. Internal operational files should be excluded.

## Requirements

- [x] Define which `.nightshift/` files are public vs. private
- [x] Add `.nightshift/` entries to .gitignore for private files (metrics/, failure_persistence.py, internal hooks)
- [x] Keep public: spec templates (_TEMPLATE*.md), SPEC-GUIDE.md, README.md explaining the workflow
- [x] Remove or .gitignore: metrics/, hooks/ (internal), analyze_metrics.py, propagate_scores.py, validate_metrics.py, nightshift-dag.py
- [x] Rewrite `.nightshift/README.md` for contributors: what specs are, how to propose one, what the lifecycle is
- [x] Ensure the LOOP.md / ORCHESTRATOR.md / WATCHER.md files are either excluded or rewritten for public context

## Acceptance Criteria

- [x] AC 1: `.gitignore` excludes `.nightshift/metrics/`, `.nightshift/hooks/`, `.nightshift/*.py`
- [x] AC 2: `.nightshift/README.md` exists and explains the spec workflow for external contributors
- [x] AC 3: All `_TEMPLATE*.md` files are present and contain no private/internal references
- [ ] AC 4: `.nightshift/LOOP.md`, `.nightshift/ORCHESTRATOR.md`, `.nightshift/WATCHER.md` are either gitignored or rewritten to be contributor-friendly
- [ ] AC 5: No private metrics data (JSON files with session data, scores, etc.) is committed
- [x] AC 6: A contributor reading only the public `.nightshift/` files can understand how to write and submit a spec

## Context

- Current `.nightshift/` contents include operational automation (LOOP.md, ORCHESTRATOR.md, WATCHER.md) used by Nightshift for automated spec execution
- Metrics files track spec execution history, scores, and failure patterns — all internal
- The spec templates are valuable for contributors and should remain
- SPEC-GUIDE.md (if it exists) explains how to write specs — keep it
- Decision: whether to keep the Nightshift workflow concept visible (educational) or hide it entirely (simpler)

## Scenarios

1. Contributor opens `.nightshift/` → sees README.md → understands "specs drive development" → sees templates → copies one → writes a spec → submits PR
2. Maintainer runs Nightshift locally → private files exist in their working copy but are gitignored → automation works as before → public repo stays clean
3. Contributor sees a `status: done` spec → understands it was completed → reads it to learn about the feature's design rationale

## Out of Scope

- Rewriting Nightshift automation to work differently for public contributors
- Publishing the Nightshift toolchain as a separate package
- Removing Nightshift from the project entirely

## Notes for the Agent

- Start by listing all files in `.nightshift/` to understand the full surface
- The goal is subtraction: remove what doesn't help contributors, keep what does
- Private files should be .gitignored, not deleted — the maintainer still uses them locally
- Ignore rules and contributor docs are in place, but tracked private files still need index cleanup. `git rm --cached` was blocked by the Dropbox/FUSE `index.lock` restriction in this environment, so AC 4 and AC 5 remain open until that cleanup is run successfully.
