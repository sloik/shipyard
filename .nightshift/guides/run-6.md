Load when: you run `/nightshift run` or `/nightshift kickoff` and have reached the steps listed under Covers.
Covers: part 6 of 8 of the run procedure: continues with: b; c; First scaffold only (SPEC-392); d; e.
Not here: spec authoring (`/nightshift spec`), recovery of a blocked spec (`unblock.md`); the run's pinned executable blocks are in `pinned-briefs.md`, `pinned-checks.md` and `pinned-validator.md`.
Requires: a ready spec in an installed project; read the parts in order: `run.md`, `run-2.md`, `run-3.md`, `run-4.md`, `run-5.md`, `run-6.md`, `run-7.md`, `run-8.md`.

# Run guide, part 6 of 8

**b. Dispatch, with the read-only footprint asserted by hash, over both assigned
arm surfaces (R4/R6/AC1/AC2).** Capture each arm's tree hash *and* its
working-tree entries before and after; assert that the tree hash is equal and
that the two sets of entries are equal. A worktree that was already dirty at
dispatch is not the verifier's footprint — only what the set comparison shows it
added or removed is. Mutation, or an entry gained or lost, in *either* arm voids
the verdict; a clean baseline arm never masks a dirty head arm or vice versa:

```bash
# NIGHTSHIFT-FOOTPRINT-BEGIN
# usage: FOOTPRINT_BASELINE_BEFORE=$(footprint_before <baseline-worktree>)
#        FOOTPRINT_HEAD_BEFORE=$(footprint_before <head-worktree>)   # export/keep both in scope
#        ... dispatch the verifier ...
#        footprint_after <baseline-worktree> "$FOOTPRINT_BASELINE_BEFORE" baseline
#        footprint_after <head-worktree> "$FOOTPRINT_HEAD_BEFORE" head
# The captured value is the arm's tree hash on line 1 and its working-tree
# entries below it, so `footprint_after` set-compares what the verifier returned
# against what it was handed (SPEC-284). It is never a test of whether the
# worktree happened to be clean at dispatch: an entry in both snapshots was
# already there and is nobody's write, while an entry only after (added) or only
# before (removed) is the verifier's, whatever the path is called.
footprint_before() {
  git -C "$1" rev-parse 'HEAD^{tree}'
  git -C "$1" status --porcelain=v1 --untracked-files=all | LC_ALL=C sort
}
footprint_after() {
  local worktree="$1" before="$2" label="$3"
  local before_tree after_tree before_dirt after_dirt added removed
  before_tree=$(printf '%s\n' "$before" | head -n 1)
  before_dirt=$(printf '%s\n' "$before" | tail -n +2 | grep -v '^[[:space:]]*$' | LC_ALL=C sort)
  after_tree=$(git -C "$worktree" rev-parse 'HEAD^{tree}')
  after_dirt=$(git -C "$worktree" status --porcelain=v1 --untracked-files=all | grep -v '^[[:space:]]*$' | LC_ALL=C sort)
  if [ "$after_tree" != "$before_tree" ]; then echo "FOOTPRINT[$label]: violated (tree $before_tree -> $after_tree)"; return 1; fi
  added=$(comm -13 <(printf '%s\n' "$before_dirt") <(printf '%s\n' "$after_dirt") | grep -v '^[[:space:]]*$')
  removed=$(comm -23 <(printf '%s\n' "$before_dirt") <(printf '%s\n' "$after_dirt") | grep -v '^[[:space:]]*$')
  if [ -n "$added" ]; then echo "FOOTPRINT[$label]: violated (verifier added: $(echo $added))"; return 1; fi
  if [ -n "$removed" ]; then echo "FOOTPRINT[$label]: violated (verifier removed: $(echo $removed))"; return 1; fi
  echo "FOOTPRINT[$label]: clean ($after_tree)"; return 0
}
# NIGHTSHIFT-FOOTPRINT-END
```

```
Agent({
  description: "nightshift verify {spec-id}",
  subagent_type: "nightshift-verifier",
  prompt: <composed verifier brief, naming DISPATCH_PLAN.arm_working_directories.baseline and .head as the two mandatory workdirs, one per arm, for every command>,
  mode: "bypassPermissions",
})
```

The verifier runs against the **standalone repository emitted in
`DISPATCH_PLAN`**, never the existing run worktree — and, since SPEC-282, that
standalone repository already contains both arms pre-materialized as their own
runnable, checked-out, read-only working directories at
`DISPATCH_PLAN.arm_working_directories.baseline` and `.head`. The verifier
never checks out a ref, creates a worktree, or materializes any file itself;
it only names whichever of the two already-assigned directories a command
targets (for example with the tool's `workdir` or `git -C`). Every command in
the brief must name the correct arm's directory explicitly. If the current
harness cannot make that assignment, do not launch the verifier; resolve the
controlled evidence gap instead. The parent retains the run worktree and both
arm surfaces until after the verdict is validated, then performs parent-owned
cleanup.

**c. Verdict schema.** Default: the verifier writes only the small input `{acs, arm_isolation:
{baseline|head: {runtime, device?}}, suites: [{name, samples: {baseline|head: [{"path": <raw
pytest -q or junit output>}]}}], premise_dispute, contamination}` and the parent runs
`verification_report.py assemble-verdict --plan <plan.json> --input <file> --spec-path <spec>
--main-root <root> --out <verdict>`: it derives identity, `scope`, the five lists and the
footprint, runs the validator below and refuses with its exact defect. A hand-written verdict
stays valid. Otherwise the verifier writes one JSON object. Under the (a-alt)
no-test-suite brief, `suites` is legitimately `[]` — the validator (below) never
requires a non-empty `suites` array, only that `acs` is non-empty and every AC
carries evidence. `acs[*].evidence` is specifically a non-empty JSON string,
not a structured value. `git_footprint` must contain the required `baseline`
and `head` arms and may carry supplementary top-level evidence keys. An empty
suite array is not a schema gap to work around:

[Pinned in `.nightshift/guides/pinned-briefs.md`: the verdict-JSON template block and its sentence - byte-exact, not repeated here.]

Sample forms accepted by `assemble-verdict`: `pytest -q` output, junit XML, `python -m unittest` output and `xcodebuild test` output. Any other output is refused (so is output matching two forms); for another runner give a structured sample `{"executed": true, "failing": [names], "failed": n, "passed": n, "skipped": n}`, where `failed` equals `len(failing)`. An arm window given as null, empty, `"None"` or `"null"` is absent; give both `started_at` and `ended_at` or neither.

A sample is evidence of an actual run, never a placeholder (R3, SPEC-282). The
validator (below) rejects a sample that declares `"executed": false`, an arm
with no samples at all, and a "zero-count placeholder" — a sample reporting
zero passed, zero failed, and no failing names, which is indistinguishable
from a suite that never ran. Each of the three is a controlled evidence-gap
reason, not an empty passing sample. Do not fabricate a nonzero count to dodge
this check; if an arm genuinely could not be run, that is exactly the
evidence gap the validator exists to surface.

**First scaffold only (SPEC-392).** A genuinely unavailable baseline is represented
separately with optional `suites[].baseline_unavailable`; it is never a passing
sample or a regression comparison. The exact shape is:

```json
{
  "schema_version": "1.0.0",
  "reason": "first_scaffold_absent",
  "baseline_commit": "<assigned synthetic baseline SHA>",
  "head_commit": "<assigned synthetic head SHA>",
  "scaffold_paths": ["app/Example.xcodeproj/project.pbxproj"],
  "guard": {"path": "scripts/quality.sh", "sha256": "<tracked baseline file SHA-256>"},
  "config_path": ".nightshift/config.yaml",
  "command": "bash scripts/quality.sh test"
}
```

The verifier independently runs the configured command in each assigned arm
three times. Every baseline sample records `executed: true`, `exit_code: 78`,
`discovered: 0`, `passed: 0`, `failed: 0`, `skipped: 0`, `failing: []`, and
`output_sha256` (SHA-256 of stdout bytes concatenated with stderr bytes). Each
head sample records explicit execution, exit0, nonzero equal discovered/passed
counts, zero failed/skipped and no failing names. All five classification lists
are empty: there is no executable baseline against which to claim fixes or
regressions. Failure assertions remain in force; a head failure cannot use this
representation to pass.

Validation requires the standalone surface and exact assigned refs/arm heads,
proves each safe relative scaffold path absent at baseline and present at head,
checks the baseline tracked guard bytes/hash, and binds the plain launcher/guard
argv to the tracked configured command in both arms. It reproduces each actual
baseline attempt with `shell=False`, a30-second timeout and unchanged Git
footprint, matching actual exit78 and output digest. Allowed launchers are
`bash`, `sh` and `python3`; shell expressions and launcher flags cannot substitute
for the tracked guard. Never manufacture an unavailable baseline because tests
fail or tools are missing: the missing first scaffold must be established.
Ordinary executable baselines retain the existing sample and regression rules.
Unavailable-baseline output explicitly says comparison unavailable; it does not
claim that baseline tests passed. Identity, scope, containment, contamination and
both-arm read-only obligations still apply.

When `verdict` is `disputes_premise`, `premise_dispute` is required and carries
three fields: `claim`, `evidence` (both R5), and `spec_defect: true | false`
(R2, SPEC-ARGO-049) — the verifier's own explicit statement of whether the
dispute names a requirement or AC of *this spec* that is itself wrong or
unmeetable. This is the field Step 5c(e) routes on; it is not inferred by the
parent from the claim text, and the validator rejects a `disputes_premise`
verdict that omits it.

Classification is defined over sample sets, not totals — `any` is the union across
an arm's samples, `all` the intersection:

| Bucket | Definition | Meaning |
|---|---|---|
| `regressed` | `head_all − baseline_any` | fails in **every** head sample, in **no** baseline sample |
| `newly_flaky` | `(head_any − head_all) − baseline_any` | new intermittent failure — not a pass, not a deterministic regression |
| `flaky_observed` | `(head_any − head_all) ∪ ((baseline_any − baseline_all) ∩ head_any)` | pre-existing flake, still reproducing in some head sample; never a regression |
| `fixed` | `baseline_all − head_any` | fails in **every** baseline sample, in **no** head sample — a deterministic failure that is now deterministically gone |
| `flake_resolved` | `(baseline_any − baseline_all) − head_any` | an **intermittent** (not all-fail) baseline failure that reproduces in **zero** head samples — a flake that stopped reproducing, distinct from `fixed`'s all-fail precondition (BUG-024) |

`newly_flaky` exists so the multi-sample rule is not a one-way ratchet. Requiring
"fails in all head samples" alone would silently absolve an introduced race — a
60%-failure race clears a 5-sample all-fail bar 92% of the time. Report it; do not
merge on it without a decision.

`flake_resolved` exists because `fixed`'s `baseline_all − head_any` definition
requires a 100%-baseline-failure precondition that a genuinely intermittent flake
almost never satisfies at any practical sample count (BUG-024: a 13%-flake-rate
test clears a 30-sample all-fail bar with probability ~1e-27). `fixed` and
`flake_resolved` partition the same underlying signal — "failed at least once in
baseline, never in head" (`baseline_any − head_any`) — by whether the baseline
failure was total (`fixed`) or partial (`flake_resolved`); a name can never be in
both. `flaky_observed`'s second term is correspondingly narrowed to
`(baseline_any − baseline_all) ∩ head_any` — a partial baseline flake only stays
`flaky_observed` if it is still reproducing in at least one head sample; once
head_any goes to zero, it moves to `flake_resolved` instead of being silently
absorbed with no distinguishing signal. `flake_resolved` does not weaken
`regressed` or the 3x-minimum sampling rule (Gap Protocol stop-immediately
clause): it still requires the standard per-arm sample count to fire, per the
`need` check below, and it only ever removes failures from view, never adds one.

**d. Validate the verdict — this is the audit (R3/R4/R5).** One command; it recomputes
every classification from the submitted names and never trusts the verifier's arithmetic:

[Pinned in `.nightshift/guides/pinned-validator.md`: NIGHTSHIFT-VERDICT-VALIDATOR - byte-exact, not repeated here.]

[Pinned in `.nightshift/guides/pinned-validator.md`: the `GATE: reject` rule that follows the validator - byte-exact, not repeated here.]

**e. Route on the validated verdict.**

Before routing a validated `fail` to terminal blocking, use the managed
`verifier_feedback.py` boundary. Only a current, independently
produced failure (no `contamination`, or its R3 exposure rule met) with complete AC evidence and a clean footprint can create the
parent-signed packet. The parent selects exactly one remediation mode per round
(`resume_original` or `fresh_worker`), preserves the original authority, and
requires a newly independent verifier on the changed head before integration.
The bound is two rounds (`remediation_limit`, SPEC-266 resilience ladder): the
second runs only when the fresh valid failure's failed ACs are a strict subset of
the packet's, with a new packet and a new fresh verifier; a failure that is not a
strict subset, or any failure after the second round, exhausts the bounded path
(SPEC-411).
The verifier and remediation actor never communicate directly, mutate lifecycle,
merge, or self-accept.

Packet admission recomputes the containment binding from the parent-private exact
candidate revision, then requires the verdict's synthetic `head_commit` and opaque
`implementation_head_digest` to equal the dispatch plan and evidence. A legacy
failure verdict without the digest is rejected as `legacy_verdict_identity`.
After remediation, compare exact private Git revisions first, prepare a new
contained surface, validate its new identity pair, persist it, and only then
request the fresh verifier. Reducer events and replay keys use the digest, not the
Git object ID.

Invalid/contaminated verdicts create no packet and permit only one replacement
verifier on the unchanged head. Remediation or dispatch failure, unchanged head,
a second invalid verdict, or a fresh valid failure that earns no second round
(not a strict failed-AC subset, or the second round already spent) exhausts the
bounded path and resolves through controlled blocked policy. A valid
`disputes_premise` verdict is neither: it spends no replacement verifier or
remediation and the reducer hands it to the parent decision path below with the
verdict's `spec_defect` (terminal reason `premise_dispute`, next action
`parent_decision`); an incomplete dispute (no claim, evidence or boolean
`spec_defect`) is an invalid verdict. Record each actor attempt separately
from the parent delivery result via the configured SPEC-224 adapter. The typed
admission seam handles both sources without adding another lifecycle owner
(SPEC-235-001).
`implementer_blocked` is an attempt fact that opens a parent-owned assessment:
retain and hash-inventory the candidate, validate the closed diagnosis envelope,
classify mechanical evidence, use at most one read-only diagnostician for safe
uncertainty, and dispatch at most one bounded `resume_original` or
`fresh_specialist` repair. Reuse keyed effects after callback loss, polling, or
restart; never renew allowances on reconnect. A changed repair must pass a newly
independent verifier and the coordinator's serialized fresh-main integration
before delivery may close.

After the verdict validator has produced the auditable verdict, publish the
actual verification outcome exactly once. Map `pass` to `passed`, `fail` to
`failed`, and an unresolved or unauditable result to `unknown`; this optional
publication does not change the routing table below.

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event verification.completed --outcome "{VERIFICATION_OUTCOME}"
```

| `VERDICT` | Parent action |
|---|---|
| `pass` | continue to Step 6; check 5 of the evidence gate is satisfied |
| `fail` | do not merge; Step 6's controller-backed unblock path |
| `disputes_premise` with `premise_dispute.spec_defect: true` | **not a failure**, and never a merge on the verifier's authority. The verifier's own R2 field says a requirement or AC of *this spec* is wrong or unmeetable. Record the dispute verbatim in the run report and parent progress artifact, then submit any loosened AC to the independent `nightshift-ac-reviewer`, retain its valid `reports/<SPEC>/ac-review.json`, and add the approved old → new row to `## AC Amendments`; re-run the gate and continue to `done`. A veto leaves the expectation intact and routes to blocked/user authorization. The dispute is evidence for a parent decision, never the decision itself. |
| `disputes_premise` with `premise_dispute.spec_defect: false` | **not a failure, and not an unresolved spec expectation** (SPEC-ARGO-049 R1/R3). The verifier's own R2 field says no requirement or AC of this spec is in question — the dispute is against something else (an enforcement gate, a tool, a parent-level claim outside the spec). There is no spec expectation to amend, and `blocked`/`evidence_gap` stays reserved for a genuinely unresolved **spec** expectation (R3), so it does not apply here either. Record the dispute verbatim in the run report and the parent progress artifact, file it as follow-up work (a new spec or TODO item — cite the ID once created), and continue to the ordinary evidence gate: once the follow-up is filed, this verdict satisfies check 5 (Step 6). |
| missing / `GATE: reject` | treat as `evidence_gap`; do not merge |

Record the outcome in both the report and the lifecycle commit trailer
`Nightshift-Evidence-Verifier:` (Step 6). Canonical `record_metrics.py` reads a
fixed set of trailer keys and ignores unknown ones, so this trailer is durable and
greppable in git today but is **not** yet consumed into metrics.


**Runs resolved before this instruction existed have no recoverable count.** A future reader
(including `SPEC-ARGO-038-001`) must report those as `unavailable` — never estimate, reconstruct, or
backfill a number for them, no matter how plausible an estimate would be. Likewise, a pre-SPEC-ARGO-061
`self-verified` commit is not retroactively relabeled `self-verified-experimental` — Out of Scope
for SPEC-ARGO-061 explicitly forbids reclassifying prior sessions' self-verified resolutions.

### Structured native failures and setup recovery (SPEC-NS-KIT-160)

`suite-sample --output-dir <private>` persists full output and `.process.json`: arm, invocation identity, raw SHA-256, native exit, completed/unavailable state and independent count evidence.
Pytest names come from the final outer summary; nested failures remain diagnostics. Unittest subtest and Xcode assertion-event counts remain distinct from named failed cases; ambiguous membership or mixed formats remain gaps.
JUnit uses suite testcase members, never diagnostic elements. Missing/conflicting summaries, denied collection and native timeouts are unavailable, never completed samples or passes.
Raw entries may bind `native: {exit_code, timed_out, denied}`, `arm` and `invocation_identity`; legacy raw-only intake retains its existing contract.
Implementation/fixture/environment hypotheses require nonempty relative, hash-verified evidence under the evidence root; otherwise use inconclusive. Labels never establish causal controls or acceptance.
Persist `persist_setup_recovery(directory, identity=..., prerequisite=..., next_action=..., responsible_actor=...)`; name `setup-recovery.json` as existing `blocker_evidence` and keep timestamped invocation logs separate.
The first action/actor stays fixed for unchanged identity/prerequisite. Invalid prior evidence requires repair before retry; wording/log churn cannot reopen the fingerprint.
Only changed recorded identity/prerequisite enters `unblock_spec.prepare` and its existing bounded attempt ledger. This helper schedules no launch, adds no budget and grants no override.
Sampling is unchanged: normally one per arm; three for unexcused head failure, arm/sample disagreement, supported flakiness or unsupported launch failure. Diagnostic probes cannot replace samples, exits, controls or the independent verdict.

### Predeclared baseline corrections (BUG-NS-KIT-170)

Use `prepare_verifier_dispatch(..., expected_baseline_fix=...)` before execution for the exact declaration described in `pinned-briefs.md`; the public plan carries it under `sampling.expected_baseline_fix`. This adds no waiver, writer, lifecycle, integration or release authority.
Use `suite_required_samples(suite, plan=original_plan, footprint=both_arm_footprints)` after the actual configured pair; operational tuples additionally require every ordered `suites` member and separate `sampling_anchor`. Assembly and embedded/public validation receive that same trusted context and independently recheck tuple-wide eligibility; missing/altered approval, clean-member failures or collection gaps preserve escalation.
Eligibility requires complete collection/outcome proof and unchanged target Python test-file bytes with assertions. Trusted pytest observations support unchanged quiet/xdist commands; complete verbose native rows remain supported. Other runners or unverifiable edits retain the strict count; no silent suite narrowing is allowed.
The earlier SPEC-NS-KIT-160 sampling paragraph describes legacy plans; this opt-in is its sole narrowly proved baseline-only exception. One pair observes a correction and establishes no statistical determinism, future reliability or measured savings. AC derivation, containment, original receipts, remediation, serial exact-head integration, fresh-main and whole-kit release gates stay in force.

### Required authored deliverables: ordered intake (BUG-NS-KIT-166)

Generated handoff and manually copied suite/no-suite pinned briefs use the same
`NIGHTSHIFT-ORDERED-DELIVERABLE-INTAKE` block in `pinned-briefs.md`. Preserve it
verbatim. Before accessing substantive required-deliverable conclusions, the
verifier independently derives the relevant source behavior, test assertions
and actual command results from the exact assigned arms, preserving observations
outside the arms. Metadata/path existence and unrelated AC work do not establish
that derivation; target reads rather than searching outcome-bearing documents.
Then inspect the real contractual deliverable and its committed digest. This
instruction order adds no staged-access capability or content-free substitution.

Classify actual exposure honestly. Unavoidable/accidental early exposure remains
`before_derivation` with any capability/evidence gap; it cannot become a final
pass by relabelling. Supported late exposure is `required_deliverable /
after_derivation`. Keep original rejected evidence, exact identity and both-arm
read-only checks. Exposed failures still need independent native reproduction
and lead-only remediation. Assembly and strict final admission remain unchanged.

### Canonical hand-back packaging identity (SPEC-NS-KIT-162)

Before an expensive configured canonical suite, retain the supported
`release.py check-final-manifest` result for the final managed candidate. Treat
its manifest, payload and handoff digests as one binding, never as permission to
reuse a green result after edits. A mismatch stops launch until final edits and
explicit regeneration are complete. The helper is a packaging check; existing
whole-kit release validation and the sole serial integration owner remain in force.

### Verification economics summary at verification/recovery (SPEC-NS-KIT-183)

Opt-in full/small/recovery parents use `verification_economics.checkpoint`:
`status`, `reason_codes`, `decision`, `disposition`, `unmet_obligations` and scoped
`cumulative` measurements belong in the existing parent brief/progress/report.
See `run-3.md` § Opt-in verification economics at parent boundaries for setup,
finite fixtures and authority. `unblock_spec.prepare` / `resume_recovery` expose
the same summary before retry; pass `--economics-context <private-json>`.
`review_needed` stops automatic launch; retain original eligibility, failures and
unmet gates. Existing reuse/authority contracts, healthy operations, hard budgets,
default/opt-out behavior and distinct fresh-main remain unchanged.

Blocks/setup: ORCHESTRATOR.md.
