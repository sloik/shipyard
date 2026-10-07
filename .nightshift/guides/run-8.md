Load when: you run `/nightshift run` or `/nightshift kickoff` and have reached the steps listed under Covers.
Covers: part 8 of 8 of the run procedure: Step 7: Process suggested follow-up specs; within: If controller recovery fails or cannot run → block and escalate; Record each dispatched agent's response state (SPEC-ARGO-037); Status discipline.
Not here: spec authoring (`/nightshift spec`), recovery of a blocked spec (`unblock.md`); the run's pinned executable blocks are in `pinned-briefs.md`, `pinned-checks.md` and `pinned-validator.md`.
Requires: a ready spec in an installed project; read the parts in order: `run.md`, `run-2.md`, `run-3.md`, `run-4.md`, `run-5.md`, `run-6.md`, `run-7.md`, `run-8.md`.

# Run guide, part 8 of 8

**If any other check fails or the orchestrator reports blocked/stuck → invoke the controller-backed unblock protocol:**

Keep the spec `in_progress` while the parent creates the durable blocked evidence
required by the lifecycle contract, then use `unblock_spec.py prepare` with the
same stable run ID. The parent records every result with `record_attempt` and is
the sole caller of `finalize`; parent remains the sole lifecycle and merge owner.
It never asks the worker to mutate lifecycle state, merge, or finalize metrics.
An eligible packet permits exactly one isolated,
bounded recovery worker. A skipped or failed packet records the controller-produced
next safe action and causal confidence, leaves the spec blocked, and forbids an
automatic retry for the unchanged fingerprint. For a `scope_violation` packet
(SPEC-300-002 R8), `prepare` reports `eligibility: skipped` with next safe
action "human scope decision" unless a `## Scope Amendments` row now exists on
main covering every path named in `block_reason`, in which case it reports
`eligibility: eligible` and rung 1 may run ordinarily — this is the one
class where a later `prepare` call on the *same* blocked spec can flip from
skipped to eligible without a new blocker, because the human-approved
amendment is exactly the fact that changes.

Only a verified `record_attempt(... outcome="succeeded")` followed by `finalize`
may transition `blocked -> ready`. Rerun ordinary admission and the fresh-main
evidence gate from that ready state; do not jump from blocked to `in_progress` or
`done`. The recovery report must include the packet/attempt artifact references,
verification result, human-action flag, and a Causal confidence line. When the
mechanism is not proven by before/after evidence it says `not_established`, not a
speculative explanation of why it worked.

**If controller recovery fails or cannot run → block and escalate:**

1. Mark the spec blocked on main. For `commit-backed`, use the failure persistence helper (`failure_persistence.py` in the project's `.nightshift/` or `canonical/` directory):
   ```bash
   python3 -c "
   import sys; sys.path.insert(0, '.nightshift')
   from failure_persistence import mark_spec_blocked
   from pathlib import Path
   mark_spec_blocked(Path('specs/<spec-file>'), '<specific reason: which check(s) failed and why>')
   "
   ```

   For `private-local`, call `transition_private_state(..., "blocked",
   run_id=<started-run-id>, owner="coordinator", assigned_spec=<spec-id>,
   note=<specific reason>)` instead. It must leave one terminal checkpoint and no
   staged/committed private path. Run the SPEC-291 `record-transition` command
   below (with `--reason`) regardless of mode.

   `-> blocked` is a judgment transition (SPEC-291 R3): record the transition
   artifact *before* committing (below), so the artifact file exists on disk
   to be staged in the same commit — an empty reason is refused, not silently
   skipped. This also upserts the spec's `## State rationale` section
   (SPEC-357); `--reconsider-when` is required (non-empty) whenever `--to`
   is `blocked` (or `draft`/`planned`) — a concrete condition, decision,
   date, or review trigger that would change this status, not a repeat of
   the reason:
   ```bash
   python3 .nightshift/spec_artifacts.py record-transition <spec-file> \
     --from in_progress --to blocked --run-id <started-run-id> \
     --reason "<specific reason: which check(s) failed and why>" \
     --reconsider-when "<what would change this: unblock condition, date, or review trigger>"
   ```

2. In `commit-backed`, commit on main: stage both the spec file and its
   `reports/<spec-id>/artifacts/` directory (the sibling of the specs
   directory's `reports/`, not bare `reports/` from the project root — see
   Step 2b).
   ```
   chore: mark <spec-id> blocked

   <one-line reason>

   Nightshift-Evidence-Report: <pass|fail|unknown>
   Nightshift-Evidence-Tests: <pass|fail|unknown>
   Nightshift-Evidence-Code: <pass|fail|unknown>
   Nightshift-Evidence-ACs: <pass|fail|unknown>
   Nightshift-Evidence-Verifier: <pass|fail|disputes_premise|unknown>
   Nightshift-Blocker-Class: <implementation|test_infrastructure|fixture_drift|baseline_regression|external_input|evidence_gap|scope_violation|unknown>
   Nightshift-Blocker-Scope: <in_scope|out_of_scope|mixed|unknown>
   Nightshift-Scope-Check: <violated|not_run|clean|amended>
   Nightshift-Unblock-Attempts: <0|1>
   Nightshift-Unblock-Limit: 1
   Nightshift-Unblock-Rung: <0|1|2|3|4|5>
   Nightshift-Parent-Tool-Calls: <N>
   Nightshift-Resolution-Kind: <verifier-dispatched|self-verified|self-verified-experimental>
   Nightshift-Experimental-Sample-For: <currently-live designating spec (e.g. canonical SPEC-223, which supersedes the original SPEC-ARGO-038-001 designation — read that spec's own file for the live target before writing this trailer) | omit unless Resolution-Kind is self-verified-experimental>
   ```

   **BUG-017 — same single-paragraph rule as the `done` commit above applies here.**
   If attribution trailers (`Co-Authored-By:`, `Claude-Session:`, or equivalent)
   are also required, append them as more lines inside this same trailer block —
   never as a separate blank-line-delimited paragraph, and never with no blank
   line at all between the one-line reason above and this block. Git's trailer
   parser only recognizes one contiguous, fully trailer-shaped final paragraph;
   splitting or omitting the blank line silently hides `Nightshift-*` trailers
   from every reader, including `record_metrics.py`.

   The subject line is exactly `chore: mark <spec-id> blocked` with no trailing suffix —
   this is what `record_metrics.MARK_COMMIT_RE` and `hooks/commit-msg` both enforce. The
   one-line reason goes as the first line of the commit body, above the trailer block; it
   is for human/git-log readability only — `derive_block_reason` reads the reason from the
   spec file's own `block_reason`, not from the commit.

   The tool-call tally and resolution-kind trailers are mandatory here too (R2's "terminal
   resolution" includes `blocked`, not only `done`) — same definitions as the done-path
   instruction above: count the parent's own tool calls from Step 5 launch to this commit,
   self-tallied and unaudited, and record which resolution kind actually occurred.

   Classify the blocker by observed cause, not by the worker's status. Use
   `fixture_drift` for stale/mutated expected artifacts, `test_infrastructure`
   for harness/port/environment failures, `evidence_gap` when implementation may
   be sound but a required gate cannot be demonstrated, `implementation`
   for a defect in the spec's delivered code, and `scope_violation` (SPEC-300-002
   R3) when evidence-gate check 6 denied a path — always with `blocker_scope:
   out_of_scope`, and see the "check 6 fails" carve-out above for the routing
   difference: this class never enters the controller-backed ladder
   automatically. Scope says whether the required fix belongs to the
   kicked-off spec.

3. Write a Cortex breadcrumb:
   `mcp__cortex__cortex_breadcrumb`: `"Spec <spec-id> blocked after kickoff run: <reason>"`

4. Leave the worktree in place for inspection. Tell the user:
   - Which evidence check(s) failed and what is specifically missing
   - Which controller recovery attempt was recorded, or why it was skipped
   - Worktree path for manual inspection of partial work
   - Suggested next step (fix the gap and re-run, or investigate the blocker)

**Record each dispatched agent's response state (SPEC-ARGO-037).** Terminal
resolution is not complete until one outcome row exists per agent this run
dispatched — the run worker, the Step 5c `nightshift-verifier`, and any bounded
recovery worker. This runs on **both** branches: a blocked run is exactly the case
the field exists to measure, and a run that never produced a worker still
dispatched one.

<!-- SPEC-ARGO-037-RESOLUTION-BEGIN -->
```bash
# One record per dispatched agent. agent_response is the PARENT's observation of
# whether that agent responded — never the agent's own account, because the agent
# this field exists to catch is the one that stopped answering.
#
#   completed              engaged and reached its own terminal state
#   refused_with_evidence  declined, and stated a reason  <- NOT a failure
#   no_response            launched, never acted (heartbeat stuck at parent-seeded,
#                          zero tool calls, zero commits)
#   stalled_mid_task       acted, then froze with work incomplete
#   partial_abandoned      landed partial work, then went unresponsive
#   launch_failure         launch was REJECTED; no worker ever ran (Step 5a branch)
#
# Everything except `completed` needs agent_response_evidence: the parent-observable
# facts. Heartbeat state, tool-call count, commit count, or the refusal's reason.
python3 "$ARGO_HOME/Skills/delegate/scripts/record_agent_outcome.py" --allowed-values
python3 "$ARGO_HOME/Skills/delegate/scripts/record_agent_outcome.py" --append /tmp/outcome-{spec-id}.json
```
<!-- SPEC-ARGO-037-RESOLUTION-END -->

The writer rejects a record with a missing or off-enum `agent_response` and names
the allowed values; the `pre-commit` guard it installs rejects a hand-edited row
that skipped it. Do not classify a `refused_with_evidence` as a stall because the
run did not land — a correct refusal is the system working, and folding the two
together is the one thing the vocabulary exists to prevent.

**Status discipline:** never leave a spec stuck at `in_progress` after the kickoff
resolves. One of `done` or `blocked` must be visible in both frontmatter and the
durable status reader. Commit it only in `commit-backed`; private-local uses the
matching local run event. The board uses the existing reconciliation path.

Before becoming idle on this path, record `terminal_resolution: blocked` and
`terminal_resolution_elapsed_s` in the parent progress artifact. A failed evidence
gate has one and only one controller-backed unblock pass; its skipped, failed, and
successful outcomes all continue to a terminal state rather than `awaiting parent
integration`.

After the durable `blocked` state exists, publish the terminal fact and do not
wait for its optional consumer:

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event run.completed --outcome blocked
```

### Step 7: Process suggested follow-up specs

After the run resolves and a report exists, check the report for a `## Suggested Follow-up Specs` section. This applies after **every** run completion or unblock — not only for `done` specs (a blocked run can still surface valid follow-ups).

After processing that section, the coordinator executes the managed canonical
processor exactly once: `python3 .nightshift/followup_processor.py --root
.nightshift --specs-dir .nightshift/specs --source-spec <SPEC-ID> --run-id
<RUN-ID> --terminal-context <done|noop|partial|blocked|unblock|verifier_warning|material_scope|integration_failure|post_release>
--evidence-ref <project-relative-report>`. A suggestion also passes controlled
classification and source-aware child arguments. The processor runs the
source-aware conflict check, preserves distinct conflict/NFR/tool outcomes, and
seals `created` only after its child exists with the exact backlink. No
suggestion records the required zero observation. A report alone is not evidence.

For each suggestion entry, run the conflict check:

```bash
python3 .nightshift/check_followup_spec.py \
    --suggestion-title "<suggestion title>" \
    --specs-dir .nightshift/specs \
    [--artifact "<output_artifact path>"] \
    [--domain "<domain>"] [--layer <0-3>]
```

Act on the JSON result:

- **Exit 0 (`status: clean`)** — create the spec immediately in `.nightshift/specs/` using the `proposed_id` from the JSON and the `SPEC-GUIDE.md` format. Do **not** ask for confirmation. Commit the new spec file.
- **Exit 1 (`status: conflict`)** — do **not** create the spec. Record the conflict detail under the suggestion entry in the run report.
- **Exit 1 AND `nfr_texts` non-empty** — read each NFR text returned by the script and judge semantically whether the suggestion violates any NFR constraint. No violation → treat as clean and create the spec. Violation found → do not create; record the NFR constraint that blocks it.
- **Script missing** (`.nightshift/check_followup_spec.py` not found) — record the suggestion as pending in the report; skip creation.

Keep this policy here only — `board.py`'s run prompt points at this skill rather than duplicating it, so the two cannot drift.
