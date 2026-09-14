# Nightshift Kit — Changelog & Migration Guide

> **Versioning:** SemVer (`kit_version` in config.yaml).
> - **Major** — breaking changes to protocol, config schema, or metrics schema
> - **Minor** — new features, new config sections, new protocol steps (backward-compatible)
> - **Patch** — bug fixes, wording clarifications, no config/protocol changes
>
> **Rule:** Every change to canonical files MUST bump `kit_version` and add an entry here.

## 3.22.0 (2026-09-14)

### Board detail panel: opacity slider + full-width bottom docking (SPEC-349)

The board's sliding detail panel (`#panel`, extended from SPEC-347's left/
right docking) gains:

- An opacity slider (40%–100%, default 100%) in the panel header, applying
  plain CSS `opacity` to the whole panel (background, text, and chips fade
  together) so the board and the open spec's detail can be read at once
  without one fully occluding the other.
- A third docking position, bottom, reached by cycling the existing side
  toggle (right → bottom → left → right). Bottom-docked spans the full
  viewport width and reuses the existing top-edge drag handle to resize
  height.
- The panel's height now always leaves room above `#recent-bar` (the
  RECENT spec-history strip) in every docking mode, not only bottom-docked —
  it never covers that strip, though it may still overlap the kanban columns
  above it.
- A visible top-edge border, matching the existing side border, hinting that
  the top edge is draggable (previously only the left/right resize edge had
  a visible border at rest).

No config schema or protocol changes; UI-only.

## 3.21.8 (2026-09-13)

### Verdict validator's scope recomputation no longer rejects correct verdicts (BUG-336)

`Skills/nightshift/SKILL.md`'s embedded `NIGHTSHIFT-VERDICT-VALIDATOR`
(SPEC-300-002 R6 scope recomputation, only exercised when a standalone
verifier surface is supplied as its third argument) had two independent
defects that both made it reject a verdict that was actually correct.
First, `git diff --name-only --diff-filter=ACDMR verifier-baseline
verifier-head` had no trailing `--`, so it was ambiguous whenever the
surface repo's working tree also contained paths literally named
`verifier-baseline`/`verifier-head` — always true, since those are
SPEC-282's two arm working directories. git refused with "ambiguous
argument", stderr was discarded, and the diff was silently read as empty,
failing the very next comparison against the verifier's real
`scope.checked`. Second, the per-path `classify_write` call passed
`project_root` twice and a literal `None` instead of the real kit
directory and spec-relative path (the shape `scope_gate.py`, a few hundred
lines earlier in the same file, already uses correctly), so the `spec_self`
reason code could never fire and the spec's own file — touched by ordinary
lifecycle bookkeeping in essentially every real run — was misclassified
`outside_root`. Fixed both: the diff invocation now ends with a bare `--`
to disambiguate the two refs from pathspecs, and `classify_write` now
receives the already-computed `kit_dir` and a `spec_relpath` re-expressed
relative to the surface repo (the validator's own established convention
of passing the spec file as a real path inside the standalone surface,
confirmed against `test_verifier_gate.py`'s existing AC5 fixture). New
regression coverage in `canonical/tests/test_bug_336_verdict_validator_scope_recomputation.py`:
a realistic fixture with `verifier-baseline`/`verifier-head` directories
literally at the surface root and a real two-commit history that changes
the spec's own file plus an in-scope write, run both against the fixed
script (accepts a correct verdict, still rejects a genuine unreported
out-of-scope write) and against single-defect mutants of the script that
independently reproduce each original bug. Patch-only: no config/protocol
schema changes.

## 3.21.7 (2026-09-12)

### Drag-and-drop status no longer flickers back to the old column (SPEC-348)

`onCardDrop()` optimistically flips a dragged card's status and repaints
before the blocking `window.prompt()` reason dialog, then issues the
persisting `PUT`. If the 10s status poll's queued fetch returned while the
prompt was open and reached the server before the drop's own PUT committed,
the poll's unconditional `specs = fresh` overwrite snapped the card back to
its old column — visible as a flicker, sometimes stuck until the next poll.
A module-level `pendingMoves` map (spec id → `{newStatus, sinceMtime}`) is
now set right after the optimistic status assignment and cleared in all
three PUT outcomes (success, non-ok, network error). A new pure
`mergeFreshSpecs(prevSpecs, freshSpecs, pendingMoves)` replaces the
unconditional overwrite in `pollSpecs()`: it keeps the optimistic status
unless the fresh snapshot's `_mtime` is strictly newer than `sinceMtime`, in
which case fresh wins and the pending entry clears. Specs with no pending
move are unaffected. Regression coverage: 8 new unit tests in
`canonical/tests/test_board_status_poll_merge.py`, extracting the embedded
JS and running it in Node, including a red/green proof against the pre-fix
`board.py`. Patch-only: no config/protocol schema changes.

## 3.21.6 (2026-09-12)

### Board panel gains configurable side (left/right) and draggable top offset (SPEC-347)

The sliding detail panel was hard-coded right-docked and full-viewport-height,
with no way to move it to the left or shrink it. A new `#panel-side-toggle`
button switches the panel between right-docked (default) and left-docked via
a single `.side-left` CSS class that mirrors position, border, and the
width-resize handle's edge; `startPanelResize`'s width-delta sign is
captured per-drag and mirrored for left-docked mode so dragging still grows
and shrinks the panel correctly on either side. A new `#panel-top-resize`
handle lets the operator drag the panel's top offset while it stays
anchored to the viewport bottom, clamped between the board header and a
minimum panel height. `panelSide`/`panelTopOffset` persist through the
existing `saveSettings()`/`loadSettings()` mechanism (already project-scoped,
so this is per-board with no new plumbing). A `panelDragActive` guard keeps
the click-outside-closes-panel listener from misfiring on either drag.
Cross-board syncing of these preferences is a deferred nice-to-have (see the
spec's Out of Scope). Regression coverage: 8 new Playwright tests in
`canonical/tests/test_board_browser.py`. Patch-only: no config/protocol
schema changes.

## 3.21.5 (2026-09-12)

### Board panel gains "reveal in Finder" and "open in Terminal" actions (SPEC-345)

The sliding detail panel already let an operator jump into a spec's file via the
"↗ OPEN/EDIT" (VS Code) button, but had no way to jump into the spec's containing
folder in Finder or a Terminal window rooted there. Two new endpoints mirror the
existing `_open_in_vscode`/`/api/open/spec/{spec_id}` pattern:
`POST /api/open/spec/{spec_id}/finder` runs `open -R <path>`;
`POST /api/open/spec/{spec_id}/terminal` opens Terminal.app via `osascript`,
passing the spec's parent directory as a trailing argv element (never
interpolated into the AppleScript source text) and applying `quoted form of`
before it reaches any shell — no string concatenation into a shell command
anywhere in either new function. Both endpoints match the existing
404/400/500/503 error contract. Two new panel buttons call them, matching the
existing toast-on-failure pattern. Regression coverage: 11 new FastAPI
`TestClient` tests and 4 new Playwright tests. Patch-only: no config/protocol
schema changes; macOS-only, matching the existing VS Code open path's own
darwin special-case.

## 3.21.4 (2026-09-12)

### Board panel's details toggle no longer closes the sliding panel (SPEC-346)

Clicking the sliding detail panel's "details" metadata toggle (`#panel-meta-toggle`)
closed the whole panel instead of expanding/collapsing the group. Its `onclick` handler
(`toggleMetaCollapsed`) calls `renderPanelMeta()`, which replaces `#panel-meta`'s
`innerHTML` — including the clicked button — before the click event bubbles to the
document-level "click outside closes panel" listener, which checked
`panel.contains(e.target)`. Since `e.target` was by then a detached node, the check
wrongly read false and closed the panel. The listener now checks `e.composedPath()`
(captured at dispatch time, immune to later DOM mutation) instead of `e.target`,
structurally fixing this for any panel-internal control, not just this one toggle.
Regression coverage: 3 new Playwright tests in `canonical/tests/test_board_browser.py`.
Patch-only: no config/protocol schema changes.

## 3.21.3 (2026-09-12)

### Run reports embed spec identity so distinct runs can never silently collide (SPEC-343)

A completed run's final narrative report was silently overwritten by a different run's
report finalized later the same day, because both wrote to the same shared, destructive,
date-only path (`reports/YYYY-MM-DD-nightshift-report.md`). The earlier narrative survived
only in Git history; neither project's board `/api/reports` listing surfaced the
root-level file at all. Source: a weekly Cortex smoke check (Core/Tools incident).

Step 14 of `LOOP.md` (and the matching prose in `Skills/nightshift/SKILL.md`) now directs
every run to `reports/YYYY-MM-DD-nightshift-report-<SPEC-ID>.md`. `board.py` gains
`finalize_report()`: an identical-content write to an occupied target is idempotent, and a
differing-content write (e.g. a same-spec same-day rerun) is deterministically disambiguated
with a `-run2`, `-run3`, … suffix rather than truncating the prior file — never a silent
overwrite. `board.get_reports()` now also parses and returns `spec_id`/`run_suffix`
attribution per report (`None`/`None` for legacy date-only reports, which remain listed and
readable — no existing report was renamed or deleted). Project attribution continues to
reuse SPEC-340's existing project-root scoping (`_project_root_for_reports()`); a sibling
project sharing one Git repository is not attributed to the wrong board. The independent
verifier-report-blinding mechanism (SPEC-228/239/282) is root-prefix-based, not
filename-based, and the new convention's spec-ID-in-filename is actually a strict
improvement for same-spec path-based exclusion (`same_spec_report_exclusions`'s existing
`-SPEC-XXX-`-suffix precedent). Regression coverage:
`canonical/tests/test_spec343_report_collision_regression.py` — a disposable temporary Git
repository with two project roots, two same-day runs, a same-spec rerun, a legacy
date-only negative control routed through the same production `finalize_report()` function
(proving the regression oracle is real, not a tautology), and an assertion that board
discoverability and independent-verifier exclusion hold independently for the same report.
Known remaining gap (out of this spec's `touches:`): `nightshift_coordinator.py`'s
`_record_run_spend_ceiling_breach` still appends to the shared date-only path; flagged for
a follow-up spec. Patch-only: no config/protocol schema changes; existing reports are
unaffected and unmoved.

## 3.21.2 (2026-09-12)

### Verifier surface no longer drops tracked-and-ignored retained files (SPEC-342)

`verification_report.py` builds each verifier arm by materializing every path tracked in
the source repository at that ref, then running `git add -A` in the standalone destination
repository. `git add -A` honours `.gitignore` — and the destination's own `.gitignore` is
itself a source-tracked file that gets copied in, so a file that is genuinely tracked in the
source *and* matches one of that project's own ignore patterns (a legitimate, intentional
combination: a force-added, retained evidence/report file living under an otherwise-ignored
directory such as `reports/_wip/`) was silently absent from the arm's commit even though it
was present on disk. The September 8 kit 3.17.0 refresh introduced this by replacing a
per-arm force-add with the current plain `add -A`; source: Cortex SPEC-CTX-CORE-061.

`_materialize_ref` now also returns every path it wrote from the source ref's tracked tree,
and `prepare_verifier_surface` force-adds exactly those paths (`_force_add_tracked_paths`,
using `git add -f --pathspec-from-file`/`--pathspec-file-nul` to stay correct under very
large tracked-path counts and non-UTF-8 filenames) before the existing plain `add -A` picks
up everything else. No file that was never tracked in the source is force-included, and the
SPEC-228/239/282 containment/exclusion rules that deliberately withhold same-spec and
excluded reports are unchanged. Regression coverage:
`canonical/tests/test_spec342_verifier_retained_ignored_files.py` (hermetic dispatch +
committed-object read-back, a negative control that reproduces the pre-fix drop in-process,
and a tamper-detection case) and
`canonical/tests/test_spec342_managed_refresh_integration.py` (refresh integration test
against a disposable temporary project via the real `nightshift-sync.py canonical_sync`
path, with a positive and a negative candidate). Patch-only: no config/protocol schema
changes; `verification_report.py` is managed payload (`CANONICAL_PROTOCOL_FILES`), so
installed copies need this refresh once released.

## 3.21.1 (2026-09-12)

### Fleet collection no longer crashes on incomplete validation evidence (SPEC-344)

A real fleet collection crashed in `fleet_metrics.py::_metric_summary` comparing
`validation.test_pass_rate: null` with an integer (`TypeError: '>=' not supported
between instances of 'NoneType' and 'int'`), producing no snapshot at all. Null,
missing, wrong-type, boolean, negative, and out-of-range validation values are now
treated as explicitly *unknown* rather than crashing or silently counting as
passing. A new, purely additive `evidence_quality.fleet_validation_unknown_rate`
snapshot metric distinguishes "no evidence" from "evidence shows failure"; the
schema version is unchanged and both existing consumers (`analyze_fleet_snapshot`,
`fleet_evidence_summary`) already forward the whole dict, so neither needed a code
change. Patch-only: no config/protocol changes.

## 3.21.0 (2026-09-11)

### StatusStore binds one Nightshift project per git repository, not one per checkout (SPEC-340)

`StatusStore.for_specs_dir` conflated a project's root with its git checkout toplevel. That
crashed every board of a Nightshift project that is a strict subdirectory of its repository
(`checkout_root != repository` in `_repository_identity`, which is correct and stays), and —
because `default_db_path_for_specs_dir` resolved one DB path per git common directory — a
repository holding several independently configured Nightshift projects had all of them writing
into the *same* status DB before this crashed. Observed live in `Cortex/` (`core/`, `api/`,
`mcp/`, `tools/`): all four boards down with `StatusStoreError: terminal projection checkout
identity is invalid`, and the shared `Cortex/.git/nightshift-status.db` already held 100 rows
commingled across all four projects, including 3 rows under an unattributable `BUG-001` id.

The default DB path is now namespaced by the project's path relative to its own checkout
toplevel — `<git-common-dir>/nightshift/<project-relpath>/nightshift-status.db` — computed from
*that checkout's own* `git rev-parse --show-toplevel`, never from the common directory's parent,
so linked worktrees of the same project still share one DB while sibling projects in one
repository no longer collide. A project whose root *is* the checkout toplevel (relpath `.`) keeps
its exact pre-3.21.0 path, `<git-common-dir>/nightshift-status.db` — every existing single-project
install in the fleet is this case, and it is unaffected by this release. `for_specs_dir` now
passes a real checkout root to `bind_repository` (never `project_root`); the bound identity widens
to also record the owning project's relpath, so two Nightshift projects can never silently share
a status DB again.

**Migration required** for any repository holding more than one Nightshift project that shares a
git checkout (i.e. only repositories in the `Cortex/`-like shape above — every single-project
install needs no action). Run the one-shot splitter against the shared DB:

```
python status_store.py --source <repo>/.git/nightshift-status.db \
    --project core=<repo>/core/.nightshift/specs \
    --project api=<repo>/api/.nightshift/specs \
    ...
```

It attributes each row to the one project whose specs dir declares that row's spec id, and it
fails closed: any spec id attributable to zero or more than one project aborts the entire
migration before any destination file is written, naming every offending id and its row count,
and leaves the source database byte-identical. Not a member of the intra-DB
`_migrate_vN_to_vN+1` chain — those migrations take a single `sqlite3.Connection` and cannot open
or write sibling DB files, which is the entirety of what this migration does.

## 3.20.4 (2026-09-09)

### The scope guard resolves the kit directory per staged path (BUG-335)

BUG-321 stopped the spec-home rule denying `SPEC-GUIDE.md` — a `CANONICAL_PROTOCOL_FILES`
member whose name matches the `SPEC-*.md` pattern — by exempting anything the release manifest
declares as payload. That exemption was keyed on a **single** `kit_dir`, and `_cli_check`
resolves exactly one (`project_root/canonical` when it exists).

A repository can hold several kit directories. The Nightshift repository holds three: the
canonical source at `canonical/`, plus installs at `.nightshift/` and `canonical/.nightshift/`.
`release_coordinator.py` stages payload for every install in a repository in one commit, so the
guard was handed paths belonging to kits other than the one it resolved and the exemption could
not fire — `.nightshift/SPEC-GUIDE.md` resolved outside `canonical/` entirely, and
`canonical/.nightshift/SPEC-GUIDE.md` resolved to `.nightshift/SPEC-GUIDE.md`, which the
manifest does not list because payload is listed relative to a kit root.

The 3.20.3 fleet rollout hit this after committing three repositories and halted with
`unexpected_mid_rollout`:

```
[nightshift write-scope]   DENY spec_wrong_home .nightshift/SPEC-GUIDE.md
[nightshift write-scope]   DENY spec_wrong_home canonical/.nightshift/SPEC-GUIDE.md
```

The guard correctly has no environment-variable bypass, so a multi-install repository could not
be released at all until the resolution was fixed.

The exemption now resolves the kit **per path**: the kit a path belongs to is the nearest
ancestor carrying kit metadata (`release-marker.json`, which `release.apply_install` writes into
every install, or `release-manifest.json`). Membership is then checked against that kit's own
manifest, so any number of installs and any nesting works. The caller-supplied `kit_dir` remains
the fallback, so single-kit callers are unaffected, and the exemption is still keyed on manifest
membership rather than basename — a spec-shaped file inside a kit that the manifest does not
declare is still denied.

No migration required.

## 3.20.3 (2026-09-09)

### The finding-family gate moves out of the per-install payload check (BUG-334)

3.20.2 wired SPEC-337's `finding_family_regression_errors` into
`release.payload_gate_errors`. That host was wrong on two counts, and 3.20.2 never
reached the fleet because of it.

**Every install would have failed its payload invariant.** `payload_gate_errors` is not
canonical-only: `validate_install.py` calls `validate_manifest(ctx.install, names)` with an
*install* directory in the `canonical` position. Installs do have a `specs/` directory (so the
check's guard did not fire) but never receive `metrics/validation-error-floor-baseline.json`,
which is canonical-only and not managed payload. The check therefore took its
unreadable-baseline branch and returned a hard error on every install — `KIT.PAYLOAD`, and so
`doctor`, would have reported a spurious failure across all 16 fleet repositories. Delivering
the baseline would not have helped: an install's own spec corpus has nothing to do with
canonical's finding-family floor.

**The canonical suite stopped fitting in its timeout.** The check runs
`validate_specs.validate_directory()` over all 378 canonical specs, which shells out to
`git log -G` and `git show` twice per spec, costing ~37 s per call. With `validate_manifest` on
many tests' hot path, `tests/test_validate_install.py::test_artifact_hash_matches_written_bytes`
went from **2.41 s to 40.47 s** and the suite from ~1000 s to ~3400 s — past
`CANONICAL_SUITE_TIMEOUT_S = 2100`. The first real 3.20.2 `--apply` run refused at preflight
(`canonical suite command exceeded 2100s`) and left all 16 repositories untouched.

The check now runs from `release_coordinator.coordinate_release()`, next to
`check_canonical_suite_headroom` — the placement SPEC-336 already established for a
canonical-only release gate: once per release, against the canonical checkout, denying with
`failure_class: canonical_preflight` and surfacing
`finding_family_regression_healthy`/`finding_family_regression_errors` in the result. A
canonical that declares no floor (no baseline artifact) is a recorded skip
(`finding_family_regression_skipped`) rather than a silent pass, matching SPEC-336 R4's
degrade-safe choice for "no measurement recorded yet". `finding_family_regression_errors`
itself is unchanged and keeps its loud-on-missing contract for direct callers.

No migration required.

## 3.20.2 (2026-09-09)

### The finding-family baseline diff is wired into the release gate (SPEC-337)

SPEC-270 built `finding_family_summary()`/`diff_finding_family_summaries()` and committed a
baseline artifact (`canonical/metrics/validation-error-floor-baseline.json`), but nothing ever
called the diff against it — the exact gap that let the SPEC-254/255 `unmanaged paths:
canonical_copies.py` finding sit unnoticed among ~130 pre-existing errors (SPEC-319 § Open
Questions item 3 / SPEC-QUESTIONS-007 Q3 option B). `payload_gate_errors` (`release.py`) now has a
new `finding_family_regression_errors` check that loads the baseline, runs
`finding_family_summary()` against the live `canonical/specs` corpus, and denies the release on any
finding family that is new or has grown; a shrunk or removed family is never an error. The
baseline was refreshed to the current corpus (`719` findings across `8` families, absorbing the
`unclassified-finding` family and the other drift SPEC-337's own Problem section measured), so this
check is clean today and only trips on future regressions. To accept a genuine new/grown family
after reviewing it, regenerate the baseline from the repo root:

```
python3 canonical/validate_specs.py canonical/specs --format json --ownership-summary \
  | python3 -c "import json, sys; data = json.load(sys.stdin); \
      json.dump(data['finding_family_summary'], sys.stdout, indent=2); print()" \
  > canonical/metrics/validation-error-floor-baseline.json
```

## 3.20.1 (2026-09-09)

### SPEC-336's headroom guard is actually wired into a real release (post-merge verifier finding)

An independent verifier dispatched against the combined 3.20.0 delivery found that
`check_canonical_suite_headroom()` (SPEC-336) was correctly implemented and unit-tested in
isolation, but never called from `coordinate_release()`'s real suite-run path or from `main()` —
so the BUG-320 tripwire it restores did not actually fire during a real release, only when a test
imported and called the function directly. `coordinate_release()` now calls it immediately after
each real canonical-suite run and refuses the release (`failure_class: canonical_preflight`) when
the guard reports unhealthy headroom, surfacing `canonical_suite_headroom_healthy`/
`canonical_suite_headroom_reason` in the result dict. Two new regression tests
(`test_coordinate_release_fails_preflight_on_violated_headroom`,
`test_coordinate_release_proceeds_with_healthy_headroom`) prove the wiring end-to-end rather than
only the guard function in isolation.

## 3.20.0 (2026-09-09)

### Four follow-ups from SPEC-QUESTIONS-007 land together (SPEC-334, SPEC-335, SPEC-336, SPEC-338)

Delivered as four concurrently-dispatched workers on disjoint file sets, resealed and released
together in one combined version bump.

- **SPEC-334** — `release_handoff.repin_pending_handoffs`/`complete_pending_handoffs` previously
  completed a pending sentinel handoff regardless of the source spec's own status, letting a
  release mark work as delivered before the spec was actually `done`. Both functions now gate on
  `_spec_status(canonical, spec_id) == "done"`; an unresolvable `spec_id` is treated as not-done
  without raising. Skipped-but-eligible records are now observable via the coordinator's new
  `release_handoffs_blocked_by_spec_status` result field.
- **SPEC-335** — `record_metrics.py`'s `mark-commit`/`correct-commit` modes resolved install paths
  against the process's cwd instead of the actual git repository root, doubling the prefix
  whenever `--repo` names a subdirectory (this is how the phantom `canonical/canonical/metrics/`
  directory appeared during SPEC-319's closeout). Both call sites now anchor against a resolved
  `_repo_root(repo)` instead; an unresolvable root is now a reported error, not a silent
  `unknown`/no-op fallback.
- **SPEC-336** — `CANONICAL_SUITE_TIMEOUT_S`'s headroom guard asserted against a hand-edited,
  stale literal (`measured_healthy_runtime_s = 996.10`) that nothing kept in sync with reality —
  the BUG-320 tripwire could never actually fire again. `coordinate_release` now records a durable,
  timestamped measurement after every real canonical-suite run
  (`canonical/reports/_wip/canonical-suite-duration-*.json`), and
  `check_canonical_suite_headroom()` evaluates the same 2x-headroom relation against the latest
  *healthy* recorded measurement instead of the literal. Degrades safely (`healthy=True`) on a
  fresh checkout with no prior measurement.
- **SPEC-338** — `canonical/SPEC-GUIDE.md` now documents `delivered_but_not_closed_findings`
  (SPEC-332 R4): a release-handoff record at `status: completed` implies the spec shipped, so any
  other spec status is a record inconsistency, fixed by closing the spec or retiring the handoff.

## 3.19.3 (2026-09-09)

### The completed-handoff orphan gate is wired in; 19 historical records dispositioned (SPEC-333)

BUG-331 implemented `completed_handoff_orphan_errors` — a check that flags a `status: completed`
release-handoff record whose sealed manifest fingerprint is no longer resolvable — but left it
deliberately unwired from `payload_gate_errors` because turning it on immediately denied this
repository's own release checks over 19 real historical records already orphaned by past
same-version reseals (5 on 3.18.0, 14 more at 3.12.0/3.13.0/3.14.0).

All 19 are now dispositioned: each was verified to have `status: done` on its own spec and every
one of its `changed_managed_paths` present in the current canonical tree, then folded — reset to
the pending sentinel so the next real fleet rollout completes it again, the same pattern already
used for `BUG-016.json`. `completed_handoff_orphan_errors` is now called from
`payload_gate_errors`, so it fires wherever `validate_manifest` does (release coordinator
preflight, `validate_install.py`'s `KIT.PAYLOAD` invariant). A new regression test
(`test_gate_wires_in_completed_handoff_orphan_errors`) proves the wired-in gate — not just the
standalone function — catches a genuinely orphaned record.

## 3.19.2 (2026-09-09)

### BUG-331 LE1: the same-version-reseal refusal fired for real, resolved by version bump

No functional change. This bump is itself BUG-331's Live Execution Checklist evidence: after
3.19.1 fleet-delivered BUG-331 and the coordinator completed `release-handoffs/BUG-331.json`
against that release's real fingerprint (`524e9f65…`, 20 installs verified), a same-version
`write_manifest` call against the unchanged 3.19.1 manifest was deliberately attempted. It raised
`SameVersionResealError`, naming `BUG-331.json` by name, exactly as designed — confirmed the
manifest was left untouched (no write occurs before the exception). This bump is the sanctioned
resolution path named in that error message: `kit_version` moves to 3.19.2, so `write_manifest`
now succeeds and the 3.19.1 manifest (fingerprint `524e9f65…`) is retained in
`retained_manifests`, keeping `BUG-331.json`'s sealed reference resolvable.

## 3.19.1 (2026-09-09)

### A same-version manifest reseal can no longer silently orphan a completed release-handoff's fingerprint (BUG-331)

`write_manifest` retained the previous manifest in `retained_manifests` only when `kit_version`
changed. A reseal at an unchanged version replaced the on-disk fingerprint and retained nothing,
so a `release-handoffs/*.json` record already `completed` against that fingerprint became silently
unverifiable — the provenance chain lost a link with no warning (SPEC-257 requires every sealed
`(version, fingerprint)` pair to stay resolvable). `write_manifest` now raises
`SameVersionResealError`, naming the offending record(s) and both sanctioned paths (bump
`kit_version` so the previous manifest is retained, or reset the named records to `pending` first),
whenever a same-version reseal would replace a fingerprint a completed handoff still names. A
version bump, or a same-version reseal with nothing completed against the old fingerprint, behaves
exactly as before.

A companion function, `completed_handoff_orphan_errors`, additionally detects any *already*-orphaned
completed record. It is implemented and unit-tested but deliberately not yet wired into the SPEC-324
payload gate: this repository's own `release-handoffs/` carries 19 real historical records already
orphaned by past same-version reseals (5 on 3.18.0, 14 more at 3.12.0/3.13.0/3.14.0), and wiring the
check in today would correctly deny this repo's own release checks until a human dispositions them —
deferred to a follow-up spec.

## 3.19.0 (2026-09-08)

### Nested-install admission fixed, and a required-config-section migration closes the fleet's biggest CFG.RUNNER_POLICY gap

- **`ROOT.IDENTITY` accepts real nested installs (BUG-328).** `check_root_identity`
  equated "legitimate root" with "at the git toplevel", denying every nested
  install (`Cortex/{api,core,mcp,tools}`, `Fartownik/BE`, `Argo/Skills/focus`,
  `Nightshift/canonical` — 7 of 22 installs on the 2026-09-08 fleet survey). A
  real (non-symlinked, non-escaping) subdirectory of the toplevel whose own
  `.nightshift` is itself a kit install now passes with `observed=nested-install`;
  symlinked roots, escaped roots, and a foreign `.nightshift` still fail exactly
  as before. `INT.HOOKS` needed no change — its linked-worktree common-git-dir
  logic already covers nested installs.
- **Schema `3.2.0`: a registered migration adds every section `CFG.RUNNER_POLICY`
  requires (SPEC-327).** Installs bootstrapped at kit 3.0.1 lack `runner`,
  `nightshift_state`, `release_policy`, `parallel_admission` and were
  permanently DENIED (17 of 22 installs on survey). The new migration appends
  every missing required section with its documented safe default, additive-only
  and idempotent; `validate_install.py` now imports its required-section tuples
  from `config_migrations.py` so the validator and the migration cannot drift
  apart again. Applied fleet-wide by this release with `--migration-runner
  reference`.

Correction to 3.18.1's note above: BUG-331 (same-version reseal orphaning a
completed handoff's fingerprint) was **not** actually fixed in 3.18.1 — that
line described intended, not delivered, work. BUG-331 remains open and is
being fixed separately; this release's own manifest reseals at an unchanged
`kit_version` (now bumped here) avoid re-triggering it in the interim.

- **`write_manifest` refuses a same-version reseal that would orphan a
  completed handoff's fingerprint (BUG-331).** A reseal at an unchanged
  `kit_version` replaces the on-disk fingerprint without retaining it; if a
  `release-handoffs/*.json` record with `status: completed` names that exact
  fingerprint, the rewrite now raises `SameVersionResealError` naming the
  record(s) and both sanctioned paths (bump `kit_version` so the previous
  manifest is retained, or reset the records to `pending` first). A version
  bump, or a same-version rewrite with no completed record on the old
  fingerprint, is unchanged. This same reseal (3.19.0, unchanged version) is
  itself tolerated by the new check because nothing has completed against
  the fingerprint it replaces.

  A companion function, `completed_handoff_orphan_errors`, additionally
  detects any *already*-orphaned completed record (fingerprint neither
  current, nor retained, nor explicitly unretained) — this repository's own
  accumulated 3.12.0/3.13.0/3.14.0/3.18.0 instances (19 records). It is
  implemented and unit-tested but deliberately **not yet wired into the
  SPEC-324 payload gate**: doing so today would correctly DENY this
  repository's own KIT.PAYLOAD checks until those 19 records are
  dispositioned, which is a human call BUG-331 explicitly left out of scope.
  A follow-up spec wires it in once disposition lands.

## 3.18.1 (2026-09-08)

### The board and the spec files are provably in sync; "delivered but not closed" is a static error (SPEC-332)

After the 3.18.0 rollout the canonical board showed two specs `in_progress`.
The board was right — BUG-323 and SPEC-324 had been delivered (handoffs
completed) and never marked done — and nothing had said so. Two gaps, now
closed:

- **The board/file relation is a checked property.** The SPEC-296-008 /
  BUG-313 reconcile rule moves into `status_store.py` as pure, shared
  functions (`should_reconcile_frontmatter_status`, `classify_status_sync`);
  `board.py` re-exports them unchanged. New `GET /api/status-sync` reports,
  from the same single batch state read `/api/specs` uses, every spec whose
  effective status differs from its file — with the reason
  (`durable-terminal-ahead-of-file`, `durable-stale-behind-file`) — and
  `/api/health` carries `status_sync_mismatches`. Read-only beyond the
  existing BUG-313 repair.
- **The same check runs without the board.** `validate_specs.py
  --status-store <db>` compares the durable store to every spec file
  offline; an unopenable store is its own error, never a pass.
- **Delivered but not closed.** `validate_specs.py` now errors when a spec's
  release handoff is `completed` while its status is not `done` — the exact
  miss above, caught with no board at all.
- Tests cover every path: the BUG-313 repair still fires and reports nothing;
  a terminal row ahead of the file is reported, not hidden; a stale
  non-terminal row is reported; R4 positive and negative; the health count.

Same-version reseals stop here: 3.18.0's final fingerprint `030c0022…` is
referenced by six completed handoffs and is retained by this bump (BUG-331).

### The formal drift lane no longer vetoes an unrelated release (BUG-333)

`formal/nightshift/validate_evidence.validate` treated anchor staleness — any
change to `board.py`/`status_store.py` since the registry's pinned revision — as
an artifact-integrity error, so `record_lane` exited 1 and a canonical-suite
test turned every whole-kit release red until the lane owner re-baselined with
a TLC toolchain that is not on the release machine. SPEC-304 defines the lane
as non-blocking and SPEC-308 gives stale rows a tolerance and attention rule:
staleness is tracked state. `validate` now accepts a stored summary that
differs from the recomputation only in `freshness`/`coverage_state`, reports
it stale, and still fails on any other divergence. Not payload; nothing on an
install changes.

### Migration

None. `schema_version` stays `3.1.0`.

## 3.18.0 (2026-09-08)

**The bug-fix release for what 3.17.0 found — and the first release whose
`--apply` is closed by a static payload gate before any install is touched.**
3.17.0 (SPEC-319) needed four apply attempts because canonical shipped payload
that its own installs' gates rejected, one defect per ~17-minute attempt; it
also left the phantom-install defect worked around by hand. This release fixes
the class, not just the instances. Scope, evidence and rollout: SPEC-325.

### A directory named `.nightshift` is only an install when it is one (BUG-323)

Every discovery path — `nightshift-sync.find_nightshift_dirs`,
`nsm.discover_projects`, `nightshift-master._discover_projects`,
`doctor.find_projects` — treated the directory *name* as proof of a kit install.
A stray `.nightshift/red-proofs/` (Cortex) or a non-Nightshift `.nightshift/tasks/`
(Inwestomat) then became an "install" with no configuration, the coordinator
raised a migration request it could never satisfy, and **the whole repository
was skipped** — real installs included. Cortex lost four installs from 3.17.0
until its phantoms were quarantined by hand; Inwestomat stayed on 3.14.0.

- New `release.is_kit_install(nightshift_dir)`: true iff the directory holds
  `config.yaml` (written by bootstrap) or `release-marker.json` (written by
  every release). One definition, in managed payload, so canonical and installs
  agree by construction — the `nightshift-sync.py` comment that its walker and
  `nsm`'s "must be kept in agreement by hand" described exactly this failure.
- Applied by the three operational walkers; a phantom is neither returned nor
  descended into. `release_coordinator.plan_repositories` independently
  classifies one as `skipped: phantom_install` and never groups it with the
  repository's real installs.
- `doctor` deliberately still walks every `.nightshift` — it is the diagnostic
  path — and `inspect` reports a phantom as a new CRITICAL **D0** finding naming
  the two missing files and the consequence, so it is explained rather than
  hidden. Live: nsm's configured roots drop from six "projects" to the three
  real ones (Inwestomat's `_System/.nightshift` and two `.argo/*/pre-edit`
  evidence directories were phantoms).

### Static payload gate at release preflight (SPEC-324)

`release.validate_manifest` already ran at coordinator preflight and closed
`--apply` on any error; it checked the manifest's *shape* and never asked
whether installs would *accept* the payload. It now does, in seconds, before
the suite and before any install is touched:

- **Payload shell lint** — `shellcheck` over every `.sh` entry; a manifest with
  shell payload and no `shellcheck` on `PATH` is itself an error (fails closed).
  Would have caught BUG-322.
- **Payload accepted by the shipped guard** — the candidate payload's own
  `scope_guard.classify_write` over every manifest path, in a simulated install
  layout and a simulated canonical layout, with no active spec, against a
  scratch marker embedding the candidate manifest. Would have caught BUG-321;
  a fixture that regresses the guard to its pre-BUG-321 rule proves it.
- **Skill version parity** — `Skills/nightshift/SKILL.md`'s `version:` equals
  `kit_version`. Cost a full suite run during the 3.17.0 cut.
- **Handoff membership** — every pending `release-handoffs/*.json` names only
  paths its target manifest manages, via `release_handoff.validate_artifact`
  so stranded records with dispositions resolve against their retained
  manifests exactly as at authoring time. Surfaces the SPEC-254/255 class where
  a release cannot proceed past it.
- `scripts/check_nightshift_drift.py` aligns **five** `kit_version` artifacts:
  `SKILL.md` joins `config.yaml`, `config-reference.yaml`, `LOOP.md` and the
  CHANGELOG top entry.

Fixtures that ship a single module — no shell, no guard, no skill — are
unaffected and need no shellcheck.

### A delivered install is now ON the release (BUG-326)

The coordinator delivered payload and marker and never touched the install's
project-owned `config.yaml` — so its `kit_version` stayed behind, and two
required admission invariants read exactly that value: `CFG.PARSE_VERSION`
(config must match the marker) and `KIT.MARKER` (whose "supported release"
comparison, run from an install, is against the install's own stale
`kit_version`). Every rollout therefore left every install it reached DENIED at
admission. Measured after 3.17.0, before this fix: **22 of 22 installs DENY**,
all on those two invariants. `nightshift-sync.py` had done this correctly since
SPEC-127; the coordinator replaced that path (SPEC-156) without inheriting it.

- New `config_migrations.set_kit_version(text, version)`: rewrites only the
  quoted value on the existing `kit_version:` line, nothing else; text without
  the line is unchanged.
- On every verified delivery the coordinator reconciles `kit_version` before
  smoke checks and staging, reports it under `config_kit_version_updates`, and
  commits it with the payload — `config.yaml` is now always on the release
  allowlist (both of the coordinator's independent allowlist computations
  agree). A `config.yaml` that is already dirty still skips the repository:
  project-owned work in progress is never written into. Dry-run reports the
  planned `from`/`to` and writes nothing.
- The kit's own `hooks/pre-commit` is installed into the repository's hooks
  directory when **no** pre-commit hook exists — the BOOTSTRAP.md copy, which
  `INT.HOOKS`' remedy already assigns to "the whole-kit release" — and reported
  under `hooks_wired`. An existing hook is never overwritten or merged, only
  reported as `kept-existing`. `.git/hooks` is outside the worktree; nothing is
  staged.
- `release_coordinator.py --migration-runner reference` applies
  `default_migration_runner` — the deterministic function a dispatched worker
  must reproduce byte-for-byte — so a schema-behind install with nothing to
  reconcile is migrated in the same guarded run instead of skipped forever.
  Default behaviour is unchanged.
- New `scripts/fleet_admission_survey.py`: runs every install's own
  `validate_install.py` and tabulates failing invariants — the static check
  that found this, and the check that proves the fix.

Two admission failures the survey found are **not** this bug and are filed:
`CFG.RUNNER_POLICY` (3.0.1-era configs lack `runner`, `nightshift_state`,
`release_policy`, `parallel_admission` — SPEC-327, a registered schema
migration) and `ROOT.IDENTITY` on nested installs (BUG-328).

### The kit's pre-commit no longer lints a kit-only commit (BUG-329)

`hooks/pre-commit` ran the project's configured `commands.lint` and
`commands.type_check` on every commit — including a whole-kit release commit
that stages only `.nightshift/` payload, the marker and the `kit_version` line.
The 3.18.0 rollout stopped at its tenth repository because that hook, installed
by the same run (BUG-326), invoked `swiftlint`, which does not exist on the
release machine, against a commit containing no Swift. Lint and type-check
gate project code; a commit with no project path has nothing for them to check.

- The hook now skips exactly those two steps when every staged path has a
  `.nightshift` component (nested installs included), printing one line that
  says so. The decision is structural — no environment variable can trigger
  it — and the scanner, spec validation and write-scope guard run unchanged.
  Any staged path outside `.nightshift/` runs both as before.
- `release_coordinator.wire_pre_commit_hook` now refreshes a **kit-owned**
  hook (one carrying `# Nightshift Kit — Pre-commit hook`, the header the
  write-scope installer already recognises) to the shipped payload when the
  bytes differ (`refreshed`), leaves an identical one (`up-to-date`), and still
  never touches a foreign hook (`kept-existing`). Without this, the hooks
  BUG-326 installs are frozen copies and a fixed hook never reaches them.
- New `tests/test_pre_commit_hook.py` runs the real hook in a fixture
  repository with a linter that cannot exist.

### A rerun after a refused release commit recognises the coordinator's own work (BUG-330)

BUG-326 writes the install's `kit_version` and stages it with the payload; when
the repository's hook then refuses the commit, the coordinator stops and leaves
that one-line change staged, as it should. On the rerun the runbook prescribes,
the pre-apply boundary check read that dirty `config.yaml` as project-owned
work and skipped the repository as `known_project_local` — forever, since only
the coordinator would ever clear it. Observed on the second 3.18.0 apply at
CoJezdzi, the repository the first apply had stopped on.

A dirty `config.yaml` whose content equals HEAD's plus this release's own
`kit_version` reconciliation (`config_migrations.set_kit_version`) is now the
coordinator's leftover, not project dirt. Any other difference — another
version, an added section, whitespace — still skips the repository, and an
unreadable HEAD copy fails toward the stricter path.

### SPEC-254 / SPEC-255 release-handoff correction

Both declared `impact: required` with `changed_managed_paths:
[canonical_copies.py]`. `canonical_copies.py` is a canonical-only pre-commit
guard that has never been managed payload, so neither record could ever
re-pin. Corrected to `impact: exempt` with the reason; the records are retired
(git history retains them). `validate_specs.py` had reported this all along —
as one line among 135 pre-existing errors.

### Incidental test corrections (each verified stale at HEAD first)

`test_config_migration` asserted the literal schema `3.0.0` (SPEC-269 moved it
to `3.1.0`) and a discovery count that included phantoms; `test_nsm_roots`
expected projects that left Argo Home in SPEC-ARGO-017; `test_ns_control`,
`test_doctor` and `test_nsm_roots` built installs as bare directories, which
BUG-323 defines as phantoms — their fixtures now write a `config.yaml`. No
assertion was weakened: the phantom-count test gained a positive assertion that
no phantom path appears.

### Migration

None. `schema_version` stays `3.1.0`. An install at 3.17.0 moves in one
coordinator-applied step.

## 3.17.0 (2026-09-08)

**First whole-kit rollout since 3.14.0 (2026-09-02).** 3.15.0 and 3.16.0 were cut
in canonical on 2026-09-04 but never delivered, so an install moving to 3.17.0
receives all three releases' payload at once and completes 38 release handoffs
that had been waiting on a qualifying release. The release's own scope, evidence
and rollout record are SPEC-319 (`specs/SPEC-319-cut-and-roll-out-nightshift-3-17-0.md`,
report under `reports/SPEC-319/`).

### Board request-latency work budget, and a non-blocking event loop (SPEC-303)

Clicking a spec on the board took ~1 s at p50 and 10 s+ at p95. Board telemetry
located the cost in the request, not the rendering (`browser.panel_markdown_parse`
p50 2.7 ms against `browser.panel_fetch` p50 1409 ms / p95 11130 ms).

- Blocking filesystem, SQLite and subprocess work no longer runs on the event
  loop: every board route whose handler does such work is declared `def` (served
  on Starlette's threadpool), not `async def`, and a test enumerates the app's
  routes so a new blocking `async def` handler fails the suite.
- `SpecCache` entry mutation and status writes are serialized by a lock.
- New `tests/test_board_latency_baseline.py` asserts per-request **work-count**
  budgets (deterministic counters, not wall-clock thresholds) against a fixture
  corpus. The single-spec budget is asymptotically flat: one
  `GET /api/spec/{id}` does identical work at 40 and at 400 specs. One coarse
  wall-clock smoke test per hot route remains as a documented backstop.
- A failed drag re-renders when the card was orphaned mid-request.

### Spec detail panel: declared execution models, styled artifacts, collapsible metadata (SPEC-307)

- **New optional `execution:` frontmatter field** with `worker_model` and
  `verifier_model` (free-form model identifiers; absent means "parent default").
  Documented in `SPEC-GUIDE.md` Phase 5 and `_TEMPLATE.md`. `validate_specs.py`
  accepts it and rejects non-string values or unknown keys under `execution:` —
  WARN for `draft`, ERROR for `ready`. Until now the model a spec should run on
  lived only in the parent's memory as an Agent-call parameter; a cheaper-model
  policy is now declarable on the spec itself.
- `/api/spec/<id>` returns `execution` verbatim; the panel shows both values as
  metadata rows next to status, and the copied run prompt carries one
  `Launch the run worker with model: <…>` line per declared key. Prompts for
  specs without the field are byte-identical to before.
- The SPEC-291 artifact list is styled (`.artifacts-label`, `.artifact-row`,
  `.artifact-type`, `.artifact-date`, `.artifact-summary` had no CSS at all), and
  the metadata table — grown to 12+ rows — is collapsible.

### Verification protocol for evidence that requires real git mutation (SPEC-309)

A probe run on 2026-09-06 established that the sandbox refusal hit by
`isolation: "worktree"` subagents does not track the boundary its message
asserts: it fires identically for the agent's own worktree and for a disposable
external scratch repo, and it tracks invocation *shape*, not mutation
(`git add .` succeeded unrefused where `git status`/`git log`/`git commit` were
refused against the same repo). The consequence is structural, so `SKILL.md` now
states it rather than leaving each session to rediscover it:

- Worker- and verifier-dispatch sections document that a spec whose Live
  Execution Checklist or Acceptance Criteria require a real `git commit`-class
  operation cannot be fully executed or independently verified by a
  worktree-isolated subagent.
- The sanctioned fallback is named: the coordinator executes the live proof
  directly and the completion report says so explicitly, rather than reading like
  ordinary worker output.
- The verifier-brief template tells the verifier to mark such an AC
  `unverifiable` with the specific reason — never `fail`, which would
  misrepresent a sandbox limitation as a defect in the work.

### Report section contract extended to coordinator-authored reports (SPEC-317)

SPEC-299 restored the `## Blocked Specs` / `## Open Questions` /
`## Report Action Log` headings to the *worker* boilerplate; reports written by a
coordinator session by hand still had no mechanical check. `validate_specs.py`
gains `--check-report-headings`, date-gated so no historical report is
retroactively flagged, and `LOOP.md` Step 14's contract now covers
coordinator-authored reports too.

### Lifecycle-commit trailers are visible to git's own trailer parser (BUG-017)

Git recognizes only the **last** contiguous, blank-line-delimited paragraph of a
commit message as trailers. This project's own convention wrote the
`Nightshift-*` block, a blank line, then `Co-Authored-By:`/`Claude-Session:` — so
`git log --format=%(trailers:key=…)`, which `record_metrics.py` uses, silently
read back empty values for **every** `Nightshift-*` field on every lifecycle
commit.

- `SKILL.md`'s documented commit shape now places every trailer — `Nightshift-*`
  and attribution alike — in one contiguous paragraph.
- A regression test asserts `git interpret-trailers --parse` recovers every
  `Nightshift-*` key from that documented shape.
- `record_metrics.py` detects and reports the "trailer-shaped line present in the
  body but invisible to the parser" case instead of absorbing it into defaults.

### `--mark-commit` recognizes `BUG-NNN` lifecycle commits (BUG-018)

`MARK_COMMIT_RE` required a literal `SPEC-` prefix, so every
`chore: mark BUG-NNN done|blocked` commit — this project's own documented naming
for bugfix specs — no-opped through `record_metrics.py --mark-commit` with no
error and no warning, and no `BUG-*` spec ever recorded terminal metrics. The
regex now matches both forms; `SPEC-*` behavior is unchanged.

### `INT.HOOKS` admission no longer denies every linked worktree (BUG-019)

`validate_install.py`'s `check_int_hooks` always failed with
`observed: foreign-or-escaped` / `NS-REM-HOOK-SHADOWED` when run from a linked
git worktree — even with `core.hooksPath` unset and the pre-commit hook present,
executable and demonstrably running. Since worktree isolation is the kit's own
kickoff convention, this blocked LOOP Step 1 admission in every installed
project, with no manual fallback. The check now passes for a linked worktree
whose effective hooks directory is its repository's shared, un-shadowed one, and
still fails when `core.hooksPath` genuinely points outside the repository — in
both a main checkout and a linked worktree. Reported from a live kickoff in
`agent-chat-mcp`.

### `scope_guard.py`'s spec-home rule no longer falls open on import failure (BUG-020)

`_discover_specs_dirs`'s hardcoded `.nightshift/specs` / `canonical/specs`
fallback sat *after* its `try`/`except`, so any exception from the dynamic
`doctor.py` import returned an empty result and the universal "spec files have
one home" rule fell open. This was live, not hypothetical: the hooks invoke bare
`python3`, and loading `doctor.py` under Python 3.14 raises inside dataclass
processing. The fallback is now reachable on that path; the rule falls open only
when neither fleet discovery nor the fallback finds a usable specs directory,
matching its documented contract. No change to the discovery mechanism itself.

### Live-execution checkboxes require backing evidence — spec template v11 (BUG-023)

`validate_specs.py` treated a checked `- [x] **LEn:**` box as proof the live
execution happened, checking nothing behind it. That is exactly how SPEC-300-003
and SPEC-300-004 reached `done` with entire Live Execution Checklists never
executed (BUG-021, BUG-022).

- Under `real_use_evidence.policy: required_before_done`, each checked LE item
  must carry an inline `(evidence: <path>)` reference that resolves to a real
  file relative to the spec's directory or its parent. Existence only — no hash,
  deliberately asymmetric with `delegated_experiment`.
- A missing, empty or non-existent reference is an ERROR at `status: done`,
  naming the LE id and the reference.
- **`specs/_TEMPLATE.md` → v11.** Specs below v11 are grandfathered; do not bump
  an already-`done` spec to v11 without backfilling real evidence references.

### `flake_resolved` verdict classification bucket (BUG-024)

`SKILL.md`'s verdict table defined `fixed` as `baseline_all − head_any`, which
requires a 100% baseline failure rate — a test failing 13% of the time clears a
30-sample all-fail bar with probability ≈1×10⁻²⁷. The bucket that exists to name
"this spec fixed a flake" was mathematically unreachable for an actual flake. New
disjoint bucket `flake_resolved` = `(baseline_any − baseline_all) − head_any`
partitions `fixed`'s precondition, so `fixed ∪ flake_resolved = baseline_any −
head_any` exactly, with no overlap by construction and no new threshold to pick.

### The board learns terminal status from commit-only finalization (BUG-313)

`_should_reconcile_frontmatter_status` refused to let a fresh `done`/`blocked`
frontmatter value repair a stale non-terminal durable row, on the premise that
only `nightshift_coordinator.py`'s immutable-decision projector writes terminal
truth. But the kit's own documented interactive workflow (`SKILL.md` Steps 1–7)
finalizes a spec by editing frontmatter and committing — so every hand-driven
coordinator session left the board showing a non-terminal column for a `done`
spec. A one-time forward reconcile from non-terminal durable to terminal
frontmatter is now allowed, using the same file-mtime-vs-checkpoint-mtime
comparison the existing non-terminal repair path already used, and it is durable
(`status_store.update_state`).

### Write-scope hook installer (SPEC-318 follow-through)

SPEC-318 confirmed by live probe that Claude Code fires a mid-session-installed,
marker-keyed `PreToolUse` hook, and left `hooks/install-write-scope-hook.sh` in
the managed payload. `release-manifest.json` was resealed for it.

### Close the widen-while-still-`ready` bypass and same-field reconciliation gap (SPEC-302-001)

Two real, reproduced gaps in the SPEC-302 scope-widening reconciliation mechanism
are closed, both disclosed by SPEC-302's own independent verifier:

- `_scope_at_last_ready` now finds the commit where the spec's `status:`
  *transitioned into* `ready` (its immediately preceding commit for that spec
  file had a different `status:`, or none exists), not merely the most recent
  commit whose `status:` happens to read `ready`. A widening committed while
  `status:` remains `ready` (never touching `in_progress`) can no longer become
  its own reconciliation baseline and bypass the amendment gate.
- `_reconcile_scope_widening` no longer treats each field as a single
  baseline-or-current binary choice. A commit that both narrows (drops an
  existing item) and widens (adds an uncovered item) the *same* field now only
  reverts the specific uncovered addition — the narrowed-out item stays dropped,
  never silently restored as a side effect of blocking the widening. Applied
  consistently to `write`, `deny`, and `read`.

Neither gap was an AC failure of SPEC-302 (both AC1/AC3 passed on their tested
paths), but both were real weaknesses in a mechanism whose purpose is closing
exactly this class of enforcement gap. No change to SPEC-302's own tested paths.

### Mechanical scope-amendment gate (SPEC-302)

`scope_guard.scope_from_main` now reconciles a widened `scope.write`/`deny`/`read`
on main against the value that was in effect the last time the spec was `ready`,
before returning it. A widening with no covering `## Scope Amendments` row
(`Approved by: human`/`human:<name>`, dated on or after that ready commit) is not
honored for enforcement — the narrower prior value is used instead, per field, so
an unrelated narrowing in the same commit still takes effect immediately. A pure
narrowing never requires an amendment row. Both the evidence-gate check 6 script
and the git pre-commit guard (`scope_guard.py check`) read scope exclusively
through this one function, so the precondition applies identically at both
layers, with no duplicated matching logic. A spec that has never been `ready`, or
whose scope has never widened, validates and enforces unchanged.

- `scope_guard.py` gains `_scope_at_last_ready`, `_valid_amendment_rows`,
  `_covered_by_amendment`, and `_reconcile_scope_widening`, wired into
  `scope_from_main`.
- `Skills/nightshift/SKILL.md` documents the precondition alongside the existing
  "scope changes are human-approved, mechanically" paragraph, and its embedded
  check-6 gate script's `scope_self_edit` comparison now uses main's raw
  (unreconciled) scope so a worker-branch edit that leaves `scope:` untouched is
  never misclassified as a self-widening because of an unrelated, already-rolled-
  back widening on main.
- Kit-version bump for this change is deferred to the parent — `config.yaml`
  (`kit_version`) is outside this spec's declared `scope.write`.

### The canonical-suite preflight bound tracks the suite again (BUG-320)

`release_coordinator.py`'s `CANONICAL_SUITE_TIMEOUT_S` was 600s, set when the
canonical suite measured 305.25s. By 3.17.0 a **green** suite measured 996.10s
(3448 passed, 11 skipped) through the manifest's own declared `uv` environment,
so the guard that exists to catch a *hang* was converting every healthy release
into `failure_class: canonical_preflight` and touching no install. Raised to
2100s, and the pinning test now carries the new measurement and asserts the
headroom *relation* (cap − measured ≥ measured) plus the timeout message built
from the constant, so the next module that lengthens the suite fails that
arithmetic instead of silently blocking releases. The guard is unchanged in
every other respect: still finite, still enforced on both the probe and the
suite step, still `returncode 124` → preflight failure with zero fleet mutation.

### The kit's own guard no longer blocks the kit's own release (BUG-321)

`scope_guard.py`'s universal "spec files have one home" rule matches on basename
(`^(SPEC-.+|NFR-.+|.+-QUESTIONS-.+)\.md$`), and `SPEC-GUIDE.md` matches it.
`SPEC-GUIDE.md` is not a spec — it is the kit's authoring guide, a
`CANONICAL_PROTOCOL_FILES` member that correctly lives at the kit root — so every
write to it was denied `spec_wrong_home`. It is the only manifest member the
pattern catches (checked across all 115 managed files).

Because `hooks/protect-write-scope.sh` runs that classification in `pre-commit`,
and `release_coordinator.py` delivers payload and then commits it, **a kit
release could not be committed in any repository with the write-scope hook
installed** — enforcement blocking delivery, through the one universal rule that
applies with no active spec and has no environment-variable bypass. It halted the
3.17.0 rollout live, after three repositories had already committed.

The rule now exempts paths that are members of the kit's own release manifest,
read from `release-marker.json` (embedded in every install) or
`release-manifest.json` (canonical). Keyed on membership, not on a filename, so a
future managed file with a spec-shaped name needs no further patch. Enforcement
is unchanged everywhere else: a spec-shaped path under the kit that is *not*
payload is still denied, the same basename outside the kit is still denied, and
missing or malformed kit metadata means "not payload" — the rule fails closed.

Latent until now because the rule only began genuinely enforcing when BUG-020
made `_discover_specs_dirs`' hardcoded fallback reachable; before that it fell
open whenever `doctor.py`'s import raised, which it does under Python 3.14.

### Shipped kit shell satisfies a receiving project's shellcheck gate (BUG-322)

`hooks/install-write-scope-guard.sh` assigns the snippet its installer writes
into a target `pre-commit`. The single quotes are load-bearing — the snippet must
reach that hook as literal text so `$(git rev-parse …)` expands when the
*installed* hook runs, not when the installer does — but `shellcheck` reports
`SC2016 (info)` for it, and a project is entitled to treat any shellcheck finding
as a failure. `Fartownik`'s pre-commit does, so the coordinator's payload commit
was blocked there and the rollout halted after 15 installs across 10
repositories.

Declared with a targeted `# shellcheck disable=SC2016` plus a comment explaining
why the expansion is deliberate. The `SNIPPET=` value is byte-identical — the
diff is five added comment lines and nothing else. A sweep of every `.sh` file in
the manifest (six) finds no other finding.

Same family as BUG-321 — canonical payload failing a gate its own installs run —
but a different cause: a third-party linter with a legitimate observation about
deliberate code. Canonical still has no pre-release gate that runs the payload
through the checks installs apply to it; that gap is recorded as follow-up work
rather than patched a third time.

### Not in this payload

Work merged in the same window that changed no managed payload file, and so
carries no entry above: the TLA+ formal lane (SPEC-304 registry re-baseline and
drift lane, SPEC-305 executable trace conformance, SPEC-306 coverage ledger,
SPEC-308 scheduled lane and drift digest, SPEC-315 and SPEC-316 property
divergences) lives under `formal/`; BUG-021, BUG-022, BUG-310, BUG-311 and
BUG-312 corrected live-execution-checklist claims on already-`done` specs; and
BUG-314 re-pinned the `tla2tools.jar` v1.8.0 hash to the real rolling-prerelease
asset.

### Migration

None. `schema_version` stays `3.1.0`; no config or metrics schema change. An
install at 3.14.0 moves to 3.17.0 in one coordinator-applied step.


## 3.16.0 (2026-09-04)

### Scope enforcement at the evidence gate and the verifier (SPEC-300-002)

The evidence gate (Step 6) gains check 6 — **Scope**: every path in the candidate
branch's diff against main is classified by `scope_guard.py` against the spec's
declared write scope (SPEC-300-001), read from the spec file on main. A denied
path with no covering `## Scope Amendments` row fails the gate; the spec lands
`blocked` with `blocker_class: scope_violation`, `blocker_scope: out_of_scope`,
and a `block_reason` naming each offending path and its reason code. This class
is never auto-entered into the controller-backed unblock ladder — a human adds
the amendment row on main, after which `unblock_spec.py prepare` reports
`eligibility: eligible` for that spec.

- `scope_violation` added to `BLOCKER_CLASS_ENUM` (`record_metrics.py`,
  `validate_metrics.py`, `fleet_metrics.py`) and to `lifecycle.BLOCKER_CLASSES`.
- New `Nightshift-Scope-Check: clean|amended|violated|not_run` terminal-commit
  trailer, read by `record_metrics.py --mark-commit` into `resolution.scope_check`
  (`metrics/_SCHEMA.md`); a legacy commit with no trailer reads `absent`, not an
  error.
- The verifier brief (both the suite and no-suite templates) gains a fifth
  input, `Declared write scope`, rendered from main's `scope:` (or
  `project root (default)`) plus a fixed implicit-rule summary.
- The verdict schema gains `scope: {"checked": [...], "out_of_scope": [...],
  "amended": [...]}`; `validate_verdict` requires it and, given the standalone
  verifier surface, recomputes it from the `verifier-baseline..verifier-head`
  diff and rejects a disagreeing verdict.
- `unblock_spec.py prepare` treats a `scope_violation` packet as
  `eligibility: skipped` unless a `## Scope Amendments` row now covers every
  offending path named in `block_reason`.

## 3.15.0 (2026-09-04)

### Write-scope declaration, template v10, resolver library, validator (SPEC-300-001)

Specs can now declare `scope:` (`write`, `deny`, `read`) in frontmatter — a machine-readable
write boundary that later SPEC-300 children enforce (evidence-gate check 6, the git pre-commit
guard, and the harness `PreToolUse` hook). This child delivers the declaration, the shared
resolver, and the authoring step only; nothing yet blocks a misplaced write.

- **`specs/_TEMPLATE.md` → v10.** Adds a documented `scope:` frontmatter block and a
  `## Scope Amendments` body section (`Date | Path or glob | Change (old → new) | Reason |
  Approved by`). Migration: add nothing; absent `scope:` means project root.
- **New `scope_guard.py`.** `resolve_scope`, `classify_write`, `classify_read`, `active_spec`,
  `scope_from_main`, and a `check` CLI. Implements every default/implicit rule from SPEC-300
  § Defaults (project-root default, implicit kit evidence paths, heartbeat exception, spec-home
  rule, malformed-target rule, deny-wins) behind ten controlled reason codes.
- **`validate_specs.py`** validates `scope:` (lists of strings, no absolute paths, no `..`, no
  `{{...}}` anchors) and `## Scope Amendments` (`Approved by` must be `human` or `human:<name>`);
  warns (never errors) when a `ready` feature/bugfix/refactor spec has neither `scope:` nor
  `touches:`.
- **`SPEC-GUIDE.md`** gains a "Write scope" section documenting the field, defaults, implicit
  rules, amendment rule, and all ten reason codes.
- **`Skills/nightshift/SKILL.md`** — the `/nightshift spec` interview proposes `scope.write` from
  Context paths and `touches:`; the kickoff brief boilerplate states the resolved scope and the
  deny-then-retry rule.
- Existing specs validate unchanged — `scope:` is entirely optional, and no historical spec is
  retroactively required to declare one.

Out of scope for this child: enforcement (SPEC-300-002/003/004), deriving `touches:` from
`scope.write`, migrating historical specs to v10.

### Git pre-commit write-scope guard (SPEC-300-003)

A misplaced write that survives every harness-side check still has to pass through `git commit`
in the worker's worktree. Git hooks live in the shared common directory, so this is the earliest
portable point to reject an out-of-scope path, before it reaches a branch the parent has to diff.

- **New `hooks/protect-write-scope.sh`.** Resolves the active spec via `scope_guard.py
  active_spec` (env var, then the `nightshift/<SPEC-ID>-<run-id>` branch); with no active spec it
  enforces only the two universal rules (spec-home, malformed-target). With an active spec, it
  reads `scope.write` from the spec on the configured main branch (never the worktree or worker
  branch) and classifies every staged path (`git diff --cached --name-status --diff-filter=ACDMR
  -M -z`, both sides of a rename) with the shared `scope_guard.py` resolver. Rejects the commit
  with a dedicated exit code (96 — `protect-live-data.sh` already owns 97) on any `DENY`, printing
  the offending paths, their reason codes, the spec ID, and the declared `write` globs. Fails
  **open** on internal error (missing resolver, git failure) with a `[nightshift write-scope]`
  warning; no environment-variable bypass exists — only a `## Scope Amendments` row on main or
  removing the path from the index can commit an out-of-scope write.
- **New `hooks/install-write-scope-guard.sh`.** Idempotent chaining installer (marker
  `# SPEC-300-003 protect-write-scope`, inserted before a trailing `exit 0`), resolving the guard
  from either the Argo Home or `.nightshift/hooks/` layout. Refuses to touch an unrecognised
  pre-commit hook rather than silently altering it.
- **`hooks/guard-registry.yaml`** gains the write-scope guard entry so the generic guard-liveness
  checker (`preflight.check_guard_liveness`) reports it for opted-in protected checkouts.
- **Managed `hooks/pre-commit`** now runs the guard (when present) before lint/type-check, so a
  scope rejection surfaces before slower gates run.
- **`doctor.py`** gains finding `D7` (`WARNING`): the kit ships `protect-write-scope.sh` but the
  repository's common-dir pre-commit hook lacks the marker. `doctor --fix` runs the installer for
  that repository; doctor never edits an unrecognised hook, and the installer's refusal becomes
  the finding's remedy text.
- **Release manifest** — both new scripts join the managed payload set (executable mode).

### Harness `PreToolUse` write-scope hook (SPEC-300-004)

The guard and the gate catch a misplaced write after it happened, and the file may already be
untracked and invisible to `git diff`. This child adds the earliest enforcement point: a Claude
Code `PreToolUse` hook that stops an out-of-scope write before the tool call executes.

- **New `hooks/write-scope-hook.sh`.** Resolves the active spec the same way the git guard does
  (env var, then branch); with no active spec it enforces only the two universal rules. For
  `Edit|Write|MultiEdit|NotebookEdit`, classifies `tool_input.file_path`/`notebook_path` with
  `scope_guard.py` against `scope.write` as committed on main and denies with the spec ID, path,
  reason code, declared globs, and a "record it under `## Scope Blockers`" instruction. For
  `Bash`, best-effort extracts write targets from a bounded pattern list (redirects,
  `cp`/`mv`/`install`/`rsync`, `mkdir`/`touch`, `tee`, `sed -i`) and classifies each; an
  unparseable command is allowed (the git guard and evidence gate remain the backstops). The
  heartbeat `cp` to `reports/_wip/orchestrator-progress-<spec-id>.md` is explicitly allowed even
  when its destination sits in a sibling main checkout, outside the worker's own worktree. For
  `Read|Grep|Glob`, enforces `scope.read` only when it is a list; `unrestricted` (the default)
  exits without ever calling the resolver. Fails **open** on any internal error (missing
  `jq`/`python3`, missing resolver, unparsable input) with a `[nightshift write-scope]` stderr
  warning; no environment-variable bypass exists. A per-event debug line is appended to
  `reports/_wip/write-scope-hook-debug.log`, never to the tool's own output.
- **New `hooks/install-write-scope-hook.sh`.** Idempotently wires three `PreToolUse` entries
  (marker key `nightshift-write-scope`) into the project's `.claude/settings.json` without
  disturbing any other configured hook; `--uninstall` removes only the marked entries. Init and
  retrofit offer the install alongside the pre-commit hook offer.
- **`Skills/nightshift/SKILL.md`** documents that the hook fires for `isolation: "worktree"`
  workers launched from a project where it's installed (project-level setting, not per-worker),
  that a worker whose own settings omit it still meets the write-scope contract through the git
  guard and the evidence gate, and that Codex/Hermes have no equivalent hook today — both rely on
  the git guard and the gate, with the terminal commit's `Nightshift-Scope-Check:` trailer
  recording the outcome either way.
- **`EXTENSIONS.md`** gains a harness write-scope hook coverage matrix.
- **`doctor.py`** gains finding `D8` (`WARNING`): the kit ships `write-scope-hook.sh` but the
  repository's `.claude/settings.json` lacks the `nightshift-write-scope` entry. `doctor --fix`
  runs the installer; a project with no `.claude/` directory still gets the finding, with a manual
  step as the remedy — `--fix` never creates `.claude/` on its own.
- **Release manifest** — both new scripts join the managed payload set (executable mode).

### Conditional canonical-payload write-scope exception (SPEC-300-001-001)

SPEC-301 and SPEC-300-004-001 both hit the same friction: their `scope.write` named only the
source file they directly edited (e.g. `SKILL.md`), but the kickoff protocol's own mandatory
release-manifest regeneration step then required touching `release-manifest.json` (and often
`CHANGELOG.md`), which `scope_guard.py` correctly denied against the narrower declared scope
every time — a recurring, structural friction rather than a one-off authoring gap.

- **`scope_guard.py`** `classify_write` gains one new conditional implicit-allow rule, reusing the
  existing `implicit_kit_path` reason code (no new reason introduced): `<kit_dir>/CHANGELOG.md`
  and `<kit_dir>/release-manifest.json` are writable **only when** the spec's own declared
  `scope.write` already names at least one file that is itself a member of `nightshift-sync.py`'s
  `CANONICAL_PROTOCOL_FILES` — i.e. the spec is already legitimately editing managed canonical
  payload. A spec with no such relationship gets no exception; `release-manifest.json` still
  denies with its pre-existing reason code. The membership check loads `nightshift-sync.py`
  without importing it as a package module and fails **closed** (exception never fires) if the
  module cannot be located or loaded.
- **`specs/_TEMPLATE.md`** `scope:` authoring guidance documents the exception so an author does
  not need to add `release-manifest.json`/`CHANGELOG.md` to `write` by hand for a
  canonical-payload-editing spec.
- **`SPEC-GUIDE.md`** "Write scope" section documents the exception alongside the other
  implicit-allow rules, and the `implicit_kit_path` reason-code row now mentions it.
- Demonstrated live against SPEC-301's and SPEC-300-004-001's real, unchanged, already-`done`
  `scope.write` declarations: `scope_guard.py check` now returns `ALLOW implicit_kit_path` for
  the `release-manifest.json`/`CHANGELOG.md` edits both specs' workers made and originally
  recorded as `## Scope Blockers`.

Out of scope: which files are members of the release manifest's managed set (untouched here);
widening the implicit-allow rule to any file other than these two; the git pre-commit guard's and
harness hook's own copies of this logic (both call the same shared resolver, so this fix applies
to all three enforcement points).

## 3.14.0 (2026-09-01)

### Typed spec artifacts: persist the reason and evidence behind every status transition (SPEC-291)

A spec's lifecycle decisions were made on evidence that evaporated the moment the decision was
committed — a promotion left only a commit subject, never the reasoning or validation behind it.

- New per-spec artifact convention: `reports/<SPEC-ID>/artifacts/index.json` records every durable
  status transition (`status-transition`, `decision`, `validation-evidence`, `context`, `verifier`,
  `other` — a closed, registered vocabulary) with `type`, `created`, `actor`, `summary`, and path.
- `StatusStore.transition_commit_backed` now requires and durably records a `reason` for every
  judgment transition (promotions, blocks, supersessions, manual board moves); mechanical
  transitions (`ready -> in_progress`, evidence-gated `-> done`, controller-verified
  `blocked -> ready`) synthesize their reason from the run ID automatically.
- New canonical entrypoints: `spec_artifacts.py` (index read/write/validate + `record-transition`
  CLI) and `spec_promotion.py` (the `draft`/`planned -> ready` promotion entrypoint, persisting the
  resolved `promotion_gap` rationale and gathered findings as artifacts).
- `validate_specs.py` validates every artifact index (schema, registry membership, tracked paths, no
  orphan files) from this release's cutover forward — historical transitions are not retroactively
  required to have artifacts.
- The board spec-detail panel lists each spec's artifact history; the kickoff/run brief scaffold
  includes the artifact-index summary when one exists.

### Dispose of the stranded pending release handoffs SPEC-244 made legible (SPEC-251)

Gave every stranded pending release-handoff record (43 live at implementation time) exactly one
recorded disposition — `re-pin` (still needs shipping), `fold` (ships in the next release), or
`retire` (never will, with a written reason) — grounded in fleet-presence evidence, never inferred
from age. A new mechanical check (`release_handoff.stranded_disposition_findings`) fails validation
if the stranded set regrows without a disposition on every member.

### Let a spec author a release handoff without stranding it on its own implementation (SPEC-253)

A handoff authored while its own spec is still in flight has no real manifest fingerprint to pin yet.
The coordinator now mechanically re-pins a pending record's `manifest_fingerprint`/`target_version`
to the manifest actually being released, at release time, before any completion check — a
formalization of manual practice that previously happened by hand on every release. A record whose
`changed_managed_paths` content genuinely differs from what's being released is reported, never
silently re-targeted.

### Re-target or deliver pending release handoffs when `kit_version` bumps (SPEC-277)

A `kit_version` bump previously stranded every pending handoff still targeting the outgoing version
in one shot (nine at once, in the SPEC-239 bump). Adopts SPEC-253's mechanical re-pin for the bump
case rather than a second bump-specific mechanism, and teaches `validate_specs` to distinguish "
stranded by an in-flight bump, resolved automatically at next release" from "stranded and abandoned,
needs operator attention."

### Constrain `invocation_kind` to the documented vocabulary at every admission caller (SPEC-245)

Every `validate_install.run_validation` call site now passes one of the documented
`INVOCATION_KINDS` values instead of an ad hoc string, closing the gap where an undocumented
invocation kind could silently bypass admission classification.

### Promote the evidence-arithmetic gate to a shared canonical helper (SPEC-246)

The evidence-gate arithmetic used by SPEC-229-006's live end-to-end tests is now a shared
`evidence_arithmetic.py` helper (renamed from a test-local module) with its own dedicated coverage,
removing duplicated gate logic between the live and fixture-driven test suites.

### Document the sanctioned procedure for discharging a canonical-copy drift alarm (SPEC-254)

`canonical_copies.py`'s drift alarm previously had no documented, sanctioned discharge procedure —
an agent hitting it had to reason out a fix from scratch. Documents the exact procedure and adds a
disk-resolved guard so the alarm can't be silently bypassed.

### Make the commit-time canonical-copy guard fire for out-of-repo copies (SPEC-255)

The canonical-copy drift guard previously only checked copies inside the same repository; a copy
living outside the repo entirely could drift without ever tripping the alarm. The guard now resolves
copy paths from disk rather than assuming repo-relative placement.

### Reconcile the blocked-commit subject template with `MARK_COMMIT_RE` (SPEC-256)

The documented blocked-commit subject template in `SKILL.md` didn't match the regex
`record_metrics.py`'s commit-msg hook actually enforces, producing commits that looked correct but
were silently rejected. Corrected the template and added a regression test pinning the two together.

### Classify the live validation error floor into spec-owned and unowned findings (SPEC-270)

`validate_specs.py specs` produces hundreds of findings with no way to tell "known, owned by an open
spec, deliberately not fixed yet" from "nobody's watching this." New `owns_findings:` frontmatter
field plus a family-key classifier attribute each finding to its owning open spec(s) or mark it
unowned; a committed baseline artifact lets a later run diff what changed, including a family change
that leaves the total count flat.

### Decide the release_handoff declaration for a spec in a terminal non-delivering status (SPEC-271)

A spec that reaches `superseded` keeps whatever `release_handoff: impact: required` declaration it
had while live, producing a permanent, unclearable "requires a release handoff artifact" finding for
work that will never ship. `superseded` (the one terminal, non-delivering lifecycle status) now
defaults to suppressing that finding without touching the declaration; a dedicated, separately
evidenced function lets an authorized re-classification (`required -> exempt`) happen deliberately,
never as a side effect of the status transition itself.

### Extend the artifact-side reachability sweep to the reports and runs directories (SPEC-272)

Extends SPEC-252's artifact-reachability sweep (previously scoped to `release-handoffs/`) to
`canonical/reports/` (reachable via a `SPEC-<id>`/`BUG-<id>` name-token, or one of two closed named
exception shapes) and `canonical/runs/` (reachable via an `events.jsonl` `spec_id`, never by
directory naming) — closing the gap where an artifact-side entry referencing no live spec, or
referenced by nothing, was invisible to validation.

### Give a terminal commit a safe correction path on a shared branch (SPEC-275)

Correcting a wrong evidence trailer on an already-landed terminal commit previously had no safe path
on a shared branch — `git commit --amend` risks rewriting a concurrent writer's commit if `HEAD` has
advanced. Adds a documented, non-amend correction-commit path plus `record_metrics.py
--correct-commit`/`--verify-amend-head` guards.

### An externally resolved blocker has no controller-sanctioned path back to ready (SPEC-276)

A spec blocked by the controller, then fixed by something outside the controller's own unblock
ladder (a manual fix, an upstream dependency landing), had no sanctioned way back to `ready` without
either re-running the full ladder from scratch or a raw frontmatter edit. `unblock_spec.py`'s
`record_attempt` now accepts an externally-resolved recovery path with its own evidence requirement,
relaxing the gate without weakening the evidence bar.

### Serialize manifest-touching integration with a release-surface lease (SPEC-278)

Concurrent Nightshift runs integrating manifest-touching changes at the same time could race each
other's manifest reseals. `parallel_executor.py` gains a `ReleaseSurfaceLease`
(`fcntl.flock(LOCK_EX | LOCK_NB)`, 5s acquire / 300s hold bound) that the coordinator holds for the
duration of a manifest-touching integration, serializing what used to be an unguarded race.

### BUG-016 — A spec renders in one board column while its details show a different status

Fixed a board rendering path where a spec's column placement and its detail-panel status could
disagree after a status write, with new regression coverage in `test_board_api.py`.

### Persist a status-transfer refusal on the spec instead of only in a vanishing toast (SPEC-290)

A board drag or status-dropdown move refused by a client-side pre-check (the NFR
active/retired-only rule) or a server-refused `/api/spec/<id>/status` write reported the
reason only in a toast that auto-hides after 3 seconds. There was no durable record of what
was refused or why once the toast faded, and — unlike the board's existing `block_reason`
convention — nothing survived in the spec file for another tool or agent to discover.

- New frontmatter field `transfer_refusal`, written server-side to the spec file (matching
  `block_reason`'s mechanism) whenever a status-transfer request is refused, from either
  refusal source (client pre-check via new `POST /api/spec/<id>/transfer-refusal`, or a
  server-refused write inside `SpecCache.update_status`) — both converge on the same
  persisted shape.
- A network-level failure (thrown before any `Response` exists) still persists a refusal
  record using the same generic fallback toast text, via the same POST endpoint.
- Cleared automatically the next time that spec's status write succeeds, and via a new
  manual dismiss control in the panel (`DELETE /api/spec/<id>/transfer-refusal`) that clears
  it without requiring a successful move first.
- The panel's `block_reason` row gets a subtle reddish background hint and the new
  `transfer_refusal` row a subtle, distinct amber hint, both theme-adaptive (reusing the
  existing `--c-blocked` / `--c-active` tokens via `color-mix()`).
- `transfer_refusal` registered in `vocabulary-registry.yaml` (tooltip help text) and given a
  shape check in `validate_specs.py` (non-empty string when present).
- The toast, its 3-second auto-hide, and all existing successful status-write behavior are
  unchanged.

## 3.13.0 (2026-08-30)

### Resolve portable anchors in declared external verifier inputs (SPEC-289)

SPEC-288's `external-evidence:<repository-root>#<repository-relative-path>` declarations
could not both validate and execute: `validate_specs.py` (SPEC-071) correctly rejected a
literal absolute repository root as a host-path leak and required a `{{ANCHOR}}`-relative
token, while `verification_report.py::_resolve_one_declaration` called only
`os.path.expanduser` on the root — which expands `~` but never resolves `{{ARGO_HOME}}`-style
tokens — so the portable spelling was refused as `not_a_git_repository`. No declaration could
satisfy both gates, blocking the motivating case, SPEC-ARGO-067.

- `_resolve_declared_root` now routes only the repository-root component of a declaration
  through the canonical `path_vars.resolve(..., mode="execute")` primitive, against the
  subject project root supplied to verifier-surface construction — no second token parser.
- New named refusal reason `anchor_resolution` (18 → 19) replaces the misleading
  `not_a_git_repository` for an unknown or unresolvable anchor; refuses before any source
  byte is read or any arm is created.
- Every SPEC-288 containment property is unchanged: report-root/same-spec refusal still fires
  after an anchor resolves, source object databases stay unreachable, inert (no-declaration)
  dispatch is byte-identical to before.
- `Skills/nightshift/SKILL.md` documents the anchor-capable declaration syntax and the
  ordered SPEC-ARGO-067 closure packet (new declaration-only baseline, dedicated run ID,
  independent verifier dispatch; explicitly no model or LM Studio command).

### Ship the reviewer prompts LOOP.md dispatches against (BUG-015)

`LOOP.md` Steps 7, 9.5, and 10 dispatch reviewers using three prompt files
(`prompts/spec-reviewer.md`, `prompts/quality-reviewer.md`, `prompts/completion-checklist.md`)
that existed nowhere in canonical's tracked history and were entirely absent from
`release-manifest.json`'s managed scope — so a board configured `review.mode: subagent` or
`hybrid` reached a missing file, and authoring the files in canonical alone would not have
put them on any installed board.

- The three files now exist in `canonical/prompts/`, sourced from the pre-relocation
  canonical originals (verified against `LOOP.md`'s actual dispatch placeholders, not
  assumed), and are managed release payload for the first time (101 → 104 files).
- New guard `tests/test_canonical_prompt_assets.py` fails whenever a `.nightshift/prompts/<name>`
  path referenced from a canonical `.md` file has no counterpart in `canonical/prompts/` or is
  absent from the release manifest — the same-spirit sibling to the existing copy-drift guard.
- The A/B prompt-variant registry already in `canonical/prompts/` is unaffected and remains
  unmanaged, project-owned state.

## 3.12.0 (2026-08-30)

### Predeclared external evidence reaches the verifier, under containment (SPEC-288)

A spec whose durable evidence lives in *another* repository was structurally
unverifiable. `verification_report.py` built the standalone verifier surface from
the subject repository alone and ignored `context.required_inputs` entirely, so
SPEC-ARGO-067 — which needs the retained Hermes benchmark run in
`Tools/benchmarks` — had no way to produce a verdict at all. Thirty-one Argo specs
reference paths outside Argo Home, so this is a category, not one spec.

The obvious fix is the dangerous one. Handing a verifier a declared host path
would break the standalone containment model outright and would let a candidate
point its verifier at its own report. This release instead *projects* the bytes
and never exposes a path.

- **`prepare-dispatch --spec-path <repo-relative-spec>`** (also on
  `prepare-surface`) reads that spec's `context.required_inputs` from the commit
  at **each** verifier arm. Entries of the form
  `external-evidence:<repository-root>#<repository-relative-path>` are eligible;
  every other entry keeps its existing meaning and is untouched.
- **The two arms must declare identically.** The declaration is read from the
  committed spec, never the working tree, and a candidate that adds, changes, or
  removes an `external-evidence:` entry during its own run is refused before the
  verifier launches rather than resolved in either arm's favour.
- **Resolve, pin, project.** Each admitted input must be a regular tracked file,
  or a bounded tracked directory (≤256 members, ≤8 MiB projected in total), that
  is committed and clean at its source. Its bytes are read from the source
  repository's Git object database at a pinned commit and copied into
  `.nightshift-verifier-inputs/<source-repository-id>/<source-path>` inside both
  arms as regular read-only files. No symlink, no shared object database, no host
  path: the projection keeps working when the source checkout is gone.
- **Declaration never overrides containment.** A declared path that lies under a
  report root, or that identifies the spec under verification, is refused even
  though it was declared. SPEC-228/239 same-spec withholding is unchanged.
- **Fail closed, by name.** Eighteen reasons — `declaration_not_identical`,
  `malformed_declaration`, `same_spec_report`, `report_root`, `same_spec_content`,
  `absolute_path_escapes_source_repository`, `path_traversal`,
  `not_a_git_repository`, `symlink`, `symlink_member`, `missing`, `untracked`,
  `untracked_member`, `mutable`, `unsupported_entry_type`,
  `directory_bounds_exceeded`, `namespace_collision`, `projection_collision` —
  each writes durable refusal evidence and leaves no surface at all, so no
  rejected byte can reach either arm.
- **Recorded both sides.** Containment evidence gains `declared_external_inputs`
  (declaration, source identity, pinned commit, object ID, projected path, digest,
  handling). The verifier receives a sanitized `MANIFEST.json` inside the
  namespace — no declaration string, no host path — which is how it distinguishes
  a projection from native subject-repository content.
- **The evidence source need not be a managed Nightshift install.** A
  `committed_kit: opt_out` repository such as `Tools/benchmarks` is a valid
  source; only Git-committed, clean content is required.

`CONTAINMENT_EVIDENCE_SCHEMA_VERSION` is `1.6.0`. The identity projection is
deliberately unchanged: projected bytes are already bound through
`synthetic_head_tree`, and the records through `containment_evidence_sha256`, so
`identity_schema_version` stays `1.0.0` and every existing digest is unaffected.

**Migration: none.** Without `--spec-path` the mechanism is inert and a dispatch
is byte-equivalent in surface shape to a 3.11.3 one, including projects whose
specs already populate `context.required_inputs`.

## 3.11.3 (2026-08-30)

### One line is scanned in time linear in its length (SPEC-287)

`scanner._scan_line` re-read the whole preceding text once per candidate. Two
context helpers each sliced `text[: match.start()]` and scanned it —
`_phone_context_ok`, which decides whether an undelimited digit run is introduced
by a phone keyword, and `_url_path_context`, which decides whether a long digit
run is a resource id inside a URL path. Candidate count grows with line length,
so one line cost O(candidates × length).

Measured on a release-marker-shaped single line: `_scan_line` took 3.07 s at
100 KB, 12.04 s at 200 KB, 47.94 s at 400 KB and 192.86 s at 800 KB — a clean 4×
per doubling, which extrapolates to hours for one 8 MB line and to roughly an
hour per megabyte beyond that. A pre-commit gate on a repository holding any
large single-line file could stall indefinitely with no finding to show for it.
This was live in every install: `scanner.py` is release payload.

- Both helpers now read only the text between the previous candidate and the
  current one. Those windows are disjoint, so a whole line costs one pass. The
  same corpora now take 0.06 s at 400 KB and 0.26 s at 1.6 MB, and one 8 MB line
  scans in about 1.3 s.
- **No detection rule, pattern or threshold changed.** `PHONE_CONTEXT_PATTERN` is
  untouched, quantifiers included: its separator runs are still unbounded, so a
  phone keyword thousands of separator characters ahead of the number is still
  context, exactly as before. The narrower fixed-window alternative was rejected
  for that reason and is recorded in the spec.
- The phone rule is proved equivalent rather than assumed: the pattern cannot
  match a digit anywhere, and the previous candidate ends on ten digits, so no
  context match can end at this candidate and also reach back across it.
  `Pattern.search(text, pos, endpos)` is used instead of a slice because `pos`
  restricts only where a match may begin, while `\b` and lookbehind still read the
  real text before it and `endpos` reproduces the slice's `$`.
- The URL-path rule is carried by a small accumulator, `_UrlPathContext`, holding
  the token start, its first `/`, whether a non-`/` follows that `/`, and whether
  `://` appears. `_url_path_context` remains as the single-shot form.
- Guards added to the canonical suite: an 8 MB line must scan in under 5 s, and
  the cost ratio across a 4× step in line length must stay under 8 (linear is
  about 4, the old quadratic about 16). Both are ratio- or budget-based rather
  than wall-clock constants, so they survive different hardware. A seeded
  differential test checks both helpers against the pre-change expressions,
  which are kept verbatim in the test file as the oracle.

**Migration:** none. Behaviour is identical; only the cost changed. Installs pick
this up with the payload.

## 3.11.2 (2026-08-30)

### The verifier footprint is asserted by porcelain set comparison, not emptiness (SPEC-284)

`verifier_footprint_errors(before, after)` accepted a `before` footprint and then
discarded `before.porcelain`. Trees were compared correctly, but the working tree
was tested for *emptiness* of `after.porcelain` — a test of whether the worktree
happened to be clean when the verifier was handed it, not of what the verifier
did. `capture_verifier_footprint` already recorded `porcelain` on both snapshots,
so the data for a real comparison was collected and thrown away.

The consequence was a gate firing on correct input. Any pre-existing dirt at
dispatch — an untracked scratch file, a generated artifact, an unrelated modified
file in the operator's checkout — made a verifier that wrote nothing report
`FOOTPRINT: violated`, and the validator return `GATE: reject`. Measured on the
Argo board on 2026-08-19: zero verifier writes, tree hash identical, verdict
rejected.

- The working-tree half is now a set comparison of the two snapshots. An entry in
  both was already there and is not attributable to the verifier. An entry only
  in `after` was added; an entry only in `before` was removed. Both are writes —
  a verifier that tidies up after itself has still written to the worktree.
- The comparison unit is the whole `XY path` status line, so a path present in
  both snapshots under a changed status is still caught.
- `VERIFIER_FOOTPRINT_EXCLUSIONS` and `is_excluded_verifier_footprint_path` are
  retired. They hardcoded one project's generated artifact into the shared kit to
  paper over the emptiness test. Under the set comparison that entry cancels on
  its own, in every project, and no project-specific path remains.
- The tree-hash assertion is unchanged and undiminished: a verifier that modifies
  a tracked file, adds an untracked path, or removes a pre-existing one still
  voids its verdict.

**Verdict schema (additive).** Each `git_footprint` arm now carries
`porcelain_before` alongside `porcelain_after`; the previous `porcelain` key is
renamed to `porcelain_after` for symmetry. `identity_schema_version` is
deliberately unchanged — it binds `implementation_head_digest` identity, not the
footprint shape. `CONTAINMENT_EVIDENCE_SCHEMA_VERSION` moves 1.4.0 -> 1.5.0, and
is outside the identity projection, so verifier identity digests are unchanged.

**Migration.** Verifiers must report both fields per arm. The shipped
`NIGHTSHIFT-VERDICT-VALIDATOR` recomputes the comparison from the verdict's own
two sets and rejects an arm that records only the old flat `porcelain` key —
reading a missing before-set as empty would silently accept real dirt. The
`footprint_before` helper in the skill now emits the arm's tree hash followed by
its working-tree entries, and `footprint_after` set-compares against it; both
sides of the pair must be taken from the same release.

## 3.11.1 (2026-08-30)

### An absolute tracked symlink no longer makes the verifier surface unbuildable (SPEC-285)

`_materialize_ref` in `verification_report.py` resolved every tracked symlink's
link text against the entry's own parent directory inside the surface. For an
**absolute** link text pathlib discards the left operand, so the resolution was
the raw target, `commonpath` was `/`, and the containment check raised
unconditionally. A relative traversal attempt (`../../etc/passwd`) and an
absolute link to an ordinary file outside the repository were indistinguishable
to that predicate, though only the first is the threat it guards against.

The failure was total, not partial: `prepare-dispatch` exited nonzero, the
parent recorded the controlled evidence gap `verifier_surface_unavailable`, and
no spec in an affected repository could reach a verifier verdict at all. Argo
Home is affected today through its tracked `AGENTS.md -> ~/.claude/CLAUDE.md`,
which is its documented Codex entry point and not retargetable.

- The traversal guard is now scoped to the threat it was written for: a
  **relative** link text that resolves outside the surface destination is still
  refused, and the diagnostic names the path, the link text, and the reason
  rather than a bare "escapes".
- An **absolute** link text landing outside the surface is materialized as a
  visible regular file containing the link text. The entry stays present and the
  verifier can see what it pointed at, while a plain file cannot be followed
  anywhere — so SPEC-228/239 containment holds trivially and the verifier gains
  no read path out of the surface.
- An absolute link text landing *inside* the surface, and any in-surface
  relative symlink, still materialize as ordinary working symlinks. This is not
  a blanket retreat from symlinks.
- Containment evidence gains `transformed_symlinks`: per ref, per entry, the
  path, the original link target, and the handling applied
  (`link-text-file`), so a transformed entry is distinguishable from one whose
  content merely differs. `CONTAINMENT_EVIDENCE_SCHEMA_VERSION` 1.3.0 → 1.4.0.
  The key is additive and outside the identity projection, so verifier identity
  digests are unchanged.
- `verifier-self-test` now carries both symlink shapes, making the repair part
  of the managed release smoke contract.

No config or protocol change; no migration required.

## 3.11.0 (2026-08-30)

### Whole-kit release of the resilient-unblock kit with a registered config migration (SPEC-269)

Bundles the fleet-facing release of the drive-to-done/resilience work landed across
five prior specs, each already documented under its own heading below, plus this
spec's own release-mechanics contribution:

- SPEC-259 — the opt-in `/nightshift unblock <spec-id> --to-done` recovery ladder.
- SPEC-260 — independent AC-review validation and rung-4 veto escalation.
- SPEC-266 — the in-loop `resilience.*` recovery ladder (verifier_fail, premise,
  evidence_gap, transport).
- SPEC-267 — the machine-parseable, harness-aware command tutorial.
- SPEC-268 — the board's drive-to-done copy prompt.

Fleet installs previously received these changes only by reading the canonical
repo's protocol docs; without a whole-kit release and a config migration, an
install's `config.yaml` never gained the `resilience.*`/`unblock.*` blocks that
SPEC-266/SPEC-259/SPEC-260 depend on, even after the kit's `config.yaml` schema
carried them.

- `config.yaml`/`config-reference.yaml` `schema_version` bumped `"3.0.0"` →
  `"3.1.0"` (additive, non-breaking): the schema now formally documents the
  `resilience.*` and `unblock.*` blocks that were already shipped as protocol
  behavior but never reflected in the schema version.
- Added `config_migrations.py`: a pure, idempotent, deterministic migration
  (`add_resilience_and_unblock_blocks`) that adds the `resilience.*`/`unblock.*`
  blocks with their documented starter defaults to an install's `config.yaml`
  only when a block is absent, and bumps `schema_version` to `"3.1.0"`. A config
  already at or above `"3.1.0"` is returned byte-identical (untouched); applying
  the migration twice is identical to applying it once. This is "the registered
  deterministic migration" `Skills/nightshift/SKILL.md` Step 3 (`/nightshift
  release`) requires the coordinator's per-install migration workers to follow.
- `release.py`'s manifest builder now reads `schema_version` from the canonical
  `config.yaml` (falling back to `"3.0.0"` when absent, matching prior behavior)
  instead of hard-coding `"3.0.0"` into every release manifest — the coordinator's
  `_migration_needed()` check depends on this to ever flag an install as
  requiring the SPEC-269 migration.
- `release.py`'s `write_manifest()` no longer nests a retained manifest's own
  `retained_manifests`/`unretained_manifests` inside the entry it retains. Each
  nested copy duplicated a manifest already sitting beside it in the same flat
  list, so every release doubled the manifest — 12KB at 3.8.4 growing to 60MB by
  3.11.0 across eleven releases — while `resolve_retained_manifest()` never
  recursed into the nested copies and so could never reach them. The 3.11.0
  manifest is 221KB; all eleven retained releases keep their `kit_version`,
  `fingerprint`, and complete `files` list. This also unblocks the release
  itself: `release-marker.json` embeds the manifest, and a 29MB single-line
  marker stalled content-scanning pre-commit hooks in the fleet for tens of
  minutes per install.
- `scanner.py` now recognizes every managed install staged in a repository
  rather than only a root-level `.nightshift/`. New `staged_install_prefixes()`
  derives each install prefix from the staged paths, and the managed-payload
  guard, retained manifest, and exemption run once per install. A repository
  with a nested install — Argo Home carries both `.nightshift/` and
  `Skills/focus/.nightshift/` — previously had the nested install's verified
  release bytes left outside the exemption, so a whole-kit release counted its
  own payload toward the diff-size escalation (673 of 1,303 added lines) and
  demanded a human sign-off on every release. Project-owned paths such as
  `config.yaml` remain unexempted under every prefix.

## 3.10.2 (2026-08-29)

### Materialize both verifier suite arms before read-only dispatch (SPEC-282)

- `prepare_verifier_surface()` now checks out each of `verifier-baseline` and
  `verifier-head` into its own dedicated, already-runnable working directory
  (linked worktrees of the standalone verifier repository only, never of the
  source repository), instead of leaving both as bare tags inside a single
  working tree checked out at head. Recorded in containment evidence as
  `surface_repositories`; `containment_evidence_schema_version` bumped to
  1.3.0 (additive field, not part of the closed identity projection).
- `PreparedVerifierDispatch.public_plan()` gains `arm_working_directories`
  (`{"baseline": ..., "head": ...}`) so the verifier brief can assign each arm
  its own read-only working directory without any verifier-side checkout.
- Added `capture_verifier_footprints()` / `verifier_footprint_errors_multi()`
  to assert the read-only footprint gate over both assigned arm surfaces
  (SPEC-228 R4): mutation or an unexpected generated artifact in either arm
  voids the verdict.
- `Skills/nightshift/SKILL.md` Step 5c: the dispatch boundary prose, the
  verifier brief's assignment instructions, the footprint-capture snippet,
  the verdict's `git_footprint` schema, and the embedded verdict validator
  script now cover both materialized arms. The validator additionally rejects
  a suite sample declaring `"executed": false`, a suite entry missing either
  arm's samples, and a synthetic zero-count placeholder sample (zero passed,
  zero failed, no failing names) — each as its own controlled evidence-gap
  reason, never as an empty passing sample (SPEC-228, observed against
  SPEC-279-001's verdict).


## 3.10.1 (2026-08-29)

### Board drive-to-done copy prompt (SPEC-268)

- Added `⛒ COPY DRIVE-TO-DONE PROMPT`, visible only while the open spec is
  `blocked` (hides `▶ COPY RUN PROMPT` in that state). `buildDriveToDonePrompt`
  emits a harness-neutral body: `$nightshift unblock <id> --to-done` first,
  with the `/nightshift` form for Claude Code / Hermes and other CLIs in
  parentheses, plus a `--from-rung 3` hint when the blocker class is
  `evidence_gap`.
- `buildRunPrompt`'s kickoff line gained the same harness-syntax note.

### Extend release-handoff hash coverage to non-manifest release inputs (SPEC-283)

- `release_handoff._manifest_sha256()` now accepts an optional `canonical` root
  and, when supplied, also hashes the current bytes of the non-manifest release
  inputs `managed_paths()` accepts (`config.yaml`, `release-manifest.json`).
- `build_delivery_receipt()` and `validate_positive_delivery()` accept and
  thread through the same optional `canonical` parameter; `complete_pending_handoffs()`
  now passes it. A handoff declaring `config.yaml`/`release-manifest.json` in
  `changed_managed_paths` can now be positively verified and completed, instead
  of staying `status: pending` forever.

## 3.10.0 (2026-08-29)

### In-loop resilience ladder (SPEC-266)

- Added parent-owned, run-id-keyed recovery decisions for verifier failure,
  premise dispute, evidence gap, and transport stall before terminal blocked.
- Added `resilience.*` defaults and controlled `resilience_rung` telemetry.

## 3.9.3 (2026-08-29)

### Harness-aware command tutorial (SPEC-267)

- Added a fenced YAML `commands` registry to the Nightshift skill and a
  read-only `skill_tutorial.py` renderer for `tutorial [command]` and its
  `help [command]` alias. It presents every command, its options and decision
  tree, then provides focused purpose, limits, side effects, prompts, and
  real-repository examples.
- Rendering uses `$nightshift …` under Codex and `/nightshift …` elsewhere.
  The registry-consistency test rejects both missing registry rows and missing
  command headings before the guide can drift.

### AC-review amendment gate (SPEC-260)

- Added independent AC-review validation, mandatory AC Amendments documentation,
  and rung-4 veto escalation to user authorization.

### Drive-to-done recovery ladder (SPEC-259)

- Added the opt-in `/nightshift unblock <spec-id> --to-done` ladder with
  `--from-rung <2-4>` and mutation-free `--dry-run` planning.
- Preserved ordinary unblock packet and attempt behavior; only opt-in skipped
  admission adds `escalate: true`.
- Added parent-owned `unblock_rung` evidence events and terminal
  `Nightshift-Unblock-Rung` metrics ingestion. Workers remain evidence-only.
- Documented the drive-to-done defaults and the pre-SPEC-260 rung-4
  `unavailable` route to human authorization.

> The `runtime.loop_version` field (date-based) tracks when the LOOP.md was last touched
> and is used for metrics comparison — it is NOT the authoritative version.

---

## 3.9.2 (2026-08-29)

### Board toast surfaces the real status-write failure reason (SPEC-281)

- `PUT /api/spec/{id}/status` already returned a specific, actionable `detail`
  string on refusal (NFR/handoff/promotion-gap validation), but all three
  frontend failure sites in `board.py` — the drag-end handler's not-ok
  branch, its network-error `.catch`, and the detail-panel status dropdown's
  handler — discarded that body and always showed a generic
  "status write failed" toast.
- All three sites now show the server's exact `detail` text when present.
  A missing/non-JSON body or a network error (no response to read) still
  falls back to the generic message; nothing renders as `undefined` or
  `[object Object]`.

**Migration:** install the complete 3.9.2 payload. No configuration or schema
migration is required.

## 3.9.1 (2026-08-29)

### Release-suite timeout tracks measured healthy runtime (SPEC-279-001)

- The canonical-suite release guard remains finite and fail-closed, but now
  allows 600 seconds instead of 300 seconds. The exact declared suite measured
  305.25 seconds wall time at 3.9.0, so the former threshold rejected healthy
  work before any fleet write.
- Timeout failures retain the `canonical_preflight` classification, attempted
  command and configured duration, zero completed suite runs, and the existing
  no-write guarantee.

**Migration:** install the complete 3.9.1 payload. No configuration or schema
migration is required.

## 3.9.0 (2026-08-29)

### Durable pre-fix red-proof artifacts (SPEC-279)

- A red run can now commit a structured artifact binding its baseline revision,
  exact test-file SHA-256, and exact failing pytest node IDs.
- Later post-fix integration records a mechanical reassertion without reverting
  code. A byte-identical test is explicitly inherited evidence; a missing or
  changed test reports `not_re_derivable` with a machine-readable reason.
- SPEC-239 is the first backfill: baseline `1bd395c`, the independently matched
  `51293f5f…` test content, and its observed seven-test failure set.

**Migration:** install the complete 3.9.0 payload. Existing projects need no
configuration migration; new red-proof evidence is committed under each
project's `.nightshift/red-proofs/` directory.

## 3.8.7 (2026-08-28)

### Canonical suite command is repository-root-relative (SPEC-243-001-001)

- The dependency-complete `commands.test` declaration now selects
  `canonical/tests` when executed verbatim from the repository root used by
  preflight and standalone verifier dispatch.
- Live subprocess regressions cover both root preflight and an automatically
  derived verifier command in its sanitized standalone repository.

**Migration:** install the complete 3.8.7 payload. Projects with their own
`.nightshift/config.yaml` keep their project-owned command unchanged.

## 3.8.6 (2026-08-28)

### Teardown tolerates an already-exited process group (SPEC-273)

- `extension_runtime.ExtensionSupervisor._terminate_group` no longer treats a
  `PermissionError` from `os.killpg` as fatal when this same `Popen` handle has
  already observed the child as reaped (`proc.poll() is not None`). Under
  machine load, `killpg` against a pid/pgid the kernel has recycled to an
  unrelated process returns `EPERM` rather than the expected `ESRCH`; that is
  the kernel's real response to pid reuse, not an anomaly, and teardown must
  not raise on it.
- A `PermissionError` against a group this handle still considers live
  (`proc.poll()` is `None`) is a genuine permission failure and still
  propagates — the tolerance is not a blanket except-and-pass, and a live
  group is still terminated with no surviving descendants.
- Root cause of `test_ac7_hostile_consumer_matrix_does_not_delay_independent_work`
  and `test_ac3_official_cli_end_to_end_five_checkpoints[kickoff]` intermittently
  failing on unrelated teardown noise, filed by the SPEC-252 kickoff run.

**Migration:** install the complete 3.8.6 payload. No configuration or schema
migration is required.

## 3.8.5 (2026-08-28)

### Historical release manifests are retained for sealed handoffs (SPEC-257)

- Each new manifest retains the exact preceding release manifest and carries
  older retained evidence forward, keyed by kit version and fingerprint.
- Handoff path membership is resolved against that exact historical surface.
  Versions released before retention are listed explicitly with a reason; they
  never fall back silently to the current managed-path set.
- The six-ID retired skill-path enumeration is removed. Historical records now
  pass through release evidence, while a path absent from its retained manifest
  remains an unmanaged-path failure.

**Migration:** install the complete 3.8.5 payload. No configuration or schema
migration is required.

## 3.8.4 (2026-08-28)

### Acceptance-criterion reasons must survive verifier containment (SPEC-274)

- When an acceptance criterion requires a decision or reason to be recorded,
  its authoritative record must now live in verifier-readable committed content,
  such as the spec body, `CHANGELOG.md`, or another tracked artifact. A same-spec
  run report may summarize the outcome but cannot satisfy the criterion alone.
- Spec authors must not make a working-tree-only condition the subject of an
  acceptance criterion. `prepare-dispatch` constructs its sanitized surface from
  the baseline and candidate commits, so untracked files and uncommitted actions
  are absent by construction. Such work belongs under a recorded-resolution
  clause whose decision and reason are committed.
- The guidance codifies the verifier-observability lesson from SPEC-252's
  amended AC4 and AC5. It does not change report exclusion or any other
  `verification_report.py` behavior.

**Migration:** install the complete 3.8.4 payload. No configuration or schema
migration is required.

## 3.8.3 (2026-08-28)

### Python bytecode cache is ignored across payload integration (SPEC-280)

- `__pycache__/`, `.pyc`, and `.pyo` are derived interpreter state. Manifest
  construction, whole-kit installation, extension packaging, installed-package
  inventory, scanner classification, and terminal managed-payload integrity now
  exclude them consistently. Native extension modules such as `.pyd` remain
  ordinary payload files.
- Bootstrap copying is exclusion-aware and the installed `.gitignore` carries
  the same policy, so cache already present in a canonical checkout cannot enter
  a new install.
- This supersedes SPEC-242's bytecode-escalation decision. Managed source bytes,
  executable modes, symlinks, hardlinks, and non-cache aliases remain protected;
  only machine-specific bytecode cache is outside the integration inventory.

**Migration:** install the complete 3.8.3 payload. Existing cache may remain on
disk; it is ignored and is never staged, copied, or treated as release evidence.
No project configuration migration is required.

## 3.8.2 (2026-08-28)

### Deployed board starts keep the managed payload byte-stable (SPEC-242)

- Policy (b) is authoritative: deployed `board.sh` exports
  `PYTHONDONTWRITEBYTECODE=1` for its own process tree, so a normal board start
  creates no `__pycache__` directory or `.pyc` file under the install root and
  leaves every applied managed-payload byte unchanged. The export is deliberately
  scoped to the deployed launcher; it does not suppress bytecode in the canonical
  checkout or for unrelated Python processes. The accepted cost is a small
  per-start import penalty.
- Generated bytecode remains unclaimed install content in both `scanner` and
  `managed_payload_provenance`; it receives no mutable project-owned exemption.
- Rejected alternative (a), declaring generated bytecode as project-owned install
  state in both classifiers, would introduce a new project-owned category that two
  independent classifiers must agree on indefinitely. Policy (b) removes the
  classification question instead of answering it and gives release verification
  the stronger direct byte-stability invariant.

**Migration:** install the complete 3.8.2 payload. No project configuration
migration is required.

## 3.8.1 (2026-08-28)

### Module-relative data resources ship with their managed readers (SPEC-240)

- `vocabulary-registry.yaml` now ships beside `vocabulary.py`, restoring the
  deployed `/api/vocabulary` endpoint and non-empty board field help.
- Release validation now rejects non-Python resources opened relative to a
  manifest-managed module when the resource is missing from the managed set.
  The general closure check also identified and now ships `metric-ranges.yaml`
  beside `metrics_fidelity.py`.
- The deployed-board containment proof pins the missing-resource bucket to
  empty and exercises the live vocabulary response from an applied release.

**Migration:** install the complete 3.8.1 kit payload; the two new data files
must move atomically with their managed readers.

## 3.8.0 (2026-08-27)

### Same-spec reports are excluded from the verifier dispatch surface (SPEC-239)

- The verifier surface now withholds every tracked report whose path or content
  names the spec under verification, regardless of whether the candidate changed
  the file. Sibling reports from earlier rounds of the same spec were unchanged
  across both arms, therefore byte-identical, therefore retained and readable.
- Retention survives for reports belonging to other specs, so canonical tests
  that consume unrelated report fixtures keep working inside a prepared surface.
- Containment evidence gained `explicit_report_paths`, `same_spec_id`, and
  `same_spec_excluded_paths` (path to `path`/`content` rule), and its
  `schema_version` moved to `1.1.0`. The three withholding rules are recorded as
  disjoint sets so a reader can tell which one took which path.
- `prepare-dispatch` and `prepare-surface` now require `--spec-id`, recompute the
  same-spec scope independently before emitting a plan, and exit non-zero with
  `verifier_surface_unavailable` when that scope cannot be resolved. Same-spec
  resolution runs before the destination repository is created, so a failure
  leaves no surface behind.
- The Step 5c verifier briefs no longer assert blanket absence of report
  artifacts; they state the guarantee the mechanism delivers and still require
  incidental observations to be recorded in `contamination`.

**Migration:** install the complete 3.8.0 kit payload. Any caller of
`verification_report.py prepare-surface` or `prepare_verifier_surface()` must
pass the spec identifier; there is no permissive default, because a missing
identity cannot scope the exclusion.

## 3.7.0 (2026-08-27)

### Orphaned and untracked release-handoff artifacts are now findings (SPEC-252)

- Handoff validation was driven only from the spec side, so an artifact that no
  spec declared was reachable by nothing: never validated, never completed, and
  never reported. `release_handoff.sweep_handoff_directory` now walks the
  directory itself and reports each finding against the artifact's own path,
  since an orphan has no spec ID to be attributed to. Zero declaring specs and
  more than one are distinct diagnostics.
- Every artifact must also be tracked in git. Tracking is judged only where the
  question is meaningful: outside a repository, or under a git-ignored path such
  as a private install's kit directory, the assertion is skipped rather than
  reported against every artifact.
- **R4, first instance:** `release-handoffs/SPEC-213.json` was orphaned because
  SPEC-213 declared no `release_handoff:`. The spec now declares
  `impact: required`, matching what its artifact asserts; the rationale is
  recorded in that spec's body. Retiring the artifact instead would be disposing
  of stranded backlog, which belongs to SPEC-251.
- **R4, second instance:** `release-handoffs/SPEC-201.json` was present in the
  working tree and untracked in git — so a checkout and the working tree counted
  different corpora, which is what made SPEC-244's AC1 arithmetic ambiguous
  (34/22/12 versus 33/22/11). It has been **removed**, not tracked. SPEC-201 is
  `superseded` (main commit 5119e40, after SPEC-200 returned `not established`),
  and the artifact was a `pending` promise at target 3.3.0 against kit 3.7.0 —
  stranded on arrival for work that will never ship. Tracking it would have
  committed a permanently undeliverable record into the backlog SPEC-251 must
  dispose of; it was never committed, so nothing in history is lost. Because the
  file was untracked, no branch commit can show its deletion: it was removed
  from the main working tree by the SPEC-252 kickoff parent during integration,
  with a byte copy and the full reason preserved outside the kit at
  `.nightshift/local-preserved/SPEC-252-R4/`.

### Implementer-blocked diagnosis and bounded delivery recovery (SPEC-235-001)

- Implementer `blocked`, failed, refused, stalled, and unavailable attempt
  outcomes now open a parent-owned diagnosis obligation instead of terminating
  delivery directly.
- A closed, privacy-bounded blocker envelope inventories the retained candidate,
  full AC partition, changed-file hashes, controlled facts, prior probes, and
  original authority before another actor may receive it.
- Deterministic seven-class assessment may spend one read-only diagnostician for
  safe uncertainty and one mutually exclusive original-or-specialist repair.
  Replays bind source, assessment, candidate revision, route, and ordinal.
- Repaired revisions rejoin the existing newly independent verifier,
  coordinator-owned serial integration, and fresh-main validation path. Portable
  outcome records expose preservation, assessment, route, allowance, confidence,
  operator-action, and delivery-phase fields.

**Migration:** install the complete 3.7.0 kit payload. Existing serialized
SPEC-235 states without SPEC-235-001 fields remain readable with zeroed recovery
allowances; reconnecting an active run does not create or renew an allowance.

## 3.6.7 (2026-08-27)

### Fresh terminal integrity and shared-drift containment (SPEC-232)

- Terminal managed-payload receipts now reject stale, future-dated, cross-run,
  and cross-manifest reuse before any result authority action.
- Inline/instruction and coordinator paths propagate the admitted run binding;
  worker-local drift holds descendants while independent work remains eligible.
- A shared control-plane integrity failure is retained once per run, stops later
  dispatch and integration, and preserves already-running workers and evidence.
- Runtime closure validation derives entrypoints, imports, shell launchers, and
  declared dynamic resources from production sources and the release manifest.

**Migration:** install the complete 3.6.7 kit payload. Receipts created by an
earlier run or outside the bounded freshness window cannot authorize result
acceptance and must not be replaced with a second admission after work.

## 3.6.6 (2026-08-26)

### Verifier/remediation identity interoperability (SPEC-235-002)

- Standalone verifier dispatch now emits a versioned synthetic Git head and a
  distinct SHA-256 implementation binding derived from private candidate and
  containment evidence.
- Parent remediation admission validates both identities without rewriting the
  independent verdict; fresh remediation surfaces persist a new pair before the
  one fresh-verifier request.
- Legacy failure verdicts without the new digest fail closed with the controlled
  `legacy_verdict_identity` migration reason. Ordinary pass auditing remains
  compatible.

**Migration:** install the complete 3.6.6 kit payload. In-flight legacy failure
verdicts must be independently re-dispatched under identity schema 1.0.0 before
they can enter remediation.

## 3.6.5 (2026-08-26)

### Complete installation admission coverage (SPEC-229-001)

- The coordinator now invokes the common installation admission gate before
  Git, spec-readiness, lifecycle, command, or dispatch work.
- Instruction-packet generation invokes the same gate for the resolved install
  and emits no packet when admission is denied or indeterminate.
- The supported-start inventory now covers both paths and has regression tests
  for missing future inventory entries.

**Migration:** none. Install the complete 3.6.5 kit payload; partial file-level
updates are not supported.

## 3.6.4 (2026-08-26)

### Atomic package lifecycle state (SPEC-231)

- Install and update now restore the prior package tree when the authoritative
  ledger write fails, preventing orphaned activated bytes.
- Removal first moves the owned tree outside the discovery root and restores it
  if the ledger write fails, so every failure leaves one ledger-matching state.
- Remove dry-runs now enumerate every owned relative file, revoked event and
  capability, and the ordered mutation actions before apply.

**Migration:** none. Install the complete 3.6.4 kit payload. Existing package
ledgers and installed package layouts remain compatible.

## 3.6.3 (2026-08-26)

### Independent private experiment streams (SPEC-238)

- Experiment event sequence-conflict checks are now scoped by experiment ID,
  allowing multiple preregistered experiments in one enrolled project to each
  begin at sequence one without weakening within-stream fork detection.
- Added a regression test proving equal sequence numbers are accepted across
  distinct experiments and rejected within the same experiment.

**Migration:** none. Install the complete 3.6.3 kit payload. Existing event
streams and quarantine records remain immutable.

## 3.6.2 (2026-08-26)

### Stable private reenrollment (SPEC-238)

- Reenrolling a known checkout after its Git head advances now reuses and
  verifies the first immutable origin observation instead of attempting a
  divergent rewrite and quarantining normal repository progress.
- Added a live-regression test that advances a repository, reenrolls it, and
  proves project identity, checkout identity, origin bytes, and quarantine
  state remain stable.

**Migration:** none. Install the complete 3.6.2 kit payload. Existing origin
records remain authoritative and are not rewritten.

## 3.6.1 (2026-08-26)

### Private-sink outage continuity (SPEC-238)

- Experiment observers now retain the last verified event-chain head while an
  enrolled private sink is unavailable, seal subsequent events to the private
  outbox, and reconcile them without resetting sequence or chain history.
- Event append validates the enrolled sink before creating a stream lock, so a
  missing transport root cannot be mistaken for a valid empty evidence store.

**Migration:** none. Install the complete 3.6.1 kit payload; already retained
3.6.0 experiment events and results remain valid and unchanged.

## 3.6.0 (2026-08-26)

### Evidence-backed real-use experiments (SPEC-238 / SPEC-238-001)

- Added revision-bound tracked experiment descriptors, closed private domain
  events, immutable hash-chained capture, sealed results, deterministic analysis,
  and rebuildable running-experiment projections.
- Source specs can explicitly delegate only post-delivery Live Execution
  hypotheses to completed instrumentation; delivery correctness, safety, privacy,
  compatibility, NFR, and release proof remain non-delegable.
- Added denominator-aware experiment metrics, fleet and board visibility, and
  idempotent unsupported-result routing through the existing follow-up authority.
- Registered `EXP-SPEC-231-01` and instrumented reusable-package lifecycle
  boundaries without expanding SPEC-230's five-event public protocol.

**Migration:** no automatic enrollment or collection. Projects that opt in retain
private evidence outside Git and may delete/rebuild the sanitized WIP projection.

## 3.5.0 (2026-08-26)

### Reusable extension packages and scoped installation (SPEC-231)

- Added deterministic, data-only `.nsext` packaging with a closed manifest,
  complete digest inventory, schemas, documentation, tests, license, and provenance.
- Added explicit project/user install, verify, update, rollback, remove, approval,
  ledger, atomic staging, and sanitized discovery/status operations.
- Capability-expanding updates now disable prior project approvals until the new
  exact version is explicitly re-approved; catalogues remain informational only.
- Canonical tests use local fixtures and the managed release contains packaging
  machinery without any production extension package.

**Migration:** install the complete 3.5.0 kit payload. Existing observational
extensions continue to work. Reusable packages are not installed or enabled
automatically.

## 3.4.0 (2026-08-25)

### Controlled verifier-remediation feedback (SPEC-235)

- A current, uncontaminated independent failing verdict can now enter one
  parent-owned, signed, size/privacy-bounded remediation packet.
- One mutually exclusive resume-or-fresh remediation attempt must produce a new
  head and pass a newly independent verifier before serial integration.
- Invalid verdicts receive one replacement verifier, while replay, contradictory
  delivery, exhausted budgets, and pre-verifier implementer blocks fail closed
  through controlled terminal policy.
- The durable reducer exposes a source-tagged recovery-admission seam for the
  later SPEC-235-001 implementer-blocked diagnosis without implementing it here.

**Migration:** install the complete 3.4.0 kit payload. No project configuration
migration is required.

## 3.3.3 (2026-08-25)

### Installation-admission adversarial hardening (SPEC-229-005)

- One combined privacy fixture now proves that absolute-path, Git-remote,
  command, URL, environment, and subprocess-output canaries remain absent from
  both console and JSON evidence.
- Artifact creation now rejects traversal identifiers, symlinked output paths,
  concurrent writers, interrupted/full writes, and hostile spec identifiers as
  indeterminate instead of leaving a partial success signal.
- Root and effective hook paths are bound to one coherent Git worktree, with
  linked-worktree positives and foreign, nested, and escaped negatives.

**Migration:** install the complete 3.3.3 kit payload. No project configuration
migration is required.

## 3.3.2 (2026-08-25)

### Complete installation-admission contract coverage (SPEC-229-004)

- Configuration admission now evaluates every documented severity row, including
  domain-specific optional commands, selected-stack capabilities, safe defaults,
  private-local paths, and controlled unknown I/O outcomes.
- Managed payload validation assigns corrupt fingerprints to `KIT.MARKER` while
  unsafe or empty file manifests remain exact `KIT.PAYLOAD` failures.
- Coverage accounting denies zero or incomplete applicability, and supported
  retained-prior releases are distinguished from divergent or unsupported ones.

**Migration:** install the complete 3.3.2 kit payload. No project configuration
migration is required.

## 3.3.1 (2026-08-25)

### Live installed managed-payload hook proof (SPEC-229-002)

- A real temporary repository now exercises the released pre-commit hook through
  ordinary `git commit` processes, proving both managed-payload rejection and
  project-owned application/config/spec/knowledge/evidence/board-state commits.
- Rejection guidance names the installed path, its canonical-relative
  destination, and the required whole-kit release route.
- Installed admission fixtures now deny removed, shadowed, and early-success
  hook wiring specifically through `INT.HOOKS`.

**Migration:** install the complete 3.3.1 kit payload. No project configuration
migration is required.

## 3.3.0 (2026-08-24)

### Executable follow-up lineage processing (SPEC-236)

- The managed follow-up processor now records terminal follow-up decisions through
  one source-aware executable boundary, with replay-safe zero observations and
  sealed child backlinks.

**Migration:** install the complete 3.3.0 kit payload; the SPEC-236 handoff
remains pending until the whole-kit release succeeds.

## 3.1.9 (2026-08-23)

### Follow-up lineage and incidence metrics (SPEC-236)

- Structured follow-up decisions now carry source-aware, immutable lineage with
  a closed cause/detail taxonomy, explicit zero-suggestion observations and
  byte-idempotent operation keys.
- Canonical aggregation distinguishes unique eligible sources from child specs,
  exposes nullable denominator-aware rates, and offers an allowlisted public
  projection that excludes prose and project identity.
- Created child specs can validate their exact source and lineage backlink;
  ordinary and historical specs remain free of synthetic parentage.

**Migration:** install the full 3.1.9 payload. Existing historical records may
be backfilled only from explicit structured evidence; no spec or Git history is
rewritten.

## 3.1.8 (2026-08-23)

### History-verified protocol archives (SPEC-217)

- The escalation scanner excludes a `.argo/protocol-archive/` snapshot only
  when its complete staged blob is reachable from repository history.
- One-byte mutations and authored additions remain fully counted, while secret
  and PII checks remain unchanged.

**Migration:** install the released scanner payload; no configuration migration
is required.

## 3.1.7 (2026-08-23)

### Verified kickoff watchdog cleanup (SPEC-226)

- Kickoff parents now record the watchdog task ID, stop that exact task, and
  report one explicit cleanup outcome (`checked-clean`, `check-failed`, or
  `check-not-run`) for every terminal path.
- A managed helper and regression contract cover clean, leaked, unavailable,
  and blocked-resolution cases; a lingering watchdog is visible evidence rather
  than an inferred successful stop.

**Migration:** install the released `ORCHESTRATOR.md` and watchdog-cleanup
payload. No project configuration migration is required.

---

## 3.1.6 (2026-08-23)

### Heartbeat-only liveness (SPEC-225)

- Watchers and kickoff parents now use the active-run heartbeat as the sole
  liveness signal. File mtimes, branch-tip movement, and commit counts are not
  stall evidence; long read-only work declares its phase and duration, and
  correct zero-commit work declares `no_commit_expected: true`.
- The shared Codex Nightshift skill records the same harness-agnostic contract.

**Migration:** install the released `LOOP.md`, `ORCHESTRATOR.md`, and
`WATCHER.md` managed payload. No project configuration migration is required.

## 3.1.5 (2026-08-22)

### Managed payload PII scan (SPEC-213)

- The staged-diff scanner derives canonical managed paths from the release
  provenance manifest and skips PII findings for those paths only; secret
  findings remain blocking.
- Scan output now reports the number of managed files skipped, while
  project-owned files continue through the existing PII gate.

**Migration:** install the released scanner and managed-provenance payload; no
project configuration changes are required.

## 3.1.4 (2026-08-22)

### Portable pre-commit command parsing (SPEC-212)

- The pre-commit hook now reads configured lint and type-check commands through
  PyYAML, so quoted values and trailing YAML comments work consistently on macOS
  and other supported shells.
- Invalid command configuration fails closed with a readable hook error before
  any configured command is evaluated.

**Migration:** install the released pre-commit hook payload; no project config
changes are required.

## 3.1.3 (2026-08-22)

### Project-configured terminal outcome records (SPEC-224)

- Projects can opt into a generic JSON-array or JSONL terminal-outcome adapter.
  The released commit-message hook requires a changed matching record for every
  terminal lifecycle commit and recognizes both insertion and in-place edits.
- Preflight reports a configured but unwired outcome boundary as an installation
  health failure. The contract normalizes fleet-safe fields without requiring an
  Argo-specific ledger; Argo maps its existing `agent-outcomes.json` fields.

**Migration:** add `terminal_outcomes` to the project configuration, then install
the released `commit-msg` hook and `terminal_outcomes.py` payload. `--no-verify`
remains an explicit Git-level bypass outside hook enforcement.

## 3.1.2 (2026-08-22)

### Terminal lifecycle evidence enforcement (SPEC-221)

- `hooks/commit-msg` now rejects terminal `done` and `blocked` lifecycle
  commits whose required evidence, blocker, recovery, parent-call, or resolution
  trailers are absent or empty, regardless of whether a parent or worker authored
  the message.
- The managed release payload now includes the commit-message hook and its
  regression tests, so releases deliver the enforcement mechanism and proof
  together.

**Migration:** none; install the released `hooks/commit-msg` through the normal
canonical release flow.

## 3.1.1 (2026-08-22)

### Verifier gate hardening (SPEC-222)

- The managed verifier payload now owns one exact generated-file footprint
  exclusion (`graphify-out/graph.html`) and tests that no broader path is
  ignored.
- Verifier footprint snapshots are explicitly worktree-local, so unrelated
  parent-checkout dirtiness cannot invalidate a clean verifier run.
- Acceptance-criteria coverage is extracted from the current spec's
  `## Acceptance Criteria` section only, preventing cross-spec prose mentions
  from becoming phantom coverage requirements.

**Migration:** none.

## 3.1.0 (2026-08-10)

### Live fleet feedback and evidence quality (SPEC-208)

- The bounded fleet collector now consumes the live portable projects registry,
  preserves duplicate display names as distinct resources, discovers only the
  project-root metric store, and reads current release-marker provenance.
- New canonical metrics use schema version 2 with controlled outcomes and a
  controlled failure category for blocked terminal rows. Historical version-1
  rows remain valid and explicitly expose unknown or unclassified evidence.
- Fleet analysis and the safe knowledge handoff expose denominator-backed
  unknown-outcome and blocked-classification rates for later Evolve verification.
- Nightshift and Evolve instructions now resolve the canonical kit from its
  relocated Developer/ManagedProjects source.

**Migration:** none. Config schema remains 3.0.0; historical metrics remain
readable, while newly emitted blocked metrics require a controlled category.

## 3.0.1 (2026-08-09)

### Bounded release gate

- Board browser tests now use DOM readiness plus explicit UI assertions instead
  of `networkidle`, which is incompatible with the board's background polling.
- Browser operations have a ten-second default timeout, and the coordinator
  caps each canonical-suite subprocess at five minutes. A timeout is now an
  auditable preflight failure, never an indefinitely blocked release.

**Migration:** none.

## 3.0.0 (2026-08-09)

### ManagedProjects relocation

- Adds `argo_home.py` to the managed release payload. It is a local dependency
  of `reflexion_producer.py`; shipping the consumer without the resolver made
  fresh installs fail after the ManagedProjects relocation.
- Managed projects now live under `~/Dropbox/Developer/ManagedProjects`, not
  under Argo Home. The major version makes that topology boundary explicit.

**Migration:** no config-schema migration. Existing project configuration is
already schema 3.0.0; the canonical payload updates the runtime path resolver.

## 2.67.3 (2026-08-09)

### Canonical copy, then project config migration (SPEC-190-001-001)

- Release now treats the exact manifest and marker as canonical-owned payload
  that is replaced deterministically. Historical provenance of an old kit copy
  is diagnostic evidence, not an admission gate.
- Project configuration remains project-owned. When a schema migration is
  required, its isolated result is validated separately and applied only after
  that install's canonical payload copy succeeds.
- This removes the rule that stranded the 2.67.2 fleet rollout while retaining
  staged-path, ownership-boundary, smoke, verification, commit, opt-out, and
  no-push guards.

**Migration:** none. The ordinary release command now performs the canonical
payload replacement without `--adopt-unresolved-managed`.

## 2.67.2 (2026-08-09)

### Explicit legacy managed-payload adoption (SPEC-190-001-001)

- The release coordinator has an operator-authorized adoption mode for legacy
  file-only-sync payloads whose per-file provenance was never retained.
- The override remains bounded to the exact manifest payload and release
  marker. Project config, specs, generated metrics, knowledge, application
  code, unrelated staged paths, opt-out policy, and pushes remain protected.

**Migration:** none. Use `--adopt-unresolved-managed` only after an operator
explicitly authorizes replacement of unresolved canonical managed files.

## 2.67.1 (2026-08-09)

### Pre-copy release ownership and deterministic recovery (SPEC-207)

- Fleet release now proves copy, marker, migration, staging, and commit
  ownership before the first project write. The canonical
  `metrics/_SCHEMA.md` is managed while generated project metrics remain
  excluded.
- Canonical-suite metadata declares a dependency-capable `uv` environment and
  import probe; the probe and suite run through the same environment.
- Partial applies have a read-only exact-current / retained-prior / unresolved
  classifier, and controller unblock paths resolve relative specs against the
  explicit project root.

**Migration:** none. Existing installations update through the guarded whole-kit
release; preserved partial applies require an evidence-backed disposition first.

## 2.67.0 (2026-08-09)

### Measured phase duration observability (SPEC-196)

- Canonical runs can emit controlled phase boundaries keyed by stable run ID;
  metrics derives duration mechanically and distinguishes measured, skipped,
  interrupted, and unavailable work.
- Analytics excludes unavailable legacy zero rows from bottleneck rankings and
  includes median, p90, and share for measured phase samples.

**Migration:** none. Existing zero-duration rows remain valid and are labelled
unavailable by analytics.

## 2.66.0 (2026-08-08)

### Exact historical-checkbox disposition evidence (SPEC-204)

- `validate_specs.py` retains the normal error for every unchecked Requirement
  or Acceptance Criterion on a `done` spec, unless the project owns an exact
  ordered inventory matching filename, line, section, and checkbox text.
- Only `intentional_historical_record` and `unresolved_evidence_gap` are
  recognized. Exact matches remain visible warnings and never become checked
  items or implementation claims; missing, malformed, partial, stale, reordered,
  or unknown evidence fails closed to the original errors.
- The inventory is explicitly project-owned and absent from the managed release
  set. Canonical ships only the generic validator and schema documentation.
- The existing versioned release-handoff gate remains in the same terminal
  validation path and is independently enforced when an inventory is present.

**Migration:** none. Projects that intentionally retain historical unchecked
contract items may create the documented inventory only after explicit review;
Nightshift does not generate or rebaseline it.

## 2.65.0 (2026-08-08)

### Managed-install provenance and direct-edit guard (SPEC-203)

- Installed commit gates reject staged changes to manifest-managed Nightshift
  payloads unless the bytes exactly match the release being staged. Application
  code, project configuration, specs, run evidence, and declared migration outputs
  remain outside this gate.
- Release markers retain the complete fingerprint-bound per-file manifest. The
  read-only audit distinguishes an exact current copy, a proven prior release copy,
  and unresolved divergence without using timestamps, similarity, or aggregate
  fingerprints as per-file evidence.
- Doctor and release preflight surface the same classifications, preserve every
  dirty file and index entry, and refuse synchronized-release claims when required
  metadata is missing or corrupt.

**Migration:** none. A clean guarded release writes retained per-file evidence. An
older install with dirty managed files remains a safe skip until those files are
reviewed; the coordinator never overwrites them to manufacture provenance.

## 2.64.4 (2026-08-08)

### Scanner: the detector's own fixtures can be committed (SPEC-197)

**Closes the known limitation recorded under 2.64.0.** A secret/PII detector's test suite
must contain secret-shaped and PII-shaped inputs or it tests nothing, and the scanner scans
every added line of every staged file — including its own tests. Three of the four commits
that have ever touched `tests/test_scanner.py` could not have landed without `--no-verify`,
which skips not just the finding but the whole pre-commit hook: the secret scan, spec
validation, lint, type check, the canonical copy-drift guard and the `[SPEC-ID]` check.

- A finding is now excluded **only when both** conditions hold: the location matches a
  kit-owned fixture path anchor, **and** the digest of the exact matched value is in the
  kit's fixture registry. Either alone excludes nothing.
- **This is not a path allowlist.** A live credential dropped into a file at the anchor path
  still blocks, because its digest is not registered. And a registered fixture value copied
  into `scanner.py`, a spec, this changelog or a commit message still blocks, because none
  of those is a fixture path — which makes the SPEC-183 convention a mechanism rather than a
  request.
- **Digests, never values.** A registry of literal fixture strings would itself trip the
  gate it exists to satisfy.
- **Not project-configurable, by design.** No `git:` key, no environment variable, no CLI
  flag. The anchors are a closed list in `scanner.py`; the registry lives at
  `tests/fixture_digests.txt`, which `nightshift-sync.py` never delivers to a project
  install. An install therefore finds no registry and excludes nothing — the mechanism is
  inert outside canonical, and a project cannot widen its own gate by editing a vendored
  file. A missing registry is normal and is not an error.
- **Excluded, not silenced.** Every excluded finding is still printed on each run, marked
  `[kit fixture]`, with its location and class. `ScanReport` exposes them as `excluded`,
  separately from `findings`.
- **Fails closed.** A malformed digest, or an over-broad anchor (a bare directory, a glob,
  an absolute path, one containing `..`, or one naming a source file, spec or config), is
  discarded and reported, and every finding it would have covered still blocks.
- SPEC-192 acknowledgements are unchanged and independent: the expiring mechanism still
  covers one reviewed **real** PII value anywhere, and the non-expiring one covers only
  synthetic kit fixtures at kit paths.

**Migration:** none required. No config schema change.

⚠️ **Non-synced hand-copy:** `Cortex/core/nightshift_scanner.py` was refreshed in the same
commit, as every `scanner.py` change must be.

## Unversioned — recorded 2026-08-08, shipped in a later release

> **Version-attribution note (SPEC-319, 2026-09-08):** this entry was written under
> an `Unreleased` heading while 2.64.3 was current and was never folded into a version
> heading; every later entry was inserted above it. SPEC-199 is `done` and its telemetry
> is present in `board.py` today (SPEC-303 measured against it), so it shipped — but the
> pre-relocation history that would pin the exact release is not in this repository, so
> no version claims it.

### Local board performance telemetry (SPEC-199)

- The local board exposes an on-demand, process-local aggregate performance
  summary. It keeps bounded timing samples for startup, cache work, supported
  routes, and browser paint-gated interactions; it neither exports telemetry
  nor retains request/spec content.
 - `board.sh` now records a board PID only after `/api/health` responds, making
   spawned and HTTP-ready distinct operator states.

## 2.64.3 (2026-08-08)

### Scanner: reserved documentation domains are not PII (SPEC-198)

- An email address whose domain is reserved for documentation no longer produces a finding.
  **RFC 2606 §2** reserves the `.test`, `.example`, `.invalid` and `.localhost` top-level
  domains; **RFC 2606 §3** reserves `example.com`, `example.net` and `example.org`; **RFC
  6761** restates them as special-use names that resolvers must refuse to resolve. No mail
  exchanger for one can exist, so an address there cannot receive mail and cannot identify a
  person. Subdomains are covered by the rule that covers their parent.
- **Recall is unchanged.** Every other domain still blocks, including lookalikes that merely
  contain a reserved label. `.local` (mDNS) and `.internal` (ICANN private-use) are
  deliberately *not* reserved here — a private network really does deliver mail to the
  latter — and both still block.
- Measured effect on the kit's own tree: findings fall from 51 across 11 files to 41 across
  6. Five test files whose only finding was a single `git config user.email` line are now
  clean, and `tests/test_scanner.py` drops from 24 findings to 21.
- Every fixture in `tests/test_scanner.py` whose job is to *be detected* moved to a
  non-reserved domain behind one constant, and an assertion pins that constant as
  non-reserved — so reserving it later fails the suite loudly instead of silently converting
  six recall tests into assertions that nothing was found.

**Migration:** none required. No config schema change; the reserved set is canonical-owned
and deliberately not project-configurable.

⚠️ **Non-synced hand-copy:** `Cortex/core/nightshift_scanner.py` was refreshed in the same
commit, as every `scanner.py` change must be.

## 2.64.2 (2026-08-08)

### Board tooltip safety during card drag (SPEC-195)

- Board card reorders now hide an existing spec tooltip at drag start and
  suppress pointer-driven tooltips until the drop or cancellation has completed.

## 2.64.1 (2026-08-08)

### Coordinator lifecycle authority (SPEC-191-001)

- Coordinator-backed lifecycle writes now persist a linked StatusStore checkpoint before
  tracked frontmatter, making failures explicit and recoverable rather than reporting a
  terminal status with stale runtime state.
- Control reconciles terminal frontmatter with the same durable status layer used by boards.
- `board.sh` preflights FastAPI dependencies and supports `NIGHTSHIFT_BOARD_PYTHON` for
  installed project runtimes before it records a PID.

## 2.64.0 (2026-08-08)

### Scanner: correct finding attribution + reviewed-PII acknowledgements (BUG-013, SPEC-192)

**Config schema addition** — new optional `git.pii_acknowledgements` list. Backward compatible:
projects without a `git:` section behave exactly as before (every finding blocks).

- **BUG-013 — findings were attributed to the wrong file and to lines that cannot exist.**
  Observed in Inwestomat: `email at DnaRynkow/.argo/README.md:127` for a 102-line file containing no
  `@`, and line 451 of that same file. The findings were REAL — six saved HTML articles embed an
  account address — but path and line were not. That is worse than a false positive: verifying a
  finding meant reconstructing the scanner's own search, and a reviewer who opens the named file sees
  nothing and learns to distrust the gate.
- **SPEC-192 — a reviewed PII finding can now be acknowledged** instead of forcing `--no-verify`,
  which also skips the secret scan, spec validation, lint and the spec-ID check. Acknowledgements are
  keyed by **SHA-256 of the value**, so acknowledging PII never writes PII into config; they require
  an **expiry (≤365 days)** and a reason; **secrets can never be acknowledged, only PII**; and
  acknowledged findings are still **printed** on every commit, marked `[acknowledged]`.
- Fixed a `home_address` false positive: a date followed by a capitalised newspaper name parsed as a
  street address. `123 Main Street` still blocks — recall preserved.

**Migration:** none required. To use acknowledgements, run
`python3 scanner.py --staged --config <cfg> --acknowledge-template` and paste the stanza under a
top-level `git:` key, filling `expires` and `reason` (an unedited stanza is invalid and keeps blocking).

⚠️ **Non-synced hand-copy:** `Cortex/core/nightshift_scanner.py` is a copy that
`Cortex/api/Dockerfile:58` builds into the production image and that `nightshift-sync.py` does not
know about. It was refreshed in the same commit; any future scanner change must do the same or Cortex
ingestion silently keeps the old version.

⚠️ **Known limitation at the time of this release — RESOLVED in 2.64.4 (SPEC-197).** A secret
detector's own test suite necessarily contains secret-shaped fixtures, and secrets cannot be
acknowledged by design — so `tests/test_scanner.py` could not pass its own gate and every commit to
it had used `--no-verify` (SPEC-183 included). SPEC-197 closed this with a fixture exclusion
requiring both a kit-owned path anchor and the digest of the matched value; see the 2.64.4 entry.

### Versioned canonical release handoffs (SPEC-189)

- Release-impact specs now carry a portable, machine-validated handoff binding
  changed managed paths, a target version, changelog, manifest fingerprint,
  migration plan, and fleet scope.
- A release-impact spec cannot reach `done` without a valid pending or completed
  handoff. Only the guarded release coordinator completes matching handoffs after
  a successful full-kit rollout; dirty and opted-out installs remain safe skips.

---

## 2.63.2 (2026-08-02)

### Bounded stopped-board refresh fanout (SPEC-182)

- Nightshift Control limits concurrent stopped-board summary subprocesses to four,
  preventing fleet-wide registry scans from exhausting the fixed per-board timeout.
- Project cards and dependency graphs remain available together after a Control restart
  across the full registered fleet.

## 2.63.1 (2026-08-02)

### Cross-project dependency consistency (SPEC-182)

- Boards, the DAG CLI, the parallel executor, and Nightshift Control now resolve
  exact dependency IDs from registered physical spec files, even when peer boards
  are stopped.
- Completed external prerequisites admit dependents; pending prerequisites wait;
  missing or duplicate IDs fail explicitly instead of becoming indefinite waits.
- Individual project graphs retain external prerequisite nodes and open their exact
  owning board/spec.

## 2.63.0 (2026-08-01)

### Visible spec ownership in Nightshift Control (SPEC-178, SPEC-179)

- Public project boards can keep Nightshift state private while retaining an
  explicit, auditable ownership record for each active spec.
- Nightshift Control overlays live session ownership on in-progress specs,
  distinguishing owned, unowned, unknown, and claim-conflict states.

## 2.62.0 (2026-08-01)

### Private-local Nightshift state (SPEC-181)

- Added explicit `nightshift_state.policy` selection. Existing and missing policy
  remain `commit-backed`; projects may opt into `private-local` without putting
  their Nightshift control plane in application Git history.
- Added coordinator-owned durable local lifecycle/run IDs, ignored allowlisted
  worktree projection and evidence return, and pre-launch/pre-merge privacy gates.
- Updated kickoff, loop, orchestrator, bootstrap, Git, sync, release, and migration
  guidance. Application branches, evidence gates, merges, and cleanup are unchanged.

## 2.61.0 (2026-08-01)

### Project-owned local worktree paths (SPEC-180)

- All generated worktree paths now resolve below a deterministic local temporary
  namespace keyed by repository path, never beside or inside a Dropbox project.
- Creation, integration, and cleanup verify both the managed namespace and Git
  common-directory ownership before acting on an existing worktree.
- Kickoff, orchestrator, Git, and primary-branch guidance use the same resolver;
  `worktree_paths.py` is part of the managed release surface.

## 2.60.1 (2026-08-01)

### Board lifecycle authority and contract-review metrics

- A terminal lifecycle decision on main (`blocked`, `done`, `superseded`, or
  `retired`) now remains in its canonical board column even when a retained
  worktree still reports `in_progress`.
- Lifecycle classification events can record bounded, prose-free R/AC contract
  friction telemetry and calibration metrics.

## 2.60.0 (2026-07-29)

### Completed release, lifecycle, and board reliability work

- Fleet release policy declarations now reconcile with compatible repository
  commit hooks before a guarded local rollout (SPEC-156-002).
- The board's copy actions work from both the standalone board and the
  Nightshift Control modal, with a supported browser fallback (SPEC-171,
  SPEC-171-001).
- Spec maturity, priority, and run-admission state are represented separately
  in lifecycle and board views (SPEC-162-001).
- `board.sh` backgrounds the board, reports its exact stop command, and can
  safely stop only its own recorded board process (SPEC-167).

---

## 2.59.0 (2026-07-29)

### Atomic versioned fleet release (SPEC-156)

Canonical kits now have deterministic, content-addressed release manifests.
Release apply copies the complete managed set, verifies it, and writes an exact
installed release marker last. Generated project registries are a separate
operation and are excluded from release diffs.

The `/nightshift release` coordinator now owns canonical preflight, bounded
per-install migration workers, repository-wide dirty-path isolation, exact
allowlisted local commits, declared smoke verification, stop-on-unexpected
semantics and structured fleet evidence. Nightshift Control can run a release
preflight and copy the coordinator prompt, but cannot apply directly.

## 2.58.0 (2026-07-28)

### Canonical sync safety batch (SPEC-151–154)

Canonical sync now excludes documentation templates from live-spec validation,
avoids treating documented structured run IDs as payment-card PII, registers the
canonical Nightshift project for cross-project `SPEC` dependencies, and blocks
propagation when the canonical kit version and changelog release metadata differ.

## 2.57.0 (2026-07-28)

### Compatible commit grammar and lifecycle metrics (SPEC-150)

Nightshift now accepts ordinary `[SPEC-ID] type: description` commits alongside
the parent lifecycle subjects that emit metrics: `chore: mark SPEC-ID done` and
`blocked`. The shared grammar supports hierarchical IDs with numeric final
components, and canonical sync deploys the hook, metrics parser, and supporting
protocol guidance together.

---

## 2.56.0 (2026-07-27)

### Control work summary and metric help (SPEC-144)

Nightshift Control now shows Draft, Blocked, Ready, and Active work counts for
every discovered project, plus an explicit `OPEN` or `CLEAR` state. The counts
are read-only, work when a project board is stopped, and use a short cache so
routine Control polling remains lightweight. The per-project board's RUNS,
MTTD, MTTR, CFR, FORMAT, and EASY-FIX indicators now include concise native
hover help.

---

## 2.55.0 (2026-07-25)

### Pending draft and ready work tiles (SPEC-142)

The Nightshift control board now shows compact Draft and Ready tiles in its
header. They derive from the same canonical spec-frontmatter payload as the
board, refresh with normal board refresh and polling, and explicitly render
zero when no work is waiting in either lifecycle state.

---

## 2.54.0 (2026-07-25)

### Static active-NFR reconciliation gate (SPEC-140)

Active NFR scope matching now has one canonical implementation shared by the
impact audit and validation gate. `ready`, `in_progress`, and `blocked` specs
must bind every mechanically matched active NFR (directly or through its parent)
or record an auditable `nfr_waivers: [{id, reason}]` decision; drafts warn while
done specs are not re-gated. `audit_nfr.py --check-all` provides the CI and
pre-promotion batch gate. The canonical authoring and orchestration guidance now
makes reconciliation agent-owned housekeeping rather than optional human review.

---

## 2.53.0 (2026-07-25)

### Parent-authoritative kickoff resolution metrics (SPEC-139-004-001)

Mark-commit metrics now link blocked and later-recovered transitions with the
canonical `in_progress` commit as a stable run ID. Parent lifecycle commits
capture all four evidence-gate results, blocker class and scope, unblock
attempts/limit, automatic-unblock success, deferred recovery, and measured
resolution latency through controlled Git trailers. Validation remains
backward-compatible for historical rows, while cross-run analysis reports
evidence-gate failure rate, automatic-unblock success rate, deferred-recovery
rate, blocker-class counts, and median final resolution latency.

## 2.52.0 (2026-07-25)

### Bounded parallel orchestration proof and operator guidance (SPEC-139-004)

Canonical Nightshift now includes a hermetic real-Git-repository proof covering
live frontier fan-out, descendant-only blocking, serialized green merges,
conflict holding, post-merge reversion, and retained unmerged work. The
orchestrator and Git guides add the operator checklist: worktrees isolate edits
but do not make specs compatible, and one coordinator exclusively owns lifecycle
and merge transitions. `config-reference.yaml` documents the bounded
`parallel_integration.max_repair_attempts` setting.

## 2.51.0 (2026-07-02)

### Emission-time vocabulary normalization (SPEC-130)

`record_metrics.py` now normalizes status and model vocabulary where rows are
born: status synonyms (`done`, `implemented`, `passed`, …) map to the
VOCABULARY.md canonical enum with the original preserved in `status_raw`;
out-of-vocab statuses pass through with a loud warning. Model spellings are
case-folded through an alias table (`GPT-5 Codex`/`codex-gpt-5`/`codex` →
`gpt-5-codex`) with `model_raw` preserved, and `?`/`unknown`/blank model values
fall through the trailer → config → `unknown` chain instead of winning it.
Historical rows are not rewritten. Driven by the 2026-07-02 cross-project
aggregation (14 status variants, ~39% unusable model attribution across 381
rows).

## 2.50.0 (2026-07-02)

### Canonical audit batch (SPEC-124..128)

- **SPEC-124 (bugfix):** kit test suite no longer reads fixtures from live
  install paths — Dashboard/hear-me-say metrics fixtures vendored into
  `tests/fixtures/`. Suite is green on any checkout.
- **SPEC-125 (bugfix):** `validate_metrics.py` type-guards all numeric
  comparisons (13 sites): null/list-typed fields yield validation errors
  instead of a TypeError that killed `analyze_metrics.py` on real corpora.
- **SPEC-126 (bugfix):** `worktree_janitor.py` resolves project-prefixed spec
  IDs (`FART-SCR-132-002`, `SPEC-CTX-MCP-008`) from branch names; previously
  only bare `SPEC-\d+` matched, making the janitor a no-op on real installs.
- **SPEC-127:** `nightshift-sync.py canonical` now writes `kit_version`
  through to each install's config.yaml (only that value; rest of the file
  untouched). Ends the perennial version-mismatch warning noise.
- **SPEC-128:** janitor gains `sweep_wip_heartbeats()` — removes
  `reports/_wip/orchestrator-progress-*.md` for done specs immediately and
  other resolved per-run `_wip` files past 30 days; wired into
  `run_startup_janitor`.

## 2.49.1 (2026-06-28)

### Board status write-through regression fix

Board-originated status changes now update both the durable status checkpoint
store and the spec file's `status:` frontmatter. This keeps board drag/API
changes aligned with `/nightshift kickoff`, which gates on the markdown file.

The board also reconciles newer spec-file frontmatter for non-terminal statuses,
not only terminal states, while preserving worktree-origin durable checkpoints
whose `spec_path` points at a different checkout.

## 2.49.0 (2026-06-26)

### Multi-axis code-generation rubric (SPEC-108)

`eval/codegen_rubric.py` scores generated code artifacts across test pass-rate,
execution time, SPEC-093 secret/PII scanner findings, and coupling/complexity.
It aggregates vectors per model, selects Pareto-best models without collapsing
the axes into one scalar, flags trivial or under-covered test sets using the
SPEC-097 coverage-targeted posture, and emits `routing_signal` /
`sft_target_signal` fields for SPEC-099 and SPEC-100 consumers.

## 2.48.0 (2026-06-26)

### Trajectory and path evaluation (SPEC-107)

`eval/trajectory.py` evaluates agent runs at final-response, single-step, and
trajectory granularity. Trajectory assertions are opt-in per eval spec and
support any-order, in-order, and exact-order tool-call matching, plus repeated
run averaging for noisy path variance.

## 2.47.0 (2026-06-25)

### Failure taxonomy and tool-call validity metrics (SPEC-106)

`eval/failure_taxonomy.py` classifies failed or low-quality regression traces
into named failure modes, builds row-normalized confusion matrices with the
diagonal zeroed, surfaces dominant asymmetric error pairs, computes tool-call
validity rates, and emits an evolve-friendly prioritized-fix payload.

### SFT decision procedure reference (SPEC-109)

`knowledge/tool-call-schema-validation-rubric.md` now includes the quantitative
SFT pre-run decision procedure: a token-budget gate, learning-curve read-out
rule, optional full-precision-only `weightwatcher` triage, and the
data-before-hyperparameters posture.

## 2.46.0 (2026-06-25)

### Loop observability metrics (SPEC-111)

`loop_observability.py` computes MTTD, MTTR, change failure rate, and
format-failure/easy-fix rates from the existing Nightshift execution history
database. The board exposes the metrics through `/api/loop-observability` and a
compact header strip, while `Skills/evolve/scripts/evolve-metrics.py` includes
the same block in summary JSON and as the named `loop_observability` metric.

---

## 2.45.0 (2026-06-25)

### Confidence calibration reliability diagram (SPEC-112)

`confidence_gate.py` now records labeled confidence/outcome pairs to an
append-only JSONL store, computes reliability-diagram bins and Expected
Calibration Error, renders the diagram as Markdown, and recommends a data-tuned
confidence floor when ECE shows miscalibration.

---

## 2.44.1 (2026-06-25)

### Board durable-status reconciliation (SPEC-120)

The board now reconciles stale durable status checkpoints when canonical spec
frontmatter has a newer terminal status. Active worktree transitions still use
the durable store, but a spec completed through frontmatter/metrics no longer
stays silently stuck in `in_progress`; the board appends a
`frontmatter-reconcile` checkpoint and displays the terminal status.

Canonical sync now also includes `trace_export.py`, which is imported by
`failure_persistence.py`.

---

## 2.44.0 (2026-06-25)

### Loop-level caching (SPEC-105)

`prompt_engine.py` now exposes stable-prefix prompt composition so loop calls
can keep system/primer/spec/DevKB context as a fixed literal prefix while
appending volatile per-step state. `llm_client.py` accepts structured prompts:
Anthropic requests put `cache_control` on the stable prefix block, while
OpenAI-compatible local calls send one literal prompt string for KV-prefix reuse.
`nightshift_coordinator.py` adds an exact full-input-hash cache for
deterministic sub-steps and explicitly bypasses gating tests and volatile state.

## 2.43.0 (2026-06-24)

### Offline replay-eval gate for `/evolve` protocol changes (SPEC-110)

`Skills/evolve/scripts/offline-replay-eval.py` replays candidate protocol
changes against SPEC-095 regression trace cases, scores baseline and candidate
outputs with SPEC-097 graded eval metrics, applies a bootstrap confidence
interval over per-trace deltas, checks declared neutral trace classes for
decision invariance, and logs promote/reject rationales before live protocol
promotion.

## 2.42.0 (2026-06-24)

### Graded eval metrics and calibrated judge pinning (SPEC-097)

`canonical/eval/` adds graded eval primitives over the SPEC-095 regression trace
corpus: pinned judge tuples with stable hashes, explicit local rubrics,
per-slice metric aggregation for production-distribution / known-failure /
out-of-scope cases, north-star correlation anti-overfit flags, bootstrap-CI
improvement gating with the 3x-to-10x sample-size rule, and coverage-targeted
edge-case synthesis for named weak slices.

## 2.41.0 (2026-06-24)

### Confidence-scored escalation gate (SPEC-098)

`confidence_gate.py` adds a pure decision-level escalation gate for agent
outputs. Callers can score discrete decisions from 3-5 diverse reruns using
majority-vote agreement, or use a native 0-1 logprob confidence without extra
rerun cost. The gate escalates material-consequence decisions when confidence is
below the configured floor or rerun variance exceeds the configured bound, while
low-stakes uncertain decisions auto-proceed.

## Documentation (2026-06-24)

### Argo stack threat model (SPEC-102)

`knowledge/argo-stack-threat-model-RAISE.md` captures a Nightshift-local threat
model over Argo's Cortex / Nightshift / Hippo / MCP / parallel-agent surfaces.
It uses Wilson's trust boundaries, RAISE, and excessive-agency taxonomy, and
states explicitly that MAESTRO is only the Albada alternative frame.

## 2.40.0 (2026-06-24)

### Tool-call schema validation + SFT decision rubric (SPEC-100)

`tool_call_validation.py` adds a local runtime guard that parses model-emitted
tool calls, validates arguments with Pydantic schemas before handler execution,
and rejects malformed calls such as `add(jeden, dwa)` or over-arity calls before
any tool side effect can run.

The new rubric in `knowledge/tool-call-schema-validation-rubric.md` documents
schema validation as the near-term deliverable, prompt/grammar tool exposure as
the default over per-tool SFT, and QLoRA adapter retraining as research-tier
work reserved for hot-path, stable tasks with collected weak cases.

## 2.39.0 (2026-06-24)

### Model routing by complexity (SPEC-099)

`model_selection.py` now exposes semantic model-tier routing primitives:
`RouteQuery` for structured classifier output, off-schema tier normalization,
nearest-centroid semantic routing over exemplar tasks, routed tool trimming,
and measured latency/throughput trust gates before a tier can be used.

## 2.38.0 (2026-06-24)

### Regression trace export to eval corpus (SPEC-095)

Failed runs can now export a replayable regression trace case into
`eval-specs/regression-traces/` when the failure event carries structured trace
context. The exported JSON case records the AIE log-everything field contract,
the failing-step label (`retrieval`, `processing`, or `generation`), the expected
output, and a minimal replay check so a captured failure can become a green
regression after the fix.

## 2.37.0 (2026-06-24)

### Actor-critic in-place revision loop (SPEC-096)

`critic.py` now defines structured critic inputs that preserve raw failing
test/lint/type/build output verbatim, including explicit role inversion when the
actor and critic are the same local model. `loop.py` adds a bounded
generate/reflect revision primitive that keeps the same actor in the same
worktree and escalates after the configured cap instead of re-dispatching or
looping indefinitely.

ORCHESTRATOR.md now states that failed post-merge validation output must be sent
back as raw critic input to the same worktree actor before revert/escalation.

## 2.36.0 (2026-06-24)

### Commit secret/PII + escalation gate (SPEC-093)

`scanner.py` is now an importable staged-diff scanner that returns structured
secret/PII findings and threshold-triggered escalation decisions. The
pre-commit hook calls it before spec validation, lint, and type checks, rejecting
staged secrets, valid PII, and over-bound diff/token cost unless explicit
Lukasz sign-off is supplied through the configured environment variable.

New git config fields: `diff_risk_threshold`, `token_cost_threshold`, and
`escalation_signoff_env`.

## 2.35.1 (2026-06-24)

### Board copy-run prompt avoids duplicated spec IDs

`COPY RUN PROMPT` now detects titles that already begin with the selected spec
ID, such as `SPEC-CTX-TOOLS-048 — Eliminate Reverse-Drift False Positives`, and
uses that title as the kickoff label instead of prefixing the ID again. Titles
without the ID keep the existing `/nightshift kickoff <SPEC-ID> <Title>` shape.

## 2.35.0 (2026-06-24)

### Durable spec-status checkpoint layer (SPEC-094)

Spec status can now be stored as append-only SQLite checkpoints keyed by stable
spec id. `status_store.py` exposes `get_state`, `update_state`, and
`get_state_history`; board reads overlay the latest durable checkpoint on top of
spec frontmatter while retaining frontmatter as fallback metadata. The live board
initializes the store from the repository's git common directory, so worktrees of
the same checkout share one status DB and a worktree-side status update becomes
visible to the main board before merge.

The board API adds `/api/spec/{spec_id}/status/history` for the audit ledger.
Existing file-backed `SpecCache` behavior remains available when no store is
configured, which keeps static/export and legacy tests compatible.

## 2.35.0 (2026-06-24)

### Board copy-run prompt includes the spec title

The board's `COPY RUN PROMPT` now includes the selected spec's title in the
kickoff command line (`/nightshift kickoff <SPEC-ID> <Title>`). This keeps
cross-project pasted prompts distinguishable when multiple projects reuse
the same spec ID. No config or protocol-step changes.

---

## 2.34.0 (2026-06-14)

### `run_validation.py`: mechanize Step 9 validation capture (SPEC-092 / R4 conversion)

The first conversion from SPEC-089's mechanization inventory (after metrics in SPEC-086).
`run_validation.py` runs the configured `commands.{build,test,lint,type_check}` (respecting
`test_timeout_s`, Null Command Policy) and writes `metrics/<spec-id>.validation.json`
(build_pass, tests_total/passed/failed, lint/type errors, per-command exit). The mark-done
metrics hook now **prefers** that file for authoritative test/lint/type/build numbers,
falling back to report-parsing when absent — additive, no behaviour change when missing.
LOOP.md Step 9 documents it as optional convenience (not hard-mandatory). +5 run_validation
tests, +1 mark-commit test (prefers validation.json).

**DOGFOODED:** ran `run_validation.py` on the canonical kit's own pytest → a real
`validation.json` (build_pass true, **17/17 tests**); the SPEC-092 mark-done row reads those
counts. This closes the last loose thread in the metrics arc — test counts are now
authoritative, not parsed from prose.

---

## 2.33.0 (2026-06-14)

### Unify telemetry: ingest eval `results/` into the `metrics/` corpus (SPEC-091)

R5 surfaced that small-model data lived only in the eval harness's `results/` corpus,
invisible to `analyze_metrics`/the audit (which read `metrics/`) — two telemetry systems
that don't talk. `ingest_eval_results.py` converts each `results/<model>/EVAL-N/result.json`
into a schema-valid `metrics/*.yaml` row by **reusing `record_metrics.build_metrics`** (no
schema drift): `pass`→completed/done, `fail`→failed/partial, `timeout`→blocked (+ derived
`error_type`/`kill_reason`); `started_at` derived from `timestamp − total_duration_s`; git
fields synthetic. Idempotent (`--dry-run`, `--include-archived`). +4 tests.

**DOGFOODED:** ran on the real corpus → **21 eval rows** ingested, all validate-clean,
idempotent. The `metrics/` corpus now holds 5 small/local models (gemma-4-31b, qwen-72b,
mistral-small, deepseek-32b, qwen3.5-9b-mlx) with outcome distributions — cross-model
comparison (the stated reason metrics exist) is queryable for the first time.

---

## 2.32.0 (2026-06-14)

### Inline duplicate-spec body-text gate (SPEC-088 / audit R6)

`check_followup_spec.py check()` (the per-suggestion gate) compared only titles, so a
verbatim-duplicate follow-up that shared few title tokens slipped through at creation
(the SPEC-055==048 leak); only the whole-corpus `scan_all` compared bodies. `check()`
now accepts `--suggestion-body` (the proposed requirement/AC prose) and flags
`body_similarity` against existing specs' Requirements+AC sections, reusing scan_all's
tokeniser/threshold so inline and corpus agree. Backward compatible (title-only when
omitted). +3 tests (30 green). The `nightshift` skill Step 7 should pass
`--suggestion-body` to activate it; until then `scan_all` remains the disk-level backstop.

---

## 2.31.0 (2026-06-14)

### Hook-driven metrics: rollout mechanism, model attribution (F3), LOOP rewire (SPEC-087)

Builds on SPEC-086 (the dogfooded mechanical emission) to make it the *primary* path
everywhere and to close the audit's F3 (cross-model attribution).

- **LOOP.md Step 13 rewritten:** metric/ledger emission is hook-driven at the mark-done
  commit; the in-loop `record_metrics.py` call is now explicitly **optional enrichment**,
  not a mandatory terminal step (the droppable instruction the audit showed fails).
- **ORCHESTRATOR.md standardized:** mark-done/blocked/in_progress commits use the
  canonical `chore: mark <id> <state>` subject (the hook + `started_at` derivation key on
  it; the old `[<id>] chore: mark done` would not trigger the hook). Metrics no longer
  hand-authored.
- **Model attribution (closes F3):** the mark-done commit MAY carry a `Nightshift-Model: <id>`
  trailer; `record_metrics.py --mark-commit` reads it (precedence trailer > `--model` >
  config > `unknown`). Best-effort — a dropped trailer degrades to `unknown`, no hard
  dependency — but when present the rows finally answer "which model". The mark-commit
  regex also broadened to accept `chore(scope): mark ...`.
- **`nightshift-sync.py --install-git-hooks`** (opt-in): idempotently activates the
  post-commit hook in each install's git hooks dir — merges the marked block into an
  existing hook (e.g. graphify) rather than overwriting, and dedups monorepo installs
  that share one `.git`. Off by default (it touches `.git/hooks`); pair with `--dry-run`.
- **Tests:** +3 mark-commit (trailer / no-trailer→unknown / `chore(scope):`), +5 sync
  hook-install (fresh / merge / idempotent / dry-run / non-git). 39 metrics+sync tests green.
- **DOGFOODED (AC5):** SPEC-087's own `chore: mark SPEC-087 done` commit (`9ab12481`)
  with a `Nightshift-Model: claude-opus-4-8` trailer auto-emitted
  `metrics/2026-06-14_002_SPEC-087.yaml` — validate-clean, `model` populated from the
  trailer, zero hand-authoring.

**Reach:** monorepo installs (Cortex/*, Inbox, Tools/*, Skills/focus) are live (shared
hooks path). **Deferred:** executing the standalone-repo rollout (Fartownik/CoJezdzi/
shipyard/agent-chat-mcp) — the mechanism is built + dry-run-verified, but installing into
active external repos is left as a deliberate `nightshift-sync.py canonical --install-git-hooks`
run rather than mutating them mid-session.

---

## 2.30.0 (2026-06-14)

### Mechanical metrics + failure-ledger emission at the mark-commit (SPEC-086)

The 2026-06-14 audit (`AUDIT-followup-2026-06-14.md`) measured that SPEC-067's
`record_metrics.py` changed nothing on real runs — metric capture stayed at 1.6%
because the script still had to be *invoked by the agent* at the end of a run (a
droppable terminal step), and 0 failure-ledgers existed across 11 installs. Root
cause: fixes that depend on the agent following an instruction don't survive real
runs. The remedy is mechanical.

- **`record_metrics.py` gains `--mark-commit <sha>` mode.** Given a
  `chore: mark <id> done|blocked` commit it derives EVERYTHING with zero
  agent-supplied args: spec-id/outcome from the subject, `started_at` from the
  matching `mark <id> in_progress` commit, `completed_at` from the mark commit,
  files/lines from the `in_progress..mark` span (scoped to the install), tests from
  the spec's newest report, model/harness from config. Routes to the correct
  install via the spec file path changed in the commit. Idempotent (won't duplicate
  or clobber an agent-authored row). No-ops on every non-mark commit.
- **`hooks/post-commit`** (new) calls it, so emission is agent-independent. If the
  repo already has a post-commit hook (e.g. graphify), install the marked block at
  the top (graphify's early `exit 0` would skip a trailing block).
- **`tests/test_mark_commit_metrics.py`** (5 tests, AC1–AC5). Existing 12
  `record_metrics` tests unchanged/green.
- **DOGFOODED (AC6):** SPEC-086's own `chore: mark SPEC-086 done` commit
  (`b59d7a38`) auto-emitted a `validate_metrics`-valid row with zero hand-authoring.
  Emitted row committed as evidence (`metrics/2026-06-14_001_SPEC-086.yaml`).

**Reach:** the monorepo installs (Cortex/*, Inbox, Tools/*, Skills/focus) are LIVE
immediately — they share Argo Home's `core.hooksPath`, so the one installed
`post-commit` serves all of them and falls through to canonical's new
`record_metrics.py`. The next real internal `mark done` auto-emits. **Deferred to
SPEC-087 (rollout, draft):** LOOP.md/ORCHESTRATOR wording (in-loop call → optional
enrichment), and installing the hook + syncing the new `record_metrics.py` into the
STANDALONE repos (Fartownik/CoJezdzi/shipyard — their copies lack `--mark-commit`,
so a hook-only install there no-ops). Verify-then-sync for the standalone fan-out.

**Known limitation (not fixed here):** hook-emitted rows carry `model: unknown` — the
hook can't know which model ran. This fixes R1 (rows exist: 1.6% → guaranteed) and R3
(ledger), but NOT the audit's F3 cross-model-comparison purpose; `model` attribution
still needs the optional in-loop enrichment call, or capturing the running model at
commit time (e.g. a commit trailer the hook reads) — tracked separately.

**Changes:** `record_metrics.py` (+`--mark-commit` mode), `hooks/post-commit` (new),
`tests/test_mark_commit_metrics.py` (new), `specs/SPEC-086-*` (done), `specs/SPEC-087-*`
(draft), version artifacts → 2.30.0.

---

## 2.29.5 (2026-06-14)

### Version-artifact reconciliation + audit follow-up (SPEC-086 drafted)

**Version drift fix (bookkeeping bug).** Releases 2.22.0→2.29.4 bumped this CHANGELOG
but left the version-carrying artifacts behind: `config.yaml` was stuck at `2.23.0`,
`config-reference.yaml` and `LOOP.md` at `2.21.0`. Because `nightshift-sync.py` reads
the canonical version from `config.yaml`, every install was being compared against a
stale baseline. All three artifacts are reconciled to `2.29.5` here. (This is the
recurring drift the journal flagged on 2026-04-17 — "bump + sync in the same commit
as every canonical merge … needs a hook to enforce." Enforcement candidate noted.)

**Audit follow-up (no behavior change in this entry).** `AUDIT-followup-2026-06-14.md`
measured whether the 2026-05-28 audit's R1–R6 (landed v2.19.0) changed real-run
behavior. Finding: they did not — metric capture is still 1.6% (R1), 0 failure-ledgers
exist across 11 installs (R3), 0 small-model runs (R5). The fixes that depended on the
agent following an instruction failed; only the pure-code fixes (R4, R6) moved.

**SPEC-086 drafted** (`specs/SPEC-086-...`): make metrics + failure-ledger emission
mechanical by triggering it at the parent's main-side `chore: mark <id> done|blocked`
commit (a post-commit hook), instead of asking the agent to remember a terminal call.
Status `draft` — must be dogfooded (AC6) before it is marked done, explicitly because
SPEC-067 was marked done without a real-run check and the audit proved it non-working.

**Changes:**

- `config.yaml`, `config-reference.yaml`, `LOOP.md`: `kit_version` → `2.29.5`.
- `specs/SPEC-086-mechanical-metrics-emission-at-mark-commit.md`: new (draft).
- `AUDIT-followup-2026-06-14.md` (in the Nightshift project root): new.

---

## 2.29.4 (2026-06-05)

### Apply git-worktree detection in _load_registries (SPEC-085)

`_load_registries()` now skips any `projects-registry.json` found inside a git-worktree
checkout, closing the same class of gap that SPEC-072 closed for project discovery.
A shared `_is_git_worktree(path)` helper is extracted at module level and used by both
`_discover_projects()` and `_load_registries()` — eliminating duplicated inline detection logic.

SPEC-084's `logger.debug("skipped git-worktree checkout: %s", project_root)` line and
the surrounding comment block in `_discover_projects()` are preserved exactly (behavior
identical; only the predicate expression was replaced with the helper call).

**Changes:**

- `nightshift-master.py`: added `_is_git_worktree(path: Path) -> bool` helper at module
  level (after `_port_for_name`); updated `_load_registries()` to call the helper on each
  registry file's parent dir and skip if it's a worktree; updated `_discover_projects()`
  to call the helper instead of the inline `(project_root / ".git").is_file()` expression.
- `tests/test_ns_control.py`: added `TestLoadRegistries` class with five tests covering
  AC3 (shared helper) and AC4 (worktree registry skipped, real registry loaded).

---

## 2.29.3 (2026-06-05)

### Log skipped git-worktree checkouts during Control discovery (SPEC-084)

`_discover_projects()` now emits a `DEBUG` log line (`skipped git-worktree checkout: <path>`)
whenever it skips a discovered root because it's a linked git worktree (the SPEC-072
`.git is a file` guard). Normal startup output and the returned project list are unchanged.

**Changes:**

- `nightshift-master.py`: added `import logging` and a module-level
  `logger = logging.getLogger(__name__)`; added `logger.debug(...)` call immediately
  before the `continue` in the worktree-skip guard (line ~119).
- `tests/test_ns_control.py`: added `TestDiscovery.test_skipped_worktree_emits_debug_log`
  — asserts the DEBUG line appears (naming the path) for a synthetic worktree (.git FILE)
  and is absent for a normal project (.git directory); also asserts the returned project
  list is unchanged (AC2).

---

## 2.29.2 (2026-06-05)

### Gate static-irrelevant live-only board UI in export (SPEC-083)

The static snapshot export now hides three categories of UI that are meaningless
in an offline, single-file context: the Refresh button (`#btn-refresh`), worktree
status badges (`.wt-badge`), and external-project chips (`.chip[data-external="1"]`).

**Changes:**

- `board.py` (`_build_static_shim`): added a `<style>` block (SPEC-083 section)
  with three `html.static-export { display: none !important; }` rules, and added
  `document.documentElement.classList.add('static-export')` immediately after the
  `window.__STATIC__ = true` assignment. The CSS class is set by JS in the shim so
  it applies only when the shim runs (i.e. in static exports). The live board is
  completely unchanged — no modification to `HTML_TEMPLATE` or live code paths.

- `tests/test_board_export.py`: new `TestStaticUIGating` class (7 tests, AC3).
  Asserts CSS hide rules are present in the export HTML, the `static-export` class
  setter is present, and the gating CSS does NOT appear in the live `HTML_TEMPLATE`.

**No config changes required.**

---

## 2.29.1 (2026-06-05)

### Anchor-scoped display-path strip in master board (SPEC-082)

`nightshift-master.py` frontend JavaScript previously stripped only the macOS
`/Users/<name>` prefix for display, leaking full paths from Cowork VM
(`/sessions/.../mnt/...`), Linux (`/home/<name>`), and macOS temp
(`/var/folders/...`) environments.

**Changes:**

- `nightshift-master.py`: replaced the inline
  `p.path.replace(/^\/Users\/[^\/]+/, '~')` with a call to a new
  `displayPath(p)` helper that collapses four prefix patterns to `~`:
  `/Users/<n>`, `/home/<n>`, `/sessions/<id>`, and `/var/folders/<x>/<y>`.
  The helper is display-only — `p.path` (real absolute path) is still used
  verbatim in `card.dataset.path`, `path.title`, and all action API calls.
  `start`/`stop`/`open` behavior is unchanged (R2 / AC2).

- `tests/test_ns_control.py`: new `TestDisplayPathNormalization` class with 8
  tests covering AC3 (node-executed normalization for `/Users/`, `/home/`,
  `/sessions/` inputs), R3 (unrecognized path preserved), and AC2 (execution
  paths use raw `p.path`).

**No config changes required.** `nightshift-master.py` is outside `canonical/`
so no `kit_version` bump is warranted.

---

## 2.29.0 (2026-06-05)

### kit_version-gated prose path-leak severity (SPEC-081)

`validate_specs.py` now reads the project's live `kit_version` from its
`config.yaml` to decide whether a prose absolute-path leak is a **WARNING**
(transition period) or a hard **ERROR** (post-migration).

**Changes:**

- `validate_specs.py`: two new internal helpers —
  `_read_kit_version(config_path)` (yaml.safe_load, returns None on any
  failure) and `_kit_version_gte(version_str, threshold)` (tuple-split
  comparison, returns False on any parse error for safe degradation).
- `validate_file` now accepts an optional `config_path: Path | None = None`
  parameter. When omitted, it auto-resolves from `spec_file.parent.parent /
  "config.yaml"` (standard `.nightshift/specs/<SPEC>.md` layout), so
  both directory-mode and file-mode invocations (e.g. pre-commit hook) pick up
  the project config automatically.
- Prose leak finding is **ERROR** when `kit_version >= 2.24.0` (value of
  `PROSE_ERROR_KIT_VERSION`); **WARNING** otherwise — including when config is
  absent, unreadable, missing the `kit_version` key, or has a non-parseable
  value.
- Registry leaks remain **ERROR** unconditionally (unchanged from SPEC-071).

**Operator note:** Before bumping a project's `kit_version` to `2.24.0` or
above, run the SPEC-071 prose migration tool (`migrate_paths.py`) to convert
any remaining absolute host paths to `{{ANCHOR}}`-relative tokens.  Bumping
the version without migrating first will cause pre-commit spec validation to
fail for every file that still contains an absolute path.

**No config changes required.**

---

## 2.28.0 (2026-06-04)

### Pre-flight validation of per-project column override config (SPEC-080)

`validate_specs.py` now checks a project's `board_column_defaults` override
(when present in the sibling `config.yaml`) during the normal validation pass.
Malformed overrides are surfaced as `WARNING`-level findings — matching SPEC-078's
runtime severity (warn + fallback, never a hard error).

**Changes:**

- `spec_frontmatter.py`: new `VALID_COLUMN_STATES` frozenset and
  `check_column_override(override) -> list[str]` — shared pure checker for
  unknown status ids, invalid `default_state` values, and non-permutation
  `order`. Single source of truth (R4).
- `board.py`: `_apply_column_override` refactored to call `_check_column_override`
  (imported from `spec_frontmatter`) rather than duplicating the validation
  logic inline. Fallback block retains equivalent logic when `spec_frontmatter`
  is unavailable. Runtime behavior (warn to stderr + fall back to canonical) is
  identical; the SPEC-078 test suite confirms this.
- `validate_specs.py`: new `validate_config_file(config_path) -> list` function
  (mirrors `validate_registry_file` pattern). `validate_directory` calls it when
  a sibling `config.yaml` is present, emitting results under the `"config.yaml"`
  key. Absent or valid overrides produce no findings (R3).
- `tests/test_validate_specs.py`: 9 new tests under `# SPEC-080` covering AC1
  (unknown status id), AC2 (invalid default_state), AC3 (non-permutation order),
  AC4 (valid + absent override → no findings), and `validate_directory` wiring.

**Migration:** None required. `validate_config_file` is additive; projects without
`board_column_defaults` in `config.yaml` see no change in output.

**Note:** `kit_version` bump in `config.yaml` deferred — config.yaml is out of
scope for this worktree agent per task hygiene rules.

---

## 2.27.0 (2026-06-04)

### Startup note when a per-project column override is active (SPEC-079)

`_apply_column_override` now returns a one-line note summarising what
changed vs the canonical defaults when a valid override is applied.
`__main__` prints the note immediately after the primary `▸ NIGHTSHIFT
BOARD — …` line.

**Changes:**

- `board.py`: `_apply_column_override` return type changed from `None` to
  `str | None`.  Returns a `▸ Column override loaded: …` string listing
  only the state-changed columns (in canonical order) and/or "order
  customized", or `None` when no override is active, the section is absent,
  or the override is invalid.  Identity overrides (present but identical to
  canonical) also return `None`.
- `board.py` `__main__`: captures the return value of `_apply_column_override`
  and prints `  <note>` when non-None.
- `tests/test_board_api.py`: eight new tests under "SPEC-079" covering AC1–AC4
  (note present for valid override, absent without one, names only changed
  columns, column order determinism, no-delta edge case, invalid-override guard).

**Migration:** None required.  Callers that discarded the return value of
`_apply_column_override` continue to work unchanged.

---

## 2.26.0 (2026-06-04)

### Board toolbar "Reset column layout" button (SPEC-077)

Adds a one-click "↺ RESET COLS" button to the board header toolbar that restores
the canonical default column layout (collapsed: active, planning, blocked;
hidden: superseded, retired; order: canonical) by calling the existing
`_seedColumnsFromDefaults()` helper and persisting the result via `saveSettings()`.

**Changes:**

- `board.py` HTML: added `<button id="btn-reset-cols" onclick="resetColumnLayout()">↺ RESET COLS</button>` to the header toolbar, between ⇔ FIT and ⊞ COLS.
- `board.py` JS: added `resetColumnLayout()` — calls `_seedColumnsFromDefaults()`, `renderBoard()`, `saveSettings()`. Column-level state only; `cardOrder`, `columnWidths`, graph settings, and all other preferences are untouched.
- `tests/test_board_browser.py`: four new tests covering button presence (AC1), canonical state after click (AC2), preservation of non-column prefs (AC3/AC4), and post-reload persistence (R3).

**Migration:** None required. `resetColumnLayout` is purely additive.

---

## 2.25.0 (2026-06-04)

### Board startup stdout/stderr captured to per-project log file (SPEC-076)

`nightshift-master.py` `start_project()` previously discarded each board's
stdout/stderr via `subprocess.DEVNULL`. Board crashes on startup (such as the
malformed-spec traceback in SPEC-073) left no trace — the only signal was "Board
did not start within 10s" with no cause.

**Changes:**

- `start_project()` opens `board.restart.log` (append-truncated on each start,
  write mode) in the same directory as `board.py`, and passes the file handle
  as both `stdout` and `stderr` to `subprocess.Popen`. The parent closes its
  handle after `Popen` returns; the child keeps writing — the call remains
  non-blocking (AC3).
- Log path resolves relative to `board.py`'s parent directory, covering both
  layouts transparently:
  - Standard `.nightshift/` layout → `<project>/.nightshift/board.restart.log`
  - Flat canonical-kit layout (SPEC-075) → `<project>/board.restart.log`
- The API response now includes `"log": "<absolute path>"` so the caller always
  knows where to look. The Control UI's start-timeout alert (`onStart` JS)
  appends the log path to the message: `"Board did not start within 10s\nLog: <path>"`.
- Tests (+3, `tests/test_ns_control.py`): Popen receives a real file handle (not
  DEVNULL) for stdout and stderr; log path resolves correctly for the standard
  layout; log path resolves correctly for the flat canonical-kit layout.

**Migration:** None — additive change. `board.restart.log` appears next to
`board.py` for each project on next board start. No config changes required.

---

## 2.24.0 (2026-06-04)

### Static board snapshot exporter (SPEC-070)

`board.py` and `nightshift-master.py` now support exporting a self-contained,
offline-capable HTML snapshot of any project's Nightshift board.

**Usage — single project:**

```bash
python .nightshift/board.py --specs .nightshift/specs --export my-board.html
```

**Usage — batch export via master:**

```bash
python nightshift-master.py export-snapshot --projects API,CORE --out ./snapshots/
```

The exported file is a single `.html` file that works without a running server or
network connection. All API routes are intercepted by an inline `fetch()` shim
that resolves from a `window.STATIC` blob embedded in the page. `marked.js` and
`vis-network.js` are downloaded at export time and inlined. Google Fonts and
SortableJS CDN references are removed. `window.Sortable` is stubbed as a no-op
constructor. Worktree `path` values are tokenized via `path_vars.tokenize()`.
AC7 fail-closed gate: any residual absolute path outside a code fence/span
raises `ExportLeakError` and blocks the write.

**New public API in `board.py`:**
- `export_board_html(specs_dir, project, *, lib_fetcher, reports_dir, worktree_status) -> str`
- `ExportLeakError`

**New subcommand in `nightshift-master.py`:**
- `export-snapshot --projects NAME[,NAME,...] [--out DIR]`

---

## 2.23.0 (2026-06-04)

### Per-project column default-state override (SPEC-078)

Projects can now override the canonical SPEC-074 board column defaults (per-column
`default_state` and/or column order) for their board only, without modifying `board.py`.

**How to use:** add an optional `board_column_defaults:` section to the project's
`.nightshift/config.yaml`:

```yaml
board_column_defaults:
  default_state:
    blocked: expanded   # change only the columns you want
  order:                # optional full-permutation reorder
    - in_progress
    - ready
    - draft
    - blocked
    - active
    - planning
    - done
    - superseded
    - retired
```

**Changes:**
- `board.py` gains `_build_status_columns()` (extracted builder, no behavior change),
  `_VALID_DEFAULT_STATES` constant, and `_apply_column_override(config_path)` function.
- `_apply_column_override` is called from `__main__` after `specs_dir` is resolved;
  it reads `config.yaml` (from `specs_dir.parent/`), merges any valid
  `board_column_defaults` override over the canonical defaults, and reassigns the
  `STATUS_COLUMNS` and `status_columns_json` module globals.
- Absent section / missing file / invalid override → canonical defaults unchanged
  (SPEC-074 behavior, `global` reassignment never executed). Invalid overrides emit a
  `WARNING` to stderr and fall through without breaking board startup.
- The `STATUS_COLUMNS_ORDER` drift guard is unaffected: order overrides are validated
  as full permutations of all 9 statuses before being applied.
- `config.yaml` is already excluded from `nightshift-sync.py` (line 51 comment) so
  the override survives canonical syncs.
- `config-reference.yaml` updated with `board_column_defaults` section.
- **Tests:** +10 `canonical/tests/test_board_api.py` covering AC1–AC5. Total: 113 passed.

**Migration:** none — additive config section, no behavior change for projects without
the override. `nightshift-sync.py canonical` propagates the updated `board.py`.

---

## 2.22.0 (2026-06-04)

### Board default column layout (SPEC-074)

Fresh boards now open with an opinionated column layout instead of nine expanded,
equally-weighted columns. The new default (left → right):

| Column | Default state |
|--------|---------------|
| ACTIVE | collapsed |
| PLANNING | collapsed |
| DRAFT | expanded |
| BLOCKED | collapsed |
| READY | expanded |
| IN_PROGRESS | expanded |
| DONE | expanded |
| SUPERSEDED | hidden |
| RETIRED | hidden |

**Changes:**
- `STATUS_COLUMNS_ORDER` reordered to `active, planning, draft, blocked, ready, in_progress, done, superseded, retired`.
- Each `STATUS_COLUMNS` entry now carries `default_state: "expanded"|"collapsed"|"hidden"` — serialized into the `COLUMNS` payload via `__STATUS_COLUMNS_JSON__` / `/api/statuses`.
- Client JS seeds `collapsedColumns` and `hiddenColumns` from `col.default_state` on fresh state (no saved version) or version mismatch.
- `COL_STATE_VERSION = 1` in localStorage. Existing boards pick up the new defaults once (one-time adoption); subsequent loads restore user customization normally. `cardOrder` and all other preferences are not affected by the version bump.
- Drift guard unchanged — `STATUS_COLUMNS_ORDER` set still equals all nine canonical statuses.

**Migration note:** On first load after this update, each project's board will re-seed
`collapsedColumns` / `hiddenColumns` from the new defaults. Any explicit collapse/expand/hide
choices the user made previously will need to be re-applied once. `cardOrder`,
`columnOrder`, `columnWidths`, and all other settings are preserved.

---

## 2.21.0 (2026-06-01)

### Board graph view — grouping-node shape + dashed parent edges (SPEC-070)

The graph view previously drew only `after:` dependency edges and gave every spec
an identical dot, so there was no way to tell a runnable spec from a `type: main`
grouping/umbrella spec — leading to a failed attempt to "run" a grouping spec
(which `ORCHESTRATOR.md` §2.1b and `nightshift-dag.py` treat as non-executable).

- **Grouping-node shape.** Nodes whose `type ∈ {main, nfr}` (the nightshift-dag
  executable predicate) render as a **diamond**; runnable specs keep the **dot**.
- **Dashed parent edges.** Faint, no-arrowhead **dashed** edges show `parent:`
  grouping membership, visually distinct from solid `after:` arrows. Drawn only
  when both endpoints are visible and the parent resolves to a real node.
- **GROUPING legend toggle.** Mirrors the status-hide legend; default on; hides
  the dashed edges on high-fan-out parents (persisted in settings).
- **API (additive).** `/api/graph` nodes now carry `type`; the response gains a
  separate `parent_edges` list (resolvable parents only). Existing `edges`
  (after-deps) and node placement (`X = status`) are unchanged.
- **Tests.** +5 `canonical/tests/test_board_api.py` (node `type`, `parent_edges`
  for resolvable + dangling parents, after-edge isolation). JS syntax green.

**Migration:** none — additive API + client-only render change. `nightshift-sync.py canonical`
propagates the updated `board.py` to installs.

## 2.20.1 (2026-05-31)

### Bugfix — board column fit overflow

`fitColumns()` now subtracts board-view padding and inter-column gaps before
dividing width, so columns fill the viewport without overflowing past the right
edge. *(Catch-up entry — shipped in commit `fceae332`; config.yaml was bumped at
the time but this CHANGELOG entry was missed.)*

## 2.20.0 (2026-05-30)

### Board UX — auto-fit columns + panel below header

⇔ FIT button distributes visible expanded columns to fill board width; the detail
panel starts below the header toolbar (`var(--header-h)`) instead of covering it;
`syncHeaderHeight()` keeps the offset live on init + resize. 4 new unit tests.
*(Catch-up entry — shipped in commits `33b710d3` / `54095cd6`; CHANGELOG entry was
missed at the time.)*

## 2.19.2 (2026-05-29)

### Test-only — correct stale `check_followup_spec` unknown-domain test

`test_proposed_id_fallback_for_unknown_domain` asserted that an unrecognized
domain maps to `FART-MISC-`. That was pre-2.17.0 behavior. Since 2.17.0,
`_proposed_id`'s documented priority is: `--parent-id` → domain in
`_DOMAIN_PREFIX_MAP` → **infer the project's dominant prefix** (generic `SPEC-`
when nothing exists to infer). Only the explicit `misc` domain maps to
`FART-MISC-`. The hardcoded-FART expectation also contradicts the kit's
language-agnostic principle.

Replaced the single stale assertion with three accurate cases: unknown domain
**infers** the existing prefix (`FART-DS-`), unknown domain in an empty project
falls back to `SPEC-`, and explicit `misc` maps to `FART-MISC-`. **Full canonical
suite is now green (904 passed, 0 failed).**

**Migration:** None — test-only, no protocol/runtime/synced-file change.

---

## 2.19.1 (2026-05-29)

### Bugfix — board `/api/projects-registry` crash under import-based launch (SPEC-069)

`board.py`'s `projects_registry()` resolved its file via `specs_dir`, a name bound
only inside the `if __name__ == "__main__":` block. Under the documented
`python board.py` launch that name is a module global and the endpoint works; under
**import-based launch** (`uvicorn board:app`, the test harness, any embedding host)
it is undefined → `NameError` → HTTP 500. Because a board page load calls the
endpoint on startup, the run-prompt browser test could not reach its assertions.

- **Fix:** resolve the registry path via `cache._specs_dir.parent` — the same
  injected-cache source the worktree endpoint already uses. One line; no other
  endpoint was affected (`project_name`, `reports_dir`, `reads_file` all carry
  module-level defaults; only `specs_dir` lacked one).
- **Tests:** +26 in `tests/test_board_api.py` covering the previously-untested
  registry endpoint (incl. the regression: 200 under import launch, populated, and
  malformed-JSON paths), the external-spec proxy (port range, spec_id validation,
  unreachable shape), reports listing/reading (incl. a direct `_resolve_report_path`
  traversal-guard test), and report read-tracking persistence.
- **Stale test fix:** `test_run_prompt_button_copies_skill_based_prompt` asserted
  run-prompt text removed by the 2.18.1 thin-pointer slimming; updated to the
  current phrasing (`before marking the spec blocked`, `Suggested Follow-up Specs`).
  Board test failures went 2 → 0.

**Migration:** None — patch, no config/protocol/metrics change. Projects pick up the
fixed `board.py` via `nightshift-sync.py canonical`.

**Still pre-existing (unrelated, untouched):**
`test_check_followup_spec.py::test_proposed_id_fallback_for_unknown_domain`.

---

## 2.19.0 (2026-05-29)

### Single-call metrics + duplicate-spec scan (SPEC-067, SPEC-068)

Acts on the 2026-05-28 canonical audit, which found that per-spec metric capture had
collapsed in practice (the busiest project, Cortex/api, logged 102 reports but 2
metric files) because Step 13 asked the *model* to hand-author a ~60-field YAML —
the first thing a loaded or less-capable model drops. The fix moves authoring from
the model to deterministic code, shrinking the loop rather than adding to it.

**`record_metrics.py`** (new) — emits one schema-valid per-spec metrics YAML from a
single call. The model supplies only what it knows (status, outcome, test counts,
review cycles, failure info); everything else is **derived** (files/lines/commit from
git; harness/loop_version/review_mode from `config.yaml`) or **computed**
(satisfaction block). Key points:
- Additive **`outcome`** field — controlled vocabulary `done | partial | blocked | noop`
  — alongside the unchanged `status` enum, so reports/metrics become minable without
  breaking any consumer. `noop` (with `status: completed`) marks runs that needed no
  code change, so duplicate/no-op runs stop masquerading as feature work.
- **`--model`** override beats the template's blank `runtime.model`, so the model
  field — the basis for cross-model comparison — is never empty.
- Non-`completed` runs require `--error-type`/`--error-desc` and append a one-line
  `failure-ledger.json` entry, so the failure path is recorded, not invisible.
- Emitted files pass `validate_metrics.py` unchanged (verified by tests).
- Multi-document `config.yaml` is parsed via `safe_load_all` + merge.

**`LOOP.md`** — Step 13 hand-authoring block and the dead "Post-Run Metrics Emission"
triple-JSON section (which produced 0 files in practice) are removed and replaced by
the `record_metrics.py` call. **LOOP.md: 2281 → 2090 lines (−191).** Step 14 report
template gains a controlled `**Outcome:**` line.

**`check_followup_spec.py`** — new **`--scan-all`** mode compares every spec pair
across the whole specs dir by title AND requirement/AC body similarity, catching
duplicates regardless of how they were created. Root cause from the audit: the
per-suggestion gate only runs in the kickoff flow, so hand-authored/bulk-promoted
duplicates (e.g. SPEC-CTX-API-055, a verbatim copy of SPEC-048) bypass it entirely.

**Tests** — `tests/test_record_metrics.py` (12) and 6 added to
`tests/test_check_followup_spec.py`; all green.

**Incidental:** fixed `config-reference.yaml` `kit_version` drift (was stuck at
2.17.0 → 2.19.0); bumped `loop_version` to 2026-05-29.

**Migration:** None required — schema is backward-compatible (additive `outcome`
field; `status` enum unchanged). Projects pick up `record_metrics.py`,
`check_followup_spec.py`, and the slimmer `LOOP.md` via `nightshift-sync.py canonical`.
The next LOOP run per project emits metrics via the script instead of by hand.

**Known pre-existing failures (not introduced here):**
`test_check_followup_spec.py::test_proposed_id_fallback_for_unknown_domain` and
`test_board_browser.py::test_run_prompt_button_copies_skill_based_prompt` fail on the
parent commit too; left for a separate fix to keep this change surgical.

---

## 2.18.1 (2026-05-28)

### Relocate follow-up spec policy into the kickoff skill

The post-report **Suggested Follow-up Specs** handling policy (the
`check_followup_spec.py` conflict-check loop) previously lived inline in
`board.py`'s `buildRunPrompt()`, duplicating behavior that belongs to the
`/nightshift kickoff` flow. It now lives solely in the kickoff skill.

**`board.py`:**
- `buildRunPrompt()` is now a thin pointer — it tells the kickoff agent to follow
  the `/nightshift kickoff` skill and not implement the spec itself, instead of
  embedding the full unblock + follow-up policy inline. The board run prompt and
  the skill can no longer drift.

**Kickoff skill (`SKILL.md`, not part of kit sync):**
- New "Step 7: Process suggested follow-up specs" carries the full policy
  (clean/conflict/NFR/missing-script branches).

**Migration:** None. No config schema, protocol step, or metrics change. Projects
pick up the slimmer `board.py` via `nightshift-sync.py canonical`.

---

## 2.18.0 (2026-05-28)

### NFR alignment gate + impact audit (SPEC-065, SPEC-066)

Two new mechanisms ensuring specs are reviewed against active NFRs before
execution, and that existing specs are surfaced when a new NFR is added.

**`validate_specs.py`:**
- Error on `status: ready` + `type: feature/bugfix/refactor` specs missing
  the `nfrs:` field. `nfrs: []` is valid — it means "reviewed, none apply."
- Warning (non-fatal) on `status: draft` + same types missing `nfrs:`.
- `status: done`, `in_progress`, and `blocked` specs are exempt (backward
  compatibility).
- New: `scope_tags:` on NFR-family specs must be a list of strings when present.

**`check_followup_spec.py`:**
- `nfr_texts` now returns ALL active NFRs unconditionally. Previous keyword
  filtering (domain/artifact match in NFR body) silently excluded NFRs that
  didn't happen to contain the domain string. Retired NFRs are excluded.

**`audit_nfr.py`** (new script):
- Scope-filtered impact report for non-done specs when a new NFR is added.
- Match strategy: spec's `domain:` / `layer-N` / `touches:` token intersection
  with NFR's `scope_tags`. No `scope_tags` = conservative, all non-done specs.
- Retired NFRs produce a message and exit 0 (no report).
- `--format text` (default) or `--format json`. Always exits 0 — report tool,
  not a pass/fail gate.

**`specs/_TEMPLATE-NFR.md`:**
- New `scope_tags: []` field on both top-level and sub-NFR frontmatter.
- Vocabulary: domain names (`ui`, `be`, `ds`), layer indicators (`layer-0`…
  `layer-3`), tech keywords (`swiftui`, `auth`, `database`).

**`SPEC-GUIDE.md`:**
- Phase 0: new step 3 — read all active NFRs before the spec interview begins.
- Phase 9 checklist: `nfrs:` item added (populate before saving).
- New "Creating an NFR Spec" section with `audit_nfr.py` post-save workflow.

**`SKILL.md`** (nightshift skill):
- Step 1: NFR scan added to context check.
- Step 4: `nfrs:` validation item added.
- Step 6 (new): post-save `audit_nfr.py` run for `type: nfr` specs.

**Migration:** No breaking changes. Existing `done`/`in_progress`/`blocked`
specs are exempt from the `nfrs:` requirement. Projects with `ready` specs
that lack `nfrs:` will now see validation errors — add `nfrs: []` to clear
them (or list applicable NFR IDs).

---

## 2.17.0 (2026-05-26)

### Follow-up spec ID collision prevention

Fixed a class of spec ID collision where follow-up specs from multiple parent
specs share a global sequential counter and land on the same ID (e.g., two
parents both generate a third child and both claim `-044`).

**`check_followup_spec.py`:**
- Added `--parent-id PARENT` argument. When provided, the proposed ID uses
  `PARENT-NNN` format scoped to that parent, making cross-stream collisions
  structurally impossible.
- Added existence check: the returned `proposed_id` is now guaranteed unique
  against all existing spec IDs in the directory — even without `--parent-id`.
- Fixed project-prefix inference: when the domain doesn't match the built-in
  `_DOMAIN_PREFIX_MAP` (Fartownik-specific), the script now infers the dominant
  ID prefix from existing specs instead of falling back to `FART-MISC-`. This
  makes the script useful in non-Fartownik projects without configuration.

**`LOOP.md`** — report template `## Suggested Follow-up Specs` block gains a
`parent:` field. Set it to the originating spec's parent ID so the kickoff
agent can pass `--parent-id` to `check_followup_spec.py`.

**`SPEC-GUIDE.md`** — new `## ID Assignment Rules` section documents the
mandatory use of `check_followup_spec.py` for all ID generation, the collision
risk of manual increment, and when to use `--parent-id`.

**Migration:** No changes to existing specs or config.yaml. The `--parent-id`
argument is additive and backward-compatible. Projects should update their local
`check_followup_spec.py` via `nightshift-sync.py canonical`.

---

## 2.16.0 (2026-05-23)

### Board responsiveness — diff render, tab-activate sync, dep-aware panel refresh (SPEC-063)

The SPEC-050 board now updates incrementally:

- **Card-level diff render.** When the 10s poll detects only an mtime change
  on existing specs (no column moves, no adds/removes), only the changed
  cards' DOM is swapped via `renderCard(spec, blocksMap).replaceWith()`. Full
  `renderBoard()` still fires for column-move / topology changes (preserves
  SortableJS state and column ordering) and for the REFRESH button.
- **Graph node-level diff.** `updateGraphFromSpecs(fresh)` uses
  `graphNodesDataset.update([{id, color}])` to recolor changed nodes without
  destroying the network or re-running layout. Topology changes still hit
  `showGraph()` on next tab activate.
- **Tab-activate sync.** `showBoard()` (made async) and `showGraph()` now
  fetch `/api/specs` on activate so the newly-visible tab reflects current
  disk state, not the cached `specs[]` from the last poll. Eliminates the
  "manual refresh after switching tabs" workaround.
- **Dependency-aware panel refresh.** When the panel is open and a spec
  referenced by it (`after:`, `requires:`, `parent:`, `violates:`, `nfrs:`,
  `children:`, or reverse `blocks`) changes status, `refreshPanelDependencies()`
  re-renders just the chips section — no full panel rebuild, no scroll-jump.

### Cross-project dependency navigation (SPEC-064)

The board now resolves dependencies that live in other projects:

- **`projects-registry.json` in every `.nightshift/`.** Generated by
  `nightshift-sync.py canonical` at the end of the sync pass. Lists each
  project's name, absolute path, hash-derived board port, and most common
  spec-ID prefixes (≥3 occurrences, sorted by count then length).
- **`/api/projects-registry`** — board exposes the file as JSON for the UI.
- **`/api/external-spec/{port}/{spec_id}`** — server-side proxy to a peer
  board's `/api/spec/{id}`. Port whitelisted to 7800-7999 (SSRF protection),
  500ms timeout, returns `{_unreachable: true}` gracefully when the target
  board isn't running. CORS-free by design — no `CORSMiddleware` needed.
- **External chip rendering.** Dependency chips for specs that resolve to
  other projects render as anchors with `↗` icon, dashed border, and
  `target="_blank"`. Status pill fills in asynchronously via the proxy.
- **`?spec=<id>` URL handler.** Auto-opens the panel for the requested
  spec after load. Powers cross-board navigation (the external link from
  project A's board lands on project B's board at the right spec).
- **Longest-prefix-match resolver.** `SPEC-CTX-API-007` correctly resolves
  to `api` (prefix `SPEC-CTX-API`), not `core` (prefix `SPEC-CTX`).
- **"Spike" reminder.** VOCABULARY.md gained a Cross-Project Dependencies
  section linking the registry mechanism to the spec-type vocabulary.

### Compatibility

Fully backward-compatible:
- No frontmatter schema changes.
- Boards without a `projects-registry.json` (older projects, never re-synced)
  degrade gracefully — `/api/projects-registry` returns
  `{generated_at: null, projects: []}` and external dep resolution returns
  null, falling through to the existing internal-chip path.
- REFRESH button still triggers the full `renderBoard()` / `showGraph()`
  path; the diff render is additive.

### Migration

Run canonical sync once to write `projects-registry.json` into every project:

```bash
python3 ManagedProjects/Nightshift/nightshift-sync.py canonical
```

The new file appears alongside the propagated protocol files in each
`.nightshift/`. Restart any running `nightshift-board` processes so they
pick up the new endpoints.

### Out of scope (deferred)

- WebSocket/SSE push for sub-second freshness — 10s poll + diff render is
  sufficient at current scale.
- Multi-host federation (boards on different machines).
- Auto-starting the target project's board when clicking an external link.
- Reverse navigation ("who references me across projects").

---

## 2.15.1 (2026-05-23)

### Spec-type vocabulary for sub-agent discoverability (SPEC-062)

Added `canonical/VOCABULARY.md` — a concise (114-line) reference card summarizing
how sub-agents should treat each spec type. Focuses on the cases agents most often
mishandle: NFR lifecycle (`active | retired` only, never `blocked`/`done`),
research/analysis "done" criteria (`output_artifact` presence, not build/test
gates), and the "spike maps to research" clarification.

The full per-type rules still live in `_TEMPLATE-NFR.md`, `_TEMPLATE-RESEARCH.md`,
and `_TEMPLATE-ANALYSIS.md`. VOCABULARY.md is the entry-point summary so a
sub-agent handed a brief with `nfrs: [NFR-NNN]` injections doesn't have to
read four templates to learn the lifecycle rules.

**New file: `canonical/VOCABULARY.md`**
- Summary table (lifecycle / loop pickup / blockable / "done" per type)
- NFR contract (lifecycle, loop exclusion, blocker semantics, cross-refs, hierarchy, common sub-agent mistakes)
- Research/Analysis contract (lifecycle, output_artifact requirement, what "done" means, what NOT to do)
- Spike note (Agile-sense spike = `research` or `analysis`; no new type)
- Cross-reference quick card (`nfrs:`, `violates:`, `parent:`, `children:`, `domain:`, `output_artifact:`)

**Propagation:** added to `nightshift-sync.py → CANONICAL_PROTOCOL_FILES`. Synced
to every project's `.nightshift/VOCABULARY.md` on next `nightshift-sync.py canonical`.

**ORCHESTRATOR.md integration:** when a sub-agent brief includes injected NFR
constraints (§3.x), it now also receives a required-read line pointing to
`.nightshift/VOCABULARY.md`. Same for briefs whose spec resolves to
`domain: research` or `domain: analysis`.

**SPEC-GUIDE.md integration:** Phase 2 (Scope & Type) now cross-links to
VOCABULARY.md so spec authors discover the non-code lifecycle rules during
spec creation.

### Drift cleanup (incidental)

This release also bumps `kit_version` in `canonical/LOOP.md` and
`canonical/config-reference.yaml` to match `canonical/config.yaml` (previously
they were stuck at 2.14.3 while config.yaml was already 2.15.0). The drift was
pre-existing — `python3 scripts/check_nightshift_drift.py` is now green again.

### Out of scope (deferred)

- No new `type:` enum values. "Spike" is documented as a synonym for
  `research`/`analysis`, not a new type. Adding new types would require
  changes across `spec_frontmatter.py`, `validate_specs.py`, runners, and the
  board — explicitly deferred.
- No changes to NFR enforcement code (SPEC-058 already enforces lifecycle at the
  validator/board layer).

### Compatibility

Fully backward-compatible. No frontmatter schema changes, no protocol semantics
changes. New file is doc-only; existing projects keep working without re-sync
(but should re-sync at next opportunity to receive the new vocabulary file).

### Migration

```bash
cd <project>/.nightshift
python3 ../ManagedProjects/Nightshift/nightshift-sync.py canonical --dry-run
python3 ../ManagedProjects/Nightshift/nightshift-sync.py canonical
```

Or run `python3 nightshift-sync.py canonical` from the Nightshift root to
propagate to all projects at once.

---

## 2.15.0 (2026-05-21)

### Follow-up spec autocreation with conflict check (SPEC-060)

When the kickoff agent finishes or unblocks a spec, it now checks for a
`## Suggested Follow-up Specs` section in the run report and auto-creates
follow-up specs — no manual step required.

**New file: `canonical/check_followup_spec.py`**
Mechanical conflict check script. Given a suggestion title + optional artifact,
domain, and layer, it runs four checks:
- Title Jaccard similarity against all existing spec titles (threshold 0.4)
- `output_artifact` exact clash with any ready/in_progress spec
- Domain+layer cluster membership (informational)
- NFR file extraction — returns full NFR text for semantic judgment by the agent

Exit 0 = clean (with `proposed_id`). Exit 1 = conflict (with `conflicts` list).
NFR texts are always returned in both cases so the agent can judge semantically.

**`buildRunPrompt` updated** — the copied prompt now includes a follow-up spec
creation policy block: for each suggestion entry, run the script, auto-create if
clean, record conflict reason if not. NFR violations are judged semantically by
the kickoff agent after reading the surfaced NFR texts.

**`LOOP.md` Step 14 updated** — the run report template now includes a
`## Suggested Follow-up Specs` structured section (one YAML-like entry per
suggestion). Orchestrator fills it during report generation.

**`nightshift-sync.py` updated** — `check_followup_spec.py` added to
`CANONICAL_FILES` so it deploys to all `.nightshift/` projects on sync.

**Migration:** run `nightshift-sync.py canonical` to deploy. No config changes.
After deployment, `.nightshift/check_followup_spec.py` exists in each synced
project and the board's run prompt includes the creation policy.

---

## 2.14.3 (2026-05-20)

### Kickoff unblock before block

The board-copied `COPY RUN PROMPT` now tells the parent kickoff agent to try one
focused unblock pass before marking a spec blocked. If the orchestrator reports
blocked/stuck or the evidence gate fails, the parent gathers the exact blocker,
redirects or relaunches the run/implementation agent with a narrow unblock task,
and reruns the evidence gate.

The spec is marked blocked only when the unblock pass fails, cannot run without
human/external input, or continuing would be unsafe. Final Block Reasons and
escalations must include what unblock attempt was made, or why it was skipped.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated board
prompt and protocol docs.

## 2.14.2 (2026-05-20)

### Enforce NFR active lifecycle

NFR-family specs are now guarded by both validation and runtime tooling. Any
spec whose `id` starts with `NFR-`, or whose `type` is `nfr`, may use only
`status: active` or `status: retired`.

`validate_specs.py` rejects blocked/ready/done NFR-family specs with an explicit
NFR lifecycle error. `failure_persistence.mark_spec_blocked()` no longer writes
`status: blocked` to NFR-family specs; it records pending/failure state in the
body under `## Active Run State` instead. The board API rejects invalid
NFR-family status edits, and the detail-panel status dropdown limits NFR-family
specs to `active` and `retired`.

**Migration:** run `nightshift-sync.py canonical` to deploy the validator,
failure-persistence helper, board update, templates, and protocol docs. Existing
NFR-family specs with invalid statuses should be changed to `status: active`
unless intentionally retired.

## 2.14.1 (2026-05-17)

### Canonical sync ships validator helper modules

`nightshift-sync.py canonical` now deploys the first-party Python helper
modules imported by synced validators and DAG tooling. This prevents deployed
project copies from receiving `nightshift-dag.py` or `validate_metrics.py`
without local dependencies such as `model_stylesheet.py`,
`parallel_executor.py`, `dispatch.py`, and `metrics_fidelity.py`.

The canonical drift checker now parses synced Python files and fails if a
first-party import is missing from `CANONICAL_PROTOCOL_FILES`, so future helper
imports cannot silently break deployed `.nightshift/` folders.

**Migration:** run `nightshift-sync.py canonical` to deploy the helper modules
into project `.nightshift/` folders.

---

## 2.14.0 (2026-05-12)

### Autonomous kickoff resolution

The parent kickoff agent no longer offers merge/discard choices to the user.
Instead it resolves the run autonomously after the orchestrator completes:

- **Evidence gate (all four must pass to merge):** report exists, tests passed,
  code changed outside `reports/`, AC checklist has no `❌`.
- **Pass:** merge worktree branch, clean up, mark spec `done`, report to user.
- **Fail:** mark spec `blocked` via `failure_persistence.mark_spec_blocked`,
  write a Cortex breadcrumb, leave the worktree for inspection, send an
  escalation message explaining which check(s) failed and what's missing.

The board-copied "COPY RUN PROMPT" text was updated to reflect this contract.
The user is only involved when evidence is genuinely insufficient and the spec
is blocked.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated
`board.py` to project `.nightshift/` folders. The SKILL.md (`kickoff` and
`run` commands, Step 6) is updated in the global skills directory and does not
need a per-project deploy.

---

## 2.13.1 (2026-05-05)

### Blocked spec title preservation

Spec validation now rejects specs whose first body H1 is `# Block Reason`,
because the board derives card titles from the first H1 and would display the
blocker label instead of the real spec title.

Blocked specs must keep the real spec title as the first body H1 and use
`## Block Reason` as the first content section after that title. The canonical
template, loop/orchestrator guidance, and failure persistence helper now emit
that shape.

**Migration:** run `nightshift-sync.py canonical` to deploy the validator,
template, protocol docs, and helper update into project `.nightshift/` folders.
Existing blocked specs should be adjusted to keep a real title H1 first.

---

## 2.13.0 (2026-05-05)

### Board spec-link status previews

Spec links in the board detail panel now show linked-spec status without
requiring navigation. The `after:` and `blocks:` chips include compact status
labels and status-colored borders, with blocked and done specs emphasized.

Rendered `spec://SPEC-ID` links inside spec markdown get the same status
decoration. Hovering either a dependency chip or a decorated markdown link shows
the linked spec preview with ID, title, status, and problem/context snippet when
available.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated board,
docs, and config metadata into project `.nightshift/` folders.

---

## 2.12.1 (2026-05-03)

### Explicit kickoff command contract

Replaces the board prompt's implicit `/nightshift run <SPEC-ID>` parent-mode
instruction with an explicit `/nightshift kickoff <SPEC-ID>` command.

The Nightshift skill now treats `/nightshift kickoff` as a parent kickoff wrapper
around `/nightshift run` with `kickoff_parent: true`. In that mode, the generated
run/orchestrator brief must include a `## Kickoff Parent Context` section, so the
launched agent knows it is being monitored and must write live progress to
`reports/_wip/orchestrator-progress-<SPEC-ID>.md`.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated board and
orchestrator protocol. Update installed Nightshift skills separately where
applicable.

---

## 2.12.0 (2026-05-03)

### Board kickoff prompt and orchestrator progress contract

Adds a board action for copying a skill-based Nightshift run prompt from the
spec detail panel. The prompt delegates to `/nightshift run <SPEC-ID>` and
frames the receiving agent as a parent kickoff monitor rather than the
implementer.

The Nightshift skill now documents parent kickoff agent mode for `/nightshift
run`, including the split between the kickoff agent and the run/orchestrator
agent. `ORCHESTRATOR.md` adds a kickoff-parent progress contract: orchestrators
choose a cadence and keep live progress inspectable in
`reports/_wip/orchestrator-progress-<SPEC-ID>.md`.

The board copy-spec-ID icon is also restyled for clearer contrast in light and
dark mode.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated board,
orchestrator protocol, and config metadata into project `.nightshift/` folders.
Update installed Nightshift skills separately where applicable.

---

## 2.11.1 (2026-05-02)

### Git policy source of truth

Adds `GIT.md` as the canonical Nightshift git workflow policy. It now owns the
semantics for dirty-tree handling, spec status commits, commit format, hooks,
worktrees, merge/post-merge validation, and human-review expectations.

`LOOP.md`, `ORCHESTRATOR.md`, `BOOTSTRAP.md`, `HUMAN-REVIEW.md`, config comments,
and hooks now reference `GIT.md` instead of independently owning those rules.
The drift checker now verifies that the policy document is present, synced, and
referenced by the key protocol surfaces.

**Migration:** run `nightshift-sync.py canonical` to deploy `GIT.md` and
the updated references into project `.nightshift/` folders. No config field
changes are required.

---

## 2.11.0 (2026-05-01)

### OpenSpec-transfer workflow controls

Adds five canonical workflow/audit primitives derived from the OpenSpec analysis:

- `nightshift-instructions.py` emits agent-readable instruction packets with state, blockers, context files, validation commands, progress, and recommended next action.
- `verification_report.py` defines durable `verification.json` + `verification.md` artifacts with completeness/correctness/coherence dimensions and CRITICAL/WARNING/SUGGESTION severity gates.
- `source_fingerprints.py` records base SHA-256 fingerprints and blocks stale source-of-truth writes unless a human override reason is recorded.
- `nightshift-dag.py graph|next` now surfaces optional stacking metadata (`provides`, `requires`, `touches`, `parent`) and ready-spec guidance.
- `replay.py` writes and inspects failed-run replay bundles with command evidence, context hashes, diff summary, inventories, and blocker explanation.

Protocol docs now require instruction packets during context loading and verification reports before `status: done`. `nightshift-sync.py` deploys the new canonical helpers.

**Migration:** run `nightshift-sync.py canonical --apply` to copy the new helper scripts into deployed `.nightshift/` folders. Existing specs remain valid; stacking fields are optional.

---

## 2.10.3 (2026-04-26)

### New tool: `validate_specs.py` — static spec frontmatter validator

Adds a static validator that checks every spec `.md` file in a `specs/` directory
for well-formed frontmatter and a canonical lifecycle status value.

**What it validates:**
- Opening and closing `---` frontmatter delimiters present
- YAML inside the block is valid
- Required fields `id` and `status` are present
- `status` is one of: `planning`, `draft`, `ready`, `in_progress`, `blocked`, `done`, `superseded`, `active`, `retired`

**Source of truth:** `VALID_SPEC_STATUSES` constant added to `spec_frontmatter.py`.
Both `validate_specs.py` and (going forward) `board.py` should import from there
rather than maintaining a duplicate list.

**Pre-commit hook:** `hooks/pre-commit` now detects staged `specs/*.md` files and
runs `validate_specs.py` against them. A commit that stages a spec with an invalid
`status` is rejected before it lands.

**CLI usage:**
```
python3 .nightshift/validate_specs.py .nightshift/specs/            # full scan
python3 .nightshift/validate_specs.py .nightshift/specs/SPEC-001.md  # single file
python3 .nightshift/validate_specs.py .nightshift/specs/ --format json
```

**Tests:** `tests/test_validate_specs.py` — 24 tests covering all validation paths.

**Migration:** Copy `validate_specs.py` from canonical to your project's
`.nightshift/` directory and install (or reinstall) the pre-commit hook.

---

## 2.10.2 (2026-04-26)

### board.py — REPORTS button: spec-specific count

The spec-detail panel's `📋 REPORTS` button label was showing **global** unread count, but clicking it opens the panel **filtered by spec ID**. So a spec with zero matching reports still showed "(6 unread)" and the user opened to "no reports found" — confusing mismatch.

Now:

- No unread anywhere → `📋 REPORTS`
- No spec context, or all unread reports happen to match this spec → `📋 REPORTS (N unread)` (single number)
- Spec context, mixed counts → `📋 REPORTS (N/M unread)` where N = unread for this spec, M = unread total

Tooltip explains the format. The number you see is the number you'll see in the pre-filtered panel.

---

## 2.10.1 (2026-04-26)

### board.py — Fix: detail panel no longer auto-restores on page load

`openPanelId` was both **persisted** in localStorage and **restored on `loadSpecs()`**, which meant: open a spec → click outside the panel (which hides but doesn't clear the state) → reload → panel pops back open with the previous spec, even when you didn't have one open.

Two fixes:

1. `loadSpecs()` no longer auto-calls `openPanel(openPanelId)`; it explicitly resets `openPanelId = null` on every load. Recent-bar chips remain for one-click re-entry.
2. `openPanelId` is no longer written to `localStorage` (commented out in `saveSettings` / `loadSettings`). Stale state from previous sessions can't drift back.

The card-highlight feature (`card--active` for the spec whose panel is open) still works in-session — it just doesn't survive across reloads. That's the fix the user asked for.

---

## 2.10.0 (2026-04-26)

### board.py — Archive view for done specs

Done specs older than **14 days** (by file mtime) are now treated as **archived** for display purposes only — there's no new status, no protocol change, no spec edits. Pure UI behavior.

**Default:** archived specs are **hidden** from both the board and the graph view. The DONE column shows only fresh items (≤ 14 days), keeping it uncluttered as the project ages.

**New header button:** `🗄 ARCHIVED` lives next to `📋 REPORTS`.

- When archived items are hidden (default) and at least one exists, the button reads `🗄 +N` (with the count of hidden archives). Click to reveal.
- When showing, the button reads `🗄 ARCHIVED` and gets the active highlight. Click to hide again.
- When zero archived specs exist, the button is neutral.

**Coverage:** filter applies to (a) board column rendering, (b) board column count badges, (c) graph nodes (and incident edges drop along with them). Toggling the button re-renders both views.

**Threshold:** hardcoded to 14 days. Source of truth: each spec's file mtime, exposed via `_mtime` on `/api/specs`. State persisted in localStorage (`showArchived`).

**Why mtime:** matches the existing DONE-column auto-sort. No protocol changes, no `done_at` field needed. If a done spec gets edited (e.g. notes added) it'll un-archive until 14 days pass again — acceptable trade-off for not requiring a schema migration.

---

## 2.9.2 (2026-04-25)

### board.py — Reports: stronger read/unread distinction + live refresh

**Visual distinction** between read and unread reports:

- **Unread:** 3px left-rail accent in the theme color, subtle theme-tinted background, name in bold full-contrast text. Hover deepens the tint. Designed to draw the eye on a long list.
- **Read:** 55% opacity, no left-rail accent, name in muted color and normal weight. Hover lifts to 85% so they're still readable when you mouse over.

**Live refresh on MARK READ.** Hitting `✓ MARK READ` in the report-content view now re-renders the list view in the background, so when you click `← REPORTS` you immediately see the just-read item faded out — no manual refresh needed. (Previously the toast appeared but the list still rendered the report as unread.)

---

## 2.9.1 (2026-04-25)

### board.py — Reports list filter + header entry point

- **Filter input** in the reports panel. Live, case-insensitive substring match against report filename + basename. Heading shows `N of M · K unread` when filtered, or `M reports · K unread` when not. `✕` button clears the filter.
- **Pre-filled from spec context.** Clicking `📋 REPORTS` on a spec card now opens the reports list pre-filtered with that spec's ID — so you immediately see only reports for that spec. Clear the filter to see everything.
- **Header REPORTS button.** New `📋 REPORTS` in the main header (next to GRAPH / COLS) opens the reports panel without any spec context — useful for browsing across the whole project. Panel header shows "ALL REPORTS"; back button is hidden because there's no spec to return to.
- **Panel header label** now reflects the current view: `<spec-id>` (spec view), `<spec-id> · REPORTS` (reports filtered to a spec), `ALL REPORTS` (header entry), `<spec-id> · REPORT` / `REPORT` (single report view).

---

## 2.9.0 (2026-04-25)

### board.py — Report discovery: recursive

Reports were only being read from `.nightshift/reports/`, but agents tend to drop reports next to the artifact they reviewed (e.g. `App/FartownikDS/reports/...`, `App/Fartownik/reports/...`). The board now walks the project root and surfaces every `*.md` file inside any directory named `reports/`, with sensible excludes (`.git`, `.claude`, `.cortex`, `node_modules`, `DerivedData`, `Pods`, build/dist/target, venvs).

**API changes:**

- `GET /api/reports` items now have `filename` (project-relative path, used as the unique identifier) and `name` (short basename, used for display). Sorted newest-first by mtime.
- `GET /api/report/{filename:path}` accepts paths with slashes; resolves and validates the candidate is inside the project root (no traversal). Frontend uses `encodeURIComponent` on the path.

**UI changes:**

- Reports list shows the basename (without `.md`) as the title and the directory path on the meta line below (e.g. `2026-04-25-FART-DS-002-nightshift-report` · `App/FartownikDS/reports`).
- Selected-report header in the panel shows just the short name; full path is on the `title=` tooltip for hover.
- Read-state in `.nightshift/board-reads.json` is keyed by relative path so reports with the same basename in different sub-packages are tracked independently.

---

## 2.8.3 (2026-04-25)

### board.py — Card border color updates immediately on drag

Dragging a card to a different column now updates its `data-status` attribute on the moved DOM element, not just the JS state. The CSS border-left rule (`.card[data-status="..."] { border-left-color: var(--c-status); }`) repaints right away. Previously the card kept the old column's color until the next poll/render cycle, which made it look like the drop hadn't taken effect. Revert path also restores the old `data-status` if the API write fails.

---

## 2.8.2 (2026-04-25)

### board.py — AUTO is a toggle; drag cancels physics

`⚙ AUTO` is now a real on/off toggle:

- **Click once** → physics starts; button shows `⏸ STOP` (active state).
- **Click again** → physics halts immediately; current positions are snap-aligned (if SNAP is on), saved, and locked. Button returns to `⚙ AUTO`.
- **Drag any node while physics is running** → simulation cancels right away so the user isn't fighting it; positions are saved at that moment.
- **Stabilization completing** also auto-stops physics (the natural settle point).

Internal: `_physicsRunning` flag drives the UI state; `startAutoArrange` / `stopAutoArrange` keep `setOptions({physics: ...})` calls symmetric so vis.js never gets stuck with physics half-on. Physics is also explicitly reset on every `showGraph()` re-render so theme changes / filter toggles don't leak the running state.

---

## 2.8.1 (2026-04-25)

### board.py — Suppress graph hover tooltip during drag

vis.js can fire `hoverNode` mid-drag, which was re-showing the spec popover after `dragStart` had hidden it. Added an `_isNodeDragging` flag set in `dragStart` (when a node is involved) and cleared in `dragEnd`. The `hoverNode` handler now early-returns while the flag is set, so dragging stays uncluttered. Tooltip resumes normally after release.

---

## 2.8.0 (2026-04-25)

### board.py — Cards follow worktree status

Previously a sibling worktree's status only showed up as a 🔧 badge overlay; the card itself stayed in the column matching `main`'s status. Now the board uses the **most progressive** status across `main` + every sibling worktree as the spec's effective state:

- If main says `ready` and worktree says `in_progress` → card is in IN_PROGRESS, badge still labels which worktree.
- If main says `in_progress` and worktree says `done` (pre-merge) → card is in DONE, badge surfaces which branch.

Same logic flows through to the graph view (column placement + node color). Counts in column headers and DONE-column auto-sort all use the effective status. The 🔧 badge continues to show the divergence so you can tell apart "merged" from "pending merge".

Status precedence follows the canonical board lifecycle: `planning < draft < ready < in_progress < blocked < active < done < superseded < retired`. Worktree never *demotes* a card's status — only promotes.

---

## 2.7.5 (2026-04-25)

### board.py — Graph edge direction fix

Edges in `/api/graph` now go **prerequisite → dependent** instead of dependent → prerequisite. If `FART-DS-014` has `after: [FART-DS-019]`, the arrow now points `019 → 014` ("do 019 first, it unblocks 014") — matching how a kanban/project-flow graph is naturally read. Previously arrows pointed the other way ("014 needs 019"), which was technically a build-dependency convention but confused everyone reading it as a workflow graph.

---

## 2.7.4 (2026-04-25)

### board.py — Auto-arrange graph nodes

New `⚙ AUTO` button in the graph toolbar (next to `⟲ RESET` and `⚏ SNAP`). Click to run Barnes-Hut force-directed physics for 250 iterations starting from the **current** node positions, then freeze. Resolves overlaps, lets edges pull connected nodes toward each other, and respects `⚏ SNAP` (snaps the final positions to grid). Saved positions update so the new arrangement persists.

Distinction: `⟲ RESET` discards manual positions and re-applies the column layout. `⚙ AUTO` keeps the rough current arrangement and just settles it.

---

## 2.7.3 (2026-04-25)

### board.py — Graph: click vs drag

vis.js fires a `click` event even after a node drag completes. This made the spec detail panel pop open every time you finished dragging a node. Now we set a one-shot suppression flag in `dragStart` (when `params.nodes.length > 0`) and clear it on the next `click`. Result: drag does drag, click does click, no surprise panel.

---

## 2.7.2 (2026-04-25)

### board.py — Peek-on-hover from RECENT bar

Hovering a chip in the RECENT bar now temporarily highlights the matching card on the board (dashed `--c-theme` outline via `.card--peek`) and/or the matching node in the graph (thicker theme-colored border + soft glow via `graphNodesDataset.update`). Highlight clears on `mouseleave`. Camera, scroll, and zoom are **not** touched — if the card/node is offscreen, that's fine; the existing tooltip already shows you the spec details. Coexists with `.card--active` (open panel) so both can be visible simultaneously.

---

## 2.7.1 (2026-04-25)

### board.py — Independent graph filter; tooltip contrast

- **Graph and board now have independent visibility.** The clickable graph legend (top-right, in graph view) toggles `graphHiddenStatuses` — used only by the graph. The board's COLS dropdown still toggles `hiddenColumns` — used only by the board. Same set of statuses, two independent filters; both persisted separately in localStorage.
- **Tooltip problem text uses `var(--text)` instead of `var(--text-muted)`** for proper contrast against the popover background. Title and problem snippet now share the same color; the visual hierarchy comes from the divider line and font size.

---

## 2.7.0 (2026-04-25)

### board.py — Hover popovers, node click, theme refresh, snap

**Hover popovers everywhere.** Hovering a card on the board, a chip in the RECENT bar, or a node in the graph now shows the same styled tooltip: spec ID (in theme color) → full title → status (in its status color) → snippet of the spec's `## Problem` (or `Issue`/`Why`/`Background`/`Context`/`Description`/`Summary`/`Overview`) section. Backend `_parse_spec_file` extracts the snippet to `_problem` (capped at 280 chars, markdown bullets/quotes stripped); served via `/api/specs` so no per-hover fetch.

**Node click opens the spec detail panel.** Clicking a graph node now opens the same right slide-in detail panel as clicking a board card (full title, meta, deps, REPORTS button, full markdown body). Highlight-and-info-bar still happens too. Closing the panel returns you to the graph as it was.

**Graph re-renders on theme change.** Toggling dark/light (`☀`/`☾`) or cycling the theme color (`◉`) while the graph is open now re-runs `showGraph()` so node colors, edge colors, and label strokes update from the live CSS variables. Saved positions and snap state persist across the re-render.

**Snap-to-grid for graph nodes.** New `⚏ SNAP` toggle in the graph toolbar. When on (default), dragged nodes snap to a 35px grid on drop — visually aligned without exact pixel-pushing. Toggling SNAP on also re-snaps all currently rendered positions. Saved positions are kept on grid coordinates. State persists in localStorage.

---

## 2.6.1 (2026-04-25)

### board.py — DONE auto-sort, theme-aware nav, clickable legend filter

- **DONE column auto-sorts by completion time.** Most-recently-modified done specs appear at the top. Backend exposes file mtime via `_mtime` in the spec API; frontend sorts `done` cards by `_mtime` desc instead of using `cardOrder`. When a card is dragged into DONE, its local `_mtime` is bumped immediately so the card jumps to the top right away (no waiting for the next poll).
- **vis.js navigation buttons themed.** Replaced vis.js's hardcoded PNG sprite icons with Unicode glyphs (`↑↓←→ + − ⊡`). Buttons now use `--surface-hi`, `--border`, `--text` for resting state and `--c-theme` on hover, so they match dark/light mode and the cycled theme color.
- **Legend doubles as filter.** The graph legend (top-right) is now interactive: click a status to toggle its visibility. Hidden statuses fade to 32% opacity. The `hiddenColumns` set is shared with the board's COLS dropdown — toggle in one place, both views update.

---

## 2.6.0 (2026-04-25)

### board.py — Worktree-aware status badges

When a sibling git worktree has a spec at a different `status:` than what `main` shows (e.g. a Codex subagent in worktree branch `feat/foo` has marked `FART-DS-008` as `in_progress` but the main branch still says `ready`), the board card now displays a 🔧 badge in the theme color: `🔧 IN_PROGRESS · feat-foo`.

This surfaces in-flight work that hasn't merged back to main yet — without merging the branch.

**Backend:** new endpoint `GET /api/worktree-status` runs `git worktree list --porcelain`, walks each non-main worktree's `.nightshift/specs/` directory, and reports specs whose worktree status differs from main. Returns `{spec_id: [{branch, status, path}, ...]}`.

**Frontend:** worktree state is fetched alongside `/api/specs` on initial load and on every poll cycle. Re-renders the board on change.

**Protocol note (in `~/.claude/CLAUDE.md`):** worktree-side status changes don't propagate to the board until merge. The parent agent (on `main`) should still mark `status: in_progress` on `main` *before* spawning a worktree subagent. The 🔧 badge is ambient awareness, not a substitute for marking on `main`.

---

## 2.5.1 (2026-04-25)

### board.py — Graph polish

- **Free-axis drag.** Dropped the per-axis `fixed: { x: true, y: false }` lock that prevented horizontal dragging. Physics is now disabled entirely so the column layout is the deterministic *initial placement*; you can drag any node anywhere from there.
- **Empty status columns skipped.** Only statuses that actually have nodes get a column slot — no more huge empty gap between READY and DONE when nothing else has work.
- **Column spacing widened** (260px between columns, 70px between rows) and **vertically centered** around origin.
- **Legend & info panel theme-aware.** Background now uses `var(--surface-hi)` instead of hardcoded `rgba(20,20,20,0.9)`; correct in both dark and light modes.
- **Legend moved to top-right** so it doesn't conflict with vis.js's bottom-left navigation buttons. The selected-node info bar now floats at top-center.
- **Initial fit works without physics.** Switched from `stabilizationIterationsDone` (which doesn't fire when physics is off) to `afterDrawing` for the first-frame fit.

---

## 2.5.0 (2026-04-25)

### board.py — Graph view rework

**Root-cause fix:** vis.js was rendering canvas elements that could escape the `#graph-container` flex bounds, leaving the graph invisible (worst case: dense graphs in light mode). Added explicit CSS constraints (`#graph-container > div`, `#graph-container canvas` forced to `100%/100%`) plus `position: relative; overflow: hidden; min-height: 0` on the container itself.

**Theme-aware colors:** Node, edge, label, and highlight colors are now read live from CSS variables (`--c-draft`, `--c-ready`, ..., `--text`, `--text-muted`, `--c-theme`) at graph render time. Light and dark mode both look correct; cycling the theme color affects the graph too. Labels get a stroke matching `--surface` for readability against any node fill.

**Column layout:** By default, graph nodes are positioned in vertical columns matching the board's status order (DRAFT → READY → IN_PROGRESS → BLOCKED → ONGOING → DONE → SUPERSEDED). X is locked per status; Y is seeded from `cardOrder` (so the visual order in a graph column reflects the order on the board) and adjusted by Barnes-Hut physics.

**Drag-to-persist:** Drag any node and its position is saved to localStorage. On next load, that node stays where you put it (both axes locked). All other nodes still follow the column layout.

**Nav controls:** vis.js's `navigationButtons` are now enabled — zoom, pan, fit. Keyboard arrows pan, +/- zoom (when graph has focus).

**Column visibility filter:** Hiding a column on the board (via the COLS dropdown) now also hides those nodes (and their edges) from the graph view. One control, both views.

**RESET button:** New `⟲ RESET` button in the graph toolbar clears all saved node positions and re-applies the default column layout.

---

## 2.4.6 (2026-04-25)

### board.py — Fix: graph view — switch to force-directed layout

The previous LR hierarchical layout broke on dense graphs (e.g. Fartownik: 20+ specs all depending on DS-001/002/003). vis.js cannot produce a valid hierarchical layout when many nodes share the same parents — it collapses them to overlapping positions or renders nothing visible.

Switched to Barnes-Hut force-directed layout (`improvedLayout: true`), which handles arbitrary dependency density. `stabilization.fit: true` + explicit `network.fit()` after stabilization ensures the graph always fills the view on open.

---

## 2.4.5 (2026-04-25)

### board.py — Fix: graph view empty on open

`network.fit()` is now called after stabilization completes when no specific node is being highlighted. Previously the graph rendered but placed nodes outside the visible viewport (double-click was needed to fit). Now the graph automatically fits to show all nodes on first open.

---

## 2.4.4 (2026-04-25)

### board.py — Recent bar hover tooltip

Hovering a chip in the RECENT bar now shows a styled tooltip with the full spec title, ID, and status (in its status color). The native browser `title` attribute has been removed. Tooltip positions above the chip and flips below if near the top of the screen.

---

## 2.4.3 (2026-04-25)

### board.py — Resizable detail panel

The spec detail panel can now be resized by dragging its left edge. The handle lights up in the theme color on hover. Width is constrained between 280px and 85% of viewport. Setting persists in localStorage and is restored on next visit.

---

## 2.4.2 (2026-04-25)

### board.py — Reports panel + card order persistence

**Reports panel:** Human review reports (`.nightshift/reports/*.md`) are now surfaced directly in the board. Open any spec's detail panel and click `📋 REPORTS (N unread)` to browse reports. Reports open in a slide-in sub-view within the same panel with ●/○ read/unread indicators. Click a report to read it with full markdown rendering; click `✓ MARK READ` to mark it. Read state is stored in `.nightshift/board-reads.json` (atomically written). Back navigation returns you to the report list or spec detail.

**Card order persistence:** Dragging specs within a column (reordering) now persists across restarts. Order is stored in localStorage under the board's port key. New specs that haven't been manually ordered appear at the bottom of their column. Cross-column drops also preserve the target column's order.

---

## 2.4.1 (2026-04-25)

### board.py — auto-poll

Board tab now polls `/api/specs` every 10 seconds automatically. Only fires
when the board tab is active and no search is in progress. Re-renders only
if a spec's status or count actually changed — silent no-op otherwise. Open
detail panels and active card highlights are preserved across polls.

---

## 2.4.0 (2026-04-25)

### Local Web Kanban Board (`board.py`)

New `canonical/board.py` — a single-file FastAPI server that serves a local Kanban
board for Nightshift specs at `http://localhost:7842`.

**Features:**
- Terminal Noir theme (dark, monospace, neon status accents)
- Seven status columns: DRAFT → READY → IN_PROGRESS → BLOCKED → ONGOING → DONE → SUPERSEDED
- Drag-and-drop status updates (SortableJS); changes write to spec files atomically
- mtime-keyed two-tier cache: Tier 1 (frontmatter, always in memory), Tier 2 (body, lazy)
  — cannot serve stale data; automatically picks up external file changes
- Search: debounced, in-memory after body warm, no cache staleness risk
- Detail panel: full markdown render (Marked.js), dependency chips with jump-to
- Dependency graph tab: Vis.js network, click-to-highlight connections
- `[⌥ DEPS]` toggle: dep badges on cards + click-to-graph navigation
- `--port`, `--open`, `--specs` CLI flags

**Sync:** `board.py` added to `CANONICAL_PROTOCOL_FILES` — deploy with
`python nightshift-sync.py canonical --apply`.

**Launch:**
```bash
.nightshift/board.sh                          # auto-opens browser, hash port
.nightshift/board.sh --port 8080              # override port
python .nightshift/board.py --specs ./plans/specs/  # test against any spec dir
```

**Hash-based port:** `board.py` derives a deterministic port from the project name
(`7800 + sum(ord(c) for c in project_name) % 200`). Each project always gets the
same port — safe to run multiple boards in parallel and easy to bookmark.

**Sync:** `board.sh` added to `CANONICAL_PROTOCOL_FILES` alongside `board.py`.

---

## 2.3.0 (2026-04-17)

### Karpathy Coding Principles — agent prompts v2 + spec template v5

Direct adoption of Andrej Karpathy's four LLM-coding principles (Think Before Coding · Simplicity First · Surgical Changes · Goal-Driven Execution), sourced from `forrestchang/andrej-karpathy-skills`. Applied to both Argo's global protocol surface and Nightshift's agent prompt chain.

**Changes to canonical/:**

- `prompts/implementation_v2.md`, `prompts/test_planning_v2.md`, `prompts/review_v2.md`, `prompts/validation_v2.md` — new Karpathy-aware versions of each agent phase prompt. Each extends the v1 body with principle-targeted guidance appropriate to that phase:
  - **implementation_v2** — Simplicity First + Surgical Changes + Think Before Coding; rejects speculative abstractions, "improvements" outside spec scope, silent assumption-picking.
  - **test_planning_v2** — Goal-Driven Execution; every AC becomes a failing-then-passing test; vague ACs get pushed back to the author, not invented around.
  - **review_v2** — Surgical Changes enforcement with a concrete blocklist (quote-style drift, out-of-scope docstrings, whitespace reflows) + Simplicity First senior-engineer test + Goal-Driven verification (every AC maps to a passing test).
  - **validation_v2** — Goal-Driven verification with strict evidence rules; "tests pass" alone is not proof; Live Execution Checklist items require their own evidence.
- `prompts/_registry.yaml` — v2 activated for all four phases; v1 kept as `experimental` for A/B comparison.
- `specs/_TEMPLATE.md` — bumped to v5 with optional `karpathy_checklist: [think|simple|surgical|goal]` frontmatter field. Empty means the global defaults apply; populated signals extra emphasis for agents running v2+ prompts (e.g., `[surgical]` on a bugfix spec where drive-by refactoring is the primary risk).

**Changes to Argo startup surface (outside canonical/, listed for traceability):**

- `~/.claude/CLAUDE.md` — new `## Karpathy Coding Principles` section after Defaults.
- `Argo/session.md` — one-line reference in Defaults.

**Migration:** No action required for existing v4 specs — `karpathy_checklist` is optional. Agents on the next run automatically use the v2 prompts. v1 prompts remain in `prompts/` for comparison; set `_registry.yaml` → `active:` back to `*_v1.md` to revert per-phase.

### Accumulated audit follow-up (prior work, bundled into 2.3.0)

The 2.2.1 → 2.3.0 bump also bundles canonical changes landed since 2026-04-10 that had not yet been versioned:

- **SPEC-040..048** (2026-04-16 audit follow-up): execution history DB wired into LOOP Step 16, handler registry wired into Step 2, outcome router into Step 11 with policies/backoff/ESCALATE action, `nsm.py` multi-root config, `IMPROVEMENTS.md` extractor fix, `config.yaml v3.0.0` + `--migrate-config`, `prior_attempts` enforcement gate, metrics timestamp validation.
- **SPEC-026/027/028** (Multi-stack Phase 3, 2026-04-17): cross-stack integration gate, output artifact verification, research synthesis gate.

These were already merged to canonical; 2.3.0 is the first version that captures them in the changelog.

---

## 2.2.1 (2026-04-10)

### Fix: Human review report now enforced in LOOP.md

Step 14 (Report Generation) was softly worded and skipped by agents.
Step 16 (Loop exit) had no gate on report existence.

**Changes:**
- Step 14: added `MANDATORY` header, self-verification step (confirm file exists before proceeding to Step 15), updated Why to clarify the report is the primary deliverable
- Step 16: added exit gate — loop cannot exit without `reports/YYYY-MM-DD-nightshift-report.md` present and non-empty; if missing, returns to Step 14
- `Skills/nightshift/SKILL.md`: brief boilerplate now includes explicit MANDATORY report instruction; post-run review blocks merge until report is confirmed

### Fix: Attempts write gap — `knowledge/attempts/` now has write triggers

`knowledge/attempts/` existed in every project but was never written to. The read side (Step 3) was wired; the write side was not.

**Changes:**
- LOOP.md implementation debug discipline (~line 712): "If 3+ fix attempts fail" now explicitly instructs writing `knowledge/attempts/<spec-id>-<description>.md` before triggering the circuit breaker
- LOOP.md Step 12 pattern decision Q3 ("Did I iterate through 3+ approaches?"): now explicitly instructs writing attempt records for each failed approach in `knowledge/attempts/`, with cross-reference from the pattern file
- `canonical/knowledge/attempts/_TEMPLATE.md`: reconciled format — YAML frontmatter with `spec_id`, `problem_area`, `date`, `status`, `approach`, `model_used`, `phase`, `error_type`; sections now match LOOP.md stall section (`What Was Tried`, `Why It Failed`, `What We Learned`, `Revisit If`, `Related Patterns`); added filled-in example

**Migration:** No config changes. Runs on 2.2.0 projects automatically on next sync.

---

## 2.2.0 (2026-03-30)

### New: Pre-Commit Hook

`hooks/pre-commit` is now part of the canonical kit and synced to every project
by `nightshift-sync.py`. The hook reads `lint` and `type_check` commands from
`config.yaml` and runs them before every `git commit`, rejecting commits that
fail — regardless of which agent or harness is running.

**Files changed:** `hooks/pre-commit` (new), `nightshift-sync.py`

**What's new:**
- `hooks/pre-commit` — shell script: reads `commands.lint` and `commands.type_check`
  from `config.yaml`, runs them, exits non-zero on failure
- `nightshift-sync.py` — canonical sync now includes `hooks/` directory sync
  (always-overwrite, executable bit preserved). Hooks were previously documented
  in `BOOTSTRAP.md` but never shipped with the kit.

**Migration (2.1.0 → 2.2.0):**

```bash
# Install the hook into your project's git:
cp .nightshift/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The hook is inert until `lint` and/or `type_check` are set in `config.yaml`.
No config changes required — just install and go.

---

## 2.1.0 (2026-03-30)

### New: DevKB Injection System

External Development Knowledge Base (DevKB) can now be loaded into every Nightshift
run automatically. DevKB contains cross-project lessons per technology — agents no
longer need to rediscover known fixes.

**Files changed:** `config.yaml`, `BOOTSTRAP.md`, `LOOP.md`

**What's new:**
- `config.yaml` — new `devkb` section: `path`, `writeback`, `mappings`, `always_include`
- `BOOTSTRAP.md` — Phase B8 (interactive DevKB config), Phase E1a (DevKB loading at bootstrap)
- `LOOP.md` — Step 3a (DevKB loading per loop iteration), Step 12.5 (DevKB writeback staging)
- `nightshift-sync.py` — new script: ingests DevKB proposals + syncs canonical protocol files

### New: Spec Status Lifecycle

Specs now have their `status:` frontmatter explicitly updated at each lifecycle stage.
Previously, specs were never marked `in_progress` or `done` — only `blocked` was set.

**Files changed:** `LOOP.md`, `ORCHESTRATOR.md`

**What's new:**
- `LOOP.md` Step 2 — marks selected spec as `status: in_progress` + commit
- `LOOP.md` Step 12.7 — marks completed spec as `status: done` + commit (MANDATORY)
- `ORCHESTRATOR.md` Step b — marks spec `in_progress` on main before launching sub-agent
- `ORCHESTRATOR.md` Post-merge — verifies `status: done`, sets it if sub-agent forgot
- `ORCHESTRATOR.md` Failure handling — records failed/blocked/discarded outcomes in metrics/reports and uses canonical frontmatter lifecycle statuses

### New: nightshift-sync.py

Bidirectional sync tool for all Nightshift projects:
1. **DevKB Ingest** — collects proposals from `.nightshift/knowledge/devkb-updates/`, deduplicates, appends to canonical DevKB, removes processed proposals
2. **Canonical Sync** — pushes protocol files from `canonical/` to all `.nightshift/` directories

**Location:** `ManagedProjects/Nightshift/nightshift-sync.py`

### Migration from 2.0.0

1. **config.yaml** — add the `devkb` section (optional, leave `path: ""` to disable):
   ```yaml
   devkb:
     path: ""
     writeback: true
     mappings: {}
     always_include: []
   ```
   Also bump:
   ```yaml
   kit_version: "2.1.0"
   ```
   And in `runtime:`:
   ```yaml
   loop_version: "2026-03-30"
   ```

2. **LOOP.md / BOOTSTRAP.md / ORCHESTRATOR.md** — run `nightshift-sync.py canonical`
   to push updated protocol files to all projects. Or wait for the scheduled task (daily 7 AM).

3. **Existing specs** — any specs currently `status: ready` that were already completed
   by a previous run should be manually set to `status: done`. Check metrics files to
   confirm which specs were actually completed.

4. **DevKB setup** (optional) — if you want DevKB injection, set `devkb.path` in each
   project's config.yaml and define `devkb.mappings` for the project's languages.

5. **No breaking changes.** All existing config.yaml files work without modification.
   The new `devkb` section is optional and defaults to disabled.

---

## 2.0.0 (2026-03-23)

### Breaking: Hierarchical Specs

Specs can now be organized in parent-child hierarchies with NFR (Non-Functional
Requirement) constraints.

**Files changed:** `config.yaml`, `LOOP.md`, `ORCHESTRATOR.md`, `nightshift-dag.py`

**What's new:**
- Spec frontmatter: `type: main`, `type: nfr`, `parent:`, `children:`, `implementation_order:`, `violates:`
- `nightshift-dag.py` — DAG engine for dependency analysis and execution plan generation
- `ORCHESTRATOR.md` — §2.1a (pre-computed plan check), §2.1b (main spec detection), §3.x (NFR injection)
- `LOOP.md` — Task Selection excludes `type: main` and `type: nfr` specs

### Breaking: Metrics Schema v1.0

Structured YAML metrics with enforced schema. Previous freeform metrics are no longer accepted.

**Files changed:** `metrics/_SCHEMA.md`, `validate_metrics.py`

### Migration from 1.x

1. **Specs** — existing specs keep working. New `type:` values (`main`, `nfr`) are optional.
   Specs without `type:` default to `feature`.
2. **Metrics** — all metrics YAML must now conform to `_SCHEMA.md`. Run `validate_metrics.py`
   to check existing files.
3. **config.yaml** — add `kit_version: "2.0.0"` at the top level.
4. **nightshift-dag.py** — copy to `.nightshift/` if using hierarchical specs.

---

## 1.0.0 (2026-03-16)

Initial release of Nightshift Kit.

- 16-step autonomous execution loop (LOOP.md)
- 5-phase bootstrap (BOOTSTRAP.md)
- Orchestrator for multi-spec delegation (ORCHESTRATOR.md)
- 6-persona review system (REVIEW.md)
- Knowledge patterns (knowledge/patterns/)
- Circuit breaker (stall detection)
- Crash recovery (checkpoints)
- Watcher (parallel review agent)
- Pre-commit hook generation
- Metrics collection (per-spec YAML)
