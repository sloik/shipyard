# Orchestrator Protocol

## Terminal managed-payload integrity ownership

The orchestrator/coordinator is the sole owner of
`managed_payload_provenance.verify_terminal_integrity`. It retains each
successful admission receipt and consumes it exactly once after worker work and
before terminal lifecycle, merge, post-merge validation, or cleanup. Never take
a fresh admission in place of the comparison. Worker-local deny/indeterminate
holds that result and transitive dependents while preserving its branch and
worktree; a shared-install failure stops subsequent dispatch and all integration
without misreporting already-running workers.

Canonical-source authoring is the explicit parent-owned SPEC-365 path documented
in GIT.md. Inject `authoring_provider` independently of worker packets/outcomes;
retain original receipts, strict results, approved main scope, exact candidate and
fresh-main bindings. Bootstrap requires external user authorization and an
independently validated exact-candidate verdict; missing proof permits no
acceptance, lifecycle, merge or cleanup. Shared and dogfooded installed copies
remain strict. NFR-001 ownership, bounded dispatch, overlap containment, the sole
serialized integration queue and distinct fresh-main suite remain unchanged.

## Orchestrator Capability Requirements

The orchestrator role requires a model capable of:
- Following multi-step protocols with conditional branching across 3+ specs
- Remembering and executing post-merge validation steps after each spec
- Managing git worktrees (create, merge, clean up) without losing track
- Writing structured YAML that matches a schema exactly
- Making model selection decisions based on spec metadata

**Minimum capability tier: tier-2** (see config.yaml → runner.tiers)

If the orchestrator is below tier-2 capability, expect: missed validation steps,
wrong metrics format, incomplete merges. (Proven in Run2: Haiku orchestrator
ignored 3 of 4 Phase 8 improvements.)

---

**Purpose:** When multiple specs are ready and context bloat is a concern, delegate each spec to a fresh sub-agent instead of running all specs in one session. The orchestrator manages sequencing, failure handling, and rollup reporting.

**Git policy:** `GIT.md` is the source of truth for worktrees, status commits,
commit format, merge strategy, and post-merge validation. This document describes
orchestrator sequencing and references that policy.

## Observational extension checkpoint contract (SPEC-230)

Both direct `$nightshift run` and the `$nightshift kickoff` wrapper execute the
five mechanical calls in `EXTENSIONS.md` at their real authoritative
boundaries. The kickoff parent does not synthesize or duplicate worker facts:
the shared run ID and sequences make each event/job exactly once. After durable
enqueue it may launch the independent extension supervisor/drain; it never waits
for an extension domain result or places extension work in the integration queue.
`background.continue` may outlive `run.completed` until its declared deadline.

## Versioned release handoff (SPEC-189)

Before recording a release-impact canonical spec as `done`, the parent verifies
its `release_handoff` declaration and artifact against the current manifest.
The worker never fulfils the artifact and never runs an ad-hoc sync. A pending
handoff is fulfilled only by the serialized `/nightshift release` coordinator
after its canonical preflight, whole-kit rollout, verification, and durable
release report. Dirty and opted-out installs are visible safe skips.

### Retired managed-path spellings in sealed handoffs (SPEC-250)

Six handoffs sealed before SPEC-230 — SPEC-203, SPEC-207, SPEC-208, SPEC-225,
SPEC-226, SPEC-228 — record the delivered skill as
`../Skills/nightshift/SKILL.md`, the spelling `managed_paths` itself used while
the skill sat outside the release manifest. They are historically accurate: the
surface was renamed beneath them, so each reported a permanent
`names unmanaged paths` finding it could never fix.

**Chosen — read the retired spelling for those enumerated records, edit no
artifact.** `release_handoff.accepted_artifact_paths` admits
`LEGACY_SKILL_PATH` for the closed set `LEGACY_SKILL_PATH_SPEC_IDS`, and only
while `SKILL_MANAGED_PATH` is itself managed by the current manifest. Reason:
SPEC-244 established that a delivered handoff is a sealed statement about the
past, judged on its own terms. A rename of the managed surface is a fact about
the validator's world, so the validator learns the rename; the record stays as
sealed.

**Rejected — normalise the six records to `Skills/nightshift/SKILL.md`.** It
would leave no permanent table in code, which is its one real advantage. It was
rejected because it edits five `completed` delivery records and one `pending`
record to claim a manifest path that was not managed at their target versions
(2.67.3 through 3.2.0), falsifying them in the single dimension a sealed
artifact exists to preserve, and because it sets the precedent that the next
managed-surface rename rewrites history again rather than recording it.

The enumeration never widens. `managed_paths` still refuses every
parent-directory escape; any other unmanaged path inside an enumerated record
still fails; the same spelling inside any other record still fails; and no new
spec ID may join the set. Admission at the validator is also not admission at
delivery: `build_delivery_receipt` cannot hash a path the manifest does not
name, so `validate_positive_delivery` refuses to complete such a record and it
stays `pending`.

## Kickoff Parent Progress Contract

## Kickoff Spec-Ownership Claims (SPEC-178)

The parent kickoff coordinator, not its worker, owns one advisory exact-path
claim for the selected spec file. Before it mutates lifecycle state, creates a
branch/worktree, or launches a worker, it resolves the spec path to an absolute
path and checks `local_session_list_claims`. A live matching claim held by a
different session stops the kickoff and names the owner session ID, label, and
claim age; the same coordinator session reuses its claim and may resume.

The parent starts or retains a local session labelled `nightshift-<SPEC-ID>`,
claims the path with a purpose containing the run and spec ID, and renews the
30-minute claim on the existing heartbeat cadence. It releases the claim after
either terminal `done` or `blocked` resolution. Claims are advisory: any local
coordinator outage is a recorded warning, never a launch blocker. The run report
records whether the claim was acquired, reused, or skipped.

For the operational question “who owns this `in_progress` spec?”, provide one
bounded verdict: a live matching claim gives owner session ID/label/age; with no
claim, no matching branch, and no verified worktree, say **unowned** explicitly.
Coordinator unavailability is **unknown**, never unowned. Ignore `_`-prefixed
spec templates when enumerating specs.

An orchestrator may be launched by a parent kickoff agent, for example through a
board-copied `/nightshift kickoff <SPEC-ID>` prompt. In that mode, the parent
agent does not implement or validate the spec directly. It launches the
orchestrator, monitors progress, and reports evidence back to the human.

The orchestrator knows it is running under a kickoff parent when its launch brief
contains a `## Kickoff Parent Context` section. If that section is absent, this
progress contract is optional.

When running under a kickoff parent, the orchestrator must make progress
inspectable:

1. Choose and state a progress cadence based on spec size and risk.
   - Small/simple spec: update after each major phase.
   - Medium/large/risky spec: update at least every 10-15 minutes or after each
     major phase, whichever comes first.
2. Write live progress to `reports/_wip/orchestrator-progress-<SPEC-ID>.md`.
   Under worktree isolation, create the update in that worktree first and copy
   it to the parent-provided absolute path with `/bin/cp`:
   ```bash
   HEARTBEAT_LOCAL="$PWD/reports/_wip/orchestrator-progress-<SPEC-ID>.md"
   # Write the complete update locally, including `heartbeat_state: worker-started`.
   /bin/cp "$HEARTBEAT_LOCAL" "<main-repo-abs>/reports/_wip/orchestrator-progress-<SPEC-ID>.md"
   ```
   The `Write` tool and direct shell redirection (`>`) to the main-checkout
   path do not work under worktree isolation. `/bin/cp` from a worktree-local
   file is the supported cross-worktree write path. The first successful copy
   must replace the parent's `heartbeat_state: parent-seeded` marker with
   `heartbeat_state: worker-started`; its absence means the heartbeat never
   started, while a stale file containing it means the worker later stalled.
3. Update that file with:
   - current phase,
   - last completed action,
   - next planned action,
   - active blocker or stuck signal, if any,
   - latest evidence paths such as metrics, reports, verification artifacts, or
     commits.
4. If asked by the parent kickoff agent for status, answer from the current
   progress file and then continue the run.
5. If the orchestrator believes the spec is blocked or cannot proceed, report
   the exact blocker, what has already been tried, latest evidence paths, and
   the smallest bounded recovery task. The parent applies the controller-backed
   unblock protocol (`unblock_spec.py prepare`, `record_attempt`, `finalize`)
   before terminal resolution. The worker supplies evidence only: the parent
   retains lifecycle, merge, metrics, and cleanup ownership.

`reports/_wip/` is intentionally used for this live progress artifact because it
is already gitignored and reserved for in-flight run scratch state.

### Heartbeat is the sole liveness signal (SPEC-225)

The heartbeat file described above is the **only** liveness signal a parent may
use to judge whether a worker is alive. Two measured 2026-08-19 false alarms are
the evidence for this rule and must not be re-triggered by a "smarter" probe:

- A 30-minute quiet gap in the heartbeat file was, on inspection, 24 read-only
  `pytest` samples with no file `mtime` change — the worker was verifying, not
  stalled.
- A branch-tip probe (checking for new commits) declared failure on a run that
  correctly required no commit at all.

**R1 — prohibition.** Parents (and any secondary review agent such as the
watcher below) MUST NOT supplement or replace the heartbeat file with an
inferred-activity probe: no scanning file `mtime`s for recent changes, no
checking branch-tip advancement, no counting commits, and no equivalent proxy
for "is the worker doing something." A worker that is reading, testing, or
verifying without writing files or committing is not stalled, and no such probe
may say otherwise. If a parent-facing instruction anywhere in this kit would let
a reader arm one of these probes as a liveness check, that instruction is a bug
against this rule.

**R2 — declare long read-only phases.** A worker entering a long read-only
phase (test verification, evidence-gate review, spec/AC re-reading, and similar)
must heartbeat with the phase name and its expected duration instead of going
quiet, e.g.:

```
phase: verification (running full test suite, expected ~8 min)
```

Silence with no phase declared is not "probably fine" — it is exactly the
condition R4 below still catches.

**R3 — "no commit expected" is a declarable heartbeat state.** Not every
correct run produces a commit (a read-only audit, a verification-only spec, a
run that determines no change is needed). The worker may declare this
explicitly in its heartbeat, e.g. `no_commit_expected: true`, so the parent's
terminal-resolution logic does not classify a correct zero-change run as a
failure or a stall merely because no new commit appeared.

**R4 — real stalls are still caught.** None of R1-R3 weaken stall detection: a
worker that goes quiet **without** declaring a phase (R2) or a no-commit-expected
state (R3) must still be caught once the existing stale-heartbeat threshold is
crossed — the 20/40-minute ladder and escalation behavior described elsewhere in
this document are unchanged. What changes is only the signal used to decide
"quiet" — the heartbeat file's own state and timestamp, never a supplemental
mtime/branch-tip/commit-count probe.

The protocol decision rules are implemented for reuse in
`liveness_classifier.py`; the module is a testable shared model, not a standing
watchdog process.

### Independent verifier read boundary (SPEC-222, SPEC-228)

When a parent dispatches an independent verifier, it first uses managed
`verification_report.py prepare-dispatch` to create a standalone sanitized Git
repository. That repository is the verifier's sole read surface. It has an
independent object database and synthetic baseline/head refs containing all
tracked branch content except recognized report roots and the explicit run
report. A linked worktree, sparse checkout, or deleted checkout file is not an
eligible substitute because it leaves excluded blobs reachable through the
source object database. Pre-dispatch evidence must record that every report-path
probe is unreachable and that the object database is not shared.

The normal-suite and no-test-suite routes invoke that same executable boundary;
the latter supplies an empty suite tuple rather than bypassing preparation. On
success it emits a sanitized dispatch plan containing only the standalone
repository, its synthetic refs/commits, the configured suite tuple, brief kind,
and containment-evidence digest. It never emits the source checkout, report
paths, or parent-owned evidence path. The parent harness must assign the emitted
repository to every verifier command and must not substitute the run worktree.
A nonzero exit or invalid plan forbids the Agent call and becomes the controlled
evidence-gap reason `verifier_surface_unavailable`. Lifecycle, merge, watchdog
cleanup, and terminal resolution remain parent-owned.

The dispatch plan uses identity schema `1.0.0` and carries both a synthetic
`head_commit` for Git commands in the standalone surface and an opaque
`implementation_head_digest` for remediation binding. Preparation accepts the
spec/run IDs and derives the latter from a domain-separated digest of the private
candidate revision plus a digest of the canonical containment projection. The
exact candidate revision never enters the plan or verifier brief. The verifier
must copy both public values unchanged into its verdict.

Every `git status`, tree-hash, and diff command used for the verifier footprint
assertion must name the standalone surface. The source run worktree and parent
checkout are outside the verifier capability boundary and their dirtiness cannot
void an otherwise read-only verdict. Declared suite labels are neutral and their
commands are copied exactly from project configuration; headers must not carry
expected totals, status claims, comments, or worker conclusions. Every verifier
verdict includes the required `contamination` field, including when its value is
`null`.

The only generated-file exception is the exact relative path
`graphify-out/graph.html`. Do not exclude its directory, a basename match, or
other generated files. Canonical `verification_report.py` owns this exact-path
policy and the current-spec Acceptance Criteria extractor used by verifier-gate
callers; do not duplicate either rule in a consumer.

### Immediate launch-failure recovery (SPEC-194)

The stale-heartbeat ladder applies only after a worker has written
`heartbeat_state: worker-started`. A harness rejection, or a completion before
that marker carrying a launch/harness error, is an observable `launch_failure`,
not a 20/40-minute stall. The parent records the timestamp, sanitized error,
launch result, and heartbeat state in the progress artifact and run report, then
decides before arming or waiting on the watchdog.

For a retryable error that needs no human input or unsafe action, the parent makes
exactly one focused retry: same spec/run ownership and isolation, narrowed brief
limited to the launch blocker and one deterministic verification step. Record
`launch_retry: 1` before dispatch. The retry worker reports evidence only and
never changes lifecycle state or merges. If the retry reaches `worker-started`,
ordinary liveness and evidence-gate handling resumes; the final report retains
the initial launch-failure evidence.

An ineligible first failure, or a second pre-start launch/harness failure, ends
dispatch. The parent uses the existing controller-backed blocked-resolution
contract with `blocker_class: launch_failure`, preserved evidence, and its next
safe action. It performs no extra worker launch and never recasts this outcome
as a stale heartbeat.

### Parent watchdog-task cleanup (SPEC-226)

The parent that arms a kickoff liveness watchdog records its exact harness task
identifier in the parent progress state as `watchdog_task_id`, alongside the
claim, run ID, and heartbeat reference. A label or task-name lookup is not
sufficient: cleanup targets the identifier returned by the arm operation.

Before the parent becomes idle, every terminal route — `done`, evidence-gate
`blocked`, confirmed hang, and pre-heartbeat launch failure — runs the same
cleanup assertion. It stops the recorded task when one was armed, enumerates
parent-owned running background tasks, and compares their identifiers with the
recorded `watchdog_task_id`. Record exactly one result in the parent progress
artifact and final run report:

| Result | Meaning | Terminal handling |
| --- | --- | --- |
| `checked-clean` | The recorded ID is absent after the stop request. | Continue resolution. |
| `check-failed` | Stop failed or the recorded ID remains present. | Surface the task ID and failure; do not silently swallow it. The run cannot claim a clean terminal resolution. |
| `check-not-run` | No watchdog was armed, task listing is unavailable, or the assertion could not execute. | Record the bounded reason and whether human action is needed; never report this as clean. |

This is a parent obligation, not a worker-side assertion. The portable
`watchdog_cleanup.py` helper is the reference classifier for the three outcomes
and supports regression tests without making a harness-specific task-list API a
hard dependency. The report must distinguish all three outcomes so absent
cleanup evidence is never misread as a successful stop.

### Completion reconciliation (SPEC-234)

Before any kickoff parent returns idle or answers a status request, it must run
the durable `kickoff_reconciliation.py` reducer.  The reducer persists the
monotonic path `worker_running` → `worker_completed` →
`verifier_dispatching` → `verifier_dispatched`, with the completion and verifier
dispatch idempotency keys retained in state.  A callback, terminal heartbeat, or
polling observation supplies the same normalized completion delivery.

The parent supplies the narrow `KickoffRuntimeAdapter` contract: durable state
load/save, completion polling, idempotent verifier dispatch, and scheduled
reconciliation.  Polling is a bounded fallback, not a reason to wait for a
human status ping.  If a process dies after the dispatch intent was persisted,
the next reconciliation retries with the same key; the adapter launches at most
one independent verifier.  A verifier-launch failure enters
`controller_resolution_required` with the sanitized reason
`verifier_launch_failed`; a preparation or report-unreachability failure uses
the distinct sanitized reason `verifier_surface_unavailable`. The parent then
uses the existing controller-backed terminal-resolution path and never
self-verifies.

### Controlled verifier remediation (SPEC-235)

A current, schema-valid, uncontaminated independent `fail` verdict may enter
`verifier_feedback.py` exactly once. The parent validates its identity, current
head, complete AC coverage and clean footprint, then creates one immutable,
parent-signed `remediation_feedback` packet. The packet carries only hash-bound
project-relative evidence, argv command vectors, the original authority and an
exact allowed/forbidden surface; reports, prompts, logs, private paths and raw
output never cross the boundary.

The durable reducer owns the mutually exclusive `resume_original` or
`fresh_worker` choice, a `1/1` remediation budget, and keyed effects. A changed
head must pass a newly identified independent verifier before it enters the one
serial integration queue and fresh-main validation. Dispatch failure,
unavailability, unchanged head, remediation failure, or a fresh valid failure
resolves `blocked` with one controlled next action. Invalid/contaminated initial
verdicts create no packet and receive at most one replacement verifier on the
unchanged head; a second invalid verdict terminates with human action required.

At admission the parent recomputes the binding and validates the verdict against
the dispatch plan and full containment evidence. Missing or contradictory split
identity fields yield `legacy_verdict_identity` or `verifier_identity_mismatch`
and create no packet. For a completed remediation, the coordinator first proves
the exact private Git revision changed, prepares and validates a new contained
surface, persists its synthetic-head/digest pair, and only then emits the one
fresh-verifier request. Events, signatures and replay keys bind to the digest;
Git revision comparisons remain private coordinator operations.

Adapters translate callbacks, polling, cancellation and liveness into normalized
events and execute keyed effects; they contain no lifecycle or eligibility
policy. Actor-attempt outcomes are recorded separately from the parent delivery
decision through the configured SPEC-224 adapter. The typed admission seam is
source tagged. `verifier_failure` retains the signed remediation packet path.
`implementer_blocked` enters SPEC-235-001's source-specific, schema-checked
diagnosis path inside the same reducer: preserve the candidate; inventory all
changed paths and ACs; mechanically classify the blocker; optionally launch one
read-only diagnostician only for safe uncertainty; then select exactly one
bounded `resume_original` or `fresh_specialist` repair. Implementer explanations
never establish causality. External input/authority, protected or destructive
scope, irreducible ambiguity, actor unavailability, unchanged/rejected repair,
exhausted allowance, or later independent failure produces one evidenced
parent-owned block and safe operator action. Successful repair still requires a
newly independent verifier, the existing integration broker, and a distinct
fresh-main validation.

Effect identities include the recovery source, assessment digest, private
candidate revision, selected route, and ordinal. Callback delivery, polling,
restart, and acknowledgement loss therefore reconcile existing actors and
effects rather than launching duplicates. A recovery holds dependents and
overlapping surfaces while unrelated work may advance under NFR-001.

**When to use orchestrator mode:**
- 3+ specs are ready (`config.yaml` → `runner.mode: "orchestrator"`)
- Context window management matters (long-running projects)
- Independent review per spec is desired

**When to use inline mode (LOOP.md):**
- 1–2 specs ready (default, `runner.mode: "inline"`)
- Simple projects with fast builds
- Early bootstrap runs

---

## Orchestrator Flow

### Dynamic Admission Frontier (SPEC-139-001)

Before concurrent dispatch, compute the current frontier from durable spec
status rather than treating static DAG layers as a launch instruction. A ready
spec is eligible only when every `after:` dependency is `done`; descendants of a
`blocked` or `failed` dependency are blocked with that exact ancestor, while
unrelated work remains eligible. Cycles and missing dependencies are invalid and
never dispatched.

Use `nightshift-dag.py admission --worker-limit <N>` to write
`admission-plan.json` and `admission-plan.md` beside the specs. The plan records
every admitted, deferred, blocked, and invalid candidate. It also compares
declared `touches:` surfaces against active and newly admitted work. The default
`parallel_admission.missing_touches_policy: exclusive` treats empty/coarse
surfaces conservatively; do not silently infer parallel safety from missing
metadata. Recompute after every completion or failure so newly unblocked work can
fan out without waiting for an unrelated worker.

### Bounded worktree dispatch (SPEC-139-002)

Parallel dispatch is opt-in: set `parallel_admission.worker_limit` to an integer
of at least `2`. Missing, zero/one, or malformed settings retain sequential
coordination. Before every launch the coordinator runs the worktree janitor,
records the durable `in_progress` checkpoint, then assigns exactly one spec to
one unique branch, worktree, and run id. Worker artifacts live below
`.nightshift/runs/<run-id>/<spec-id>/`; workers report only their own outcome.

After any outcome the coordinator releases capacity, recomputes the live
frontier, and refills it immediately. The dispatcher first records a crash as
recoverable `pending`; the live parent then owns its single terminal transition
to `blocked` before the selected run returns. Concurrent workers never merge
branches directly; the coordinator retains integration ownership
(SPEC-139-003).

The authoritative live caller is `Coordinator.run()` in
`nightshift_coordinator.py`, the `/nightshift run` CLI implementation. Only an
explicit integer `parallel_admission.worker_limit >= 2` selects its parallel
branch. That branch constructs one `BoundedWorktreeDispatcher` for the exact
spec IDs selected by the invocation and one `SerializedIntegrationQueue`.
The coordinator starts workers in one bounded `ThreadPoolExecutor`; each start
returns an in-flight future and polling only observes completion. Workers return
isolated results to the dispatcher; the coordinator drains successful handles
into that sole queue. Queue acceptance writes durable `done`; worker failure,
queue hold, or integration failure converges once to durable `blocked` under the
parent, with a final sweep forbidding selected `pending`/`in_progress` residue.
Missing, boolean, string, zero, or one limits keep `Coordinator.run()` on its
existing sequential path.

### Full completion-evidence decision (SPEC-296-002)

Worker completion is not integration admission. Before any completed handle is
given to `SerializedIntegrationQueue`, the live `Coordinator.run()` path makes
one full completion-evidence decision from the LOOP result envelope. The
coordinator invokes its parent-owned `completion_evidence_provider`; worker
result fields are never an authority for this decision. The provider returns a
receipt bound to spec ID, dispatcher run ID, current main, exact clean candidate
commit, independently observed changed files, and SHA-256 artifact descriptors
for the Step 9 test result, Step 9.5 AC checklist, Step 14 report, and Step 10
independent-verifier verdict. The coordinator reloads candidate artifacts from
the immutable Git object, reloads the verifier only from the parent-private
`.nightshift/completion-evidence/` root, and applies the existing verifier
schema, candidate identity, independence, contamination, footprint, and complete
per-AC validators. Only those checks plus passing tests, ACs, and verdict are
`accepted`; explicit valid failures are `rejected`; a missing provider/receipt,
stale identity, hash mismatch, malformed artifact, or incomplete evidence is
`indeterminate` and fails closed.

This decision is separate from managed-payload integrity. An admission receipt
or terminal payload-integrity acceptance cannot populate or satisfy completion
evidence. Forged all-pass strings in a worker outcome are ignored. Only
completion-accepted handles proceed to the queue, where the
existing managed-payload gate still runs independently before merge. Rejected
or indeterminate handles retain their branch, worktree, worker outcome, and
integrity receipt coordinates in the durable parent-owned `blocked` checkpoint;
they are never marked `done` and are not cleaned up.

### Immutable terminal choice before lifecycle projection (SPEC-296-003)

For each selected spec and coordinator-issued logical run ID, the coordinator
records exactly one `done` or `blocked` row in the status store's append-only
`terminal_decisions` history before it projects that choice into lifecycle
status. The `(spec_id, run_id)` key is immutable: replaying the same choice
returns the original row and projects at most one matching checkpoint; asking
for the opposite choice raises `TerminalDecisionConflict` and stops closed.
Decision history and lifecycle history are deliberately separate tables.

The serialized queue owns accepted/reverted integration choices. The live
coordinator owns dispatch, worker, completion-evidence, integration-exception,
held, and final-sweep blocked choices. If interruption occurs after the durable
choice but before projection, recovery first reloads the existing choice using
the handle's coordinator-issued `terminal_run_id`, then projects that choice;
it never substitutes a new run ID or converts a recorded `done` to `blocked`.
Integration exceptions are isolated to the current deterministic handle; after
recovering or blocking that handle, the same queue continues independent peers
while retaining cross-handle overlap memory. Only an evidenced shared integrity
failure stops subsequent candidates.
The immutable queue decision carries the pre-merge observed-file set and
declared surfaces. Recovery restores overlap memory from those exact durable
values; it must not recompute the candidate diff after the candidate is already
in main, where that comparison can be empty.
On a fresh coordinator restart, startup recovery considers only selected specs
whose current non-terminal checkpoint names the original decision run. Each
newly projected `done` choice is passed through the queue's validated,
idempotent restore API before dispatch advances. Malformed surfaces stop closed;
arbitrary historical `done` rows never seed the current queue.
Dependency-descendant propagation remains a separate derived lifecycle effect,
not a second terminal choice for the selected logical run.

### Durable terminal choice to tracked frontmatter (SPEC-296-005)

Every live queue handle carries the resolved, tracked canonical spec path and
the parent validates that path's frontmatter ID before integration mutation.
After the immutable terminal choice and its matching durable status checkpoint
exist, the same coordinator-owned queue projects that exact `done` or `blocked`
value to the tracked spec.  The two writes are deliberately ordered rather than
made falsely atomic: interruption may leave durable state ahead of frontmatter,
and startup recovery replays the existing choice under its original run ID.
Recovery never chooses a replacement terminal value.

The projector commits only the owned spec path with the canonical
`chore: mark <spec-id> done|blocked` subject and the complete evidence, verifier,
blocker, unblock, resolution, parent-call, and model trailer contract.  A `done`
commit's pass trailers derive from the coordinator-accepted completion receipt
stored with the immutable decision; blocked or unavailable facts remain
`unknown`. Before writing, the projector appends a receipt to
`terminal_projection_events` binding decision/run/path, pre-write SHA-256, and
the exact expected post-write SHA-256. StatusStore admits a `started` receipt
only while the path is clean at the exact base HEAD and independently derives
both hashes from that immutable blob. Recovery independently repeats that
derivation; caller-supplied hashes never establish ownership. The store persists
one normalized Git common-directory owner intrinsically from its canonical
location or through explicit construction. Projector creation requires that
owner and never establishes it by first use. Every receipt binds that owner plus
the exact checkout root. Linked worktrees share the owner but
independent clones do not; both admission and replay revalidate these identities.
A dirty matching
path is recoverable only when its bytes equal that canonical target. Dirty opposite or mixed
user edits are refused untouched; a clean tracked opposite terminal value is
corrected outward from immutable durable truth. Crash after write, failed
commit, and crash after commit are replayed idempotently. Path-only commit
semantics preserve unrelated staged and unstaged paths and keep main clean for
the next serialized handle.

### Board read reconciliation direction (SPEC-296-008)

Board cache/API reads are not a terminal lifecycle owner. File mtime may repair
only nonterminal-to-nonterminal durable cache drift. A file value of `done` or
`blocked` never appends inward to StatusStore, even when newer than a transient
durable checkpoint; the board displays the durable value. When a matching
immutable terminal decision and lifecycle checkpoint exist, that pair wins
regardless of file status or mtime, and only the coordinator-owned projector
above may converge tracked frontmatter and create the canonical terminal commit.

### Serialized integration queue and fresh-main validation (SPEC-139-003)

Every queue construction requires a real, current, writable `StatusStore`.
Construction verifies the SQLite file exists, schema v5 is current, an
immediate write transaction can be acquired, and terminal-decision,
terminal-projection, merge-attempt, and cleanup storage are queryable. `integrate()` repeats
this durability check before inspecting or
mutating Git, because storage can disappear after construction. Missing,
non-store, stale, deleted, unreadable, or unwritable storage fails closed before
merge, lifecycle projection, or cleanup. Tests use real stores in their
temporary repositories; in-memory stand-ins are not an allowed queue path.

Completed workers enter one coordinator-owned queue; dispatch completion does
not mean `done`. The queue sorts candidates deterministically, compares both
`touches:` and actual `main...branch` changed files against already accepted
work, then rebases/reconciles each candidate onto the current main branch.

The parent addresses this queue only through the integration broker. At dispatch
the broker leases declared `touches:` plus configured release hotspots, queues
an overlap rather than racing it, and checks main is clean and index-safe before
each integration. A dirty main is recorded as `main_dirty_external` without
stashing, staging, or changing user files. CHANGELOG/version/release-handoff
surfaces are parent-owned: workers provide relative-path intents, never direct
edits. A rebase conflict receives one bounded packet containing only conflict
paths and refs; its terminal result is durable and never left in progress.

The queue records every main-merge command in the append-only
`merge_attempt_events` ledger before Git mutation and again with its checked
outcome. Exit zero is accepted only when HEAD is a clean exact two-parent merge
whose first parent is recorded main, second parent is the immutable candidate,
and tree equals Git's deterministic merge-tree result,
or when the candidate was already an ancestor of the unchanged clean main.
No-op, wrong-parent, unrelated-HEAD, or candidate-unreachable success claims are
never validated or projected `done`. Malformed runner attributes and inspection
errors are normalized into durable evidence rather than escaping after `started`.
A cleanly aborted first content conflict, postcondition mismatch, or interrupted command is held
as `NS-INTEGRATION-MERGE-CONFLICT` or `NS-INTEGRATION-MERGE-INTERRUPTED` with one
restart-safe retry. The retry is allowed only while the candidate revision is
unchanged and main is exactly the recorded clean pre-merge revision; a second
failure chooses one immutable `blocked` decision as
`NS-INTEGRATION-MERGE-RETRY-EXHAUSTED`. A non-conflict command failure on safely
restored main blocks immediately as `NS-INTEGRATION-MERGE-COMMAND-FAILED`.
Dirty, divergent, or otherwise ambiguous main is held as
`NS-INTEGRATION-MERGE-RECOVERY-REQUIRED`; it cannot retry until exact restoration.
Candidate identity drift is separately held and never substitutes a new object
into an old attempt. These merge classifications retain branch/worktree inputs,
never run cleanup, and remain distinct from post-merge validation and checked
revert evidence. On restart, an exact durable `succeeded` row resumes at
validation/revert without another merge; an invalid success shape appends a
durable recovery-required hold.
Keyed prepared recovery uses this same proof and reconciles its matching merge
ledger before validation. The ledger identity must match the prepared intent's
canonical observed and declared surface sets, and the declared set must also
match the handle; candidate, main, spec, run, and bounded attempt identity must
match as well. Every observed/conflict path is a strict repository-relative
path; declared/reserved touch surfaces use the same rule while retaining the
existing single trailing `/` directory marker. Absolute, traversal/dot,
internal-empty, backslash, URI, and platform-drive aliases are refused without
normalization. The StatusStore enforces the same rule at merge-ledger admission.
Noncanonical, malformed, missing, or mismatched identity evidence is held as
`NS-INTEGRATION-MERGE-RECOVERY-IDENTITY-MISMATCH`. Parent shape alone is
insufficient. A wrong tree, candidate mismatch, surface mismatch, or divergent
checkout becomes the terminal keyed queue record as a retained recovery-required
hold; an exact applied merge first gains its matching durable `succeeded` row
and then resumes validation without remerge.
Only the queue's exact untracked evidence file is excluded from the clean-main
proof; all other tracked, staged, and untracked changes fail closed.

**Deployment-environment authorization hold (SPEC-294).** Immediately before
each merge attempt -- inside the same loop that retries after a bounded repair,
so a repair commit is re-checked on its own next iteration -- an optional,
coordinator-injected `authorization_gate` callable may hold the candidate for a
third reason beside conflict and overlap: its resolved deployment environment
(`config.yaml`'s `deployment:` block plus the spec's `deploy_environment:`
frontmatter) requires `on_completion: authorize` and no durable, non-agent-actor
SPEC-291 `decision` artifact yet binds that exact candidate SHA. The hold is
`QueueDecision.outcome = "held"` with `overlap_kind = "authorization_required"`
-- the same durable, already-derived shape every other hold uses, not a new
mechanism. Rebase and fresh-main validation already ran (they are unconditional
ahead of this check); only the final `git merge` call is gated. Absent the
optional callable (the default), this paragraph never applies and every
candidate merges exactly as it always has (R2). A human records authorization
through the board UI (`POST /api/spec/{id}/deployment-authorization`); the
coordinator is still the sole `spec_artifacts.write_artifact` caller. A
subsequent commit on the candidate branch changes its SHA, so a stale
authorization is never honored -- the same drift-based invalidation this queue
already applies everywhere else, not new machinery.

For each accepted merge it runs the configured build/test gate from main and
records separate evidence. A conflict or overlap holds only that candidate and
keeps its worktree. A validation failure returns raw output to the originating
worker for the configured bounded repair attempt. Before every normal or
prepared-recovery revert, the queue appends a durable `started` checkpoint with
the pre-merge and merge revisions. It then appends the exact command outcome,
return code, stdout, stderr, observed files, and post-attempt revision before any
`blocked` choice. Exit zero is not sufficient: successful recovery additionally
requires a clean new HEAD whose parent is the exact merge revision and whose
tree equals the pre-merge tree.

Exhaustion after that checked success blocks only dependency descendants and
retains the branch. A failed, interrupted, or postcondition-mismatched revert is
reason-coded and held with branch/worktree and red-main evidence intact; it is
never reported as a successful revert. A replay retries only when HEAD is still
the exact clean merge revision. If a crash occurred after Git created the revert
commit but before outcome persistence, recovery proves the parent/tree/clean
postcondition and records a reconciled success without issuing another revert.
Ambiguous revision or dirty-index state stays held. No queue cleanup occurs
before main is green and durable `done` status has been recorded.

Every integration call, including keyed prepared recovery, reloads the latest
typed revert attempt for each logical run before candidate Git mutation. An
unresolved attempt whose merge still affects current main is a queue-global
barrier: independent handles are held as
`shared_main_revert_recovery_required` until the exact owner
restores main. Binding requires repository-local Git lineage plus either the
exact merge HEAD, its direct recovery child, or a persisted observed-file delta
from the recorded pre-merge tree; ancestry alone is insufficient. Thus an old
attempt whose candidate surfaces are demonstrably restored cannot poison later
work. A durable `succeeded` attempt clears the main-safety barrier as soon as
its recorded parent/tree postconditions validate, independently of later
terminal projection. Dirty or divergent owner replay remains held, and a fresh
queue never treats process-local memory as recovery authority.
An already-terminal handle whose durable status and tracked frontmatter are
clean may be replayed read-only before this barrier. That replay restores its
persisted accepted observed/declared surfaces so later overlap checks remain
sound; it does not write status, choose another terminal decision, project a
commit, or clear another run's revert barrier. An incomplete terminal
projection remains behind the barrier because completing it can mutate Git.

### Safe bounded parallel operation (SPEC-139-004)

Use parallel mode only after checking the graph, repository, and test
environment. Worktrees isolate concurrent edits; they do **not** establish that
two specs are compatible. One coordinator is the sole owner of lifecycle
transitions and merge decisions.

Before enabling `parallel_admission.worker_limit >= 2`:

1. Verify every prerequisite is declared in `after:` and the graph has no
   missing nodes or cycles. Dispatch the live ready frontier, not a whole static
   layer; a blocked node stops only its descendants.
2. Start from a clean, green `main` baseline. Do not use parallel execution to
   hide an existing failing build, uncommitted work, or unresolved merge.
3. Review each `touches:` declaration as an ownership claim. It must name the
   files, directories, contracts, migrations, or capabilities the spec may
   change. Empty/coarse declarations use the configured conservative policy;
   they are not evidence of safety.
4. Pick a worker limit from CPU/RAM, model capacity, and isolated test resources
   such as ports, databases, emulators, and caches. Start conservatively and
   namespace or semaphore every shared resource.
5. Keep exactly one coordinator for a repository/run. Workers implement one
   spec in one worktree and report results; they never select another spec,
   advance another lifecycle state, or merge into `main`.

Recovery is deliberately narrow: inspect held, failed, or unmerged worktrees;
rebase/reconcile the affected branch; then rerun fresh-main validation. Do not
delete commits unreachable from main. A failed merge is held or reverted before
unrelated work stops, and only actual descendants inherit a block.

Do not use bounded parallel orchestration when dependencies are unclear; when a
shared schema or public-interface migration lacks a parent integration plan; when
the baseline is dirty or red; or when tests require constrained shared
infrastructure that cannot be isolated or capacity-limited. Run those cases
sequentially or create an explicit parent plan first.

### 1. Bootstrap
- **Mandatory admission gate (SPEC-229):** before verifying the git tree or reading
  `config.yaml` for execution, `validate_install.py` must run and return `allow`
  (`.nightshift/preflight.py --spec-id <SPEC_ID>` runs it first automatically). A
  missing/unexecutable validator or a non-`allow` result blocks Bootstrap entirely —
  there is no manual fallback. Do not claim a spec, write lifecycle state, or create
  a branch/worktree/heartbeat before this gate returns `allow`.
- Read `config.yaml`, verify clean git tree, run pre-flight (same as LOOP.md step 1).
  Run `python3 .nightshift/preflight.py --spec-id <SPEC_ID>` (present on every
  supported install) so the admission/clean-tree/spec/dependency/baseline findings
  are captured in a durable artifact.
- Verify `runner.mode == "orchestrator"` is set
- Verify all fields present: `runner.model`, `runner.harness` are non-empty
- Log: orchestrator session started, timestamp

### 2. Task Queue

#### 2.1a Pre-Computed Plan Check (NEW — Hierarchical Specs)

Before applying the Task Selection Algorithm, check for a pre-computed execution plan:

```
if execution-plan.json exists in specs/ directory:
    plan = read execution-plan.json
    if plan.source_spec matches the spec being run:
        task_queue = plan.execution_order
        nfr_map = plan.nfr_injections
        log "Using pre-computed plan from execution-plan.json"
        → skip to §3 (For Each Spec)
else:
    log "No plan file — computing order inline"
    → continue with Task Selection Algorithm below
```

The `execution-plan.json` file is produced by `nightshift-dag plan <SPEC-ID>` (see SPEC-004-003). It contains:
- `execution_order`: ordered list of executable spec IDs
- `nfr_injections`: map of spec ID → list of NFR constraint IDs
- `cycles`: any detected dependency cycles (blocked specs excluded from order)

If the plan file exists but is stale (its `source_spec` doesn't match), ignore it and compute inline.

#### 2.1b Main Spec Detection (NEW — Hierarchical Specs)

If the spec being run has `type: main` in its frontmatter:

```
if spec.type == "main":
    DO NOT delegate this spec to a sub-agent.

    1. Read spec's children: and implementation_order: fields
    2. Run: nightshift-dag plan <SPEC-ID> --specs-dir specs/
       → generates/validates execution-plan.json
    3. Read execution-plan.json
    4. Set main spec status: in_progress (update file, commit)
    5. Add children to task_queue in execution_order
    6. Process each child as a normal spec (§3)

    When last child completes successfully:
        changed_files = union(child.files_changed for child in completed_children)
        related_stacks = []

        if config.stacks exists:
            for each child in completed_children:
                child_root = config.stacks[child.stack].root
                for each file in child.files_changed:
                    if file is outside child_root:
                        for each stack_name, stack_profile in config.stacks:
                            if stack_name != child.stack and file matches stack_profile.root:
                                related_stacks.append(stack_name)
            related_stacks = unique(sorted(related_stacks))

        if commands.test is null or empty:
            Log WARNING "No project-wide test suite configured -- integration gate skipped"
            Record report entry: integration_gate: skipped
            Set main spec status: done (update file, commit)
            Log "Main spec <SPEC-ID> complete — child validations passed, integration gate skipped"
        else:
            Run project-wide commands.build on main (if configured)
            Run project-wide commands.test on main
            For each stack in related_stacks:
                Run config.stacks.<stack>.commands.test if configured

            if all integration commands pass:
                Record report entry: integration_gate: passed
                Set main spec status: done (update file, commit)
                Log "Main spec <SPEC-ID> complete — cross-stack integration gate passed"
            else:
                Write reports/_wip/integration-failure-<SPEC-ID>-<timestamp>.md
                Record report entry: integration_gate: failed
                Leave main spec as in_progress
                STOP for human review

    If any child fails:
        Log failure, leave main spec as in_progress
        Human must decide next step
```

Main specs are containers. They describe WHAT a feature achieves but are never executed as code tasks. Their children are the executable units.

**Failure report template (`reports/_wip/integration-failure-<SPEC-ID>-<timestamp>.md`):**

~~~markdown
# Integration Failure: <SPEC-ID>

- Main spec: <SPEC-ID>
- Generated: <ISO-8601 timestamp>
- Related stacks checked: <comma-separated stack list or "none">

## Children Merged

1. <CHILD-SPEC-ID> (stack: <stack>, branch: <branch>)
   - <changed file 1>
   - <changed file 2>
2. ...

## Validation Output

~~~text
<full build/test output from the failed integration gate>
~~~
~~~

**Related stack detection notes:**
- Child-local post-merge validation still uses the child spec's own stack profile when `stack:` is set.
- The Level 3 gate is **main-spec only**. Non-main specs do not run this branch.
- Root matching is path-prefix based:
  - `root: "."` matches all project files
  - `root: "api/"` matches `api/users.py` but not `shared/config.yaml`
- Files matching no stack root add **no** extra stack tests; only the project-wide suite runs.
- Backward compatibility: if `stacks:` is absent, or the project has no `type: main` specs, behavior stays at the pre-SPEC-026 flow.

#### 2.1c Task Selection Algorithm

- Read `specs/` and apply the Task Selection Algorithm (LOOP.md step 2)
- Build ordered list of ready specs to delegate
- **For each spec**, read the `stack:` field from its frontmatter (added by SPEC-023). This value is used in section 3 for brief construction and post-merge validation. Specs without `stack:` use top-level defaults throughout.
- Log: task queue size, first spec, any dependencies detected

### 3. For Each Spec

#### 3.x NFR Constraint Injection (NEW — Hierarchical Specs)

When constructing a sub-agent brief, inject NFR constraints if available:

```
if nfr_map exists (from §2.1a) AND spec_id in nfr_map:
    nfr_ids = nfr_map[spec_id]
    if nfr_ids is non-empty:
        for each nfr_id in nfr_ids:
            nfr_file = find specs/NFR-{nfr_id}-*.md
            constraint_text = extract ## Constraint section from nfr_file
            if found:
                add to brief_constraints list

        Prepend to sub-agent brief:

        ## Quality Constraints (must satisfy)
        • [constraint text from NFR 1]
        • [constraint text from NFR 2]

        These constraints are binding acceptance criteria.
        Violations fail the spec even if all explicit ACs pass.

        Before a spec is treated as `ready` for dispatch, the acting agent MUST
        follow `SPEC-GUIDE.md`'s **NFR reconciliation transition gate**: bind or
        explicitly waive every mechanically matched active NFR, then run the
        static validator. This is agent-owned housekeeping, not human advice.

        Also prepend to sub-agent brief a required-read line:

        **Required read:** `.nightshift/VOCABULARY.md` — covers NFR lifecycle,
        blocker semantics, and how to record pending/failure state without
        modifying NFR status. Read before acting on the constraints above.
```

If no `nfr_map` exists (flat-spec project, no plan file), skip this step entirely. The brief is unchanged for backwards compatibility.

If the spec's `domain:` resolves to `research` or `analysis` (not `code`), also include `.nightshift/VOCABULARY.md` as a required read — non-code specs have different "done" criteria (output_artifact presence, source-count rules) that are summarized there.

#### a2. Check Previous Reflection (if orchestrator mode)

Before writing the next spec's brief:

1. Run:
   ```bash
   python3 check_reflection.py --spec <PREV_SPEC_ID> --output-dir .nightshift/reflections --since <timestamp>
   ```
   where `<timestamp>` is the ISO 8601 timestamp you noted after launching the previous spec's reflection (step c2)

2. If `done: true` and `new_patterns` is non-empty:
   - Add to the next spec's brief: "New patterns available from {PREV_SPEC_ID}: {list}"
   - The sub-agent's LOOP step 3a will pick them up via normal pattern injection

3. If `done: false`:
   - Log: "Reflection from {PREV_SPEC_ID} still running — proceeding without"
   - Patterns will be available for subsequent specs

#### a. Sub-Agent Tier Selection

When `runner.model_selection` is "auto", determine the sub-agent tier from spec frontmatter:

| Criteria | Tier |
|---|---|
| type: bugfix AND layer: 1 | tier-1 |
| type: bugfix AND layer: 2+ | tier-2 |
| type: feature AND ac_count ≤ 3 | tier-1 |
| type: feature AND ac_count 4-8 | tier-2 |
| type: feature AND ac_count 9+ | tier-3 |
| layer: 3 (architectural) | tier-3 |

Read the tier's model and harness from `config.yaml → runner.tiers.<tier>`.
If the computed tier doesn't exist in config (e.g., no tier-3 defined), fall back to the highest available tier.
Log the chosen tier, model, and harness in the brief.

When `runner.model_selection` is "fixed", always use tier-1 for all sub-agents.

#### a_brief. Known Issues from Previous Specs

If a previous spec's post-merge validation failed and was reverted:

Include in the brief:
```
KNOWN ISSUE from SPEC-XXX (reverted):
[description of what broke + error output]

This may affect your work if you touch the same files.
Focus on YOUR spec — do not re-implement the reverted spec.
If your pre-flight fails because of this, attempt a minimal fix
(the error details above should help) and proceed.
```

If a previous spec was merged successfully but with warnings (e.g., test flakiness):
```
NOTE from SPEC-XXX (merged with warnings):
[description of the warning]
```

#### a_stack. Stack Profile Resolution (NEW — Multi-Stack Routing)

Before writing the brief, resolve the spec's stack profile:

```
resolve_stack(spec, config):
    stack_name = spec.frontmatter.stack  # from SPEC-023
    if stack_name:
        if "stacks" in config and stack_name in config.stacks:
            return config.stacks[stack_name]
        else:
            log(WARNING, f"Unknown stack '{stack_name}' for {spec.id} -- falling back to default commands")
            return None  # use top-level defaults
    else:
        return None  # no stack tag → use top-level defaults (backward compatible)
```

If a stack profile is resolved, inject a `## Stack Profile` section into the brief (see template below). If no profile is resolved (no `stack:` tag, or unknown stack name), the brief is unchanged — identical to current behavior.

#### a_brief. Write Brief
Write a brief for the sub-agent — WHAT to achieve, not HOW. Template:

```markdown
## Task
Execute LOOP.md for spec: {SPEC_FILE}

## Context
- Project root: {PROJECT_ROOT}
- Nightshift config: .nightshift/config.yaml
- Protocol: .nightshift/LOOP.md
- Knowledge: .nightshift/knowledge/
- DevKB files: [list relevant DevKB files based on spec domain]
- Domain: {EFFECTIVE_DOMAIN} (resolved per-spec: spec.domain → stack_profile.domain → runner.domain → "code")
<!-- Domain is ALWAYS included in Context, even when no Stack Profile section follows -->

## Stack Profile
<!-- ONLY included when spec has stack: <name> AND config.stacks.<name> exists -->
<!-- If no stack: field → omit this entire section -->

**Stack:** {STACK_NAME} (from config.stacks.{STACK_NAME})
**Domain:** {EFFECTIVE_DOMAIN} (resolved per-spec: spec.domain → stack_profile.domain → runner.domain → "code")

Read LOOP-DOMAIN-MAP.md and apply the `{EFFECTIVE_DOMAIN}` column for steps 1, 4, 5, 7, 8, 9, 10.

**Commands:**
- test: `{stacks.<stack>.commands.test}` (or "not configured")
- build: `{stacks.<stack>.commands.build}` (or "not configured")
- lint: `{stacks.<stack>.commands.lint}` (or "not configured")
- type_check: `{stacks.<stack>.commands.type_check}` (or "not configured")
- format: `{stacks.<stack>.commands.format}` (or "not configured")

**DevKB files:**
- {stacks.<stack>.devkb[0]}
- {stacks.<stack>.devkb[1]}
- (or "none specified" if devkb is absent)

**Conventions:**
- {stacks.<stack>.conventions[0]}
- {stacks.<stack>.conventions[1]}
- (or "none specified" if conventions is absent)

**Environment:**
- Activation: `{stacks.<stack>.env.activate}` (or "none")
- Required binaries: {stacks.<stack>.env.required_binaries[]} (or "none specified")

<!-- End of Stack Profile section -->

## Instructions
1. Read .nightshift/BOOTSTRAP.md phases E1–E4 (knowledge & loop entry)
2. Generate the instruction packet before implementation:
   `python3 .nightshift/nightshift-instructions.py apply --spec {SPEC_ID} --json`
   Read every non-optional path in `contextFiles`; if `state` is `blocked`, fix or report the blocker before coding.
3. Your assigned spec is {SPEC_FILE} — execute this spec ONLY
3. Follow LOOP.md steps 1–15 for this spec only
4. Metrics: do NOT hand-author. The per-spec row is emitted automatically by the
   post-commit hook when the spec is marked done/blocked (SPEC-086/087). Optionally
   call `record_metrics.py` for a richer row — but it is NOT required.
5. Commit your work with conventional commit format

## Constraints
- Execute ONLY the assigned spec. Do NOT pick a different spec.
- Do NOT read or modify other specs in specs/
- Do NOT loop back to task selection (LOOP step 16) — return after one spec
- Write a success pattern to knowledge/patterns/ if your approach is reusable

## Runtime Fields
The hook derives `harness` / `loop_version` from `config.yaml` automatically. The one
field it cannot derive is the **model** — pass it as a `Nightshift-Model: {MODEL_NAME}`
trailer on the mark-done/blocked commit (see step 3 of "If build and test PASS"). That
is what enables model/harness/loop-version comparison in analyze_metrics.py. A missing
trailer degrades to `model: unknown` (the row still emits).
```

#### b. Launch Sub-Agent
- **Mark spec as `status: in_progress`** through the shared status checkpoint
  layer before launching. The board reads this durable layer first, so the state
  is visible across worktrees before merge. Resolve `nightshift_state.policy`
  before mutation. For default `commit-backed`, also keep main frontmatter in sync
  and commit exactly `chore: mark <spec-id> in_progress`; its SHA is the run ID.
  For explicit `private-local`, the coordinator uses `private_state.py` to update
  ignored frontmatter plus `StatusStore`; the durable event supplies the run ID
  and no private path may be staged or committed.
- Before the first concurrent launch, run the startup janitor from
  `worktree_janitor.py`. It reconciles stale linked worktrees, keeps any branch
  with unmerged commits as `unmerged — manual`, and only deletes resolved
  worktrees through the shared cleanup primitive. See `GIT.md` § Worktree
  Cleanup and Retention.
- Use Agent tool with isolation: "worktree". If the harness requires manual
  creation, compute the path with `worktree_paths.py plan` and pass
  `worktree_paths.py verify` before launch. Never create a project sibling or
  an in-repository `.nightshift/worktrees/` checkout; see `GIT.md` § Worktree
  Cleanup and Retention.
- Pass the brief and all context
- Sub-agent runs in a clean git worktree with isolated context window
- In `private-local`, run the privacy gate, then hydrate the verified worktree
  through the explicit projection allowlist. Before integration, return only
  contract-declared evidence and rerun the gate against tracked/staged paths and
  the application branch diff. A violation preserves the worktree and refuses merge.
- See `GIT.md` § Spec Status Commits and § Branches and Worktrees.

#### c. Wait & Receive
- Sub-agent executes LOOP.md steps 1–15 autonomously
- Returns: completion status, commit hash, metrics file path

#### c2. Launch Async Reflection (if orchestrator mode)

After receiving sub-agent results:

1. Launch background reflection:
   ```bash
   ./reflect_async.sh <SPEC_ID> .nightshift/metrics .nightshift/knowledge/patterns .nightshift/reflections
   ```
2. Note the current timestamp (ISO 8601, e.g., `2026-03-18T14:30:00Z`) for use with `--since` filtering later
3. Continue immediately to step 3d (Assess Result) and then to the next spec

For a kickoff-parent completion notification, this continuation is mandatory and
immediate: update parent progress with `terminal_resolution:
evidence_gate_running` and a start timestamp, then run the evidence gate. A
completed worker must not remain `awaiting parent integration` while the parent
waits for a human status ping. The parent records `terminal_resolution: done` or
`terminal_resolution: blocked` plus elapsed resolution time before it becomes
idle. Before any failed-evidence lifecycle mutation, classify an expected
browser/API/test-runtime absence as `waiting_external_input`: record its
allowlisted capability category and next action in the parent resolution
artifact, preserve `unblock_attempts: 0`, and wait for that capability. Only a
critical, evidenced failure uses the existing controller-backed protocol for
exactly one bounded unblock pass; every such critical outcome reaches terminal
resolution.

**Why async?** The reflection runs in the background while you work on the next spec. Insights from spec 1's reflection may be available to specs 2 and 3 in the same run, improving decision-making. See the `a2` step below for how to check for completed reflections.

#### d. Assess Result

Before merging, validate metrics:

```bash
python3 .nightshift/validate_metrics.py <metrics_file>
```

If validation fails: log warnings in the orchestrator report but still merge (metrics quality is important but shouldn't block working code).

| Status | Action |
|--------|--------|
| **completed** | Merge worktree → main, continue to post-merge validation |
| **failed** | Write failure summary (see below), check for cascading blocks, continue |
| **blocked** | Log to failure report, check dependencies, continue |
| **discarded** | Log outcome, continue (knowledge preserved in knowledge/) |

### Post-Merge Validation

Policy source: `GIT.md` § Merge and Post-Merge Validation. The steps below are
the orchestrator execution detail for that policy.

After merging a spec's worktree to main:

1. **Resolve commands** — use stack-specific commands when available:
   ```
   # Post-merge command resolution:
   if spec.frontmatter.stack and spec.frontmatter.stack in config.stacks:
       profile = config.stacks[spec.frontmatter.stack]
       test_cmd  = profile.commands.test  or config.commands.test
       build_cmd = profile.commands.build or config.commands.build
       lint_cmd  = profile.commands.lint  or config.commands.lint
   else:
       test_cmd  = config.commands.test
       build_cmd = config.commands.build
       lint_cmd  = config.commands.lint
   ```

2. Checkout main and run a clean build + test using the resolved commands:
   ```bash
   git checkout main
   <build_cmd>
   .nightshift/run_with_timeout.sh <commands.test_timeout_s> <test_cmd>
   ```

3. **If build and test PASS:**
   - Main is green.
   - Verify `.nightshift/reports/{SPEC_ID}/verification.json` exists and has no CRITICAL issues (SPEC-052). Warnings require rationale or follow-up.
   - **Verify spec status:** Check that the shared status checkpoint layer has
     `status: done` for the spec and, while legacy lifecycle artifacts still read
     frontmatter, that `specs/{SPEC_ID}.md` also has `status: done`.
     If the sub-agent forgot to mark it (common with worktree merges), update the
     durable state and frontmatter, then commit with the **canonical mark-commit format**
     `chore: mark <spec-id> done` (NOT `[<id>] chore: mark done` — the post-commit metrics
     hook keys on `^chore(\(scope\))?: mark <id> (done|blocked)`, so a non-standard subject
     means no metrics row). Add a `Nightshift-Model:` trailer so the row is model-attributed:
     ```
     chore: mark <spec-id> done

     Nightshift-Model: <orchestrator model id>
     Nightshift-Evidence-Report: pass
     Nightshift-Evidence-Tests: pass
     Nightshift-Evidence-Code: pass
     Nightshift-Evidence-ACs: pass
     Nightshift-Blocker-Class: none
     Nightshift-Blocker-Scope: none
     Nightshift-Unblock-Attempts: <0|1>
     Nightshift-Unblock-Limit: 1
     ```
     The hook then emits the per-spec metrics row automatically (SPEC-086/087) — do not
     hand-author metrics. Use source fingerprint metadata when available; stale
     source-of-truth writes must be reconciled rather than overwritten (SPEC-053).
     The matching in-progress commit is the stable resolution `run_id`. If a
     blocked transition is later marked done, the hook records a recovery attempt
     under that same run instead of presenting it as an unrelated success.
   - Proceed to next spec.

4. **If build or test FAIL:**
   a. This spec's merge broke main. Treat the failing build/test/lint output as
      raw critic input and send it back to the SAME worktree actor before any
      re-dispatch, revert, or failed mark:
      ```
      Your merge broke main. Here is the error output:
      [paste error output from build or test]

      Fix it on your branch, then signal ready for re-merge.
      ```
   b. Preserve the raw output verbatim in the reflection input. If the actor and
      critic are the same local model, present the actor's prior output under an
      inverted role so the model critiques it as another agent's work.
   c. Re-merge the corrected branch and re-validate.
   d. If the agent's fix works → proceed to next spec.
   e. Cap in-place reflection at about 3 cycles. If the cap is reached OR the
      agent can't fix it:
      - Revert the merge: `git revert --no-edit <merge_commit>`
      - Mark the spec as "failed" with `error_type: "post_merge_regression"`
      - Record the failure details (error output, files involved) in the next spec's brief as a KNOWN ISSUE
      - Proceed to next spec

5. Record post-merge validation result in the orchestrator report:
   ```
   Post-merge validation: PASS | FAIL (reverted) | FAIL (fixed by agent)
   ```

#### e. Report Per-Spec
Append result to running report:

```markdown
### {SPEC_ID} — {Title}
- Status: completed | failed | blocked | discarded
- Duration: Xs
- Commit: {hash}
- Tests: N passed, M failed (if any)
- Metrics: {metrics file path}
```

### 4. Failure Handling

When a sub-agent returns non-completed status:

1. **Read metrics and reports** — understand what happened
2. **Check dependencies** — do any remaining specs have `after: [{FAILED_SPEC_ID}]`?
   - Yes → mark those specs `status: blocked` (cascading block)
   - Exception: never mark NFR-family specs (`id: NFR-*` or `type: nfr`)
     blocked. Keep them `active`/`retired` and record pending or failed run state
     in the NFR body. Failed NFR verification blocks the triggering executable
     spec or creates/links a violation bug with `violates: [NFR-001]`.
   - **For each cascading block:** keep the real spec title as the first body H1
     and add `## Block Reason` as the first content section after that title.
     The Block Reason MUST specify:
     - Which dependency failed/is blocked (spec ID)
     - Which specific requirements/functionality of that spec this one needs
     - What would unblock the chain
     Example:
     ```markdown
     # SPEC-011 - Dependent Feature

     ## Block Reason

     Blocked by SPEC-010 (Database Migration Layer) which failed during implementation.
     This spec needs SPEC-010's migration runner (R1) and schema versioning (R3) to
     create the tables defined in Requirements R1-R4.
     Unblock path: fix SPEC-010 failure (see reports/BLOCKED-SPEC-010-*.md) → rerun → unblock this.
     ```
   - No → continue to next spec
3. **Write failure summary** to `reports/_wip/failures-{date}.md`:
   ```markdown
   ### {SPEC_ID} — {STATUS}
   **Phase:** {failure.phase}
   **Error:** {failure.description}
   **Root cause hypothesis:** {failure.root_cause}
   **Suggestion:** {failure.suggestion}
   **Dependent specs:** {any specs blocked by this, with which requirements they need}
   ```
4. **Continue** to next spec (don't stop entire run)

### 5. Final Report

After all specs processed, write consolidated report to `reports/YYYY-MM-DD-nightshift-report.md`:

```markdown
# Nightshift Report — Orchestrator Run

**Date:** YYYY-MM-DD
**Mode:** orchestrator
**Specs attempted:** N
**Specs completed:** M
**Specs failed:** F
**Specs blocked:** B

## Completed Specs
- SPEC-001: [Title] — ✅ completed
- SPEC-005: [Title] — ✅ completed

## Failed Specs
- SPEC-010: [Title] — ❌ failed (see failures report)

## Blocked Specs
- SPEC-015: [Title] — ⏸ blocked (awaits SPEC-010)

## Summary Metrics
- Total duration: Xs
- Avg spec duration: Ys
- Avg review cycles: N.N
- Total tests: T (passed P, failed F)
- Total files changed: F

## Discovered TODOs
- See TODOs-discovered.md for items found during implementation
```

### 6. Metrics Roll-Up

Aggregate metrics from all spec runs:

```markdown
# Metrics Summary

- Total completed: N specs
- Total duration: Ts (hours)
- Average per spec: Ys
- Model used: {model}
- Harness: {harness}
- Loop version: {version}

## Per-Persona Review Metrics
- Architect: N blocking issues (avg X per spec)
- Security: N issues found
- Performance: N issues found
- Domain: N issues found
- Quality: N issues found
- User: N issues found

## Failure Breakdown
- Build errors: N specs
- Test failures: N specs
- Review rejections: N specs
```

### 7. Cleanup & Commit

1. Commit all reports and metrics together:
   ```
   git add reports/ metrics/ .nightshift/specs/
   git commit -m "docs: orchestrator run report and final metrics"
   ```
2. Clean up `reports/_wip/` (temporary failure summaries merged into final report)
3. Emit completion signal

---

## Sub-Agent Brief Template (Detailed)

Use this for actual delegation:

```markdown
## Task
Execute LOOP.md for a single spec in this Nightshift project.

## Context

**Project:** {project_name}
**Project root:** {absolute_path}
**Primary languages:** {languages from config.yaml}

**Key files to understand:**
- `.nightshift/config.yaml` — project commands, conventions, circuit breaker
- `.nightshift/LOOP.md` — 16-step cycle you'll follow
- `.nightshift/BOOTSTRAP.md` — (read phases E1–E4 only)
- Your assigned spec: `specs/{SPEC_ID}.md`
- Relevant knowledge files in `.nightshift/knowledge/` (use your judgment)

**DevKB context:**
Before starting, read these files from `_System/DevKB/` if they apply to your spec:
- {RELEVANT_DEVKB_FILES} (selected based on spec domain)

**Domain:** {EFFECTIVE_DOMAIN} (resolved per-spec: spec.domain → stack_profile.domain → runner.domain → "code")
<!-- Domain is ALWAYS included in Context, even when no Stack Profile section follows -->

## Stack Profile
<!-- Include this section ONLY if spec has stack: <name> AND config.stacks.<name> exists -->
<!-- Omit entirely for specs without a stack: field -->

**Stack:** {STACK_NAME} (from config.stacks.{STACK_NAME})
**Domain:** {EFFECTIVE_DOMAIN} (resolved per-spec: spec.domain → stack_profile.domain → runner.domain → "code")

Read LOOP-DOMAIN-MAP.md and apply the `{EFFECTIVE_DOMAIN}` column for steps 1, 4, 5, 7, 8, 9, 10.

**Commands:**
- test: `{stacks.<stack>.commands.test}` (or "not configured")
- build: `{stacks.<stack>.commands.build}` (or "not configured")
- lint: `{stacks.<stack>.commands.lint}` (or "not configured")
- type_check: `{stacks.<stack>.commands.type_check}` (or "not configured")
- format: `{stacks.<stack>.commands.format}` (or "not configured")

**DevKB files:**
- {stacks.<stack>.devkb[0]}
- {stacks.<stack>.devkb[1]}
- (or "none specified" if devkb is absent)

**Conventions:**
- {stacks.<stack>.conventions[0]}
- {stacks.<stack>.conventions[1]}
- (or "none specified" if conventions is absent)

**Environment:**
- Activation: `{stacks.<stack>.env.activate}` (or "none")
- Required binaries: {stacks.<stack>.env.required_binaries[]} (or "none specified")

## Instructions

1. **Read BOOTSTRAP.md phases E1–E4:**
   - E1: Read knowledge files in `.nightshift/knowledge/`
   - E2: Survey specs queue (understand the full landscape)
   - E3: Check for STOP signal (verify you can proceed)
   - E4: Skip the "enter loop" routing — you're already in orchestrator mode

2. **Your assigned spec is `specs/{SPEC_ID}.md`**
   - Read it completely
   - This is the ONLY spec you will execute
   - Do NOT pick a different spec
   - Do NOT work on multiple specs

3. **Execute LOOP.md steps 1–15:**
   - Step 1: Pre-flight check — run `.nightshift/preflight.py --spec-id {SPEC_ID}`, which runs
     `validate_install.py` first (SPEC-229). A missing/unexecutable validator or a non-`allow`
     admission result blocks Step 1 with no manual fallback.
   - Step 2: Task selection (you're assigned {SPEC_ID} — skip the algorithm)
   - Steps 3–15: Full 16-step cycle for your spec
   - Do NOT do step 16 (loop back to task selection)
   - Return after step 15 (commit, metrics, report)

4. **Write metrics to `.nightshift/metrics/`:**
   - File name: `YYYY-MM-DD_NNN_{SPEC_ID}.yaml`
   - **METRICS FORMAT:** Your metrics YAML MUST match `metrics/_SCHEMA.md` exactly. The coordinator records controlled phase start/finish boundaries and supplies the stable run ID/event stream to `record_metrics.py`; workers never estimate timing or lifecycle/merge duration. A phase is `measured`, `skipped`, `interrupted`, or `unavailable`, never silently unknown `0`.
   - CRITICAL: Include these runtime fields from config.yaml:
     ```yaml
     loop_version: "{from config.yaml runtime.loop_version}"
     model: "{from config.yaml runner.model}"
     harness: "{from config.yaml runner.harness}"
     review_mode: "{from config.yaml review.mode}"
     ```
   - These fields enable orchestrator metrics aggregation

5. **Commit your work:**
   - Use conventional commit format: `feat(SPEC-ID): <description>`
   - Include Nightshift trailers: `Nightshift-Loop:`, `Spec:`, `Phase:`
   - One logical commit per spec (or incremental during implementation)

6. **Optional: Success pattern**
   - If your approach is reusable, write to `knowledge/patterns/PATTERN-name.md`
   - If not, log your reasoning in metrics under `knowledge.pattern_written: false`

## Constraints

- **Single spec only** — execute your assigned spec, nothing else
- **No spec selection** — don't loop back to LOOP step 2
- **No context expansion** — don't read unassigned specs or touch other worktrees
- **No harness changes** — use the harness/model from config.yaml
- **Clean commits** — conventional format, descriptive messages
- **Test timeout:** If test command runs longer than `config.yaml` → `commands.test_timeout_s` seconds, the process will be killed and exit code 124 returned. When this happens:
  1. Log "Test hang detected"
  2. Retry ONCE: run `commands.build` first (clean build), then test again with the same timeout
  3. If retry also times out (exit 124), fail the spec with `error_type: "test_hang"` — do not attempt further retries
  4. Record in metrics: `phases.validation.test_hang_detected: true` (or preflight if hang was detected in pre-flight)
  - Use `.nightshift/run_with_timeout.sh` wrapper as documented in LOOP.md Test Timeout Protocol

## Build & Verify

All verification happens in your LOOP.md execution. Orchestrator will assess via metrics.

## DevKB References

[Include specific DevKB entries relevant to the spec's domain]
```

---

## Failure Detection & Escalation

### Sub-Agent Failure Signals

Sub-agent signals failure via:
- Metrics file with `status: failed | blocked | discarded`
- A BLOCKED report in `reports/BLOCKED-{SPEC_ID}-{timestamp}.md`
- Non-zero exit from the Agent tool

### Orchestrator Escalation Logic

When running under `## Kickoff Parent Context`, treat a blocked/stuck result as
an escalation to the parent kickoff agent, not as permission for the worker to
change lifecycle state or merge. Include the exact blocker, what was tried,
latest evidence paths, and one bounded recovery task. The parent owns the
controller-backed unblock protocol: it runs `unblock_spec.py prepare`, records
the result with `record_attempt`, and calls `finalize` only after verified
success. Ineligible cases are controlled skips with human escalation; a success
is `blocked -> ready`, never a direct return to `in_progress`.

For an agent-local mandatory tool failure, the parent records controlled
recovery events through the existing run log and follows one bounded ladder:
probe; smallest safe repair; post-repair probe; then one fresh-worker or
transport-rebind probe if the original worker is stale. The replacement worker
cannot mutate lifecycle state or merge. A terminal `evidence_gap` requires that
viable alternatives were recorded as ineligible, unsafe, externally-authorized,
or exhausted; a single cached tool failure is not a true block. Private
projection transport may be `awaiting_sync` without changing this decision.

```python
if sub_agent_status == "completed":
    merge_worktree()
    # Only the coordinator-owned checked cleanup protocol may remove resources.
    # It runs after immutable terminal decision + durable/frontmatter projection,
    # records exact ownership before mutation, checks subprocess/postconditions,
    # and durably enumerates every retained resource on partial failure.
    cleanup_merged_worktree(status_store=durable_store, spec_path=canonical_spec)
    continue_next_spec()

elif sub_agent_status in ["failed", "blocked", "discarded"]:
    if sub_agent_status in ["failed", "blocked"]:
        mark_spec_status(spec_id, "blocked")  # frontmatter lifecycle status; skip NFR-family specs
        # If spec_id starts with NFR- or type is nfr, keep status active/retired and
        # record the pending/failure state in the NFR body instead.
        record_error_type(spec_id, sub_agent_status)  # metrics/report outcome
    read_metrics_and_reports()
    write_failure_summary(reports/_wip/failures-{date}.md)

    # Check for cascading blocks
    dependent_specs = specs_with_after_dependency(current_spec_id)
    for spec in dependent_specs:
        mark_as_blocked(spec)  # no-op for NFR-family specs; record run state instead

    continue_next_spec()  # Don't stop entire run

else:
    # Unknown status — log and continue
    log_warning(f"Unknown status: {sub_agent_status}")
    continue_next_spec()
```

---

## Exit Conditions

**Stop orchestrator when:**
1. All specs are processed (completed, failed, blocked, or discarded)
2. A STOP file is detected (manual pause — same as LOOP.md)
3. All remaining specs are marked `status: blocked` (cascading failure)

**Outcome:**
- Write final report to `reports/YYYY-MM-DD-nightshift-report.md`
- Commit all changes
- Emit completion signal

---

## Multi-Model Comparison Mode

When `config.yaml → comparison.enabled: true`, the orchestrator enters multi-model comparison mode.

### Flow

1. **For each spec in the queue:**
   - For each model in `comparison.models[]`:
     - Set `runner.model` and `runner.harness` from the model config entry
     - Launch sub-agent in worktree (same as single-model mode)
     - Sub-agent executes LOOP.md steps 1–15 with the assigned model
     - Metrics are written to `.nightshift/metrics/` with the model name in the filename

2. **After all models complete all specs:**
   - Run `python3 .nightshift/compare_models.py .nightshift/metrics --format text`
   - Generate comparison report grouped by `task_id` (spec)
   - For each spec: show side-by-side comparison of all models' results
   - Models ranked by average composite score across all specs
   - Report written to `comparison.report_dir` (default: `reports/model-comparison/`)

3. **Result:**
   - Metrics directory contains runs for each (spec, model) pair
   - Comparison report provides human-readable analysis
   - JSON output available via `--format json` for programmatic use

### Key Points

- Each model runs independently — no cross-model interference
- Metrics YAML must include `model` and `harness` fields for traceability
- If a spec has only one model, it's skipped in the comparison output
- Missing or inconsistent fields are handled gracefully (defaults/N/A)

---

## Integration with BOOTSTRAP.md

**BOOTSTRAP.md phase E4** (line ~480) already routes correctly:

> **If `runner.mode: orchestrator`** (or unset and multiple specs are ready):
> - **Read:** `.nightshift/ORCHESTRATOR.md`
> - Follow the orchestrator protocol — delegate each spec to a fresh sub-agent

This orchestrator.md fulfills that contract. No changes needed to BOOTSTRAP.md.

---

## Stack-Aware Routing — Backward Compatibility (SPEC-024)

The stack-aware routing additions (stack profile resolution, `## Stack Profile` brief injection, and stack-specific post-merge validation) are fully backward compatible:

- **Specs without `stack:`** work exactly as before. No `## Stack Profile` section is injected, and all commands resolve to the top-level `commands:` block. There is zero behavioral change for existing specs.
- **Single-stack projects with no `stacks:` section in config.yaml** are unaffected. The orchestrator only looks up `config.stacks` when a spec has an explicit `stack:` field. If `config.stacks` is absent, the lookup is skipped entirely.
- **The `## Stack Profile` section is only injected** when both conditions are met: (1) the spec has `stack: <name>` in its frontmatter, AND (2) `config.stacks.<name>` exists in config.yaml. An unknown stack name produces a WARNING log and falls back to defaults — the spec is not blocked.
- **LOOP.md is unchanged.** Sub-agents receive resolved commands in their brief and follow LOOP.md as-is. Stack awareness lives entirely in the orchestrator's brief construction and post-merge validation.

---

## Consistency with LOOP.md

- **Task selection:** Orchestrator uses LOOP.md step 2 algorithm once at the top
- **Sub-agent execution:** Each sub-agent follows LOOP.md steps 1–15 exactly
- **Metrics format:** Same YAML schema as LOOP.md step 13, plus runtime fields
- **Reports:** Same structure and commit format as LOOP.md step 14
- **Knowledge:** Same `knowledge/` directory, same discovery logic (LOOP.md step 3)

The orchestrator is a thin wrapper around LOOP.md, not a replacement.
