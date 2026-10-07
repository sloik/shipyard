Load when: you run `/nightshift run` or `/nightshift kickoff` and have reached the steps listed under Covers.
Covers: part 1 of 8 of the run procedure: Step 1: Resolve spec; Step 2: Mark spec `in_progress` on main (EXECUTE NOW — before anything else); Step 3: Read config; Step 3b: Bind the stable observational checkpoints; within: If `spec-id` provided; If no `spec-id`; NFR reconciliation check (MANDATORY before launch); Main freeze (SPEC-NS-KIT-001); One-call ownership answer; 2a; 2a2; 2b.
Not here: spec authoring (`/nightshift spec`), recovery of a blocked spec (`unblock.md`); the run's pinned executable blocks are in `pinned-briefs.md`, `pinned-checks.md` and `pinned-validator.md`.
Requires: a ready spec in an installed project; read the parts in order: `run.md`, `run-2.md`, `run-3.md`, `run-4.md`, `run-5.md`, `run-6.md`, `run-7.md`, `run-8.md`.

# Run guide, part 1 of 8

### Step 1: Resolve spec

**If `spec-id` provided:**
- Find `specs/SPEC-{spec-id}-*.md` (or exact filename match)
- Validate `status: ready` — if not, error with current status and a suggestion (e.g. "status is draft — promote it with `/nightshift spec` first")

**If no `spec-id`:**
- Scan all specs for `status: ready`
- Sort by layer (ascending), then priority (ascending)
- Admit by dependency first (SPEC-NS-KIT-004): run `python3 .nightshift/nightshift-dag.py admission --specs-dir .nightshift/specs --worker-limit 1` and choose only from `frontier` in the `admission-plan.json` it writes (dependency-ready specs; layer/priority order them); a ready spec with an unmet `after:` is never chosen, whatever its layer or priority
- Show user which spec was selected and ask to confirm before proceeding

If no ready specs exist, report the queue state and exit.

**NFR reconciliation check (MANDATORY before launch):** Read the canonical
`SPEC-GUIDE.md` transition gate. Reconcile the selected spec against every
active NFR: bind each mechanical match in `nfrs:` (the NFR or its parent), or
record `nfr_waivers: [{id, reason}]` with a non-empty reason. Run
`python3 audit_nfr.py --check-all --specs-dir specs/` where that helper is
installed. This applies equally to `/nightshift run` and its `/nightshift
kickoff` wrapper; do not duplicate or weaken the canonical rule here.

**Dependency drift check (MANDATORY, after resolving, before any other work):**

The frontmatter `after:` field can drift from what the spec body actually says. A spec body might describe "blocked on FART-DS-019" while `after:` is empty — the formal dependency check then says "ready" even though the work genuinely depends on something unfinished. Catch this here so the agent never launches with stale dependency info.

Scan the spec body (everything after the `---` frontmatter delimiter) for spec IDs that match the project's ID pattern (e.g. `FART-DS-\d+`, `SPEC-\d+`) inside any of these dependency-implying constructions:

- `blocked on <ID>` / `blocks on <ID>`
- `depends on <ID>` / `depend[s]? on <ID>`
- `after <ID>` (when used as a verb/preposition, not part of an unrelated sentence)
- `needs <ID>` / `requires <ID>` / `prerequisite[:]? <ID>`
- `embeds <ID>` / `built on <ID>` / `built atop <ID>`
- `wait[s]? for <ID>` / `waiting on <ID>`
- Any "Context" / "Background" / "Problem" section that lists another spec ID with a dependency-implying verb

For each ID found in the body but **NOT** present in the frontmatter `after:` array:

1. Show a clear warning:
   ```
   ⚠ Drift: spec body mentions {ID} as a dependency, but it is not in `after:`.
     Found in: "<10-word excerpt around the match>"
     Frontmatter `after:` currently: [<existing list>]
   ```

2. Ask the user (do **not** auto-fix — prose can be loose, e.g. "inspired by X" or "see also X"):
   ```
   How to proceed?
   (a) Add {ID} to `after:` on main, commit, and continue
   (b) Abort the run so I can review and decide whether the prose or the frontmatter is wrong
   (c) Skip this warning and proceed anyway (rare — only when the prose is informational, not a real dependency)
   ```

3. If (a): edit the spec frontmatter, `git commit -m "chore: declare {ID} as dependency of {spec-id}"`, then re-resolve from Step 1 (the new dep might itself need running first).
   If (b): exit with a one-line summary of the drift and how to fix.
   If (c): proceed but record the decision in the run's log so the post-run review can flag it.

Authors describe dependencies in prose and forget the frontmatter, so agents either hit the missing prerequisite or re-discover it from prose. A deterministic pre-flight check beats both.

### Step 2: Mark spec `in_progress` on main (EXECUTE NOW — before anything else)

#### Advisory spec-ownership claim (SPEC-178 — parent-owned)

Before the status/branch/agent mutation below, the **parent coordinator** obtains
an advisory claim for the selected spec's resolved absolute path. This is a
coordination guard, not a distributed lock: an unavailable coordinator records a
warning and the kickoff continues.

1. Retain one local coordinator session ID for this kickoff. A newly started
   session uses `local_session_start(harness, label="nightshift-{spec-id}",
   focus="Nightshift kickoff {spec-id}")`; a resumed parent reuses its existing
   session ID. The label is deliberately spec-specific, so `local_session_list`
   alone distinguishes concurrent Nightshift runs.
2. Call `local_session_list_claims()` and find a non-expired claim whose `path`
   exactly equals the resolved absolute spec path. If another session owns it,
   call `local_session_list()` to resolve the owner label, then halt **before**
   changing status, creating a branch/worktree, or launching an agent. State the
   owning session ID, its label, and the claim age. If this coordinator already
   owns the claim, continue with claim state `reused` (same-session re-entry is
   idempotent).
3. With no matching live claim, call
   `local_session_claim_path(session_id, absolute_spec_path,
   purpose="nightshift kickoff {spec-id} run {run-id}", ttl_minutes=30)` and
   record claim state `acquired`. The purpose must contain the spec ID.
4. If any coordinator operation is unreachable or errors, record claim state
   `skipped` plus the error in the heartbeat and report, then continue;
   never fail or hang the kickoff on this advisory outage.

The spec path, session ID, TTL, and claim state belong to the parent kickoff state, not the worker brief. At each Step 5b heartbeat beat,
the parent calls `local_session_renew_claim(session_id, absolute_spec_path,
ttl_minutes=30)`. A renewal failure is a warning and does not stop the run.

On every terminal path in Step 6 (`done` **or** `blocked`), the parent calls
`local_session_release_claim(session_id, absolute_spec_path)`. It records a
release failure as a warning but still completes the terminal lifecycle state.
The report must state `Claim: acquired`, `Claim: reused`, or `Claim: skipped`,
and include any claim/release warning.

**Main freeze (SPEC-NS-KIT-001).** Request: `local_session_claim_path(sid, <hooks/main-freeze.sh key>, purpose="main-freeze: <reason>", ttl_minutes=30)`; `local_session_renew_claim`/`local_session_release_claim` extend/end it. A non-holder's commit or merge on main is refused ("BLOCKED by main-freeze lease (SPEC-NS-KIT-001)": holder, reason, expiry; unresolved committer: set `NIGHTSHIFT_COORDINATOR_SESSION`). Outage fails open with a warning; `--no-verify` bypasses.

**One-call ownership answer.** When asked who owns an `in_progress` spec, the
coordinator performs this bounded ownership query and returns one verdict: first
match `local_session_list_claims()` by the resolved absolute path; for a live
match, enrich it from `local_session_list()` with owner session ID, label, and
age. With no live claim, inspect only the matching branch and verified worktree.
If neither exists, return explicit **unowned** — never infer ownership from the
stored `in_progress` marker. Skip `_`-prefixed template files when scanning
specs. Coordinator outage returns **unknown (claim service unavailable)**, never
an unsafe `unowned` verdict.

> **This is the very first action after resolving the spec. Read only
> `nightshift_state.policy` first, using `private_state.py policy`; an invalid value
> stops before mutation or launch. Missing means `commit-backed`. Do not infer mode
> from `.gitignore` or remote visibility.**

#### Commit-backed (default)

Execute the existing three actions below. Each is a separate tool call.

**2a. Edit the spec file:**

```
Edit({
  file_path: "<absolute path to>/specs/<spec-id>-*.md",
  old_string: "status: ready",
  new_string: "status: in_progress",
})
```

(If the spec is already `in_progress` from a prior aborted run, skip 2a and go directly to 2a2. Do not regress the status.)

**2a2. Record the SPEC-291 transition artifact — before the commit.** This
edit is a mechanical `ready -> in_progress` transition, so its reason
synthesizes from the run ID with no prose required. Run this *before* 2b so
the artifact file exists on disk to be staged in the same commit — writing it
after would leave it untracked, which corpus validation would then flag as an
orphan/untracked finding on the very next run:
```bash
python3 .nightshift/spec_artifacts.py record-transition <spec-file> \
  --from ready --to in_progress --run-id <run-id>
```
A non-zero exit means the transition was classified as a judgment transition
(unexpected for `ready -> in_progress`) — pass `--reason "<why>"` and retry
rather than skipping this step; it is what R3 makes durable and what Step 6
below, and the board panel, both read back.

This same call also upserts the spec's `## State rationale` section
(SPEC-357) — the current declaration of *why* the spec is in this status,
distinct from the derived run-state explanation. No extra step is needed;
`record-transition` is the one shared capture routine for every kickoff/
terminal/unblock boundary. Pass `--reconsider-when "<...>"` whenever `--to`
is `draft`/`planned`/`blocked` (required, refused otherwise), and
`--state-evidence '{"kind": "file", "path": "..."}'` (repeatable) for any
typed evidence locator worth recording.

**2b. Commit on main with the spec file and its artifact directory staged.**
The artifact directory is a sibling of the specs directory's `reports/`, not
bare `reports/` from the project root — `.nightshift/reports/<spec-id>/artifacts/`
in a deployed project, `canonical/reports/<spec-id>/artifacts/` in this kit repo:

```
Bash({
  command: "cd <project-root> && git add <relative spec path> <specs-dir-sibling>/reports/<spec-id>/artifacts/ && git commit -m 'chore: mark <spec-id> in_progress'",
})
```

If `git status` shows other staged changes from earlier work, **stash them first** (`git stash push --staged`) so this commit is clean. Restore the stash after launch.

**2c. Verify the commit landed — HARD GATE:**

```
Bash({
  command: "cd <project-root> && git log --oneline -1",
})
```

The output must show `chore: mark <spec-id> in_progress` as the latest commit. If it does not, the commit failed silently — stop and investigate. **Do not proceed to Step 3 until you see this commit in `git log`.**

The board picks up the status change within ~10s of the commit.

#### Private-local (explicit opt-in)

The parent coordinator calls `transition_private_state(..., "in_progress",
owner="coordinator", assigned_spec=<spec-id>)` from the installed
`private_state.py`, using `StatusStore.for_specs_dir`. Record its returned
`run_id`; that durable local lifecycle event replaces the lifecycle commit proof.
Verify all of the following before Step 3:

- frontmatter and the status reader both show `in_progress` with the same run ID;
- `HEAD` and `git write-tree` are byte-for-byte unchanged;
- `private_state.py privacy-check` passes for every configured private path.

Never stage or force-add private Nightshift state. A worker cannot own this call.

Run 2a2 here too, exactly as above — the artifact is a spec-side record, not
private state. Unlike commit-backed, private-local makes no lifecycle commit
at all (`HEAD`/`git write-tree` stay byte-for-byte unchanged), so the artifact
file lands on disk untracked until a later ordinary commit (e.g. the run's own
implementation commit) picks it up; do not force a commit here solely to
track it, since that would break the byte-for-byte invariant above.

### Step 3: Read config

Read `.nightshift/config.yaml`:
- `runner.mode` — `inline` or `orchestrator`
- `commands.build`, `commands.test`, `commands.lint`, `commands.type_check`
- `commands.test_fast` (optional, SPEC-396): the worker hand-back tier. A worker
  runs it at its Step 9 hand-back check instead of `commands.test`; it is the same
  suite minus the tests marked `slow` or `browser`. `commands.test` stays the
  complete suite that verifiers, preflight dispatch and the release gate run, and
  the release gate's full-suite run remains the proof of record. Absent key: workers
  run `commands.test`.
- `project.language`, `project.name`
- `circuit_breaker` thresholds

If config.yaml is missing or unreadable → error: "Run `/nightshift validate` first."

### Step 3b: Bind the stable observational checkpoints

Both normal `$nightshift run` and `$nightshift kickoff` use the same mandatory
standalone launcher. This is the executable binding for SPEC-230; prose
mentioning an event is not publication. Invoke it as a new process exactly at
the five boundaries named below. Do not define a shell function or depend on
variables from an earlier fenced block: shell state does not persist across
agent tool calls.

For every command below, replace `{RUN_ID}` with the already-durable run ID from
Step 2, `{SPEC_ID}` with the resolved exact spec ID, and `{RUN_KIND}` with the
literal `run` for `$nightshift run` or `kickoff` for `$nightshift kickoff`.
Those three values remain identical for all five calls. Never execute a command
that still contains braces. The launcher discovers its private/configured
roots, chooses a PyYAML-capable runtime, records failures privately, and always
returns success on an extension-side failure; it never replaces the
authoritative run result.

Immediately after the durable `in_progress` state and run ID exist, execute:

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event run.started --outcome unknown
```

Each later block independently invokes the same launcher. It derives the next
contiguous sequence from the durable spool, so paths that do not reach a
checkpoint do not fabricate it. When approved artifact references exist, place
their closed JSON list in an ignored/private file, set the private
`NIGHTSHIFT_EXTENSION_ARTIFACT_ROOT`, and append
`--artifact-refs-file <private-file>` to that one invocation; raw artifacts stay
below the private artifact root.

