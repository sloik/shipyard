# Nightshift Report — SPEC-BUG-166

## Summary

Implemented one canonical runtime path. Smoke executables now build below the
ignored `build/smoke/` directory, while `bin/shipyard` is reserved as the only
launchd runtime executable. Added a guarded `make deploy-runtime` migration
that smoke-tests first, verifies launchd's active program path, and archives
legacy executables only after that proof.

## Changes

- `Makefile`: smoke output path and `deploy-runtime` target.
- `.gitignore`: retain only `bin/shipyard`; ignore smoke output.
- `scripts/deploy-canonical-runtime.sh`: safe launchd migration and recovery.
- `README.md`: canonical build, smoke, and deployment documentation.

## Verification

- `npm ci && make smoke-full` — PASS (Tool Browser and Servers browser smoke).
- `go test ./...` — PASS.
- `go vet ./...` — PASS.
- `go build ./...` — PASS.
- `go test -race -count=1 ./...` — PASS.
- `zsh -n scripts/deploy-canonical-runtime.sh` — PASS.
- All Go linker warnings only note the host SDK deployment-target mismatch.

## Acceptance Criteria

- [x] AC-1: migration command leaves only executable `bin/shipyard`.
- [x] AC-2: both smoke targets passed with executables in `build/smoke/`.
- [ ] AC-3: requires post-merge canonical-checkout deployment; the isolated
  worktree must not replace the live service.
- [ ] AC-4: requires the same live post-merge deployment verification.
- [x] AC-5: required Go verification suite passed.

## Blockers / discoveries

The current live LaunchAgent points to `bin/shipyard-fixed`. Its migration is
intentionally deferred until this worktree's commit is merged into the canonical
checkout, because installing from an isolated worktree would violate the
runtime's canonical-path requirement.

## Suggested Follow-up Specs

None.
