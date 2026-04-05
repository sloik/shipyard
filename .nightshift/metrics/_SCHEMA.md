# Nightshift Metrics YAML Schema

**Version:** 1.0
**Status:** Active
**Last Updated:** 2026-03-29

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
```

### `phases.execution_mode` (string, required)

Mode of execution for this spec.

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

### `failure.root_cause` (string, required)

Analysis of the root cause.

**Type:** `string`
**Constraints:** Non-empty

### `failure.suggestion` (string, required)

Recommended next step or fix.

**Type:** `string`
**Constraints:** Non-empty

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
