Load when: you run `/nightshift run` or `/nightshift kickoff` and have reached the steps listed under Covers.
Covers: part 2 of 8 of the run procedure: Step 4: Scaffold agent brief; within: a; b; b1; c; d; e; f; g.
Not here: spec authoring (`/nightshift spec`), recovery of a blocked spec (`unblock.md`); the run's pinned executable blocks are in `pinned-briefs.md`, `pinned-checks.md` and `pinned-validator.md`.
Requires: a ready spec in an installed project; read the parts in order: `run.md`, `run-2.md`, `run-3.md`, `run-4.md`, `run-5.md`, `run-6.md`, `run-7.md`, `run-8.md`.

# Run guide, part 2 of 8

### Step 4: Scaffold agent brief

Auto-generate the brief the agent will receive.

**a. Extract from spec frontmatter:**
- `id`, `layer`, `type`
- `after:` dependencies (mention as context, not blockers)
- `prior_attempts` — if any, include them: "Previous attempts: [list]. Do not repeat these approaches."

**b. Extract from spec body:**
- Problem section → brief Problem
- Requirements section → brief Requirements (verbatim)
- Acceptance Criteria → brief AC (verbatim)
- Context section → target files, test files, framework

**b1. Include the artifact-index summary when one exists (SPEC-291).** Read
`reports/<SPEC-ID>/artifacts/index.json`, if present, and add one line per
entry (`type` / `created` date / `summary`) to the brief under an "Artifact
history" heading — so the agent starts from why prior transitions happened
instead of re-deriving it. Absent or empty is silently skipped, never an
error (R7: most specs have no artifact history yet).

**c. Auto-map DevKB files** from spec `technologies` field using the DevKB Mapping Table in Implementation Notes. If the spec has no `technologies` field, detect from target file extensions (`.py` → python.md, `.swift` → swift.md + xcode.md, `.ts/.js` → shell.md, etc.).

**d. Populate Build & Verify** from `config.yaml` commands.

**e. Add standard boilerplate:**
```
- Read `.nightshift/BOOTSTRAP.md` first — it defines how to start a run
- Follow `.nightshift/LOOP.md` for the spec→implement→test→review→commit cycle
- Work only on spec {spec-id}. Do not touch other specs or unrelated files.
- Declared write scope: {scope.write, or "project root (no scope: declared)"}. An
  enforcement point that denies a write names the offending path and this scope;
  retry inside the declared scope first. If the write is genuinely needed outside
  it, do not perform it — record the path/reason under `## Scope Blockers` in the
  run report and return `worker-blocked` (SPEC-300 § Enforcement); scope only
  widens through a human-approved `## Scope Amendments` row on main. **This is a
  mechanical gate precondition, not just an audit trail (SPEC-302 R1):** if
  `scope.write` (or `deny`/`read`) on main is edited directly — widened with no
  covering `## Scope Amendments` row dated on or after that widening and carrying
  `Approved by: human` (or `human:<name>`) — `scope_guard.scope_from_main` does
  not honor the widened value for enforcement; it falls back to the narrower
  value that was in effect the last time the spec was `ready`. A pure narrowing
  (removing a `write` glob, adding a `deny` glob) never needs a row and always
  takes effect immediately (R2). Both the evidence-gate check 6 script below and
  the git pre-commit guard (SPEC-300-003) read scope exclusively through this one
  reconciling function (R3), so this precondition applies identically at both
  layers. A spec that has never had its scope widened, or whose `## Scope
  Amendments` table has always been empty, is unaffected (R5). SPEC-302-001
  closed two residual gaps in this same mechanism: a widening committed while
  `status:` stays `ready` (never passing through `in_progress`) can no longer
  become its own reconciliation baseline, and a commit that both narrows and
  widens the *same* field no longer un-drops the narrowed-out item as a side
  effect of blocking the uncovered widening.
- Commit your changes — the parent will review and merge the worktree branch.
- **Every `git commit` in this run MUST be prefixed with `NIGHTSHIFT_ACTIVE_SPEC={spec-id}`
  in the exact same shell invocation**, e.g.
  `NIGHTSHIFT_ACTIVE_SPEC={spec-id} git commit -m "..."` (SPEC-301). Your branch
  name is harness-assigned (`worktree-agent-<hex>` when launched with
  `isolation: "worktree"`) and does not encode the spec ID, so the git
  pre-commit write-scope guard (SPEC-300-003) cannot resolve the active spec
  from the branch name alone — without the inline env var it silently falls
  back to `no_active_spec` (allow, not a false deny, but also not enforcing
  your declared `scope.write`). A bare shell `export NIGHTSHIFT_ACTIVE_SPEC=...`
  does NOT help if your tool issues each command in a fresh shell — verify
  this for your own harness before relying on it, and prefix every commit
  inline regardless. This only reaches the git-guard layer; it does not
  retroactively affect any other enforcement point that resolves the active
  spec independently (e.g. a `PreToolUse` hook spawned by the harness itself
  reads its own environment, not this shell's).
- If you touch a file that is itself a member of `nightshift-sync.py`'s
  `CANONICAL_PROTOCOL_FILES` (i.e. your `scope.write` already legitimately
  includes a managed canonical-payload file), you do **not** need to add
  `release-manifest.json`/`CHANGELOG.md` to `scope.write` by hand —
  `scope_guard.py` implicit-allows both for you in that case
  (SPEC-300-001-001). Regenerate the manifest via
  `release.write_manifest(canonical_path, CANONICAL_PROTOCOL_FILES)` before
  your final commit regardless, and verify hashes with `shasum -a 256`
  against every file you edited — a stale manifest checksum breaks
  `release.apply_install()`'s verification everywhere it's exercised (SPEC-301).
- Circuit breaker limits: {max_same_errors} same errors, {max_review_cycles} review cycles, {timeout_minutes} min total
- Do NOT use Write tool for existing files — use Edit with precise replacements
- Do NOT guess API names — grep existing code first
- One fix at a time, one build at a time — do not stack changes
- MANDATORY: After completing the spec, write a human review report to
  `reports/YYYY-MM-DD-nightshift-report-{spec-id}.md` (Step 14 of LOOP.md).
  This is NOT optional. A run without a report is an incomplete run.
  The report must include, verbatim as headings, matching LOOP.md Step 14's
  canonical template exactly (not a paraphrase): summary stats, per-spec
  changes, test results, AC checklist, a `## Blocked Specs` section, an
  `## Open Questions` section, and a `## Report Action Log` section — each
  states its content, or the literal word `None`/a `none_found` row when
  empty, never omitted. Also include any other blockers or discoveries.
```

**f. If `kickoff_parent: true`, add this section to the launched agent brief:**
```markdown
## Kickoff Parent Context

You were launched by a parent kickoff agent. The parent agent is monitoring this
run and will not implement the spec directly.

You are the run/orchestrator agent. You own Nightshift startup, instruction
packet generation, context loading, implementation, validation, metrics, reports,
and commits.

You run in an isolated git worktree, so the parent CANNOT see files inside your
worktree while you work. To stay observable, publish your heartbeat to the SHARED
progress file at the absolute path the parent gave you — it points into the MAIN
checkout (outside your worktree), under `_wip/` (gitignored, so no commit/merge
conflict):

`{progress_file_abs}`  (= `<main-repo>/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md`)

**Hard cadence rule — the parent enforces this:** the heartbeat file MUST advance
at least once every 20 minutes. If 20 minutes pass with no update, the parent
treats the run as stalled and may stop it. Update at each major phase or every
~10 minutes during long compute, whichever comes first — never let the file go
quiet for 20 minutes, even mid-step (write "still working on X, no new commit yet"
rather than nothing).

Each update OVERWRITES the file with: current phase, last completed action, next
action, latest commit SHA on your branch (so the parent can confirm forward motion
without seeing your worktree), an ISO-8601 UTC timestamp, blockers/stuck signals,
and latest evidence paths.

**Worktree-isolation write method — required:** `Write` and direct shell
redirection (`>`) to `{progress_file_abs}` are rejected because that path is
outside this worktree. Write the complete heartbeat to a worktree-local file,
then use `/bin/cp` to publish it to the shared path:

```bash
HEARTBEAT_LOCAL="$PWD/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md"
mkdir -p "$(dirname "$HEARTBEAT_LOCAL")"
# Produce the complete update locally. Its first line must be:
# heartbeat_state: worker-started
/bin/cp "$HEARTBEAT_LOCAL" "{progress_file_abs}"
```

The first successful `/bin/cp` replaces the parent seed's
`heartbeat_state: parent-seeded` marker. A seed that never gains
`heartbeat_state: worker-started` means **heartbeat never started**; a stale
file that does contain `worker-started` means **heartbeat stalled after start**.
Do not attempt another external write mechanism.

**`heartbeat_state` — controlled vocabulary.** The field is the file's **first
line** and takes exactly one of four values. Nothing else is a valid state:

| Value | Meaning | Written by |
|---|---|---|
| `parent-seeded` | file created at launch; the worker has not written yet | parent, Step 5 |
| `worker-started` | the run is live — **non-terminal**, the watchdog keeps measuring staleness | run agent |
| `worker-done` | the run finished its work — **terminal** | run agent |
| `worker-blocked` | the run stopped and cannot proceed — **terminal** | run agent |

`worker-done` and `worker-blocked` are the terminal set. **Before you return, your
final heartbeat MUST carry a terminal value on line 1.** A run that finishes while
still at `worker-started` is byte-for-byte indistinguishable from a hung one, and
the Step 5b watchdog will correctly report it as a stall — the false-alarm case
this vocabulary exists to remove. Write `worker-done` when you completed the work
(including a clean no-change outcome) and `worker-blocked` when you are handing
back a blocker. After writing a terminal `heartbeat_state` make no further commits on
the branch: the verifier judges that exact tip and the parent merges only it. You may
add one optional line `head: <sha>` (the branch tip you declare done); a mismatch with
the tip is `stale_head`.

Only line 1 is read. Naming a terminal value further down the file — in a "next
action" line, a quoted log, an evidence path — does **not** end the run and is not
read as terminal. Do not invent spellings (`worker-complete`, `done`, `finished`):
an unrecognised value is treated as non-terminal.

If you believe the spec is blocked or cannot proceed, report the exact blocker,
what you already tried, the latest evidence paths, and the smallest bounded
recovery task that should be attempted next. The parent kickoff agent may use
that to invoke the controller-backed unblock protocol before a terminal blocked
status is committed.
```

**g. Git-mutation-evidence preflight (SPEC-309, R1/R2/R4) — check before Step 5, not after
a failed dispatch.** Read this spec's Live Execution Checklist and Acceptance Criteria: do any
of them require a real git commit-class operation — `git add`, `git commit`, `git worktree add`,
or any mechanism that only fires at commit time (a pre-commit hook, a branch-naming convention
check)? If so, **a worktree-isolated worker cannot reliably execute it.** The sandbox's `rtk`
wrapper refuses bare `git status`/`git log`/`git commit` invocations, with byte-identical refusal
wording whether the target is the agent's own assigned worktree or a wholly disposable scratch
repository the agent built itself with no connection to the real project's git state (confirmed by
direct probe, 2026-09-06) — **this is a static command-shape parse check, not a target- or
mutation-aware boundary**: bare `git add .` (a real mutation) succeeds unrefused against an
external scratch repo in the same probe. A sanctioned `dangerouslyDisableSandbox: true` escalation
on the same command is refused identically; this is a platform boundary, not a bug to route around.
Three specific things must never be done in response to this refusal:
1. Do not suggest, and a worker should not attempt, an absolute-path invocation like `/usr/bin/git`
   in place of bare `git` as a workaround — that is a different, narrower fix for a *different*
   problem (BUG-019's compound/aliased commands), see the BUG-021 worked example under Step 5c.
2. Do not pipe (`| cat`, `| head`) or redirect (`>`) a git invocation to get around this refusal.
   That shape change bypasses the refusal outright — including for real `git commit` against a
   repository wholly external to the agent's own worktree — which means it evades an isolation
   guarantee, not merely an inconvenient control. See BUG-310 for the full finding; treat any
   dispatched agent that does this as having violated the sandbox boundary, not worked around an
   inconvenience.
3. Do not wrap the invocation in a subprocess call from another language (e.g. Python's
   `subprocess.run(["git", ...])`) to get around this refusal, even for a read-only command. This
   is a third observed bypass form (BUG-310, discovered during BUG-313), consistent with the same
   static command-shape parse mechanism rather than a new boundary — the wrapper's check keys off
   the literal `git ...` command-line shape it is asked to run directly, not any semantic property
   of the invocation, so any indirection that changes that literal shape bypasses it. Treat this
   identically to item 2: a dispatched agent that does this has violated the sandbox boundary, not
   found a sanctioned workaround, regardless of whether the wrapped command was itself read-only.

- **Sanctioned fallback (R2):** the coordinator (the top-level, non-isolated session) executes the
  live proof directly instead of a worktree-isolated worker. The completion report must name this
  explicitly — e.g. "executed by the coordinator, not a worktree-isolated worker, because
  `<spec-id>`'s evidence requires a real `git commit`" — rather than silently reading like ordinary
  worker output.
- This does not lift or route around the sandbox restriction itself (Out of Scope, SPEC-309 R5) —
  it only means the coordinator anticipates the constraint before dispatch instead of discovering
  it mid-run after burning a worker turn.
- See Step 5c's verifier-brief guidance (R3) below for the matching independent-verification-side
  handling — the same limitation applies to a dispatched `nightshift-verifier` trying to
  independently re-execute the same evidence.

**Runner mode variation:**
- `inline` — agent processes this spec only, returns when done
- `orchestrator` — after completing this spec, agent picks the next `ready` spec by layer+priority and continues until the queue is empty or circuit breaker trips

Print the scaffolded brief to the user (as FYI context), then proceed immediately to Step 5. Do NOT ask for confirmation — the user already stated intent by invoking `/nightshift run` or `/nightshift kickoff`. Only stop and ask if something is genuinely unclear or missing (e.g. ambiguous spec body, unresolved dependency drift from Step 1, missing required config values).

