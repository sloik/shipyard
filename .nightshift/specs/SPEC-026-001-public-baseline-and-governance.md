---
id: SPEC-026-001
priority: 1
layer: 3
type: feature
status: done
after: [SPEC-025]
parent: SPEC-026
nfrs: [NFR-003]
prior_attempts: []
created: 2026-03-31
---

# Public Baseline and Governance

## Problem

The Shipyard repository contains personal paths, private references, and internal tooling assumptions that cannot be exposed publicly. Before any other migration work, the repo must be audited and cleaned, and standard open-source governance files must be added. Without this, pushing to a public GitHub repo would leak private information.

## Requirements

- [ ] Audit all committed files for personal paths (e.g., `/Users/<username>/`, `~/projects/`), API keys, tokens, and private references
- [ ] Remove or parameterize all hardcoded personal paths in source code and configuration
- [ ] Audit git history for leaked secrets (if history will be preserved; alternatively, plan a squashed initial commit)
- [ ] Add MIT LICENSE file to repository root
- [ ] Add CONTRIBUTING.md with contribution guidelines (PR process, code style, testing requirements)
- [ ] Add CODE_OF_CONDUCT.md (Contributor Covenant or equivalent)
- [ ] Add .gitignore entries for common secret files (.env, *.key, credentials.json, etc.)
- [ ] Verify no test fixtures contain real credentials or personal data

## Acceptance Criteria

- [ ] AC 1: `grep -rn '/Users/<username>' .` returns zero matches in tracked files (excluding .git/)
- [ ] AC 2: `grep -rn` for private path patterns returns zero matches in tracked files
- [ ] AC 3: LICENSE file exists at repo root and contains MIT license text
- [ ] AC 4: CONTRIBUTING.md exists and covers: how to submit PRs, code style, testing, spec workflow
- [ ] AC 5: CODE_OF_CONDUCT.md exists at repo root
- [ ] AC 6: .gitignore includes entries for .env, *.key, credentials.json, and xcuserdata/
- [ ] AC 7: All test fixtures use synthetic/mock data only
- [ ] AC 8: Project builds successfully after all path changes

## Context

- Personal paths are likely in: test fixtures, configuration files, manifest.json examples, comments
- MCPRegistry.swift and related services may have hardcoded discovery paths
- ShipyardBridge may reference specific socket paths
- The `.nightshift/` directory will be separately narrowed in SPEC-026-004
- Decision needed: preserve full git history (requires BFG or git-filter-repo) vs. squashed initial public commit

## Scenarios

1. Contributor clones the public repo → builds with `xcodebuild` → no path errors referencing private directories → build succeeds
2. Security researcher runs `trufflehog` or similar on the repo → zero high-confidence secret findings
3. New contributor reads CONTRIBUTING.md → understands PR process → submits a well-formed PR following the guide

## Out of Scope

- CI/CD setup (separate spec)
- README rewrite (SPEC-026-005)
- Nightshift surface narrowing (SPEC-026-004)
- Actual public push to GitHub (manual step after all specs complete)

## Notes for the Agent

- Start by running `grep -rn '/Users/' .` and searching for private path patterns across the repo to find all personal path references
- Check Package.swift, any .plist files, and Xcode project settings for hardcoded paths
- The git history decision (preserve vs. squash) should be documented as a recommendation, not implemented — that's a manual decision for the maintainer
