---
name: nightshift
version: 3.26.3
description: "Interactive companion for the Nightshift Kit autonomous dev loop. Use this skill whenever the user mentions nightshift, night shift, autonomous dev loop, creating specs, bootstrapping a dev loop, retrofitting a project with nightshift, spec drift, spec sync, or anything related to setting up or managing an autonomous code execution pipeline. Also triggers on: 'write a spec', 'create a spec', 'add nightshift', 'check specs', 'spec drift', 'nightshift config', 'nightshift status', 'nightshift validate', 'nightshift board', 'board api', 'spec status transition', 'search specs', 'check rules'. If the user is working with .nightshift/ folders, specs/ directories, config.yaml for dev loops, or mentions LOOP.md / BOOTSTRAP.md / ORCHESTRATOR.md, use this skill."
---

# Nightshift Kit Skill

For inline run and kickoff, explicit canonical-source authoring uses GIT.md's
receipt-bound SPEC-365 contract. The parent alone injects `authoring_provider`
into the existing result-acceptance seam, separately from worker packets. Retain
the original receipt and strict result; require external authorization and an
independently validated verdict binding the exact candidate before bootstrap.
Missing proof stops acceptance, lifecycle, merge and cleanup. Installed copies
stay strict; the sole serialized queue, fresh-main suite and pending release
handoff remain required. Never regenerate admission to authorize changed bytes.

The canonical kit's own test suite runs in parallel through pytest-xdist, capped at 4
workers by default. To lower the worker count for one run, set
`PYTEST_XDIST_AUTO_NUM_WORKERS=<n>` (the cap cannot be raised through it).

The interactive companion for the Nightshift Kit — an autonomous dev loop that reads specs, writes tests, implements code, reviews its own work, and commits results. This skill handles everything humans do *around* the loop: setting it up, writing specs, maintaining the knowledge base, and keeping specs aligned with reality.

Private Dropbox observability is opt-in only: set `observability.sink: private-dropbox`
and provide `NIGHTSHIFT_DROPBOX_ROOT` privately at runtime. Never place paths,
URLs, credentials, raw logs, prompts, commands, or environment values in public
configuration or reports. If Dropbox is unavailable, preserve the run outcome and
use the sealed `NIGHTSHIFT_OUTBOX_ROOT` fallback for later reconciliation.

For registered public projects, audit tracked Nightshift artifacts with
`observability_enroll.py audit` before a release. Migration copies and
hash-verifies private artifacts before an operator-approved future-index
cleanup. It never rewrites history; history remediation remains a separate,
explicit dry-run-first operator action.

For future real-use questions, preregister a falsifiable adoption, effectiveness,
or reliability hypothesis and collect closed privacy-safe events at normal
workflow boundaries. A source spec may close with unchecked live items only when
`real_use_evidence.policy: delegated_experiment` maps every item exactly once to a
valid descriptor, finished instrumentation spec, and SPEC-236 lineage record.
Never delegate Requirements, Acceptance Criteria, NFRs, destructive safety,
privacy, compatibility, or release evidence. Zero samples remain `no_samples`;
later unsupported evidence creates a linked follow-up without rewriting history.

## Liveness contract (SPEC-225)

The heartbeat is the sole liveness signal for a Nightshift run. Do not infer a
stall from file mtimes, branch-tip movement, commit counts, or any equivalent
activity proxy: read-only verification and correctly completed zero-commit runs
are valid. A long read-only phase must heartbeat with its phase and expected
duration; a run with no expected commit declares `no_commit_expected: true`.
Only a stale heartbeat with no declared phase is a real stall, subject to the
configured threshold.

## Where to look

Detail lives in guides, loaded only when needed. In an install they are
`.nightshift/guides/<topic>.md`; in the kit repository the same files are
`canonical/guides/<topic>.md`. Guides exist only in installs of a kit that ships them.

Run `python3 .nightshift/skill_tutorial.py <command>` to print a command's when-to-use,
not-when and `guide:` path (the registry below is the only place they are written).

Intents with no command of their own:

- search specs, list blocked or ready specs, show a spec or its status history → `board`
- who is working on what (`in_progress` specs, run state) → `board`
- move a spec's status, or why a card did not move → `board`
- is this install sound → `validate`; why is it invisible or stale → `doctor`

## How This Skill Works

<!-- nightshift-commands-registry -->
```yaml
commands:
  - name: tutorial
    one_liner: Learn which Nightshift command fits before changing anything.
    options: ["[command]", "alias: help [command]"]
    when_to_use: Read a harness-aware, read-only overview or focused command guide.
    side_effects: None; it only reads this registry and renders guidance.
    not_when: You already know the command and need it executed.
    asks: Nothing; choose an optional command name for focused help.
    example: "SPEC-267: inspect `tutorial unblock` before choosing SPEC-259's drive-to-done path."
  - name: init
    one_liner: Start Nightshift in a new or empty project.
    options: []
    when_to_use: Bootstrap a project that has no existing implementation to analyse.
    side_effects: Creates .nightshift configuration, copied canonical protocol, and optional hook files.
    not_when: The project already has code and needs its conventions captured first.
    asks: Project identity, commands, conventions, review personas, and runner mode.
    example: "SPEC-230: initialize a fresh fixture install before proving checkpoint behavior."
  - name: retrofit
    one_liner: Add Nightshift to an existing codebase after mapping it.
    options: []
    when_to_use: Adopt Nightshift in a project with existing code, conventions, and tests.
    side_effects: Creates .nightshift files plus baseline and gap specs after analysis.
    not_when: The project is new or empty; use init instead.
    asks: Confirmation of detected architecture, conventions, tests, and known gotchas.
    example: "SPEC-153: inspect an existing managed project before aligning its canonical integration."
  - name: spec
    one_liner: Create or amend a testable, dependency-aware specification.
    options: []
    when_to_use: Define or edit requirements and acceptance criteria before implementation.
    side_effects: Writes or updates spec files after user confirmation and validation.
    not_when: You need to execute an already-ready spec; use run or kickoff.
    asks: Problem, requirements, acceptance criteria, context, dependencies, and scope boundaries.
    example: "SPEC-260: define the AC-review agent and amendment-gate acceptance criteria."
  - name: sync
    one_liner: Compare done specs against their current implementation.
    options: []
    when_to_use: Check whether documented behavior and shipped code have drifted apart.
    side_effects: Read-only analysis unless the user approves suggested spec updates.
    not_when: You need to validate install mechanics rather than behavior; use validate.
    asks: Approval before applying any suggested spec changes.
    example: "SPEC-258: confirm a documentation correction did not change executable test behavior."
  - name: status
    one_liner: See the spec queue, dependency graph, health, and warnings.
    options: []
    when_to_use: Get a concise project-level view before selecting work.
    side_effects: Read-only dashboard and duplicate-spec scan.
    not_when: You need a full protocol/config command check; use validate.
    asks: Nothing.
    example: "SPEC-252: inspect queue and prior run outcome before resolving a terminal lifecycle state."
  - name: board
    one_liner: Find specs, read board status, and move a spec's status correctly.
    options: []
    when_to_use: List, show, search specs, run or diagnose the board, move a status (`.nightshift/board_ctl.py`; reads work offline).
    side_effects: Reads only, except start/stop and `transition`, which commits just the spec and its artifacts.
    not_when: You need install validity (validate) or install provenance (doctor).
    asks: Nothing for reads; a reason for judgment transitions.
    example: "SPEC-417-001: look up SPEC-393's status history without reading board.py."
    guide: .nightshift/guides/board-and-api.md
  - name: rules
    one_liner: Find where each rule lives; pre-flight one spec against them.
    options: ["check <spec-id>", "[--diff <range>]"]
    when_to_use: Ask "may I do X?" or "is this spec ready?" before promotion or merge.
    side_effects: Read-only; never writes the tree or store.
    not_when: You need to move a status (board) or check install files (validate).
    asks: Nothing.
    example: "SPEC-417-004: check a draft for promotion gaps and scope before asking for ready."
    guide: .nightshift/guides/rules.md
  - name: doctor
    one_liner: Diagnose reachability, payload provenance, and broken installs safely.
    options: ["[project]", "--fleet", "--fix"]
    when_to_use: An install is broken, invisible, stale, or needs a bounded mechanical repair.
    side_effects: Read-only by default; --fix performs only declared mechanical repairs.
    not_when: You only need local protocol/config validation; use validate.
    asks: Whether to permit the bounded --fix repair when findings support it.
    example: "SPEC-203: audit managed-payload provenance without inferring ownership from timestamps."
    guide: .nightshift/guides/doctor.md
  - name: validate
    one_liner: Check protocol files, config, commands, specs, dependencies, and Git setup.
    options: []
    when_to_use: Verify an install is structurally ready before a run or after setup changes.
    side_effects: Runs declared validation commands but does not intentionally mutate project state.
    not_when: You need external reachability or fleet provenance diagnosis; use doctor.
    asks: Nothing.
    example: "SPEC-243-001-001: verify root-relative canonical-suite execution from a fresh dispatch."
    guide: .nightshift/guides/validate.md
  - name: knowledge
    one_liner: Add, update, review, or import reusable project knowledge.
    options: ["add <topic>", "update <file>", review, import]
    when_to_use: Capture conventions, lessons, or report-derived knowledge for later runs.
    side_effects: Writes knowledge files for add, update, and import.
    not_when: You are defining requirements for a feature; use spec.
    asks: Topic scope, patterns, and review-persona ownership when creating an entry.
    example: "SPEC-280: record the cache-boundary lesson after the Python-bytecode policy change."
    guide: .nightshift/guides/knowledge.md
  - name: release
    one_liner: Publish and roll out one exact, validated canonical kit.
    options: ["--dry-run", "--apply"]
    when_to_use: Release an approved canonical managed payload to eligible installs.
    side_effects: --apply can copy payloads and create guarded local commits; it never pushes.
    not_when: You are implementing one spec or need a file-only sync.
    asks: Operator review of dry-run coverage and authorization before apply.
    example: "SPEC-280: roll out the cache-ignore policy only after whole-kit validation."
    guide: .nightshift/guides/release.md
  - name: unblock
    one_liner: Recover an evidence-blocked spec, optionally driving it toward done.
    options: ["<spec-id>", "--to-done", "--from-rung <2-4>", "--dry-run"]
    when_to_use: A spec is blocked and retained evidence supports the controller-backed recovery path.
    side_effects: Records controlled unblock attempts; --to-done may launch bounded recovery work.
    not_when: The spec is ready and has not yet run; use run or kickoff.
    asks: Authorization only when the ladder reaches a human-only rung.
    example: "SPEC-259: use `unblock SPEC-259 --to-done` to drive to done after cache-integrity evidence."
    guide: .nightshift/guides/unblock.md
  - name: kickoff
    one_liner: Start the parent-monitored autonomous loop for one spec.
    options: ["[spec-id]"]
    when_to_use: Run a ready spec with a parent-owned lifecycle, heartbeat, and integration flow.
    side_effects: Marks lifecycle state, launches a worker, records evidence, and may merge an accepted candidate.
    not_when: You only need direct execution guidance without the board-style parent wrapper; use run.
    asks: Nothing unless a genuine ambiguity or missing prerequisite prevents dispatch.
    example: "SPEC-252: launch a monitored parent kickoff with durable terminal-resolution evidence."
    guide: .nightshift/guides/kickoff.md
  - name: run
    one_liner: Execute the autonomous spec loop directly with the same evidence gates.
    options: ["[spec-id]"]
    when_to_use: Implement a ready spec through the normal isolated-worker workflow.
    side_effects: Marks lifecycle state, launches a worker, records evidence, and may merge an accepted candidate.
    not_when: You need to inspect or edit the spec before execution; use spec.
    asks: Nothing unless a genuine ambiguity or missing prerequisite prevents dispatch.
    example: "SPEC-260: run the AC-review amendment gate through independent verification."
    guide: .nightshift/guides/run.md
  - name: address-issues
    one_liner: Consolidate and resolve embedded questions from draft or blocked specs.
    options: []
    when_to_use: Draft or blocked specs contain explicit or implied decisions that need resolution.
    side_effects: Writes a persistent QUESTIONS spec and, after decisions, updates eligible source specs.
    not_when: A ready spec has no unresolved question; use run or kickoff.
    asks: One material decision at a time, with options and evidence where needed.
    example: "SPEC-241: resolve a bounded unblock question without rewriting the done source spec."
    guide: .nightshift/guides/address-issues.md
```

The skill provides the commands above. When the user's request matches one, follow that command's flow. When the request is ambiguous, use context to pick the right command — or ask.

### Invocation syntax by harness

`/nightshift` is a Claude-style command label, not a portable literal command.
Use the invocation that the active harness supports:

| Harness | Invoke Nightshift as |
| --- | --- |
| Claude Code with custom slash commands | `/nightshift <action>` |
| Codex | `$nightshift <action>` or a plain-language request such as “use Nightshift to validate this project” |
| Any other harness | A plain-language request naming Nightshift and the action |

All `/nightshift …` headings and references below identify the same route. When
speaking to a user, render the route in the active harness's syntax. In
particular, never tell a Codex user to enter `/nightshift`: Codex reserves `/`
for its own built-in commands and reports that input as unrecognized.

**Command routing:**
- User wants to add Nightshift to a new/empty project → `/nightshift init`
- User wants to add Nightshift to a project that already has code → `/nightshift retrofit`
- User wants to write or edit a spec → `/nightshift spec`
- User wants to run the loop directly on a spec → `/nightshift run`
- User wants a board-copied parent kickoff flow → `/nightshift kickoff`
- User wants to publish and safely roll out one canonical kit → `/nightshift release`
- User wants to check if specs match implementation → `/nightshift sync`
- User wants a quick overview of Nightshift state → `/nightshift status`
- User wants to verify the setup is correct → `/nightshift validate`
- User wants to diagnose or safely repair a broken/invisible install → `/nightshift doctor`
- User wants to manage knowledge/ entries → `/nightshift knowledge`
- User wants to surface and resolve open questions embedded in draft specs → `/nightshift address-issues`
- User wants a read-only guide to commands or options → `/nightshift tutorial [command]` (alias: `/nightshift help [command]`)

Before running any command, check: does `.nightshift/` exist in the project? If the user's request assumes it does but it doesn't, suggest `init` or `retrofit` first.

---

## `/nightshift tutorial [command]` — Read-only Command Guide

Render this guide from the fenced `commands` registry above; it is the source of
truth for tutorial text and is deliberately separate from the detailed command
sections below. The `help` alias has identical behavior. This route reads only:
it writes no files, changes no lifecycle state, and dispatches no agents.

For an executable rendering in a shell or test harness, run:

```bash
python3 canonical/skill_tutorial.py [command] --harness <codex|claude|other>
```

With no command, render the overview: description, lifecycle, table of every
registry command and options, and decision tree. With a command, render its
purpose, when not to use it, options, side effects, user prompts, and worked
example. Use `$nightshift …` in Codex and `/nightshift …` in Claude Code or other
slash-command harnesses; the renderer enforces that distinction.

---

## `/nightshift init` — Bootstrap a New Project

Creates the `.nightshift/` folder and fills in all configuration interactively.

### Step 1: Detect project context

Scan the project root for manifest files to auto-detect the stack:

| File | Indicates |
|------|-----------|
| `package.json` | Node.js / TypeScript |
| `pyproject.toml`, `setup.py`, `requirements.txt` | Python |
| `Cargo.toml` | Rust |
| `Package.swift` | Swift |
| `go.mod` | Go |
| `*.csproj`, `*.sln` | .NET / C# |
| `Gemfile` | Ruby |
| `pom.xml`, `build.gradle` | Java / Kotlin |

Also detect:
- Test framework (from config files, test directories, package deps)
- Linter/formatter (eslint, ruff, clippy, swiftlint, etc.)
- Build system (npm scripts, Makefile, cargo, swift build)
- Whether it's a git repo (warn if not — Nightshift assumes git)

Check if `.nightshift/` already exists. If yes, ask: reconfigure or abort?

### Step 2: Interactive config generation

Ask the user to confirm or override each detected value. Use AskUserQuestion or natural conversation — adapt to the user's style.

**Sections to fill:**

1. **Project identity** — name, description. Pre-fill from manifest if possible.

2. **Commands** — build, test, lint, type_check, format. Present what was detected, let user confirm or provide custom commands. All are required except format (recommended). If lint or type_check are missing, flag it: "Nightshift works best with strict static analysis. Want to set up linting as your first spec?"

3. **Conventions** — 3-5 project conventions. Give examples based on detected stack:
   - Python: "Tests live in tests/ mirroring src/ structure", "All imports sorted with isort"
   - TypeScript: "Components use functional style with hooks", "API calls go through src/api/client.ts"
   - Ask: "What patterns should every contributor follow in this project?"

4. **Review personas** — Nightshift uses 6 review personas (Architect, Security, Performance, Domain Expert, Code Quality, User Advocate). Default: all enabled. Ask if any should be disabled or if extra review criteria should be added.

5. **Runner mode** — `inline` (single session, all specs sequentially) vs `orchestrator` (fresh agent per spec). Recommend inline for projects with <10 specs, orchestrator for larger ones.

6. **Circuit breaker** — Show defaults (max 3 same errors, 5 review cycles, 120 min per spec). Ask if user wants to customize.

### Step 3: Copy canonical kit + customize config

The Nightshift Kit protocol files (LOOP.md, BOOTSTRAP.md, REVIEW.md, etc.) are complex, battle-tested documents — **never generate them**. Copy them from the canonical source.

**Locate the canonical copy:**

```bash
# The canonical Nightshift Kit lives in the managed developer projects tree:
CANONICAL="$HOME/Dropbox/Developer/ManagedProjects/Nightshift/canonical"

# Verify it exists
if [ ! -f "$CANONICAL/LOOP.md" ]; then
  echo "ERROR: Canonical Nightshift Kit not found at $CANONICAL"
  echo "Expected: Dropbox/Developer/ManagedProjects/Nightshift/canonical/"
  exit 1
fi
```

If the canonical path is not accessible (e.g., running outside Argo Home, different machine), ask the user where their canonical Nightshift Kit is located.

**Install the managed kit** (never copy the whole tree: canonical also holds the kit's own specs, reports, runs, tests):

```bash
git init -q 2>/dev/null; python3 "$CANONICAL/release.py" install --canonical "$CANONICAL" --install .nightshift \
  --name <project-name> --language <lang>   # --language repeats; both from Step 2
```

It copies only the managed set (protocol files, scripts, hooks, guides, `release-marker.json` last), creates the scaffold directories, spec templates and a `config.yaml` (with that name and language), wires `hooks/pre-commit` and `hooks/commit-msg` into the git hooks directory, then runs `validate_install.py --profile installed`. It exits non-zero unless the verdict is ALLOW and names the failing invariants; do not continue past a DENY. `--dry-run` previews; `--force` re-installs over an existing marker.

**Do NOT modify the protocol .md files.** They are the canonical protocol. Only customize config.yaml.

**Customize config.yaml** — Fill in the values gathered in Step 2:

```bash
# Use sed, python, or manual editing to fill in config.yaml with:
# - project.name, project.description, project.language
# - commands.build, commands.test, commands.lint, commands.type_check
# - conventions list
# - review.enabled (persona list)
# - runner.mode
# - circuit_breaker thresholds (if user customized)
# - git.main_branch, git.commit_style
```

The installed config.yaml already has the right structure with inline documentation — just fill in the blanks.

**Generate project-specific files** (these ARE generated, not copied):

- `prompts/spec-reviewer.md` — adversarial spec compliance reviewer
- `prompts/quality-reviewer.md` — code quality reviewer
- `prompts/completion-checklist.md` — premature victory guard

Offer to install the Claude Code `PreToolUse` write-scope hook
(SPEC-300-004): `sh .nightshift/hooks/install-write-scope-hook.sh` from the
project root, which wires `write-scope-hook.sh` into `.claude/settings.json`.
This is the earliest enforcement point — it stops an out-of-scope write
before the tool call executes, rather than at commit time — but it only
takes effect for harnesses that support `PreToolUse` (Claude Code today; see
"Harness coverage" below). Declining leaves `doctor`'s `D8` finding to catch
it later.

### Step 4: Static analysis audit

Compare detected static tools against what's expected for the language (see table in `references/templates.md`). Report gaps. If tools are missing, offer to generate `SPEC-000-tooling` as the first spec.

### Step 5: Offer first spec

"Your Nightshift Kit is ready. Want to create your first spec?" If yes → hand off to `/nightshift spec`.

---

## `/nightshift retrofit` — Add Nightshift to an Existing Project

For projects that already have code. Does everything `init` does, plus deep codebase analysis to capture the current state.

### Step 1: Deep codebase analysis

Analyze the project systematically. Read actual source files, not just manifests.

**a. Architecture scan:**
- Map directory structure and purpose of each top-level folder
- Identify entry points (main, index, app, server files)
- Detect module boundaries and dependency direction
- Count files, lines, languages

**b. Convention extraction:**
- Naming patterns (camelCase, snake_case, PascalCase — for files, variables, functions)
- Import organization (grouped? sorted? absolute vs relative?)
- Error handling style (try/catch, Result types, error boundaries, custom error classes)
- Configuration approach (env vars, config files, constants)
- Logging patterns

**c. Test pattern analysis:**
- Framework and runner
- File placement (co-located, tests/ dir, __tests__/)
- Fixture and mock patterns
- Helper utilities
- Coverage: which modules have tests, which don't

**d. Behavioral patterns:**
- API style (REST, GraphQL, RPC, CLI)
- Auth/authz approach
- Data flow: input → processing → storage → output
- State management
- Framework-specific patterns

**e. Functional mapping:**
- List all user-facing features/endpoints/commands
- Map feature → files involved

### Step 2: Interactive confirmation

Present findings to the user for validation. This is critical — automated analysis catches structure but misses intent.

Ask:
- "I found these conventions. Are they accurate? Anything missing or wrong?"
- "These seem to be the module boundaries. Correct?"
- "I see no tests for [X, Y, Z]. Is that intentional or tech debt?"
- "I detected these patterns. Are there undocumented patterns I should know about?"
- "Are there any gotchas or 'here be dragons' areas new contributors should know about?"

### Step 3: Run init flow

Execute the full `init` flow (Steps 2-4) with the detected values as pre-filled defaults.

### Step 4: Generate knowledge base

Create rich `knowledge/` files from the analysis:

- `knowledge/architecture.md` — module map, boundaries, dependency direction, entry points
- `knowledge/conventions.md` — naming, file placement, import style, error handling, logging
- `knowledge/testing.md` — framework, patterns, coverage map, fixture conventions
- `knowledge/patterns/*.md` — one file per significant pattern (auth, API, data flow, state)
- `knowledge/_review/architecture.md` — architectural decisions, ADRs if found
- `knowledge/_review/security.md` — auth patterns, input validation, secrets management
- `knowledge/_review/quality.md` — code style, naming conventions, DRY patterns

### Step 5: Generate baseline and gap specs

**Baseline specs** — describe what already exists (status: `done`, type: `feature`):
- One spec per major feature/module that already works
- Purpose: give the loop context about what's built, so new specs can `after:` reference them
- Requirements should use `[x]` checkboxes (already satisfied)
- ACs should also use `[x]` (already met by existing implementation)
- Include target files in Context so the loop knows which code implements what
- Example: `SPEC-BASELINE-001-user-auth.md` — describes current auth flow, all ACs checked, status: done

**Gap specs** — suggested improvements (status: `draft`):
- Missing tests → `SPEC-GAP-001-add-tests-for-X.md`
- Missing type checking → `SPEC-GAP-002-add-type-checking.md`
- Inconsistent patterns → `SPEC-GAP-003-standardize-error-handling.md`
- These are suggestions — user reviews and promotes to `ready` if they want them

### Step 6: Report

Summarize: what was found, what was generated, what gaps were identified, recommended first Nightshift run.

---

## `/nightshift spec` — Create or Edit a Spec

Interactive spec authoring with validation.

### Intent capture (optional short path)

Use this path when the user has a half-formed idea and wants a durable
reflection without committing to a spec interview. Do not apply the Phase 1-8
guardrail pushback during capture. Ask at most these four questions:

1. **Problem:** What feels painful, missing, or worth changing?
2. **Trigger:** What made this idea worth capturing now?
3. **Affected:** Who notices the problem or would benefit?
4. **Rough outcome:** What would better look like, without requiring a solution?

Write the answers with `intents/_TEMPLATE-INTENT.md` to
`intents/<lowercase-kebab-slug>.md` (`canonical/intents/` in the kit
repository; `.nightshift/intents/` in an installed project), set
`status: captured`, leave `promoted_to:` empty, and git-track the file. Tell
the user: **this intent is non-committing and cannot enter the Nightshift
loop. An intent cannot be dispatched, kicked off, or counted as a spec.** It
lives outside `specs/`, so do not add it to validator, scanner, or board
exclusion lists.

To reject it, change only `status` to `rejected`, or delete the intent. To
turn it into work, start the complete spec flow below. Pre-fill Phase 1 from
`problem`, `trigger`, and `affected`, and use `rough_outcome` as initial
context, but confirm each answer with the user and apply every interview
guardrail. After the new spec exists, add `Origin intent: intents/<slug>.md`
to its `## Context`, then set the intent to `status: promoted` and
`promoted_to: <SPEC-ID>`. Never promote it automatically.

### Creating a new spec

1. **Context and identity check** — read `config.yaml`, existing specs and `knowledge/`.
   Resolve the intended project from the live `projects-registry.json` and its watched
   spec root **before** the supported duplicate/ID gate. Canonical kit work belongs
   to the registered canonical project (observed code `NS-KIT`); Control is separate
   (observed `NS-CTL`); installed application specs use that project's own code/root.
   These are installation observations, not fixed defaults. Read the authoring
   placement section of `.nightshift/guides/board-and-api.md` (kit:
   `canonical/guides/board-and-api.md`) for registered-root minting, caller-only
   worktree mapping and discovery. Refuse an unexpected generic ID; correct identity,
   never invent a number, suppress conflicts or edit the global registry.
   - If `.nightshift/reports/GAP-ANALYTICS-STATUS.json` exists, read it and surface warnings before the interview.
   - If warning `AMBIGUOUS_REQUIREMENT` is present, explicitly ask for:
     - measurable constraints (numbers/thresholds)
     - explicit edge cases
     - requirement-to-AC mapping
   - **Scan active NFRs** — read all `specs/NFR-*.md` with `status: active`, extract each `## Constraint` section, carry this context forward into the interview. Required before writing requirements or ACs — without it you cannot check for constraint violations.

2. **Spec type** — ask: Feature / Bugfix / Refactor / Eval / Skill? Each has different emphasis. Before promoting the result to `ready`, follow the canonical NFR reconciliation rule in `SPEC-GUIDE.md`: bind or explicitly waive every mechanically matched active NFR, then validate.

3. **Guided interview:**

   a. **Problem** — "What problem does this solve? Why does it matter?" Help articulate clearly.

   b. **Requirements** — "What must the implementation do?" Elicit 3-7 concrete requirements. For each, verify it's testable. Flag vague requirements: "support edge cases" → ask which specific edge cases.

   c. **Acceptance criteria** — Generate from requirements, present for review. Each must be: specific, testable, independent. Flag overlaps or contradictions.

   d. **Context** — Auto-fill target files from project structure. Auto-fill test files from test conventions. Auto-fill framework from config. Ask about related specs and existing code.

   d1. **Write scope (SPEC-300-001)** — Propose `scope.write` as project-root-relative
       globs derived from the file paths mentioned in `## Context` and from `touches:`
       (e.g. `src/repositories/DocumentRepository.ts` and `touches:
       [src/search/**]` propose `scope.write: [src/repositories/**, src/search/**]`).
       Present the proposal and ask the author to confirm or narrow it. If the author
       cannot settle on a scope, that is a drafting blocker — resolve it before
       `status: ready`, per SPEC-300 § Defaults ("a scope the author could not settle
       is a drafting blocker, not a reason to leave it open"). Leaving `scope:` out
       entirely is always a valid, deliberate answer — it means the whole project
       root, exactly like an existing v9 spec with no `scope:` block. Record the
       confirmed answer as `scope.write` in frontmatter; see SPEC-GUIDE.md
       § Write scope for the full field, defaults, implicit-allow rules, and the ten
       controlled reason codes.

   e. **Layer + dependencies** — Suggest layer based on what the spec touches. Check existing specs for `after:` dependencies. Warn if dependencies are missing.

   f. **Out of scope** — "What should this NOT cover?" Suggest boundaries to prevent scope creep.

4. **Validation** (strict for `ready`, lenient for `draft`):
   - Frontmatter: all fields present, ID unique, status valid
   - Every requirement has a matching AC
   - Every AC is testable
   - Target files exist or are explicitly new
   - Dependencies resolve (all `after:` IDs exist)
   - Layer is consistent with existing spec layers
   - `nfrs:` field is populated for `type: feature/bugfix/refactor` — list applicable NFR IDs or `[]` (explicit "reviewed, none apply"); required before `status: ready`
   - Record the R/AC contract review through the existing
     `lifecycle_classification` event path, including a clean review with
     `items: []`. Use the `SPEC-GUIDE.md` controlled reason codes and record only
     reviewed counts, R/AC IDs, item kinds, and reasons — never spec prose.

5. **Write spec** to `specs/SPEC-{ID}-{slug}.md`, including the `## State
   rationale` section (SPEC-357; template v12/bugfix v4/analysis v3/research
   v3) with `record: null` — the template's placeholder text is not a valid
   value, fill in the real `status`/`reason`/`reconsider_when`/`evidence`
   from the interview above. Confirm with user before writing. When creating
   an NFR (excluded from this section — `type: nfr`/`NFR-*` never requires
   it), reconcile every matched non-done spec; when promoting any spec,
   reconcile it against every active NFR. Use `audit_nfr.py --check-all`
   where installed.

5a0. **Record the authoring decision (SPEC-357 R3)** — immediately after
    writing the file, capture the same declaration as an indexed `decision`
    artifact so `record` is no longer `null`:
    ```bash
    python3 .nightshift/spec_artifacts.py author-decision <spec-file> \
      --status <draft|planned> --reason "<why this status>" \
      [--reconsider-when "<...>"] \
      [--state-evidence '{"kind": "file", "path": "..."}']
    ```
    `--reconsider-when` is required whenever `--status` is `draft`/`planned`.
    Stage the spec file and its `reports/<spec-id>/artifacts/` directory in
    the same commit as the new spec.

5a. **Promoting `draft`/`planned` -> `ready` (SPEC-291)** — never hand-edit
    `status:` for this transition. Use the canonical entrypoint, which writes
    the durable checkpoint, the `status-transition` artifact, and — when a
    `promotion_gap` is being resolved — `decision`/`context`/
    `validation-evidence` artifacts recording the resolution rationale and
    whatever was gathered to justify it, all under
    `reports/<SPEC-ID>/artifacts/`:
    ```bash
    python3 .nightshift/spec_promotion.py <spec-file> \
      --run-id <run-or-session-id> \
      --reason "<why this is ready now>" \
      [--gap-resolved | --gap-waived-reason "<why the gap no longer blocks>"] \
      [--resolution-rationale "<what resolved the promotion_gap>"] \
      [--finding "<one finding you gathered>" ...] \
      [--evidence "<path or ID you checked>" ...]
    ```
    `--reason` is always required — a promotion with no reason is refused, not
    silently recorded. `--resolution-rationale` is required whenever
    `--gap-resolved`/`--gap-waived-reason` resolves a declared `promotion_gap`.
    A later agent should be able to answer "why is this spec ready?" by
    reading `reports/<SPEC-ID>/artifacts/index.json` alone.

5b. **Retain and discover** — keep the spec, indexed author decision, evidence and
    required handoff together on a durable branch. Branch commit, board-visible
    working-tree placement and integration into MAIN are distinct. Follow GIT.md's
    sole serialized integration authority and current MAIN freeze; disclose any
    outstanding integration. Never dirty frozen MAIN, bypass the queue, remap a board
    root or promote solely for display. Use the board guide's bounded health →
    refresh → list/detail check at the registered port: each new ID once, intended
    effective status, indexed artifacts available. HTTP 404 leaves discovery unresolved;
    intrinsic readiness PASS does not change lifecycle `draft` or make it dispatchable.
    Retain unique temporary findings with source paths and SHA-256 integrity in
    persistent branch reports before cleanup; exclude credentials and app/build trees.
    Authoring-only placement adds no native/full-kit implementation-suite obligation;
    existing implementation, independent verification, integration and release gates stay.
    Deliver skill changes from canonical source through the managed whole-kit release
    path and pending handoff, never by patching installed skill copies.

6. **Post-save for `type: nfr`** — after saving a new NFR spec, run the impact audit:
   ```bash
   python3 .nightshift/audit_nfr.py --nfr-id <new-id> --specs-dir .nightshift/specs/
   ```
   Surface the report to the user. They review the listed non-done specs and decide which ones need `nfrs: [<new-id>]` added.

### Spec IDs (SPEC-416)

A new spec ID is `{KIND}-{CODE}-{NNN}(-{NNN})*`: `{CODE}` is the project's registered code (`code` in
`projects-registry.json`; one or two letter-only segments of 2-6 capitals, e.g. `ARGO`, `NS-KIT`), `{NNN}`
has at least 3 digits. Mint with `check_followup_spec.py` (`--kind`), never by hand.

| `id_kind` | Required `type:` |
|---|---|
| `SPEC` | any except `bugfix`, `nfr`, `questions` |
| `BUG` | `bugfix` |
| `NFR` | `nfr` |
| `QUESTIONS` | `questions` (leads: `QUESTIONS-{CODE}-NNN`) |

`id_kind` is not the frontmatter `type:`. Legacy rule: existing IDs are never renamed; each project's
frozen, generated list (`spec-id-legacy/<CODE>.json`) keeps them valid. `validate_specs.py` errors on a new
ID that breaks the grammar, the project code, fleet uniqueness or the kind/type pairing. Cross-project
prerequisites still use `requires_specs: [{project: REGISTERED_NAME, spec: ID}]`; see `SPEC-GUIDE.md`.

### Editing an existing spec

If user says "edit spec SPEC-003" or names a spec file:
- Read the spec, show current state
- Ask what to change
- Validate changes
- Write updated spec

### Spec frontmatter format

```yaml
---
id: SPEC-XXX
priority: 1          # within-layer priority (1 = highest)
layer: 2             # 0 = foundation, 1 = infra, 2 = feature, 3 = polish
type: feature        # feature | bugfix | refactor | eval
status: ready        # draft | ready | in_progress | done | blocked
after: []            # soft dependencies — spec IDs
prior_attempts: []   # previous failed attempts
created: YYYY-MM-DD
---
```

---

## `/nightshift sync` — Check Spec-Implementation Alignment

Detects drift between specs (status: `done`) and their implementations.

### Step 1: Gather pairs

Read all specs with `status: done`. For each, identify target files from the Context section. Flag specs whose target files no longer exist.

### Step 2: Per-spec analysis

For each spec-implementation pair:

**a. Requirements check** — Does the code satisfy each requirement? Is there code beyond the requirements (scope creep)?

**b. AC check:**
- Test exists and passes → AC met
- Test exists but fails → DRIFT (regression)
- No test → WARNING (untested)
- Code behavior changed from what AC describes → DRIFT (diverged)

**c. Scope check** — Did anything from "Out of Scope" creep into the implementation? Were new files added that the spec doesn't account for?

### Step 3: Drift report

Per-spec: **SYNCED** / **DRIFTED** / **NEEDS REVIEW**

For drifted specs, report:
- What changed in implementation
- Which requirements/ACs are affected
- Severity: cosmetic / functional / structural

### Step 4: Suggest updates

For each drifted spec, generate a suggested update:
- Updated requirements reflecting current implementation
- New/modified ACs matching actual behavior
- Updated context (new target files, changed test files)
- Marked: `[ADDED]`, `[MODIFIED]`, `[REMOVED]`

Present as old vs suggested. User approves/rejects each change.

### Step 5: Reverse sync

Scan for implemented features with NO spec at all. Offer to generate new specs for undocumented functionality.

---

## `/nightshift status` — Project Overview

Quick dashboard of Nightshift state:

- **Spec queue:** count by status (ready / in_progress / done / blocked / draft)
- **Layer breakdown:** specs per layer, completion percentage
- **Dependency graph:** text-based, shows which specs depend on which
- **Last run:** when, which specs processed, outcomes (from reports/)
- **Knowledge coverage:** which files exist, last updated
- **Config health:** missing commands, empty conventions
- **Warnings:** specs with no ACs, orphaned specs (done but files deleted), stale blocked specs
- **Duplicate scan:** run `python3 .nightshift/check_followup_spec.py --specs-dir .nightshift/specs --scan-all`. If it exits 1, list the near-duplicate pairs (title + requirement/AC body overlap) — this catches duplicates that entered outside the per-suggestion follow-up gate (e.g. hand-authored or bulk-promoted specs).

---

## `/nightshift board` — Board, Status API and Status Transitions

Read `.nightshift/guides/board-and-api.md` (kit repository: `canonical/guides/board-and-api.md`)
before any of these; it is written from the current code:

- find the board and its port, list/show/search specs, status history, dependency graph;
- move a spec's status (which write path, which gate, when a `reason` is required);
- explain why a card did not move after a frontmatter edit (the board reads the status store).

Never guess an endpoint from memory and never hand-edit `status:` of a `blocked` or `done` spec.

---

## `/nightshift rules` — Rule Map and Pre-flight

Read `.nightshift/guides/rules.md` (kit repository: `canonical/guides/rules.md`): one row per
rule family and its source. Pre-flight a spec before promotion or merge (read-only):

`python3 .nightshift/board_ctl.py rules check <spec-id> [--diff <rev-range>]`

One `rule | pass/fail/skip | reason | source` line per check. A digest never overrides its source.

---

## `/nightshift doctor` — Diagnose Broken or Invisible Installs

Read `.nightshift/guides/doctor.md` (kit repository: `canonical/guides/doctor.md`) before running doctor: the invocation, exit codes, provenance audit and findings D7/D8 are there.

## `/nightshift validate` — Check Kit Integrity

Read `.nightshift/guides/validate.md` (kit repository: `canonical/guides/validate.md`) before running validate: every check and the output format are there.

---

## `/nightshift knowledge` — Manage Knowledge Base

Read `.nightshift/guides/knowledge.md` (kit repository: `canonical/guides/knowledge.md`) before any knowledge step: the add, update, review and import flows are there.

---

## `/nightshift release` — Publish and Roll Out One Exact Kit

Use this command only from the canonical Nightshift repository. The release unit
is the whole managed kit; never add or simulate a file-only release.

Read `.nightshift/guides/release.md` (kit repository: `canonical/guides/release.md`) before any release step: it holds Steps 1-5 (preflight, fleet dry-run, apply, verification, report).

### Required handoff completion (SPEC-189)

For every pending release-impact artifact whose target version and manifest
fingerprint match this release, the coordinator records completion only after
the full release succeeds. Do not edit an artifact to `completed` by hand,
perform a file-only sync, or treat skipped installs as synchronized. Include
completed and still-pending handoffs in the durable release report.

---

## `/nightshift unblock <spec-id>` — Evidence-backed Recovery

Use this command only for a currently `blocked` spec; only currently blocked specs
can pass preparation. The command is a
controller-backed unblock protocol: the parent first runs
`python3 unblock_spec.py prepare <spec-file> --root <project-root> --run-id <run-id>`
and presents its eligibility verdict, bounded task, pinned evidence paths and
hashes, prior attempts, guardrails, and verification gate.
`<spec-file>` may be project-relative even when `--root` is absolute; the
controller resolves it against that root, never the caller's current directory.
`--root` may be the project root or the install directory (`.nightshift`); unblock state (`runs/`, `knowledge/attempts/`, `reports/_wip/`) is kept under the install directory, and a directory with neither layout is refused (`NS-UNBLOCK-ROOT-NOT-INSTALL`).

Read `.nightshift/guides/unblock.md` (kit repository: `canonical/guides/unblock.md`) before running any unblock step: the options, the rung ladder and the evidence rules are there.

## `/nightshift kickoff [spec-id]` — Parent Kickoff Wrapper

The parent retains the successful installation admission's integrity receipt.
When the worker returns, it invokes
`managed_payload_provenance.verify_terminal_integrity` with that original
receipt before verifier-result acceptance, lifecycle terminalization, merge,
post-merge validation, or worktree cleanup. A fresh admission is not a valid
replacement. Deny or indeterminate preserves the worker branch/worktree and
routes the release-owned path to its canonical path/spec plus whole-kit release;
the parent never resets, checks out, bulk-copies, deletes, or auto-repairs it.
The result receipt is admitted against the worker worktree's install and checked there; a separate
control-plane receipt is admitted against the parent's install. A control-plane `NS-MPI-RELEASE-SUPERSEDED`
earns one fresh shared admission and one re-check; a result-receipt one ends the run `superseded`
(re-admit and re-run; the old candidate is never accepted).

Read `.nightshift/guides/kickoff.md` (kit repository: `canonical/guides/kickoff.md`), then follow the run guide: this command is a wrapper around `/nightshift run`.

## `/nightshift run [spec-id]` — Kick Off the Autonomous Loop

Takes a spec (or picks the next ready one) and launches a worktree-isolated agent to execute the full orchestrator → loop dance.

### Parent kickoff agent mode

Normal `/nightshift run <spec-id>` executes the standard run flow. If the command
was reached through `/nightshift kickoff <spec-id>`, or the human explicitly says
this is parent kickoff mode, set `kickoff_parent: true`.

When `kickoff_parent: true`, the current agent is the parent kickoff agent and
must not implement the spec directly. It launches the run/orchestrator agent,
monitors progress, and resolves the run autonomously at completion. The launched
agent must receive the Kickoff Parent Context section in its brief so it knows
progress reporting is required.

Read `.nightshift/guides/run.md` (kit repository: `canonical/guides/run.md`) first: it holds Steps 1-7 verbatim and names the continuation guides `run-2.md`, `run-3.md`, `run-4.md`, `run-5.md`, `run-6.md`, `run-7.md`, `run-8.md`, read in order as the run advances. Do not run from memory.

Small specs (about 4 ACs or fewer, one module): the kickoff parent follows `kickoff.md` § Small-spec lane and briefs the worker with `.nightshift/guides/worker-small.md` instead of LOOP.md; every gate stays.

---

## Important Implementation Notes

### Canonical kit — NEVER generate protocol files

The protocol files (LOOP.md, BOOTSTRAP.md, REVIEW.md, ORCHESTRATOR.md, etc.) are complex, battle-tested documents totaling ~4800 lines. **Never generate them from descriptions or summaries.** Always copy from `$HOME/Dropbox/Developer/ManagedProjects/Nightshift/canonical/`. Only `config.yaml` values and project-specific files (hooks, prompts) are generated; everything else is copied verbatim.

### Template files

`references/templates.md` contains the config.yaml template format, spec template, static analysis detection table, and pre-commit hook template.

### Spec ID assignment

**Always use `check_followup_spec.py` to get a proposed ID — never compute one by scanning and incrementing manually.** (Why: SPEC-GUIDE.md, "Never assign a spec ID manually".)

```bash
python3 .nightshift/check_followup_spec.py \
  --suggestion-title "Short title" \
  --specs-dir .nightshift/specs/ \
  [--parent-id PARENT-SPEC-ID]  # Required when the spec has a parent: field
```

Use the `proposed_id` from the JSON output (baseline specs: title prefix "Baseline —"; gap specs: "Gap —"); the user may override it after checking it is unused.

### Config detection heuristics

When detecting project commands, check these locations:
- `package.json` → `scripts` section
- `Makefile` / `Justfile` → targets
- `pyproject.toml` → `[tool.*]` sections, `[project.scripts]`
- `Cargo.toml` → cargo commands
- `Package.swift` → swift build/test

### Validation strictness

State rationale uses the shared SPEC-358 gate (GIT.md, "Staged spec validation"): shaped
new drafts may warn for a pending record; planned/ready admission requires a matching
current record. Run `validate_specs.py --staged <repo-root> <kit>/specs` before commit.

- `status: draft` → warn on issues, don't block
- `status: ready` → strict validation, all issues must be resolved
- `status: done` → no validation (it's already implemented)

### Language-agnostic principle

Never assume a specific language in defaults, templates, or placeholder values. Always detect from the project. If detection fails, ask. Examples belong in comments only, not in defaults.

### DevKB Mapping Table

Used by `/nightshift run` to auto-map `technologies` → DevKB files for agent briefs.

| Technology | DevKB File |
|---|---|
| Swift | `DevKB/swift.md` |
| Xcode / SPM | `DevKB/xcode.md` |
| macOS / TCC / Permissions | `DevKB/macos.md` |
| Python | `DevKB/python.md` |
| Shell / Bash | `DevKB/shell.md` |
| LLM API / Claude / OpenAI | `DevKB/llm-apis.md` |
| Architecture / Pipelines | `DevKB/architecture.md` |
| Git | `DevKB/git.md` |
| Testing / XCTest / pytest | `DevKB/testing.md` |

If the spec has multiple technologies, include all matching DevKB files. Always prepend `Argo Home/` to the path in the brief (agents need the absolute anchor).

---

## `/nightshift address-issues` — Surface and Resolve Open Questions in Draft Specs

Read `.nightshift/guides/address-issues.md` (kit repository: `canonical/guides/address-issues.md`) before any address-issues step: the QUESTIONS spec format, scan, discussion flow and guidelines are there.

### Invalid old-run administrative recovery

For the retained wrong-identity/duplicate-contradiction case, use GIT.md's
SPEC-387-001 receipt-bound invalid-run abandonment contract. The parent alone
injects `abandonment_provider` into `unblock_spec.abandon_invalid_run`,
`Coordinator.abandon_invalid_run`, or the official instruction
`abandon_instruction_run` API. It proves original A separately from exact sealed
successor B and the original target-only supported rollout report. This records
rejected-old-run and administrative blocked only. Existing prepare,
record_attempt and finalize revalidate before every mutation/restart; verified
controller recovery alone reaches ready. Preserve old evidence and candidate;
never accept, merge, complete or clean the old run. A new run requires its own
original admission. Ordinary installed, authoring, expiry and parallel callback
gates remain strict.
