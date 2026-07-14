# DevKB Update Proposal — shell.md / git.md

## Commit-message hook regexes should validate the project's real spec ID grammar

**Problem:** A local `commit-msg` hook rejected valid Shipyard commits such as
`[SPEC-BUG-154] fix: ...` because the regex only accepted numeric `SPEC-*`
prefixes.

**Root Cause:** The hook encoded an older example grammar (`SPEC-NNN`) instead
of the repo's actual spec ID grammar, which includes hyphenated prefixes such as
`SPEC-BUG-*` and standing IDs like `UX-*`.

**Fix:** Keep the hook thin, but validate sample messages through it with temp
files. Include positive examples for every accepted prefix family and negative
examples for missing, malformed, and unbracketed status-style messages.

**Prevention:** When changing a git hook regex, add a focused no-commit
validation script next to the hook and run it in reports. Do not rely on visual
regex inspection.
