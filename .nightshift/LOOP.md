# Autonomous Execution Loop

**Kit Version:** 2.1.0 | **Date:** 2026-03-30
**Purpose:** The heart of the Nightshift Kit. This document describes the full 16-step autonomous cycle that an agent follows to complete a single spec and move to the next one.

---

## Overview

The loop is designed to be followed by any agent that can:
- Read and write files
- Run shell commands
- Make decisions based on file content

The loop runs unsupervised overnight, producing code, tests, metrics, and reports. It is self-contained and technology-agnostic — it works for Swift, Python, TypeScript, Rust, or any other language. It also works for non-code domains: research (source gathering, synthesis, fact-checking), analysis (data processing, financial statements), and others.

**Key principle:** Static tools (linters, type checkers, formatters, build commands) are free. They provide feedback without burning LLM tokens. The loop maximizes their use — run them after every code change, not just at the end.

**Domain flexibility:** The 16-step structure applies to code, research, and analysis domains. When `config.yaml` → `runner.domain` is not `code`, read `LOOP-DOMAIN-MAP.md` for step-by-step domain mappings. The loop skeleton (spec → plan → execute → validate → knowledge) is universal; only the activities within each step change.

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
       "domain": config.runner.domain,
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

#### Step 1.x: Pre-Flight for Orchestrator with Main Specs (NEW — Hierarchical Specs)

If running in orchestrator mode (`config.yaml → runner.mode: "orchestrator"`) and a main spec is selected:

1. Check: does `execution-plan.json` exist in `specs/`?
2. If yes: verify `source_spec` matches the selected spec → proceed
3. If no: log instruction — `Run: nightshift-dag plan <SPEC-ID> --specs-dir specs/ first`
4. Continue with remaining pre-flight steps

This check ensures the DAG tool has validated dependencies before any model time is spent.

**What to do:**
1. Verify git working tree is clean (no uncommitted changes)
   - If dirty: stash or commit uncommitted work
2. Run the full test suite for the project (use `config.yaml` → `commands.test`)
   - **Apply the Test Timeout Protocol** (see section below Test Gate) to wrap the command if timeout is configured
   - This is a **GATE** — see "Test Gate" below
3. Run all static analysis tools (lint, type-check, format check)
   - These are **diagnostic only** — warn if failures are found, but do not stop
4. Log results: did tests pass? Any lint/type errors? Did any test hang occur?

**Why:** Establish a clean baseline. If tests are already failing, fix pre-existing failures before touching specs. An agent working from a broken state can't tell whether its changes broke something or whether it was already broken.

**Git:** No commits at this stage — just diagnostics.

**Checkpoint:** After pre-flight passes, save a checkpoint:
```
import checkpoint
checkpoint.save_checkpoint(
    spec_id=current_spec_id,
    step=1,
    step_name="preflight",
    data={
        "status": "completed",
        "git_branch": current_branch,
        "git_sha": current_commit_hash,
        "working_notes": "Preflight check passed. Test suite green.",
        "metrics_so_far": {"tests_total": N, "tests_passing": N},
        "knowledge_citations": []
    }
)
```

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
6. Commit: `chore(<spec-id>): mark in_progress`

**Task Selection Algorithm:**

```
0. Filter: type != "nfr" AND type != "main" (NFRs are standing constraints, main specs are containers — skip both)
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
- **Skip `type: nfr` specs.** (Existing rule — NFRs are constraints, not tasks.)

If a main spec is the target of the run (passed as argument), handle it via §2.1b in ORCHESTRATOR.md (fan out to children). The loop itself never picks up main specs.

**NFR specs** (`type: nfr`) are never selected by the loop. They define standing quality
constraints (e.g., "no SwiftUI faults during normal operation"). Bug specs reference
them via `violates: [NFR-001]` when a quality attribute is broken. NFRs use
`status: active` instead of the normal lifecycle (draft → ready → done).

**Key rule:** Bugfix specs always take priority over features, regardless of layer or priority number.

**Example:**
- SPEC-001 (Layer 0, feature, priority 3) — ready
- SPEC-005 (Layer 2, bugfix, priority 5) — ready
- SPEC-006 (Layer 1, feature, priority 1) — ready, but has after: [SPEC-007] and SPEC-007 is not done

Selection order: SPEC-005 (bugfix first) → SPEC-001 (Layer 0 before Layer 2) → SPEC-006 is skipped (blocked on SPEC-007)

---

### 3. Context Loading

**Pending Reflection Note (Orchestrator Mode):**
If running in orchestrator mode, you may have pending reflection output from a previous spec running asynchronously. Check for new patterns discovered before loading knowledge:
```bash
python3 check_reflection.py --spec <prev-spec> --output-dir .nightshift/reflections --since <timestamp>
```
If the reflection is done and new patterns exist, inject them into your context (step 3b will handle this). If the reflection is still running, proceed without — patterns will be available for subsequent specs.

**What to do:**
1. Read the selected spec completely
2. Examine every file mentioned in the spec's "Context" section
3. Read all relevant `knowledge/` files (agent decides which are relevant)
4. **Search for prior attempts:** Check if the spec has a `prior_attempts` field in its frontmatter — if so, read those files from `knowledge/attempts/`. Then also scan `knowledge/attempts/` for files whose `Problem area` matches the current spec's domain. Read any matches. This prevents repeating approaches that already failed.

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

---

### 4. Test Planning

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

**What to do:**
1. Following the test plan from step 4, write tests
2. Tests go alongside source code (follow project conventions)
3. Run tests immediately → expect them to fail (they test code that doesn't exist yet)
4. Verify tests fail for the right reasons:
   - Not because of import errors or typos
   - But because the feature/behavior isn't implemented
5. Commit: `test(<spec-id>): add tests (red)`
   - Include spec ID in parentheses
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
- Or wait until all tests pass, then commit: `feat(<spec-id>): implement SPEC-XXX`

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

If 3+ fix attempts fail on the same error → STOP. This is likely an architectural issue, not a bug. Log it and trigger the circuit breaker.

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

**Null Command Handling:** For each command below, if the command is null/missing, apply the Null Command Policy (see section above). Log which commands were skipped and why. Do NOT silently skip — every skipped validation must appear in the metrics log under `phases.validation.skipped: [...]`.

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

---

### 10. Post-Implementation Review (Second Review Round)

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

### 11. Capture Unrelated TODOs

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
4. Commit: `docs: log discovered TODOs for SPEC-XXX` (if any found)

**Why:** Capture learning without scope creep. Future rounds will prioritize these.

---

### 12. Commit & Changelog

**What to do:**
1. If not already committed during implementation, commit now:
   ```
   git commit -m "feat(<spec-id>): <short description>

   <body — what changed and why. Explain the approach chosen,
   alternatives considered, and any important implementation decisions.>

   Nightshift-Loop: 2026-03-16
   Spec: <spec-id>
   Phase: implementation"
   ```
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
   Commit: `chore(<spec-id>): mark done`

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

**Commit message format:**
- `<type>(<spec-id>): <subject>` — type: feat, fix, refactor, test, docs
- `<body>` — explain what changed and why (not just what)
- Trailers: `Nightshift-Loop:`, `Spec:`, `Phase:`

**Why:** Granular history makes it easy to review, revert, or trace decisions. Knowledge effectiveness tracking ensures patterns stay accurate and useful over time.

---

### 13. Metrics Logging

**CRITICAL: Schema Enforcement**

Your metrics YAML MUST follow the schema in `metrics/_SCHEMA.md` exactly. All fields marked "Required" in _SCHEMA.md are mandatory — no exceptions, no alternative formats.

**Required sections:**
- Root fields: `task_id`, `spec_file`, `started_at`, `completed_at`, `status`, `loop_version`, `model`, `harness`, `review_mode`
- Phases: `execution_mode`, `preflight`, `context_load`, `test_planning`, `test_writing`, `implementation`, `review`, `validation`, `completion_verification`
- Commit section: `hash`, `message`
- Knowledge section (when status=completed): `pattern_written`, `patterns_injected`, `patterns_cited`, `citation_rate`

**If you cannot fill a field** (e.g., no tests written), use the zero value (`0`, `false`, `[]`) — do NOT omit the field. Do NOT invent alternative formats (acceptance criteria checklists, freeform notes, etc.). The orchestrator will validate your metrics and flag non-compliance.

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
```

**For phase durations:**
- Record `date +%s` (epoch seconds) at the start and end of each major phase
- Compute `duration_s` as the difference: `END_EPOCH - START_EPOCH`
- If you cannot capture exact phase boundaries, capture at minimum:
  - `started_at` = `$LOOP_START` (beginning of Step 1)
  - `completed_at` = `$LOOP_END` (end of Step 13)
- Set individual phase `duration_s` to `0` rather than estimating

**Never fabricate timestamps or round durations.** A `duration_s: 0` is more honest than
a `duration_s: 900` that was never measured. Fabricated timestamps break cross-run analysis
and make the metrics system unreliable.

---

**What to do:**
1. Write a structured YAML entry to `metrics/YYYY-MM-DD_NNN_<spec-id>.yaml`
2. **IMPORTANT — Copy runtime fields from config.yaml before writing YAML:**
   - Read `config.yaml` → `runtime.loop_version` and set `loop_version:` in your metrics file
   - Read `config.yaml` → `runtime.model` (or use your own model name if you know it) and set `model:`
   - Read `config.yaml` → `runtime.harness` and set `harness:`
   - Read `config.yaml` → `review.mode` and set `review_mode:` in the metrics file
   - These fields enable model/harness/loop version comparison analysis
3. Include all fields:
   ```yaml
   task_id: "<spec-id>"
   spec_file: "specs/<filename>"
   started_at: "<ISO timestamp>"
   completed_at: "<ISO timestamp>"
   status: "completed"  # completed | failed | blocked | discarded | partial
   loop_version: "2026-03-17"  # From config.yaml → runtime.loop_version
   model: "claude-opus-4-6"     # From config.yaml → runtime.model
   harness: "claude-code"       # From config.yaml → runtime.harness
   review_mode: "self"          # From config.yaml → review.mode

   phases:
     preflight:
       clean_tree: true/false
       initial_tests_pass: true/false
       duration_s: 30

     context_load:
       files_read: <number>
       knowledge_entries_used: <number>
       duration_s: <seconds>

     test_planning:
       duration_s: <seconds>

     test_writing:
       tests_written: <number>
       tests_failing: <number>
       duration_s: <seconds>

     implementation:
       files_created: <number>
       files_modified: <number>
       lines_added: <number>
       lines_removed: <number>
       duration_s: <seconds>

     review:
       cycles: <number>
       issues_found:
         - persona: "<name>"
           severity: "blocking|warning|note"
           description: "<issue>"
           resolved: true/false

     validation:
       build_pass: true/false
       build_errors: <number>
       test_pass_rate: <0.0-1.0>
       tests_total: <number>
       tests_passed: <number>
       lint_errors: <number>
       type_errors: <number>
       duration_s: <seconds>

   satisfaction:
     overall_score: <0.0-1.0>
     classification: "high|medium|low"
     dimensions:
       tests: {score: <0.0-1.0>, weight: 3}
       lint: {score: <0.0-1.0>, weight: 1}
       type_check: {score: <0.0-1.0>, weight: 1}
       build: {score: <0.0-1.0>, weight: 2}
       completion_verification: {score: <0.0-1.0>, weight: 3}
       review: {score: <0.0-1.0>, weight: 2}

   commit:
     hash: "<git hash>"
     message: "<commit message>"

   # Only if status != completed
   failure:
     phase: "<which phase failed>"
     error_type: "<class of error>"
     description: "<what happened>"
     root_cause: "<what caused it>"
     suggestion: "<what should be tried next>"
   ```
3. Commit: `metrics: log SPEC-XXX completion`

4. **Propagate pattern effectiveness scores** (R1 from SPEC-P7-001):
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

**What to do:**
1. Generate a concise, human-readable summary of the work:
   ```markdown
   # Nightshift Report — [Date]

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

   ## Discovered TODOs
   - See TODOs-discovered.md for items found during implementation

   ## Changelog
   [Include changelog entries from step 12]
   ```
2. Write to `reports/YYYY-MM-DD-nightshift-report.md`
3. Commit: `docs: generate nightshift report`

**Why:** A human can scan the report in 2 minutes and know if anything needs attention.

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
   - Write final report
   - Commit all changes
   - Emit `loop_complete: true` signal
   - Exit cleanly

---

## Post-Run Metrics Emission

**MANDATORY:** This phase runs at the end of every execution, even partial runs, even runs that include blocked specs. Metrics are not optional — they are part of the protocol.

### What to Emit

At the conclusion of the loop (when no more specs are ready, or when the loop exits early), emit two aggregated metrics files:

#### 1. Per-Spec Metrics Summary: `metrics/{spec-id}.metrics.json`

**Note:** This file is generated from the per-spec YAML metrics files written in Step 13. The loop collects all completed spec metrics and consolidates them into a single JSON per spec.

**Schema:**
```json
{
  "spec_id": "SPEC-001",
  "status": "completed|failed|blocked|partial",
  "tier": 0,
  "review_cycles": 2,
  "tests_written": 12,
  "tests_passing": 12,
  "acceptance_criteria_total": 8,
  "acceptance_criteria_met": 8,
  "duration_minutes": 45,
  "files_changed": 3,
  "lines_added": 127,
  "lines_removed": 45,
  "harness": "claude-code",
  "model": "claude-opus-4-6",
  "kit_version": "2.1.0",
  "timestamp": "2026-03-27T14:32:00Z"
}
```

**Field definitions:**
- `spec_id` (string): The spec identifier (e.g., "SPEC-001")
- `status` (string): One of `completed`, `failed`, `blocked`, or `partial`
  - `completed`: All acceptance criteria met, all tests pass, no blocking issues
  - `failed`: Work attempted but did not meet acceptance criteria
  - `blocked`: Stall signal triggered, work abandoned, knowledge captured in `knowledge/attempts/`
  - `partial`: Loop exited before completion (manual stop, time limit, etc.)
- `tier` (int): The tier level of the spec (0-indexed, from spec frontmatter)
- `review_cycles` (int): Number of review-and-fix rounds completed
- `tests_written` (int): Total number of test cases written for this spec
- `tests_passing` (int): Number of tests currently passing
- `acceptance_criteria_total` (int): Total acceptance criteria in the spec
- `acceptance_criteria_met` (int): How many ACs are satisfied by the final code
- `duration_minutes` (int): Wall-clock time from Step 1 start to completion (estimate if precise timing unavailable)
- `files_changed` (int): Total count of files created or modified
- `lines_added` (int): Total lines added across all files
- `lines_removed` (int): Total lines removed across all files
- `harness` (string): The execution harness (e.g., "claude-code", "aider", "orchestrator")
- `model` (string): The LLM model used (e.g., "claude-opus-4-6", "gpt-4")
- `kit_version` (string): The Nightshift Kit version (from config.yaml → runtime.loop_version)
- `timestamp` (string): ISO 8601 timestamp when the spec run completed

**How to generate:**
1. For each completed spec, read its per-spec YAML metrics file from Step 13
2. Extract the fields listed above (mapping from YAML keys to JSON keys as needed)
3. Write one `{spec-id}.metrics.json` file per spec to `metrics/`
4. If a spec was blocked or failed, include it with `status: "blocked"` or `status: "failed"`

#### 2. Run Summary: `metrics/run-summary.metrics.json`

**Schema:**
```json
{
  "date": "2026-03-27",
  "specs_attempted": 5,
  "specs_completed": 3,
  "specs_failed": 1,
  "specs_blocked": 1,
  "total_duration_minutes": 180,
  "completion_rate": 0.6,
  "harness": "claude-code",
  "model": "claude-opus-4-6",
  "kit_version": "2.1.0",
  "project_name": "my-project",
  "timestamp": "2026-03-27T16:45:00Z"
}
```

**Field definitions:**
- `date` (string): Run date in YYYY-MM-DD format
- `specs_attempted` (int): Total specs selected for execution (ready + started)
- `specs_completed` (int): Specs with `status: completed`
- `specs_failed` (int): Specs with `status: failed`
- `specs_blocked` (int): Specs with `status: blocked`
- `total_duration_minutes` (int): Total wall-clock time from loop start to end
- `completion_rate` (float): `specs_completed / specs_attempted` (0.0–1.0)
- `harness` (string): The execution harness (e.g., "claude-code", "aider", "orchestrator")
- `model` (string): The LLM model used
- `kit_version` (string): The Nightshift Kit version
- `project_name` (string): Project name from config.yaml (if available) or directory name
- `timestamp` (string): ISO 8601 timestamp when the run ended

**How to generate:**
1. Read `config.yaml` to extract: `runtime.loop_version`, `runtime.model`, `runtime.harness`, `project.name`
2. Read all completed spec metrics from Step 13 (YAML files in `metrics/`)
3. Count:
   - `specs_completed` = count of specs with `status: completed`
   - `specs_failed` = count of specs with `status: failed`
   - `specs_blocked` = count of specs with `status: blocked`
   - `specs_attempted` = `specs_completed + specs_failed + specs_blocked + (partial specs if any)`
4. Sum individual spec `duration_s` from metrics to compute `total_duration_minutes`
5. Calculate `completion_rate = specs_completed / specs_attempted`
6. Use `date +%s` to get the final loop end timestamp
7. Write to `metrics/run-summary.metrics.json`

### When to Emit

**At loop termination:**
1. After Step 16 completes (normal exit because no more ready specs)
2. After a manual stop (STOP file detected in Step 16)
3. After a stall detection triggers (Stall Detection & Circuit Breaker triggers circuit breaker)
4. If a fatal error forces loop exit (e.g., Git error, file system error)

In all cases, emit both files **even if the run is partial or contains blocked specs**.

### Commit

After emitting both JSON files:
```bash
git add metrics/{spec-id}.metrics.json metrics/run-summary.metrics.json
git commit -m "metrics: emit post-run aggregates for $(date +%Y-%m-%d)"
```

### Purpose

Post-run metrics serve three functions:

1. **Aggregation for human review:** The JSON format is machine-readable and easily parsed into dashboards, spreadsheets, or reports
2. **Cross-run analysis:** Run summaries stack to show trends (completion rate over time, model performance, harness comparison)
3. **Protocol enforcement:** Metrics are part of the loop contract — every run must produce them. Absence of metrics files is a sign that the loop exited abnormally

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
   **Add a `# Block Reason` section** as the FIRST section after frontmatter:
   ```markdown
   # Block Reason

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
