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
  `[<spec-id>] chore: mark in_progress`.
- When a spec completes: set `status: done` and commit
  `[<spec-id>] chore: mark done`.
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
  `git.commit_prefix: "spec-id"`, subject to `git.unprefixed_paths` (below),
  and rejects `chore: mark <id> done|blocked` unless every required terminal
  lifecycle trailer is present and non-empty.

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
