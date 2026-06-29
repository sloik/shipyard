---
id: SPEC-BUG-154
template_version: 4
priority: 3
layer: 1
type: bugfix
status: in_progress
parent: SPEC-BUG-151
after: [SPEC-BUG-151]
nfrs: []
devkb_required: [git.md, shell.md, testing.md]
prior_attempts: []
attachments: []
created: 2026-06-29
---

# Commit-msg hook accepts `SPEC-BUG-*` IDs

## Problem

Shipyard uses `SPEC-BUG-*` IDs for many tracked bug and follow-up specs, but the
installed Nightshift `commit-msg` hook rejects commit messages that start with an
exact spec ID such as `[SPEC-BUG-151]`. SPEC-BUG-151 had to use `--no-verify`
for its worker commit despite using the correct ID, which weakens the intended
traceability guard.

## Requirements

- [ ] R1: The commit-message hook accepts exact Shipyard spec IDs with hyphenated
  prefixes, including `[SPEC-BUG-154]`.
- [ ] R2: The hook still rejects malformed or missing spec IDs.
- [ ] R3: The hook behavior is covered by a local validation script or focused
  test command that can be run without making real commits.
- [ ] R4: Existing Nightshift status commits (`chore: mark <spec-id> ...`) are
  not made less strict by this change.

## Acceptance Criteria

- [ ] AC1: A message like `[SPEC-BUG-154] fix: accept SPEC-BUG commit IDs`
  passes the commit-message validation.
- [ ] AC2: A message with no bracketed spec ID still fails.
- [ ] AC3: A message with a malformed ID still fails.
- [ ] AC4: The validation command and expected examples are documented in the
  run report.

## Context

Created from the `## Suggested Follow-up Specs` section of
`.nightshift/reports/2026-06-29-nightshift-report.md` after SPEC-BUG-151.

Likely target files:
- `.nightshift/hooks/commit-msg`
- Any existing or new focused hook validation script/test under `.nightshift/`

NFR review: `SPEC-NFR-001` (zero data races) does not apply because this is a
shell/git hook validation change; no Go concurrency behavior is involved.

## Live Execution Checklist

- Exercise the commit-message hook or a focused validation wrapper with passing
  and failing sample messages.
- Do not rely only on visual inspection of the regex.

## Out of Scope

- Rewriting the full Nightshift hook system.
- Changing GitHub Actions or Go CI.
- Loosening project traceability requirements beyond accepting valid Shipyard
  spec ID formats.

## Gap Protocol

- Research-acceptable gaps:
  - Exact existing hook regex and where helper tests should live.
- Stop-immediately gaps:
  - Allowing commits with no spec traceability.
  - Changing unrelated hooks.
- Max research subagents before stopping: 0
