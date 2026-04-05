# Orchestrator Protocol

## Orchestrator Capability Requirements

The orchestrator role requires a model capable of:
- Following multi-step protocols with conditional branching across 3+ specs
- Remembering and executing post-merge validation steps after each spec
- Managing git worktrees (create, merge, clean up) without losing track
- Writing structured YAML that matches a schema exactly
- Making model selection decisions based on spec metadata

**Minimum capability tier: tier-2** (see config.yaml → runner.tiers)

If the orchestrator is below tier-2 capability, expect: missed validation steps,
wrong metrics format, incomplete merges. (Proven in Run2: Haiku orchestrator
ignored 3 of 4 Phase 8 improvements.)

---

**Purpose:** When multiple specs are ready and context bloat is a concern, delegate each spec to a fresh sub-agent instead of running all specs in one session. The orchestrator manages sequencing, failure handling, and rollup reporting.

**When to use orchestrator mode:**
- 3+ specs are ready (`config.yaml` → `runner.mode: "orchestrator"`)
- Context window management matters (long-running projects)
- Independent review per spec is desired

**When to use inline mode (LOOP.md):**
- 1–2 specs ready (default, `runner.mode: "inline"`)
- Simple projects with fast builds
- Early bootstrap runs

---

## Orchestrator Flow

### 1. Bootstrap
- Read `config.yaml`, verify clean git tree, run pre-flight (same as LOOP.md step 1)
- Verify `runner.mode == "orchestrator"` is set
- Verify all fields present: `runner.model`, `runner.harness` are non-empty
- Log: orchestrator session started, timestamp

### 2. Task Queue

#### 2.1a Pre-Computed Plan Check (NEW — Hierarchical Specs)

Before applying the Task Selection Algorithm, check for a pre-computed execution plan:

```
if execution-plan.json exists in specs/ directory:
    plan = read execution-plan.json
    if plan.source_spec matches the spec being run:
        task_queue = plan.execution_order
        nfr_map = plan.nfr_injections
        log "Using pre-computed plan from execution-plan.json"
        → skip to §3 (For Each Spec)
else:
    log "No plan file — computing order inline"
    → continue with Task Selection Algorithm below
```

The `execution-plan.json` file is produced by `nightshift-dag plan <SPEC-ID>` (see SPEC-004-003). It contains:
- `execution_order`: ordered list of executable spec IDs
- `nfr_injections`: map of spec ID → list of NFR constraint IDs
- `cycles`: any detected dependency cycles (blocked specs excluded from order)

If the plan file exists but is stale (its `source_spec` doesn't match), ignore it and compute inline.

#### 2.1b Main Spec Detection (NEW — Hierarchical Specs)

If the spec being run has `type: main` in its frontmatter:

```
if spec.type == "main":
    DO NOT delegate this spec to a sub-agent.

    1. Read spec's children: and implementation_order: fields
    2. Run: nightshift-dag plan <SPEC-ID> --specs-dir specs/
       → generates/validates execution-plan.json
    3. Read execution-plan.json
    4. Set main spec status: in_progress (update file, commit)
    5. Add children to task_queue in execution_order
    6. Process each child as a normal spec (§3)

    When last child completes successfully:
        Set main spec status: done (update file, commit)
        Log "Main spec <SPEC-ID> complete — all children done"

    If any child fails:
        Log failure, leave main spec as in_progress
        Human must decide next step
```

Main specs are containers. They describe WHAT a feature achieves but are never executed as code tasks. Their children are the executable units.

#### 2.1c Task Selection Algorithm

- Read `specs/` and apply the Task Selection Algorithm (LOOP.md step 2)
- Build ordered list of ready specs to delegate
- Log: task queue size, first spec, any dependencies detected

### 3. For Each Spec

#### 3.x NFR Constraint Injection (NEW — Hierarchical Specs)

When constructing a sub-agent brief, inject NFR constraints if available:

```
if nfr_map exists (from §2.1a) AND spec_id in nfr_map:
    nfr_ids = nfr_map[spec_id]
    if nfr_ids is non-empty:
        for each nfr_id in nfr_ids:
            nfr_file = find specs/NFR-{nfr_id}-*.md
            constraint_text = extract ## Constraint section from nfr_file
            if found:
                add to brief_constraints list

        Prepend to sub-agent brief:

        ## Quality Constraints (must satisfy)
        • [constraint text from NFR 1]
        • [constraint text from NFR 2]

        These constraints are binding acceptance criteria.
        Violations fail the spec even if all explicit ACs pass.
```

If no `nfr_map` exists (flat-spec project, no plan file), skip this step entirely. The brief is unchanged for backwards compatibility.

#### a2. Check Previous Reflection (if orchestrator mode)

Before writing the next spec's brief:

1. Run:
   ```bash
   python3 check_reflection.py --spec <PREV_SPEC_ID> --output-dir .nightshift/reflections --since <timestamp>
   ```
   where `<timestamp>` is the ISO 8601 timestamp you noted after launching the previous spec's reflection (step c2)

2. If `done: true` and `new_patterns` is non-empty:
   - Add to the next spec's brief: "New patterns available from {PREV_SPEC_ID}: {list}"
   - The sub-agent's LOOP step 3a will pick them up via normal pattern injection

3. If `done: false`:
   - Log: "Reflection from {PREV_SPEC_ID} still running — proceeding without"
   - Patterns will be available for subsequent specs

#### a. Sub-Agent Tier Selection

When `runner.model_selection` is "auto", determine the sub-agent tier from spec frontmatter:

| Criteria | Tier |
|---|---|
| type: bugfix AND layer: 1 | tier-1 |
| type: bugfix AND layer: 2+ | tier-2 |
| type: feature AND ac_count ≤ 3 | tier-1 |
| type: feature AND ac_count 4-8 | tier-2 |
| type: feature AND ac_count 9+ | tier-3 |
| layer: 3 (architectural) | tier-3 |

Read the tier's model and harness from `config.yaml → runner.tiers.<tier>`.
If the computed tier doesn't exist in config (e.g., no tier-3 defined), fall back to the highest available tier.
Log the chosen tier, model, and harness in the brief.

When `runner.model_selection` is "fixed", always use tier-1 for all sub-agents.

#### a_brief. Known Issues from Previous Specs

If a previous spec's post-merge validation failed and was reverted:

Include in the brief:
```
KNOWN ISSUE from SPEC-XXX (reverted):
[description of what broke + error output]

This may affect your work if you touch the same files.
Focus on YOUR spec — do not re-implement the reverted spec.
If your pre-flight fails because of this, attempt a minimal fix
(the error details above should help) and proceed.
```

If a previous spec was merged successfully but with warnings (e.g., test flakiness):
```
NOTE from SPEC-XXX (merged with warnings):
[description of the warning]
```

#### a_brief. Write Brief
Write a brief for the sub-agent — WHAT to achieve, not HOW. Template:

```markdown
## Task
Execute LOOP.md for spec: {SPEC_FILE}

## Context
- Project root: {PROJECT_ROOT}
- Nightshift config: .nightshift/config.yaml
- Protocol: .nightshift/LOOP.md
- Knowledge: .nightshift/knowledge/
- DevKB files: [list relevant DevKB files based on spec domain]

## Instructions
1. Read .nightshift/BOOTSTRAP.md phases E1–E4 (knowledge & loop entry)
2. Your assigned spec is {SPEC_FILE} — execute this spec ONLY
3. Follow LOOP.md steps 1–15 for this spec only
4. Write metrics to .nightshift/metrics/
5. Commit your work with conventional commit format

## Constraints
- Execute ONLY the assigned spec. Do NOT pick a different spec.
- Do NOT read or modify other specs in specs/
- Do NOT loop back to task selection (LOOP step 16) — return after one spec
- Write a success pattern to knowledge/patterns/ if your approach is reusable

## Runtime Fields
Include these values in your metrics YAML:
- harness: "{HARNESS_NAME}" (from config.yaml runner.harness)
- model: "{MODEL_NAME}" (from config.yaml runner.model)
- loop_version: "{LOOP_VERSION}" (from config.yaml runtime.loop_version)

These enable model/harness/loop version comparison in analyze_metrics.py.
```

#### b. Launch Sub-Agent
- **Mark spec as `status: in_progress`** in its frontmatter on the main branch before launching.
  Commit: `chore(<spec-id>): mark in_progress`
- Use Agent tool with isolation: "worktree"
- Pass the brief and all context
- Sub-agent runs in a clean git worktree with isolated context window

#### c. Wait & Receive
- Sub-agent executes LOOP.md steps 1–15 autonomously
- Returns: completion status, commit hash, metrics file path

#### c2. Launch Async Reflection (if orchestrator mode)

After receiving sub-agent results:

1. Launch background reflection:
   ```bash
   ./reflect_async.sh <SPEC_ID> .nightshift/metrics .nightshift/knowledge/patterns .nightshift/reflections
   ```
2. Note the current timestamp (ISO 8601, e.g., `2026-03-18T14:30:00Z`) for use with `--since` filtering later
3. Continue immediately to step 3d (Assess Result) and then to the next spec

**Why async?** The reflection runs in the background while you work on the next spec. Insights from spec 1's reflection may be available to specs 2 and 3 in the same run, improving decision-making. See the `a2` step below for how to check for completed reflections.

#### d. Assess Result

Before merging, validate metrics:

```bash
python3 .nightshift/validate_metrics.py <metrics_file>
```

If validation fails: log warnings in the orchestrator report but still merge (metrics quality is important but shouldn't block working code).

| Status | Action |
|--------|--------|
| **completed** | Merge worktree → main, continue to post-merge validation |
| **failed** | Write failure summary (see below), check for cascading blocks, continue |
| **blocked** | Log to failure report, check dependencies, continue |
| **discarded** | Log outcome, continue (knowledge preserved in knowledge/) |

### Post-Merge Validation

After merging a spec's worktree to main:

1. Checkout main and run a clean build + test:
   ```bash
   git checkout main
   <commands.build>
   .nightshift/run_with_timeout.sh <commands.test_timeout_s> <commands.test>
   ```

2. **If build and test PASS:**
   - Main is green.
   - **Verify spec status:** Check that `specs/{SPEC_ID}.md` has `status: done` in frontmatter.
     If the sub-agent forgot to mark it (common with worktree merges), update the spec
     frontmatter to `status: done` and commit: `chore(<spec-id>): mark done (orchestrator)`
   - Proceed to next spec.

3. **If build or test FAIL:**
   a. This spec's merge broke main. Send the failure back to the SAME sub-agent:
      ```
      Your merge broke main. Here is the error output:
      [paste error output from build or test]

      Fix it on your branch, then signal ready for re-merge.
      ```
   b. The agent has full context of what it changed — it should fix in 1 attempt.
   c. Re-merge the corrected branch and re-validate.
   d. If the agent's fix works → proceed to next spec.
   e. If the fix fails OR the agent can't fix it:
      - Revert the merge: `git revert --no-edit <merge_commit>`
      - Mark the spec as "failed" with `error_type: "post_merge_regression"`
      - Record the failure details (error output, files involved) in the next spec's brief as a KNOWN ISSUE
      - Proceed to next spec

4. Record post-merge validation result in the orchestrator report:
   ```
   Post-merge validation: PASS | FAIL (reverted) | FAIL (fixed by agent)
   ```

#### e. Report Per-Spec
Append result to running report:

```markdown
### {SPEC_ID} — {Title}
- Status: completed | failed | blocked | discarded
- Duration: Xs
- Commit: {hash}
- Tests: N passed, M failed (if any)
- Metrics: {metrics file path}
```

### 4. Failure Handling

When a sub-agent returns non-completed status:

1. **Read metrics and reports** — understand what happened
2. **Check dependencies** — do any remaining specs have `after: [{FAILED_SPEC_ID}]`?
   - Yes → mark those specs `status: blocked` (cascading block)
   - **For each cascading block:** add a `# Block Reason` section as the FIRST section
     in the blocked spec. The Block Reason MUST specify:
     - Which dependency failed/is blocked (spec ID)
     - Which specific requirements/functionality of that spec this one needs
     - What would unblock the chain
     Example:
     ```markdown
     # Block Reason

     Blocked by SPEC-010 (Database Migration Layer) which failed during implementation.
     This spec needs SPEC-010's migration runner (R1) and schema versioning (R3) to
     create the tables defined in Requirements R1-R4.
     Unblock path: fix SPEC-010 failure (see reports/BLOCKED-SPEC-010-*.md) → rerun → unblock this.
     ```
   - No → continue to next spec
3. **Write failure summary** to `reports/_wip/failures-{date}.md`:
   ```markdown
   ### {SPEC_ID} — {STATUS}
   **Phase:** {failure.phase}
   **Error:** {failure.description}
   **Root cause hypothesis:** {failure.root_cause}
   **Suggestion:** {failure.suggestion}
   **Dependent specs:** {any specs blocked by this, with which requirements they need}
   ```
4. **Continue** to next spec (don't stop entire run)

### 5. Final Report

After all specs processed, write consolidated report to `reports/YYYY-MM-DD-nightshift-report.md`:

```markdown
# Nightshift Report — Orchestrator Run

**Date:** YYYY-MM-DD
**Mode:** orchestrator
**Specs attempted:** N
**Specs completed:** M
**Specs failed:** F
**Specs blocked:** B

## Completed Specs
- SPEC-001: [Title] — ✅ completed
- SPEC-005: [Title] — ✅ completed

## Failed Specs
- SPEC-010: [Title] — ❌ failed (see failures report)

## Blocked Specs
- SPEC-015: [Title] — ⏸ blocked (awaits SPEC-010)

## Summary Metrics
- Total duration: Xs
- Avg spec duration: Ys
- Avg review cycles: N.N
- Total tests: T (passed P, failed F)
- Total files changed: F

## Discovered TODOs
- See TODOs-discovered.md for items found during implementation
```

### 6. Metrics Roll-Up

Aggregate metrics from all spec runs:

```markdown
# Metrics Summary

- Total completed: N specs
- Total duration: Ts (hours)
- Average per spec: Ys
- Model used: {model}
- Harness: {harness}
- Loop version: {version}

## Per-Persona Review Metrics
- Architect: N blocking issues (avg X per spec)
- Security: N issues found
- Performance: N issues found
- Domain: N issues found
- Quality: N issues found
- User: N issues found

## Failure Breakdown
- Build errors: N specs
- Test failures: N specs
- Review rejections: N specs
```

### 7. Cleanup & Commit

1. Commit all reports and metrics together:
   ```
   git add reports/ metrics/ .nightshift/specs/
   git commit -m "docs: orchestrator run report and final metrics"
   ```
2. Clean up `reports/_wip/` (temporary failure summaries merged into final report)
3. Emit completion signal

---

## Sub-Agent Brief Template (Detailed)

Use this for actual delegation:

```markdown
## Task
Execute LOOP.md for a single spec in this Nightshift project.

## Context

**Project:** {project_name}
**Project root:** {absolute_path}
**Primary languages:** {languages from config.yaml}

**Key files to understand:**
- `.nightshift/config.yaml` — project commands, conventions, circuit breaker
- `.nightshift/LOOP.md` — 16-step cycle you'll follow
- `.nightshift/BOOTSTRAP.md` — (read phases E1–E4 only)
- Your assigned spec: `specs/{SPEC_ID}.md`
- Relevant knowledge files in `.nightshift/knowledge/` (use your judgment)

**DevKB context:**
Before starting, read these files from `_System/DevKB/` if they apply to your spec:
- {RELEVANT_DEVKB_FILES} (selected based on spec domain)

## Instructions

1. **Read BOOTSTRAP.md phases E1–E4:**
   - E1: Read knowledge files in `.nightshift/knowledge/`
   - E2: Survey specs queue (understand the full landscape)
   - E3: Check for STOP signal (verify you can proceed)
   - E4: Skip the "enter loop" routing — you're already in orchestrator mode

2. **Your assigned spec is `specs/{SPEC_ID}.md`**
   - Read it completely
   - This is the ONLY spec you will execute
   - Do NOT pick a different spec
   - Do NOT work on multiple specs

3. **Execute LOOP.md steps 1–15:**
   - Step 1: Pre-flight check
   - Step 2: Task selection (you're assigned {SPEC_ID} — skip the algorithm)
   - Steps 3–15: Full 16-step cycle for your spec
   - Do NOT do step 16 (loop back to task selection)
   - Return after step 15 (commit, metrics, report)

4. **Write metrics to `.nightshift/metrics/`:**
   - File name: `YYYY-MM-DD_NNN_{SPEC_ID}.yaml`
   - **METRICS FORMAT:** Your metrics YAML MUST match `metrics/_SCHEMA.md` exactly. All phase sections with `duration_s` fields are required. Do not use alternative formats (acceptance criteria checklists, freeform notes). The orchestrator will validate your metrics after completion and flag non-compliance.
   - CRITICAL: Include these runtime fields from config.yaml:
     ```yaml
     loop_version: "{from config.yaml runtime.loop_version}"
     model: "{from config.yaml runner.model}"
     harness: "{from config.yaml runner.harness}"
     review_mode: "{from config.yaml review.mode}"
     ```
   - These fields enable orchestrator metrics aggregation

5. **Commit your work:**
   - Use conventional commit format: `feat(SPEC-ID): <description>`
   - Include Nightshift trailers: `Nightshift-Loop:`, `Spec:`, `Phase:`
   - One logical commit per spec (or incremental during implementation)

6. **Optional: Success pattern**
   - If your approach is reusable, write to `knowledge/patterns/PATTERN-name.md`
   - If not, log your reasoning in metrics under `knowledge.pattern_written: false`

## Constraints

- **Single spec only** — execute your assigned spec, nothing else
- **No spec selection** — don't loop back to LOOP step 2
- **No context expansion** — don't read unassigned specs or touch other worktrees
- **No harness changes** — use the harness/model from config.yaml
- **Clean commits** — conventional format, descriptive messages
- **Test timeout:** If test command runs longer than `config.yaml` → `commands.test_timeout_s` seconds, the process will be killed and exit code 124 returned. When this happens:
  1. Log "Test hang detected"
  2. Retry ONCE: run `commands.build` first (clean build), then test again with the same timeout
  3. If retry also times out (exit 124), fail the spec with `error_type: "test_hang"` — do not attempt further retries
  4. Record in metrics: `phases.validation.test_hang_detected: true` (or preflight if hang was detected in pre-flight)
  - Use `.nightshift/run_with_timeout.sh` wrapper as documented in LOOP.md Test Timeout Protocol

## Build & Verify

All verification happens in your LOOP.md execution. Orchestrator will assess via metrics.

## DevKB References

[Include specific DevKB entries relevant to the spec's domain]
```

---

## Failure Detection & Escalation

### Sub-Agent Failure Signals

Sub-agent signals failure via:
- Metrics file with `status: failed | blocked | discarded`
- A BLOCKED report in `reports/BLOCKED-{SPEC_ID}-{timestamp}.md`
- Non-zero exit from the Agent tool

### Orchestrator Escalation Logic

```python
if sub_agent_status == "completed":
    merge_worktree()
    continue_next_spec()

elif sub_agent_status in ["failed", "blocked", "discarded"]:
    mark_spec_status(spec_id, sub_agent_status)  # Update frontmatter!
    read_metrics_and_reports()
    write_failure_summary(reports/_wip/failures-{date}.md)

    # Check for cascading blocks
    dependent_specs = specs_with_after_dependency(current_spec_id)
    for spec in dependent_specs:
        mark_as_blocked(spec)

    continue_next_spec()  # Don't stop entire run

else:
    # Unknown status — log and continue
    log_warning(f"Unknown status: {sub_agent_status}")
    continue_next_spec()
```

---

## Exit Conditions

**Stop orchestrator when:**
1. All specs are processed (completed, failed, blocked, or discarded)
2. A STOP file is detected (manual pause — same as LOOP.md)
3. All remaining specs are marked `status: blocked` (cascading failure)

**Outcome:**
- Write final report to `reports/YYYY-MM-DD-nightshift-report.md`
- Commit all changes
- Emit completion signal

---

## Multi-Model Comparison Mode

When `config.yaml → comparison.enabled: true`, the orchestrator enters multi-model comparison mode.

### Flow

1. **For each spec in the queue:**
   - For each model in `comparison.models[]`:
     - Set `runner.model` and `runner.harness` from the model config entry
     - Launch sub-agent in worktree (same as single-model mode)
     - Sub-agent executes LOOP.md steps 1–15 with the assigned model
     - Metrics are written to `.nightshift/metrics/` with the model name in the filename

2. **After all models complete all specs:**
   - Run `python3 .nightshift/compare_models.py .nightshift/metrics --format text`
   - Generate comparison report grouped by `task_id` (spec)
   - For each spec: show side-by-side comparison of all models' results
   - Models ranked by average composite score across all specs
   - Report written to `comparison.report_dir` (default: `reports/model-comparison/`)

3. **Result:**
   - Metrics directory contains runs for each (spec, model) pair
   - Comparison report provides human-readable analysis
   - JSON output available via `--format json` for programmatic use

### Key Points

- Each model runs independently — no cross-model interference
- Metrics YAML must include `model` and `harness` fields for traceability
- If a spec has only one model, it's skipped in the comparison output
- Missing or inconsistent fields are handled gracefully (defaults/N/A)

---

## Integration with BOOTSTRAP.md

**BOOTSTRAP.md phase E4** (line ~480) already routes correctly:

> **If `runner.mode: orchestrator`** (or unset and multiple specs are ready):
> - **Read:** `.nightshift/ORCHESTRATOR.md`
> - Follow the orchestrator protocol — delegate each spec to a fresh sub-agent

This orchestrator.md fulfills that contract. No changes needed to BOOTSTRAP.md.

---

## Consistency with LOOP.md

- **Task selection:** Orchestrator uses LOOP.md step 2 algorithm once at the top
- **Sub-agent execution:** Each sub-agent follows LOOP.md steps 1–15 exactly
- **Metrics format:** Same YAML schema as LOOP.md step 13, plus runtime fields
- **Reports:** Same structure and commit format as LOOP.md step 14
- **Knowledge:** Same `knowledge/` directory, same discovery logic (LOOP.md step 3)

The orchestrator is a thin wrapper around LOOP.md, not a replacement.
