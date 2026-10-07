Load when: you run `/nightshift run` or `/nightshift kickoff` and have reached the steps listed under Covers.
Covers: part 7 of 8 of the run procedure: Step 6: Post-run resolution; within: Completion notification is a terminal-resolution trigger; Parent tool-call tally (mandatory — R1/R2, SPEC-ARGO-059); Evidence gate (all seven must pass to merge); If all seven pass → merge and clean up; BUG-017 — one contiguous trailer paragraph, no exceptions; Verification timing instrumentation (SPEC-NS-KIT-002-001, additive); Terminal-trailer correction on a shared branch (SPEC-275).
Not here: spec authoring (`/nightshift spec`), recovery of a blocked spec (`unblock.md`); the run's pinned executable blocks are in `pinned-briefs.md`, `pinned-checks.md` and `pinned-validator.md`.
Requires: a ready spec in an installed project; read the parts in order: `run.md`, `run-2.md`, `run-3.md`, `run-4.md`, `run-5.md`, `run-6.md`, `run-7.md`, `run-8.md`.

# Run guide, part 7 of 8

### Step 6: Post-run resolution

When the agent completes, run **Step 5c first** — dispatch the verifier and validate its
verdict — then resolve the run autonomously using the evidence gate below. Do **not**
offer merge/discard choices to the user, and do **not** re-derive the verifier's evidence
yourself; make the decision from the validated verdict.

**Completion notification is a terminal-resolution trigger.** On receipt, the
parent immediately records `terminal_resolution: evidence_gate_running` and its
start timestamp in the parent progress artifact, stops the watchdog, and executes
this Step 6. `awaiting parent integration` is not a permitted steady state: it is
only the in-process label while the evidence gate is running. The same completion
event must produce one terminal result (`done` or `blocked`) and record elapsed
resolution time before the parent becomes idle; it must never wait for a human
status ping.

A run whose result receipt is `NS-MPI-RELEASE-SUPERSEDED` resolves to the terminal outcome `superseded`
(SPEC-NS-KIT-007): no merge or cleanup, branch and worktree preserved, the spec returned to `ready` through
a status-store transition citing the attempt artifact; re-admit and re-run, never accept the old candidate.
See `guides/kickoff.md`.

> Because the run was launched in the background (Step 5), read the worktree `<branch>` and `<path>` used in the commands below from the **completion notification's result payload** — there is no foreground return value. Also `TaskStop` the liveness watchdog now if it is still armed.

**Parent tool-call tally (mandatory — R1/R2, SPEC-ARGO-059).** Every completed kickoff resolution
records the parent coordinator's own tool-call count for this pass in a git-tracked artifact — not
optional, not left to discretion. **Counted:** every tool call the parent itself makes, starting
immediately after launching the run agent (Step 5) and ending at this pass's terminal resolution
(the `done` or `blocked` lifecycle commit below) — monitoring, the Step 5c verifier dispatch and
audit, the evidence gate, and the resolution commit itself all count. **Not counted:** anything the
launched run worker or the Step 5c verifier did inside their own agent invocations — the worker's
count is already captured separately (the Agent completion notification's `tool_uses` field).
There is no API-level ground truth to check this against: it is necessarily a self-tally the parent
keeps and reports as it goes, not an independently audited number — state it as counted, never
rounded or estimated. Record it in the terminal lifecycle commit (`done` or `blocked`, both below,
`commit-backed` policy only — see note there for `private-local`) as two trailers, never only in the
report or the gitignored progress artifact:

```
Nightshift-Parent-Tool-Calls: <N>
Nightshift-Resolution-Kind: <verifier-dispatched|self-verified|self-verified-experimental>
```

`Nightshift-Resolution-Kind` has three values, and a bare guess is never acceptable — record what
this pass actually did (SPEC-ARGO-061 R1/R3):

- **`verifier-dispatched`** — Step 5c's dispatch step was actually executed for this pass: an
  independent `nightshift-verifier` agent was launched. **The only normal path**, since Step 5c is
  mandatory for every spec, including docs/protocol-type specs with no test suite (SPEC-ARGO-061 R1
  decision; the (a-alt) brief in Step 5c is what makes that practical, not an excuse to skip
  dispatch). This value covers **every** outcome of a real dispatch attempt, not only a clean
  `pass` — a `fail` verdict, a `GATE: reject` (unauditable verdict), or an agent that launched but
  produced no usable verdict are still `verifier-dispatched`; the *quality* of what dispatch
  produced is recorded separately, via `Nightshift-Evidence-Verifier` and `Nightshift-Blocker-Class:
  evidence_gap` on the resulting `blocked` commit, never by reaching for a different
  `Resolution-Kind` value. `Resolution-Kind` answers one question only — did Step 5c's dispatch
  mechanism run for this pass, or was it deliberately bypassed — so a legitimate `blocked`
  resolution after a failed or unauditable verdict is `verifier-dispatched`, same as a `done` one.
  The one case dispatch never ran at all — the verifier agent's *launch itself* was rejected
  (SPEC-ARGO-037's `launch_failure` outcome, Step 5's launch-rejection branch) — is still recorded
  as `verifier-dispatched` here too: the parent attempted Step 5c's mandatory dispatch as required,
  the launch failure is what the controller-backed unblock/retry path and the SPEC-ARGO-037 outcome
  row exist to capture, and it is not evidence of a bypassed Step 5c the way a self-verified value
  would be.
- **`self-verified-experimental`** — dispatch was **deliberately** not performed for this pass,
  solely because this run was pre-designated, before it started, as a bounded comparison sample for
  a self-verified-arm measurement. This is the **only** sanctioned use of self-verification going
  forward — narrow, pre-declared, and never opportunistic ("this one looked easy to self-check" is
  not a qualifying reason). A pass using this value MUST also carry a
  `Nightshift-Experimental-Sample-For: <designating-spec-id>` trailer and a one-line reason in the
  commit body naming which comparison pair it fills. The originating designation was
  `SPEC-ARGO-038-001` (project-local, Argo Home); **`SPEC-ARGO-038-001` is superseded by canonical
  `SPEC-223`** (`canonical/specs/SPEC-223-measure-verified-versus-self-verified-context-spend.md`),
  which is itself currently blocked pending exactly this sample type. Before designating a new
  sample, read the currently-live designating spec's own file for the exact count/status required —
  do not assume `SPEC-ARGO-038-001` is still the live target, and do not assume `SPEC-223` will
  remain the only legitimate designator going forward; a later spec may supersede it in turn.
  `SPEC-ARGO-038-001` remains the historical discovery/partial-evidence record and is not deleted
  from this text.
- **`self-verified`** (without `-experimental`) — reserved for a pass where this convention did not
  exist yet or was not followed. **As of SPEC-ARGO-061, a bare `self-verified` on any new commit is
  itself a protocol violation, not a legitimate outcome** — R1's decision closed the "rare case
  dispatch could not happen" carve-out that used to justify it. If dispatch genuinely cannot happen
  (e.g. verifier agent launch failure), that is a `launch_failure` under the SPEC-ARGO-037 outcome
  recording and the controller-backed unblock/retry path — it does not fall back to the parent
  self-verifying and writing plain `self-verified`. A future reader must not confuse a bare
  `self-verified` commit with a deliberate `self-verified-experimental` one: the trailer value is
  the whole distinction, and the two are never interchangeable or backfillable into each other.

**Runs resolved before this instruction existed have no recoverable count.** A future reader
(including `SPEC-ARGO-038-001`) must report those as `unavailable` — never estimate, reconstruct, or
backfill a number for them, no matter how plausible an estimate would be. Likewise, a pre-SPEC-ARGO-061
`self-verified` commit is not retroactively relabeled `self-verified-experimental` — Out of Scope
for SPEC-ARGO-061 explicitly forbids reclassifying prior sessions' self-verified resolutions.

**Evidence gate (all seven must pass to merge):**

1. **Report exists** — `reports/YYYY-MM-DD-nightshift-report-<SPEC-ID>.md` (the Step 14 path) is present in the worktree.
2. **Tests passed** — report contains no `❌` on test-result lines.
3. **Code changed** — `git diff main..<branch>` has changes to files outside `reports/`.
4. **ACs covered** — report AC checklist has zero `❌` items (⚠️ with explanation is acceptable).
5. **Verifier verdict** — a Step 5c verdict exists, the validator printed
   `GATE: accept`, and either `VERDICT` is `pass`, or `VERDICT` is
   `disputes_premise` with `premise_dispute.spec_defect: false` and the
   dispute has been filed as follow-up work per Step 5c(e). Checks 1–4 read
   the run's *own* report; check 5 is the only one sourced independently of
   the author, which is why it is the one that must be dispatched, not
   re-derived by the parent. A `disputes_premise` verdict with
   `premise_dispute.spec_defect: true` does not satisfy check 5 and does not
   fail it — resolve the premise per Step 5c(e) first (it routes to
   `blocked`, per R3), then re-evaluate the gate. **The one sanctioned
   substitute for check 5** is a pass whose `Nightshift-Resolution-Kind` will be
   `self-verified-experimental` (SPEC-ARGO-061 R3): no Step 5c verdict exists
   because dispatch was deliberately skipped for a pre-designated sampling run
   (originally `SPEC-ARGO-038-001`, now superseded by canonical `SPEC-223` — see
   the Resolution-Kind section above for the currently-live designator), so the
   parent evaluates checks 1–4 and the ACs directly instead, and records
   that substitution via the trailer pair, never by leaving check 5 silently
   unaddressed. This is not available for a bare `self-verified` outcome — that
   value records a violation, not a passing gate.
6. **Scope** (SPEC-300-002 R1) — every path in `git diff --name-only
   <baseline>..<branch>` (added, modified, deleted, both sides of a rename)
   is classified by `scope_guard.py` against the spec's declared write scope,
   read from the spec file **on the configured main branch** — never the
   worker branch or the working tree (SPEC-300 R3). Runs after check 5, before
   the merge decision. Any `DENY` fails the gate. Skip this check, recording
   `Nightshift-Scope-Check: not_run` and a report warning naming the missing
   file, **only** when `scope_guard.py` is absent from the install — never
   because the spec has no `scope:` (R9): an absent `scope:` still resolves to
   the project-root default, which check 6 evaluates like any other scope.

   Run the embedded gate script against the candidate branch:

[Pinned in `.nightshift/guides/pinned-checks.md`: NIGHTSHIFT-SCOPE-GATE - byte-exact, not repeated here.]

   `SCOPE-CHECK: clean` and `SCOPE-CHECK: amended` both satisfy check 6 (an
   amendment is a human-approved widening, not a violation) and set
   `Nightshift-Scope-Check` to that exact value on the terminal `done` commit.
   `SCOPE-CHECK: violated` fails check 6; its `REASON:` line — one
   `<repo-relative-path> (<reason-code>)` entry per offending path,
   comma-separated — becomes both the spec's `block_reason` (R2) and
   `unblock_spec.py`'s only parseable record of which paths still need an
   amendment (R8). `SCOPE-CHECK: not_run` satisfies check 6 mechanically (R9)
   but is still recorded verbatim, never silently folded into `clean`.
7. **Head bound** (BUG-NS-KIT-107) — the merge target is the verified revision, never a
   branch name. `<candidate-sha>` is the exact `--head` given to `prepare-dispatch` (the
   `worker_done_head` recorded at the `TERMINAL` wake). Run `python3 .nightshift/verification_report.py
   merge-gate --plan <plan.json> --evidence <verifier-surface.json> --verdict <verdict.json>
   --branch <branch> --candidate <candidate-sha>` (from main's copy of the kit, like
   `assemble-verdict`); `MERGE-GATE: bound <sha>` satisfies check 7. `MERGE-GATE: stale_head
   <detail>` — the branch moved after the verified revision, or a digest or `head_commit` was
   altered — fails it: record `stale_head` as the redispatch reason, then re-dispatch on the
   new tip (Step 5c) or mark `blocked`. Never merge, not even "for now".

**If all seven pass → merge and clean up:**

```bash
git merge --no-ff <candidate-sha>
git worktree remove <path>
git branch -d <branch>
```

In `commit-backed`, first record the SPEC-291 transition artifact for the
evidence-gated `in_progress -> done` transition about to be made — its reason
synthesizes from the run ID, no prose required — *before* flipping status and
committing, so the artifact file exists on disk to be staged in the same
commit (writing it after would leave it untracked):
```bash
python3 .nightshift/spec_artifacts.py record-transition <spec-file> \
  --from in_progress --to done --run-id <started-run-id>
```

Resolve terminal status on main. In `commit-backed`, flip to `done` and
commit, staging both the spec file and its `reports/<spec-id>/artifacts/`
directory (the sibling of the specs directory's `reports/` —
`.nightshift/reports/...` deployed, `canonical/reports/...` in this kit
repo — not bare `reports/` from the project root):
```
chore: mark <spec-id> done

Nightshift-Evidence-Report: pass
Nightshift-Evidence-Tests: pass
Nightshift-Evidence-Code: pass
Nightshift-Evidence-ACs: pass
Nightshift-Evidence-Verifier: <pass|disputes_premise>
Nightshift-Blocker-Class: none
Nightshift-Blocker-Scope: none
Nightshift-Scope-Check: <clean|amended|not_run>
Nightshift-Merged-Revision: <candidate-sha>
Nightshift-Unblock-Attempts: 0
Nightshift-Unblock-Limit: 1
Nightshift-Unblock-Rung: <0|1|2|3|4|5>
Nightshift-Parent-Tool-Calls: <N>
Nightshift-Resolution-Kind: <verifier-dispatched|self-verified|self-verified-experimental>
Nightshift-Experimental-Sample-For: <currently-live designating spec (e.g. canonical SPEC-223, which supersedes the original SPEC-ARGO-038-001 designation — read that spec's own file for the live target before writing this trailer) | omit unless Resolution-Kind is self-verified-experimental>
```

**Lane event (SPEC-NS-KIT-108).** With this commit, emit the run's lane event: `python3 .nightshift/loop_events.py lane ... --lane full` (`--lane small` under the small-spec checklist); the arguments and counters are in `kickoff.md` § Lane telemetry. Same `<N>` as the trailer above.

**BUG-017 — one contiguous trailer paragraph, no exceptions.** If this session's
attribution convention also requires trailers such as `Co-Authored-By:` or
`Claude-Session:` on this commit, append them as additional lines **inside this
same block**, directly below `Nightshift-Experimental-Sample-For`/`Nightshift-Resolution-Kind`
— zero blank lines between any two trailer lines. Never put them in a second
paragraph after a blank line, and never glue this block directly onto free-form
prose with no blank line separating them either. Git's trailer parser
(`%(trailers:...)`, which `record_metrics.py` depends on) recognizes only the
single, last, blank-line-delimited paragraph of the commit message, and only
when every line in it is trailer-shaped — a second trailer-shaped paragraph
after this one silently hides this entire block from every `Nightshift-*`
reader, and prose glued onto this block with no preceding blank line hides
everything, including the attribution trailers. The required shape is exactly:
one blank line between the free-form body and the trailer block, then every
trailer — `Nightshift-*` and attribution alike — as one uninterrupted run of
`Key: value` lines.

**Verification timing instrumentation (SPEC-NS-KIT-002-001, additive).** Observation only —
it never relaxes any gate above. The parent records, with the controller's own clock, one
record per verifier dispatch and one per coordination stage, then adds the printed trailers to
the contiguous block above:

```bash
python3 .nightshift/record_metrics.py --record-timing dispatch --spec-id <spec-id> \
  --metrics-dir .nightshift/metrics --timing-json \
  '{"dispatch":1,"started_at":"<utc>","ended_at":"<utc>","outcome":"pass|fail|no_verdict|rejected|other","redispatch_reason":null}'
python3 .nightshift/record_metrics.py --record-timing stage --spec-id <spec-id> \
  --metrics-dir .nightshift/metrics --timing-json '{"stage":"verifier","seconds":<n>|"unavailable"}'
python3 .nightshift/record_metrics.py --render-timing-trailers --spec-id <spec-id> \
  --metrics-dir .nightshift/metrics   # prints Nightshift-Verifier-Dispatch / -Stage-Timing / -Verification-Duration-S
```

Dispatch 1 has `redispatch_reason: null`; every later dispatch of the same spec states why from
the closed set `defect_fail | unauditable_verdict | contamination | surface_env_gap | stale_head |
budget_expiry | other`. Stages: `worker_implementation`, `surface_preparation`, `verifier`,
`post_verdict_gates` (and `post_verdict_scope`, `post_verdict_terminal_integrity`,
`post_verdict_fresh_main`), `merge_cleanup`, `coordination_gate_wait`, `cleanup_diagnostic`. A
value you cannot measure is recorded as `"unavailable"`, never `0`. Wrap each configured suite
run with `python3 .nightshift/verification_report.py suite-sample --spec-id <spec-id> --arm
<arm> --suite <id> --sample <n> [--xcode] -- <exact suite command>` to record wall time,
executed/skipped counts and 1-minute load at start and end; the command's exit code passes
through unchanged. These records land in the metrics row (`verification`, and
`phases.completion_verification.duration_s`); `verification_report.py throughput-report
--metrics-dir [LABEL=]<dir>` prints per-project medians and distributions.

`Nightshift-Evidence-Verifier` records the validated `VERDICT` value verbatim —
`disputes_premise` here only ever means `premise_dispute.spec_defect: false`
(SPEC-ARGO-049 R1), since `spec_defect: true` cannot satisfy check 5 (it routes
to `blocked`). When it is `disputes_premise`, cite the filed follow-up
spec/TODO ID in the commit body or the run report, not just in the trailer.

If a controller-backed recovery was required, set
`Nightshift-Unblock-Attempts: 1`; the other successful-gate trailers stay the
same. These trailers are consumed mechanically by `record_metrics.py
--mark-commit`. The matching `in_progress` commit becomes the stable `run_id`,
so a blocked transition and a later recovery remain one analyzable run.
Set `Nightshift-Unblock-Rung` to `0` when no drive-to-done rung was entered, or
to the final entered rung (`1` through `5`) when the ladder ran.

**Terminal-trailer correction on a shared branch (SPEC-275).** Never use `git
commit --amend` to repair a terminal trailer on a shared branch: a concurrent
writer may have advanced `HEAD`, and amend would rewrite that writer's commit.
Instead create a separate correction commit with the corrected trailers and a
subject that does **not** match `MARK_COMMIT_RE`, then explicitly run
`record_metrics.py --correct-commit <bad-terminal-sha> --repo <project-root>`.
The post-commit hook cannot invoke this path and the existing metrics row is
patched in place; no second `chore: mark ...` transition is created. If an amend
is otherwise permitted, first run `record_metrics.py --verify-amend-head
<captured-40-character-sha> --repo <project-root>` using the exact SHA captured
immediately after this session's own prior commit. A mismatch is a hard stop. If
you discover that another session's commit was already rewritten, stop writing
and hand the choice to that commit's owner; do not attempt a compensating rewrite.

In `private-local`, do not make a lifecycle commit. After the same evidence gate
and serialized application merge, call `transition_private_state(..., "done",
run_id=<started-run-id>, owner="coordinator", assigned_spec=<spec-id>)`. Derive
resolution metrics with `record_metrics.derive_local_resolution`; it must resolve
the same durable run without searching Git history. `Nightshift-Parent-Tool-Calls` /
`Nightshift-Resolution-Kind` are commit trailers and R2 requires the artifact to be
git-tracked, so this instrumentation does not apply under `private-local` today —
recording the tally there needs its own private-state field, out of scope for
SPEC-ARGO-059. Run the SPEC-291 `record-transition` command above regardless of
mode — the artifact lives under `reports/<spec-id>/artifacts/`, a spec-side,
git-tracked record independent of which lifecycle-checkpoint proof was used.

Tell the user: spec ID, what landed, test count, report path. One paragraph.

Record `terminal_resolution: done` and `terminal_resolution_elapsed_s` in the
parent progress artifact only after the merge, cleanup, and durable terminal
state have all succeeded.

After that durable `done` state exists, publish the terminal fact and do not
wait for its optional consumer:

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event run.completed --outcome passed
```

**If check 6 (scope) fails → block directly; do not enter the controller-backed
ladder automatically (SPEC-300-002 R2).** A scope violation is a
human-decided class, not a mechanical recovery: skip straight to "block and
escalate" below with `blocker_class: scope_violation`,
`blocker_scope: out_of_scope`, `block_reason` set to check 6's `REASON:` line
(one `<path> (<reason-code>)` entry per offending path), and
`unblock_condition: scope amendment approved on main, or offending paths
removed from the branch`. Do not call `unblock_spec.py prepare` as part of
this automatic terminal resolution — a human adds the `## Scope Amendments`
row on main first; only then may `unblock_spec.py prepare` be invoked (by a
human or a later pass) and return eligible for rung 1 (R8). A worker that
itself returned `worker-blocked` with a `## Scope Blockers` report section
(path, reason, proposed scope change) is resolved exactly this way too — copy
`block_reason` verbatim from that section, and never apply the worker's
proposed scope change on its behalf (R7); the parent is not a scope
authority.

