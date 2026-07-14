# Nightshift Report — SPEC-BUG-154

## Summary Stats

- Spec: SPEC-BUG-154 — Commit-msg hook accepts `SPEC-BUG-*` IDs
- Type/layer: bugfix / layer 1
- Branch: `nightshift/SPEC-BUG-154`
- Worktree: `/Users/ed/Dropbox/Developer/Repos/shipyard/.nightshift/worktrees/SPEC-BUG-154`
- Base commit: `b617aa9ba5d740a1e77e3ed496be00f3352e0563`
- Result: completed
- Focused hook validation: 5 passed, 0 failed
- Go package test gate: 14 packages passed, 0 failed

## Per-Spec Changes

- Updated `.nightshift/hooks/commit-msg` to accept bracketed Shipyard/Nightshift
  IDs with known hyphenated prefix families, including `SPEC-BUG-*`, while still
  requiring a bracketed numeric ID.
- Added `.nightshift/hooks/validate-commit-msg.sh`, a local validation wrapper
  that writes sample messages to temp files and invokes the hook directly without
  making real commits.
- Marked SPEC-BUG-154 requirements and acceptance criteria complete.
- Added a DevKB update proposal for future hook-regex changes.

## Test Results

- PASS — `.nightshift/hooks/validate-commit-msg.sh`
  - `PASS: accepts SPEC-BUG ID`
  - `PASS: accepts existing numeric child spec ID`
  - `PASS: rejects missing bracketed spec ID`
  - `PASS: rejects malformed spec ID`
  - `PASS: rejects unbracketed status commit`
  - `Summary: 5 passed, 0 failed`
- PASS — `go test ./...`
  - 14 Go packages passed; 1 package reported `[no test files]`.
  - macOS linker emitted deployment-version warnings for `cmd/shipyard`, but the
    command exited 0.
- PASS — `go vet ./...`
- PASS — `go build ./...`
  - macOS linker emitted deployment-version warnings for `cmd/shipyard`, but the
    command exited 0.

## Acceptance Criteria Checklist

- [x] AC1: `[SPEC-BUG-154] fix: accept SPEC-BUG commit IDs` passes validation.
- [x] AC2: `fix: missing traceability prefix` fails validation.
- [x] AC3: `[SPECBUG-154] fix: malformed spec prefix` fails validation.
- [x] AC4: Validation command and expected examples are documented here.

## Blockers / Discoveries

- No blockers.
- Discovery: Shipyard ignores `.nightshift/**` except selected spec files, so the
  hook and focused validation script need to be explicitly staged for this
  branch.
- Discovery: the installed main-checkout hook already had a broader local regex
  than the ignored source copy, but it still rejected `SPEC-BUG-*`. The source
  copy is now the artifact under review.

## Suggested Follow-up Specs

None.
