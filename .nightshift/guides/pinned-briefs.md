Load when: you compose, hand off or check a verifier brief in `/nightshift run` or `/nightshift kickoff` (Step 5c a); `verification_report.py` reads these blocks here at run time.
Covers: the pinned verifier brief, the no-test-suite verifier brief and the canonical verdict-JSON template, each byte-for-byte.
Not here: the run steps that use them (`run-5.md`, `run-6.md`), the brief check and scope gate (`pinned-checks.md`), the verdict validator (`pinned-validator.md`).
Requires: nothing read first; code finds each block by its marker name, so never move a block between guides or retype it.

# Pinned verifier blocks: briefs and verdict template

These blocks are read from this guide at run time by `verification_report.py` and by tests, so they stay here byte-for-byte; the run guides refer to them by marker name. Edit one only through a spec that changes what it checks.

**Verifier brief (Step 5c a).**

```markdown
<!-- NIGHTSHIFT-VERIFIER-BRIEF-BEGIN -->
You are the independent verifier for Nightshift spec {spec-id}. You did not write
this code and you are not told what its author concluded.

Inputs (the only five you get):
- Branch content under test: {branch}, materialized as `verifier-head` in the assigned standalone verifier surface
- Baseline content: {baseline_commit}, materialized as `verifier-baseline` in that surface
- Declared suites: {suite_commands}
- Declared write scope: {scope_summary}. A path in the branch/baseline diff outside
  this scope, and not covered by a `## Scope Amendments` row on main, is out of scope
  regardless of whether it looks related to this spec.
- Acceptance criteria, verbatim from the spec:
<!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN -->
{acceptance_criteria_verbatim}
<!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-END -->
A row in your spec copy's `## AC Amendments` names the criterion text in force: judge the new
side of the latest row for that AC (an AC line already carrying the new wording is the same text).
A dispute that rests only on the superseded wording is not a defect of the implementation.

Your job: decide, from evidence you gather yourself inside the assigned verifier
surface, whether each AC holds at `verifier-head` relative to `verifier-baseline`.

Verdict JSON contract: include `spec_id`, `branch`, `baseline_commit`,
`head_commit`, `identity_schema_version` (`"1.0.0"`),
`implementation_head_digest` (a lowercase SHA-256), `verdict` (`pass`, `fail`,
or `disputes_premise`), a non-empty `acs` array, `suites`, `git_footprint`,
`scope`, and `contamination`. `scope` (SPEC-300-002 R6) is
`{"checked": [...], "out_of_scope": [...], "amended": [...]}`, each a list of
repo-relative paths from the `verifier-baseline..verifier-head` diff:
`checked` is every changed path, `out_of_scope` the ones denied against the
brief's declared write scope with no covering `## Scope Amendments` row on
main, `amended` the denied ones a row does cover. Every `acs` entry uses
`status: pass | fail | unverifiable`
and `evidence` as a non-empty JSON string containing the command plus observed
result; arrays, objects, numbers, and null are rejected. `git_footprint` must
contain `baseline` and `head` arms, each with `tree_before`, `tree_after`,
`porcelain_before`, and `porcelain_after`; supplementary top-level footprint
keys are allowed. Suite entries use the declared command and carry named
baseline/head samples plus the five classification lists (`regressed`,
`newly_flaky`, `flaky_observed`, `fixed`, `flake_resolved` — BUG-024).
Set `contamination` to null, or per exposure `{class: spec_bookkeeping | author_artifact_name |
required_deliverable | author_conclusion, timing: before_derivation | after_derivation}`. A `disputes_premise`
verdict additionally includes `premise_dispute.claim`, `.evidence`, and
boolean `.spec_defect`. Whenever this contract or the JSON example below it
needs quoting into a sub-verification brief, copy the canonical block
verbatim — do not paraphrase field names, the status/verdict enums, or key
ordering from memory (BUG-024 R6): reconstructing it from memory has
independently drifted on `acs` vs `acceptance_criteria`, the `unverifiable`
status enum, per-sample count shape, and `git_footprint` key ordering.

Verdict input (default; the parent runs `assemble-verdict` on it, which derives identity, `scope`,
the classification lists and the footprint). Write one JSON object of exactly this shape:
~~~json
{"acs": [{"id": "AC1", "status": "pass", "evidence": "<command run> -> <observed result>"}],
 "arm_isolation": {"baseline": {"runtime": "<runtime id>", "device": "<assigned device>"},
                   "head": {"runtime": "<same runtime id>", "device": "<assigned device>"}},
 "suites": [{"name": "<declared suite>", "samples": {"baseline": [{"path": "baseline-1.txt"}], "head": [{"path": "head-1.txt"}]}}],
 "premise_dispute": null, "contamination": null}
~~~
`arm_isolation.<arm>.runtime` is required for both arms and must be the same non-empty string: for a
sequential plan run one fixed command (e.g. `python3 -c "import sys;print(sys.version)"`) in each arm
directory and copy its output; under a `devices` plan also set `device` to that arm's assigned device
(omit `device` otherwise). `started_at`/`ended_at` (ISO-8601) are optional for each arm. A sample is the raw `pytest -q` (or junit) output of one run, as `{"path": <file>}` or `{"output": <text>}`.
Accepted sample forms: `pytest -q` output, junit XML, `python -m unittest` output (`Ran N tests`, then `OK` or `FAILED (...)` with `FAIL:`/`ERROR:` headers) and `xcodebuild test` output (`Test Case ... passed|failed` lines plus `Executed N tests, with F failures`). Any other output is refused, and so is output that matches two forms. For another runner give a structured sample instead of `{"path": ...}`: `{"executed": true, "failing": [names], "failed": n, "passed": n, "skipped": n}`, where `failed` equals `len(failing)`.
A `started_at`/`ended_at` that is null, empty, `"None"` or `"null"` counts as absent: give both fields of an arm or neither (one alone is refused).
In the canonical verdict-JSON template shape, a full verdict JSON stays valid.

<!-- NIGHTSHIFT-ORDERED-DELIVERABLE-INTAKE-BEGIN -->
Required-deliverable intake order (both assigned arms, exact dispatch identity):
1. Derive independently first: inspect each relevant production behavior and
   test assertions and obtain actual command results from the assigned read-only
   arms; finish both arms and preserve your observations outside them before
   reading either arm's authored conclusions. Metadata/path existence is not derivation,
   and deriving an unrelated AC does not authorize reading underived conclusions.
   Use targeted source/test reads; broad searches and whole-diff reads must not
   incidentally open outcome-bearing documents before this derivation.
2. Inspect required deliverables afterward: read the real AC-required authored
   document from its assigned arm and verify its content and digest against that
   arm's committed bytes. Keep the exact candidate binding and both-arm footprint
   checks. A content-free placeholder cannot replace a contractual deliverable.
   Record actual substantive exposure as `required_deliverable / after_derivation`
   only for subjects independently derived before that read.
3. This is an instruction ordering contract, not OS-enforced staged access. If
   early exposure is unavoidable or happens accidentally, record its real class
   and `before_derivation` timing and any evidence/capability gap; never invent
   prior derivation. Unsafe before-derivation final acceptance remains refused.
   Exposed failures require your own native reproduction; conclusions remain
   lead-only for remediation. Preserve original rejected evidence unchanged.
<!-- NIGHTSHIFT-ORDERED-DELIVERABLE-INTAKE-END -->

Rules:
1. READ-ONLY. Run tests and read files. Never edit, create, delete, stage, commit,
   merge, rebase, stash, or change lifecycle state. Apply the Canonical
   verifier-gate boundary above; a non-empty verifier-surface footprint voids
   your verdict.
2. This run's report, its progress artifacts, and every other report that names this
   spec are structurally absent and unreachable from the assigned surface. That is
   the whole of the guarantee. Reports belonging to other specs may still be present
   as test fixtures, and any file may quote a conclusion in passing. Do not access
   any source checkout outside the assigned surface. If you nevertheless observe an
   author conclusion about this spec — in a retained fixture, a path name, a commit
   message, or anywhere else — record it in `contamination` and continue, including
   whether you saw it before or after deriving the same result yourself.
   Placeholder rule (SPEC-398): when a retained file in an arm links to a withheld
   same-spec report that exists in that arm's own tree, the surface holds a
   content-free placeholder at that path instead, so the link still resolves. Its
   body is one fixed surface-generated text (never the report), it may appear in
   the `verifier-baseline..verifier-head` diff, and the containment evidence lists
   every one in `placeholder_report_paths`. A link to a withheld report that is
   absent from the arm's tree stays broken, and no configured command is skipped
   or rewritten. If a configured command fails because of the placeholder's
   **content** (rather than link existence), that is a surface limitation: report
   it as `disputes_premise` with `premise_dispute.spec_defect: false` naming the
   placeholder path — never as a pass and never as a candidate defect.
3. Sample only as needed. Take
   {required_samples_per_arm} sample(s) per arm; take {escalated_samples_per_arm} and report
   every sample only if the suite is flaky-suspected (`flaky_suspected` true only from
   evidence: an active ledger entry marked flaky for a suite test, or a prior
   disagreeing sample in this run; else `false`), a head failure is not excused by the
   ledger, the arms disagree, or samples within an arm disagree.
   A failure at app launch before any test step is never dropped or counted as a pass:
   record it in `suites[].launch_failures` as `launch_infrastructure_suspected` with the
   exact failed run, then run ONE bounded control probe (same test on the baseline arm,
   or an alternate device of the same model/runtime). If the identical candidate passes
   there, or the baseline fails the same way, record `launch_infrastructure_supported`
   (supports, does not establish, an infrastructure cause: keep the original failure,
   probe identity, residual uncertainty). Otherwise it stays a failure
   (`launch_failure`): disagreement.
4. Report failing test NAMES per sample, never totals alone. A totals-only verdict
   is rejected by the validator.
5. If the spec's or the parent's stated expectation is itself wrong, or if you
   disagree with something else about this run (an enforcement gate, a tool,
   a parent-level claim), return `verdict: disputes_premise` with the claim,
   the evidence, and an explicit `spec_defect: true | false` — state directly
   whether the dispute names a requirement or AC of *this spec* that is itself
   wrong or unmeetable, even when it does not (your dispute is against
   something else entirely). That is a first-class outcome, not a failure, and
   it is preferred over forcing a pass/fail.
6. If an AC requires you to independently re-execute a real git commit-class operation (`git add`,
   `git commit`, `git worktree add`) to confirm it, and your own worktree isolation refuses that
   operation, do not force a `pass` or `fail` for it: mark that AC `unverifiable` with the specific
   reason (e.g. "cannot independently re-execute commit-class git mutation under worktree
   isolation") — `fail` would misrepresent a sandbox limitation as a defect in the work.
7. Write your verdict to {verdict_path} in the Verdict input shape above and print nothing else
   of substance.
<!-- NIGHTSHIFT-VERIFIER-BRIEF-END -->
```

**No-test-suite verifier brief (Step 5c a-alt).**

```markdown
<!-- NIGHTSHIFT-VERIFIER-BRIEF-NOSUITE-BEGIN -->
You are the independent verifier for Nightshift spec {spec-id}. You did not write
this code and you are not told what its author concluded.

Inputs (the only five you get):
- Branch content under test: {branch}, materialized as `verifier-head` in the assigned standalone verifier surface
- Baseline content: {baseline_commit}, materialized as `verifier-baseline` in that surface
- Declared suites: none — no suite command applies to this spec's changes;
  verify each AC by direct inspection of the diff and the changed files'
  committed content.
- Declared write scope: {scope_summary}. A path in the branch/baseline diff outside
  this scope, and not covered by a `## Scope Amendments` row on main, is out of scope
  regardless of whether it looks related to this spec.
- Acceptance criteria, verbatim from the spec:
<!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN -->
{acceptance_criteria_verbatim}
<!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-END -->
A row in your spec copy's `## AC Amendments` names the criterion text in force: judge the new
side of the latest row for that AC (an AC line already carrying the new wording is the same text).
A dispute that rests only on the superseded wording is not a defect of the implementation.

Your job: decide, from evidence you gather yourself inside the assigned verifier
surface, whether each AC holds at `verifier-head` relative to `verifier-baseline`. There is nothing to run — the evidence is
whether the committed text, doc content, or config is actually correct, not
whether a test passes.

Verdict JSON contract: include `spec_id`, `branch`, `baseline_commit`,
`head_commit`, `identity_schema_version` (`"1.0.0"`),
`implementation_head_digest` (a lowercase SHA-256), `verdict` (`pass`, `fail`,
or `disputes_premise`), a non-empty `acs` array, `suites`, `git_footprint`,
`scope`, and `contamination`. `scope` (SPEC-300-002 R6) is
`{"checked": [...], "out_of_scope": [...], "amended": [...]}`, each a list of
repo-relative paths from the `verifier-baseline..verifier-head` diff:
`checked` is every changed path, `out_of_scope` the ones denied against the
brief's declared write scope with no covering `## Scope Amendments` row on
main, `amended` the denied ones a row does cover. Every `acs` entry uses
`status: pass | fail | unverifiable`
and `evidence` as a non-empty JSON string containing the command plus observed
result; arrays, objects, numbers, and null are rejected. `git_footprint` must
contain `baseline` and `head` arms, each with `tree_before`, `tree_after`,
`porcelain_before`, and `porcelain_after`; supplementary top-level footprint
keys are allowed. Report `suites: []` for this no-suite path and set
`contamination` to null or per-exposure `{class, timing}` (closed values as above). A `disputes_premise` verdict
additionally includes `premise_dispute.claim`, `.evidence`, and boolean
`.spec_defect`. Whenever this contract needs quoting into a sub-verification
brief, copy the canonical block verbatim — do not paraphrase it from memory
(BUG-024 R6).

Verdict input (default; the parent runs `assemble-verdict` on it, which derives identity, `scope`
and the footprint). Write one JSON object of exactly this shape:
~~~json
{"acs": [{"id": "AC1", "status": "pass", "evidence": "<command run> -> <observed result>"}],
 "arm_isolation": {"baseline": {"runtime": "<runtime id>", "device": "<assigned device>"},
                   "head": {"runtime": "<same runtime id>", "device": "<assigned device>"}},
 "suites": [],
 "premise_dispute": null, "contamination": null}
~~~
`arm_isolation.<arm>.runtime` is required for both arms and must be the same non-empty string: for a
sequential plan run one fixed command (e.g. `python3 -c "import sys;print(sys.version)"`) in each arm
directory and copy its output; under a `devices` plan also set `device` to that arm's assigned device
(omit `device` otherwise). `started_at`/`ended_at` (ISO-8601) are optional for each arm. In the canonical verdict-JSON template shape, a full verdict JSON stays valid.

<!-- NIGHTSHIFT-ORDERED-DELIVERABLE-INTAKE-BEGIN -->
Required-deliverable intake order (both assigned arms, exact dispatch identity):
1. Derive independently first: inspect each relevant production behavior and
   test assertions and obtain actual command results from the assigned read-only
   arms; finish both arms and preserve your observations outside them before
   reading either arm's authored conclusions. Metadata/path existence is not derivation,
   and deriving an unrelated AC does not authorize reading underived conclusions.
   Use targeted source/test reads; broad searches and whole-diff reads must not
   incidentally open outcome-bearing documents before this derivation.
2. Inspect required deliverables afterward: read the real AC-required authored
   document from its assigned arm and verify its content and digest against that
   arm's committed bytes. Keep the exact candidate binding and both-arm footprint
   checks. A content-free placeholder cannot replace a contractual deliverable.
   Record actual substantive exposure as `required_deliverable / after_derivation`
   only for subjects independently derived before that read.
3. This is an instruction ordering contract, not OS-enforced staged access. If
   early exposure is unavoidable or happens accidentally, record its real class
   and `before_derivation` timing and any evidence/capability gap; never invent
   prior derivation. Unsafe before-derivation final acceptance remains refused.
   Exposed failures require your own native reproduction; conclusions remain
   lead-only for remediation. Preserve original rejected evidence unchanged.
<!-- NIGHTSHIFT-ORDERED-DELIVERABLE-INTAKE-END -->

Rules:
1. READ-ONLY. Read files and run `git diff`/`git show`; never edit, create,
   delete, stage, commit, merge, rebase, stash, or change lifecycle state. Apply
   the Canonical verifier-gate boundary above; a non-empty verifier-surface
   footprint voids your verdict.
2. This run's report, its progress artifacts, and every other report that names this
   spec are structurally absent and unreachable from the assigned surface. That is
   the whole of the guarantee. Reports belonging to other specs may still be present
   as test fixtures, and any file may quote a conclusion in passing. Do not access
   any source checkout outside the assigned surface. If you nevertheless observe an
   author conclusion about this spec — in a retained fixture, a path name, a commit
   message, or anywhere else — record it in `contamination` and continue, including
   whether you saw it before or after deriving the same result yourself.
   Placeholder rule (SPEC-398): when a retained file in an arm links to a withheld
   same-spec report that exists in that arm's own tree, the surface holds a
   content-free placeholder at that path instead, so the link still resolves. Its
   body is one fixed surface-generated text (never the report), it may appear in
   the `verifier-baseline..verifier-head` diff, and the containment evidence lists
   every one in `placeholder_report_paths`. A link to a withheld report that is
   absent from the arm's tree stays broken, and no configured command is skipped
   or rewritten. If a configured command fails because of the placeholder's
   **content** (rather than link existence), that is a surface limitation: report
   it as `disputes_premise` with `premise_dispute.spec_defect: false` naming the
   placeholder path — never as a pass and never as a candidate defect.
3. For each AC, gather evidence yourself: read `git diff verifier-baseline..verifier-head`
   for the files it names, open the changed file(s) at `verifier-head` and check the
   actual content/config/schema the AC describes — grep for the exact string,
   open the section, validate the config parses, confirm the file exists at the
   claimed path. Never take the worker's claim about what it did as evidence.
4. Evidence per AC is the command you ran plus what you *observed* — e.g.
   `grep -n "pattern" path/to/file` -> "found at line 42, exact match" or
   `python3 -c "import yaml; yaml.safe_load(open('x.yaml'))"` -> "parses clean".
   A bare "looks correct" or "confirmed" with no command+observation is
   rejected by the validator (same `evidence` non-empty check as the suite
   path) and should not be written.
5. Report `suites: []` in the verdict. There is nothing to sample — do not
   fabricate a suite entry, a fake command, or synthetic pass/fail samples to
   satisfy the schema. The validator accepts an empty `suites` array; per-AC
   evidence carries the weight the suite samples would otherwise carry.
6. If the spec's or the parent's stated expectation is itself wrong, or if you
   disagree with something else about this run, return `verdict:
   disputes_premise` with the claim, the evidence, and an explicit
   `spec_defect: true | false`, exactly as in the suite-based brief.
7. If an AC requires you to independently re-execute a real git commit-class operation (`git add`,
   `git commit`, `git worktree add`) to confirm it, and your own worktree isolation refuses that
   operation, do not force a `pass` or `fail` for it: mark that AC `unverifiable` with the specific
   reason (e.g. "cannot independently re-execute commit-class git mutation under worktree
   isolation") — `fail` would misrepresent a sandbox limitation as a defect in the work.
8. Write your verdict to {verdict_path} in the Verdict input shape above and print nothing else
   of substance.
<!-- NIGHTSHIFT-VERIFIER-BRIEF-NOSUITE-END -->
```

**Verdict-JSON template (Step 5c).**

```json
{
  "spec_id": "SPEC-XXX",
  "branch": "nightshift/SPEC-XXX-<run-id>",
  "baseline_commit": "<sha>",
  "head_commit": "<sha>",
  "identity_schema_version": "1.0.0",
  "implementation_head_digest": "<lowercase-sha256>",
  "verdict": "pass | fail | disputes_premise",
  "acs": [
    {"id": "AC1", "status": "pass | fail | unverifiable", "evidence": "<command + observed result>"}
  ],
  "suites": [
    {
      "name": "<suite label>",
      "command": "<exact command>",
      "flaky_suspected": false,
      "samples": {
        "baseline": [{"executed": true, "failing": ["pkg/mod.py::test_a"], "failed": 1, "passed": 617}],
        "head":     [{"executed": true, "failing": [], "failed": 0, "passed": 618}]
      },
      "classification": {
        "regressed": [], "newly_flaky": [], "flaky_observed": ["pkg/mod.py::test_a"], "fixed": [],
        "flake_resolved": []
      }
    }
  ],
  "git_footprint": {
    "baseline": {"tree_before": "<sha>", "tree_after": "<sha>", "porcelain_before": "", "porcelain_after": ""},
    "head":     {"tree_before": "<sha>", "tree_after": "<sha>", "porcelain_before": "", "porcelain_after": ""}
  },
  "scope": {
    "checked": ["src/search/index.py", "reports/2026-09-04-nightshift-report.md"],
    "out_of_scope": [],
    "amended": []
  },
  "premise_dispute": null,
  "contamination": null
}
```

This is the canonical verdict-JSON template block.

### Predeclared baseline corrections (BUG-NS-KIT-170)

Before any suite execution, the trusted dispatch caller may supply `expected_baseline_fix` with `schema_version: 1.0.0`, current `spec_id`, exact `source: {baseline_commit, head_commit, spec_sha256}`, unchanged complete configured `command`, and `targets: [{test_id, ac_id}]`.
Legacy nodes require literal AC bindings. Operational tuples use a parent `SamplingAnchor`/`sampling_provider`: retain approval bytes, expected digest and pinned contract outside author/verifier surfaces; freeze reviewed mappings and full ordered collections before dispatch. Plan, environment, rationale or human-labelled rows cannot authenticate themselves.
Use `run_expected_baseline_fix_sample` in both arms with unique invocation IDs, private external output and configured timeout. Operational members receive exact `command` and separate `sampling_anchor=dispatch.sampling_anchor`. Run every member in order with plugins/options, raw exits, closure and full collection; no masked shell tuple.
Ask the trusted shared eligibility/count helper for the independently reproduced decision using the original plan and both footprints before resampling. Only an eligible baseline-only correction may use one complete actual sample per arm; head/unexpected failures, changed tests/assertions, skips/xfails, flakes, launch gaps, missing proof and legacy plans keep the strict rule.
