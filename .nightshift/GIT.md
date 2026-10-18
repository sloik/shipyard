# Nightshift Git Policy

**Source of truth:** This file owns Nightshift's git workflow semantics. `config.yaml`
and `config-reference.yaml` define the machine-readable configuration surface.
`hooks/` implements enforcement. Other protocol docs should reference this file
instead of restating the policy.

---

## Configuration Surface

Nightshift reads git behavior from `config.yaml` -> `git`:

- `main_branch`: target branch for completed work, default `main`.
- `branch_prefix`: prefix for spec branches, default `nightshift`.
- `commit_style`: `conventional` or `simple`; default `conventional`.
- `commit_prefix`: `spec-id` or `none`; default `spec-id`.
- `worktrees`: `auto`, `enabled`, or `disabled`; default `auto`.
- `merge_strategy`: `no-ff`, `squash`, or `rebase`; default `no-ff`.
- `merge_on_pass`: when true, merge after tests and review pass.
- `diff_risk_threshold`: staged added-line threshold requiring human sign-off,
  default `500`.
- `token_cost_threshold`: staged diff token estimate threshold requiring human
  sign-off, default `8000`.
- `escalation_signoff_env`: environment variable accepted by the pre-commit
  hook after explicit Lukasz sign-off, default `NIGHTSHIFT_ESCALATION_SIGNOFF`.

Config files document fields and defaults. This file documents how those fields
are used by the loop, orchestrator, hooks, and human review.

### `deployment:` composes with `merge_on_pass` (SPEC-294)

`deployment:` is optional and absent by default; when absent, `merge_on_pass`
is the only merge decision, exactly as above. When a project opts in,
`deployment:` adds a *further* condition on top of `merge_on_pass` -- it never
replaces it. `merge_on_pass: false` still means "never auto-merge, leave on
branch," regardless of environment. `merge_on_pass: true` with a candidate
resolved to an `authorize` environment means "prepare to merge automatically,
but not until a human authorization artifact exists for this exact SHA" -- see
ORCHESTRATOR.md's "Serialized integration queue and fresh-main validation"
section for the hold mechanics. `auto_merge`-resolved candidates in an opted-in
project behave exactly as `merge_on_pass: true` already does.

Nightshift control-state persistence is selected separately by
`nightshift_state.policy`. Missing means `commit-backed`; `private-local` must be
explicit. Invalid values stop before any lifecycle mutation or worker launch.

## Baseline and Dirty Tree

Before selecting a spec, the loop verifies the git working tree is clean.

- Dirty tree means uncommitted changes exist.
- The agent must stash, commit, or ask for human direction before touching specs.
- Preflight diagnostics do not create commits. They establish baseline health.
- If bootstrap creates a new git repository with `git init`, the session must stop
  and restart so worktree-capable harnesses can see the repository state.

## Spec Status Commits

Spec status changes are committed immediately so the board, orchestrator, and
future sessions agree on ownership.

These commits apply to the default `commit-backed` policy. In `private-local`
mode the coordinator instead calls `private_state.transition_private_state` to
write the selected ignored spec frontmatter and append the matching checkpoint
to the existing `StatusStore`. The durable local event supplies the stable run
ID. Workers cannot transition state, and terminal transitions are idempotent.

- When a spec is selected: set `status: in_progress` and commit
  `chore: mark <spec-id> in_progress` (no trailers; the hook accepts exactly this form).
- When a spec completes: set `status: done` and commit
  `chore: mark <spec-id> done` (with the terminal trailers, SPEC-221). The bracketed
  `[<spec-id>] chore: mark ...` form is rejected: metrics reads only the exact form.
- In orchestrator mode, the parent marks `in_progress` on `main` before launching
  a worktree sub-agent. Worktree-local status changes are not visible to the board
  until merged.

Use the source fingerprint guard when fingerprint metadata exists; stale
source-of-truth writes must be reconciled before overwriting frontmatter.

Terminal reconciliation is never newest-write-wins. A matching immutable
terminal decision plus durable lifecycle checkpoint outranks file status and
mtime. Board reads may reconcile newer nonterminal frontmatter inward only to
another nonterminal state; they cannot manufacture `done` or `blocked`.
Coordinator recovery projects terminal truth outward through the path-only
projector. StatusStore derives exact before/expected hashes from the clean
base-HEAD blob before accepting a receipt, and recovery recomputes the same
contract independently. Only dirty bytes equal to that canonical target may be
committed on replay; self-asserted hashes provide no authority. The StatusStore
is durably bound to the repository's normalized Git common directory either
intrinsically by location or explicitly at construction; projector use never
claims an unbound store. Each receipt also binds the exact checkout root. Linked worktrees may share the
common-dir owner, but an independent byte-identical clone cannot substitute for
it during admission or recovery. Dirty mixed or
opposite terminal edits are retained for explicit recovery; a clean tracked
opposite value is safely corrected with the canonical `chore: mark` commit and
trailers.


### Complete first terminal projection (BUG-NS-KIT-167)

The public parent queue seals v12 completion inputs before its first `started`
receipt: exact candidate/run/decision/repository bindings, accepted evidence and
verifier classifications, measured or unavailable parent tally, rationale and
hash-bound existing checked-LE proof. Its immutable closure contains the spec,
official status-transition artifact and index, committed together through normal
hooks. No requirement, AC, scope, dependency or checkbox fact is manufactured.
Staged validation reads inert captured index proof blobs, including referenced
project-root files; worktree replacements cannot override the captured proof.

An accepted application decision remains `done` if tracked projection or cleanup
is pending. API/board/CLI diagnostics name the actual reason and
`queue.recover_terminal_projection(handle)` action. Retry reuses the sealed
closure and existing candidate/fresh-main acceptance: no application test, merge
or replacement admission is replayed. A pending kit release remains separate
from application completion. Genuine older status-only receipts retain the
receipt-bound recovery path below.

Pending projection: read `terminal_projection` diagnostics in API/board/CLI; this section records the recovery action.

### Receipt-bound completion metadata recovery (SPEC-NS-KIT-150)

For a v12 pending `done` projection rejected by rationale or checked-LE evidence
validation, the parent may call
`queue.recover_terminal_projection(handle, metadata_recovery=request)`. Keep the
accepted candidate, merge, fresh-main proof, immutable terminal decision and
original `started` projection event. The exact old status-only target must still
be present. By default recovery requires its original base HEAD. No application
suite is invoked.

Build `request` from that original event's entire `payload`, adding exactly:

```python
request = {
    **original_event["payload"],
    "original_event_id": original_event["event_id"],
    "spec_id": handle.spec_id,
    "run_id": handle.terminal_run_id,
    "reason": "Parent accepted completion with the retained evidence",
    "created": "2026-10-09T18:01:00Z",  # explicit UTC, retained for replay
    "le_evidence": {
        "LE1": {"path": "canonical/reports/existing-proof.json",
                "sha256": sha256(existing_proof_bytes).hexdigest()},
    },
}
queue.recover_terminal_projection(handle, metadata_recovery=request)
```

If unrelated committed work has advanced main, the parent may add exactly one
optional field: `request["recovery_base_head"] = pinned_full_commit_sha`. Capture
the current HEAD's complete 40-character commit identity separately; a branch
name, `HEAD` alias or an unpinned observation is invalid. The pinned commit must
descend from the immutable original receipt base, and its committed spec blob
must equal the original before blob. Initial working spec bytes must still equal
the original pending target. Recovery preserves the descendant's unrelated
committed and staged content, derives artifact history from that pinned snapshot,
and appends the separate recovery base to its metadata link before any write.
The one terminal commit and crash replay must prove that exact pinned parent.
Unexpected movement after pinning, a non-descendant, changed committed original
spec or edited pending bytes refuses recovery. Omitting this field retains the
original-base-only refusal; never replace the original event, base or hashes.

Evidence paths are repository-relative safe regular local files: no absolute,
parent escape, symlink, hardlink or remote locator. Existing proof must remain
available with the bound content hash during recovery and replay. Only already
checked LE items lacking inline references may be annotated. Recovery never
checks an item or changes its wording, R/AC text or checkboxes, scope,
dependencies or release ownership. Supply every missing reference; an incomplete
or invalid target fails the ordinary validator before integration-tree writes.
The reason is a parent declaration: structural validation does not establish
that an observation is true.

The implementation derives a deterministic target through the official indexed
status-transition/rationale capture routine in a disposable snapshot. It appends
`metadata_started` linking the original event/request to all target closure
hashes, then writes and commits only the spec plus its changed artifact/index
closure. Ordinary hooks remain enabled; unrelated index entries and files are
preserved. Postconditions bind the exact parent, terminal subject/trailers,
changed paths and committed blobs before `metadata_completed` or queue cleanup.
The original `started` event remains unchanged. A competing request is refused.

After a crash or hook refusal, repeat the same public call. Once the recovery
link exists, `queue.recover_terminal_projection(handle)` can also replay its
stored request. Before-write, after-write and after-commit interruptions converge
without another terminal commit. Edited pending bytes, moved HEAD, changed proof
or unrelated closure/index content require explicit parent diagnosis; do not
rewrite the receipt or reset unrelated state to force recovery.

This API is a canonical portable rehearsal until a qualifying whole-kit release.
Canonical authoring still requires the original SPEC-365 admission receipts and
independent exact-candidate acceptance through the existing parent-owned
`authoring_provider` seam. The pending release handoff and whole-kit rollout
remain coordinator-owned. A rehearsal is no claim of released CJQ closure and
provides no installed-copy or receipt-refresh exception.

Main-merge failures use a separate coordinator-owned durable classification.
Before `git merge`, append the exact main/candidate identity and retry number.
A zero exit proves success only through an exact clean two-parent merge shape or
a candidate already contained by unchanged clean main. A first cleanly aborted
content conflict, false-success postcondition mismatch, or interruption is held for one exact
restart retry; a second becomes immutable `blocked`. A non-conflict command
failure on unchanged clean main blocks immediately. Any dirty/divergent main or
candidate identity mismatch remains held with recovery inputs intact. Never
report these as validation or checked-revert failures, never expose `done`, and
never clean the candidate worktree/branch from a failure disposition.
Keyed prepared replay must reconcile the matching merge ledger through the same
parent, reachability, deterministic-tree, and cleanliness proof before running
validation. Its observed and declared surfaces must be canonical and match the
durable ledger exactly; declared surfaces must also match the candidate handle.
Repository-relative surface paths reject absolute paths, traversal/dot and
internal-empty components, backslashes, URI forms, and platform drive aliases.
The existing single trailing `/` directory marker remains valid only for
declared/reserved touch surfaces; values are compared exactly, never rewritten.
The candidate, main, spec, run, and bounded attempt identity must match. Missing,
malformed, or mismatched identity is retained as a reason-coded hold. The
prepared intent and parent shape alone never authorize `done`.

### Shared-branch correction safety (SPEC-275)

Scope every `git add` to its exact intended path. That protects the index, but
it does **not** protect `HEAD`: on a shared branch, `git commit --amend` is never
permitted because another session may have advanced `HEAD` after the caller's
commit and amend would rewrite that other session's history.

If an exceptional same-session amend is contemplated outside a shared branch,
capture the exact 40-character `git rev-parse HEAD` value immediately after the
caller's own prior commit, then require it before the amend:

```bash
python3 .nightshift/record_metrics.py \
  --verify-amend-head <captured-40-character-sha> --repo . && \
git commit --amend
```

A mismatch is a hard stop, not a warning. Do not use Git author/email identity
as a substitute: concurrent sessions can share it. For a wrong terminal trailer,
create a separate correction commit with a subject that does not match
`MARK_COMMIT_RE`, put the corrected trailers on that correction commit, then run
`record_metrics.py --correct-commit <bad-terminal-sha> --repo .`. That explicitly
patches the one existing metrics row; it neither rewrites history nor emits a
second terminal transition, and the automatic post-commit path cannot reach it.

If a session discovers it has rewritten another session's commit, it stops writing
and hands the choice to that commit's owner. Do not attempt a compensating rewrite:
that would repeat the same ownership error one commit later.

## Commit Format

### Documentation exemption (SPEC-183)

`git.unprefixed_paths` lists path prefixes whose commits may use a plain
conventional-commit subject with **no** spec ID:

```yaml
git:
  unprefixed_paths:
    - "Wiedza/"
```

The exemption fires only when **every** staged path is under one of those prefixes.
A commit mixing exempt and non-exempt paths still requires `[SPEC-ID]`. The list is
empty by default, so behaviour is unchanged unless a project opts in.

**Why:** a knowledge corpus has no specs. Requiring one forces either a fabricated
ID or `--no-verify`, and `--no-verify` also skips the secret/PII scan — so the
strict rule was pushing operators toward the *less* safe path. In one repo it left
an entire vault untracked for months.

**Scope it to documentation trees.** Do not list source directories; spec
traceability for code is the entire point of `commit_prefix`.

### Spec-prefixed commits

When `git.commit_prefix: "spec-id"`, every non-merge, non-revert commit must start
with a spec prefix:

```text
[<spec-id>] <type>: <subject>
```

Examples:

```text
[SPEC-033] feat: handler registry with pluggable domains
[SPEC-033] test: add handler isolation tests
chore: mark SPEC-033 in_progress
```

Rules:

- The prefix makes every commit traceable in `git log`.
- Conventional types follow the prefix when `commit_style: "conventional"`.
- Useful bodies explain what changed and why, especially tradeoffs.
- Loop commits may include trailers such as `Nightshift-Loop:`, `Spec:`, and
  `Phase:` for machine parsing.
- Merge commits and revert commits are exempt from the prefix rule.
- Bootstrap commits may use simple setup messages before specs exist.

### Coordinator subjects (SPEC-NS-KIT-118)

`hooks/commit-msg` accepts these forms (`<ID>` is `SPEC|BUG|NFR|QUESTIONS-...-<number>`):

| Form | Example | Rule |
| --- | --- | --- |
| Ordinary | `[SPEC-033] feat: handler registry` | `[<ID>] ` plus text |
| ID-led | `BUG-022: execute the plan` | `<ID>: ` plus text |
| Lifecycle | `chore: mark <ID> done\|blocked` | need all `Nightshift-*` trailers (SPEC-221); the bracketed `[<ID>] chore: mark ...` form is rejected for every status (metrics reads only the exact form) |
| Status mark | `chore: mark <ID> draft\|planned\|ready\|in_progress\|superseded\|retired` | no trailers |
| Maintenance | `merge: SPEC-NS-KIT-134`, `telemetry: ...`, `release: ...`, `chore: ...` | no ID required |
| Conventional | `spec(BUG-NS-KIT-132,BUG-NS-KIT-133): ...`, `fix: ... (BUG-320 recurrence)` | type in feat, fix, docs, test, refactor, perf, build, ci, style, chore, spec, evidence, audit, draft, formal, research, wip; the subject line must contain an `<ID>` |
| Git-generated | `Merge ...`, `Revert ...` | exempt |

Any other `chore: mark ...` or `chore(scope): mark ...` subject (multi-ID, suffixed, `(container)`) is rejected as a malformed lifecycle subject, and a
conventional subject without an ID (`docs(specs): x`) is rejected. Install and roll back
(worktrees share the repository's `.git/hooks`, so this affects every worktree at once):

```bash
cp hooks/commit-msg .git/hooks/commit-msg && chmod +x .git/hooks/commit-msg   # install
rm .git/hooks/commit-msg                                                        # roll back
```

A whole-kit release refreshes a recognised kit `.git/hooks/commit-msg` (SPEC-NS-KIT-143), never a project-owned
or absent one, after replaying the last 30 days of commits through the new hook. If any would be newly rejected the
refresh is deferred (release output: `commit_msg_hook: deferred`, with the reasons and example subjects). Clear it by
writing `chore: mark <ID> done|blocked|in_progress` subjects and terminal commits with
`record_metrics.py --commit-terminal`; the next release then refreshes the hook. The previous hook is kept as
`commit-msg.nightshift-prev`; roll back with one line:

```bash
mv .git/hooks/commit-msg.nightshift-prev .git/hooks/commit-msg
```

## Hooks

Nightshift ships two git hooks:

- `hooks/pre-commit`: scans staged added lines for secrets/PII and escalation
  thresholds via `scanner.py`, validates staged specs when `validate_specs.py`
  is present, then runs configured `lint` and `type_check` commands from
  `.nightshift/config.yaml`.
  A command that cannot run is reported as `LINT TOOL UNAVAILABLE` /
  `TYPE CHECK TOOL UNAVAILABLE`, not as findings: exit 127, 126 or 78,
  `<python> -m <module>` with that module not installed, or a failing
  `commands.lint_probe` / `commands.type_check_probe`. It blocks the commit by
  default; a missing tool only warns when `commands.on_tool_unavailable: warn`
  is set (the hook then prints `gates not run: ...` at the end). Findings
  always block. `commands.lint_staged` (with `{files}`) opts in to linting only
  the staged files, minus `commands.lint_exclude` (default `.nightshift/*`);
  `commands.lint` stays the full-tree command. `hooks/pre-commit --check-tools`
  lists each install's configured commands and whether their tools are usable,
  read-only.
- `hooks/commit-msg`: enforces the `[SPEC-ID]` prefix when
  `git.commit_prefix: "spec-id"`, subject to `git.unprefixed_paths` (below),
  and rejects `chore: mark <id> done|blocked` unless every required terminal
  lifecycle trailer is present and non-empty. The non-terminal
  `chore: mark <id> in_progress` marker is accepted without trailers. This
  canonical repository must wire the hook like any install
  (`cp hooks/commit-msg .git/hooks/`) so the grammar is exercised here too.

### Staged spec validation (SPEC-358)

`hooks/pre-commit` validates specs by invoking
`python3 validate_specs.py --staged <repo-root>`, which reads the Git
**index snapshot** (`git ls-files --stage` + `git cat-file`) — never the
working tree — so it always checks the exact bytes about to be committed,
never a stale or since-edited on-disk copy. It fires on any commit that
adds/modifies/copies/renames/deletes a `specs/*.md` file, an
`artifacts/index.json`, or a file under `reports/<id>/artifacts/`; an
unrelated commit is not gated at all. HEAD is the baseline for
adoption/transition comparisons only; a brand-new repo with no HEAD gets an
explicit empty baseline. An unresolved (unmerged) index entry refuses
validation outright rather than guessing.

BUG-338's nearest-install resolver maps each affected path to its owning kit,
configuration and spec root. `hooks/pre-commit --resolve-owners` exposes those
four fields per path, NUL-delimited, without running checks. Canonical paths
have explicit canonical ownership; ambiguous root ownership refuses. Each
affected install is checked once. Missing validators refuse with a sync repair
instruction. Both sides of renames and deleted artifact paths are triggers.

Findings for the `## State rationale` section follow one severity matrix: a
`WARNING: state_rationale_*` finding never blocks the commit (e.g.
`state_rationale_legacy_missing` on an untouched old spec, or
`state_rationale_record_pending` on a new draft with no record yet); any
other `state_rationale_*` finding is fatal and rejects the commit. Repair by
adding/fixing the `## State rationale` section (see SPEC-GUIDE.md) or, for a
missing record, running the `record-transition`/`author-decision` capture
command before committing — never by loosening the section or deleting it.

| Adoption/state | Section | Matching record | Severity |
| --- | --- | --- | --- |
| New draft (absent from Git baseline), or version 12 / section opt-in | Required | May be pending in draft | Missing section errors; pending draft record warns |
| New or adopted planned/ready/in_progress/blocked/done/superseded | Required | Required | Missing, malformed or stale declaration errors |
| Unchanged pre-adoption spec | Optional | No invented history | `legacy_missing` warning |
| Any byte edit to legacy nonterminal, or transition to terminal | Required | Required except draft | Backfill before commit |
| Unchanged terminal history, or metadata-only edit to terminal legacy | Optional | No invented history | `legacy_missing` warning |
| Strict planned/ready admission, including private-local runtime | Required | Required | Legacy audit exemption does not permit promotion |
| Template / main / questions / NFR family | Not required | Not required | A declared malformed section still errors outside templates |

Version/section removal cannot undo adoption. Artifact-only changes validate
declared history without adopting an untouched legacy spec. A non-Git audit can
enforce only version/section opt-in and reports `baseline_unavailable`.

The executable and imported modules are the trusted installed validator, not
code loaded from the index. It materializes only an inert temporary data tree;
no copied program is executed. Configuration, NFR declarations, records and local
evidence come from the captured index. Worktree edits cannot change those bytes.
Changing the installed validator itself changes that trust boundary; review and
CI must use a separately trusted validator executable.

Because hooks can be bypassed, CI runs that trusted executable explicitly:
`python3 validate_specs.py <specs-dir> --base-revision <merge-base-or-parent> --format json`.
Without a supplied revision, file/directory mode compares to HEAD; a non-Git
audit reports `baseline_unavailable`. `--baseline` remains the unrelated
finding-family inventory comparison and never exempts a changed violating spec.

Commit-backed specs require both record and index in the same staged snapshot.
Private-local runtime admission reads the configured private spec/report root;
its records need not enter Git. A committed declaration cannot rely solely on
those invisible files. External project/URL availability is warning-only
`state_rationale_unverified_external`; hooks perform no network checks. Structural
validity never proves prose truth: specific-but-false reasoning needs QUESTIONS
review. Terminal evidence rules remain enforced by the ordinary validator.

### Terminal lifecycle evidence contract (SPEC-221)

Every `chore: mark <id> done` or `chore: mark <id> blocked` commit must contain
non-empty values for these trailers:

- `Nightshift-Evidence-Report`
- `Nightshift-Evidence-Tests`
- `Nightshift-Evidence-Code`
- `Nightshift-Evidence-ACs`
- `Nightshift-Evidence-Verifier`
- `Nightshift-Blocker-Class`
- `Nightshift-Blocker-Scope`
- `Nightshift-Unblock-Attempts`
- `Nightshift-Unblock-Limit`
- `Nightshift-Parent-Tool-Calls`
- `Nightshift-Resolution-Kind`

The parent coordinator owns normal terminal lifecycle transitions, while workers
must not change lifecycle state or merge. The hook does not trust author identity:
if a worker authors a terminal lifecycle subject, it is held to the same trailer
contract and is rejected when that evidence is absent or empty. Ordinary commits
and `in_progress` markers remain outside this terminal gate.

Build the block with `record_metrics.py --render-terminal-trailers`, or let
`record_metrics.py --commit-terminal` assemble the message and commit explicit
`--path`s (BUG-NS-KIT-139); it refuses before git when an input is missing and
works without this hook installed. `--parent-tool-calls unavailable` is the
explicit "not tallied" value. A bracketed `[<id>] chore: mark <id> done|blocked`
commit is not a terminal transition: `--mark-commit` refuses it, and only
`--correct-commit` reads one, to repair its existing metrics row.

### Project terminal outcome records (SPEC-224)

Projects may opt in through `terminal_outcomes` in their config. The released
commit-message hook then requires a changed, conforming record for the exact
spec and terminal outcome. The contract supports `json-array` and `jsonl`
adapters plus field mappings for the fleet-safe inputs: spec ID, terminal
outcome, agent response, causal confidence, human-action flag, and evidence
references. This detects both newly inserted records and in-place edits.

Argo registers its existing `agent-outcomes.json` writer with `adapter:
json-array`, `path: agent-outcomes.json`, and `spec_id: spec`; it does not need
to rename its ledger. A missing helper or commit-msg wiring is an installation
health failure during preflight. As with every Git hook, `git commit
--no-verify` is an explicit bypass outside hook enforcement; it is not prevented
by this contract.

The scanner does not report an email address on an IETF-reserved documentation
domain (for example, `person@example.com`). That closed RFC-derived set is owned
by canonical `scanner.py`, including subdomains, and is not project-configurable;
all other email domains remain subject to the PII gate.

Install hooks during bootstrap:

```bash
cp .nightshift/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
cp .nightshift/hooks/commit-msg .git/hooks/commit-msg
chmod +x .git/hooks/commit-msg
```

### Write-scope guard (SPEC-300-003)

`hooks/protect-write-scope.sh` is a portable backstop for a spec's declared
`scope.write` (see SPEC-300 § Scope, `scope_guard.py`): the earliest point a
misplaced write can be caught before it reaches a branch the parent has to
diff, because git hooks live in the shared common directory and fire in
every worktree regardless of harness.

- **Active-spec resolution.** `scope_guard.py active_spec` — the
  `NIGHTSHIFT_ACTIVE_SPEC` env var first, then the
  `nightshift/<SPEC-ID>-<run-id>` branch name. With no active spec, only the
  two universal rules apply (a new `SPEC-*.md`/`NFR-*.md`/`*-QUESTIONS-*.md`
  must live in a known specs directory; a malformed target name — `:`, a
  newline, or leading/trailing whitespace in the basename — is never
  writable); everything else is allowed.
- **With an active spec**, `scope.write` is read from the spec **as
  committed on the configured main branch** — never from the worktree or the
  worker's own branch, so a worker cannot widen its own scope by editing
  `scope:` on its branch. Every staged path (`git diff --cached
  --name-status --diff-filter=ACDMR -M -z`, both sides of a rename) is
  classified with the shared `scope_guard.py` resolver.
- **Dedicated exit code: 96.** (`protect-live-data.sh` already owns 97.) A
  `DENY` on any staged path aborts the commit with exit 96 and prints every
  offending path, its reason code, the spec ID, and the declared `write`
  globs. Any other outcome — a resolver that fails to load, a `git diff`
  failure, an unparsable spec — is a **fail-open**: the guard prints a
  `[nightshift write-scope]` warning and exits 0, mirroring
  `protect-live-data.sh`.
- **No environment-variable bypass.** The only way to land an out-of-scope
  path is a human-approved `## Scope Amendments` row that widens `scope.write`
  on main, or removing the path from the index with `git reset HEAD --
  <path>` before committing. `git commit --no-verify` still bypasses every
  hook, as it does for all guards in this file.
- **Install:** `sh hooks/install-write-scope-guard.sh` wires the guard into
  the repository's pre-commit hook (marker `# SPEC-300-003
  protect-write-scope`, inserted above a trailing `exit 0`, idempotent,
  resolving the guard from either the Argo Home or `.nightshift/hooks/`
  layout). It refuses to touch a pre-commit hook it does not recognise
  rather than silently overwrite it — merge the marker and snippet by hand
  in that case; the refusal message names the exact text to add. The
  *managed* `hooks/pre-commit` above also calls the guard directly, when
  present, before lint/type-check — the installer is for repositories (for
  example the Argo Home primary checkout) that chain guards onto a
  hand-maintained hook rather than running the managed one verbatim.
  `hooks/guard-registry.yaml` carries the entry so
  `preflight.check_guard_liveness` reports an opted-in protected checkout
  that is missing it. `doctor` reports an uninstalled guard as finding `D7`
  and `doctor --fix` runs the installer.

### Managed install payloads are release-owned (SPEC-203)

Project installs may customize `config.yaml`, specs, reports, metrics, knowledge,
run state, and declared migration outputs. Files named by the release manifest are
immutable release payloads: the installed pre-commit path calls the managed
provenance helper through `scanner.py` and rejects a staged divergent payload.

The read-only audit reports only relative paths and hashes, using exactly three
evidence classes:

- `exact-current` — bytes match the current canonical release manifest;
- `retained-prior-release` — bytes match a complete, fingerprint-validated
  per-file manifest retained in the install's earlier release marker;
- `unresolved-divergence` — neither proof applies.

An aggregate fingerprint, modification time, Git status label, or similarity is
never per-file provenance. Missing or corrupt metadata fails closed for the
managed path while leaving application-only commits available. Preserve an
unresolved project delta in place, create or update a canonical Nightshift spec,
and ship it through the guarded whole-kit release. Doctor and release preflight
use the same audit and never rewrite the dirty worktree or index.

The hook is fast feedback, not the acceptance authority. Its rejection names
the installed release-owned path, the matching `canonical/<path>` destination,
and the canonical spec plus whole-kit release remedy. Because Git permits
`--no-verify` and unstaged edits never reach a hook, the coordinator separately
compares the admitted receipt with disk at result acceptance. A deny or
indeterminate result occurs before lifecycle, merge, post-merge validation, or
cleanup and preserves HEAD, index, branch, worktree, and divergent payload.
Only an `allow` fills the one-per-receipt acceptance slot; a deny, a mismatch and
`NS-MPI-RELEASE-SUPERSEDED` (a sealed release landed after admission) are recorded
once as attempts under `acceptance/attempts/` and never consume it. A stored allow
is read back (`receipt_check.check="stored-result"`) unless the call does not bind
the run or any payload drift is observed, which reports a mismatch or deny.

Kickoff (SPEC-NS-KIT-007): the result receipt is admitted against and checked at the worker worktree's
install; the control-plane receipt is admitted against the parent's. A control-plane
`NS-MPI-RELEASE-SUPERSEDED` earns one fresh shared admission and one re-check; a result-receipt one
ends the run `superseded` (branch and worktree preserved, spec returned to ready, re-admit and re-run);
the old candidate is never accepted under a successor's receipt.

Hooks are enforcement implementations. If this policy changes, update this file
first, then update hooks and drift checks to match.

### Receipt-bound canonical-source authoring (SPEC-365)

The strict installed-payload gate remains the default, including in a directory
named `canonical`. Environment signoffs, worker output, a regenerated admission,
or a self-labelled authority record cannot enable source authoring. Dogfooded
`.nightshift` copies retain strict protection. This policy performs no deployment.

Before dispatch the parent retains user authorization, repository common-directory
identity, exact source/worktree identity, original admission receipt coordinates,
baseline revision, approved main scope revision and policy outside the candidate's
writable surface. A legacy receipt is unchanged: the parent independently chooses
a retained Git baseline whose manifest fingerprint and complete inventory match
the receipt and records that reconstruction. The original invocation/run identity
and 24-hour freshness checks still apply; a controller run ID cannot replace them.

Only the parent injects `authoring_provider(install, spec_id)` into
`managed_payload_provenance.verify_terminal_integrity`. The provider returns
`AuthoringAnchor(authority_path, authority_sha256, main_ref="refs/heads/main")`.
The path must be external to the candidate; the expected digest and authoritative
main ref come from retained parent state. Location alone is not authentication on
a shared host. Never load this provider or expected digest from `resultAcceptance`,
worker outcomes, candidate configuration, or the authority file itself. There is
no command-line or environment authoring override.

The JSON record has schema `1.0.0` and these exact fields:

- `authorization_id`: parent-issued immutable attempt ID; `policy`:
  `canonical-authoring-v1`; `user_authorization_sha256`: retained authorization digest.
- `binding`: original Git common-directory, worktree and install-relative hashes;
  `source_relative`, `spec_id`, and `spec_path`: exact authorized repository paths/ID.
- `receipt_sha256`, `invocation_id`, `receipt_run_id`: original admission identities.
- `baseline_revision`, `baseline_manifest_fingerprint`, `baseline_inventory_sha256`:
  independently reconstructed admitted baseline.
- `scope_revision`, `scope`: approved main revision and the `write`, `deny`, `read`
  projection rederived with `scope_guard.scope_from_main` at that exact revision.
- `main_revision`, `candidate_commit`, `candidate_tree`,
  `candidate_manifest_fingerprint`: full frozen Git and manifest identities.
- `independent_verification`: normalized parent-retained `verifier_identity_sha256`,
  `verdict_sha256`, `candidate_commit`, `candidate_tree`, and `policy`. The parent
  supplies this only after independently validating the actual verdict's schema,
  identity, independence, complete AC coverage, and clean verifier footprint.

Under existing serialization, the parent pins fresh main. The candidate must be
clean, committed, and contain that exact revision. Main movement requires a new
composition, verification and authorization ID. Comparison covers the union of
baseline and candidate managed inventories: existing entries cannot disappear;
new entries need approved scope and exact runtime-resource closure; unchanged
entries keep baseline bytes/modes. Every managed file must also match its pinned
Git blob. Unsafe paths, symlinks, aliases and conflicting main changes reject.
The manifest remains the sole inventory.

Results live separately in `reports/_wip/managed-payload-integrity/authoring-results/`,
keyed by authorization ID. Atomic write-once persistence makes identical replay
idempotent and quarantines contradictory bindings/results. Original receipts and
strict indeterminate results remain immutable. Incomplete proof or artifact failure
accepts nothing and permits no lifecycle advancement, merge, post-merge validation,
or cleanup. Preserve the candidate and evidence for bounded parent recovery.

The eight entries in `TERMINAL_ENTRYPOINT_INVENTORY` are the coverage contract.
Executable callers are Coordinator, `accept_instruction_result` (all five official
instruction routes), `run_validation`, and the existing `parallel_executor`
parent `terminal_gate` callback. Instruction-only routes are LOOP, ORCHESTRATOR,
BOOTSTRAP and the canonical skill. Pass `authoring_provider` separately from
worker packets; Coordinator also accepts a parent-selected `integrity_install`
when working on canonical sources in a repository with a dogfooded install.
Its shared-control-plane check stays strict; only the selected worker gate receives
the provider. There is still one serialized integration queue and lifecycle writer,
bounded dispatch, overlap containment, and distinct fresh-main validation (NFR-001).

**First use for SPEC-365:** preserve the old strict result and original receipt;
freeze and independently review the exact new gate implementation under the
explicit prerequisite authorization. This bounded review collects evidence only:
it advances no lifecycle and merges/cleans nothing. The verifier evaluates this
contract, including negative authority and installed-drift controls, and grants no
exception. The parent validates and externally retains the verdict and exact
candidate binding, then loads only that pinned implementation and injects its
separately anchored authoring record. Missing independent verdict or external user
authorization refuses bootstrap. Changed candidate bytes require fresh independent
verification and a new authorization ID. Normal scope/release metadata gates,
independent verdict, full canonical suite, exact fresh-main suite and lifecycle
gates remain mandatory; the versioned release handoff remains pending.

### Pre-execution operational sampling authority (BUG-NS-KIT-179)

The parent injects a distinct `SamplingAnchor` through `sampling_provider` into
`prepare_verifier_dispatch`. It retains immutable approved bytes outside candidate
and verifier surfaces, an externally expected SHA-256 and pinned exact contract.
Before execution, source review pins exact requirement/amendment text, target
assertions/artifact relationship and the complete ordered command/collection tuple.
The returned `dispatch.sampling_anchor` additionally seals the neutral dispatch;
pass it separately to observation, assembly and executable public validation.
Never obtain this context from a plan, verdict, environment or self-digest. A
human-labelled amendment alone supplies no authentication. Terminal AuthoringAnchor
and original admission receipts retain their separate acceptance obligations.

Every approved member runs separately on both arms, including clean non-target
members. Tuple-wide native collection, invocation order, raw exits, source identity,
unchanged assertions and read-only footprints are independently rechecked before
one observed correction pair qualifies. Missing or altered authority/proof retains
escalation; late issue/freeze cannot be repaired by rewriting timestamps. Legacy
schema 1.0 configured declarations are unchanged. No retrospective application to
old runs, reliability/savings claim, lifecycle, merge or release authorization follows.

### Main test-status ledger commits (SPEC-NS-KIT-002-002)

The ledger is a tracked file written only by the serialized fresh-main step's parent: after a real
fresh-main run, or a deduplicated one (`reports/_wip/ledger-pending-<spec>.json`), the parent
commits the new ledger with explicit paths in its own bookkeeping commit. Spec- and report-only
commits do not change the ledger identity; a test, resource, config, gate-script or toolchain
change does. Every non-pass entry names a BUG spec and carries age and expiry; an expired entry
excuses nothing.

### The kit's own detector fixtures (SPEC-197)

A secret/PII detector's test suite has to contain secret-shaped and PII-shaped inputs, or
it tests nothing — and the scanner scans its own tests. So the kit's fixture file is
excluded from blocking, but **only** where two independent conditions agree:

1. the location matches a kit-owned fixture path anchor (a closed list in `scanner.py`), and
2. the digest of the **exact matched value** is listed in `tests/fixture_digests.txt`.

Failing either leaves the finding blocking. That is what stops this being a path allowlist:

- A **live credential** dropped into a file at the anchor path still blocks — its digest is
  not registered.
- A **registered fixture value copied into `scanner.py`, a spec, `CHANGELOG.md` or a commit
  message** still blocks — none of those is a fixture path. This is how the SPEC-183
  convention (literal trigger examples belong in the test file and nowhere else) became a
  mechanism instead of a request.

The registry stores digests, never values: a file full of literal fixture strings would
trip the gate it exists to satisfy. Excluded findings are still **printed** on every run,
marked `[kit fixture]`, so a fixture that has quietly become something else stays visible.

**It is canonical-owned and not project-configurable** — no `git:` key, no environment
variable, no CLI flag. `nightshift-sync.py` never delivers `tests/` to a project install, so
an install has no registry, excludes nothing, and cannot widen its own gate by editing a
vendored file. A missing registry is normal, not an error.

**To add a fixture:** stage it, run the hook, and copy the digest from the blocking line the
scanner prints. Do not compute it by hand — the digest covers the exact substring the rule
matched, which routinely includes a trailing quote.

### Order of remedies, when the gate fires

1. **Is the finding wrong?** Fix the pattern's precision (SPEC-183, SPEC-198). Best outcome:
   nobody has to remember anything.
2. **Is it a kit detector fixture?** It is already handled by the mechanism above.
3. **Is it real PII you have reviewed and judged safe to commit?** Acknowledge that one
   value (below). Scoped, expiring, and a tracked diff.
4. **Is it a secret you have confirmed is not a live credential?** Argo Home's
   `ARGO_ALLOW_SECRET_PII_COMMIT` override, below — broader, and the only route
   acknowledgements deliberately refuse.
5. **`--no-verify`** — effectively never. It does not skip the finding; it skips every gate
   in the kit at once, and it leaves no trace in the repository.

### What the scanner deliberately does not report (SPEC-198)

An email address on a domain reserved for documentation produces **no finding**, because
no mail exchanger for such a domain can exist, so the address cannot receive mail and
cannot identify a person. The reserved set is exactly what the RFCs reserve:

- **RFC 2606 §2** — the `.test`, `.example`, `.invalid` and `.localhost` top-level domains.
- **RFC 2606 §3** / **RFC 6761** — `example.com`, `example.net`, `example.org`.

Subdomains count: `user@mail.example.com` is as reserved as its parent.

If you expected a finding on `…@example.com` and got none, that is this rule. Every other
domain still blocks, including names that merely contain a reserved label
(`example.com.co`, `notexample.com`, `example.community`). `.local` is mDNS and `.internal`
is ICANN's private-use name — a private network really does deliver mail there — so neither
is reserved here and both still block.

The set is a closed list in `scanner.py`, owned by canonical. There is no project key, no
environment variable and no CLI flag for it; a project that wants its own domain treated as
documentation is asking for the allowlist SPEC-192 rejected on the merits.

### Accepting a reviewed PII finding (SPEC-192)

`--no-verify` is not the way to land a commit over a PII finding. It does not skip
that finding — it skips the whole pre-commit hook: the secret scan, spec validation,
lint, type check, and the `commit-msg` spec-ID check. A one-line exception should not
cost every gate in the kit.

When a finding is real but reviewed and safe to commit:

```bash
python3 .nightshift/scanner.py --staged --acknowledge-template
```

That prints one stanza per blocking PII finding — the location, the rule class, and a
SHA-256 digest of the matched value. It never prints the value itself. Paste the
stanza under `git:` in `.nightshift/config.yaml` and **fill in `expires` and `reason`
yourself**; the stanza is deliberately invalid until you do, so an unedited paste
still blocks.

```yaml
git:
  pii_acknowledgements:
    - sha256: "<digest from the template>"
      class: home_address
      expires: 2026-11-05                     # mandatory, at most 365 days ahead
      reason: "Reviewed 2026-08-08: ..."      # mandatory, >= 10 characters
```

What this deliberately does not do:

- It does not accept a file, a directory, or a rule — only that one exact value. A
  different address, or one edited character, blocks again.
- It does not last. `expires` is mandatory and bounded; leave an acknowledgement
  alone and the gate closes again on its own. A far-future date is invalid, not a
  permanent pass.
- It does not apply to secrets. Bearer tokens and API keys can never be
  acknowledged. Remove or redact them.
- It does not hide anything. An acknowledged finding is still printed on every
  commit, marked `[acknowledged]`, with its reason and expiry.

Adding an acknowledgement is a tracked change to `config.yaml`, so it shows up in
review. `--no-verify` leaves no trace anywhere — that is the difference.

### Argo Home secret/PII override

**Reach for the acknowledgement above first.** This override is broader: it is a
whole-commit, unreviewed, unrecorded pass that leaves nothing behind in the repository.
It remains the only route for the one case acknowledgements deliberately refuse — a
**secret** finding you have confirmed is not a live credential (a fixture key in a test,
for example). For PII, prefer `pii_acknowledgements`: it is scoped to one value, it
expires, and it is visible in review.

Argo Home's tracked `hooks/install-branch-guard.sh` also installs the
`SPEC-158 secret-pii-scan` shim. It fails closed if the tracked scanner cannot
run. For a reviewed false positive only, use
`ARGO_ALLOW_SECRET_PII_COMMIT=1 git commit ...`; the hook prints that the
override is active. Never use this override to commit a real secret or PII —
remove or redact that content instead.

## Branches and Worktrees

Inline mode may work directly in the current branch for small single-agent runs.
The concurrent paths require isolated worktrees: orchestrator, parallel-layers, and
multi-model comparison treat `git.worktrees: "auto"` as mandatory. In these
paths, the default setting no longer falls back to direct edits in the current
branch.

- Branch names should follow `<branch_prefix>/<spec-id>` unless the harness owns
  branch naming.
- Sub-agents work in a clean worktree with a separate context window.
- Sub-agents execute one assigned spec and return completion status, commit hash,
  and metrics path.
- The parent orchestrator owns merging, post-merge validation, and cleanup.
- Concurrent workers never merge their own branch or another worker's branch;
  they own one spec worktree while the coordinator owns lifecycle state and
  serialized integration.

Worktrees are edit isolation, not proof that branches are compatible. Parallel
admission relies on a complete dependency graph and specific `touches:` claims;
the coordinator must still compare actual changed files, serialize integration,
and validate fresh `main` after every accepted branch. Never start more workers
than the repository's CPU/RAM and isolated test resources can support.

### Private-local projection and evidence

After worktree path and owner verification, private-local mode projects only the
selected spec, installed runtime/protocol, project config, and explicitly required
knowledge into the ignored worktree `.nightshift/`. `private_state.py` rejects
symlink escapes, foreign or unsafe worktrees, tracked destinations, and partial
copy on failed validation. Other specs, reports, metrics, credentials, and ledgers
are never implicit inputs. On return, only report, metric, verification, and
heartbeat paths named by the run contract may be copied to main's private state.

Run `private_state.py privacy-check` against every configured private path before
launch and again against the worker branch diff before merge. Any tracked, staged,
or changed private path refuses integration and leaves the worktree for inspection.
Application-only commits follow the normal serialized merge path.

### Nested repos: visibility gap, write boundary, and the git-subcommand exception

A project tree can contain nested git repositories — a tracked directory that
itself has its own `.git` (a vendored clone under a scratch directory, for
example). `git worktree add` does not carry untracked or nested-repo content
into the new worktree, so an agent that checks a nested-repo path relative to
its own worktree root can get a false negative. **Worked example:** main
checkout is `/repo`, a nested clone lives at `/repo/vendor/thing/.git`, and a
spec's worktree is `/repo/.nightshift/worktrees/agent-x`. A check for
`vendor/thing/some/file` from inside the worktree finds nothing — not because
the file is missing, but because the worktree never received it. The agent
must resolve the path against the **main checkout's absolute path**
(`/repo/vendor/thing/some/file`), not assume worktree-relative non-existence
means the file doesn't exist. To enumerate nested repos in a project when
needed: `find . -name .git -not -path './.git'`.

This gap interacts with two different write-boundary rules, which behave
differently and must not be conflated:

- **General Bash file I/O is exempt from the worktree boundary.** `Edit` and
  `Write` refuse any path outside the current worktree — including a
  main-checkout path inside a nested, gitignored repo. Plain Bash commands
  that do their own file I/O (`cat`, `sed`, `cp`, a script writing files, an
  HTTPS download writing to disk) are not subject to that tool-level check
  and succeed against the same absolute path. See [Worked heartbeat publication
  example](#worked-heartbeat-publication-from-an-isolated-worktree) for the
  canonical cross-worktree heartbeat pattern.
- **Bash invocations of `git` itself are NOT exempt when they target a nested
  repo's own `.git`.** `git -C <nested-path> ...`, `--git-dir=<nested-path>/.git`,
  and `git lfs pull` run inside or against the nested repo are blocked by the
  same worktree sandbox as `Edit`/`Write`, even though they run through Bash.
  A prior assumption — "Bash git ops work, only `Edit`/`Write` don't" — is
  wrong; only *non-git* Bash file operations are exempt. If an agent needs to
  read or refresh nested-repo content and the obvious move (`git -C
  vendor/thing pull`, `git lfs pull` in the nested repo) is blocked, the
  workaround is a plain, non-git operation instead: an HTTPS download or a
  direct file write/copy to the same absolute path, per the exemption above.

### Worked heartbeat publication from an isolated worktree

When a kickoff worker must make its liveness heartbeat visible to the parent
checkout, write the complete heartbeat in the worker's own worktree and then
copy that local file to the parent-provided shared path:

```bash
HEARTBEAT_LOCAL="$PWD/.nightshift/reports/_wip/orchestrator-progress-<SPEC-ID>.md"
HEARTBEAT_SHARED="<main-repo-abs>/.nightshift/reports/_wip/orchestrator-progress-<SPEC-ID>.md"

mkdir -p "$(dirname "$HEARTBEAT_LOCAL")"
cat > "$HEARTBEAT_LOCAL" <<'HEARTBEAT'
heartbeat_state: worker-started
phase: implementation
last_action: loaded the assigned spec and required context
next_action: implement and validate the bounded change
HEARTBEAT
/bin/cp "$HEARTBEAT_LOCAL" "$HEARTBEAT_SHARED"
```

The destination is outside the isolated worktree, so `Write` and direct shell
redirection (`>`) to `$HEARTBEAT_SHARED` are refused by the worktree boundary.
The plain Bash `/bin/cp` command is permitted because it copies an already
worktree-local file through normal Bash file I/O rather than using those
boundary-checked write mechanisms. This copy is the supported way to publish
the heartbeat without writing directly to the parent checkout.

## Worktree Cleanup and Retention

All Nightshift-created worktrees MUST use the canonical resolver; never place them
beside a project (`../run-*`, `<project>-nightshift-*`) or below the checkout's
`.nightshift/` directory. Both locations are commonly synchronized by Dropbox and
can be mistaken for real projects.

```bash
WT=$(python3 .nightshift/worktree_paths.py plan --repo "$PROJECT_ROOT" --spec "$SPEC_ID")
git -C "$PROJECT_ROOT" worktree add -b "nightshift/$SPEC_ID" "$WT"
python3 "$PROJECT_ROOT/.nightshift/worktree_paths.py" verify \
  --repo "$PROJECT_ROOT" --worktree "$WT"
python3 "$PROJECT_ROOT/.nightshift/worktree_local_config.py" copy \
  --repo "$PROJECT_ROOT" --worktree "$WT"
```

The resolver uses a deterministic local temporary namespace containing a hash of
the repository path. The verify step compares Git common directories, so an equal
project basename, branch name, or path prefix cannot redirect a merge or cleanup to
another repository. `NIGHTSHIFT_WORKTREE_ROOT` may override the temporary base, but
the resolver rejects overrides inside the repository or its synchronized ancestor.

Nightshift runs a mechanical startup janitor before concurrent execution starts.
The janitor enumerates `git worktree list --porcelain`, maps linked worktrees
back to the current project's specs, and delegates eligible resources to the
same coordinator-owned `CheckedCleanupProtocol` used after integration. Foreign,
wrong-repo, or incompletely owned worktrees are retained.

Retention is status and marker based:

- `done` worktrees are garbage-collection candidates.
- `blocked` and `failed` worktrees are garbage-collection candidates only when
  the worktree root does not contain `.nightshift-keep`.
- `.nightshift-keep` pins a blocked or failed worktree for human inspection.

Cleanup is permitted only after the immutable terminal decision, matching
durable lifecycle status, and clean committed terminal frontmatter agree for the
same run. `CheckedCleanupProtocol` records an exact owner inventory in the
append-only `cleanup_events` table before any Git mutation. Cleanup evidence is
distinct from the current lifecycle checkpoint: retries cannot rewrite status,
decision identity, accepted completion evidence, or terminal metrics.

The recorded owner binds repository common directory, canonical worktree path,
exact branch ref, and candidate revision. A retargeted ref or substituted replay
handle is retained. Blocked or otherwise unmerged work receives a durable
`refs/nightshift/recovery/<spec>/<run>` ref pinned to the candidate before the
last worktree/branch reachability roots can be removed. A first attempt cannot
claim an arbitrary absent path or ref as released; only a prior exact `started`
inventory plus current Git-confirmed absence permits interrupted-operation
reconciliation.

Every `git worktree remove --force` and `git branch -D` result is checked, then
Git is re-inventoried to prove the requested postcondition. Partial or failed
cleanup records every retained/released worktree, branch/ref, keep marker, and
recovery ref with a reason code. Exact-owner retry is idempotent after either
terminal outcome and never chooses another terminal value. A stale `completed`
event is also re-inventoried. The exact durable owner path is checked with
non-following filesystem inspection as well as Git registration; an ordinary
directory, file, symlink (including a broken symlink), registered worktree, or
ambiguous/foreign entry at that path is retained and never followed or deleted.
Recreated or retargeted branch/recovery refs are retained as well.
Legacy fan-in and worktree preparation retain existing resources rather than
performing cleanup outside this protocol.

The janitor continues to classify an unmerged candidate that it cannot safely
bind to this protocol as `unmerged — manual`; merge-path cleanup and concurrent
paths never bypass the checked owner.

## Merge and Post-Merge Validation

Completed spec work merges to `git.main_branch` according to `git.merge_strategy`
when `git.merge_on_pass` is true.

For parallel work, `SerializedIntegrationQueue` is the coordinator-owned sole
merge authority. It takes completed worktree branches in deterministic spec-ID
order, checks both declared surfaces and `git diff --name-only main...branch`,
reconciles each candidate against current main, and merges exactly one candidate
at a time. Workers never run `git merge` into main.

If a candidate conflicts or overlaps accepted work, it is held with its
worktree intact. If fresh-main validation fails, the queue returns raw output to
the originating worker for the bounded repair cycle. On exhaustion it reverts
the merge, blocks only transitive descendants, and retains unmerged work for
inspection. Cleanup is permitted only after an accepted, green main merge.

After every merge:

1. Checkout the configured main branch.
2. Run the resolved build and test commands on main.
3. Verify the spec is `status: done`.
4. If validation passes, continue.
5. If validation fails, fix on the branch and re-merge; if that fails, revert the
   merge commit and record the failure.

Main must stay green. A successful branch test is not enough.

If a parallel candidate is held, conflicts, or fails fresh-main validation,
retain its unmerged worktree for inspection. Reconcile/rebase that one branch or
revert its merge before resuming; do not delete commits unreachable from main.
Only descendants of the failed spec are blocked. Unrelated frontier work may
continue under the same sole coordinator.

## Human Review

Human review should inspect commits as the durable audit trail:

- Walk the log for the Nightshift run.
- Read commit messages for clear rationale and appropriate granularity.
- Inspect key diffs with `git show`.
- Confirm commit format follows this policy unless explicitly disabled.

The review question is not only "did tests pass"; it is whether the history tells
a coherent, reversible story for each spec.


## Receipt-bound invalid-run abandonment (SPEC-387-001)

This bounded installed-project recovery applies only to an original wrong-run
identity rejection followed by an immutable corrected-retry contradiction. It
never authorizes terminal acceptance, candidate merge, completion or cleanup.
Canonical authoring remains the separate SPEC-365 contract above. Expired
receipts may be inspected for this rejected administrative decision only;
`verify_terminal_integrity` still rejects expired result acceptance.

The parent injects `managed_payload_provenance.AbandonmentAnchor` through a
callable `abandonment_provider(install, spec_id)`. Its positional inputs are an
externally retained authority JSON path, exact SHA-256, frozen old candidate
checkout, and, for successor B, canonical release source and release root.
Authorization and independent-verifier validation are parent responsibilities;
worker packets, environment variables and configuration cannot supply them.
The authority must reside outside the project, candidate, source and consumer
Git repositories and every linked checkout of them (fail closed if checkouts
cannot be enumerated).

Automatic-retry rule. It is implemented once, in
`unblock_spec.automatic_attempt_decision`, whose docstring carries this exact
text; `prepare`, `record_attempt` and the packet revalidation before every
administrative mutation call it directly, and the ordinary `prepare`,
`record_attempt` and `finalize` call it through `_ordinary_decision`:

<!-- automatic-retry-rule -->
Automatic recovery attempts are keyed by the current blocker fingerprint. This
rule governs every automatic attempt, administrative and ordinary alike. Retry
state is the durable status-store ledger alone: durably issued packets and
recorded attempt outcomes with their digests, on both routes. An attempt file is
evidence bound to its ledger digest. A ledger entry whose file is missing,
unsafe, corrupted, digest-mismatched or not bound to a durable issuance fails
closed with a named reason: it never reopens the fingerprint, never counts as no
outcome and never permits a further automatic attempt. A file without a ledger
entry is not an outcome. Any completed outcome (failed, skipped or succeeded)
recorded in the ledger on the current fingerprint by any run closes that
fingerprint to further automatic attempts; after a succeeded outcome only
finalize is permitted. `retry_override` (human) is the only way to open a closed
fingerprint. The sole exemption is a crash replay: the same run, on the same
fingerprint, presenting the same durably issued packet, with no outcome yet
recorded in the ledger for that packet; it may record exactly one outcome. A
succeeded-but-unfinalized run may finalize idempotently and may not record
again; an ordinary run whose own automatic succeeded attempt is on file may
re-prepare finalize-only (the same packet, which can only finalize). A packet is
bound to the run and fingerprint for which prepare durably issued it; a packet
copied to another run, issued for another fingerprint, or superseded is refused
at record_attempt.
<!-- /automatic-retry-rule -->

For both routes, `prepare` durably issues each packet (an append-only,
per-fingerprint issuance sequence in the status store recording run, packet,
fingerprint and `retry_override`, under the controller lock); the latest
issuance on a fingerprint supersedes earlier ones, and a packet's
`retry_override` counts only as its issuance recorded it. A same-run
finalize-only re-prepare reuses its issuance. An administrative attempt is
always automatic: a manual flag never bypasses the rule. Each outcome is
recorded in the same durable ledger with its attempt id, run, fingerprint,
outcome, evidence path and SHA-256; that ledger, never a directory listing of
`knowledge/attempts/`, is what the rule reads. The named fail-closed reasons are
`NS-UNBLOCK-ATTEMPT-EVIDENCE-MISSING`, `NS-UNBLOCK-ATTEMPT-EVIDENCE-UNSAFE`,
`NS-UNBLOCK-ATTEMPT-EVIDENCE-MISMATCH` and `NS-UNBLOCK-ATTEMPT-LEDGER-ORPHANED`.
Before writing an attempt file, `record_attempt` durably records a write intent
(stamp and digest); only that ledgered intent lets a crash replay rebuild the
identical bytes; the ledger entry follows the file. A file already at the target
path without a ledger entry is refused as `NS-UNBLOCK-ATTEMPT-LEDGER-ORPHANED`
and is never read, and `finalize` accepts only a succeeded attempt whose ledger
entry is bound to the packet's issuance and whose file matches the entry's
digest. A non-automatic, human-authorized outcome is ledgered as evidence but is
not an automatic attempt and never closes a fingerprint. The SPEC-351
repeated-failure gate reads the ledgered attempts of the spec and its parent; an
entry whose file is not intact counts as a failed attempt and is listed by name
as `integrity_failures` in the packet.

An install that predates the ordinary ledger needs no operator step: the first
ordinary `prepare` of a spec (and of its parent) adopts every parseable
`unblock_attempt` file of that spec that has no ledger entry, once, recording
its current digest as `legacy_adopted` (it has no issuance and stands as its
own, so a closed fingerprint stays closed), reports unparsable files by name and
emits `unblock_legacy_attempts_adopted`. A file that appears after adoption has
no ledger entry and is not an outcome. `unblock_spec.py adopt-legacy-attempts
--spec <ID>` runs the same idempotent adoption by hand.

<!-- ledger-integrity-wedge -->
**Integrity wedge and its human exits (both routes).** When a ledgered attempt
file is missing, unsafe or corrupt, the fingerprint is closed to every run,
including `retry_override`, with the `NS-UNBLOCK-ATTEMPT-EVIDENCE-*` reason
above; this is by design and is the only way a fingerprint can be stuck. The
exits are human: (a) re-evidence the blocker, which gives a new fingerprint (the
decision record stays in the ledger); (b) restore the file's exact bytes, whose
digest is in the ledger entry; (c) repair the status store outside the protocol,
which is outside the threat model and must be recorded by hand. There is no
protocol repair action by design (owner decision on SPEC-421 F6).
<!-- /ledger-integrity-wedge -->

`record_attempt` and `finalize` route by the presented packet alone: a packet
carrying `invalid_run_abandonment` (stamped by administrative `prepare`) is
verified against the durable decision and issuance ledger, and a forged marker
is refused; any other packet runs the ordinary controller, whose `issuance_id`
is its own durable issuance. A stripped administrative packet's attempt file
has no ledger entry, so it is never an outcome, and ordinary `finalize` refuses
to move an administrative blocker to ready; ordinary `record_attempt` refuses an
administrative blocker the same way, before writing. The SPEC-351
repeated-failure gate is re-evaluated at `record_attempt` from the ledgered
attempts, not from the packet pinned at prepare; both refusals emit
`unblock_decision_refused`.

Abandonment fails closed over a live unrelated blocker: if the spec is already
blocked for any reason other than this same rejected run's retained evidence, it
refuses with a named reason and changes nothing; a human resolves that blocker
first. The check runs inside the same controller lock as the administrative
blocked write, and a related prior blocker's fields are moved into
`unblock_history` as `superseded_blocker`, never silently overwritten. A failed write of the sanitized rejected-replay quarantine record never
turns a rejection into success and is named in the rejection reason. The record uses schema `1.0.0` and policy
`receipt-bound-invalid-run-abandonment-v1` with these exact fields:

- `authorization_id`, `user_authorization_sha256`, `binding`, `spec_id`, `spec_path`;
- `receipt_ref`, `receipt_sha256`, original `invocation_id`, rejected `wrong_run_id`;
- original `baseline_revision`, frozen `candidate_commit`, `candidate_tree`,
  `candidate_binding`, enumerated `control_paths`;
- `retained_evidence`: exact `admission`, `acceptance`, `quarantine`,
  `failed_verifier` references, each `{path, sha256}`;
- `independent_verification`: the existing normalized AuthoringAnchor verifier
  identity/verdict digest, candidate commit/tree and policy contract;
- `active_release`: exact `fingerprint`, `inventory_sha256`, `marker_sha256`,
  `installed_revision`, and `rollout` (null only for complete original A).

Bindings are the existing `_git_binding` project/common-directory/checkout/install
hashes, independently reconstructed by the parent. A lifecycle commit SHA is
never the receipt invocation identity. Control paths are selected spec and
explicit report files only; application changes and other evidence changes stop
recovery. Every release proof reconstructs the complete inventory and modes from
pinned Git blobs and checks current bytes, markers, manifests and unsafe aliases.

For B, `rollout` contains `source_binding`, `source_relative`, `source_commit`,
`source_tree`, `release_root_binding`, `report`, `invocation` and `lineage`.
Lineage is exactly `{predecessor: A_fingerprint, successor: B_fingerprint,
authorization_sha256: user_authorization_sha256}`. Retain the original successful,
non-dry-run target-only `release_coordinator.coordinate_release(canonical,
installs=[exact_install], manifest=manifest, dry_run=False, release_root=root)`
report using official `release_coordinator.write_metrics`. Both report and actual
invocation evidence live in ignored target-local `reports/_wip/` paths with
externally pinned digests. The actual invocation record contains exactly `api`,
`metrics_writer`, `canonical`, `installs`, `dry_run`, `release_root`,
`manifest_sha256`, `source_observed_inventory`, `source_commit`, `source_tree`,
`report_sha256`. The observed inventory has path, actual SHA-256 and executable
mode for every source entry and must equal committed B. Independently pin it at
the original invocation. A later replay, no-commit replay report, CLI fleet
release, partial or replaced report cannot substitute for that proof. The report
must establish one verified target, A's predecessor fingerprint, the exact
committed installed B revision, passing real suite and smokes, and no conflict,
rollback, skipped target or file patch. Central skill delivery is separately
represented by the exact authorized release root.

Supported parent APIs (no administrative CLI or worker-deserialized authority):

1. `managed_payload_provenance.verify_invalid_run_abandonment(install,
   spec_id=..., abandonment_provider=...)` performs read-only proof.
2. `unblock_spec.abandon_invalid_run(spec_file, install,
   abandonment_provider=...)` persists one distinct atomic rejection decision
   (via `managed_payload_provenance.record_invalid_run_abandonment`)
   and the existing durable administrative **blocked** projection.
3. Only existing `unblock_spec.prepare`, `record_attempt` and `finalize`, each
   with the same `abandonment_provider`, may verify recovery and reach ready.
   Every mutation/restart revalidates all original A and exact active B proofs.
4. `Coordinator(..., abandonment_provider=...).abandon_invalid_run(spec_id)`
   and `nightshift-instructions.py::abandon_instruction_run(packet,
   nightshift_dir=..., spec_file=..., official_path=...,
   abandonment_provider=...)` route official coordinator, inline-run, kickoff,
   board-copied-kickoff, direct-loop and direct-orchestrator recovery here.
   Parallel terminal callbacks retain coordinator-owned strict acceptance.

The distinct decision is `reports/_wip/managed-payload-integrity/abandonment/`
plus the original invocation JSON filename; it declares `rejected-old-run`,
reason `NS-MPI-INVALID-RUN-ABANDONED`, eligible controller, demonstrated causal
confidence and no additional human action. Sanitized contradictory replays are
quarantined in that separate namespace. Old receipt, admission, strict rejection,
quarantine, verifier and frozen candidate bytes remain unchanged. Identical
replay resumes matching ownership without a second successful outcome. After
ready, admit a genuinely new worker/run from the fresh baseline and retain its
own original receipt. The abandoned invocation, result and candidate remain
permanently rejected.

### Implementer-assessed terminal blocks (BUG-NS-KIT-173)

`implementer-assessed-blocked` is a blocked-only resolution kind backed by the
actual closed reducer state. Use `record_metrics.py --commit-terminal` with
`--assessment-state` instead of a verdict; stage the state and lifecycle evidence.
The normal commit hook validates state digest, original candidate and inventories.
It cannot mark Done, claim a verifier or replace a later independent check.

Pending release handoff source ranges use `release_handoff.pin_commit_range` before their normal authoring commit (SPEC-NS-KIT-192). Preserve original spellings and bind actual immutable endpoints, repository and bounded diff; unresolved legacy history stays unresolved. Checked cleanup requires main ancestry or its exact owned recovery ref to retain both endpoints, preserving uncommitted disposable handoff evidence and refusing unknown provenance. A SHA string is not a Git reachability root. The sole integration/cleanup owner and completed receipts remain unchanged.


### Equivalent self-spec reconciliation

SPEC-NS-KIT-172 adds an opt-in parent-provider capability to the existing
`SerializedIntegrationQueue`; it is not semantic merging. Default queues retain
strict conflict refusal. First obtain the ordinary durable held conflict under
the original accepted immutable candidate/run. The existing single retry is the
only mutation attempt available; no new run, rebase or candidate verification is
manufactured to reset that budget.

A trusted parent supplies `SelfSpecReconciliationAuthority(approval_path,
approval_sha256, verification_path, verification_sha256)` through
`selfspec_reconciliation_provider(handle)`. Both hash-pinned JSON files must be
outside the subject/worker repositories. Candidate config, spec text, handle
outcome and checkbox claims grant no authority. Require the original managed
admission receipt and current terminal integrity check, accepted completion input,
and a configured real fresh-main gate. A custom `merge_runner` is ineligible.

Both parent records bind `spec_id`, original `run_id`, unique original `base`,
`main_before`, original `candidate`, assigned repository-relative `spec_path`,
original receipt `binding`/`receipt_sha256`, and `contract_sha256` of the narrowly
normalized complete spec. Approval additionally requires `approved_by: human:<owner>`
and `amendments_sha256` over the exact Scope Amendments and AC Amendments section
bodies in that order (missing sections contribute no bytes). The parent's accepted
independent-verifier projection additionally requires `producer: independent-verifier`,
`independent: true`, `verdict: pass`, and sorted exact `checked_items` for every
candidate-checked R/AC. This projection must come from original accepted independent
evidence; the reconciler does not author acceptance or approvals.

Call `queue.propose_selfspec_reconciliation(handle)` after the first held conflict
for the deterministic proposal. Only existing identified Requirements/Acceptance
Criteria checkbox marker bytes normalize; IDs, order, prose, whitespace, metadata,
LE, comments, fenced examples and amendment/history bytes remain significant.
The main/candidate normalized blobs must match exactly; candidate checked items
must strictly extend main's checked items and all require accepted evidence.
Only that assigned spec may conflict. The output blob is the original candidate
blob, never edited prose or a newly ticked item.

Reset the held handle's scheduler status to completed and submit it to the same
queue API under the same run to consume its one existing retry. The queue persists
the exact blobs, parent/receipt/authority digests, original held-event linkage and
expected whole tree before any resolution write. It uses normal Git merge/commit
hooks and Git's ordinary merge result for every other path. Exact two parents and
the entire reproducible tree must match afterward. Arbitrary resolutions, additional
conflicts, stale authority, moved tips, changed receipts or changed source refuse.
No provider may choose a different resolution or approve another scope.

The merge does not establish Done. Actual configured fresh-main validation on the
exact resulting revision precedes ordinary terminal projection and checked cleanup.
Failed validation follows existing checked-revert ownership rules. Hook rejection,
partial writes, proof mismatch, concurrent user/index work or exhausted retries
preserve resources and produce a controlled hold/failure; unowned state is never
aborted or overwritten. A persisted owned merge commit can resume validation after
interruption without a second merge. Before/after-write crashes otherwise converge
only under existing exact ownership proof or stay safely held/terminally failed;
they never reset the retry budget. Query the original StatusStore merge-attempt
history for the append-only proof and outcomes. Durable/public proof records use
relative paths, controlled reasons and hashes, never private spec bodies/host locators.
A successful integration still needs its normal pending whole-kit release; no
installed patch, extra worker, LLM conflict resolver, or file-only rollout is added.

## Worktree local config (SPEC-NS-KIT-231)

After worktree ownership verify, `worktree_local_config.py copy --repo <project>
--worktree <path>` copies only `git.worktree_local_config.copy` exact repo-relative
files (default `.claude/settings.local.json`). Built-in secret path rules,
project `deny` globs and the existing scanner prevent secret copies. Absolute,
parent-traversing, outside-root, symlink and directory sources are refused.
Tracked files and existing destinations are never overwritten. An identical
existing destination is `unchanged`, a different one is `skipped/exists`; bytes,
file mode and permission rules are otherwise unchanged. No new permission or
`additionalDirectories` entry is added. Retain the JSON result list in the run
report; the kit's preparation path also persists it beside the handle's events.

`git.worktree_local_config.required: true` makes refused/failed copies fatal
before launch; `absent` remains a successful non-error. Without required mode,
copy failures warn and worktree creation continues. A harness-created isolated
worktree needs the parent to invoke this same helper after ownership verify.

**Owner approval wait (SPEC-NS-KIT-231).** Before any command that may prompt,
write `waiting_on: owner_approval`, `waiting_command: <one-line command or reason>`
and `waiting_since: <ISO-8601 UTC>` in the same heartbeat file; keep
`heartbeat_state: worker-started`. If a prompt is unexpected, declare the wait
at once. Remove these fields when you resume. Never include environment values;
command text has control characters removed and is limited to 200 characters.
A valid non-terminal declaration is `waiting_on_approval` at any age: show the
sanitized command and wait age (unknown for an absent/invalid timestamp), and
report "owner needed". Do not kill, restart or retry the worker because of this
wait; ask the worker and the owner before any stall action. Terminal states still
win. Without a valid wait declaration, the existing phase/20/40-minute ladder
and silent-worker stall behavior remain unchanged.
