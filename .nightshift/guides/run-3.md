Load when: you run `/nightshift run` or `/nightshift kickoff` and have reached the steps listed under Covers.
Covers: part 3 of 8 of the run procedure: Step 5: Launch agent; Step 5b: Enforced liveness loop (monitor the background run); Watchdog cleanup assertion (SPEC-226); Durable pre-fix red proofs (SPEC-279); within: Worktree path and project-ownership gate; Branch-name active-spec resolution (SPEC-301); Subagent coverage (SPEC-300-004 R7); Capture the `agentId` from this launch result; Immediate launch-failure branch (before the heartbeat watchdog); Wake source 1 — completion notification; Wake source 2 — liveness watchdog (the hang case); This is still wake source 2, not a third one.
Not here: spec authoring (`/nightshift spec`), recovery of a blocked spec (`unblock.md`); the run's pinned executable blocks are in `pinned-briefs.md`, `pinned-checks.md` and `pinned-validator.md`.
Requires: a ready spec in an installed project; read the parts in order: `run.md`, `run-2.md`, `run-3.md`, `run-4.md`, `run-5.md`, `run-6.md`, `run-7.md`, `run-8.md`.

# Run guide, part 3 of 8

### Step 5: Launch agent

> **Precondition — verify before calling Agent():** for `commit-backed`, run
> `git log --oneline -1` and confirm the latest commit is `chore: mark {spec-id}
> in_progress`. For `private-local`, confirm the matching durable `in_progress`
> event/run ID and unchanged HEAD/index. If the selected proof is absent, return
> to Step 2. Do not proceed.

**Worktree path and project-ownership gate:** harness-managed `isolation: "worktree"`
is preferred. If the platform requires the parent to create a worktree manually, obtain
its path from the target project's installed resolver—never construct a sibling path
such as `<project>-nightshift-*` and never put it below the synchronized checkout:

```bash
WT=$(python3 <main-repo-abs>/.nightshift/worktree_paths.py plan \
  --repo <main-repo-abs> --spec {spec-id})
git -C <main-repo-abs> worktree add -b nightshift/{spec-id}-<run-id> "$WT"
python3 <main-repo-abs>/.nightshift/worktree_paths.py verify \
  --repo <main-repo-abs> --worktree "$WT"
```

The verify command is a hard gate before launch, merge, or cleanup: it proves the
worktree shares the intended project's Git common directory. A path/ownership failure
stops the run; do not fall back to a Dropbox sibling. After a successful merge, remove
the worktree and branch immediately as required by Step 6.

**Branch-name active-spec resolution (SPEC-301):** the `nightshift/{spec-id}-<run-id>`
branch shape above is only produced by the manual `git worktree add -b ...` path
just shown. A harness-managed `isolation: "worktree"` launch assigns its own
branch name independently of this convention (observed in this repository:
`worktree-agent-<hex>`) — `scope_guard.py`'s `active_spec()` cannot and does not
try to parse a spec ID out of that shape (no derivable relationship exists between
a harness-assigned hex ID and any spec ID). Every worker brief's Step 4e
boilerplate compensates by requiring `NIGHTSHIFT_ACTIVE_SPEC={spec-id}` inline on
every `git commit`; do not assume branch-name parsing alone enforces `scope.write`
for a harness-launched worker.

**Subagent coverage (SPEC-300-004 R7):** the write-scope `PreToolUse` hook is a
project-level Claude Code setting, not a per-worker one — when it is installed
in `<project>/.claude/settings.json`, it fires for every tool call a worker
launched with `isolation: "worktree"` makes from that project, including a
worker whose own worktree carries no `.claude/settings.json` of its own. A
worker whose settings happen to omit the hook (a harness that doesn't read
project settings, or a project that never ran the installer) still meets the
write-scope contract through the git pre-commit guard (SPEC-300-003) and the
evidence gate (SPEC-300-002) — the hook is the earliest layer, not the only
one.

**Known, accepted gap — `NIGHTSHIFT_ACTIVE_SPEC` does not reach the
`PreToolUse` hook for a harness-launched worker (SPEC-300-004-001):** the
parent's own Agent-launch tool (the `Agent({...})` call shown in Step 5) has
no parameter for setting an environment variable, or any other durable
per-session value, for the launched subagent's whole session — its schema
exposes only `description`, `isolation`, `mode`, `model`, `name`, `prompt`,
`subagent_type`, and `team_name`. This was checked directly against the
launch tool's own schema (not inferred), so it is a confirmed answer, not an
open question. A worker's own Bash tool calls cannot substitute for this
either: SPEC-301 confirmed empirically that a shell `export` in one Bash tool
call does not persist into the next — the harness issues each Bash call in a
fresh shell. Combined with the branch-name finding directly above (a
harness-assigned `worktree-agent-<hex>` branch carries no spec ID for
`scope_guard.py` to parse), this means **`scope_guard.py`'s `active_spec()`
has no working input for the `PreToolUse` hook on a harness-launched kickoff
today** — neither `NIGHTSHIFT_ACTIVE_SPEC` nor branch-name parsing resolves
the active spec at that layer, so it falls back to `no_active_spec` (allow)
for every real kickoff, which in turn means the hook's *spec-scoped* `write`/
`deny`/`read` rules never actually deny an out-of-scope write today. This is
not a false-deny risk (R4: a resolution failure always falls open, never a
false deny) — it is a coverage gap. The hook's two **universal** rules (the
spec-home guard and the malformed-target guard, which do not depend on
`active_spec()` resolving anything) still fire normally and are unaffected.
The two layers that remain fully working for spec-scoped enforcement on a
harness-launched kickoff are the git pre-commit guard (SPEC-300-003, via the
inline `NIGHTSHIFT_ACTIVE_SPEC={spec-id}` commit-prefix convention above,
which the guard reads directly from the `git commit` subprocess's own
environment) and the parent's evidence gate (SPEC-300-002). No fix is
available at the harness layer today (SPEC-300-004-001 R1/R3); this is
recorded as a known, accepted limitation, not a silent one.

In `private-local`, after this verification and before launch, invoke
`project_private_state` with an explicit allowlist containing only the selected
spec, installed runtime/protocol, project configuration, and required knowledge.
The destination must remain ignored. Before merge, call `return_private_evidence`
with only report, metrics, verification artifacts, and heartbeat paths declared by
the run contract, then run `privacy-check --base-ref <main-ref>` on the worker.
Any tracked/staged/diff private path refuses integration and preserves the worktree.

Before launching, compute the absolute heartbeat path and substitute it for
`{progress_file_abs}` in the brief: `<main-repo-abs>/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md`.
Create the `_wip/` dir if missing, then **seed the heartbeat file now with an
initial ISO-8601 timestamp and `heartbeat_state: parent-seeded` line** so the
staleness clock starts at launch — this catches a run that hangs before it ever
writes its first heartbeat (the watchdog needs the file to exist to measure
staleness). This marker also makes a never-started heartbeat distinguishable from
one that started and later stalled. This is the shared file the parent watches in
Step 5b — both parent and run agent use this exact absolute path.

Launch the run agent **in the background** (`run_in_background: true`). This is
required: a foreground launch blocks the parent until the subagent returns, which
makes the liveness monitoring in Step 5b structurally impossible (and is why hung
runs have gone undetected). Background launch keeps the parent in control.

```
Agent({
  description: "nightshift run {spec-id}",
  prompt: <scaffolded brief>,        // with {progress_file_abs} substituted
  isolation: "worktree",
  mode: "bypassPermissions",
  run_in_background: true,           // REQUIRED — see note above
})
```

**Capture the `agentId` from this launch result** — the parent needs it to
`TaskStop` the run if it hangs (Step 5b). Display: "Agent launched in background.
Monitoring `{spec-id}`..." Then proceed immediately to Step 5b. The harness
surfaces a completion notification to the parent when the background run finishes
— that is wake source 1 in Step 5b, and the run's `<branch>`/`<path>` arrive in
that notification's result payload.

**Immediate launch-failure branch (before the heartbeat watchdog):** A rejected
launch, or a completion carrying a harness/launch error before the shared
heartbeat contains `heartbeat_state: worker-started`, is a distinct
`launch_failure` outcome. Preserve the timestamp, sanitized harness error,
launch result, and heartbeat state in the parent progress artifact and run
report; do **not** wait 20 minutes for the stale-heartbeat watchdog.

The parent may make **exactly one** focused retry only when the error is
retryable and the retry needs neither human input nor unsafe action. Reuse the
same spec, run ID, parent claim, and isolated worktree policy, but narrow the
brief to the launch blocker, required context, and one deterministic verification
step. Record `launch_retry: 1` before dispatching it. The retry worker still
cannot change lifecycle state or merge.

If the first error is ineligible (credentials, policy approval, destructive or
unsafe action, ambiguity, or external input), or if that one retry is rejected
or completes before `worker-started` with another launch/harness error, stop
launching workers. Use the existing controller-backed blocked-resolution path,
with `blocker_class: launch_failure`, the preserved evidence, and the controller
produced next safe action. This is terminal `blocked`, not a stale heartbeat and
not an extra retry. If the focused retry starts successfully, continue through
the ordinary Step 5b liveness and Step 6 evidence gates, retaining the initial
launch failure in the final report.

### Step 5b: Enforced liveness loop (monitor the background run)

The run agent runs in the background, so the parent keeps control and **MUST**
actively confirm the run is still progressing — this step is not optional. Hung
runs that silently stop "looping" are the failure mode this guards against. The
parent does not take over implementation; it only watches and, on a confirmed
hang, stops and escalates.

Exactly two things wake the parent. Handle each:

**Wake source 1 — completion notification.** When the background run agent finishes,
the harness surfaces a background-task completion notification to the parent. If
it carries a launch/harness error and the heartbeat never reached
`worker-started`, handle the immediate launch-failure branch in Step 5 first;
otherwise → go to Step 6 (post-run resolution).

**Wake source 2 — liveness watchdog (the hang case).** A hung run never sends a
completion notification, so the parent detects it on a wall-clock timer. The run
works in an isolated worktree the parent cannot read, so the parent watches the
SHARED heartbeat file instead:

`<main-repo-abs>/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md`

Immediately after launching (Step 5), arm a liveness watchdog with the **`Monitor`**
tool — a poll loop that exits, and thereby notifies the parent, on exactly one of
two conditions: the heartbeat reached a **terminal `heartbeat_state`** (`worker-done`
or `worker-blocked` — the run ended, this is `TERMINAL`, not a stall), or it has not
been touched for the stall threshold (1200s = 20 min — this is `STALL`). Do **not**
use `ScheduleWakeup` (it is `/loop`-only), and do **not** chain `sleep` commands
(long leading sleeps are blocked):

```bash
# Monitor watchdog — wakes the parent on EITHER a terminal heartbeat_state (the run
# ended cleanly) OR a heartbeat stale > 1200s (20 min).
# Terminal is checked FIRST and this ordering is load-bearing: a finished run's
# heartbeat is ALSO stale, so a staleness-first loop reports a false STALL on every
# completed run. Only line 1 is read — a terminal word elsewhere in the file must not
# disarm the watchdog on a genuinely hung run.
HB="<main-repo-abs>/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md"
TERMINAL_RE='^heartbeat_state:[[:space:]]*(worker-done|worker-blocked)([[:space:]]|$)'
while :; do
  if [ -f "$HB" ] && sed -n '1p' "$HB" | grep -Eq "$TERMINAL_RE"; then
    echo "TERMINAL: heartbeat for {spec-id} reached $(sed -n '1p' "$HB")"
    break
  fi
  if [ -f "$HB" ] && [ $(( $(date +%s) - $(stat -f %m "$HB") )) -gt 1200 ]; then
    echo "STALL: heartbeat for {spec-id} not advanced in >1200s"
    break
  fi
  sleep 60
done
```

(macOS: `stat -f %m`; Linux: `stat -c %Y`. The 60s inner poll is the watch's own
loop, not a leading sleep — the parent is not blocked while it runs.) **Capture the
watchdog's task ID when you arm it** — immediately record it as
`watchdog_task_id: <id>` in the parent progress state beside the run ID, claim,
and heartbeat reference. The parent needs that exact ID to `TaskStop` the watchdog
after the run resolves; a description or a later task-name search is not a substitute.

**This is still wake source 2, not a third one.** The watchdog wakes the parent once
and the parent routes on the message it printed: `TERMINAL` → go to Step 6
(post-run resolution) exactly as a completion notification would, recording the
terminal state read from line 1 and, before anything else, `worker_done_head: $(git rev-parse <branch>)`
in the parent progress artifact (pass it as `prepare-dispatch --head`; if the heartbeat carries
`head: <sha>`, `python3 .nightshift/verification_report.py merge-gate --heartbeat <HB> --branch <branch>`
printing `MERGE-GATE: stale_head` means the branch moved: do not dispatch the verifier); `STALL` → enter the escalation ladder below.
A `TERMINAL` wake never enters the ladder and is never recorded as a stall.

**Staleness escalation ladder** — when the watchdog fires `STALL`:

1. **First stall → classify, then grace.** Read the heartbeat's state marker.
   `heartbeat_state: parent-seeded` (or no `worker-started` marker) means
   **heartbeat never started**; `heartbeat_state: worker-started` means the
   heartbeat **stalled after start**. Record that exact classification, then
   re-arm the watchdog for ONE more interval. The run may be in one long step
   (large build, a slow model call), so do not escalate yet.
2. **Second consecutive stall (heartbeat still unchanged after the grace interval)
   → declare the run hung.** Do **not** try to "ping" the run agent — background
   subagents are not reliably pingable mid-run. Instead:
   - Stop the background run agent with `TaskStop`.
   - Mark the spec `blocked` on main via the failure-persistence helper (Step 6),
     reason e.g. `"kickoff run hung — heartbeat stale >40 min, no forward progress"`.
   - Append a `HANG` line to the heartbeat file for the post-mortem.
   - Cortex breadcrumb: `"Spec {spec-id} hung during kickoff run — stopped after stale heartbeat"`.
   - Leave the worktree in place for inspection. Tell the user what stalled (last
     recorded phase / action / commit SHA from the heartbeat) and the worktree path.

While neither wake source has fired, the parent is idle and waiting — it must not
poll the run agent directly or start doing the spec's work. The watchdog and the
completion notification are the only two channels.

### Watchdog cleanup assertion (SPEC-226)

Every terminal path — successful `done`, evidence-gate `blocked`, confirmed hung
run, and immediate launch failure (including its exhausted retry) — executes this
same parent-owned cleanup assertion before the parent becomes idle. The worker never
discharges it. The parent records the exact `watchdog_task_id`, asks the harness to
`TaskStop` that ID when it is armed, then enumerates the parent's running background
tasks and compares their IDs to the recorded ID.

Record one controlled result in both the parent progress artifact and final run
report:

| `watchdog_cleanup` | Meaning | Required action |
|---|---|---|
| `checked-clean` | The recorded watchdog ID is absent from the task listing after stop. | Continue terminal resolution. |
| `check-failed` | The recorded watchdog ID is still running, or `TaskStop` failed. | Report the failure; do not silently swallow it. Treat the terminal resolution as blocked/evidence-gap until it is resolved. |
| `check-not-run` | The harness has no task-listing capability, no watchdog was armed, or the parent could not perform the assertion. | Record the reason and whether human action is needed; this is graceful degradation, never a fabricated clean result. |

The terminal heartbeat and explicit stop are belt-and-braces, not alternatives — a
finished heartbeat does not prove task cleanup. A leaked watchdog is a protocol defect:
its task ID must appear in the `check-failed` report evidence. Before any `done` or
`blocked` lifecycle commit, include the cleanup result and the task ID (or the
documented `check-not-run` reason) in the terminal-resolution evidence. The run report
must use the exact three result names above so a missing check is distinguishable from
a clean result.

> **Platform note.** The above is the Claude path (`Agent run_in_background` + a
> `Monitor` watchdog). On Codex, use its background-execution plus a wall-clock
> watch equivalent. If a platform offers neither background launch nor a wall-clock
> watch, this flow degrades to instruction-only: launch foreground and accept that
> a hung run will block the parent — state that limitation to the user before
> proceeding rather than pretending the run is monitored.

### Durable pre-fix red proofs (SPEC-279)

When an acceptance criterion depends on a regression test having failed before
the fix, report prose is not sufficient evidence. The run that observes the red
result records the baseline revision, exact test-file bytes, and exact failing
pytest node IDs in a committed project-local artifact:

```bash
python3 .nightshift/red_proof.py record \
  --root "$PROJECT_ROOT" \
  --artifact "$PROJECT_ROOT/.nightshift/red-proofs/{SPEC_ID}.json" \
  --spec-id "{SPEC_ID}" --baseline-revision "{RED_BASELINE}" \
  --test-file "{REPOSITORY_RELATIVE_TEST_FILE}" \
  --failing-test "{EXACT_FAILING_NODE_ID}" [...]
```

The run agent must use the failures actually observed in that red execution,
inspect the emitted JSON, and commit the artifact before publishing `work.completed`.
The artifact belongs to project history; a same-spec report may summarize it but
does not replace it. Never place it under `reports/`, whose same-spec content is
intentionally withheld from the independent verifier.

When a later post-fix or integration run relies on that proof, the run agent
mechanically re-asserts it and commits the structured result before returning:

```bash
python3 .nightshift/red_proof.py reassert \
  --root "$PROJECT_ROOT" \
  --artifact "$PROJECT_ROOT/.nightshift/red-proofs/{SPEC_ID}.json" \
  --result "$PROJECT_ROOT/.nightshift/red-proofs/{SPEC_ID}-reassertion.json"
```

`reasserted` means only that the current test file is byte-identical to the file
bound into the committed observation. The result therefore says
`evidence_mode: inherited_committed_artifact` and
`red_execution_performed: false`; it never claims the post-fix run observed red.
This check must not revert or reconstruct pre-fix code. A missing or changed test
file is a successful evidence check with status `not_re_derivable` and an explicit
reason, not a stale pass and not a controller crash. The parent verifies that the
expected artifact/result is committed and verifier-readable before dispatch.


### Opt-in verification economics at parent boundaries (SPEC-NS-KIT-183)

When `verification_economics.enabled: true`, the full and small parent use the
same `verification_economics.checkpoint` decision/disposition summary. Include
its `status`, `reason_codes`, `decision` and `disposition` hash references,
`unmet_obligations` and separately scoped `cumulative` measurements in the existing
parent progress, next brief and report. Preserve native failure artifacts.
The default/opt-out route keeps its existing launch behavior and gate inventory.

Before expensive preparation, `verification_report.run_handoff` calls
`RealHandoffSteps.verification_economics`; supply the optional parent
`--economics-context <private-json>` transport. Its `intent` names a stable
`action_id`, `expected_new_evidence` and/or `changed_boundary`. Reuse that action ID
on a restart; a distinct proposed action gets a distinct ID. Current source,
contract, runtime/environment and exact command identities are recaptured, never
copied from the owner's old disposition. Environment values are hashed privately.

Owner cost/oververification signals and repeats without named new evidence are
on within this opt-in feature. Numeric soft thresholds have no defaults.
`soft_duration_seconds` compares observed native command wall time; it does not
pretend to measure reasoning, preparation or waiting. `soft_invocations` compares
observed launches. `soft_spend: {amount, currency}` uses only retained known spend
in that exact currency; unknown spend alone is not a refusal. No extra native
sample, application benchmark, polling loop or cost/provider collection is added.

Use `import_native_receipt` for existing `suite-sample` process/native records;
use `import_timing_receipt` for retained completed `record_metrics` stage snapshots
(`surface_preparation` or `coordination_gate_wait`). Pass these as `receipts` in
the transport, retaining their portable original file/hash references. Native,
preparation, reasoning and human/queue time are separate; unmeasured values are
unknown. Same-receipt imports deduplicate across recovery/new run IDs and spec
parents in indexed decision/context artifacts. Changed or missing originals,
conflicting identities and corrupt history refuse rather than reset the budget.

A nonempty `owner_signal` or another reason yields `review_needed` before launch.
It is a recommendation, never blocked, Done or permission to skip a required gate.
The parent retains the original decision and supplies one immutable `disposition`:
`decision_digest`, `kind`, `authorized_by: human:<owner>`, `statement`,
`evidence_delta` and `budget`. Supported kinds are `continue`, `reuse`,
`propose_amendment` and `recommend_replacement`. A continuation's evidence delta
must name the proposed new evidence or changed boundary, with finite positive
`budget: {invocations, duration_seconds}`. No agent judgment waives a gate.
Drift or additional receipts invalidates the old disposition; reevaluate without
resetting the retained lineage. A conflicting disposition is refused.

`reuse` delegates to existing ledger/recovery eligibility APIs with current pinned
identity and contract binding; it grants no fresh-main/safety/scope waiver. The
parent applies the existing eligible reuse plan and retains all still-required
obligations. An amendment/replacement is only a proposal for its existing authority
contract. A healthy already-running operation is never signalled by this soft
checkpoint; existing hard budgets, one-pair sampling/escalation, original receipts,
sole lifecycle/integration owner and distinct fresh-main gate remain unchanged.

Prelaunch fixture inventory is finite: unchanged-proof owner review; changed-source
or runtime continuation; identity/replay/unknown-cost/receipt-lineage controls;
owner/no-new-evidence/each configured soft trigger; unauthorized waiver, fabricated
zero, budget reset and terminal-Done refusal; healthy-operation and opt-out controls.
First delivery observes only the two disposable LE1 entrypoints with actual decision
artifacts and launch dispositions. Measurement is not an adoption/savings claim.
