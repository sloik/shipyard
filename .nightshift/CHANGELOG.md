# Nightshift Kit — Changelog & Migration Guide

> **Versioning:** SemVer (`kit_version` in config.yaml).
> - **Major** — breaking changes to protocol, config schema, or metrics schema
> - **Minor** — new features, new config sections, new protocol steps (backward-compatible)
> - **Patch** — bug fixes, wording clarifications, no config/protocol changes
>
> **Rule:** Every change to canonical files MUST bump `kit_version` and add an entry here.
> The `runtime.loop_version` field (date-based) tracks when the LOOP.md was last touched
> and is used for metrics comparison — it is NOT the authoritative version.

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
- `ORCHESTRATOR.md` Failure handling — marks failed/blocked/discarded specs in frontmatter

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
