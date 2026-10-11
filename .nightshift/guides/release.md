Load when: you run `/nightshift release`: publishing and rolling out one exact canonical kit to the fleet.
Covers: Steps 1-5 of the release flow (canonical preflight, fleet dry-run, apply, verification, report) with the exact commands and the release-policy block.
Not here: implementing a spec (`/nightshift run`), file-only sync (never valid for a release), install soundness (`/nightshift validate`).
Requires: the canonical Nightshift repository checkout, `release.py`, `release_coordinator.py`, and `release-manifest.json`.

# Release guide

### Release roles

1. One owner runs every canonical-suite and formal-lane job for a release; the `--apply` preflight counts as
   that owner's run. No second suite, and no other heavy job, runs in the same checkout while a measured suite
   is running (issues log C8: two runs of one suite killed each other; C5: a timing test failed under load).
2. Decide parallel runs before the release agent is launched, and give each run its own output name (C6: a
   second formal run overwrote the first's output).
3. Run long suites in the background and poll them, so that coordinator instructions arrive between tool
   calls (C8: a redirect went unread while the agent sat in a foreground suite).
4. Commit only in the named commit steps of this guide; diagnose with read-only commands (C7: a diagnostic
   commit had to be amended into the cut).
5. A release-spec AC that depends on the cut (fingerprint, CHANGELOG count, version) reads "the value at the
   cut" plus the command that checks it, never a literal recorded earlier (A6: literals went stale).

### Step 0: Dirty-tree audit and checkpoints

1. A few days before the release run `python3 release_coordinator.py --root <root> --checkpoint-plan`
   (read-only; prints JSON, writes nothing). Per repository it gives the dirty path count, the paths a
   checkpoint may commit, the excluded paths (`private_artifact`, `generated_registry`, `spec_wrong_home`) and
   the dry-run classification. Send each owner their repository's list.
2. On release day run the dry-run first.
3. Checkpoint only the plan's commit list per repository: `git commit -- <paths>`, through that repository's
   own hooks. Escalation sign-off for a bulk checkpoint belongs to this step.
4. Finish with a second dry-run.

### Step 1: Canonical preflight

1. Read the canonical version, newest changelog entry, sync-managed file list and
   `release-manifest.json`.
2. Regenerate the manifest from the current complete managed list.
3. Run manifest validation. Version/changelog/manifest parity, exact file
   coverage, hashes, executable modes, schema metadata and declared smoke checks
   must all pass. Apply is closed on any error.
4. Precompute every repository's canonical-payload, configuration-migration,
   staging, and commit allowlists before the first project write. Manifest files
   plus the release marker are canonical-owned replaceable payload;
   `config.yaml`, migration outputs, generated `metrics/*.yaml`, specs,
   knowledge, registries, run evidence, and application code are project-owned.
   Any overlap between those sets fails closed before mutation.
5. Run the release-metadata capability probe, then the canonical Nightshift
   suite exactly once through the same declared dependency-capable environment.
   Never substitute ambient `python3`. Do not proceed to fleet mutation unless
   the probe and suite are green.

The apply preflight's own gates, in order: finding-family floor and suite headroom on the
last recorded run (both also reported by `--dry-run`), probe, full suite, headroom on the run
just recorded. Do not repeat them in a release spec; `python3 release.py finding-floor` runs the floor alone.

Reuse (SPEC-NS-KIT-126): instead of the full suite, the apply runs `RELEASE_MECHANICAL_TESTS` when the newest
suite record passed, is under 24 hours old, was clean at both ends, the canonical tree is clean and every path
changed since its commit is in `RELEASE_MECHANICAL_PATHS` (version-bearing files: version lines only). Any other
case runs the full suite. The result shows `canonical_suite_result: reused`, `canonical_suite_reused_from` and the subset outcome.

### Step 2: Fleet dry-run

Each project's `.nightshift/config.yaml` must declare:

```yaml
release_policy:
  committed_kit: allow  # or: opt_out
```

`allow` keeps the existing guarded local-commit path. `opt_out` is a known
project-local skip: the coordinator leaves that whole repository untouched and
continues independent repositories. `release_coordinator.py` reads
`committed_kit` only and never delivers a partial manifest — a release is
always the whole managed kit or nothing for a given repository.

An install may additionally narrow what the separate, non-sealing
`nightshift-sync.py canonical` sweep delivers, independent of `committed_kit`
(SPEC-356):

```yaml
release_policy:
  committed_kit: allow  # or: opt_out
  sync_files:            # optional; nightshift-sync.py honours this, release_coordinator.py never reads it
    include: ["board.py", "validate_specs.py"]  # only from the managed set; the only widening operator
    exclude: ["Skills/nightshift/SKILL.md"]       # subtracted after include; never widens
```

`nightshift-sync.py canonical` honours `sync_files`: an install whose resolved
selection is a strict subset of the managed set is narrowed, receiving only
the selected files (with `kit_version`, seed files, hooks/, templates and the
metrics schema all suppressed). `release_coordinator.py` never reads
`sync_files` and never delivers a partial manifest under any declaration.
Commit hooks that own a compatible explicit `committed_kit` policy may expose
it with an executable commit-hook marker:

```sh
# nightshift-release-policy: committed-kit=opt_out
```

The dry-run reconciles declarations with markers in applicable `pre-commit`,
`prepare-commit-msg` and `commit-msg` hooks. A mismatch reports both the config
and hook sources before copying or staging. An unmarked hook failure remains
unexpected and retains the stop/no-push/no-rollback semantics below.

Run:

```bash
python3 canonical/release_coordinator.py \
  --root /Users/ed/Dropbox/Argo \
  --dry-run
```

Rehearsals and tests against a disposable root add `--isolated-root`, which scans `--root` alone; without
it discovery also covers the real fleet scan roots. The result's `discovery` lists the roots scanned.

Commit-msg hook refresh (SPEC-NS-KIT-143): before each release commit the coordinator refreshes a recognised kit
`.git/hooks/commit-msg` (header `Nightshift Kit — Commit message hook`; never creates or overwrites a project-owned
hook), keeping the old bytes in `commit-msg.nightshift-prev`. It first replays the repository's commits authored in the
last 30 days (at most 500, no merges) through the new hook; if any would be newly rejected the refresh is deferred and the
release continues. The dry-run prints the per-repository outcome (`would refresh`, `would defer (N would be rejected: ...)`,
`project_owned`, `absent`, `unchanged`; JSON `commit_msg_hooks`). A project clears a deferral by writing `chore: mark <ID> done|blocked|in_progress`
and terminal commits with `record_metrics.py --commit-terminal`; once the window holds no rejected message the next release
refreshes it. `--refresh-commit-msg-hooks auto|force|never` (default `auto`) overrides: `force` refreshes despite rejects, `never` skips the step.

Review exact repository/install coverage. Divergence inside the exact manifest
payload is expected and never needs provenance reconstruction: release replaces
those files deterministically. An unrelated pre-staged path or dirty
project-owned migration path skips that whole repository. Do not clean, stash,
overwrite, or stage project-owned work to make a repository eligible.

Review the fleet validation table the dry-run prints (stderr; `fleet_validation` in the
result): one row per install with its installed-profile verdict, failed invariant
codes and duration, read-only and in process. `fixed_by_release` failures (`KIT.MARKER`,
`KIT.PAYLOAD`, `CFG.PARSE_VERSION`) are cleared by the sync. Fix every `pre_existing` DENY
(identity, test command, hooks) in that install before the apply.

### Step 3: Plan configuration migrations

For every install below the manifest's required config schema, prepare one fresh
code-writing subagent in an isolated worktree. Bound concurrency to at most four
workers and give each worker only:

- that one install and its old/required schemas;
- the registered deterministic migration — `canonical/config_migrations.py`'s
  `MIGRATIONS` registry, keyed by target `schema_version`
  (`release_coordinator.default_migration_runner` is the reference caller: it
  reads the install's `config.yaml`, applies `config_migrations.migrate()`, and
  returns the result unmodified — a worker's transformation of `config.yaml`
  must match that function's output exactly, never a freeform edit);
- `config.yaml` plus the declared `.migrations/` output allowlist;
- manifest fingerprint, relevant DevKB and migration validation commands.

The worker may not copy canonical payload, commit, push, merge, alter spec lifecycle, or touch paths
outside its allowlist. The coordinator validates each result before integration.

For an install with no per-install customization to reconcile, the coordinator
may be run with `--migration-runner reference` (BUG-326): it applies
`release_coordinator.default_migration_runner` — the exact function a worker
must reproduce byte-for-byte — inside the same guarded run, and the migration
is staged and committed with the payload. The default (`worker`) keeps today's
behaviour: a fresh worker is required and the repository is skipped without one.
One failed/breaching migration skips its whole repository but does not stop
independent repositories. Multiple installs in one repository still produce at
most one coordinator-owned commit.

### Step 4: Guarded apply

Only after Steps 1–3 are green, run the coordinator with `--apply`. The
coordinator:

- copies and verifies the complete managed set and writes the exact release
  marker last;
- applies the separately validated configuration migration for that install
  only after its canonical payload copy succeeds;
- reconciles the install's project-owned `kit_version` to the release
  (BUG-326: `config_migrations.set_kit_version`, one quoted value, no other
  byte) and reports it under `config_kit_version_updates`; without this every
  delivered install fails admission on `CFG.PARSE_VERSION` and `KIT.MARKER`
  the moment the release lands;
- installs the kit's own `hooks/pre-commit` into the repository's hooks dir
  when **no** pre-commit hook exists (the documented BOOTSTRAP.md copy), and
  reports it under `hooks_wired`; an existing hook is never overwritten or
  merged, only reported as `kept-existing`;
- runs only manifest-declared install smoke checks unless release metadata names
  a specific application integration risk;
- stages only release-managed paths, verified config migrations and markers;
- proves the staged and committed path sets are allowlisted;
- excludes registries, specs, generated metrics, knowledge and application
  code while admitting the exact canonical `metrics/_SCHEMA.md` artifact;
- creates at most one local commit per fully verified repository, with release
  version/fingerprint/install-count trailers;
- never pushes.

Do not manually reproduce or bypass these commit guards.

### Step 5: Failure semantics and report

Known dirty/migration failures skip the entire repository, continue independent
repositories and make the command exit nonzero. An unexpected coordinator,
verification, smoke or commit failure stops all later work immediately. Keep
already completed local commits, leave untouched repositories on their prior
exact release, and never roll back automatically.

The exit status and the result's `outcome` field (dry-run and apply alike) tell the kinds of run apart:

| Exit | `outcome` | Meaning |
| --- | --- | --- |
| 0 | `completed` | No skips, no failure. |
| 3 | `completed_with_skips` | Known skips only; `failure_class` and `unexpected_failure` are null. |
| 1 | `failed` | Any `failure_class` or `unexpected_failure`, with or without skips. |
| 2 | (no result) | Invalid release manifest. |

If a prior apply stopped after copying or staging, rerun the same exact release.
Canonical payload replacement is idempotent, and the coordinator re-verifies
the marker, staged allowlist, and project-owned configuration boundary before it
commits. Never infer that an install is synchronized from a partial copy.

The coordinator result lists `release_handoffs_uncommitted`: the handoff files it repinned or completed that git does not show clean. Commit them with the release report before the release closes.

Write the final report and structured metrics with:

- planned, verified, skipped and untouched installs/repositories;
- old/new fingerprints and producer-session payload hashes;
- known versus unexpected failure classification;
- migration worker evidence and local commit IDs;
- canonical-suite/smoke counts, duration and observable post-commit rebuild time;
- `post_sync_validation`: the installed-profile verdict per verified install (recorded, never a stop trigger);
- the exact safe rerun command.

The operator decides separately when/if local commits are pushed.
