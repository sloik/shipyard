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
  `[<spec-id>] chore: mark in_progress`.
- When a spec completes: set `status: done` and commit
  `[<spec-id>] chore: mark done`.
- In orchestrator mode, the parent marks `in_progress` on `main` before launching
  a worktree sub-agent. Worktree-local status changes are not visible to the board
  until merged.

Use the source fingerprint guard when fingerprint metadata exists; stale
source-of-truth writes must be reconciled before overwriting frontmatter.

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
  `git.commit_prefix: "spec-id"`, subject to `git.unprefixed_paths` (below).

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

Hooks are enforcement implementations. If this policy changes, update this file
first, then update hooks and drift checks to match.

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
```

The resolver uses a deterministic local temporary namespace containing a hash of
the repository path. The verify step compares Git common directories, so an equal
project basename, branch name, or path prefix cannot redirect a merge or cleanup to
another repository. `NIGHTSHIFT_WORKTREE_ROOT` may override the temporary base, but
the resolver rejects overrides inside the repository or its synchronized ancestor.

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
