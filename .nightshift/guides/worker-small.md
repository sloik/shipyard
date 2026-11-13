Load when: a small-lane kickoff brief tells you to read this guide: a pre-bootstrapped worktree, a spec of about 4 ACs or fewer in one module.
Covers: the only LOOP.md steps a small-lane worker runs (Steps 4-5, 8, 9 and 12-14), the one report path, and the CHANGELOG/follow-up write rules.
Not here: the full loop, the parent's checklist (`kickoff.md`, "Small-spec lane"), verification and merge (parent-owned).
Requires: a worktree the parent already admitted, on its spec branch, with the spec ready; the brief's baseline commit and suite command.

# Small-lane worker guide (SPEC-NS-KIT-108)

The parent has already done startup, task selection and context loading for you; the brief names the spec, its `scope.write`, the suite command and any `devkb_required` files (read those
before your first edit). Do not re-run startup. Work only in this worktree. The spec's `scope.write` is binding.

Open `LOOP.md` only at the steps below, in this order. You never verify your own work for the parent:
independent verification and the merge-gate stay with the parent, so do not mark the spec `done`.

1. **Step 4 (test plan).** One short list: for each AC, the test that proves it and why it fails on the baseline.
2. **Step 5 (red tests).** Write the tests, run them on the baseline, confirm they fail for the right reason, and
   commit `[<spec-id>] test: add tests (red)`. Keep the failing output: it is the red proof.
3. **Step 8 (implement).** Smallest change that makes them pass; run lint/type/format as the config names them.
4. **Step 9 (validate).** Run the suite command from the brief once (`commands.test_fast` is acceptable for the
   hand-back check). Fix and re-run only after a code change.
5. **Step 12 (commit and changelog).** Commit with `[<spec-id>] <type>: <summary>`; the CHANGELOG rule is below.
6. **Step 13 (metrics).** Nothing to do; the post-commit hook emits the row.
7. **Step 14 (report).** Write the report at the path below, with the headings the brief lists.

## The report path

`reports/YYYY-MM-DD-nightshift-report-<SPEC-ID>.md`, relative to the project's reports directory
(`.nightshift/reports/` in an installed project, `canonical/reports/` in the kit repository). This is the path
LOOP Step 14 and the kickoff brief both name; never write the bare date-only file. The report carries `## Summary`,
`## Changes`, `## Verification`, an AC checklist, `## Blocked Specs`, `## Open Questions` and `## Report Action Log`
(`None` when empty). The AC checklist must list the exact test names or commands, because the verifier recomputes them.

## Write scope: CHANGELOG and follow-ups

- `CHANGELOG.md` and `release-manifest.json` pass the scope guard only when your `scope.write` names a managed
  canonical-payload file; scope permission is not operation ownership. See `ORCHESTRATOR.md` § Serialized integration
  queue and fresh-main validation for the existing authority. On broker-owned routes, workers return relative-path
  intents for parent-owned CHANGELOG/version/release-handoff surfaces and their manifest reseal; do not edit or reseal
  them. Only an explicit route brief naming surface, operation and existing authority permits a worker-owned mechanical
  operation on another route. Missing or conflicting ownership is a bounded issue to the parent; leave the surface
  untouched. An authorized CHANGELOG line stays under the current unreleased entry and never bumps `kit_version`;
  perform only the expressly assigned mechanical operation.
- `followup_processor.py` is not worker-written output. If you find a suggestion, put it in the report's
  `## Open Questions`; the parent runs the processor once at terminal resolution. Its records land in the
  private run and decision stores, outside your scope, and you never hand-write them.
- Evidence you produce goes under `reports/` (always writable); anything else outside `scope.write` is a
  `worker-blocked` report, not an edit.

## Hand back

Commit everything, leave the branch tip as the candidate, and reply with the branch, the tip commit and the report
path. The parent verifies that exact tip. If you push another commit afterwards, the parent re-verifies.

## Parent verification economics summary (SPEC-NS-KIT-183)

The opted-in small parent uses the same `verification_economics.checkpoint` summary as the full parent and recovery: `status`, `reason_codes`,
`decision`, `disposition`, `unmet_obligations` and separately scoped `cumulative` measurements. Record it in the existing brief, progress and report;
setup/finite fixtures and owner disposition live in `run-3.md` § Opt-in verification economics at parent boundaries. `review_needed` stops the next
automatic launch, never becomes blocked/Done or a mandatory-gate waiver. Workers supply evidence; the parent owns disposition, existing eligible
reuse, lifecycle/integration and distinct fresh-main. No extra suite runs solely for telemetry, healthy-operation cancellation or numeric defaults.
The default/opt-out route keeps its existing launch behavior and gate inventory.

## Observational helper capture (SPEC-NS-KIT-168)

At every ordinary handoff/report closure, always request newly authored helper metadata. Consult supported APIs, classify available helpers and hand
the explicit list to the parent. The parent alone calls `run_tooling.capture_best_effort` (or `run_tooling.py capture`); capture is metadata/digests
only and never delays correctness, recovery, Done or cleanup. Use `not_reported` without a reliable list; `none_authored` requires an explicit
declaration. No temporary-root scan, source execution/copy, forced suite or historical census. Raw snapshots need separate owner approval. Review
records one of generic_candidate, project_local, experiment, existing_supported or defect_adapter; single-context generic potential stays proposed.
Eligibility requires hash-bound second-context evidence and owner/capability/privacy/check/scope fields with no material open choice. A recommendation
grants no execution, installation or release.
