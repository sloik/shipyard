Load when: you run `/nightshift doctor`: diagnosing a broken, invisible or stale install, or applying its bounded `--fix` repairs.
Covers: the doctor invocation and exit codes, the managed-payload provenance audit, and findings D7 and D8 with the write-scope hook harness coverage.
Not here: install soundness of one project's own files (`/nightshift validate`), releasing a kit (`release.md`).
Requires: an install or fleet root to inspect; the kit's `doctor.py`.

# Doctor guide

Run `"$HOME/Dropbox/Developer/ManagedProjects/Nightshift/canonical/.board-venv/bin/python" "$HOME/Dropbox/Developer/ManagedProjects/Nightshift/doctor.py" <project>` for one install, or add `--fleet` to inspect every configured discovery root plus their shared parent (so sibling projects can be found). Add `--fix` only for mechanical repairs: missing discovery-list entries, absent kit files, and a bootstrap `_eval-project/`. It never overwrites a different existing managed file and never changes spec content, status, project config values, or the Git index. Exit codes are 0 clean, 1 warnings, and 2 CRITICAL findings.

Doctor extends validate: use validate for the install's own protocol/config/command integrity; use doctor for external reachability, kit freshness, bootstrap residue, board reachability, cross-directory spec hygiene, and the read-only managed-payload provenance audit. The audit reports `exact-current`, `retained-prior-release`, or `unresolved-divergence` using per-file hashes only. Preserve unresolved paths and route reusable work through a canonical Nightshift spec and whole-kit release; never infer ownership from timestamps, similarity, status text, or an aggregate fingerprint.

Finding `D7` (WARNING, SPEC-300-003) fires when the kit ships
`hooks/protect-write-scope.sh` but the target repository's common-dir
pre-commit hook does not carry the `# SPEC-300-003 protect-write-scope`
marker — the git write-scope guard is uninstalled there. `doctor --fix` runs
`hooks/install-write-scope-guard.sh` for that repository and records the
action; like every other `--fix` repair, it never edits a pre-commit hook it
does not recognise — the installer's own refusal message becomes the
finding's remedy text, and a human merges the guard into that hook by hand.

Finding `D8` (WARNING, SPEC-300-004) fires when the kit ships
`hooks/write-scope-hook.sh` but the target repository's
`.claude/settings.json` has no `nightshift-write-scope`-marked `PreToolUse`
entry — the Claude Code harness hook is uninstalled there. `doctor --fix`
runs `hooks/install-write-scope-hook.sh` for that repository. If the
repository has no `.claude/` directory at all, the finding still reports —
its remedy is a manual step, and `--fix` does not create `.claude/`
automatically.

**Harness coverage (SPEC-300-004 R8):** `hooks/write-scope-hook.sh` is a
Claude Code `PreToolUse` hook — Claude Code is the only harness in the
current matrix that exposes a pre-write tool hook. Codex and Hermes runs have
no equivalent interception point today; they rely entirely on the git
pre-commit write-scope guard (SPEC-300-003) and the evidence gate
(SPEC-300-002) to catch an out-of-scope write, always after the write has
already landed on disk rather than before. The terminal lifecycle commit's
`Nightshift-Scope-Check:` trailer (SPEC-300 R11 / SPEC-300-002) records the
outcome either way, so a reviewer can tell which layer actually caught (or
missed) a violation regardless of which harness ran the worker.

Even on Claude Code, where the hook does exist and is installed, its
spec-scoped rules are presently unreachable for a harness-launched
(`isolation: "worktree"`) worker — see "Known, accepted gap —
`NIGHTSHIFT_ACTIVE_SPEC` does not reach the `PreToolUse` hook for a
harness-launched worker (SPEC-300-004-001)" under Step 5 above for the
definitive answer and its evidence. Only the hook's two universal rules
fire in that case; the git guard and evidence gate remain the working
backstops.
