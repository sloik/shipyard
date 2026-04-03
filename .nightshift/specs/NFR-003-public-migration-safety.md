---
id: NFR-003
priority: 1
layer: 0
type: nfr
status: active
created: 2026-03-31
---

# Public Migration Safety

## Constraint

All changes in the SPEC-026 migration must satisfy these invariants:

1. **No data loss** — existing MCP configurations, secrets, and user preferences must survive the migration intact. If a migration step fails partway, the original data must remain readable.
2. **Rollback possible** — every destructive operation (manifest deprecation, file moves, config rewrites) must be reversible. Either keep the original files or write a backup before modifying.
3. **Existing setups continue working** — a user who updates Shipyard must not find their MCPs broken. The one-time importer must run automatically on first launch after update, and manual intervention should only be needed if the import fails.
4. **No secrets in public repo** — no API keys, personal paths (e.g., `/Users/<username>/`), tokens, passwords, or private references in any committed file. This includes code comments, test fixtures, configuration files, and git history.
5. **No silent failures** — if a migration step fails, it must log a clear error and surface it to the user (system log, alert, or both). Silent data loss is the worst outcome.

## Rationale

Shipyard manages MCP configurations that users depend on daily. A botched migration that loses configs or exposes secrets would destroy trust in the project. The migration must be invisible to existing users (everything just works after update) and safe for new public users (no leaked private data).

## Scope

- All SPEC-026 sub-specs (001 through 009)
- Any file committed to the public repository
- Git history (must be audited or cleaned)
- One-time import mechanism (manifest.json to mcps.json)
- PathManager and binary setup
- Documentation and templates

## Verification

- [ ] V1: After running the importer, all previously-configured MCPs appear in mcps.json and function correctly
- [ ] V2: Deleting mcps.json and re-running the importer from the original manifest.json produces identical results
- [ ] V3: `git log --all -p | grep -i` for common secret patterns (API key formats, /Users/<username>/, hardcoded tokens) returns zero matches in the public branch
- [ ] V4: A fresh clone of the public repo builds and runs without requiring any private files or paths
- [ ] V5: Simulating a failed import (kill process mid-write) leaves the original manifest.json intact and re-import succeeds on next launch
- [ ] V6: Every migration step logs its action to the system log with enough detail to diagnose failures

## Known Violations

None (constraint is new, defined alongside SPEC-026).

## References

- SPEC-026 (parent migration spec)
- SPEC-019 (config MCPs implementation — the mcps.json format)
- MCPRegistry.swift (current manifest discovery logic)
