# Autonomous Execution Loop

**Kit Version:** 2.56.0 | **Date:** 2026-07-27
**Purpose:** The heart of the Nightshift Kit. This document describes the full 16-step autonomous cycle that an agent follows to complete a single spec and move to the next one.

---

## Overview

The loop is designed to be followed by any agent that can:
- Read and write files
- Run shell commands
- Make decisions based on file content

The loop runs unsupervised overnight, producing code, tests, metrics, and reports. It is self-contained and technology-agnostic — it works for Swift, Python, TypeScript, Rust, or any other language. It also works for non-code domains: research (source gathering, synthesis, fact-checking), analysis (data processing, financial statements), and others.

**Key principle:** Static tools (linters, type checkers, formatters, build commands) are free. They provide feedback without burning LLM tokens. The loop maximizes their use — run them after every code change, not just at the end.

**Domain flexibility:** The 16-step structure applies to code, research, and analysis domains. When the effective domain is not `code`, read `LOOP-DOMAIN-MAP.md` for step-by-step domain mappings. The loop skeleton (spec → plan → execute → validate → knowledge) is universal; only the activities within each step change.

**Git policy:** Git workflow semantics live in `GIT.md`. This loop references that file for dirty-tree handling, status commits, commit format, hooks, worktrees, merge behavior, and human-review expectations.

---

## Domain Resolution

The effective domain for each spec is resolved via a three-level cascade:

1. **Spec-level** (`domain:` in spec frontmatter) — highest priority, set by spec author
2. **Stack-level** (`stacks.<stack>.domain` in config.yaml) — inherited from the stack profile
3. **Project-level** (`runner.domain` in config.yaml) — project-wide default
4. **Fallback** — `"code"` if none of the above are set

```
effective_domain = spec.domain or stack_profile.domain or config.runner.domain or "code"
```

This means:
- A single Nightshift run CAN interleave research and code specs
- Domain switches per-spec, not per-run — no restart or reconfiguration needed
- Steps 1, 4, 5, 7, 8, 9, and 10 use `effective_domain` to select behavior from LOOP-DOMAIN-MAP.md
- All other steps remain domain-agnostic

---

## Null Command Policy

**Problem:** When a `commands.*` field in config.yaml is `null` or missing, the agent may silently skip the corresponding quality gate. This creates invisible gaps — no tests, no linting, no type checking — with no warning to the human.

**Rule:** No null command is silently skipped. Every null command triggers one of:
1. **WARN** — log a warning in metrics and proceed (acceptable gap)
2. **SUGGEST** — log a warning AND propose a fix (fixable gap)
3. **GATE** — stop and create a spec to fix it (critical gap)

| Null command | Severity | Action |
|---|---|---|
| `commands.test` | **GATE** | Create SPEC-000-testing if one doesn't exist. Propose a test framework: Playwright for HTML/JS, pytest for Python, swift test for Swift, cargo test for Rust, npm test for TS/JS. Log: `preflight.note: "No test suite — SPEC-000-testing created"`. Proceed with remaining specs but flag every subsequent spec with `untested: true` in metrics. |
| `commands.build` | WARN | Log: `preflight.note: "No build command configured"`. Acceptable for static projects (HTML, scripts). Proceed. |
| `commands.lint` | SUGGEST | Log: `preflight.note: "No lint command — consider adding one"`. Suggest: ESLint for JS/TS, ruff for Python, swiftlint for Swift, clippy for Rust. Proceed without linting. |
| `commands.type_check` | WARN | Log: `preflight.note: "No type check configured"`. Acceptable for dynamically typed or simple projects. Proceed. |
| `commands.format` | WARN | Log: `preflight.note: "No format check configured"`. Proceed. |

**Test framework defaults by language:**

| Language | Default test command | Framework |
|---|---|---|
| HTML/CSS/JS | `npx playwright test` | Playwright |
| Python | `python -m pytest tests/ -v` | pytest |
| Swift | `swift test` | XCTest |
| Rust | `cargo test` | cargo test |
| TypeScript/JS | `npm test` or `npx vitest` | vitest/jest |
| Go | `go test ./...` | go test |

---

## Adaptive Mode (Optional)

**NEW in Phase 7.1:** If `config.yaml` → `runner.adaptive: true` AND `.nightshift/execution_graph.yaml` exists:

1. At step 2 (after task selection), compute complexity from the spec metadata:
   - **Low:** ≤3 ACs, single-file changes
   - **Medium:** 4-8 ACs, multi-file but not architectural
   - **High:** 9+ ACs or architectural changes

2. Build context dict:
   ```python
   context = {
       "domain": effective_domain,  # per-spec, see § Domain Resolution
       "complexity": complexity_computed_above,
       "spec": {"has_tests": bool, "ac_count": int},
       "config": {"watcher": {"enabled": bool}, "review": {"mode": str}},
       "diff_lines": estimated_or_zero_at_step_2
   }
   ```

3. Run: `python3 graph_engine.py --context '<json>' .nightshift/execution_graph.yaml`

4. The output is the ordered list of steps to execute. Follow ONLY those steps — skip all others.

5. Log the skipped steps in metrics: `phases.execution_mode: "adaptive"` and `phases.skipped_steps: [...]`

**If adaptive mode is off (default) or graph file missing:**
- Run all 16 steps as documented below
- Set `phases.execution_mode: "sequential"` in metrics

This allows the loop to be **right-sized** for the task: research specs skip code testing, simple fixes skip reviews, and complex features run the full pipeline.

---

## The 16-Step Cycle

### Resume from Checkpoint (if applicable)

Before starting step 1, check for existing checkpoints for the current spec:

1. **Scan for checkpoints:** Look for `.nightshift/checkpoints/<current-spec-id>/latest.json`
2. **If it exists:** A previous run crashed or was interrupted mid-spec
3. **Load the checkpoint:** Read the checkpoint file it points to
4. **Resume from the next step:** Start from the step AFTER the checkpoint's step number
5. **Skip already-completed steps:** Do not repeat steps that are marked as completed in the checkpoint
6. **Inherit context:** Use working notes, citations, and metrics from the checkpoint as your baseline

**How to resume:**
```
import checkpoint
cp = checkpoint.load_latest_checkpoint(spec_id)
if cp:
    # Print resumption instructions
    print(checkpoint.get_resume_instructions(cp))
    # Start loop from step (cp['step'] + 1)
```

---

### 1. Pre-Flight Check

#### Phase 0-A.clock: Shell Timestamp Capture (SPEC-047)

The very first side-effect of Step 1 is to capture the loop start time via a
real shell call and write it to `events.jsonl`. `metrics_fidelity.py`
cross-checks the metrics YAML against these shell-captured values at Step 14,
so if this event is missing or drifts the fidelity warnings will surface it.

```bash
# MANDATORY — first action in Step 1, before any other side-effect.
STEP1_EPOCH=$(date -u +%s)
```

```python
# Step 1 runs before Task Selection, so no spec_id exists yet — emit None.
# Per-spec start anchors are not part of SPEC-047 R2; Step 1 captures the
# run-level baseline. metrics_fidelity.py compares first-spec started_at
# against this epoch; later specs fall back to the nearest available event.
events_logger.emit(
    "step_timestamp",
    spec_id=None,
    step=1,
    phase="preflight_start",
    epoch=int(os.environ["STEP1_EPOCH"]),
)
```

The same pattern repeats at Step 13 start and Step 16 end — see those steps
for their capture blocks. Never fabricate an epoch; if the shell call fails,
omit the event (validator will flag the absence as `timestamp_drift_vs_shell`
rather than a silent accept).

#### Phase 0-A: Environment Probe

This sub-phase covers the side-effect-free environment checks: git clean check, tool availability, and the orchestrator precondition. If this sub-phase blocks, write a BLOCKED report with `failure_class: "environment"` and stop before baseline execution.

#### Phase 0-A.history: Cross-Project History DB Preflight (SPEC-040)

Before any spec runs, verify the cross-project execution history database at `~/.nightshift/history.db` is usable. This catches a future-version schema early, before model time is spent.

```python
from execution_history import ensure_schema, SchemaVersionError
try:
    ensure_schema()  # creates ~/.nightshift/ + history.db if absent, migrates forward
except SchemaVersionError as exc:
    # DB was written by a newer version of execution_history.py — refuse.
    raise SystemExit(f"Nightshift history DB is newer than this kit: {exc}")
except OSError as exc:
    # Write-permission denied or disk full — log a warning and proceed.
    # Ingestion in Step 16 will attempt again; a hard failure here is not
    # proportionate to the value of history collection.
    print(f"warning: history DB preflight failed ({exc}); Step 16 may skip ingest", file=sys.stderr)
```

Forward migrations are idempotent, so re-running this on an existing DB is a no-op. A `SchemaVersionError` is a hard stop — do not try to heal it automatically.

#### Phase 0-A.handlers: Custom Handler Preflight (SPEC-041)

Before any spec runs, instantiate the handler registry once and merge in any
custom handlers declared in `config.yaml`. Registry construction is cheap and
guarantees every Step 2 dispatch sees the same set of handlers.

```python
from handler_registry import create_default_registry, load_custom_handlers

registry = create_default_registry()
if config.get("handlers"):
    try:
        load_custom_handlers(registry, config)
    except Exception as exc:
        # Non-fatal: defaults still work. Log and continue — this matches
        # SPEC-041 AC5 ("Custom handler module missing from sys.path").
        events_logger.emit(
            "custom_handler_load_failed",
            spec_id=None,
            error=str(exc),
        )
```

Two `config.yaml` shapes are supported (either is valid):

```yaml
# SPEC-041 flat form — domain is the registry key
handlers:
  - module: ./my_deploy_handler.py
    class: DeployHandler
    domain: deploy
```

```yaml
# SPEC-033 nested form — name is the registry key
handlers:
  custom_handlers:
    - name: deploy
      module: ./my_deploy_handler.py
      class: DeployHandler
```

Failure to load a custom handler must NOT crash the loop — emit
`custom_handler_load_failed` to `events.jsonl` and proceed with whatever
handlers did register (at minimum the three built-ins: `code`, `research`,
`analysis`).

#### Phase 0-A.outcomes: Outcome-Router Policy Preflight (SPEC-042)

Before any spec runs, resolve the active outcome-routing policy set once. The
policy table is immutable for the remainder of the run — policies are fixed
at preflight by design (see SPEC-042 "Out of Scope: Policy hot-reload").

```python
from outcome_router import load_policies

# Spec frontmatter is unknown at preflight, so pass {} — per-spec frontmatter
# can still override at Step 2 if desired, but by default Phase 0-A.outcomes
# establishes the run-wide defaults.
outcome_policies = load_policies(spec_frontmatter={}, config=config)
```

Config supports two aliases:

```yaml
# SPEC-042 friendly alias (preferred in docs):
outcomes:
  defaults:
    - outcome: TEST_FAIL
      action: retry
      retry: {max_retries: 2, backoff: exponential, base_s: 5, max_s: 60}
    - outcome: REVIEW_REJECTED
      action: escalate
    - outcome: BUILD_FAIL
      action: retry
      retry: {max_retries: 1, backoff: linear, base_s: 5, max_s: 10}

# SPEC-034 canonical form — still fully supported, identical semantics:
outcome_routing:
  defaults: [ ... same entries ... ]
```

If neither key is set, `load_policies` returns `DEFAULT_POLICIES` — this
matches SPEC-042 AC5 (no config → module defaults → existing behavior
preserved).

#### Phase 0-A.schema: Config Schema Version Assertion (SPEC-044)

Before any spec runs, check the project's `config.yaml` schema version. Configs
without `schema_version` (or with a version below 3.0.0) predate the multi-stack
schema and cannot activate per-stack command selection (SPEC-024), per-spec
domain resolution (SPEC-025), or Phase 3 specs (SPEC-026/027/028).

This check emits a WARNING event but does **not** block — projects that use only
the flat `commands:` block remain fully functional at v2.2.1, and migration is
opt-in.

```python
from nightshift_sync import check_schema_outdated  # or the local helper

result = check_schema_outdated(project_root / ".nightshift" / "config.yaml")
if result["event"] == "config_schema_outdated":
    events_logger.emit(
        "config_schema_outdated",
        spec_id=None,
        schema_version=result["schema_version"],
        message=result["message"],
    )
# Always continue — the event is informational, not a gate.
```

The event payload MUST include:

- `schema_version` — the value read from the config (may be `None` if absent)
- `message` — human-readable recommendation, typically suggesting
  `nightshift-sync.py --migrate-config --apply`

If `config.yaml` doesn't exist at all, the check returns no event — projects
may genuinely have no nightshift config (rare but permitted).

Migration (one-shot, offline):

```bash
# Dry-run preview:
python3 nightshift-sync.py --migrate-config

# Apply:
python3 nightshift-sync.py --migrate-config --apply
```

Idempotent — re-running against an already-migrated project is a no-op and
writes no new log file.

#### Step 1.x: Pre-Flight for Orchestrator with Main Specs (NEW — Hierarchical Specs)

If running in orchestrator mode (`config.yaml → runner.mode: "orchestrator"`) and a main spec is selected:

1. Check: does `execution-plan.json` exist in `specs/`?
2. If yes: verify `source_spec` matches the selected spec → proceed
3. If no: log instruction — `Run: nightshift-dag plan <SPEC-ID> --specs-dir specs/ first`
4. Continue with remaining pre-flight steps

This check ensures the DAG tool has validated dependencies before any model time is spent.

Also verify the configured commands are present before execution:
- `commands.test` must be configured (or the Null Command Policy applies)
- `commands.lint` / `commands.type_check` may be null, but only as documented warnings
- Missing tools or unavailable executables belong to `failure_class: "environment"`

> **Preferred mechanization (SPEC-089-001):** if `.nightshift/preflight.py` exists,
> run `python3 .nightshift/preflight.py --spec-id <id>` before the manual checks
> below. It captures clean-tree state, selected-spec status, dependency state, and
> baseline command outcomes in `metrics/<id>.preflight.json`. A non-zero exit is a
> Step 1 pre-flight failure; read the artifact's `blocking_failures` and follow the
> existing failure/test-gate flow below. If the script is unavailable, continue with
> the manual checks in this section.

#### Phase 0-B: Baseline Test Gate

**Domain scoping:** Pre-flight checks are scoped to the spec's `effective_domain` (see § Domain Resolution):
- `code` domain: run the standard baseline test gate below using stack commands
- `research` domain: skip build/test/lint; verify tool availability per LOOP-DOMAIN-MAP.md
- `analysis` domain: skip build/test/lint; verify data/tool availability per LOOP-DOMAIN-MAP.md

This sub-phase runs the baseline execution gate: `commands.test` is mandatory, lint/type-check are diagnostic only, and the gate allows up to 3 repair attempts before blocking. If this sub-phase blocks, write a BLOCKED report with `failure_class: "baseline_red"`.

**What to do:**
1. Verify git working tree is clean (no uncommitted changes)
   - If dirty: follow `GIT.md` § Baseline and Dirty Tree
2. Run the full test suite for the project (use `config.yaml` → `commands.test`)
   - **Apply the Test Timeout Protocol** (see section below Test Gate) to wrap the command if timeout is configured
   - This is a **GATE** — see "Test Gate" below
3. Run all static analysis tools (lint, type-check, format check)
   - These are **diagnostic only** — warn if failures are found, but do not stop
4. Log results: did tests pass? Any lint/type errors? Did any test hang occur?

**Why:** Establish a clean baseline. If tests are already failing, fix pre-existing failures before touching specs. An agent working from a broken state can't tell whether its changes broke something or whether it was already broken.

**Git:** No commits at this stage — just diagnostics. See `GIT.md` § Baseline and Dirty Tree.

**If pre-flight fails:**
- Read the error output carefully
- Attempt fixes (enable missing tool, install dependencies, etc.)
- Re-run pre-flight
- Proceed to Known Issue Handling (below) and then Test Gate

### Known Issue Handling (Orchestrator Mode)

If the orchestrator brief mentions a KNOWN ISSUE from a previous spec:

1. Run pre-flight normally (build + test)
2. If pre-flight PASSES → the known issue doesn't affect this spec, proceed normally
3. If pre-flight FAILS:
   a. Check if the failure matches the KNOWN ISSUE description
   b. If it matches → attempt a minimal fix using the error details from the brief
   c. Re-run pre-flight
   d. If pre-flight passes after fix → proceed (log the fix in metrics: `preflight.known_issue_fixed: true`)
   e. If still failing → this may be a different problem, proceed to Test Gate (3 attempts)
4. If pre-flight fails and there's NO known issue → proceed to Test Gate normally

---

### Test Gate (Hard Stop)

If after 3 fix attempts the test suite STILL fails:

1. **STOP** — do not proceed to step 2 (Task Selection)
2. Write a BLOCKED report to `reports/BLOCKED-preflight-<timestamp>.md`:
   ```markdown
   # Blocked: Pre-Flight Test Gate

   **When:** <ISO timestamp>
   **Attempt:** 3 fix attempts, all unsuccessful
   **Failure class:** environment | baseline_red | spec_validation | runtime_error | circuit_breaker

   ## Tests Failed
   - List test failures with names and error messages
   - Include stack traces or assertion failures

   ## Fix Attempts
   - Attempt 1: <brief description of what was tried + outcome>
   - Attempt 2: <brief description + outcome>
   - Attempt 3: <brief description + outcome>

   ## Root Cause Hypothesis
   Agent's best hypothesis about why the baseline is broken.
   (e.g., "Missing dependency X", "API endpoint Y is down", "Configuration file corrupted")

   ## What the Human Needs to Do
   Specific suggestions for unblocking:
   - Fix infrastructure issue X
   - Update environment variable Y
   - Install/enable missing tool Z
   - Clarify configuration requirement
   ```
3. Log metrics:
   ```yaml
   task_id: "PREFLIGHT"
   status: "blocked"
   failure:
     phase: "preflight"
     error_type: "baseline_red"
     description: "Test suite fails on clean baseline after 3 fix attempts"
     root_cause: "<agent's hypothesis>"
     suggestion: "<what the human should do>"
   ```
4. Exit the loop cleanly — **do not attempt any specs**

**Why this is a hard stop, not a skip:** An agent working from a broken baseline produces unreliable results. Every test failure during implementation could be pre-existing or new — the agent can't tell them apart. Better to wait for human intervention than to produce 8 hours of potentially worthless work on a foundation that's already broken.

**Exception:** If `config.yaml` → `commands.test` is empty or missing (no test suite configured):
1. **Apply the Null Command Policy** (see section above) — this is a GATE-level gap.
2. Check if `specs/SPEC-000-testing.md` already exists:
   - If yes: it will be picked up by Task Selection (Step 2) due to Layer 0 priority. Proceed.
   - If no: **create it now.** Use the Null Command Policy's language-to-framework table to propose the right test framework. Write the spec to `specs/SPEC-000-testing.md` with `layer: 0`, `priority: 0`, `status: ready`.
3. Log in metrics: `preflight.note: "No test suite configured — SPEC-000-testing created/exists"`
4. Run only static analysis tools (lint, type-check, format)
5. Proceed to step 2 (Task Selection) — the test infra spec will be selected first due to Layer 0 + priority 0.
6. **Flag all subsequent feature specs** with `untested: true` in metrics if no test suite exists when they run.

---

### Test Timeout Protocol (Reusable)

This protocol applies whenever running `commands.test`, both in Step 1 (Pre-Flight) and Step 9 (Validation). Use this to detect and handle hung test processes.

**When running tests:**

1. **Check for timeout configuration:**
   - If `config.yaml` → `commands.test_timeout_s` is absent or 0: run the test command normally, no timeout
   - If `config.yaml` → `commands.test_timeout_s` > 0: wrap the test command with the timeout wrapper

2. **Wrap the test command if timeout is enabled:**
   ```bash
   .nightshift/run_with_timeout.sh <test_timeout_s> <commands.test>
   ```
   Example:
   ```bash
   .nightshift/run_with_timeout.sh 300 pytest tests/ -v
   ```

3. **Check the exit code and handle accordingly:**
   - **Exit code 0:** Tests passed normally. Continue.
   - **Exit code 124:** Test run timed out (process was killed after `test_timeout_s` seconds). This indicates a possible hang (e.g., GCD starvation, XCTest waiting for expectations, deadlock).
     1. Log: `"Test run timed out after {test_timeout_s}s — possible hang detected"`
     2. Set `test_hang_detected: true` in the current phase metrics (preflight or validation)
     3. Retry ONCE:
        - Run `commands.build` (clean build)
        - Then run tests again with the same timeout
     4. Check the retry exit code:
        - If retry returns 0: Continue (hang was transient)
        - If retry returns 124: Timeout happened again
          - Log: `"Test hang persisted after retry with clean build — failing spec"`
          - Mark the phase as failed with `error_type: "test_hang"`
          - Do NOT attempt further retries
   - **Any other non-zero code:** Genuine test failure (assertion failure, test error, etc.). Handle normally per step procedures.

4. **Record in metrics:**
   - `phases.preflight.test_hang_detected: false` (or `true` if timeout was hit in pre-flight)
   - `phases.validation.test_hang_detected: false` (or `true` if timeout was hit in validation)

---

### 2. Task Selection

**What to do:**
1. Read `specs/` and collect all specs with `status: ready`
2. Apply the **Task Selection Algorithm** (see below)
3. Pick the first spec that passes all filters
4. If no spec passes → check for `blocked` specs:
   - If any are blocked → write summary report, stop loop
   - If all are done → write final report, stop loop
5. **Mark the selected spec as `status: in_progress`** in its frontmatter (update the spec file)
6. Commit: `[<spec-id>] chore: mark in_progress`
   - See `GIT.md` § Spec Status Commits
7. **Capture the production-resource start snapshot (SPEC-157).** If the selected
   spec declares `production_resources: [<absolute path>, ...]`, call the helper
   below automatically. It uses only `os.stat` against each declared resource;
   missing or unreadable paths are evidence and never block the run. Specs without
   the optional field produce no artifact and otherwise behave exactly as before.
   ```python
   from production_resource_gate import save_snapshot, snapshot_resources

   production_resource_snapshot = snapshot_resources(selected_spec_frontmatter)
   save_snapshot(
       production_resource_snapshot,
       project_root / "reports" / "_wip" / f"production-resource-{current_spec_id}.json",
   )
   ```
8. **Dispatch through the handler registry (SPEC-041).** Once a spec is
   selected, route its execution through `dispatch.dispatch_spec()` instead
   of the previous hardcoded path:

   ```python
   from handler_registry import HandlerContext
   from dispatch import dispatch_spec

   ctx = HandlerContext(
       project_root=project_root,
       spec_path=selected_spec_path,
       events_logger=events_logger,
       config=config,
       checkpoint_dir=nightshift_dir / "checkpoints",
   )
   outcome = dispatch_spec(selected_spec_frontmatter, registry, ctx, config=config)
   # outcome is an Outcome dataclass — persist it into the per-spec metrics YAML
   ```

   `dispatch_spec` is responsible for:
   - Resolving `effective_domain` (spec > stack > config.runner > `"code"`)
   - Emitting `domain_defaulted` when no explicit domain is present (AC8)
   - Calling `registry.get_handler(domain)`; on `KeyError` falling back to
     `CodeHandler` and emitting `handler_fallback` (AC3, R5)
   - Always emitting `handler_selected` with
     `{spec_id, effective_domain, handler_class_name}` (R6)
   - Invoking `handler.execute(spec, ctx.as_dict())` and returning the
     `Outcome`

   The returned `Outcome` is persisted into the per-spec metrics YAML
   written in Step 13. Do not unwrap it before persistence — keep
   `status / artifacts / metrics / next_action` intact so downstream
   routers (SPEC-042) can consume them directly.

**Task Selection Algorithm:**

```
0. Filter: type != "nfr" AND id does not start with "NFR-" AND type != "main" (NFR-family specs are standing constraints / verification trackers, main specs are containers — skip both)
1. Filter: status == "ready"
2. Filter: layer <= lowest_incomplete_layer
   (don't start Layer 2 if any Layer 1 spec is still ready/in_progress)
3. Filter: all `after` dependencies have status "done" (or don't exist)
4. Sort: type == "bugfix" first (bugs always take priority)
5. Sort: by priority (ascending — 1 first)
6. Pick first
```

#### Task Selection — Main Spec Exclusion (NEW — Hierarchical Specs)

When scanning ready specs for the task queue:

- **Skip `type: main` specs.** Main specs are containers; their children are the executable tasks. Log: "Skipping SPEC-XXX (type: main — container spec)"
- **Skip `type: nfr` specs and every spec whose `id` starts with `NFR-`.** NFR-family specs are constraints / verification trackers, not executable tasks.

If a main spec is the target of the run (passed as argument), handle it via §2.1b in ORCHESTRATOR.md (fan out to children). The loop itself never picks up main specs.

**NFR-family specs** (`type: nfr` or `id: NFR-*`) are never selected by the loop.
They define standing quality constraints or dated verification trackers (e.g.,
"no SwiftUI faults during normal operation"). Bug specs reference them via
`violates: [NFR-001]` when a quality attribute is broken. NFR-family specs use
`status: active | retired` instead of the normal lifecycle and are never marked
`blocked`. Missing inputs or failed checks are recorded in the NFR body; the
triggering executable spec is blocked or a violation bug is filed.

**Key rule:** Bugfix specs always take priority over features, regardless of layer or priority number.

**Example:**
- SPEC-001 (Layer 0, feature, priority 3) — ready
- SPEC-005 (Layer 2, bugfix, priority 5) — ready
- SPEC-006 (Layer 1, feature, priority 1) — ready, but has after: [SPEC-007] and SPEC-007 is not done

Selection order: SPEC-005 (bugfix first) → SPEC-001 (Layer 0 before Layer 2) → SPEC-006 is skipped (blocked on SPEC-007)

#### Phase 1-B: Spec Integrity Check

Before context loading, validate the selected spec itself.

**What to do:**
1. Check the selected spec frontmatter contains valid `id`, `status`, `layer`, and `type` fields
2. Check every spec ID in `after:` exists in `specs/`
3. Check every spec ID in `nfrs:` exists in `specs/`
4. Check `## Requirements` and `## Acceptance Criteria` sections are present
5. Check files listed in `context.target_files` exist
   - Warn only if a target file is missing — new files are allowed
6. Run:
   ```bash
   python3 nightshift-dag.py validate-spec <spec-file>
   ```
   - Check the exit code

**If Phase 1-B fails:**
- Mark the spec `status: blocked`
  - Exception: if the selected/target spec is NFR-family (`id: NFR-*` or
    `type: nfr`), keep it `status: active` (or `retired`) and record the pending
    validation state in the NFR body instead.
- Set `blocked_reason: "validation_failed: <detail>"`
- Commit the status change immediately
- Log metrics: `phases.validation.spec_integrity: "blocked"`
- If you emit a BLOCKED report from this phase, set `failure_class: "spec_validation"`
- Continue Task Selection and pick the next ready spec
- Do **not** halt the loop for spec-integrity failures

**If Phase 1-B passes:**
- Log metrics: `phases.validation.spec_integrity: "passed"`

---

### 3. Context Loading

**Pending Reflection Note (Orchestrator Mode):**
If running in orchestrator mode, you may have pending reflection output from a previous spec running asynchronously. Check for new patterns discovered before loading knowledge:
```bash
python3 check_reflection.py --spec <prev-spec> --output-dir .nightshift/reflections --since <timestamp>
```
If the reflection is done and new patterns exist, inject them into your context (step 3b will handle this). If the reflection is still running, proceed without — patterns will be available for subsequent specs.

**What to do:**
0. **Generate the instruction packet (SPEC-051):**
   ```bash
   python3 .nightshift/nightshift-instructions.py apply --spec <SPEC-ID> --json
   ```
   Read every non-optional path listed under `contextFiles` before implementation. If the packet reports `state: blocked`, fix the named blocker or mark the spec blocked; do not start coding from incomplete context.
1. Read the selected spec completely
   - **Resolve portable path tokens (SPEC-071):** if the spec body or frontmatter
     contains `{{PROJECT_ROOT}}`, `{{ARGO_HOME}}`, or `{{HOME}}` tokens, resolve them
     to real paths **before** acting on any path or injecting the body as
     `{{spec_content}}` into a prompt. Use
     `canonical/path_vars.resolve(text, project_root, mode='execute')` — execute mode
     is fail-closed, so an unresolvable token raises rather than feeding a garbage
     path to a subprocess. Tokens inside code fences/spans are left literal. (The
     `SpecCache` stores raw token text; resolution is this egress step.)
2. Examine every file mentioned in the spec's "Context" section
3. Read all relevant `knowledge/` files (agent decides which are relevant)
4. **Search for prior attempts:** Check if the spec has a `prior_attempts` field in its frontmatter — if so, read those files from `knowledge/attempts/`. Then also scan `knowledge/attempts/` for files whose `Problem area` matches the current spec's domain. Read any matches. This prevents repeating approaches that already failed.
5. **Load `context.required_inputs` artifacts (if declared):**
   - Before implementation starts, verify every path in `context.required_inputs` exists relative to the project root
   - If any required input is missing: mark the spec `status: blocked`, record `required_inputs file not found: '<path>'`, and do not launch implementation
     - Exception: if the target is NFR-family (`id: NFR-*` or `type: nfr`), keep `status: active` and record the pending input in `## Active Run State`, `## Pending Inputs`, or `## Run Log`.
   - If all required inputs exist: read each file and append it to working context with a clear header:
     ```markdown
     ## Required Input: <relative/path>
     <file contents>
     ```
   - This injection happens alongside the rest of Step 3 context loading; specs without `required_inputs` behave unchanged

#### 3a. DevKB Loading (External Knowledge Base)

**What to do:** Load cross-project development lessons if DevKB is configured.

1. **Check `config.yaml` → `devkb.path`:**
   - If empty or missing → skip to 3b (Pattern Matching)
   - If set → proceed

2. **Resolve and read DevKB files:**
   - For each language in `config.yaml` → `project.language`:
     - Look up `devkb.mappings.<language>` → list of filenames
     - Construct full path: `<devkb.path>/<filename>`
     - Read each file
   - Also read all files in `devkb.always_include`
   - Deduplicate across mappings

3. **3-iteration pause rule (MANDATORY):**
   If you've already attempted the same fix 3+ times on this spec:
   - STOP and re-read the relevant DevKB file(s)
   - Search for the error message or pattern name in DevKB
   - If the answer was in DevKB all along, log in metrics:
     ```yaml
     devkb_miss: true
     devkb_miss_file: "<filename>"
     devkb_miss_pattern: "<what you should have found>"
     ```

4. **Log to working notes:**
   ```
   DevKB loaded: N files [list filenames]
   ```

**Why:** DevKB is the cross-project memory that prevents agents from rediscovering known fixes. Without it, the BUG-010 agent couldn't find `swift.md` because it only existed in Argo Home — now it's injected into every loop iteration via config.

---

#### 3b. Pattern Matching & Knowledge Injection (project-local)

**What to do:** Match and inject relevant success patterns to prevent reinventing solutions.

**Pattern Matching Algorithm:**

1. **Extract spec metadata** from frontmatter:
   - `domain:` (e.g., "search", "auth", "caching")
   - `tags:` (comma-separated list, if present)
   - `problem_area:` (if present; same as `domain` if not)

2. **For each pattern in `knowledge/patterns/`** (excluding `_TEMPLATE.md`):
   - Read the pattern file's header
   - Extract: `Problem area:`, `Language/Stack:`, `When to Reuse:`, `When NOT to Reuse:`
   - Score relevance using:
     ```
     Match type                Relevance score
     Domain name (exact)       3 points
     Tag overlap (≥1 tag)      2 points per tag match
     Keyword in problem area   1 point per keyword match
     ```

3. **Select top N patterns:**
   - Read `config.yaml` → `knowledge.max_patterns` (default: 5)
   - Sort patterns by score (descending)
   - Select the top N non-zero-scoring patterns
   - If fewer than N patterns score >0, include all matches

4. **Format selected patterns compactly** (each pattern ≤5 lines in the injected block):
   ```
   === RELEVANT PATTERNS (from prior successful specs) ===

   [PATTERN: Pattern-Name]
   Problem: one-line problem area
   Approach: how it works, 2-3 lines max
   Reuse when: conditions for this pattern
   Avoid when: conditions where pattern is wrong
   Source: SPEC-XXX

   [PATTERN: Another-Pattern]
   Problem: ...

   === END PATTERNS ===
   ```

5. **Inject into context** by appending to your working notes:
   ```
   Knowledge Injection Results:
   Matched spec domain: [domain], tags: [tags]
   Scanned N total patterns in knowledge/patterns/
   Injected M/N patterns (relevance scoring: domain=3pts, tags=2pts, keyword=1pt)

   [PASTE THE FORMATTED PATTERNS BLOCK ABOVE]

   These patterns are now available during implementation (step 8).
   If any pattern is a perfect fit, adapt or reuse before designing from scratch.
   If no patterns matched, note in working notes: "No relevant patterns found."
   ```

6. **Log in working notes:** "Injected N/M patterns (filtered by domain: X, tags: Y)"

7. **Initialize knowledge citation tracking** (MANDATORY):
   Start a `knowledge_citations` list in working notes:
   ```
   knowledge_citations: []
   ```
   This list will be populated during implementation (step 8) and checked in step 12 (Commit & Changelog).

8. **Add to mental notes:**
   - Which injected patterns are relevant to this specific spec?
   - Any pattern that's a perfect fit? Mark for reuse.
   - Any pattern that's the opposite of what you need? Mark to avoid.

#### 3c. Examine codebase and finalize context

5. Examine actual codebase sections the spec will touch — don't just read docs, read the code

6. Take mental notes on:
   - Existing patterns in the codebase
   - Dependencies and relationships
   - API contracts and interfaces
   - Test fixtures and utilities
   - **What was already tried and failed** (from prior attempts)
   - **Which injected patterns are relevant to this specific spec?** (from step 3b above)
   - Any architectural constraints or assumptions
   - Error handling patterns already in use
   - Performance considerations from existing code

**Why:** A spec that says "add a cache layer" is useless without understanding the current architecture. Context loading takes time but prevents architectural mistakes and rework. Prior attempt files prevent the loop from wasting tokens on approaches that have already been proven wrong. Pattern injection provides proven solutions from previous specs — accelerating design and reducing the search space.

**Git:** No commits. Just reading.

#### Phase 2-B: Checkpoint Initialization

After context loading completes, initialize the spec checkpoint:
```
import checkpoint
checkpoint.save_checkpoint(
    spec_id=current_spec_id,
    step=3,
    step_name="context_loading",
    data={
        "status": "completed",
        "git_branch": current_branch,
        "git_sha": current_commit_hash,
        "working_notes": "Preflight check passed. Context loaded and ready for implementation.",
        "metrics_so_far": {"tests_total": N, "tests_passing": N},
        "knowledge_citations": []
    }
)
```

If the checkpoint write fails, do **not** halt the loop. Log a warning in metrics as `phases.startup.checkpoint: "degraded"` and continue in degraded mode.

---

### 4. Test Planning

> **Domain-aware:** Use `effective_domain` (resolved per-spec, see § Domain Resolution) to select behavior from LOOP-DOMAIN-MAP.md. For research/analysis domains, this step becomes validation criteria planning instead of test planning.

**Critical step.** Before writing any test code, produce a plan.

**If `commands.test` is null:** You are likely working on SPEC-000-testing (creating the test infrastructure). In this case, Step 4 is about planning the test framework setup itself — which framework, which config, which initial tests. After SPEC-000-testing completes, `commands.test` will be populated for all subsequent specs.

**If `commands.test` exists but the current spec IS the test spec:** Write the test plan for the foundational test suite (regression tests for existing functionality).

**What to do:**
1. Analyze the spec's Requirements and Acceptance Criteria
2. Identify what needs to be tested:
   - Happy path (normal behavior)
   - Edge cases (boundary conditions, empty inputs, null values)
   - Error cases (what happens when things go wrong?)
   - Integration points (how does this interact with existing code?)
3. Document for each test:
   - What it tests (one sentence)
   - Inputs (if any)
   - Expected behavior
   - Why it matters
4. Identify fixtures and setup needed
5. Note expected failure modes (ways the test might fail during implementation)

**Output:** A brief test plan in the agent's working notes (not committed yet). Example:

```
Test Plan for SPEC-XXX:

1. test_basic_functionality
   - Tests: Happy path with valid input
   - Input: sample data from fixture
   - Expected: returns result matching spec requirement Y

2. test_empty_input_graceful
   - Tests: Edge case — empty input doesn't crash
   - Input: empty list/dict/string
   - Expected: returns empty result or sensible default

3. test_integration_with_cache
   - Tests: Interaction with cache layer from SPEC-YYY
   - Expected: cache is invalidated when data changes
```

**Why:** This prevents scattered, unfocused tests. It forces the agent to think about what matters before writing code.

---

### 5. Test Writing

> **Domain-aware:** Use `effective_domain` (resolved per-spec, see § Domain Resolution) to select behavior from LOOP-DOMAIN-MAP.md. For research/analysis domains, this step becomes acceptance checklist or validation script writing.

**What to do:**
1. Following the test plan from step 4, write tests
2. Tests go alongside source code (follow project conventions)
3. Run tests immediately → expect them to fail (they test code that doesn't exist yet)
4. Verify tests fail for the right reasons:
   - Not because of import errors or typos
   - But because the feature/behavior isn't implemented
5. Commit: `[<spec-id>] test: add tests (red)`
   - Commit format is governed by `GIT.md` § Commit Format
   - Commit message explains what the tests cover
   - Metrics log: record test count and initial failure state

**Checkpoint:** After tests are committed, save a checkpoint:
```
import checkpoint
checkpoint.save_checkpoint(
    spec_id=current_spec_id,
    step=5,
    step_name="test_writing",
    data={
        "status": "completed",
        "git_branch": current_branch,
        "git_sha": current_commit_hash,
        "working_notes": "Test plan from step 4 implemented. All tests failing as expected.",
        "metrics_so_far": {"tests_written": N, "tests_failing": N},
        "knowledge_citations": knowledge_citations_list
    }
)
```

**Why:** Red tests establish the specification in code. Later implementations measure success against these tests, not against vague intentions.

---

### 6. Implementation Planning

**What to do:**
1. Analyze the failing tests and spec requirements
2. Design a solution: How will you make these tests pass?
3. Outline the approach:
   - Files to create/modify
   - Major functions/classes
   - Call flow and dependencies
   - Any tricky logic or state management

**This plan is NOT reviewed by humans** — it's internal working notes. Skip it if you already know what to do.

**Write your plan to `reports/_wip/plan-<spec-id>.md`.** This directory is gitignored. Use it freely for scratch notes, diagrams, alternative approaches, or anything that helps you think. Clean up after the spec is done (or don't — it's gitignored).

**Why:** Writing a plan reduces false starts. A malformed idea gets caught before burning tokens on implementation.

---

### 7. Plan Review (First Review Round)

> **Domain-aware:** Use `effective_domain` (resolved per-spec, see § Domain Resolution) to select behavior from LOOP-DOMAIN-MAP.md. Review personas differ by domain (e.g., methodology/bias for research, accuracy/completeness for analysis).

**Critical step.** Review the implementation plan against project standards BEFORE writing code.

**Review Mode Check:** Read `config.yaml` → `review.mode`.
- If `mode` is `subagent`: dispatch a spec-reviewer subagent using `.nightshift/prompts/spec-reviewer.md`. Provide the implementation plan as `{IMPLEMENTATION_SUMMARY}` and the spec requirements as `{SPEC_REQUIREMENTS}`. Fill `{CONVENTIONS}` from config.yaml and `{KNOWLEDGE_CONTEXT}` from relevant knowledge/ files. If reviewer raises blocking issues → update plan and re-dispatch. Skip persona self-review below.
- If `mode` is `self` or `hybrid`: use persona self-review (proceed with steps below).

**What to do:**
1. For each review persona enabled in `config.yaml`:
   - Read the persona's owned documentation (from `knowledge/` or project root)
   - Review the plan against that persona's criteria
   - Check: Does the plan respect architecture? Avoid security issues? Meet performance expectations? Align with business logic? Follow coding conventions?
2. Role-play each persona:
   - Architect: "Does this match our documented architecture?"
   - Security: "Are there vulnerabilities in this approach?"
   - Performance: "Will this scale? Any N+1 queries or unnecessary work?"
   - Domain Expert: "Does the business logic handle all cases correctly?"
   - Code Quality: "Will this follow our style guide and testing standards?"
   - User Advocate: "Are UX implications considered? Accessibility?"
3. For each persona, produce structured feedback:
   ```
   [BLOCKING] / [WARNING] / [NOTE]
   Issue: <what's wrong>
   Recommendation: <how to fix it>
   ```
4. If any persona raises a **blocking** issue:
   - Stop
   - Update the plan
   - Re-review the updated plan
   - Iterate until all personas approve or have only non-blocking notes
5. Log review results (persona, severity, resolution)

**Checkpoint:** After plan review is approved, save a checkpoint:
```
import checkpoint
checkpoint.save_checkpoint(
    spec_id=current_spec_id,
    step=7,
    step_name="plan_review",
    data={
        "status": "completed",
        "git_branch": current_branch,
        "git_sha": current_commit_hash,
        "working_notes": "Implementation plan approved by all personas. No blocking issues.",
        "metrics_so_far": {"review_cycles": N},
        "knowledge_citations": knowledge_citations_list
    }
)
```

**Why:** Architectural mistakes caught here cost zero code rework tokens. Catching security issues in the plan prevents code review delays.

---

### 8. Implementation

> **Domain-aware:** Use `effective_domain` (resolved per-spec, see § Domain Resolution) to select behavior from LOOP-DOMAIN-MAP.md. For research domains, this step is source gathering and synthesis; for analysis, data processing and calculation.

**What to do:**
1. Write code to make tests pass, following the reviewed plan
2. After EVERY file change:
   - Run lint (e.g., `npm run lint`, `ruff check`)
   - Run type-check (e.g., `tsc --noEmit`, `mypy`)
   - Run format check (e.g., `prettier --check`) and fix if needed
3. Iterate:
   - Write a bit
   - Run tests → do they pass yet?
   - Run static tools
   - Write more
4. Once all tests pass locally and static tools are clean, run the full build:
   - `config.yaml` → `commands.build`
5. If build fails:
   - Analyze error
   - Fix the issue
   - Re-run build and test
   - Repeat until clean

**Key insight:** Static tools are free — run them constantly. Every lint error caught now is one fewer review cycle later.

**Citation tracking during implementation** (MANDATORY):
- As you reference or apply any of the injected patterns from step 3b, log the citation in your `knowledge_citations` list:
  ```
  knowledge_citations:
    - pattern: "PATTERN-name"
      cited_in_phase: "implementation"  # phase where it was referenced
      usage: "applied"                  # applied | considered | rejected
      note: "Applied the retry approach for handling API timeouts"
  ```
- For each pattern:
  - `pattern`: the pattern name (from the PATTERN-*.md file)
  - `cited_in_phase`: which phase referenced it (implementation, test_planning, implementation_planning)
  - `usage`: how the pattern was handled:
    - `applied`: you actually implemented the pattern or adapted it
    - `considered`: you reviewed it and decided it was relevant but didn't use it
    - `rejected`: you reviewed it and decided it wasn't applicable
  - `note`: brief explanation of why/how it was used or why rejected
- If you reject a pattern, explain why (e.g., "different architecture", "performance constraints")
- If no patterns were used, log an empty list in working notes: `knowledge_citations: []`

**Commits during implementation:**
- Commit incrementally as you reach working milestones
- Follow `GIT.md` § Commit Format for spec prefixes and message style
- Or wait until all tests pass, then commit in one go

**Checkpoint:** After implementation completes (all tests pass), save a checkpoint:
```
import checkpoint
checkpoint.save_checkpoint(
    spec_id=current_spec_id,
    step=8,
    step_name="implementation",
    data={
        "status": "completed",
        "git_branch": current_branch,
        "git_sha": current_commit_hash,
        "working_notes": "All tests passing. Implementation complete.",
        "metrics_so_far": {
            "tests_written": N,
            "tests_passing": N,
            "files_modified": ["file1.py", "file2.py"],
            "review_cycles": 0
        },
        "knowledge_citations": knowledge_citations_list
    }
)
```

### When Tests Fail or Builds Break During Implementation

DO NOT immediately attempt a fix. Follow this protocol:

1. **Read error messages completely** — stack traces, line numbers, error codes
2. **Reproduce consistently** — can you trigger it reliably?
3. **Check recent changes** — what did you just change that could cause this?
4. **Form a single hypothesis** — "I think X causes Y because Z"
5. **Test minimally** — smallest possible change to test the hypothesis
6. **Verify** — did it work? If no → new hypothesis (don't stack fixes)

If 3+ fix attempts fail on the same error → STOP. This is likely an architectural issue, not a bug. **Before triggering the circuit breaker**, write an attempt record:
```
knowledge/attempts/<spec-id>-<short-description>.md
```
Use the template at `knowledge/attempts/_TEMPLATE.md`. Fill in: what was tried, why it failed, what was learned. This file survives even when the code is reverted. Then trigger the circuit breaker.

---

### 8.4b. Implementation Checkpointing (for large specs)

When your implementation will exceed ~500 lines of changes (lines added + lines modified):

1. **Plan implementation in phases** — break into 2-4 logical chunks
   (e.g., data layer → rendering → interaction → styling)
2. **After each chunk:**
   - Run `commands.build` (if configured) — catch compile errors early
   - Run `commands.test` (if configured) — catch regressions immediately
   - If tests/build fail → fix before proceeding to next chunk
   - Save checkpoint:
     ```
     checkpoint.save_checkpoint(spec_id, step=8, step_name="implementation_chunk_N", ...)
     ```
3. **Why:** A 1000-line implementation that fails at line 800 wastes all work on lines 1-800
   if there's no checkpoint. Chunked validation catches issues when the fix is small.

**Thresholds:**
- **<200 lines** — proceed normally, no chunking needed
- **200–500 lines** — use judgment; chunk if touching multiple subsystems
- **>500 lines** — always chunk into 2-4 phases with intermediate validation

---

### 8.5. Implementation Status Check

**What to do:**

After completing implementation (step 8), self-report your status before proceeding:

| Status | Action |
|--------|--------|
| **DONE** | Proceed to step 9 |
| **DONE_WITH_CONCERNS** | Log concerns in metrics, flag in report, proceed to step 9 with extra scrutiny |
| **NEEDS_CONTEXT** | Log what's missing, check knowledge/ for answers, retry once. If still missing → BLOCKED |
| **BLOCKED** | Skip to stall detection (circuit breaker) |

**Why DONE_WITH_CONCERNS matters for Nightshift:** An unsupervised agent that says "I finished but I'm not confident about X" gives the morning reviewer a targeted place to look, instead of reviewing everything equally.

**Metrics:** Add `implementation_status` field to the metrics entry:
```yaml
phases:
  implementation:
    # ... existing fields ...
    status: "done"  # done | done_with_concerns | needs_context | blocked
    concerns: []     # list of strings, only if status == done_with_concerns
```

---

## Verification Discipline (applies to steps 9 and 12)

### The Iron Law

**NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE.**

If you haven't run the verification command in this step, you cannot claim it passes.

### Red Flags — STOP if you're thinking:
- "Should work now" → RUN the verification
- "I'm confident" → Confidence ≠ evidence
- "Just this once" → No exceptions
- "Linter passed" → Linter ≠ full build
- "Tests passed earlier" → Earlier ≠ now. Run again.

### Anti-Rationalization Table

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Partial check is enough" | Partial proves nothing |
| "Just this once" | No exceptions |
| "I'm stalled, skip validation" | Skipping makes stall worse |
| "Quick fix for now" | Quick fixes mask root causes. Investigate first. |
| "Just try changing X" | Changing without understanding = random walk. |

---

### 9. Full Validation

> **Domain-aware:** Use `effective_domain` (resolved per-spec, see § Domain Resolution) to select behavior from LOOP-DOMAIN-MAP.md. For research domains, validation is fact-checking and citation verification; for analysis, calculation verification and cross-referencing.

**Null Command Handling:** For each command below, if the command is null/missing, apply the Null Command Policy (see section above). Log which commands were skipped and why. Do NOT silently skip — every skipped validation must appear in the metrics log under `phases.validation.skipped: [...]`.

> **Optional mechanization (SPEC-092):** instead of running each command by hand, you MAY
> run `python3 .nightshift/run_validation.py --spec-id <id>`. It runs the configured
> build/test/lint/type commands, applies the test timeout, and writes
> `metrics/<id>.validation.json` — which the mark-done metrics hook then reads for
> **authoritative** test/lint/type/build numbers (instead of parsing your report). This is
> optional convenience, not a hard-mandatory step; the manual steps below remain valid.

**What to do:**
1. Run the full build (not just quick lint):
   - `config.yaml` → `commands.build` (skip with WARN if null)
2. Run the complete test suite (not just new tests):
   - `config.yaml` → `commands.test` (GATE if null — should have been handled in Step 1)
   - **Apply the Test Timeout Protocol** (see section below Test Gate in Step 1) to wrap the command if timeout is configured
3. Run all static analysis:
   - `config.yaml` → `commands.lint` (skip with SUGGEST if null)
   - `config.yaml` → `commands.type_check` (skip with WARN if null)
   - `config.yaml` → `commands.format` (skip with WARN if null)
4. Run external scenario validation (if scenarios exist):
   - List all files in `scenarios/` with `status: active`
   - For each scenario whose `target_specs` includes the current spec (or is "all"):
     - Read the scenario
     - Execute the steps described (manually trace through the code/tests)
     - Verify the expected outcome is achievable with the current implementation
     - If a scenario fails: log it as a validation failure, treat as a test failure
   - Note: Scenarios are holdout validation — the agent should NOT have read them during implementation (steps 3-8). They test whether the feature works in context, not just in isolation.
5. Log results:
   - Build: pass/fail, any warnings?
   - Tests: total count, pass rate, any failures?
   - Scenario validation: pass/fail for each scenario
   - Lint: error count, warning count
   - Type check: error count
   - Format: any files needing fixing?
6. If anything fails:
   - Go back to step 8 (implementation)
   - Fix the failure
   - Re-run full validation

**Checkpoint:** After full validation passes, save a checkpoint:
```
import checkpoint
checkpoint.save_checkpoint(
    spec_id=current_spec_id,
    step=9,
    step_name="validation",
    data={
        "status": "completed",
        "git_branch": current_branch,
        "git_sha": current_commit_hash,
        "working_notes": "Full validation passed. Build green, all tests passing, lint clean, type check clean.",
        "metrics_so_far": {
            "build_pass": True,
            "tests_total": N,
            "tests_passing": N,
            "lint_errors": 0,
            "type_errors": 0
        },
        "knowledge_citations": knowledge_citations_list
    }
)
```

**Why:** Catch regressions before the next review phase. A clean build is a quality gate.

---

### 9.5. Completion Verification (Premature Victory Guard)

**Purpose:** Prevent declaring a spec "complete" without verifying each Acceptance Criterion individually. Tests may pass without covering all ACs.

**Critical Anti-Rationalization Rules:**
- Do NOT skip this step even if all tests pass. Tests may not cover all Acceptance Criteria.
- Evidence must be fresh — from THIS step, not from earlier runs.
- Confidence is not evidence. Verification is evidence.

**What to do:**

1. **Read the spec's Acceptance Criteria section completely.**
   - Extract each criterion (AC-1, AC-2, etc.)
   - If the spec doesn't have explicit ACs, treat the Requirements section as the source

2. **Build a completion checklist** (use `.nightshift/prompts/completion-checklist.md` as your template):
   - One JSON object per spec
   - One item in the checklist array per AC
   - Each item: `{ "ac_id": "AC-1", "description": "...", "passes": false, "evidence": "", "verified_by": "test|manual|lint|build|scenario" }`

3. **Verify each AC:**
   - For each AC:
     - Identify the verification method (test, code inspection, lint, build output, scenario execution)
     - Run or trace the verification
     - Record evidence (test name, file:line, output, scenario name)
     - Set `passes: true` only if fresh evidence confirms the AC is met
   - Do NOT assume an AC passes because a similar test passed earlier — verify again now

4. **Handle failures:**
   - **If all ACs pass:** Set `all_pass: true`, proceed to step 10
   - **If any AC fails and is fixable:**
     - Go back to step 8 (implementation)
     - Fix the issue
     - Re-run full validation (step 9)
     - Return to step 9.5 and re-verify the checklist
   - **If any AC fails and is NOT fixable** (ambiguous spec, missing infra, env issue):
     - Log as a concern (e.g., "AC-X: [why it can't be verified]")
     - Set `all_pass: false` and status to `DONE_WITH_CONCERNS`
     - Proceed to step 10 but flag this in metrics and report
     - This signals the morning reviewer that the spec is functionally done but uncertain about completeness

5. **Save the checklist:**
   - Write to: `reports/_wip/checklist-<spec-id>.json` (gitignored)
   - Example: `reports/_wip/checklist-SPEC-001.json`
   - Use the JSON schema from `completion-checklist.md`

6. **Extract metrics for logging (step 13):**
   - `checklist_items`: total number of ACs
   - `items_passing`: count with `passes: true`
   - `items_failing`: count with `passes: false`
   - `all_pass`: boolean from checklist
   - `concerns`: list of concern strings (if any)
   - `duration_s`: seconds spent in this step

**Red Flags — STOP if you're thinking:**
- "Should work now" → VERIFY it
- "Tests passed earlier" → Run them again NOW
- "I'm confident about AC-3" → Confidence ≠ evidence
- "Partial verification is enough" → Verify ALL ACs
- "This AC is probably fine" → PROVE it with evidence

**Why:** Over many iterations, agents rationalize "tests pass, so we're done" without checking each AC individually. This step makes that rationalization impossible — each AC gets an explicit yes/no verdict with supporting evidence.

#### 9.5b. Verification Report Artifact (SPEC-052)

Before a spec can be marked `done`, write a durable verification artifact under `.nightshift/reports/<spec-id>/`:

- `verification.json` — structured gate input with dimensions `completeness`, `correctness`, and `coherence`
- `verification.md` — human-readable report grouped by `CRITICAL`, `WARNING`, and `SUGGESTION`

Completion rules:
- Any `CRITICAL` issue blocks `status: done`.
- `WARNING` issues require a recorded rationale or linked follow-up task.
- `SUGGESTION` issues are non-blocking.
- Verification complements tests and drift checks; it does not replace them.

If the run fails, hits a circuit breaker, aborts a retry, or verification contains a CRITICAL issue, write a replay bundle (SPEC-055) under `.nightshift/reports/<spec-id>/replay/<timestamp>/` and include the bundle path in the report.

---

### 9.6. Output Artifact Verification

**Purpose:** Enforce the handoff contract for specs that promise a concrete deliverable via `output_artifact:`.

**What to do:**

1. Check whether the current spec declares `output_artifact:` in frontmatter.
   - If absent: skip this step entirely. Behavior remains unchanged.
2. Resolve the artifact path relative to the project root and verify the file exists.
   - If missing: mark the spec `status: blocked`
   - Exception: for NFR-family specs, keep `status: active` and record the missing artifact as pending run state in the NFR body.
   - Set `error_type: "output_artifact_missing"`
   - Record message: `output_artifact declared at '<path>' but file was not produced`
   - Stop before Step 10
3. If `output_schema:` is also declared:
   - Auto-detect artifact format by extension
   - For `.json`, `.yaml`, `.yml`: load the schema and validate the artifact contents
   - For other formats (for example `.md`, `.csv`): skip schema validation, but keep the existence check
4. On schema mismatch:
   - Mark the spec `status: blocked`
   - Exception: for NFR-family specs, keep `status: active` and record the failed check/verdict in the NFR body; block the triggering spec or file a violation bug.
   - Set `error_type: "output_artifact_schema_mismatch"`
   - Record the validation error details
   - Stop before Step 10
5. On success:
   - Record that the artifact contract passed
   - Proceed to Step 10

**Why:** Research and analysis specs often hand off files to downstream code specs. Verifying the promised artifact before review/merge catches missing or malformed deliverables at the cheapest point in the loop.

---

### 9.7. Research Synthesis Gate (conditional)

**Purpose:** Verify that a research or analysis artifact is not only present, but also consumable by its direct downstream code specs.

**Trigger condition:**
- `effective_domain` resolves to `research` or `analysis`
- At least one direct dependent spec in `specs/` declares `after: [<current-spec-id>]` and resolves to `code`

If the trigger condition is not met, skip silently. Do not log the skip and do not add `phases.synthesis_gate` to metrics.

**What to do when triggered:**
1. Scan `specs/*.md` for direct code dependents of the current spec.
2. Read each dependent spec's `required_inputs:` and Context/body to infer the expected downstream interface.
3. Validate the current `output_artifact:` against those expectations:
   - file exists
   - format is parseable (`markdown`, `json`, `yaml`, `csv`)
   - required interface markers referenced by dependents are present (for example `recommendation` or `benchmarks`)
4. Write `knowledge/handoffs/<spec-id>.json` with:
   - `spec_id`, `domain`, `output_location`, `output_format`
   - `key_findings` (3-7 one-sentence findings)
   - `confidence`
   - `dependent_specs`
   - `interface_validation`
   - `validation_details`
   - `timestamp`
5. Write `knowledge/patterns/<spec-id>-findings.md` under 50 lines with:
   - decision made
   - key constraints
   - anti-patterns discovered
   - reference to the full artifact path
6. Record the optional metrics block:
   ```yaml
   phases:
     synthesis_gate:
       triggered: true
       dependent_specs: [SPEC-YYY, SPEC-ZZZ]
       interface_validation: passed|failed
       handoff_artifact_path: "knowledge/handoffs/SPEC-XXX.json"
       knowledge_pattern_path: "knowledge/patterns/SPEC-XXX-findings.md"
       duration_s: N
   ```

**Failure handling:** If any dependent interface check fails, treat it as a BLOCKING issue. Return to step 8, repair the output, then re-run steps 9, 9.5, 9.6, and 9.7. The standard circuit breaker still applies.

**Implementation note:** The canonical helper for this gate is `canonical/synthesis_gate.py`.

---

### 10. Post-Implementation Review (Second Review Round)

> **Domain-aware:** Use `effective_domain` (resolved per-spec, see § Domain Resolution) to select behavior from LOOP-DOMAIN-MAP.md. Review personas are domain-specific (e.g., methodology/accuracy/bias for research, accuracy/completeness for analysis).

**Review Mode Check:** Read `config.yaml` → `review.mode`.
- If `mode` is `subagent` or `hybrid`: dispatch TWO reviewer subagents sequentially:
  1. **Spec compliance reviewer** using `.nightshift/prompts/spec-reviewer.md`. Provide spec requirements, implementation summary, conventions, and knowledge context. Wait for result. If ❌ issues found → fix code, re-dispatch reviewer until ✅.
  2. **Quality reviewer** using `.nightshift/prompts/quality-reviewer.md`. Provide description, spec requirements, conventions, knowledge context, and git SHA range. Wait for result. If Critical/Important issues → fix code, re-dispatch reviewer.
  After both reviewers approve, skip persona self-review below and proceed to step 11.
- If `mode` is `self`: use persona self-review (proceed with steps below).

**Why two-stage review at step 10:** Spec compliance first ensures the code does what was asked. Quality review second ensures it's well-built. Running quality review on code that doesn't meet spec wastes tokens.

**What to do:**
1. Generate a summary of changes (diff, file list, line counts)
2. For each review persona:
   - Read their owned documentation (same as step 7)
   - Review the **actual diff** (not just the plan)
   - Check for:
     - Code quality issues
     - Missed edge cases
     - Test gaps
     - Performance inefficiencies
     - Security concerns
     - Spec drift (did you build what the spec asked for?)
   - **Computed Value Verification** (for "Data Integrity" or equivalent persona):
     When the spec involves computed metrics, aggregated values, or derived displays:
     1. Identify all computed values in the implementation (sums, percentages, counts, filtered lists)
     2. Trace each computation back to the source data — manually verify at least 2 representative values
     3. If the project has a renderable output (HTML, UI, report):
        - Render/run the output
        - Compare displayed values against your manual calculation
        - If they differ → **[BLOCKING]** issue
     4. Do NOT trust the code logic alone — the code may be correct but operating on wrong data,
        or the data model may have nulls/edge cases that produce unexpected results.
     Example: If code says `progress = done / total` and `total` can be null,
     the rendered value may differ from what the data model implies.
3. Role-play each persona again:
   ```
   [BLOCKING] / [WARNING] / [NOTE]
   Issue: <what's wrong in the actual code>
   Recommendation: <how to fix it>
   ```
4. If any **blocking** issues:
   - Fix the code
   - Go back to step 8 (implementation)
   - Re-run full validation
   - Re-review once fixed
5. If only **warnings** or **notes**:
   - Log them for knowledge/metrics
   - Optionally create a TODO for future work
   - Proceed to next step
6. Track review cycles:
   - Metrics log: how many full review rounds did this spec require?

**Why:** Independent review catches blind spots. Code written in one context (implementation) is easier to review in a fresh context.

---

### 11. Outcome Routing (SPEC-042)

After Step 9 (validation) or Step 10 (post-review) returns a failure signal,
the loop must decide: retry, abort, escalate, or treat the outcome as
acceptable and proceed to commit. This decision is delegated to the outcome
router loaded in Phase 0-A.outcomes — no more hardcoded "if retry_count < 3,
retry" branches.

**Order of operations (R6 — circuit breaker first):**

1. **`check_circuit_breaker()` runs BEFORE `route_outcome()`.** A tripped
   breaker short-circuits to `ABORT` without consulting policies. This
   preserves the existing safety floor from SPEC-016.
2. **Map the handler result to a router `Outcome`.** The handler-registry
   `Outcome` dataclass (SPEC-033 / SPEC-041) uses a free-form status string;
   convert it to an `outcome_router.Outcome` enum via
   `handler_outcome_to_router_outcome()`. Unknown status strings fall back to
   `Outcome.FATAL`, whose policy default is `ABORT` (AC6).
3. **Call `route_outcome(router_outcome, policies, attempt, context, …)`**
   and honour `RoutingDecision.action`:

   | Action                | What the loop does                                                                                    |
   |-----------------------|-------------------------------------------------------------------------------------------------------|
   | `NEXT`                | Accept the outcome as success-equivalent. Fall through to the commit/changelog path (Step 12).        |
   | `RETRY` / `REPLAN` / `SUMMARIZE_AND_RETRY` | Increment retry counter, honour `wait_seconds` backoff, jump back to Step 7 (implementation).  |
   | `ABORT` / `BLOCK`     | Emit `spec_aborted` event, write BLOCKED report, move to Step 12 with failure status.                 |
   | `ESCALATE`            | Emit `spec_escalated` event, flag the spec for human review in the run report, move to Step 12.       |

**Reference driver.** The concrete retry loop implementing this flow is
`canonical/retry_loop.py` — `execute_with_retry(attempt_fn, policies, …)`.
Test harnesses and any future orchestrator should call into that function
instead of duplicating the control flow. The driver handles event emission,
backoff sleep, circuit-breaker checks, and terminal routing.

**Events emitted (R4, R5):**

| Event                      | When                                        |
|----------------------------|---------------------------------------------|
| `circuit_breaker_checked`  | before every attempt; carries `tripped` bool |
| `handler_outcome_received` | after each attempt, with `router_outcome`    |
| `prior_attempts_recorded`  | SPEC-046 gate wrote the prior attempt to the spec's `prior_attempts:` list (fires BEFORE `retry_decided`) |
| `prior_attempts_write_failed` | SPEC-046 gate could not write (frontmatter parse / disk error). Retry is converted to `ABORT` — loop MUST NOT jump back to Step 7. |
| `retry_decided`            | every retryable `RoutingDecision` — `{outcome, retry_count, max_retries, backoff_seconds, action}` |
| `retry_backoff_start` / `retry_backoff_end` | bracketing the `time.sleep(wait_seconds)` pause; `retry_backoff_end` carries `elapsed_seconds` |
| `spec_aborted`             | terminal `ABORT` / `BLOCK` — `{reason, final_outcome, total_retries, exhausted}` |
| `spec_escalated`           | terminal `ESCALATE` — `{final_outcome, total_retries}` |

**SPEC-046 — prior_attempts retry precondition gate.** Before the loop
consumes a retryable `RoutingDecision` and jumps back to Step 7, the retry
driver parses the spec's YAML frontmatter, appends a new entry to
`prior_attempts:`, and writes the result back atomically. The entry carries
`{attempt, date, session_id, outcome, events, failure_hint}` — derived from
the terminal handler outcome (no LLM call). If the write fails the retry is
blocked and converted to `ABORT` with a `prior_attempts_write_failed` event;
retries are forbidden without an audit trail. Specs that legitimately run
many times (e.g., `eval-specs/`) can opt out with
`prior_attempts_tracking: false` in frontmatter. The list is capped at 10
entries; overflow rotates to `<spec-stem>.attempts-archive.json` next to the
spec. CLI inspection: `python nightshift-dag.py attempts SPEC-ID`.

Note: SPEC-046 is **forward-only** — it does not retroactively backfill
`prior_attempts:` for specs whose retries happened before it landed.

These events are consumed by the SPEC-040 history DB ingest at Step 16 for
cross-run retrospective analysis.

**Reporting integration.** When `spec_escalated` is emitted, the run report
(Step 14) must surface the spec under a "Needs Human Review" section. When
`spec_aborted` is emitted with a non-circuit-breaker reason, the BLOCKED
report path (see § Stall Detection & Circuit Breaker) is still written so
the historical traceability is identical to a circuit-breaker abort.

---

### 11b. Capture Unrelated TODOs

**What to do:**
1. During implementation, the agent may notice issues outside the current spec's scope:
   - Tech debt (outdated libraries, inefficient patterns)
   - Missing documentation
   - Potential bugs elsewhere
   - Opportunities for refactoring
2. Log each finding to `reports/TODOs-discovered.md`:
   ```
   ### [Category] — [Brief title]
   **Location:** <file and line>
   **Why:** <why it matters>
   **Suggested action:** <what could be done>
   ```
3. Do NOT fix these issues now — they become input for future specs
4. Commit: `[SPEC-XXX] docs: log discovered TODOs` (if any found)

**Why:** Capture learning without scope creep. Future rounds will prioritize these.

---

### 12. Commit & Changelog

**What to do:**
1. If not already committed during implementation, commit now:
   ```
   git commit -m "[<spec-id>] feat: <short description>

   <body — what changed and why. Explain the approach chosen,
   alternatives considered, and any important implementation decisions.>

   Nightshift-Loop: 2026-03-16
   Spec: <spec-id>
   Phase: implementation"
   ```

   **Commit message rules:** Follow `GIT.md` § Commit Format. The spec prefix is
   the human-visible traceability tag; trailers such as `Spec:` remain useful for
   machine parsing.
2. Write a CHANGELOG entry in human-friendly language (not commit-message format):
   ```markdown
   ### [Spec ID] — [Title]

   **Changed:**
   - What was added/modified in plain language
   - Highlight behavioral changes

   **Tests:**
   - N new tests covering X scenarios

   **Status:** ✅ Complete
   ```
3. **Knowledge effectiveness tagging** (MANDATORY):
   1. Review the `knowledge_citations` list from your working notes (initialized in step 3b, populated during step 8)
   2. For each cited pattern, evaluate its effectiveness:
      - If spec completed successfully AND pattern was applied → tag as `helpful`
      - If spec completed successfully but pattern was only considered/rejected → tag as `neutral`
      - If spec had issues and the applied pattern contributed to those issues → tag as `harmful`
   3. Record tags in the metrics file (see R3 in this brief — the `knowledge:` section in step 13)
   4. Optionally update the pattern file itself with an effectiveness counter:
      - Locate the pattern file: `knowledge/patterns/PATTERN-name.md`
      - Find the "Effectiveness Tracking" section at the bottom
      - Increment the relevant counter (Cited, Helpful, Neutral, or Harmful)
      - Update `Last cited` timestamp to today's date
      - This is optional but encouraged — it keeps patterns self-updating

4. Success pattern checkpoint (MANDATORY decision):

   #### Pattern Decision Checklist

   Before deciding `pattern_written: false` with "nothing novel," ask yourself these 4 questions:

   1. **Did I create a reusable class, struct, function, or utility that solves a concurrency, async, or infrastructure problem?**
      → If yes, that's a pattern. Write it.

   2. **Did I discover a workaround for a framework limitation?** (e.g., "API X doesn't support Y, so I did Z instead")
      → If yes, the workaround is the pattern. Write it.

   3. **Did I iterate through 3+ approaches before finding one that works?**
      → If yes, the failed approaches AND the winning approach together ARE the pattern. Document what didn't work and why. Future agents hitting the same problem need this.
      → **Also write attempt records** for each failed approach in `knowledge/attempts/` using `_TEMPLATE.md`. One file per failed approach (e.g., `SPEC-007-approach-fts5.md`, `SPEC-007-approach-regex.md`). Cross-reference them from the pattern you write (`## Related Patterns` section).

   4. **Would another agent working on a similar spec benefit from knowing my solution?**
      → If yes, write the pattern. If you're unsure, write it anyway — a pattern that's never cited is cheaper than an agent that wastes 2 hours rediscovering a solution.

   **If ANY answer is yes → write the pattern.**

   "Nothing novel" means: the implementation was a straightforward application of existing patterns/APIs with no surprises, no iteration, no workarounds. If you fought the build system, concurrency model, test infrastructure, or framework quirks for more than ~30 minutes, something IS novel — write it down.

   **When writing:** Use the template in `knowledge/patterns/_TEMPLATE.md`. Include:
   - The problem (what you were trying to do)
   - What didn't work (failed approaches — this is often the most valuable part)
   - What worked (the solution)
   - When to reuse / when NOT to reuse

   You MUST do one or the other (write pattern or log skip reason). Silently skipping is not allowed — make the decision explicit. If skipping:
     ```yaml
     knowledge:
       pattern_written: false
       skip_reason: "Straightforward implementation, no novel technique"
     ```

5. **DevKB writeback** (if `config.yaml` → `devkb.writeback: true`):

   After the pattern decision, ask: **Is this lesson cross-project relevant?**

   A pattern is cross-project relevant if:
   - It's about a language/framework quirk (not project-specific logic)
   - Another project using the same tech stack would hit the same problem
   - It's about a tool, build system, or testing pattern

   **If yes → stage a DevKB update:**
   - Write to `.nightshift/knowledge/devkb-updates/<language>-<spec-id>.md`
   - Use this format:
     ```markdown
     # DevKB Update — <spec-id>
     **Target file:** <language>.md (e.g., swift.md)
     **Section:** <where it should go in the DevKB file>
     **Date:** <today>

     ## Entry

     ### <Short title>
     **Problem:** <one-line>
     **Root Cause:** <one-line>
     **Fix:** <the solution>
     **Prevention:** <how to avoid next time>
     ```
   - Log in metrics:
     ```yaml
     devkb_update_staged: true
     devkb_update_file: "<filename>"
     devkb_update_target: "<language>.md"
     ```

   **If no → skip silently.** (Unlike patterns, DevKB writeback doesn't require a skip reason.)

   **Sync process:** Staged updates in `devkb-updates/` are reviewed and merged into the canonical DevKB by a human or scheduled task (outside the loop). The agent never writes directly to the external DevKB path — it only stages proposals.

6. Commit the changelog entry separately if needed:
   ```
   git commit -m "docs(<spec-id>): update CHANGELOG"
   ```

7. **Mark spec as `status: done`** in its frontmatter (update the spec file).
   Before writing source-of-truth frontmatter, use the source fingerprint guard (SPEC-053) when fingerprint metadata exists for this run; if the live file changed since context capture, stop and reconcile instead of overwriting.

   **Terminal done-state checkbox gate (SPEC-161):** Before accepting or committing
   this durable transition, run the validator against the edited spec:
   ```bash
   python3 validate_specs.py <spec-file>
   ```
   A normal `done` spec must have every checkbox in `## Requirements` and
   `## Acceptance Criteria` checked (`[x]`). If validation fails, its diagnostics
   name the exact path, section, line, and checkbox text. Do **not** commit or claim
   completion: return the spec to a non-terminal state, repair the named contract
   items, and rerun the command. Unchecked boxes elsewhere remain outside this gate.

   Only after this command exits zero may the parent lifecycle commit be accepted:
   `chore: mark <spec-id> done`.

   **This step is MANDATORY.** Without it, the spec remains `in_progress` and will
   not be filtered out by Task Selection (step 2), causing re-selection in the next
   loop iteration. In orchestrator mode, the orchestrator also cannot detect completion
   by scanning frontmatter.

**Checkpoint:** After commits are complete, save a final checkpoint (before clearing):
```
import checkpoint
checkpoint.save_checkpoint(
    spec_id=current_spec_id,
    step=12,
    step_name="commit_changelog",
    data={
        "status": "completed",
        "git_branch": current_branch,
        "git_sha": current_commit_hash,
        "working_notes": "All work committed. Changelog updated. Spec is complete.",
        "metrics_so_far": metrics_dict,
        "knowledge_citations": knowledge_citations_list
    }
)
```

**Commit message format:** `GIT.md` § Commit Format is the source of truth.

**Merge to main:** See `GIT.md` § Merge and Post-Merge Validation.
After all commits for the spec are done and tests pass:
1. If working on a feature branch (worktree), merge to `config.git.main_branch` (default: `main`)
2. Use the merge strategy from `config.git.merge_strategy` (default: `no-ff`)
3. Run post-merge validation (build + test on main)
4. If post-merge validation passes → spec is complete, proceed to next step
5. If post-merge validation fails → fix on branch, re-merge, or revert (see ORCHESTRATOR.md § Post-Merge Validation)

**Why:** Granular history makes it easy to review, revert, or trace decisions. Ordinary
commits use the `[SPEC-ID]` prefix; parent lifecycle transitions use the exact
`chore: mark SPEC-ID done|blocked` form so `record_metrics.py --mark-commit` can
attribute the run. Knowledge effectiveness tracking ensures patterns stay accurate
and useful over time.

---

### 13. Metrics Logging

**Metrics are emitted MECHANICALLY by the post-commit hook — you do not have to do
anything here (SPEC-086/087).**

History: earlier loops asked the model to hand-author a ~60-field YAML (honored ~2%
of runs); SPEC-067 reduced that to a script call (still ~1.6% — the call was a
terminal step the model dropped). The 2026-06-14 audit's lesson: *a metrics step
that depends on the agent remembering it does not survive real runs.* So emission no
longer depends on you. When the spec is marked done/blocked (Step 16 / the parent's
`chore: mark SPEC-ID done|blocked` commit), the installed `hooks/post-commit` runs
`record_metrics.py --mark-commit`, which derives the whole row from git + the spec's
report and appends a `failure-ledger.json` entry on non-done. Zero action required
in this step; the row is guaranteed.

**Two things still help, both optional / lightweight:**

1. **Model attribution (one trailer line).** The hook cannot know which model ran.
   When you (or the parent) make the mark-done/blocked commit, add a trailer so the
   row is model-attributed:
   ```
   chore: mark SPEC-ID done

   Nightshift-Model: <your model id>
   ```
   If omitted, the row still emits with `model: unknown` — no failure, just a less
   useful row. This is the ONE thing worth remembering, and it degrades gracefully.

2. **Optional enrichment (only if you want a richer row).** The hook-emitted row is
   correct but coarse (tests parsed from the report; review-cycles/pattern-citations
   not captured). If you want those fields, you MAY call `record_metrics.py` directly
   during the run — but this is **optional enrichment, NOT a mandatory step**. Do not
   treat it as required; the hook already guarantees the row. (Legacy call form below.)

---

### Timestamp Capture (MANDATORY)

All timestamps in metrics MUST come from actual shell commands, not estimates.

**At the START of the loop iteration (Step 1):**
```bash
LOOP_START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```

**At the END of the loop iteration (this step):**
```bash
LOOP_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
STEP13_EPOCH=$(date -u +%s)
```

```python
# SPEC-047 — record the shell-captured metrics-logging start alongside
# the human-readable LOOP_END. validate_metrics.py --fidelity verifies
# `completed_at` in the YAML matches STEP13_EPOCH within ±1s.
events_logger.emit(
    "step_timestamp",
    spec_id=spec_id,
    step=13,
    phase="metrics_logging_start",
    epoch=int(os.environ["STEP13_EPOCH"]),
)
```

**Durations:** you do not capture or compute per-phase durations by hand.
`record_metrics.py` records run-level `started_at` / `completed_at` from
`$LOOP_START` / `$LOOP_END` and sets per-phase `duration_s` to `0` (the loop does
not collect per-phase wall-clock timing). The only timestamps you provide are the
two run-level shell values above.

**Never fabricate timestamps.** A `duration_s: 0` is more honest than a
`duration_s: 900` that was never measured — which is exactly why the script writes
`0` rather than asking you to estimate. Fabricated `started_at` / `completed_at`
break cross-run analysis and the `--fidelity` check.

---

**Optional enrichment — legacy direct call. SKIP THIS unless you specifically want
the richer fields; the hook already emits the row at mark-done. NOT a required step.**

1. (Optional) Emit a richer metrics row with a direct script call:
   ```bash
   python3 .nightshift/record_metrics.py \
     --spec-id "<spec-id>" --spec-file "specs/<filename>" \
     --status completed --outcome done \
     --model "<your model name>" \
     --started-at "$LOOP_START" --completed-at "$LOOP_END" \
     --tests-total <N> --tests-passed <N> \
     --lint-errors <N> --type-errors <N> --build-pass true \
     --review-cycles <N> --completion-score <0.0-1.0> \
     --patterns-written <N> --patterns-injected <N> --patterns-cited <N> \
     --metrics-dir .nightshift/metrics --config .nightshift/config.yaml
   ```
   - `--status` ∈ `completed | failed | blocked | discarded | partial`.
   - `--outcome` ∈ `done | partial | blocked | noop` — a controlled vocabulary that
     makes runs minable. Use **`--outcome noop`** (with `--status completed`) when the
     spec required no code change (already satisfied / duplicate) so no-op runs are
     countable instead of masquerading as feature work.
   - For any **non-`completed`** status you MUST also pass `--error-type` and
     `--error-desc`. The script then appends a one-line entry to
     `metrics/failure-ledger.json` so the failure path is never invisible.
   - Pass `--model "<your model name>"`: `config.yaml`'s `runtime.model` is blank by
     design ("filled at runtime"), and an empty `model` field breaks the cross-model
     comparison metrics exist for. The override wins over config.
   - Other fields you don't pass are **derived** (harness / loop_version / review_mode
     from `config.yaml`; files / lines / commit hash+message from git) or default to
     zero. Never fabricate values — `duration_s: 0` is more honest than an estimate.
   - The script writes `metrics/YYYY-MM-DD_NNN_<spec-id>.yaml` in the schema
     `validate_metrics.py` consumes. Do not also hand-write a YAML.
2. Commit: `metrics: log SPEC-XXX completion`

3. **Propagate pattern effectiveness scores** (R1 from SPEC-P7-001):
   ```
   python3 propagate_scores.py --metrics .nightshift/metrics --patterns .nightshift/knowledge/patterns
   ```
   This updates all pattern files' Effectiveness Tracking tables based on citations in the completed spec's metrics.
   The script is idempotent (tracks processed files in `.nightshift/knowledge/.propagation-log`).
   For dry-run preview: `python3 propagate_scores.py --dry-run`

**Clear checkpoints:** Spec is now fully complete. Remove all checkpoints to clean up:
```
import checkpoint
deleted = checkpoint.clear_checkpoints(current_spec_id)
print(f"Cleaned up {deleted} checkpoint files for {current_spec_id}")
```

**Why:** Metrics reveal patterns. Over time, they show which parts of the loop work and which need improvement. Checkpoints are only for crash recovery; once a spec is complete, they're no longer needed.

---

### 14. Report Generation

**MANDATORY. This step cannot be skipped.** A run without a human review report is an incomplete run. Do not proceed to Step 15 until the report file exists on disk.

**What to do:**
0. **Append production-resource evidence when the spec opted in (SPEC-157).**
   Load the Step 2 snapshot, capture a second stat-only snapshot, and append the
   rendered section to this report. A changed resource defaults to `ambiguous`;
   use `attributed` only when the run has concrete writer evidence, which must be
   supplied verbatim. Never infer causation from a stat delta alone.
   ```python
   from production_resource_gate import (
       compare_snapshots, load_snapshot, render_report_section, snapshot_resources,
   )

   before = load_snapshot(project_root / "reports" / "_wip" / f"production-resource-{current_spec_id}.json")
   after = snapshot_resources(selected_spec_frontmatter)
   production_resource_section = render_report_section(compare_snapshots(before, after))
   # Include production_resource_section verbatim in the report when non-empty.
   ```
1. Generate a concise, human-readable summary of the work:
   ```markdown
   # Nightshift Report — [Date]

   **Outcome:** done
   <!-- Controlled vocabulary — use EXACTLY one of: done | partial | blocked | noop.
        Must match the --outcome value passed to record_metrics.py in Step 13.
        `noop` = spec needed no code change (already satisfied / duplicate).
        One spelling, lowercase — this is what makes reports minable across runs. -->

   ## Summary
   - Specs completed: N of M
   - Tests passed: X/Y (Z%)
   - Build: ✅ pass
   - Lint: ✅ pass
   - Review cycles: avg 1.5

   ## Completed Specs
   - SPEC-001: [Title] — ✅ done
   - SPEC-005: [Title] — ✅ done

   ## Blocked Specs
   - SPEC-010: [Title] — ⏸ blocked (reason in BLOCKED-SPEC-010.md)

   ## Open Questions
   - SPEC-010 § Requirements: [brief question text] — blocker
   - SPEC-007 § AC-3: [brief question text] — advisory
   See specs/{PROJECT}-QUESTIONS-NNN.md for the consolidated tracker.
   If no QUESTIONS spec exists yet, these will be picked up by the next
   `/nightshift address-issues` run.

   ## Discovered TODOs
   - See TODOs-discovered.md for items found during implementation

   ## Suggested Follow-up Specs
   <!-- SPEC-060: Structured follow-up suggestions for the kickoff agent to autocreate. -->
   <!-- If no suggestions: write "(none)" as the body (no list items). -->
   <!-- The kickoff agent will run check_followup_spec.py on each entry and autocreate -->
   <!-- a spec if no conflicts are found. Conflicts and NFR violations are recorded here. -->

   <!-- Zero-suggestion form: -->
   <!-- (none) -->

   <!-- One-or-more-suggestion form (repeat block per suggestion): -->
   - title: "Short description of the suggested work"
     rationale: "Why this is needed — what was found during this run, and why it is out of scope for this spec"
     artifact: "relative/path/to/output_artifact (omit if unknown)"
     domain: "ds | ui | net | be | watch | arch | test | infra | misc"
     layer: 0  # 0=foundation, 1=infra, 2=feature, 3=polish
     parent: ""  # Optional: parent spec ID (e.g. "SPEC-004"). Set when this follow-up
                 # belongs under an existing parent spec. Passed as --parent-id to
                 # check_followup_spec.py so the ID is scoped to that parent (PARENT-NNN)
                 # and cannot collide with follow-ups from other parents.
     # Filled in by kickoff agent after check_followup_spec.py runs:
     outcome: "created SPEC-004-003 | conflict: <reason> | pending (script missing)"

   ## Changelog
   [Include changelog entries from step 12]
   ```
2. **Metrics Fidelity section (SPEC-047)** — before writing the report,
   run the plausibility checks and paste the rendered markdown into a
   new `## Metrics Fidelity` section:
   ```bash
   python3 canonical/validate_metrics.py .nightshift/metrics \
       --fidelity \
       --events-file .nightshift/runs/<run_id>/events.jsonl \
       --format markdown
   ```
   If the output is `_All metric fidelity checks passed._`, include that
   line verbatim. If warnings are present, include the rendered table —
   this makes synthetic timestamps and round durations visible in the
   report instead of hidden in the YAML. ≥3 warnings additionally emit
   `metrics_fidelity_low` (severity `high`) to `events.jsonl`; the run
   still completes.
3. Write to `reports/YYYY-MM-DD-nightshift-report.md`
4. **Verify the file exists** — confirm `reports/YYYY-MM-DD-nightshift-report.md` is present and non-empty before continuing. If it is missing or empty, write it again.
5. Commit: `[SPEC-XXX] docs: generate nightshift report`

**Why:** A human can scan the report in 2 minutes and know if anything needs attention. This is the primary deliverable of a Nightshift run — not just the code, but the audit trail.

---

### 15. Check Watcher Feedback

**What to do:**
1. Read `.nightshift/WATCHER-REVIEW.md` (if it exists)
2. Look for feedback on the current spec (check the `## SPEC-XXX` section)
3. If feedback exists:
   - Read all findings
   - For **blocking** issues: stop, fix the code, re-run validation, re-review
   - For **warnings** / **notes**: log them in metrics, continue to step 16
4. Append a line to mark the feedback as `acknowledged`:
   ```markdown
   ### Acknowledged
   Processed by loop at 2026-03-17T23:30:00Z — See metrics for details.
   ```

**Why:** The watcher provides independent review while the main loop works. This pulls in that feedback before moving on.

---

### 16. Loop

**What to do:**
1. Return to step 2 (Task Selection) to pick the next spec
2. Or, if no more ready specs:
   - **Gate: verify `reports/YYYY-MM-DD-nightshift-report.md` exists and is non-empty.** If it does not exist, go back to Step 14 now — do not exit without it.
   - Commit all changes
   - **Ingest into cross-project history DB (SPEC-040):** after per-spec metrics have been finalized, call `execution_history.ingest_run_and_log()` for the completed run. Ingestion is **idempotent** (keyed on `run_id` — re-running the same run is a no-op) and **non-fatal**: any failure logs a `history_ingest_failed` event to the run's `events.jsonl` and the loop continues to exit cleanly.

     ```python
     from pathlib import Path
     from execution_history import ingest_run_and_log

     # R2: canonical project_root. Prefer config.yaml project.root if set,
     # otherwise infer from the spec's parent-of-.nightshift/ (the project root).
     project_root = Path(config.get("project", {}).get("root", Path.cwd()))
     nightshift_dir = project_root / ".nightshift"

     ingest_run_and_log(
         nightshift_dir=nightshift_dir,
         run_id=run_id,
         project=config.get("project", {}).get("name", ""),
     )
     ```

     A successful ingest appends a `history_ingest_succeeded` event; a failed one appends `history_ingest_failed`. Either way, control falls through to `loop_complete: true` — never raise out of Step 16 because of history.
   - **Shell timestamp — loop exit (SPEC-047).** Capture the final shell
     epoch and write the third mandatory `step_timestamp` event. Together
     with Step 1 and Step 13 this gives `metrics_fidelity.py` a full
     start/middle/end triangulation.
     ```bash
     STEP16_EPOCH=$(date -u +%s)
     ```
     ```python
     events_logger.emit(
         "step_timestamp",
         spec_id=None,
         step=16,
         phase="loop_exit",
         epoch=int(os.environ["STEP16_EPOCH"]),
     )
     ```
   - Emit `loop_complete: true` signal
   - Exit cleanly

---

## Post-Run Metrics Emission

Per-spec metrics are emitted during **Step 13** by `record_metrics.py` — one
schema-valid YAML per spec, in the format `validate_metrics.py` and
`analyze_metrics.py` already consume. There is **no** separate post-run JSON
aggregate: cross-run and cross-model analysis reads the per-spec YAMLs directly via
`analyze_metrics.py`, so a second hand-built aggregate would only drift.

Metrics remain part of the loop contract: a completed spec with no metrics file in
`metrics/` means the loop exited abnormally — treat a missing file as a defect, not
a choice. Non-`completed` runs additionally append to `metrics/failure-ledger.json`
(handled by `record_metrics.py`), so the failure path is always recorded.

---

## Stall Detection & Circuit Breaker

The loop monitors for signals that indicate it's stuck and can't progress.

### Stall Signals

| Signal | Threshold | Meaning |
|--------|-----------|---------|
| **Same build error repeated** | 3 consecutive identical errors | Agent is trying the same fix or can't diagnose the root cause |
| **Review cycle count** | >5 full review rounds | Agent keeps producing code that reviewers reject |
| **Test pass rate not improving** | 3 implementation attempts with same or worse pass rate | Agent is not converging on a solution |
| **Phase duration exceeded** | 3x the running average for that phase | Something is fundamentally wrong, not just slow |
| **Total spec duration** | Configurable max (default: 2 hours) | Hard ceiling regardless of progress signals |

### What Happens on Stall

When any stall signal triggers:

1. **Stop work immediately** — don't attempt another fix
2. **Write a BLOCKED report** to `reports/BLOCKED-<spec-id>-<timestamp>.md`:
   ```markdown
   # Blocked: SPEC-XXX

   **When:** [timestamp]
   **Phase:** [which step of the loop]
   **Signal:** [which stall signal triggered]
   **Failure class:** environment | baseline_red | spec_validation | runtime_error | circuit_breaker

   ## What Was Attempted
   - Attempt 1: [brief description + error]
   - Attempt 2: [...]
   - Attempt 3: [...]

   ## Root Cause Hypothesis
   Agent's best guess at what's wrong and why.

   ## What a Human Needs to Do
   Specific suggestions for unblocking (e.g., "clarify spec requirement X",
   "provide API documentation", "fix infrastructure").
   ```
3. **Distill knowledge** — Even failed work has value. Write a per-attempt knowledge file:
   ```
   Save to: knowledge/attempts/SPEC-XXX-short-description.md

   # SPEC-XXX: [Title] — [Approach tried]

   **Spec:** SPEC-XXX
   **Date:** YYYY-MM-DD
   **Status:** failed | blocked | discarded
   **Problem area:** [e.g., search, auth, data-layer — for auto-discovery]

   ## What Was Tried
   Brief description of the approach and why it seemed promising.

   ## Why It Failed
   Root cause (not just the symptom). What stall signal triggered?

   ## What We Learned
   Insights about the problem space. What does this rule out? What does it suggest?

   ## Revisit If
   Conditions under which this approach might work (e.g., "if dataset exceeds 100K",
   "if a native FTS extension becomes available", "if memory budget doubles").
   ```
   This file survives even when the code is reverted. Future specs tackling the same
   problem area will find it via auto-discovery (LOOP step 3) or explicit `prior_attempts`
   references in their frontmatter.

   **Success patterns (when spec completes):** When a spec succeeds (not stalls), the agent should also check: "Did I use an approach that's worth reusing?" If yes, write a success pattern to `knowledge/patterns/` using the template. Not every success needs a pattern — only approaches that solve a recurring problem or demonstrate a non-obvious technique.
4. **Revert working tree** — Clean up: `git checkout .` or `git stash drop` to remove failed code.
   The code is gone, but the learning is preserved in `knowledge/`.
5. **Log metrics** with `status: discarded` and full failure details
6. **Mark spec as `status: blocked`** in its frontmatter (update the spec file).
   Parent kickoff exception: when this run was launched by the board-copied
   `/nightshift kickoff <SPEC-ID>` prompt, the parent kickoff agent must
   coordinate one focused unblock pass before committing a blocked status unless
   the blocker requires human/external input, the unblock task is not actionable,
   or continuing would be unsafe. If the spec is still blocked afterward, the
   Block Reason must include the unblock attempt or why it was skipped.
   Exception: NFR-family specs (`id: NFR-*` or `type: nfr`) are never blocked.
   Keep or normalize them to `status: active` (unless already `retired`) and
   record the pending/failure state under `## Active Run State`, `## Pending
   Inputs`, or `## Run Log`. If an NFR check failed, block the triggering spec
   or create/link a violation bug with `violates: [NFR-001]`.
   For normal executable specs, keep the real spec title as the first body H1 and add `## Block Reason` as the
   first content section after that title:
   ```markdown
   # SPEC-XXX - Real Spec Title

   ## Block Reason

   [Why this spec was blocked. Include:]
   - Which phase stalled and why
   - What was tried (reference knowledge/attempts/ entry)
   - What would need to change to unblock
   - If the spec itself is ambiguous: which requirements are unclear
   ```
   This is mandatory — a blocked spec without a Block Reason is a data loss.
7. **Check cascading blocks** — if other specs have `after: [THIS_SPEC_ID]`, mark them
   blocked too, with a Block Reason explaining which part of this spec they need.
8. **Attempt next spec** — don't stop the entire loop
9. **If all remaining specs are blocked or done** → write final report, stop loop

### Manual Stop

A human can create a `STOP` file (empty) in `.nightshift/`. The loop checks for this between iterations:

1. Finish current phase cleanly (don't abandon mid-write)
2. Commit any work in progress
3. Write a partial report
4. Log metrics with `status: stopped`
5. Exit
6. Delete `STOP` file so the next run starts clean

---

## Configuration

All behavior is configurable in `config.yaml`. Key sections:

- `commands` — build, test, lint, type_check, format commands
- `conventions` — project-specific patterns to follow
- `circuit_breaker` — thresholds for stall detection
- `git` — main branch, branch prefix, commit style
- `review` — which personas to invoke, extra criteria

---

## Quick Reference

**Key files:**
- `config.yaml` — read for commands, conventions, circuit breaker thresholds
- `specs/` — read to pick next task (step 2)
- `knowledge/` — read for context (step 3)
- `.nightshift/WATCHER-REVIEW.md` — read for feedback (step 15)

**Key commits:**
- After test writing: `test(<spec-id>): add tests (red)`
- After implementation: `feat(<spec-id>): implement <spec-id>`
- After review fixes: `fix(<spec-id>): address review feedback`
- Metrics: `metrics: log <spec-id> completion`
- Reports: `docs: generate nightshift report`

**Key outputs:**
- Metrics: `metrics/YYYY-MM-DD_NNN_<spec-id>.yaml`
- Report: `reports/YYYY-MM-DD-nightshift-report.md`
- Blocked: `reports/BLOCKED-<spec-id>-<timestamp>.md`
- Failed approaches: `knowledge/attempts/SPEC-XXX-description.md`
- TODOs: `reports/TODOs-discovered.md`

---

> This loop is designed to run unsupervised. Trust the process. A human reviews the results in the morning.
