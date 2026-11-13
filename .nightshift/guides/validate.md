Load when: you run `/nightshift validate`: checking that `.nightshift/` is well-formed before a run or after setup changes.
Covers: every validate check (protocol files, config, commands, specs, dependencies, Git setup) and the report format.
Not here: external reachability and fleet provenance (`/nightshift doctor`), spec-to-code alignment (`/nightshift sync`).
Requires: an installed `.nightshift/` in the project.

# Validate guide

Verifies `.nightshift/` is well-formed and ready to run. Perform each check, report pass/fail, and provide specific fix suggestions for failures.

### Check 1: Required protocol files

Verify these exist: BOOTSTRAP.md, LOOP.md, ORCHESTRATOR.md, REVIEW.md, HUMAN-REVIEW.md, config.yaml. Optional but recommended: WATCHER.md, LOOP-DOMAIN-MAP.md, SPEC-GUIDE.md. Report each individually.

### Check 2: config.yaml structure

Parse as YAML. Verify required sections exist: `project` (name, language), `commands` (build, test, lint), `review` (enabled), `runner` (mode). Check that no required command is empty string or missing. Flag if `type_check` is empty for typed languages (TypeScript, Python with mypy, etc.).

### Check 3: Commands execution

Run each configured command and check exit codes. Install dependencies first if needed (npm install, pip install, etc.). Report each command's result. Distinguish between "command fails because code has issues" (warning) vs "command not found" (critical — tool not installed).

### Check 4: Spec integrity

For each spec in `specs/`:
- Parse frontmatter: required fields (id, priority, layer, type, status, created)
- Check ID uniqueness across all specs. Fleet-wide ID collisions are warning-only
  findings emitted by `validate_specs.py`; inspect that command's output for
  colliding project paths.
- Check status is valid enum (draft/ready/in_progress/done/blocked)
- For `status: ready` specs: verify all sections exist (Problem, Requirements, AC, Context, Out of Scope)
- Flag specs with requirements but no matching ACs

### Check 5: Dependency resolution

Build dependency graph from `after:` fields. Check for: circular dependencies, references to non-existent spec IDs, layer violations (spec in layer 2 depending on spec in layer 3).

### Check 5b: Duplicate specs

Run `python3 .nightshift/check_followup_spec.py --specs-dir .nightshift/specs --scan-all`. Exit 0 = clean; exit 1 = near-duplicate pairs found (title and/or requirement/AC body overlap above threshold). Report each pair so the user can retire or merge the duplicate. This is the disk-level backstop for duplicates that bypassed the per-suggestion follow-up gate.

### Check 6: Git integration

- Pre-commit hook: exists at `.git/hooks/pre-commit`, is executable, references config.yaml commands
- `.gitignore`: has entries for `_wip/`, `STOP`, `checkpoints/`
- Git repo exists (warn if no `.git/`)

### Check 7: Knowledge health

- Knowledge directory exists with expected subdirs (patterns/, attempts/, _review/)
- Review persona docs exist in `_review/` if personas are enabled in config
- Flag empty knowledge files (created but never populated)

**Output format:** Per-check pass/fail table, then detailed findings with specific fix commands the user can run.
