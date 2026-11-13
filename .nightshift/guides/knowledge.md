Load when: you run `/nightshift knowledge` (`add`, `update`, `review`, `import`): managing the project's knowledge base.
Covers: the four knowledge subcommands, the entry format and the review-persona ownership rules.
Not here: defining requirements for a feature (`/nightshift spec`), install checks (`/nightshift validate`).
Requires: an installed project with a `knowledge/` directory.

# Knowledge guide

### `add <topic>`
Guided creation of a new knowledge/ file. Ask what the topic covers, what patterns or lessons to capture, and which review persona (if any) owns it.

### `update <file>`
Read existing entry, ask what changed, update it.

### `review`
Check all entries for staleness — if specs have been completed since the knowledge file was last updated, flag it. Suggest updates based on recent reports.

### `import`
Read recent Nightshift reports and metrics. Extract lessons (what failed, what worked, what patterns emerged) and add them to knowledge/ entries or create new ones.

### `import --devkb` — DevKB updates promotion sweep (SPEC-352)

Distinct from the report/metrics `import` above: this sweeps the
`devkb-updates/` **staging area** — the files agents write per LOOP.md §1770
when `devkb.writeback: true` — and promotes them into the external, cross-project
DevKB (`devkb.path` in `config.yaml`), rather than into this project's local
`knowledge/` directory.

**Why a separate step exists:** the staging contract (BOOTSTRAP.md §B8/E1a,
LOOP.md §1770/§1805) always described this as "reviewed and merged... by a
human or scheduled task (outside the loop)" — but that scheduled task never
existed, so nothing staged there was ever promoted. `canonical/devkb_sweep.py`
is that task.

**Run on demand:**

```bash
python3 canonical/devkb_sweep.py sweep \
  --devkb <path-to-DevKB-dir> \
  --source canonical/knowledge/devkb-updates \
  [--source <fleet-project>/.nightshift/knowledge/devkb-updates ...] \
  [--apply] [--json]
```

- Without `--apply`: decision-only. Every staged file is parsed, its target
  DevKB file/section resolved, and a decision recorded in the ledger
  (`<source>/.sweep-ledger.json`): `auto_merge` (no existing heading collision
  — safe to land) or `needs_review` (a heading with the same title already
  exists in the target file — never auto-applied; surfaced for a human
  accept/reject/edit call, and recorded `rejected` with a reason until one is
  made).
- With `--apply`: `auto_merge` decisions are actually appended to
  `<devkb>/<target-file>.md`, `<devkb>/INDEX.md` is updated if it tracks
  section-level entries, and the staged file is moved to a `merged/`
  subdirectory next to its source. Re-running is idempotent — the ledger is
  keyed by content hash, so an already-decided file (merged OR rejected) is
  never re-surfaced or re-merged.
- Writing into an out-of-repo DevKB checkout from an isolated Nightshift
  worktree run is itself a cross-repo write; treat it the same way
  `SPEC-241`'s own staged lesson prescribes — do not attempt it silently from
  a run whose declared write scope doesn't cover that path. Decide the
  backlog (no `--apply`, or `--apply` targeting a path the run is actually
  scoped to write) and hand the real DevKB write to the operator/actor that
  owns that checkout.

**Run periodically (R4):** since "a human remembers to run it" is the exact
failure mode this closes, schedule `devkb_sweep.py sweep --apply` (with a real
`--devkb` path the runner is scoped to write) as a recurring task — e.g. a
cron/launchd job or a step at the start of `/nightshift run`'s Phase A
re-entry check, whichever the fleet operator's scheduling story already uses.
On-demand invocation (above) remains valid at any time; the periodic run is
additive, not a replacement.


## Observational helper capture (SPEC-NS-KIT-168)

At every ordinary handoff/report closure, always request newly authored helper metadata.
Consult supported APIs, classify available helpers and hand the explicit list to the parent.
The parent alone calls `run_tooling.capture_best_effort` (or `run_tooling.py capture`);
capture is metadata/digests only and never delays correctness, recovery, Done or cleanup.
Use `not_reported` without a reliable list; `none_authored` requires an explicit declaration.
No temporary-root scan, source execution/copy, forced suite or historical census. Raw snapshots
need separate owner approval. Review records one of generic_candidate, project_local,
experiment, existing_supported or defect_adapter; single-context generic potential stays proposed.
Eligibility requires hash-bound second-context evidence and owner/capability/privacy/check/scope
fields with no material open choice. A recommendation grants no execution, installation or release.


For data-only use, call `run_tooling.py capture --reports-root <reports> --project <code>
--spec-id <ID> --run-id <run> --source-root <explicit-root> --input <private-metadata.json>`.
The explicit candidate list has candidate_id, logical locator and category (closure, scope,
brief, monitoring, recovery, fixture, experiment, other); optional source is relative to the
explicit source root and never retained. Missing/inaccessible sources remain unknown.
Use bounded symbolic labels for portable rationale, API comparison and capability fields;
never paste commands, prompts, personal content, credentials or source. `review` takes
candidate_id/disposition/comparison/rationale/contexts; `list` reads indexed run versions.
An eligible review supplies owner_project/owner_spec, boundary inputs/outputs/side_effects/
dependencies/compatibility, privacy=metadata_only, checks, write_surface and empty
unresolved_decisions. Each context has project/evidence/sha256; evidence is a safe relative
file under the reports root, independently retained before the eligibility decision.
For an accepted opportunity use `review` input {"proposal": {"candidate_id": "<id>",
"specs_dir": "<owned-specs>", "title": "<bounded title>", "dry_run": true}}.
The supported follow-up gate routes duplicates to existing IDs; clean proposals retain a
separate draft plus authored decision artifact with backlinks, without reserving the ID.
Only explicit dry_run=false authors that separate Draft using the existing author-decision
API. Review active NFR/release obligations before promotion; no sampled raw helper is promoted.
The sole parent writer validates a complete batch before publishing one indexed snapshot;
repeat digest/run capture and identical review reuse records; changed bytes link a new version.

Optional source_project/source_spec/source_run preserve a helper's actual origin when its
review belongs to another spec. Unknown historical run/availability stays not_reported.
Version identity binds the predecessor, so reverting bytes preserves an unambiguous chain.
