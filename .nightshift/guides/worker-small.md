Load when: a small-lane kickoff brief tells you to read this guide: a pre-bootstrapped worktree, a spec of about 4 ACs or fewer in one module.
Covers: the only LOOP.md steps a small-lane worker runs (Steps 4-5, 8, 9 and 12-14), the one report path, and the CHANGELOG/follow-up write rules.
Not here: the full loop, the parent's checklist (`kickoff.md`, "Small-spec lane"), verification and merge (parent-owned).
Requires: a worktree the parent already admitted, on its spec branch, with the spec ready; the brief's baseline commit and suite command.

# Small-lane worker guide (SPEC-NS-KIT-108)

The parent has already done startup, task selection and context loading for you; the brief names the spec,
its `scope.write`, the suite command and any `devkb_required` files (read those before your first edit).
Do not re-run startup. Work only in this worktree. The spec's `scope.write` is binding.

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

- `CHANGELOG.md` and `release-manifest.json` are yours to edit only when your `scope.write` names a managed
  canonical-payload file; the scope guard then allows both implicitly. A spec that touches no managed file writes
  neither. The CHANGELOG line goes under the current unreleased entry, never bumps `kit_version`, and a managed
  edit is followed by one `release.write_manifest` reseal as the brief says.
- `followup_processor.py` is not worker-written output. If you find a suggestion, put it in the report's
  `## Open Questions`; the parent runs the processor once at terminal resolution. Its records land in the
  private run and decision stores, outside your scope, and you never hand-write them.
- Evidence you produce goes under `reports/` (always writable); anything else outside `scope.write` is a
  `worker-blocked` report, not an edit.

## Hand back

Commit everything, leave the branch tip as the candidate, and reply with the branch, the tip commit and the report
path. The parent verifies that exact tip. If you push another commit afterwards, the parent re-verifies.
