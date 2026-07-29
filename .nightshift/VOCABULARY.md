# Nightshift Spec Vocabulary

**Canonical source:** `vocabulary-registry.yaml` (version 1).

This generated entry point is checked by `vocabulary.py audit`; consumer-specific examples may add context but must not redefine these terms.

| Key | Label | Short help | Allowed values |
|---|---|---|---|
| `id` | Spec ID | Stable identifier for a spec. | — |
| `title` | Title | Human-readable spec name. | — |
| `type` | Type | The kind of work a spec describes. | feature, bugfix, refactor, main, nfr, research, analysis, task |
| `status` | Status | Stored lifecycle maturity and scheduling intent; not a derived gate. | draft, planned, ready, in_progress, blocked, done, superseded, active, retired |
| `priority` | Priority | Lower number means higher within-layer priority. | — |
| `layer` | Layer | Dependency ordering tier: 0 foundation through 3 polish. | 0, 1, 2, 3 |
| `after` | Dependencies | Hard execution dependencies by spec ID. | — |
| `parent` | Parent | Grouping parent | — |
| `provides` | Provides | Capabilities this spec creates. | — |
| `requires` | Requires | Capabilities this spec needs. | — |
| `touches` | Touches | Likely affected surfaces. | — |
| `nfrs` | NFR bindings | Active quality constraints bound to the spec. | — |
| `nfr_waivers` | NFR waivers | Audited reason an applicable NFR does not bind. | — |
| `requirements` | Requirements | Testable requested outcomes. | — |
| `acceptance_criteria` | Acceptance criteria | Concrete verification conditions. | — |
| `evidence` | Evidence | Durable proof supporting a result. | — |
| `verification` | Verification | Deterministic checks run against the contract. | — |
| `confidence` | Confidence | Diagnostic estimate; never a hidden status transition. | — |
| `outcome` | Outcome | Result of one run | done, partial, blocked, noop |
| `readiness` | Readiness | Deterministic intrinsic contract check. | PASS, REVIEW, FAIL |
| `run_state` | Run state | Current derived admission or execution condition. | runnable, specification_incomplete, intentionally_future, validation_failed, review_required, waiting_dependencies, waiting_external_input, time_gated, overlap_conflict, dependency_cycle, resource_gated, waiting_gap_spec |
| `blocker_class` | Blocker class | Category of an evidenced exceptional constraint. | technical_infeasibility, safety_constraint, evidence_unavailable, critical_external_constraint, unknown_critical_failure |
| `blocker_scope` | Blocker scope | Whether the blocker belongs to this contract. | in_scope, out_of_scope, mixed, unknown |
| `block_reason` | Block reason | Specific evidence-backed explanation of a blocker. | — |
| `unblock_condition` | Unblock condition | Smallest evidence needed to resume safely. | — |
| `prior_attempts` | Prior attempts | Durable record of earlier attempts. | — |
| `overrides` | Overrides | Explicit | — |
| `roles` | Roles | Run | run, worker, orchestrator, parent |

## Registry-derived definitions

### Spec ID

A unique durable identifier used by dependencies and reports.

### Title

The H1 summary of a spec contract.

### Type

Classifies a specification and selects its completion rules.

### Status

draft is being defined; planned is validated future work; ready is validated current-priority work; blocked is an evidenced critical constraint only.

### Priority

Scheduling order within a layer; it does not change readiness.

### Layer

Architectural execution tier used for ordering work.

### Dependencies

IDs which must be complete before this spec can run.

### Parent

Parent initiative or NFR hierarchy reference.

### Provides

Capability markers produced by the spec.

### Requires

Advisory capability markers

### Touches

Scope markers used for overlap warnings.

### NFR bindings

NFR IDs that apply as binding constraints.

### NFR waivers

Explicit exception record for a mechanically matched NFR.

### Requirements

Contract requirements mapped to acceptance criteria. A normal done spec has every Requirement checkbox checked; validate_specs.py enforces this terminal invariant.

### Acceptance criteria

Checkable conditions that prove the contract. A normal done spec has every Acceptance Criterion checkbox checked; validate_specs.py enforces this terminal invariant.

### Evidence

Test

### Verification

Validation evidence collected before resolution.

### Confidence

Non-authoritative confidence signal for a decision.

### Outcome

Immutable run result.

### Readiness

PASS allows admission evaluation; REVIEW preserves ambiguity for a recorded decision; FAIL prevents admission.

### Run state

Non-durable operational state derived from current evidence; a closed gate never changes stored lifecycle status.

### Blocker class

Classifies a true blocker for metrics and recovery; ordinary dependency and scheduling waits are admission states.

### Blocker scope

Scope classification for blocker remediation.

### Block reason

Why an exceptional constraint prevents progress.

### Unblock condition

Actionable or explicitly unknown condition for recovery.

### Prior attempts

Historical attempts consulted before retrying work.

### Overrides

Recorded exceptions to configured behavior.

### Roles

Roles separate execution from coordination and parent resolution.
