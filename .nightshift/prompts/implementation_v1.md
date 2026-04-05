---
id: implementation_v1
phase: implementation
version: "1"
created: "2026-03-30"
runs: 0
successes: 0
success_rate: 0.0
---
# Implementation Prompt

Implement the requested change from the reviewed plan.

## Implementation Summary
{{implementation_summary}}

## Constraints
{{constraints}}

## Focus
- Make the smallest change that fully satisfies the spec.
- Preserve backward compatibility.
- Prefer simple, reviewable code over clever code.

## Output
Return a concise implementation summary and note any follow-up risks.
