# Metrics Schema — Failure Fields (SPEC-045 addendum) + Synthesis Gate Note

> This file documents the **failure-record fields** consumed by
> `canonical/knowledge_writer.py` (`synthesize()` / `extract_failure_info()`).
> For the full per-spec metrics YAML schema, see `canonical/metrics/_SCHEMA.md`.
> SPEC-028 adds an optional `phases.synthesis_gate` block when Step 9.7 fires.

## Emission path (SPEC-067)

Per-spec metrics are emitted by **`canonical/record_metrics.py`**, not hand-authored
by the model. The script writes one schema-valid YAML, deriving most fields from git
and `config.yaml` and computing the `satisfaction` block from objective inputs. See
LOOP.md Step 13 for the invocation. There is no separate post-run JSON aggregate —
`analyze_metrics.py` reads the per-spec YAMLs directly.

## Follow-up lineage and incidence metrics (SPEC-236)

`followup_metrics.py` seals versioned JSON lineage records beneath the ignored
metrics/report surface. Each record has a stable operation key, project/run/source
IDs, optional created child ID, closed cause/detail/phase/outcome values, derived
`source_contract_incomplete`, source hash, timestamp, and approved relative evidence
references. Replays are byte-idempotent. The aggregate reports explicit numerator,
eligible denominator, nullable value and `sample_state`; it treats a recorded zero
suggestion decision as an eligible observation. Fleet/public projections allow only
controlled categories, counts, rates, time buckets and source hashes.

## Private Dropbox observability boundary (SPEC-187)

When explicitly enrolled, `observability.sink: private-dropbox` stores immutable
private artifacts outside the repository. Public configuration and aggregate-safe
projections contain only controlled categorical/count/duration values and
fingerprints. Redacted private evidence remains in the operator store. Raw logs,
prompts, command arguments, environment values, secrets, application/user data,
absolute paths, and remote URLs are forbidden in every class.

## Prospective real-use experiments (SPEC-238)

Tracked `experiments/*.yaml` descriptors preregister a revision-bound hypothesis,
eligible population, event chain, numerator/denominator, thresholds, stopping rule,
producer fingerprint, privacy class, and invalidating assumptions. The private
observability store owns immutable `experiment_event` and `experiment_result`
objects. Events are per-project sequence/hash chained and carry only UUIDs,
digests, controlled identifiers, enums, booleans, counts, durations, and versions.

`reports/_wip/experiment-status.json` is replaceable derived state. The board
`/api/experiments` route and fleet snapshot expose only experiment/source IDs,
revision, state, review trigger, sample state, eligible count, integer numerator
and denominator, nullable value, evidence scope, conclusion, and bounded timing.
Raw observations never cross that projection. Empty denominators are
`sample_state: no_samples` with `value: null`; passive observations cannot support
a controlled or randomized claim. Unsupported or invalidated sealed results use
the existing SPEC-236 follow-up processor exactly once.

## Recovery telemetry and run projection (SPEC-188)

Recovery observations use the existing run event stream only: `capability_probe`,
`recovery_attempt_started`, `recovery_attempt_finished`, `recovery_escalated`,
`block_evaluated`, and `run_resolved`. Payloads are controlled enums, booleans,
counts, bounded durations, hashes, and approved relative evidence references.
Analytics deduplicate by run ID and use explicit numerator/denominator/no-sample
results for capability failure, automatic recovery, fresh-worker rescue, and
premature blocks. A private sink failure is `awaiting_sync`, never a reason to
alter implementation evidence or lifecycle resolution.

## Fleet evidence snapshot (SPEC-156-001)

On demand only, `fleet_metrics.py` reads an explicit local registry of managed
project paths and writes the single replaceable, gitignored
`reports/_wip/fleet-metrics-snapshot.json`. It uses bounded concurrency (at
most four projects) and emits only allowlisted categorical outcomes/failures,
counts, durations, timestamps, source hashes, registered project identity,
portable path, kit/schema version, and release fingerprint. Raw metric YAML,
URLs, branches, commits, prose, logs, environment/configuration values and
application/user data never enter the snapshot.

The snapshot records registered/reachable/missing project and eligible-run
denominators, zero-sample windows, source metric hashes, and observations
classified as `single_observation`, `repeated_single_project`, or
`cross_project`. These fields are evidence rather than collection gates:
`/evolve` retains its existing sufficiency and approval decisions. No release
invokes collection, no scheduler is installed, and no fleet ledger/database or
canonical mutation path exists.

## Lifecycle classification events (SPEC-162-001)

`lifecycle_metrics.emit_lifecycle_event()` writes
`event: lifecycle_classification`, `schema_version: 1` through the same durable
`RunEventLog.emit()` path as loop events. Required fields are `spec_id`,
`from_status`, `to_status`, readiness (`PASS`, `REVIEW`, or `FAIL`),
derived `run_state`, and boolean `classified`. Optional evidence fields record
corrections, ambiguity/discussion resolution, blocker validation/reason/dwell,
transition durations, scope revision, partial-value preservation, and gap-spec
outcomes. Scope events may additionally record `scope_split`, moved
requirement/AC mappings, outcome (`done` or `partial`), and
completed-evidence preservation.

An intrinsic readiness review may add a prose-free `contract_review` payload:

```yaml
contract_review:
  requirements_reviewed: 2
  acceptance_criteria_reviewed: 3
  items:
    - kind: requirement
      id: R2
      reasons: [ambiguous_or_unbounded, missing_oracle]
    - kind: acceptance_criterion
      id: AC3
      reasons: [stale_or_unverified_baseline]
```

Record every contract review that examines R/ACs, including clean reviews with
`items: []`. The counts are item-observation denominators, so a later review of
the same revised item is a new observation. Each flagged item counts once in its
rate and once under every applicable reason. The controlled reasons are
`ambiguous_or_unbounded`, `delegated_material_decision`,
`non_testable_or_tautological`, `stale_or_unverified_baseline`,
`dependency_drift`, `environment_unreproducible`, `scope_overload`, and
`missing_oracle`. The payload permits only counts, canonical R/AC identifiers,
item kinds, and reason codes; never copy requirement or AC prose into it.

`lifecycle_metrics.calibrate_lifecycle_events()` is the executable definition
of every policy metric. Each rate emits `numerator`, `denominator`, `value`, and
`sample_state`. An empty eligible population is `{denominator: 0, value: null,
sample_state: no_samples}`; it is never reported as a zero failure rate.

| Metric | Denominator | Numerator / output |
|---|---|---|
| `false_block_rate` | evaluated blocked classifications | corrected non-blockers |
| `dependency_wait_misclassification_rate` | ordinary dependency waits | waits corrected from blocked |
| `planned_rejection_rate` | proposed `planned` transitions | rejected proposals |
| `draft_escape_rate` | classifications originating in `draft` | premature admissions |
| `ready_to_draft_rate` | classifications originating in `ready` | resolutions to `draft` |
| `classification_correction_rate` | all classified events | corrected classifications |
| `status_ambiguity_rate` | all classified events | `REVIEW`/ambiguous classifications |
| `blocked_validity_rate` | evaluated blocked classifications | evidence-valid blockers |
| `partial_value_preservation_rate` | partial outcomes | preserved completed evidence |
| `classification_discussion_rule_rate` | resolved discussions | discussions producing a reusable rule |
| `requirement_contract_friction_rate` | requirement observations in recorded contract reviews | flagged requirement observations |
| `acceptance_criterion_contract_friction_rate` | AC observations in recorded contract reviews | flagged AC observations |
| `contract_friction_rate` | all R/AC observations in recorded contract reviews | all flagged observations |

The same aggregation emits status-resolution, blocker-reason, scope-revision
and gap-extraction distributions; contract-friction reason and item-kind
distributions; blocker dwell summaries;
`planned_to_ready_time_s`; and `ready_to_runnable_time_s_by_gate`. Historical
calibration is separate from the current deterministic readiness result. Early
contract friction measures revisions caught before implementation; late GAP
requirement patterns remain a separate escape signal and are not reinterpreted.

## `outcome` field (SPEC-067)

An **additive** root field carrying a controlled vocabulary so reports and metrics
are minable: `done | partial | blocked | noop`. It sits alongside `status` (which
keeps its existing enum `completed|failed|blocked|discarded|partial`, so existing
consumers are unaffected). `noop` (with `status: completed`) marks a run that needed
no code change — already satisfied or a duplicate — so no-op runs are countable
instead of masquerading as feature work. The report template's `**Outcome:**` line
must match the `--outcome` passed to `record_metrics.py`.

## Versioned terminal evidence (SPEC-208)

New records emitted by `record_metrics.py` carry `metrics_schema_version: 2`.
Version 2 requires the root `outcome` to use the canonical vocabulary above. A
terminal `blocked` record must also carry `failure.category`, chosen from the
controlled categories accepted by `record_metrics.py` and
`validate_metrics.py`. Free-form descriptions remain private to the original
metric record and are never promoted into a fleet snapshot.

Historical records without `metrics_schema_version` are interpreted as version
1. They remain readable: missing or unfamiliar outcomes become explicit
`unknown` observations at the fleet boundary, and blocked rows without a safe
category remain unclassified. The collector may normalize only these stable
aliases to `done`: `complete`, `completed`, `implemented`, `pass`, `passed`, and
`success`. Compound or caveated values are not guessed.

Each fleet snapshot exposes two evidence-quality rates with an integer
`numerator`, integer `eligible_denominator`, and nullable `value`:

| Metric | Numerator | Eligible denominator |
|---|---|---|
| `fleet_unknown_outcome_rate` | collected rows whose normalized outcome is `unknown` | all collected metric rows |
| `fleet_blocked_classification_rate` | blocked rows with a controlled failure category | all blocked rows |

The first rate is a defect rate, so lower is better; the second is a coverage
rate, so higher is better. When the eligible denominator is zero, `value` is
`null` rather than a misleading zero.

## Purpose

SPEC-045 relaxed the previously-mandatory `failure.root_cause` and
`failure.suggestion` fields to **optional**. This allows raw failure
records produced by handlers that don't yet perform diagnosis (e.g., the
eval harness's `metrics/failure-ledger.json`) to flow through the
knowledge extractor without being silently dropped. When these fields
are absent, the extractor derives fallback text from `error_type`.

## Failure record (minimum viable)

A failure record is any mapping that contains at least:

- `error_type` (string) — a short category key (e.g., `test_failure`,
  `eval_timeout`, `build_broken`).
- `description` (string) — a one-line human summary of what failed.

Either field alone is sufficient for the record to be accepted, but
both are strongly recommended.

### Optional fields

| Field | Type | Semantics |
|-------|------|-----------|
| `phase` | string | Loop phase that produced the failure (e.g., `validation`, `implementation`). Preserved if present; otherwise empty. |
| `root_cause` | string | Explicit root-cause analysis. **Preserved verbatim when non-empty** — no fallback override. |
| `suggestion` | string | Explicit remediation hint. **Preserved verbatim when non-empty**. |
| `details` | mapping | Arbitrary structured context (e.g., `eval_id`, `model`). Used for spec-ID derivation in `failure-ledger.json` entries. |

## Examples

### Explicit-diagnosis form (preferred)

```yaml
failure:
  phase: "validation"
  error_type: "test_failure"
  description: "assert_equal failed in test_parse_commas"
  root_cause: "Mocked dependency returned wrong type"
  suggestion: "Fix the stub to return a DecimalField, not str"
```

Both `root_cause` and `suggestion` are preserved verbatim in the
rendered `IMPROVEMENTS.md`.

## SPEC-028 synthesis gate note

When a research or analysis spec has direct code dependents, Step 9.7 writes
an optional metrics section:

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

This block is omitted entirely when the gate is not applicable. Absence means
"not triggered", not "failed to run".

### Minimal form (fallback kicks in)

```json
{
  "error_type": "eval_timeout",
  "description": "Eval EVAL-002 for model google/gemma-4-31b ended with status 'timeout'",
  "spec_file": "eval-specs/EVAL-002-csv-parser.md"
}
```

The extractor derives:

- `root_cause` → `"Eval exceeded configured time budget"`
- `suggestion` → `"Raise time budget, reduce eval scope, or switch to faster model"`

## Fallback derivation table

Source of truth lives in `canonical/knowledge_writer.py`
(`_ROOT_CAUSE_BY_ERROR_TYPE`, `_SUGGESTION_BY_ERROR_TYPE`). Current
covered error types:

- `test_failure`, `test_hang`
- `build_broken`, `build_error`
- `type_error`, `lint_error`
- `eval_timeout`, `eval_run_failed`
- `aider_failure`, `timeout`

Unknown `error_type` values fall back to generic "inspect logs" text.
The table is intentionally small — LLM-based inference and a formal
taxonomy are out of scope for SPEC-045.

## Empty-run output

If the extractor finds no failures, `IMPROVEMENTS.md` is written with
the single-line body `_No failures this run._` — no placeholder
"Learning #1" entries.

## Supported input sources

`synthesize()` scans its `metrics_dir` for:

1. `*.yaml` / `*.yml` per-spec metrics files (full schema in
   `canonical/metrics/_SCHEMA.md`, `failure` section).
2. `failure-ledger.json` — a JSON array of flat failure records (format
   matches the "Minimal form" example above).

Both sources feed into a single grouped output keyed by `error_type`.

## Controlled verifier-remediation fields (SPEC-235)

Role-aware attempt and parent-delivery records use controlled fields only:

| Field | Type | Contract |
| --- | --- | --- |
| `role` | enum | `implementer`, `verifier`, `remediator`, or `parent` |
| `agent_outcome` | enum | `completed`, `blocked`, `refused`, `failed`, `stalled`, `unavailable`, `passed`, or `cancelled` |
| `reason` | enum | Controlled reducer reason; never prose conclusions |
| `head_digest` | string/null | Exact candidate Git digest |
| `artifact_refs` | list | Project-relative path plus SHA-256 only |
| `idempotency_key` | string | Stable run/spec/head/effect identity |
| `attempt_ordinal` | integer | Remediation and replacement budgets are independently bounded at `1/1` |
| `duration_s` | number | Measured non-negative duration |
| `human_action_required` | boolean | True only for external authority/input, safety/scope refusal, exhausted budgets, or adapter failure |
| `next_action` | enum | Controlled controller/operator action |

Actor outcomes never copy directly into spec lifecycle. The parent terminal row
is a separate delivery decision. Packet bodies, verdict prose, logs, prompts,
commands, environment values and private paths are not metrics fields.
