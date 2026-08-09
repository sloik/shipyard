# Nightshift Metrics YAML Schema

**Version:** 1.1
**Status:** Active
**Last Updated:** 2026-07-25

This document defines the complete schema for per-spec YAML metrics files produced by the Nightshift loop (Step 13 of LOOP.md).

---

## Overview

Each completed spec produces one metrics YAML file with the following structure:

```
metrics/
├── YYYY-MM-DD_NNN_<spec-id>.yaml
└── ...
```

The metrics file captures:
- Task identification and timeline
- Execution phases and their outcomes
- Satisfaction scores across multiple dimensions
- Commit information
- Knowledge/learning outcomes (if completed)
- Failure details (if not completed)
- Parent-authoritative kickoff resolution and recovery history (when emitted by
  a mark-commit hook)

### Unblock attempt additions (SPEC-185)

`resolution` may additionally contain `attempt_result` (`succeeded`, `failed`,
or `skipped`), `attempt_evidence_verified` (boolean), `causal_confidence`
(`demonstrated`, `supported`, `hypothesis`, or `not_established`),
`attempt_duration_s`, and the relative `attempt_artifact`. These fields are
all-or-nothing when present and are derived from the immutable attempt artifact;
older trailer-only resolution rows remain valid. Analytics report `N/A` for a
rate whose denominator has no samples rather than treating absence as zero.

### Private recovery projection additions (SPEC-188)

`resolution.recovery` is optional and contains only booleans for eligible,
failed, succeeded, fresh-worker-rescued, and overturned-premature-block states.
The private manifest carries hashes plus approved relative evidence references,
project/origin/worktree fingerprints, and kit/schema versions. Sink state may
be `awaiting_sync`; it never changes the evidence gate or lifecycle outcome.

---

## Root Fields (Required)

All fields at the root level are mandatory.

### `task_id` (string, required)

The spec ID being executed.

**Type:** `string`
**Example:** `"SPEC-001"`
**Constraints:** Non-empty

### `spec_file` (string, required)

Path to the spec file relative to project root.

**Type:** `string`
**Example:** `"specs/SPEC-001.md"`
**Constraints:** Non-empty

### `started_at` (string, required)

ISO 8601 timestamp when the loop iteration began.

**Type:** `string` (ISO 8601 format)
**Example:** `"2026-03-29T10:15:30Z"`
**Constraints:**
- Must be valid ISO 8601 timestamp
- Must include timezone (Z or ±HH:MM)
- Captured from `date -u +%Y-%m-%dT%H:%M:%SZ` at loop start

### `completed_at` (string, required)

ISO 8601 timestamp when the loop iteration ended.

**Type:** `string` (ISO 8601 format)
**Example:** `"2026-03-29T11:45:20Z"`
**Constraints:**
- Must be valid ISO 8601 timestamp
- Must include timezone (Z or ±HH:MM)
- Must be >= `started_at`
- Captured from `date -u +%Y-%m-%dT%H:%M:%SZ` at loop end

### `status` (string, required)

Overall completion status of the spec.

**Type:** `string` (enum)
**Valid values:** `"completed"` | `"failed"` | `"blocked"` | `"discarded"` | `"partial"`
**Example:** `"completed"`
**Constraints:**
- If `"completed"`: `knowledge` section is required
- If not `"completed"`: `failure` section is required

### `loop_version` (string, required)

Version identifier for this loop run.

**Type:** `string`
**Example:** `"2026-03-17"`
**Constraints:**
- Copied from `config.yaml` → `runtime.loop_version`
- Enables cross-run version tracking

### `model` (string, required)

Name of the LLM model used.

**Type:** `string`
**Example:** `"claude-opus-4-6"`
**Constraints:**
- Copied from `config.yaml` → `runtime.model`
- Enables model comparison analysis

### `harness` (string, required)

Name of the execution harness/platform.

**Type:** `string`
**Example:** `"claude-code"`
**Constraints:**
- Copied from `config.yaml` → `runtime.harness`
- Enables harness comparison analysis

### `review_mode` (string, required)

Review mode setting for this run.

**Type:** `string`
**Example:** `"self"`
**Constraints:**
- Copied from `config.yaml` → `review.mode`
- Indicates whether review was autonomous, manual, or hybrid

---

## Phases Section (Required)

Contains execution data for each major phase of the spec loop.

### Structure

```yaml
phases:
  execution_mode: <string>
  preflight: <object>
  context_load: <object>
  test_planning: <object>
  test_writing: <object>
  implementation: <object>
  review: <object>
  validation: <object>
  completion_verification: <object>
  synthesis_gate: <object, optional>
```

### `phases.execution_mode` (string, required)

Mode of execution for this spec.

### Duration measurement (SPEC-196)

Every phase object carrying `duration_s` may carry `measurement_state`:
`measured`, `skipped`, `interrupted`, or `unavailable`. `measured` is produced
only by paired coordinator `phase_started` / `phase_finished` events for the
same `run_id` and spec. `skipped`, `interrupted`, and `unavailable` have no
invented duration (`duration_s: 0`). Legacy rows without a state remain valid,
but analytics treats their zero durations as unavailable rather than fast work.

`run_id`, `spec_duration_s`, and `spec_duration_state` are optional additive
fields. They link emitted measurements to the append-only event stream and
provide a non-double-counted total across retried phase intervals.

**Type:** `string`
**Example:** `"eval"`
**Constraints:** Non-empty

---

### `phases.preflight` (object, required)

Pre-execution validation phase.

**Fields:**

#### `clean_tree` (boolean, required)

Whether the repository tree was clean before starting.

**Type:** `boolean`

#### `initial_tests_pass` (boolean, required)

Whether initial tests passed before starting.

**Type:** `boolean`

#### `duration_s` (number, required)

Duration of preflight phase in seconds.

**Type:** `number` (integer or float)
**Constraints:** >= 0

---

### `phases.context_load` (object, required)

Context loading phase (reading spec, DevKB, existing code, etc.).

**Fields:**

#### `files_read` (integer, required)

Number of files read during context load.

**Type:** `integer`
**Constraints:** >= 0

#### `knowledge_entries_used` (integer, required)

Number of knowledge/DevKB entries consulted.

**Type:** `integer`
**Constraints:** >= 0

#### `duration_s` (number, required)

Duration of context loading in seconds.

**Type:** `number` (integer or float)
**Constraints:** >= 0

---

### `phases.test_planning` (object, required)

Test planning phase.

**Fields:**

#### `duration_s` (number, required)

Duration of test planning in seconds.

**Type:** `number` (integer or float)
**Constraints:** >= 0

---

### `phases.test_writing` (object, required)

Test implementation phase (TDD).

**Fields:**

#### `tests_written` (integer, required)

Number of tests written.

**Type:** `integer`
**Constraints:** >= 0

#### `tests_failing` (integer, required)

Number of tests initially failing (before implementation).

**Type:** `integer`
**Constraints:** >= 0

#### `duration_s` (number, required)

Duration of test writing in seconds.

**Type:** `number` (integer or float)
**Constraints:** >= 0

---

### `phases.implementation` (object, required)

Implementation phase (writing code to pass tests).

**Fields:**

#### `files_created` (integer, required)

Number of new files created.

**Type:** `integer`
**Constraints:** >= 0

#### `files_modified` (integer, required)

Number of existing files modified.

**Type:** `integer`
**Constraints:** >= 0

#### `lines_added` (integer, required)

Total lines of code added (net).

**Type:** `integer`
**Constraints:** >= 0

#### `lines_removed` (integer, required)

Total lines of code removed (net).

**Type:** `integer`
**Constraints:** >= 0

#### `duration_s` (number, required)

Duration of implementation in seconds.

**Type:** `number` (integer or float)
**Constraints:** >= 0

---

### `phases.review` (object, required)

Code review and feedback cycles phase.

**Fields:**

#### `cycles` (integer, required)

Number of review/feedback cycles completed.

**Type:** `integer`
**Constraints:** >= 0

#### `issues_found` (array, required)

List of issues discovered during review.

**Type:** `array of objects`

**Issue Object Fields:**

- `persona` (string, required): Reviewer persona (e.g., "security", "performance")
- `severity` (string, required): Severity level: `"blocking"` | `"warning"` | `"note"`
- `description` (string, required): Description of the issue
- `resolved` (boolean, required): Whether the issue was resolved

---

### `phases.validation` (object, required)

Validation and testing phase (build, tests, lint, type checking).

**Fields:**

#### `build_pass` (boolean, required)

Whether the build succeeded.

**Type:** `boolean`

#### `build_errors` (integer, required)

Number of build errors.

**Type:** `integer`
**Constraints:** >= 0

#### `test_pass_rate` (number, required)

Fraction of tests passed (0.0 to 1.0).

**Type:** `number` (float)
**Constraints:** [0.0, 1.0]

#### `tests_total` (integer, required)

Total number of tests executed.

**Type:** `integer`
**Constraints:** >= 0

#### `tests_passed` (integer, required)

Number of tests that passed.

**Type:** `integer`
**Constraints:** >= 0

#### `lint_errors` (integer, required)

Number of linting errors detected.

**Type:** `integer`
**Constraints:** >= 0

#### `type_errors` (integer, required)

Number of type checking errors.

**Type:** `integer`
**Constraints:** >= 0

#### `duration_s` (number, required)

Duration of validation phase in seconds.

**Type:** `number` (integer or float)
**Constraints:** >= 0

---

### `phases.completion_verification` (object, required)

Final verification that the spec was fully completed.

**Fields:**

#### `acceptance_criteria_met` (boolean, required)

Whether all acceptance criteria from the spec were met.

**Type:** `boolean`

#### `no_regression` (boolean, required)

Whether no regressions were introduced.

**Type:** `boolean`

---

### `phases.synthesis_gate` (object, optional)

Present only when Step 9.7 triggered for a `research` or `analysis` spec with
at least one direct code dependent.

**Fields:**

#### `triggered` (boolean, required when section present)

Always `true` when this section exists.

#### `dependent_specs` (array[string], required when section present)

Direct downstream code specs validated against the current output.

#### `interface_validation` (string, required when section present)

Result of the downstream interface check.

**Valid values:** `"passed"` | `"failed"`

#### `handoff_artifact_path` (string, required when section present)

Relative path to `knowledge/handoffs/<spec-id>.json`.

#### `knowledge_pattern_path` (string, required when section present)

Relative path to `knowledge/patterns/<spec-id>-findings.md`.

#### `duration_s` (number, required when section present)

Wall-clock duration of the synthesis gate in seconds.

---

## Satisfaction Section (Required)

Quality and satisfaction metrics across multiple dimensions.

### Structure

```yaml
satisfaction:
  overall_score: <number 0.0-1.0>
  classification: <string: high|medium|low>
  dimensions:
    tests: {score: <number>, weight: <number>}
    lint: {score: <number>, weight: <number>}
    type_check: {score: <number>, weight: <number>}
    build: {score: <number>, weight: <number>}
    completion_verification: {score: <number>, weight: <number>}
    review: {score: <number>, weight: <number>}
```

### `satisfaction.overall_score` (number, required)

Weighted overall quality score.

**Type:** `number` (float)
**Constraints:** [0.0, 1.0]
**Calculation:** Weighted average of all dimension scores

### `satisfaction.classification` (string, required)

Quality classification based on overall score.

**Type:** `string` (enum)
**Valid values:** `"high"` | `"medium"` | `"low"`
**Mapping:** Typically:
- `"high"`: overall_score >= 0.85
- `"medium"`: 0.6 <= overall_score < 0.85
- `"low"`: overall_score < 0.6

### `satisfaction.dimensions` (object, required)

Quality scores across 6 dimensions.

#### Required Dimensions

Each dimension is an object with `score` and `weight`:

**`tests`** — Test coverage and quality
- `score` (number [0.0, 1.0]): Test quality score
- `weight` (number >= 0): Importance weight (default: 3)

**`lint`** — Code style and linting
- `score` (number [0.0, 1.0]): Lint cleanliness score
- `weight` (number >= 0): Importance weight (default: 1)

**`type_check`** — Type safety (if applicable)
- `score` (number [0.0, 1.0]): Type checking score
- `weight` (number >= 0): Importance weight (default: 1)

**`build`** — Build success and reliability
- `score` (number [0.0, 1.0]): Build quality score
- `weight` (number >= 0): Importance weight (default: 2)

**`completion_verification`** — Acceptance criteria met
- `score` (number [0.0, 1.0]): Completion score
- `weight` (number >= 0): Importance weight (default: 3)

**`review`** — Code review findings
- `score` (number [0.0, 1.0]): Review quality score
- `weight` (number >= 0): Importance weight (default: 2)

---

## Commit Section (Required)

Git commit information for the completed work.

### Structure

```yaml
commit:
  hash: <string>
  message: <string>
```

### `commit.hash` (string, required)

Git commit hash (full or short form).

**Type:** `string`
**Example:** `"abc123def456789"`
**Constraints:** Non-empty

### `commit.message` (string, required)

Commit message.

**Type:** `string`
**Example:** `"feat: implement SPEC-001 metrics validator"`
**Constraints:** Non-empty

---

## Knowledge Section (Required if `status == "completed"`)

Learning outcomes and pattern tracking.

**Required when:** `status == "completed"`
**Optional when:** `status` is one of `"failed"`, `"blocked"`, `"discarded"`, `"partial"`

### Structure

```yaml
knowledge:
  pattern_written: <integer>
  patterns_injected: <integer>
  patterns_cited: <integer>
  citation_rate: <number 0.0-1.0>
```

### `knowledge.pattern_written` (integer, required)

Number of patterns written to knowledge base.

**Type:** `integer`
**Constraints:** >= 0

### `knowledge.patterns_injected` (integer, required)

Number of patterns injected (made relevant) during implementation.

**Type:** `integer`
**Constraints:** >= 0

### `knowledge.patterns_cited` (integer, required)

Number of patterns cited in the implementation or documentation.

**Type:** `integer`
**Constraints:** >= 0

### `knowledge.citation_rate` (number, required)

Fraction of available patterns that were cited (0.0 to 1.0).

**Type:** `number` (float)
**Constraints:** [0.0, 1.0]

---

## Failure Section (Required if `status != "completed"`)

Failure details and analysis.

**Required when:** `status` is one of `"failed"`, `"blocked"`, `"discarded"`, `"partial"`
**Optional when:** `status == "completed"`

### Structure

```yaml
failure:
  phase: <string>
  error_type: <string>
  description: <string>
  root_cause: <string>
  suggestion: <string>
```

### `failure.phase` (string, required)

Which phase failed.

**Type:** `string`
**Example:** `"validation"`
**Constraints:** Non-empty

### `failure.error_type` (string, required)

Category of error.

**Type:** `string`
**Example:** `"test_failure"` | `"build_error"` | `"type_error"`
**Constraints:** Non-empty

### `failure.description` (string, required)

Description of what failed.

**Type:** `string`
**Constraints:** Non-empty

### `failure.root_cause` (string, optional)

Analysis of the root cause. Optional as of SPEC-045 — when absent, the
knowledge extractor (`knowledge_writer.synthesize`) derives a fallback
summary from `error_type`. Handlers SHOULD populate this when they have
a specific diagnosis.

**Type:** `string`
**Constraints:** Non-empty when present
**Example:** `"Mocked dependency returned wrong type"`

### `failure.suggestion` (string, optional)

Recommended next step or fix. Optional as of SPEC-045 — when absent,
the extractor derives a fallback hint from `error_type`. Handlers
SHOULD populate this when they have concrete remediation advice.

**Type:** `string`
**Constraints:** Non-empty when present
**Example:** `"Re-read spec requirements, review failing tests, align contracts."`

---

## Resolution Section (Optional, strict when present)

The `resolution` section records the parent kickoff flow's authoritative
evidence decision. It is emitted mechanically by `record_metrics.py
--mark-commit`; worker-authored metrics do not decide whether a kickoff merged
or blocked.

```yaml
resolution:
  run_id: "<in-progress commit SHA>"
  stage: kickoff_gate
  attempt: 1
  prior_outcome: none
  final_outcome: blocked
  evidence_gate:
    report_exists: pass
    tests_passed: fail
    code_changed: pass
    acs_covered: fail
  blocker_class: fixture_drift
  blocker_scope: out_of_scope
  unblock_attempts: 1
  unblock_limit: 1
  automatic_unblock_succeeded: false
  later_session_required: false
  resolution_latency_s: 840
```

Constraints:

- `run_id` is the matching canonical `chore: mark <spec-id> in_progress`
  commit SHA. All later blocked/done transitions for that run share it.
- `stage`: `kickoff_gate | recovery`.
- `attempt`: integer >= 1; transitions are ordered within a run.
- `prior_outcome`: `none | done | blocked`.
- `final_outcome`: `done | blocked | waiting_external_input`. The wait value is
  non-terminal and requires the additive `ordinary_wait` record below.
- Every `evidence_gate` value is `pass | fail | unknown`.
- `blocker_class`:
  `none | implementation | test_infrastructure | fixture_drift |
  baseline_regression | external_input | evidence_gap | unknown`.
- `blocker_scope`: `none | in_scope | out_of_scope | mixed | unknown`.
- `unblock_attempts` and `unblock_limit` are non-negative integers, with
  attempts <= limit.
- `automatic_unblock_succeeded` and `later_session_required` are booleans.
- `resolution_latency_s` is a non-negative number derived from commit times.

For an expected missing API/browser/test capability, `ordinary_wait` records a
privacy-safe capability class rather than raw logs, paths, hosts, or tokens:

```yaml
ordinary_wait:
  category: test_runtime # test_runtime | api_runtime
  missing_capability: browser_runtime # browser_runtime | api_runtime | test_runtime
  resolution_state: awaiting_capability # awaiting_capability | resolved
  next_action: provide browser_runtime and rerun the evidence gate
```

An ordinary wait has `final_outcome: waiting_external_input`,
`blocker_class: none`, and `unblock_attempts: 0`; it does not use the critical
unblock-controller budget. Historical rows without `ordinary_wait` remain valid.

`analyze_metrics.py` groups these rows by `run_id` and reports evidence-gate
failure rate, automatic-unblock success rate, deferred-recovery rate, blocker
class counts, ordinary-wait counts/category/state, and median final resolution
latency. With no linked runs, ordinary-wait rate is `N/A`; with linked runs and
no ordinary waits, it is explicitly `0`.

---

## Validation Rules

- **All fields marked "required"** must be present (no omissions)
- **Timestamps** must be valid ISO 8601 format with timezone
- **Numeric ranges**: Scores [0.0, 1.0], counts >= 0, durations >= 0
- **Time ordering**: `completed_at >= started_at`
- **Status-dependent fields**:
  - If `status == "completed"`: `knowledge` section required, `failure` section optional
  - If `status != "completed"`: `failure` section required, `knowledge` section optional
- **Zero values** are valid: Use `0`, `0.0`, or `false` rather than omitting fields

---

## Example: Valid Completed Spec

```yaml
task_id: "SPEC-001"
spec_file: "specs/SPEC-001.md"
started_at: "2026-03-29T10:15:30Z"
completed_at: "2026-03-29T11:45:20Z"
status: "completed"
loop_version: "2026-03-17"
model: "claude-opus-4-6"
harness: "claude-code"
review_mode: "self"

phases:
  execution_mode: "eval"
  preflight:
    clean_tree: true
    initial_tests_pass: true
    duration_s: 30
  context_load:
    files_read: 12
    knowledge_entries_used: 3
    duration_s: 180
  test_planning:
    duration_s: 120
  test_writing:
    tests_written: 8
    tests_failing: 8
    duration_s: 600
  implementation:
    files_created: 2
    files_modified: 5
    lines_added: 450
    lines_removed: 25
    duration_s: 1200
  review:
    cycles: 2
    issues_found:
      - persona: "security"
        severity: "warning"
        description: "Input validation missing on line 45"
        resolved: true
      - persona: "performance"
        severity: "note"
        description: "Consider caching repeated queries"
        resolved: false
  validation:
    build_pass: true
    build_errors: 0
    test_pass_rate: 1.0
    tests_total: 8
    tests_passed: 8
    lint_errors: 0
    type_errors: 0
    duration_s: 90
  completion_verification:
    acceptance_criteria_met: true
    no_regression: true
  synthesis_gate:
    triggered: true
    dependent_specs: ["SPEC-002"]
    interface_validation: "passed"
    handoff_artifact_path: "knowledge/handoffs/SPEC-001.json"
    knowledge_pattern_path: "knowledge/patterns/SPEC-001-findings.md"
    duration_s: 12

satisfaction:
  overall_score: 0.92
  classification: "high"
  dimensions:
    tests:
      score: 1.0
      weight: 3
    lint:
      score: 1.0
      weight: 1
    type_check:
      score: 0.9
      weight: 1
    build:
      score: 1.0
      weight: 2
    completion_verification:
      score: 1.0
      weight: 3
    review:
      score: 0.8
      weight: 2

commit:
  hash: "a1b2c3d4e5f6"
  message: "feat: implement SPEC-001 metrics validator"

knowledge:
  pattern_written: 1
  patterns_injected: 2
  patterns_cited: 1
  citation_rate: 0.5
```

---

## Example: Valid Failed Spec

```yaml
task_id: "SPEC-005"
spec_file: "specs/SPEC-005.md"
started_at: "2026-03-29T12:00:00Z"
completed_at: "2026-03-29T13:30:00Z"
status: "failed"
loop_version: "2026-03-17"
model: "claude-opus-4-6"
harness: "claude-code"
review_mode: "self"

phases:
  execution_mode: "eval"
  preflight:
    clean_tree: true
    initial_tests_pass: true
    duration_s: 20
  context_load:
    files_read: 8
    knowledge_entries_used: 1
    duration_s: 120
  test_planning:
    duration_s: 90
  test_writing:
    tests_written: 5
    tests_failing: 5
    duration_s: 300
  implementation:
    files_created: 1
    files_modified: 2
    lines_added: 200
    lines_removed: 0
    duration_s: 1800
  review:
    cycles: 0
    issues_found: []
  validation:
    build_pass: false
    build_errors: 3
    test_pass_rate: 0.2
    tests_total: 5
    tests_passed: 1
    lint_errors: 5
    type_errors: 2
    duration_s: 120
  completion_verification:
    acceptance_criteria_met: false
    no_regression: false

satisfaction:
  overall_score: 0.25
  classification: "low"
  dimensions:
    tests:
      score: 0.2
      weight: 3
    lint:
      score: 0.3
      weight: 1
    type_check:
      score: 0.2
      weight: 1
    build:
      score: 0.0
      weight: 2
    completion_verification:
      score: 0.2
      weight: 3
    review:
      score: 0.0
      weight: 2

commit:
  hash: "x1y2z3a4b5c6"
  message: "wip: SPEC-005 incomplete implementation"

failure:
  phase: "validation"
  error_type: "test_failure"
  description: "4 of 5 tests failed during validation. Build compilation errors in implementation."
  root_cause: "Implementation did not fully address the spec requirements. API contract mismatch in data structures."
  suggestion: "Re-read spec requirements, review failing test cases, clarify data structure contracts, implement missing fields."
```

---

## See Also

- **LOOP.md Step 13**: Metrics logging procedure
- **validate_metrics.py**: Automated schema validator
- **ORCHESTRATOR.md Step 3d**: How metrics are validated in the orchestration loop
