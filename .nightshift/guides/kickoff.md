Load when: you run `/nightshift kickoff [spec-id]`, the parent-monitored wrapper around `/nightshift run`.
Covers: the receipt validity window (24 h), what the parent kickoff agent does and must not do, the small-spec lane checklist and lane telemetry, and the platform-neutral delegation wording.
Not here: the run steps themselves (`run.md` and its continuation guides) and the terminal-integrity rule (kept in SKILL.md).
Requires: `.nightshift/guides/run.md`; the parent's retained installation admission receipt.

# Kickoff guide

**The retained receipt is only valid for `MAX_RECEIPT_AGE` (24 h) after
admission (SPEC-387).** A kickoff run that outlives 24 h will have its
terminal-integrity check reject the retained receipt as stale — reported as
indeterminate `NS-MPI-RECEIPT-INVALID` with a `receipt_check.check == "stale"`
field carrying the observed age and the 24 h limit, never as a duplicate
contradiction. As with any indeterminate/deny result, the parent preserves
the worker branch/worktree exactly as above; it must never accept this run's
result against a freshly obtained admission — that "fresh admission is not a
valid replacement" rule above applies here too. The remedy is to re-admit
(a genuinely fresh installation admission and receipt) and re-run the spec
from that admission, so its own terminal-integrity check falls inside the
24 h window on its own run. Never regenerate or backdate an admission to
retroactively cover this run's already-changed bytes — that would defeat the
receipt's binding to the exact admitted artifact.

## Two receipts and the superseded close (SPEC-NS-KIT-007)

The kickoff takes two receipts, both retained by the parent and neither replaceable by a later admission:

- **Result receipt**, admitted against the worker worktree's install (`<worktree>/.nightshift`, the
  coordinator's `_worker_install_root`) at launch, once the worktree exists. It is checked there at
  terminal, never against the main checkout, so another session's sealed release on main cannot hit it.
  `python3 .nightshift/run_validation.py ... --integrity-install <worktree>/.nightshift
  --integrity-receipt <ref> --integrity-receipt-sha256 <sha> --run-id <run>` passes that same worker install.
- **Control-plane receipt**, admitted against the parent's own install (`.nightshift`, no spec id) at launch.

Resolve a terminal check in this order, control plane first:

1. A control-plane `NS-MPI-RELEASE-SUPERSEDED` means a sealed release landed after launch. Take exactly one
   fresh shared admission against the parent install and re-check once; any second failure is a
   control-plane failure and stops integration. The result receipt is never re-admitted here.
2. A result-receipt `NS-MPI-RELEASE-SUPERSEDED` ends the run with outcome `superseded`: no merge, no
   cleanup, branch and worktree preserved, the spec returned to `ready` by a status-store transition
   record citing the attempt artifact (`acceptance/attempts/<invocation>-<sha>.json`), then a new
   admission and a new run. The old candidate is never accepted under the new receipt.
3. `receipt_check.check == "stored-result"` is a read-back of an earlier decision. With a deny current
   code it is handled exactly as that deny; with `allow` it is logged (artifact, `prior_attempts`) and accepted.

A fleet project with a single-install layout has no separate worker install, so it takes path 2.

Use this command when a board-copied prompt or human explicitly wants a parent
agent to start and monitor a Nightshift run without doing implementation work.

`/nightshift kickoff <spec-id>` is a wrapper around `/nightshift run <spec-id>`
with `kickoff_parent: true`.

The parent kickoff agent:
- invokes the `/nightshift run` flow below,
- resolves the explicit state policy and records `in_progress` on main before launch
  (commit-backed lifecycle commit or private-local durable event),
- launches or coordinates the run/orchestrator agent,
- injects the **Kickoff Parent Context** section into the launched agent brief,
- monitors progress while the run is active,
- dispatches an independent `nightshift-verifier` when the run resolves and audits
  its structured verdict with the Step 5c validator, rather than re-deriving the
  evidence in its own context,
- autonomously resolves the run at completion: verifies evidence, merges and
  cleans up if sufficient, or invokes the controller-backed unblock protocol
  before a terminal blocked escalation.

The parent kickoff agent does **not** implement, research, validate, or code the
spec directly. The run/orchestrator agent owns Nightshift startup, instruction
packet generation, context loading, implementation, validation, metrics, reports,
and commits.

This wording is intentionally platform-neutral. In Claude, use the available
Agent/subagent mechanism. In Codex, use the available agent/delegation mechanism.
If no subagent mechanism is available, report that limitation before falling back
to inline execution.

## Small-spec lane (SPEC-NS-KIT-108)

A spec is small-lane eligible when it has **at most 4 ACs**, changes **one module** (its `scope.write` is one
module plus its tests and the spec's own evidence), and has **no managed-payload change beyond that module's own
edit, the CHANGELOG line and the mechanical consequences of that edit** (the `release.write_manifest` reseal and,
in the kit repository, the fixture re-record it forces); adding, removing or renaming a managed file, or touching
an enrolment list, makes it a full-lane spec. Anything else uses the full flow above. The lane trims paperwork, never a gate: head binding, scope, terminal integrity
and independent verification are identical in both lanes.

For both full and small lanes, scope permission is not operation ownership. Resolve operation ownership in the
explicit route brief under existing authority (`ORCHESTRATOR.md` § Serialized integration queue and fresh-main
validation). On broker-owned routes, workers return relative-path intents for parent-owned CHANGELOG/version/
release-handoff surfaces and their manifest reseal; workers do not edit or reseal them. A legitimate worker-owned
mechanical operation on another route names its surface and operation explicitly. Missing or conflicting ownership
is a bounded issue to the parent before edits, not an implicit transfer of authority.

The worker brief for this lane is one page: the spec path, its `scope.write`, explicit operation ownership
(parent-owned intents or expressly assigned worker operations), the baseline commit, the exact suite
command, the report path, and the line "Read `.nightshift/guides/worker-small.md` instead of LOOP.md". It keeps the
heartbeat file path and drops the long Kickoff Parent Context text.

Condensed parent checklist, in order (the run guides give the detail of each command):

1. Take the two receipts and record `in_progress` (see above); create the worktree; launch the worker with the brief.
2. On `TERMINAL`, read the branch tip once. That sha is the candidate for everything below.
3. Run the scope gate against the candidate (`scope_guard.py`, run-7 check 6).
4. **Independent verification is mandatory.** `prepare-dispatch` with `--head <candidate-sha>`, dispatch one
   `nightshift-verifier`, then `assemble-verdict` and `validate-verdict` until the validator prints `GATE: accept`.
   The parent never re-derives the evidence itself and never substitutes a self-check.
   If the spec was amended on main after the candidate was built, re-run `prepare-dispatch` with `--contract-ref main` and the same `--head`; do not commit main's spec onto the candidate to refresh the contract.
5. Run the terminal-integrity check with the retained receipts (control plane first, as above).
6. **The merge-gate check is mandatory.** `verification_report.py merge-gate --plan --evidence --verdict --branch
   --candidate <candidate-sha>` must print `MERGE-GATE: bound <sha>`; merge exactly that sha, never the branch name.
   `stale_head` means re-verify the new tip (`stale_head` redispatch reason).
   After the exact merge, complete the existing fresh-main validation; a failure enters the same sole owner's
   settlement before integration resumes (GIT.md).
   Before merging, run `python3 release.py finding-floor` on the candidate; exit 1 refuses the merge.
7. Record `done` (transition artifact and trailers, `followup_processor.py` once, cleanup) and emit the lane event.
   Build the trailers with `record_metrics.py --commit-terminal` (BUG-NS-KIT-139).
   Before the done commit run `spec_artifacts.py untracked-refs <spec-file>`: commit its `outside` paths first, stage its `stage_with_done` paths in the done commit.

## Lane telemetry (both lanes)

Every kickoff records which lane it used, once, at terminal resolution, through the run event log
(`loop_events.py`, event `lane_recorded`); installs report the comparison with the existing
`verification_report.py throughput-report --metrics-dir .nightshift/metrics`, so no further release is needed.

```bash
python3 .nightshift/loop_events.py lane --run-id <run-id> --spec-id <spec-id> --lane <small|full> \
  --parent-tool-calls <N|unavailable> --worker-wall-s <S|unavailable> \
  --verifier-wall-s <S|unavailable> --verifier-dispatches <N> [--redispatch-reason <reason> ...]
```

`<N>` is the same parent tool-call count as the `Nightshift-Parent-Tool-Calls` trailer; `worker-wall-s` runs from worker
launch to `TERMINAL`; `verifier-wall-s` is the sum of the dispatch durations recorded with
`record_metrics.py --record-timing dispatch`; each re-dispatch adds one reason from that command's closed list. A
value the parent could not measure is `unavailable`, never 0.

Before implementation, normal instruction apply/coordinator admission checks trusted external inputs (SPEC-NS-KIT-175); follow SPEC-GUIDE.md § Required external input readiness. Exit0 alone is not eligibility; repair setup before a new run, never replace its receipt.
