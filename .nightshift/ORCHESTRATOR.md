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

**Git policy:** `GIT.md` is the source of truth for worktrees, status commits,
commit format, merge strategy, and post-merge validation. This document describes
orchestrator sequencing and references that policy.

## Kickoff Parent Progress Contract

An orchestrator may be launched by a parent kickoff agent, for example through a
board-copied `/nightshift kickoff <SPEC-ID>` prompt. In that mode, the parent
agent does not implement or validate the spec directly. It launches the
orchestrator, monitors progress, and reports evidence back to the human.

The orchestrator knows it is running under a kickoff parent when its launch brief
contains a `## Kickoff Parent Context` section. If that section is absent, this
progress contract is optional.

When running under a kickoff parent, the orchestrator must make progress
inspectable:

1. Choose and state a progress cadence based on spec size and risk.
   - Small/simple spec: update after each major phase.
   - Medium/large/risky spec: update at least every 10-15 minutes or after each
     major phase, whichever comes first.
2. Write live progress to `reports/_wip/orchestrator-progress-<SPEC-ID>.md`.
3. Update that file with:
   - current phase,
   - last completed action,
   - next planned action,
   - active blocker or stuck signal, if any,
   - latest evidence paths such as metrics, reports, verification artifacts, or
     commits.
4. If asked by the parent kickoff agent for status, answer from the current
   progress file and then continue the run.
5. If the orchestrator believes the spec is blocked or cannot proceed, report
   the exact blocker, what has already been tried, latest evidence paths, and
   the smallest focused unblock task that should be attempted next. The parent
   kickoff agent will coordinate one unblock pass before any blocked status is
   committed unless the blocker requires human/external input or continuing is
   unsafe.

`reports/_wip/` is intentionally used for this live progress artifact because it
is already gitignored and reserved for in-flight run scratch state.

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

### Dynamic Admission Frontier (SPEC-139-001)

Before concurrent dispatch, compute the current frontier from durable spec
status rather than treating static DAG layers as a launch instruction. A ready
spec is eligible only when every `after:` dependency is `done`; descendants of a
`blocked` or `failed` dependency are blocked with that exact ancestor, while
unrelated work remains eligible. Cycles and missing dependencies are invalid and
never dispatched.

Use `nightshift-dag.py admission --worker-limit <N>` to write
`admission-plan.json` and `admission-plan.md` beside the specs. The plan records
every admitted, deferred, blocked, and invalid candidate. It also compares
declared `touches:` surfaces against active and newly admitted work. The default
`parallel_admission.missing_touches_policy: exclusive` treats empty/coarse
surfaces conservatively; do not silently infer parallel safety from missing
metadata. Recompute after every completion or failure so newly unblocked work can
fan out without waiting for an unrelated worker.

### Bounded worktree dispatch (SPEC-139-002)

Parallel dispatch is opt-in: set `parallel_admission.worker_limit` to an integer
of at least `2`. Missing, zero/one, or malformed settings retain sequential
coordination. Before every launch the coordinator runs the worktree janitor,
records the durable `in_progress` checkpoint, then assigns exactly one spec to
one unique branch, worktree, and run id. Worker artifacts live below
`.nightshift/runs/<run-id>/<spec-id>/`; workers report only their own outcome.

After any outcome the coordinator releases capacity, recomputes the live
frontier, and refills it immediately. A crash becomes recoverable `pending`
state and does not leak a slot. Concurrent workers never merge branches
directly; the coordinator retains integration ownership (SPEC-139-003).

### Serialized integration queue and fresh-main validation (SPEC-139-003)

Completed workers enter one coordinator-owned queue; dispatch completion does
not mean `done`. The queue sorts candidates deterministically, compares both
`touches:` and actual `main...branch` changed files against already accepted
work, then rebases/reconciles each candidate onto the current main branch.

For each accepted merge it runs the configured build/test gate from main and
records separate evidence. A conflict or overlap holds only that candidate and
keeps its worktree. A validation failure returns raw output to the originating
worker for the configured bounded repair attempt; exhaustion reverts the merge,
blocks only its dependency descendants, and retains the branch. No queue cleanup
occurs before main is green and durable `done` status has been recorded.

### Safe bounded parallel operation (SPEC-139-004)

Use parallel mode only after checking the graph, repository, and test
environment. Worktrees isolate concurrent edits; they do **not** establish that
two specs are compatible. One coordinator is the sole owner of lifecycle
transitions and merge decisions.

Before enabling `parallel_admission.worker_limit >= 2`:

1. Verify every prerequisite is declared in `after:` and the graph has no
   missing nodes or cycles. Dispatch the live ready frontier, not a whole static
   layer; a blocked node stops only its descendants.
2. Start from a clean, green `main` baseline. Do not use parallel execution to
   hide an existing failing build, uncommitted work, or unresolved merge.
3. Review each `touches:` declaration as an ownership claim. It must name the
   files, directories, contracts, migrations, or capabilities the spec may
   change. Empty/coarse declarations use the configured conservative policy;
   they are not evidence of safety.
4. Pick a worker limit from CPU/RAM, model capacity, and isolated test resources
   such as ports, databases, emulators, and caches. Start conservatively and
   namespace or semaphore every shared resource.
5. Keep exactly one coordinator for a repository/run. Workers implement one
   spec in one worktree and report results; they never select another spec,
   advance another lifecycle state, or merge into `main`.

Recovery is deliberately narrow: inspect held, failed, or unmerged worktrees;
rebase/reconcile the affected branch; then rerun fresh-main validation. Do not
delete commits unreachable from main. A failed merge is held or reverted before
unrelated work stops, and only actual descendants inherit a block.

Do not use bounded parallel orchestration when dependencies are unclear; when a
shared schema or public-interface migration lacks a parent integration plan; when
the baseline is dirty or red; or when tests require constrained shared
infrastructure that cannot be isolated or capacity-limited. Run those cases
sequentially or create an explicit parent plan first.

### 1. Bootstrap
- Read `config.yaml`, verify clean git tree, run pre-flight (same as LOOP.md step 1).
  Prefer `python3 .nightshift/preflight.py --spec-id <SPEC_ID>` when present so the
  clean-tree/spec/dependency/baseline findings are captured in a durable artifact;
  fall back to LOOP.md Step 1 manual checks if the script is unavailable.
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
        changed_files = union(child.files_changed for child in completed_children)
        related_stacks = []

        if config.stacks exists:
            for each child in completed_children:
                child_root = config.stacks[child.stack].root
                for each file in child.files_changed:
                    if file is outside child_root:
                        for each stack_name, stack_profile in config.stacks:
                            if stack_name != child.stack and file matches stack_profile.root:
                                related_stacks.append(stack_name)
            related_stacks = unique(sorted(related_stacks))

        if commands.test is null or empty:
            Log WARNING "No project-wide test suite configured -- integration gate skipped"
            Record report entry: integration_gate: skipped
            Set main spec status: done (update file, commit)
            Log "Main spec <SPEC-ID> complete — child validations passed, integration gate skipped"
        else:
            Run project-wide commands.build on main (if configured)
            Run project-wide commands.test on main
            For each stack in related_stacks:
                Run config.stacks.<stack>.commands.test if configured

            if all integration commands pass:
                Record report entry: integration_gate: passed
                Set main spec status: done (update file, commit)
                Log "Main spec <SPEC-ID> complete — cross-stack integration gate passed"
            else:
                Write reports/_wip/integration-failure-<SPEC-ID>-<timestamp>.md
                Record report entry: integration_gate: failed
                Leave main spec as in_progress
                STOP for human review

    If any child fails:
        Log failure, leave main spec as in_progress
        Human must decide next step
```

Main specs are containers. They describe WHAT a feature achieves but are never executed as code tasks. Their children are the executable units.

**Failure report template (`reports/_wip/integration-failure-<SPEC-ID>-<timestamp>.md`):**

~~~markdown
# Integration Failure: <SPEC-ID>

- Main spec: <SPEC-ID>
- Generated: <ISO-8601 timestamp>
- Related stacks checked: <comma-separated stack list or "none">

## Children Merged

1. <CHILD-SPEC-ID> (stack: <stack>, branch: <branch>)
   - <changed file 1>
   - <changed file 2>
2. ...

## Validation Output

~~~text
<full build/test output from the failed integration gate>
~~~
~~~

**Related stack detection notes:**
- Child-local post-merge validation still uses the child spec's own stack profile when `stack:` is set.
- The Level 3 gate is **main-spec only**. Non-main specs do not run this branch.
- Root matching is path-prefix based:
  - `root: "."` matches all project files
  - `root: "api/"` matches `api/users.py` but not `shared/config.yaml`
- Files matching no stack root add **no** extra stack tests; only the project-wide suite runs.
- Backward compatibility: if `stacks:` is absent, or the project has no `type: main` specs, behavior stays at the pre-SPEC-026 flow.

#### 2.1c Task Selection Algorithm

- Read `specs/` and apply the Task Selection Algorithm (LOOP.md step 2)
- Build ordered list of ready specs to delegate
- **For each spec**, read the `stack:` field from its frontmatter (added by SPEC-023). This value is used in section 3 for brief construction and post-merge validation. Specs without `stack:` use top-level defaults throughout.
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

        Before a spec is treated as `ready` for dispatch, the acting agent MUST
        follow `SPEC-GUIDE.md`'s **NFR reconciliation transition gate**: bind or
        explicitly waive every mechanically matched active NFR, then run the
        static validator. This is agent-owned housekeeping, not human advice.

        Also prepend to sub-agent brief a required-read line:

        **Required read:** `.nightshift/VOCABULARY.md` — covers NFR lifecycle,
        blocker semantics, and how to record pending/failure state without
        modifying NFR status. Read before acting on the constraints above.
```

If no `nfr_map` exists (flat-spec project, no plan file), skip this step entirely. The brief is unchanged for backwards compatibility.

If the spec's `domain:` resolves to `research` or `analysis` (not `code`), also include `.nightshift/VOCABULARY.md` as a required read — non-code specs have different "done" criteria (output_artifact presence, source-count rules) that are summarized there.

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

#### a_stack. Stack Profile Resolution (NEW — Multi-Stack Routing)

Before writing the brief, resolve the spec's stack profile:

```
resolve_stack(spec, config):
    stack_name = spec.frontmatter.stack  # from SPEC-023
    if stack_name:
        if "stacks" in config and stack_name in config.stacks:
            return config.stacks[stack_name]
        else:
            log(WARNING, f"Unknown stack '{stack_name}' for {spec.id} -- falling back to default commands")
            return None  # use top-level defaults
    else:
        return None  # no stack tag → use top-level defaults (backward compatible)
```

If a stack profile is resolved, inject a `## Stack Profile` section into the brief (see template below). If no profile is resolved (no `stack:` tag, or unknown stack name), the brief is unchanged — identical to current behavior.

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
- Domain: {EFFECTIVE_DOMAIN} (resolved per-spec: spec.domain → stack_profile.domain → runner.domain → "code")
<!-- Domain is ALWAYS included in Context, even when no Stack Profile section follows -->

## Stack Profile
<!-- ONLY included when spec has stack: <name> AND config.stacks.<name> exists -->
<!-- If no stack: field → omit this entire section -->

**Stack:** {STACK_NAME} (from config.stacks.{STACK_NAME})
**Domain:** {EFFECTIVE_DOMAIN} (resolved per-spec: spec.domain → stack_profile.domain → runner.domain → "code")

Read LOOP-DOMAIN-MAP.md and apply the `{EFFECTIVE_DOMAIN}` column for steps 1, 4, 5, 7, 8, 9, 10.

**Commands:**
- test: `{stacks.<stack>.commands.test}` (or "not configured")
- build: `{stacks.<stack>.commands.build}` (or "not configured")
- lint: `{stacks.<stack>.commands.lint}` (or "not configured")
- type_check: `{stacks.<stack>.commands.type_check}` (or "not configured")
- format: `{stacks.<stack>.commands.format}` (or "not configured")

**DevKB files:**
- {stacks.<stack>.devkb[0]}
- {stacks.<stack>.devkb[1]}
- (or "none specified" if devkb is absent)

**Conventions:**
- {stacks.<stack>.conventions[0]}
- {stacks.<stack>.conventions[1]}
- (or "none specified" if conventions is absent)

**Environment:**
- Activation: `{stacks.<stack>.env.activate}` (or "none")
- Required binaries: {stacks.<stack>.env.required_binaries[]} (or "none specified")

<!-- End of Stack Profile section -->

## Instructions
1. Read .nightshift/BOOTSTRAP.md phases E1–E4 (knowledge & loop entry)
2. Generate the instruction packet before implementation:
   `python3 .nightshift/nightshift-instructions.py apply --spec {SPEC_ID} --json`
   Read every non-optional path in `contextFiles`; if `state` is `blocked`, fix or report the blocker before coding.
3. Your assigned spec is {SPEC_FILE} — execute this spec ONLY
3. Follow LOOP.md steps 1–15 for this spec only
4. Metrics: do NOT hand-author. The per-spec row is emitted automatically by the
   post-commit hook when the spec is marked done/blocked (SPEC-086/087). Optionally
   call `record_metrics.py` for a richer row — but it is NOT required.
5. Commit your work with conventional commit format

## Constraints
- Execute ONLY the assigned spec. Do NOT pick a different spec.
- Do NOT read or modify other specs in specs/
- Do NOT loop back to task selection (LOOP step 16) — return after one spec
- Write a success pattern to knowledge/patterns/ if your approach is reusable

## Runtime Fields
The hook derives `harness` / `loop_version` from `config.yaml` automatically. The one
field it cannot derive is the **model** — pass it as a `Nightshift-Model: {MODEL_NAME}`
trailer on the mark-done/blocked commit (see step 3 of "If build and test PASS"). That
is what enables model/harness/loop-version comparison in analyze_metrics.py. A missing
trailer degrades to `model: unknown` (the row still emits).
```

#### b. Launch Sub-Agent
- **Mark spec as `status: in_progress`** through the shared status checkpoint
  layer before launching. The board reads this durable layer first, so the state
  is visible across worktrees before merge. Until mark-commit metrics fully move
  off frontmatter, also keep the main-branch spec frontmatter in sync for the
  canonical lifecycle commit.
  Commit with the canonical format `chore: mark <spec-id> in_progress` (NOT `[<id>] chore: mark
  in_progress` — the metrics hook derives `started_at` from the matching in_progress commit by
  this exact subject; a non-standard subject loses the run span).
- Before the first concurrent launch, run the startup janitor from
  `worktree_janitor.py`. It reconciles stale linked worktrees, keeps any branch
  with unmerged commits as `unmerged — manual`, and only deletes resolved
  worktrees through the shared cleanup primitive. See `GIT.md` § Worktree
  Cleanup and Retention.
- Use Agent tool with isolation: "worktree"
- Pass the brief and all context
- Sub-agent runs in a clean git worktree with isolated context window
- See `GIT.md` § Spec Status Commits and § Branches and Worktrees.

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

Policy source: `GIT.md` § Merge and Post-Merge Validation. The steps below are
the orchestrator execution detail for that policy.

After merging a spec's worktree to main:

1. **Resolve commands** — use stack-specific commands when available:
   ```
   # Post-merge command resolution:
   if spec.frontmatter.stack and spec.frontmatter.stack in config.stacks:
       profile = config.stacks[spec.frontmatter.stack]
       test_cmd  = profile.commands.test  or config.commands.test
       build_cmd = profile.commands.build or config.commands.build
       lint_cmd  = profile.commands.lint  or config.commands.lint
   else:
       test_cmd  = config.commands.test
       build_cmd = config.commands.build
       lint_cmd  = config.commands.lint
   ```

2. Checkout main and run a clean build + test using the resolved commands:
   ```bash
   git checkout main
   <build_cmd>
   .nightshift/run_with_timeout.sh <commands.test_timeout_s> <test_cmd>
   ```

3. **If build and test PASS:**
   - Main is green.
   - Verify `.nightshift/reports/{SPEC_ID}/verification.json` exists and has no CRITICAL issues (SPEC-052). Warnings require rationale or follow-up.
   - **Verify spec status:** Check that the shared status checkpoint layer has
     `status: done` for the spec and, while legacy lifecycle artifacts still read
     frontmatter, that `specs/{SPEC_ID}.md` also has `status: done`.
     If the sub-agent forgot to mark it (common with worktree merges), update the
     durable state and frontmatter, then commit with the **canonical mark-commit format**
     `chore: mark <spec-id> done` (NOT `[<id>] chore: mark done` — the post-commit metrics
     hook keys on `^chore(\(scope\))?: mark <id> (done|blocked)`, so a non-standard subject
     means no metrics row). Add a `Nightshift-Model:` trailer so the row is model-attributed:
     ```
     chore: mark <spec-id> done

     Nightshift-Model: <orchestrator model id>
     Nightshift-Evidence-Report: pass
     Nightshift-Evidence-Tests: pass
     Nightshift-Evidence-Code: pass
     Nightshift-Evidence-ACs: pass
     Nightshift-Blocker-Class: none
     Nightshift-Blocker-Scope: none
     Nightshift-Unblock-Attempts: <0|1>
     Nightshift-Unblock-Limit: 1
     ```
     The hook then emits the per-spec metrics row automatically (SPEC-086/087) — do not
     hand-author metrics. Use source fingerprint metadata when available; stale
     source-of-truth writes must be reconciled rather than overwritten (SPEC-053).
     The matching in-progress commit is the stable resolution `run_id`. If a
     blocked transition is later marked done, the hook records a recovery attempt
     under that same run instead of presenting it as an unrelated success.
   - Proceed to next spec.

4. **If build or test FAIL:**
   a. This spec's merge broke main. Treat the failing build/test/lint output as
      raw critic input and send it back to the SAME worktree actor before any
      re-dispatch, revert, or failed mark:
      ```
      Your merge broke main. Here is the error output:
      [paste error output from build or test]

      Fix it on your branch, then signal ready for re-merge.
      ```
   b. Preserve the raw output verbatim in the reflection input. If the actor and
      critic are the same local model, present the actor's prior output under an
      inverted role so the model critiques it as another agent's work.
   c. Re-merge the corrected branch and re-validate.
   d. If the agent's fix works → proceed to next spec.
   e. Cap in-place reflection at about 3 cycles. If the cap is reached OR the
      agent can't fix it:
      - Revert the merge: `git revert --no-edit <merge_commit>`
      - Mark the spec as "failed" with `error_type: "post_merge_regression"`
      - Record the failure details (error output, files involved) in the next spec's brief as a KNOWN ISSUE
      - Proceed to next spec

5. Record post-merge validation result in the orchestrator report:
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
   - Exception: never mark NFR-family specs (`id: NFR-*` or `type: nfr`)
     blocked. Keep them `active`/`retired` and record pending or failed run state
     in the NFR body. Failed NFR verification blocks the triggering executable
     spec or creates/links a violation bug with `violates: [NFR-001]`.
   - **For each cascading block:** keep the real spec title as the first body H1
     and add `## Block Reason` as the first content section after that title.
     The Block Reason MUST specify:
     - Which dependency failed/is blocked (spec ID)
     - Which specific requirements/functionality of that spec this one needs
     - What would unblock the chain
     Example:
     ```markdown
     # SPEC-011 - Dependent Feature

     ## Block Reason

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

**Domain:** {EFFECTIVE_DOMAIN} (resolved per-spec: spec.domain → stack_profile.domain → runner.domain → "code")
<!-- Domain is ALWAYS included in Context, even when no Stack Profile section follows -->

## Stack Profile
<!-- Include this section ONLY if spec has stack: <name> AND config.stacks.<name> exists -->
<!-- Omit entirely for specs without a stack: field -->

**Stack:** {STACK_NAME} (from config.stacks.{STACK_NAME})
**Domain:** {EFFECTIVE_DOMAIN} (resolved per-spec: spec.domain → stack_profile.domain → runner.domain → "code")

Read LOOP-DOMAIN-MAP.md and apply the `{EFFECTIVE_DOMAIN}` column for steps 1, 4, 5, 7, 8, 9, 10.

**Commands:**
- test: `{stacks.<stack>.commands.test}` (or "not configured")
- build: `{stacks.<stack>.commands.build}` (or "not configured")
- lint: `{stacks.<stack>.commands.lint}` (or "not configured")
- type_check: `{stacks.<stack>.commands.type_check}` (or "not configured")
- format: `{stacks.<stack>.commands.format}` (or "not configured")

**DevKB files:**
- {stacks.<stack>.devkb[0]}
- {stacks.<stack>.devkb[1]}
- (or "none specified" if devkb is absent)

**Conventions:**
- {stacks.<stack>.conventions[0]}
- {stacks.<stack>.conventions[1]}
- (or "none specified" if conventions is absent)

**Environment:**
- Activation: `{stacks.<stack>.env.activate}` (or "none")
- Required binaries: {stacks.<stack>.env.required_binaries[]} (or "none specified")

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
   - Step 1: Pre-flight check (prefer `.nightshift/preflight.py --spec-id {SPEC_ID}` when present; fall back to manual checks)
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

When running under `## Kickoff Parent Context`, treat a blocked/stuck result as
an escalation to the parent kickoff agent, not as permission for the parent to
immediately mark main blocked. Include the exact blocker, what was tried, latest
evidence paths, and one focused unblock task. The parent kickoff agent owns the
unblock-before-block pass.

```python
if sub_agent_status == "completed":
    merge_worktree()
    cleanup_merged_worktree()  # shared primitive; see GIT.md merge-path cleanup
    continue_next_spec()

elif sub_agent_status in ["failed", "blocked", "discarded"]:
    if sub_agent_status in ["failed", "blocked"]:
        mark_spec_status(spec_id, "blocked")  # frontmatter lifecycle status; skip NFR-family specs
        # If spec_id starts with NFR- or type is nfr, keep status active/retired and
        # record the pending/failure state in the NFR body instead.
        record_error_type(spec_id, sub_agent_status)  # metrics/report outcome
    read_metrics_and_reports()
    write_failure_summary(reports/_wip/failures-{date}.md)

    # Check for cascading blocks
    dependent_specs = specs_with_after_dependency(current_spec_id)
    for spec in dependent_specs:
        mark_as_blocked(spec)  # no-op for NFR-family specs; record run state instead

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

## Stack-Aware Routing — Backward Compatibility (SPEC-024)

The stack-aware routing additions (stack profile resolution, `## Stack Profile` brief injection, and stack-specific post-merge validation) are fully backward compatible:

- **Specs without `stack:`** work exactly as before. No `## Stack Profile` section is injected, and all commands resolve to the top-level `commands:` block. There is zero behavioral change for existing specs.
- **Single-stack projects with no `stacks:` section in config.yaml** are unaffected. The orchestrator only looks up `config.stacks` when a spec has an explicit `stack:` field. If `config.stacks` is absent, the lookup is skipped entirely.
- **The `## Stack Profile` section is only injected** when both conditions are met: (1) the spec has `stack: <name>` in its frontmatter, AND (2) `config.stacks.<name>` exists in config.yaml. An unknown stack name produces a WARNING log and falls back to defaults — the spec is not blocked.
- **LOOP.md is unchanged.** Sub-agents receive resolved commands in their brief and follow LOOP.md as-is. Stack awareness lives entirely in the orchestrator's brief construction and post-merge validation.

---

## Consistency with LOOP.md

- **Task selection:** Orchestrator uses LOOP.md step 2 algorithm once at the top
- **Sub-agent execution:** Each sub-agent follows LOOP.md steps 1–15 exactly
- **Metrics format:** Same YAML schema as LOOP.md step 13, plus runtime fields
- **Reports:** Same structure and commit format as LOOP.md step 14
- **Knowledge:** Same `knowledge/` directory, same discovery logic (LOOP.md step 3)

The orchestrator is a thin wrapper around LOOP.md, not a replacement.
