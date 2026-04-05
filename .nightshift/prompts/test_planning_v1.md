---
id: test_planning_v1
phase: test_planning
version: "1"
created: "2026-03-30"
runs: 0
successes: 0
success_rate: 0.0
---
# Test Planning Prompt

Use the spec to draft a concrete test plan.

## Spec Content
{{spec_content}}

## Acceptance Criteria
{{ac_list}}

## Task
- Identify happy-path coverage.
- Include edge cases and failure cases.
- Keep the plan short, specific, and executable.

## Output
Return a numbered test plan with test names, inputs, expected behavior, and rationale.
