---
id: SPEC-BUG-169
template_version: 7
priority: 1
layer: 0
type: refactor
status: done
after: [SPEC-BUG-159]
provides: [offline-govulncheck-negative-fixture]
requires: [vulnerability-gate]
touches: [Makefile, scripts, test/security-fixtures]
prior_attempts: []
nfrs: [SPEC-NFR-001]
parent: SPEC-BUG-159
created: 2026-08-08
stack: go
domain: code
output_type: test
---

# Add a Locked Offline govulncheck Advisory Fixture

## Problem

SPEC-BUG-159 proves the `govulncheck` command path fails closed, but its
negative fixture does not exercise a locked local advisory database.

## Requirements

- [ ] R1: Provide a version-controlled local advisory fixture compatible with
  the supported govulncheck release.
- [ ] R2: Prove a known reachable vulnerable dependency fails without network
  access.
- [ ] R3: Keep production scanner configuration unchanged.

## Acceptance Criteria

- [ ] AC1: The offline fixture causes govulncheck to exit nonzero deterministically.
- [ ] AC2: The fixture runs without live advisory or module access.
- [ ] AC3: `make security-self-test` documents and executes the offline probe.

## Context

Created from SPEC-BUG-159's follow-up report. If govulncheck lacks a stable
offline database flag, document that constraint and retain the command-path
probe rather than emulating production behavior.
