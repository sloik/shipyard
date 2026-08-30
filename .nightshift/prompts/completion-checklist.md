# Completion Verification Checklist Template

**Used by:** `LOOP.md` Step 9.5 (Completion Verification — Premature Victory Guard). Unlike
`spec-reviewer.md` and `quality-reviewer.md`, this file is a **template the loop agent fills
in itself**, not a prompt dispatched to a subagent. It carries no `{PLACEHOLDER}` tokens: the
agent copies the JSON structure below and populates it from the spec under work. It applies in
every `review.mode`, including `self`.

**Purpose:** Guard against premature victory — ensure all Acceptance Criteria are verified before declaring a spec complete.

**Anti-Rationalization Principle:**
- Do NOT skip this step even if all tests pass. Tests may not cover all Acceptance Criteria.
- Evidence must be fresh — from THIS step, not from earlier runs.
- Confidence is not evidence. Verification is evidence.

---

## Instructions for the Agent

### Step 1: Extract Acceptance Criteria from Spec
Read the spec file completely. Identify the "Acceptance Criteria" or "Requirements" section. Each criterion becomes one checklist item.

**Example:** If the spec says:
```
Acceptance Criteria:
- AC-1: Search returns results for valid queries
- AC-2: Empty query returns empty results gracefully
- AC-3: Search is case-insensitive
```

Then you will create three checklist items.

---

### Step 2: Build the Checklist Structure
Create a JSON object with this structure:

```json
{
  "spec_id": "SPEC-XXX",
  "timestamp": "ISO-8601 timestamp (when this checklist was created)",
  "checklist": [
    {
      "ac_id": "AC-1",
      "description": "Exact text from spec's Acceptance Criteria",
      "passes": false,
      "evidence": "",
      "verified_by": "test | manual | lint | build | scenario"
    }
  ],
  "all_pass": false,
  "concerns": []
}
```

**Field definitions:**
- `ac_id`: Identifier for this criterion (AC-1, AC-2, etc.)
- `description`: The exact requirement from the spec
- `passes`: Boolean. `false` initially, only set to `true` after verification
- `evidence`: Reference to the verification (test name, build output section, command run, file reference)
- `verified_by`: One of: `test` (unit/integration test), `manual` (code trace/inspection), `lint` (static analysis), `build` (compiler/build output), `scenario` (scenario validation)
- `all_pass`: Set to `true` only when ALL items have `passes: true`
- `concerns`: List of strings. If any AC cannot be verified, log it here before setting status to DONE_WITH_CONCERNS

---

### Step 3: Verify Each Acceptance Criterion

For each AC item in the checklist:

1. **Identify the verification method:**
   - Does an existing test cover this? → `verified_by: test`
   - Can you trace through code manually? → `verified_by: manual`
   - Is this a code quality/style requirement? → `verified_by: lint`
   - Does the build output confirm this? → `verified_by: build`
   - Does a scenario exercise this? → `verified_by: scenario`

2. **Run or reference the verification:**
   - If test: run the test suite, record which test(s) cover this AC
   - If manual: read the relevant code section, trace through logic
   - If lint: run linter, check for violations related to this AC
   - If build: examine build output or compilation result
   - If scenario: execute the scenario steps, verify expected outcome

3. **Record evidence:**
   - Test: test name and pass status (e.g., `test_search_valid_queries() — PASSED`)
   - Manual: file path and brief description (e.g., `SearchService.search() lines 42-58 — implements case-insensitive comparison`)
   - Lint: linter output (e.g., `eslint: 0 errors`)
   - Build: compiler output section (e.g., `Build completed successfully`)
   - Scenario: scenario name and result (e.g., `scenario/basic-search.md — completed as expected`)

4. **Set passes to true only when:**
   - You have fresh evidence (from THIS step, not from earlier)
   - The evidence clearly demonstrates the AC is met
   - There is no ambiguity

---

### Step 4: Handle Failures

**If all ACs pass:**
- Set `all_pass: true`
- Set `status: READY_FOR_NEXT_PHASE` in your notes
- Continue the loop at step 9.6 (Output Artifact Verification), then 9.7 if it applies, then step 10

**If any AC fails or cannot be verified:**

**If fixable (e.g., test fails, code logic is wrong):**
- Go back to step 8 of LOOP.md (implementation)
- Fix the issue
- Re-run validation (step 9)
- Re-check this checklist
- Return to step 3 above and re-verify

**If not fixable (e.g., ambiguous spec, missing infrastructure, environment issue):**
- Add a concern entry: `"AC-X: [description of why it can't be verified]"`
- Document what's blocking it
- Set `all_pass: false` and `status: DONE_WITH_CONCERNS`
- Continue the loop, but flag this in your metrics and report
- Note: DONE_WITH_CONCERNS means you finished the work but are uncertain about completeness. The morning reviewer gets a targeted place to investigate.

---

### Step 5: Save the Checklist

Save the completed checklist to: `reports/_wip/checklist-<spec-id>.json` (this directory is gitignored).

**Example filename:** `reports/_wip/checklist-SPEC-001.json`

Then, extract key metrics to log in the main metrics YAML:
- `checklist_items`: total number of ACs
- `items_passing`: count of items with `passes: true`
- `items_failing`: count of items with `passes: false`
- `all_pass`: boolean
- `concerns`: list of concern strings (if any)
- `duration_s`: seconds spent in this step

---

## JSON Schema Reference

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["spec_id", "timestamp", "checklist", "all_pass", "concerns"],
  "properties": {
    "spec_id": {
      "type": "string",
      "description": "Spec identifier (e.g., SPEC-001)"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp when checklist was created"
    },
    "checklist": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["ac_id", "description", "passes", "evidence", "verified_by"],
        "properties": {
          "ac_id": {
            "type": "string",
            "description": "Acceptance Criterion ID (AC-1, AC-2, etc.)"
          },
          "description": {
            "type": "string",
            "description": "Full text of the AC from the spec"
          },
          "passes": {
            "type": "boolean",
            "description": "Does this AC pass? Only true if verified."
          },
          "evidence": {
            "type": "string",
            "description": "Reference or output showing verification (test name, file:line, output, scenario name)"
          },
          "verified_by": {
            "type": "string",
            "enum": ["test", "manual", "lint", "build", "scenario"],
            "description": "How was this verified?"
          }
        }
      }
    },
    "all_pass": {
      "type": "boolean",
      "description": "True only if ALL checklist items have passes=true"
    },
    "concerns": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Issues blocking verification (empty if all_pass=true)"
    }
  }
}
```

---

## Example: Completed Checklist

```json
{
  "spec_id": "SPEC-001",
  "timestamp": "2026-03-17T22:45:30Z",
  "checklist": [
    {
      "ac_id": "AC-1",
      "description": "Search returns results for valid queries",
      "passes": true,
      "evidence": "test_search_returns_results() — PASSED. Tested with 5 sample queries, all returned expected results.",
      "verified_by": "test"
    },
    {
      "ac_id": "AC-2",
      "description": "Empty query returns empty results gracefully",
      "passes": true,
      "evidence": "test_search_empty_query_returns_empty() — PASSED",
      "verified_by": "test"
    },
    {
      "ac_id": "AC-3",
      "description": "Search is case-insensitive",
      "passes": true,
      "evidence": "SearchService.search() lines 52-57 implements .toLower() before comparison. test_search_case_insensitive() — PASSED",
      "verified_by": "test"
    },
    {
      "ac_id": "AC-4",
      "description": "Results are sorted by relevance score (highest first)",
      "passes": true,
      "evidence": "test_search_results_sorted_by_relevance() — PASSED. Verified output order matches relevance calculation in ResultSorter class.",
      "verified_by": "test"
    }
  ],
  "all_pass": true,
  "concerns": []
}
```

---

## Example: Checklist with Concerns

```json
{
  "spec_id": "SPEC-005",
  "timestamp": "2026-03-18T01:15:00Z",
  "checklist": [
    {
      "ac_id": "AC-1",
      "description": "Cache hits reduce query time by 50%",
      "passes": false,
      "evidence": "Benchmark test shows 45% improvement, not 50%. Likely due to measurement variance or initial load overhead.",
      "verified_by": "test"
    },
    {
      "ac_id": "AC-2",
      "description": "Cache is thread-safe under concurrent load",
      "passes": false,
      "evidence": "test_concurrent_cache_access() fails intermittently. Race condition suspected but not isolated.",
      "verified_by": "test"
    }
  ],
  "all_pass": false,
  "concerns": [
    "AC-1: Performance target may be unrealistic given system load. Needs acceptance of 45% vs 50% or investigation of why overhead is higher than expected.",
    "AC-2: Thread-safety issue remains unresolved. Blocks production use of cache. Spec needs clarification on concurrency model (fine-grained locking vs lock-free vs coarse-grained)."
  ]
}
```

---

## Key Rules

1. **No skipping:** Every AC must be in the checklist. No "assumed to pass" items.
2. **Fresh evidence only:** If you ran a test at step 5, and it passed, you still need to run it again here to claim `passes: true`.
3. **Explicit concerns:** If you can't verify something, log it. Don't pretend it's fine.
4. **One decision per checklist:** Each checklist is tied to ONE spec. Don't combine multiple specs.
5. **Timestamping matters:** Record when the checklist was created (ISO 8601). This helps with traceability.
6. **Report integration:** Key metrics from the checklist feed into the main metrics YAML (step 13 of LOOP.md).

---

## Integration with LOOP.md

This checklist is executed as **Step 9.5 (Completion Verification)**, between step 9 (Full
Validation) and step 9.6 (Output Artifact Verification).

At the end of step 9.5:
- Checklist JSON saved to `reports/_wip/checklist-<spec-id>.json`
- Key fields copied to metrics under `phases.completion_verification:`
- If `all_pass: true` → continue the loop (9.6, then 9.7 if it applies, then step 10)
- If `all_pass: false` → either go back to step 8 to fix, or continue with the DONE_WITH_CONCERNS flag

This guard prevents the loop from declaring a spec complete without actually proving each AC is met.
