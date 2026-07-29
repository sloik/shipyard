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

- When a spec is selected: set `status: in_progress` and commit
  `[<spec-id>] chore: mark in_progress`.
- When a spec completes: set `status: done` and commit
  `[<spec-id>] chore: mark done`.
- In orchestrator mode, the parent marks `in_progress` on `main` before launching
  a worktree sub-agent. Worktree-local status changes are not visible to the board
  until merged.

Use the source fingerprint guard when fingerprint metadata exists; stale
source-of-truth writes must be reconciled before overwriting frontmatter.

## Commit Format

When `git.commit_prefix: "spec-id"`, every non-merge, non-revert commit must start
with a spec prefix:

```text
[<spec-id>] <type>: <subject>
```

Examples:

```text
[SPEC-033] feat: handler registry with pluggable domains
[SPEC-033] test: add handler isolation tests
[SPEC-033] chore: mark in_progress
```

Rules:

- The prefix makes every commit traceable in `git log`.
- Conventional types follow the prefix when `commit_style: "conventional"`.
- Useful bodies explain what changed and why, especially tradeoffs.
- Loop commits may include trailers such as `Nightshift-Loop:`, `Spec:`, and
  `Phase:` for machine parsing.
- Merge commits and revert commits are exempt from the prefix rule.
- Bootstrap commits may use simple setup messages before specs exist.

## Hooks

Nightshift ships two git hooks:

- `hooks/pre-commit`: scans staged added lines for secrets/PII and escalation
  thresholds via `scanner.py`, validates staged specs when `validate_specs.py`
  is present, then runs configured `lint` and `type_check` commands from
  `.nightshift/config.yaml`.
- `hooks/commit-msg`: enforces the `[SPEC-ID]` prefix when
  `git.commit_prefix: "spec-id"`.

Install hooks during bootstrap:

```bash
cp .nightshift/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
cp .nightshift/hooks/commit-msg .git/hooks/commit-msg
chmod +x .git/hooks/commit-msg
```

Hooks are enforcement implementations. If this policy changes, update this file
first, then update hooks and drift checks to match.

### Argo Home secret/PII override

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

## Worktree Cleanup and Retention

Nightshift runs a mechanical startup janitor before concurrent execution starts.
The janitor enumerates `git worktree list --porcelain`, maps linked worktrees
back to the current project's specs, reads durable status first and frontmatter
second, and reports any worktree it cannot confidently reconcile as skipped.
Foreign or wrong-repo worktrees are never deleted by this pass.

Retention is status and marker based:

- `done` worktrees are garbage-collection candidates.
- `blocked` and `failed` worktrees are garbage-collection candidates only when
  the worktree root does not contain `.nightshift-keep`.
- `.nightshift-keep` pins a blocked or failed worktree for human inspection.

Before deletion, Nightshift checks for unmerged work with
`git log <main_branch>..<branch>` or an equivalent reachability check. If the
branch has commits not reachable from the configured main branch, the janitor
leaves the worktree and branch intact and reports `unmerged — manual`. Unmerged
work is never destroyed automatically, even for `done`, `blocked`, or `failed`
specs.

Actual deletion uses the shared cleanup primitive:
`git worktree remove --force <path>` followed by `git branch -D <branch>`. The
startup janitor uses this for stale resolved worktrees, and merge-path cleanup
uses it immediately after a done spec is merged successfully.

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
