Load when: you run `/nightshift run` or `/nightshift kickoff` and have reached the steps listed under Covers.
Covers: part 4 of 8 of the run procedure: Step 5c: Independent verification pass (before the merge decision); within: a; Git-mutation-evidence caveat (SPEC-309 R3, AC2); `{scope_summary}` (R5); Trusted kit and arm isolation (SPEC-NS-KIT-002-004); Reused baseline (SPEC-NS-KIT-002-002); Declared external evidence (SPEC-288).
Not here: spec authoring (`/nightshift spec`), recovery of a blocked spec (`unblock.md`); the run's pinned executable blocks are in `pinned-briefs.md`, `pinned-checks.md` and `pinned-validator.md`.
Requires: a ready spec in an installed project; read the parts in order: `run.md`, `run-2.md`, `run-3.md`, `run-4.md`, `run-5.md`, `run-6.md`, `run-7.md`, `run-8.md`.

# Run guide, part 4 of 8

### Step 5c: Independent verification pass (before the merge decision)

When this gate was reached from a worker completion that produced an
authoritative work result, first publish `work.completed` exactly once. Use
`passed`, `failed`, `blocked`, `cancelled`, or `unknown` from the
parent-observed result; a launch failure that never produced work does not
fabricate this event.

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event work.completed --outcome "{WORK_OUTCOME}"
```

Immediately before preparing or dispatching the independent verifier, publish
the real verification boundary exactly once:

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event verification.requested --outcome unknown
```

The parent does **not** re-derive the run's evidence in its own context. When the
run resolves — wake source 1, or a `TERMINAL` wake from Step 5b — dispatch a
`nightshift-verifier` agent, then audit its verdict with the validator below.
**Merge, lifecycle and metrics decisions do not move**: the verifier produces
evidence, the parent decides. This applies unconditionally, **including** specs
with no test suite (`domain: protocol`/`type: docs`, `commands.test: null`) —
those use the same mandatory dispatch with the adapted brief in (a-alt) below,
never a parent self-check (SPEC-ARGO-061 R1/R2). The only sanctioned exception to
mandatory dispatch is the narrow, explicitly-labeled `self-verified-experimental`
path defined in Step 6's `Nightshift-Resolution-Kind` documentation, reserved for
a pre-designated self-verified-arm measurement (originally `SPEC-ARGO-038-001`,
now superseded by canonical `SPEC-223` — see that Resolution-Kind section for the
currently-live designator) — not a routine fallback for any other spec.

> **Why this pays, and the failure mode it must avoid.** A verifier the parent does
> not check is just a second worker whose report is trusted — the exact problem
> verification exists to solve, moved one level up. What makes the split sound is an
> asymmetry: the verifier returns counts **and failing test names**, and the
> validator **recomputes** the regression classification from those names and
> compares it to what the verifier declared. `DECLARED_MATCH: no` means the
> verifier's conclusions disagree with its own evidence. Auditing costs one command;
> re-deriving costs a full run.

**a. Compose the verifier brief.** It carries exactly five inputs — the branch, the
baseline commit, the declared suites, the declared write scope (SPEC-300-002 R5),
and the spec's ACs verbatim — and **no worker
conclusions**, so the verifier cannot inherit them.

**Git-mutation-evidence caveat (SPEC-309 R3, AC2).** A worktree-isolated verifier is under the
exact same sandbox boundary as a worktree-isolated worker (Step 4g above): it cannot perform
commit-class git mutation, and cannot reliably re-execute even read-only `git status`/`git log`
outside its own assigned surface. Never write or imply, in a brief for a spec whose ACs require
independently re-executing a real `git commit`, that the dispatched verifier can fully re-run that
evidence itself — BUG-021's first verifier brief made exactly this mistake. Instead, identify which
AC(s) require it before dispatch and pre-declare, in the brief, that those specific AC(s) are
expected to come back `unverifiable` with reason "cannot independently re-execute commit-class git
mutation under worktree isolation" (see the matching Rule in both brief templates below, and the
BUG-021 worked example after them).

**`{scope_summary}` (R5).** Read the spec's `scope:` from the spec file **on the
configured main branch** (`scope_guard.scope_from_main`), never from the worker
branch. When `scope.write` is empty or `scope:` is absent, render the literal text
`project root (default)`. Otherwise render the `write` glob list verbatim, e.g.
`src/search/** (deny: none)`. Immediately follow with one fixed sentence — the
"implicit-rule summary" — verbatim regardless of the spec's own scope: "Kit-owned
evidence paths (`reports/**`, `metrics/**`, `red-proofs/**`, `runs/**`, `knowledge/attempts/**`, `release-handoffs/**`, `reports/_wip/**`, and this spec's own file) are always
writable; a new `SPEC-*.md`/`NFR-*.md` file is writable only in the project's specs
directory; targets with malformed names are never writable." Use this template
verbatim:

**Canonical verifier-gate boundary (SPEC-228, SPEC-239, SPEC-282; applies to both
briefs below).** Before composing either brief, materialize one standalone
sanitized Git repository with `.nightshift/verification_report.py
prepare-dispatch`. This repository is the sole verifier read surface. It has
its own object database and contains synthetic `verifier-baseline` and
`verifier-head` refs with every tracked branch path except three withheld
classes of report: the explicit run-report paths, every report whose path or
content names the spec under verification (same-spec reports, SPEC-239), and
every remaining report the candidate added, removed, or changed. Reports
belonging to other specs and unchanged across both arms are deliberately
**retained**, because canonical tests consume them as fixtures — so the
surface is scoped by subject matter, not swept clean of report roots. Beyond
the refs, `prepare-dispatch` also checks out each ref into its own dedicated,
already-runnable working directory inside that same standalone repository
(SPEC-282, R1/R2) — a synthetic ref alone is not dispatchable, because a
verifier confined to read-only commands could never turn a bare tag into a
filesystem tree without violating its own capability boundary. A linked
worktree of the *source* repository, sparse checkout, deleted checkout file,
or prompt-only prohibition is not an eligible substitute because the source
object database would keep report blobs reachable; the two arm working
directories are themselves worktrees of the *standalone* repository only,
never of the source. The command must write durable containment evidence —
which records the three withheld classes separately, the content hash of
every retained report, and the exact working-directory path assigned to each
arm — and succeed only when `git cat-file -e` fails for every withheld path at
both refs. It exits nonzero with `verifier_surface_unavailable` rather than
emitting a surface whose same-spec scope could not be computed, or whose two
arm working directories could not both be materialized. The command emits one
sanitized JSON dispatch plan containing only the standalone repository, its
synthetic refs/commits, the two arm working directories
(`arm_working_directories.baseline`/`.head`), neutral suite tuple/brief kind,
and containment-evidence digest. It does not emit the source checkout, report
paths, or parent-owned evidence path. Dispatch is forbidden when the command
exits nonzero, the plan is invalid, or the harness cannot assign both emitted
arm directories as the verifier's only working directories. Record that as
controlled `evidence_gap` reason `verifier_surface_unavailable`; never
substitute the run worktree or a parent self-check.

```bash
DISPATCH_PLAN=$(python3 .nightshift/verification_report.py prepare-dispatch \
  --source <run-worktree> --destination <new-empty-verifier-repository> \
  --baseline <baseline-commit> --head <candidate-commit> \
  --spec-id <spec-id> --run-id <run-id> \
  --report-path <repo-relative-run-report> \
  --evidence .nightshift/reports/<spec-id>/verifier-surface.json \
  [--spec-path <repo-relative-spec-file> [--no-project-spec]] \
  [--suite-command <exact-configured-command> ...]) || {
    echo 'verifier_surface_unavailable: do not call Agent' >&2
    exit 2
  }
```

Instead of `--suite-command`, pass `--no-suite` after the invocation above for a docs/design spec: it emits the no-test-suite brief and never reads `commands.test` (`handoff` takes the same flag; it conflicts with `--suite-command`).
`handoff` is also the one-call alternative that performs the worker-done head check (refusal reason `stale_head` when the branch moved) before and after brief composition.
Repeat `--suite-command` once per exact approved suite command for the normal
brief and omit it entirely for the no-test-suite brief. When no `--suite-command`
is given, `prepare-dispatch` derives one default from the source project's own
`commands.test` (SPEC-243-001) and fails closed to the no-test-suite brief when
that value is absent, empty, or malformed rather than fabricating suite evidence
— explicit `--suite-command` still always wins and is never merged with the
config-derived default. Parse `DISPATCH_PLAN` as
JSON and require its exact schema before composing the brief. Use only its
`repository`, `arm_working_directories.baseline`/`.head`, `verifier-baseline`/
`verifier-head`, suite tuple, synthetic commit IDs, and `sampling` counts in the
verifier assignment: fill the brief's `{required_samples_per_arm}` and
`{escalated_samples_per_arm}` from `DISPATCH_PLAN.sampling.required_samples_per_arm` and
`.escalated_samples_per_arm`. The source/report arguments above remain parent-private
preparation inputs and must not be copied into the brief. With `--spec-path`
(projected by default, SPEC-NS-KIT-002-005/008; `--no-project-spec` opts out for SPEC-289 external evidence and the plan then carries `spec_projection: declined`) each arm's spec is its contractual projection (boxes unticked): quote
the AC block from it (and give it to `brief_check`), fill `{scope_summary}` from `DISPATCH_PLAN.scope_summary`, pass every
same-spec report, attempt and event as `--report-path`, and keep briefs, scratch and
verdict paths out of any directory holding author artifacts.
The projection includes `## AC Amendments`. When a spec is amended on main after the candidate is built, re-run `prepare-dispatch` with `--contract-ref main` and the unchanged candidate revision (plan field `spec_contract`); do not commit main's spec onto the candidate to refresh the contract (check 6 reports `scope_self_edit`).

**Trusted kit and arm isolation (SPEC-NS-KIT-002-004).** `prepare-dispatch` and
`assemble-verdict` re-run themselves from main's copy of the kit when their own differs
(recorded in `DISPATCH_PLAN.trusted_tooling`); run a hand-written verdict through
`verification_report.py validate-verdict --plan <plan.json> --verdict <file> --spec-path <spec>`
(trusted `scope_guard` pinned), and the scope gate and terminal-integrity check from
`verification_report.py trusted-kit --source <run-worktree> --materialize <dir>`, never the candidate's copy. `DISPATCH_PLAN.arm_isolation` is
`sequential` plus the dispatcher's interpreter identity, or per-arm `--arm-device baseline=<id>
--arm-device head=<id>` with `--arm-runtime baseline=<rt> --arm-runtime head=<rt>`; a shared device
is refused (`arm_device_overlap`), arms on different runtimes (or one unlike an explicit plan
runtime) are `surface_env_gap`.

**Reused baseline (SPEC-NS-KIT-002-002).** Add `--ledger <ledger.json> --ledger-identity-file
<identity.json>` to `prepare-dispatch` when the project keeps a main test-status ledger. If the
plan carries `ledger_baseline.status: matched`, the verifier may record the baseline arm as one
sample `{"executed": true, "reused": true, "ledger_digest": "<ledger_baseline.record_digest>",
"failing": [<the ledger's failing names>], "passed": N, "failed": M}` instead of running it
(read the sealed copy at `.nightshift-ledger/baseline.json` in the baseline arm). The head arm always
needs its own real, independent run. The validator below accepts a reused sample only on the
baseline arm with a valid marker and a digest equal to the projected ledger, and never counts it
toward the escalated count. `not_matched` means run the baseline for real.

### Optional external asset evidence: setup and sharing

Before setting up or sharing external inputs, read
[external-evidence.md](external-evidence.md), installed as
`.nightshift/guides/external-evidence.md` (canonical source:
`canonical/guides/external-evidence.md`). Its setup and sharing instructions
apply alongside the declaration contract below.

**Declared external evidence (SPEC-288).** Some specs cannot be verified from the
subject repository alone: their durable evidence — a retained benchmark run, a
held-out reference output — lives in a *different* repository. `--spec-path` is
what lets such a spec's predeclared evidence reach its verifier, under
containment, and it is the only route. Without `--spec-path`, `prepare-dispatch`
behaves exactly as it did before SPEC-288, so no existing dispatch changes
behaviour by upgrading the kit.

<a id="external-evidence-declaration-contract"></a>

*The declaration contract.* An external input is declared in the spec's own
frontmatter, as one entry of `context.required_inputs`, in this exact form:

```yaml
context:
  required_inputs:
  - "external-evidence:{{ANCHOR}}/path/to/source-repository#repository/relative/path"
```

Both halves are required. The left half names the source repository *root*; the
right half is a path relative to that root, never absolute and never containing
`..`. Entries without the `external-evidence:` marker keep their existing
meaning — ordinary upstream-artifact declarations — and are neither resolved nor
projected. A declaration may name a single file or one bounded directory.

*The root is anchored, not literal (SPEC-289).* A stored spec may not carry a
host path — SPEC-071 refuses `/Users/...` as a leak — so the repository root is
written with one of the three canonical path anchors, `{{PROJECT_ROOT}}`,
`{{ARGO_HOME}}`, or `{{HOME}}`, and resolved at dispatch time by the same
`path_vars` primitive the validator's vocabulary comes from. Resolution is
fail-closed and its only context is the **subject project root** of the dispatch —
the repository passed as `--source`, which in a real run is the *run worktree*, not
the main checkout. `{{PROJECT_ROOT}}` is that worktree, so it reaches only content
the dispatch's own checkout carries; an evidence repository sitting beside the main
checkout is not there. Reach such a repository by `{{HOME}}` or `{{ARGO_HOME}}`.
`{{ARGO_HOME}}` comes from `$ARGO_HOME` or
the `session.md` walk-up *from that root*, and an anchor that does not resolve
refuses the declaration as `anchor_resolution` before a single source byte is
read. Quote the entry in YAML, and note three limits that are deliberate:

- Only the **root** is resolved. A token in the right-hand path is not expanded;
  it is a literal path component, and the declaration will be refused as
  `missing`. Anchors choose a repository, never a member inside one.
- There is **no literal escape**. A backtick-quoted or code-span token is left
  verbatim by `path_vars` and then refused as `anchor_resolution` — it is not a
  way to write a host path that the validator will not see.
- `..` is not available. `{{PROJECT_ROOT}}/../other-repo` is rejected by spec
  validation; reach a sibling repository through `{{HOME}}` or `{{ARGO_HOME}}`,
  whichever actually contains it on every host that runs the spec.

Four properties make this safe to expose to a verifier, and all four are enforced
rather than assumed:

1. **Declaration, not capability.** Only a path already written into the spec is
   eligible. The declaration is read from the spec file *as committed at each
   verifier arm*, never from the working tree, and the two arms' declaration lists
   must be identical. A candidate that adds, changes, or removes an
   `external-evidence:` entry during its own run is refused before the verifier
   launches; it cannot grant itself evidence authority mid-run.
2. **Projection, not reference.** The bytes are read from the source repository's
   Git object database at a pinned commit and *copied* into
   `.nightshift-verifier-inputs/<source-repository-id>/<source-path>` inside
   **both** arms, as regular read-only files. The verifier never receives a host
   path, a symlink, or a shared object database; the projection keeps working if
   the source checkout disappears, because the bytes are the surface's own.
   Evidence provenance is identical in both arms by design — only the subject
   repository content is supposed to differ between them.
3. **Containment is not overridden by declaration.** A declared path that is, or
   lies under, a report root — or that identifies the spec under verification — is
   refused *even though it was declared*. SPEC-228/239 same-spec withholding is
   unchanged, and a spec cannot hand its verifier its own report by declaring it.
4. **Everything is recorded.** Containment evidence gains
   `declared_external_inputs`: per input, the declaration, the source repository's
   identity and pinned commit, the object ID, the projected path, a SHA-256 digest,
   and the handling applied. Refusals are recorded the same way, in a durable
   `refused-declared-external-input` evidence file, before the dispatch fails. The
   verifier gets a sanitized copy at
   `.nightshift-verifier-inputs/MANIFEST.json` — with the declaration string and
   the source repository's filesystem location removed — which is how it tells a
   projection from native subject-repository content.

*The source repository need not be a managed Nightshift install.* It needs to be
a Git repository whose declared content is committed and clean; nothing more. A
`committed_kit: opt_out` project such as `Tools/benchmarks` is a valid evidence
source, and no kit release, `.nightshift/` directory, or config is required of it.

*Failure modes.* Every one fails closed — no surface, no partial import, no silent
skip — and names both the declaration and the reason:

| Reason | Condition |
| --- | --- |
| `declaration_not_identical` | the arms' `external-evidence:` lists differ |
| `malformed_declaration` | missing `#`, or an empty repository root or path |
| `same_spec_report` | the declared path identifies the spec under verification |
| `report_root` | the declared path lies under a withheld report root |
| `same_spec_content` | a declared metrics artifact's content names this spec |
| `absolute_path_escapes_source_repository` | the right-hand path is absolute |
| `path_traversal` | the right-hand path contains `..` |
| `anchor_resolution` | the root's `{{ANCHOR}}` is unknown, unavailable from the subject project root, or survived resolution unresolved |
| `not_a_git_repository` | the declared root resolved, but is not a Git repository root |
| `symlink` / `symlink_member` | the path, its parent, or a directory member is a link |
| `missing` | the declared path does not exist |
| `untracked` / `untracked_member` | present but not committed at the source HEAD |
| `mutable` | the declared path is dirty at the source |
| `unsupported_entry_type` | the tracked entry is not a regular file |
| `directory_bounds_exceeded` | over 256 members, or over 8 MiB projected in total |
| `namespace_collision` | the subject repository tracks `.nightshift-verifier-inputs/` |
| `projection_collision` | two declarations project to the same path (a directory and a file inside it) |

A refusal surfaces as the ordinary controlled `evidence_gap` with reason
`verifier_surface_unavailable`; read the evidence file for which declaration
failed and why, fix the *declaration*, and re-dispatch. Never work around a
refusal by handing the verifier the path directly.

*Brief addition.* When the plan's surface carries projected evidence, tell the
verifier so, without naming any source location: "Files under
`.nightshift-verifier-inputs/` are read-only projections of predeclared external
evidence, described in that directory's `MANIFEST.json`; they are not part of the
repository under verification. Cite them from your assigned arm only."


The `release_handoff` declaration is contractual projection input (BUG-NS-KIT-163).
Both arms preserve its exact semantic value from the assigned contract; absence stays absent.
Its declaration hash is proved alongside R/AC and scope. A withheld author-artifact name
inside that declaration refuses preparation; it is never replaced to alter release semantics.
Corpus identity, existence and Git-tracking checks still apply; projection grants no release.


### Suite-sample output identity and retained native evidence (BUG-NS-KIT-181)

`--suite unit` names a suite; pass command argv after `--`, for example
`--suite unit -- python -m pytest -q tests/unit`. Never put command text in the label.
Spec, arm and suite labels must be ASCII identifiers of 1..64 characters, starting
with an alphanumeric and continuing with alphanumerics, underscore, hyphen or dot;
sample numbers must be positive. Invalid names and unusable sinks refuse before launch.

With `--output-dir`, suite-sample preopens a unique private `.suite-sample-*` spool
below that directory; otherwise it uses `<metrics-dir>/suite-sample` and keeps live stdout.
The spool's `raw.log` holds exact native bytes, including non-UTF-8 bytes. Its
`native.jsonl` fsyncs the actual command, invocation identity and native exit before
final output names, bounded summaries or timing metrics are presented. Missing run
identity remains unavailable. Diagnostic text decoding never changes raw-byte evidence.

A final log, process projection or summary failure reports a separate wrapper failure
with surviving spool paths and digests. Secondary metrics failure preserves the native
return. Native-zero storage or presentation failure returns wrapper error74; a known
nonzero native exit remains unchanged. If all authorized storage routes fail, evidence
is explicitly unavailable; the healthy child is drained and no native replay occurs.
A recovered test count never supplies a missing native exit. Preserve the original
failed wrapper and recovered native artifacts as distinct evidence.
