---
name: nightshift
version: 3.22.0
description: "Interactive companion for the Nightshift Kit autonomous dev loop. Use this skill whenever the user mentions nightshift, night shift, autonomous dev loop, creating specs, bootstrapping a dev loop, retrofitting a project with nightshift, spec drift, spec sync, or anything related to setting up or managing an autonomous code execution pipeline. Also triggers on: 'write a spec', 'create a spec', 'add nightshift', 'check specs', 'spec drift', 'nightshift config', 'nightshift status', 'nightshift validate'. If the user is working with .nightshift/ folders, specs/ directories, config.yaml for dev loops, or mentions LOOP.md / BOOTSTRAP.md / ORCHESTRATOR.md, use this skill."
---

# Nightshift Kit Skill

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

The Nightshift Kit itself is agent-agnostic (any agent that reads files and runs commands can follow it). This skill is the human-facing interface — it guides users through the parts that require judgment, context, and decisions.

## Liveness contract (SPEC-225)

The heartbeat is the sole liveness signal for a Nightshift run. Do not infer a
stall from file mtimes, branch-tip movement, commit counts, or any equivalent
activity proxy: read-only verification and correctly completed zero-commit runs
are valid. A long read-only phase must heartbeat with its phase and expected
duration; a run with no expected commit declares `no_commit_expected: true`.
Only a stale heartbeat with no declared phase is a real stall, subject to the
configured threshold.

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
  - name: doctor
    one_liner: Diagnose reachability, payload provenance, and broken installs safely.
    options: ["[project]", "--fleet", "--fix"]
    when_to_use: An install is broken, invisible, stale, or needs a bounded mechanical repair.
    side_effects: Read-only by default; --fix performs only declared mechanical repairs.
    not_when: You only need local protocol/config validation; use validate.
    asks: Whether to permit the bounded --fix repair when findings support it.
    example: "SPEC-203: audit managed-payload provenance without inferring ownership from timestamps."
  - name: validate
    one_liner: Check protocol files, config, commands, specs, dependencies, and Git setup.
    options: []
    when_to_use: Verify an install is structurally ready before a run or after setup changes.
    side_effects: Runs declared validation commands but does not intentionally mutate project state.
    not_when: You need external reachability or fleet provenance diagnosis; use doctor.
    asks: Nothing.
    example: "SPEC-243-001-001: verify root-relative canonical-suite execution from a fresh dispatch."
  - name: knowledge
    one_liner: Add, update, review, or import reusable project knowledge.
    options: ["add <topic>", "update <file>", review, import]
    when_to_use: Capture conventions, lessons, or report-derived knowledge for later runs.
    side_effects: Writes knowledge files for add, update, and import.
    not_when: You are defining requirements for a feature; use spec.
    asks: Topic scope, patterns, and review-persona ownership when creating an entry.
    example: "SPEC-280: record the cache-boundary lesson after the Python-bytecode policy change."
  - name: release
    one_liner: Publish and roll out one exact, validated canonical kit.
    options: ["--dry-run", "--apply"]
    when_to_use: Release an approved canonical managed payload to eligible installs.
    side_effects: --apply can copy payloads and create guarded local commits; it never pushes.
    not_when: You are implementing one spec or need a file-only sync.
    asks: Operator review of dry-run coverage and authorization before apply.
    example: "SPEC-280: roll out the cache-ignore policy only after whole-kit validation."
  - name: unblock
    one_liner: Recover an evidence-blocked spec, optionally driving it toward done.
    options: ["<spec-id>", "--to-done", "--from-rung <2-4>", "--dry-run"]
    when_to_use: A spec is blocked and retained evidence supports the controller-backed recovery path.
    side_effects: Records controlled unblock attempts; --to-done may launch bounded recovery work.
    not_when: The spec is ready and has not yet run; use run or kickoff.
    asks: Authorization only when the ladder reaches a human-only rung.
    example: "SPEC-259: use `unblock SPEC-259 --to-done` to drive to done after cache-integrity evidence."
  - name: kickoff
    one_liner: Start the parent-monitored autonomous loop for one spec.
    options: ["[spec-id]"]
    when_to_use: Run a ready spec with a parent-owned lifecycle, heartbeat, and integration flow.
    side_effects: Marks lifecycle state, launches a worker, records evidence, and may merge an accepted candidate.
    not_when: You only need direct execution guidance without the board-style parent wrapper; use run.
    asks: Nothing unless a genuine ambiguity or missing prerequisite prevents dispatch.
    example: "SPEC-252: launch a monitored parent kickoff with durable terminal-resolution evidence."
  - name: run
    one_liner: Execute the autonomous spec loop directly with the same evidence gates.
    options: ["[spec-id]"]
    when_to_use: Implement a ready spec through the normal isolated-worker workflow.
    side_effects: Marks lifecycle state, launches a worker, records evidence, and may merge an accepted candidate.
    not_when: You need to inspect or edit the spec before execution; use spec.
    asks: Nothing unless a genuine ambiguity or missing prerequisite prevents dispatch.
    example: "SPEC-260: run the AC-review amendment gate through independent verification."
  - name: address-issues
    one_liner: Consolidate and resolve embedded questions from draft or blocked specs.
    options: []
    when_to_use: Draft or blocked specs contain explicit or implied decisions that need resolution.
    side_effects: Writes a persistent QUESTIONS spec and, after decisions, updates eligible source specs.
    not_when: A ready spec has no unresolved question; use run or kickoff.
    asks: One material decision at a time, with options and evidence where needed.
    example: "SPEC-241: resolve a bounded unblock question without rewriting the done source spec."
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

**Copy the entire canonical kit:**

```bash
# Copy all protocol files, templates, and scaffolding. Python bytecode is
# machine-specific derived state and must never enter an install.
rsync -a --exclude='__pycache__/' --exclude='*.py[co]' \
  "$CANONICAL/" .nightshift/
```

This copies:
- All 8 protocol files (BOOTSTRAP.md, LOOP.md, ORCHESTRATOR.md, REVIEW.md, HUMAN-REVIEW.md, WATCHER.md, LOOP-DOMAIN-MAP.md, SPEC-GUIDE.md)
- config.yaml template (blank placeholders)
- Spec templates (specs/_TEMPLATE.md, _TEMPLATE-ANALYSIS.md, _TEMPLATE-RESEARCH.md)
- .gitignore
- Empty directory scaffolding (knowledge/, metrics/, reports/, specs/)

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

Read `references/templates.md` for the config.yaml template format if needed. The copied config.yaml already has the right structure with inline documentation — just fill in the blanks.

**Create additional directories** not in canonical (project-specific scaffolding):

```bash
mkdir -p .nightshift/{scenarios,hooks,prompts,checkpoints}
mkdir -p .nightshift/metrics/_wip .nightshift/reports/_wip
```

**Generate project-specific files** (these ARE generated, not copied):

- `hooks/pre-commit` — reads lint/type_check from the project's config.yaml (use template from `references/templates.md`)
- `prompts/spec-reviewer.md` — adversarial spec compliance reviewer
- `prompts/quality-reviewer.md` — code quality reviewer
- `prompts/completion-checklist.md` — premature victory guard

Offer to install the pre-commit hook (`cp .nightshift/hooks/pre-commit .git/hooks/ && chmod +x .git/hooks/pre-commit`).

Alongside it, offer to install the Claude Code `PreToolUse` write-scope hook
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

1. **Context check** — read `config.yaml`, existing specs (for next ID, current layers), and `knowledge/` files.
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

5. **Write spec** to `specs/SPEC-{ID}-{slug}.md`. Confirm with user before writing. When creating an NFR, reconcile every matched non-done spec; when promoting any spec, reconcile it against every active NFR. Use `audit_nfr.py --check-all` where installed.

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

6. **Post-save for `type: nfr`** — after saving a new NFR spec, run the impact audit:
   ```bash
   python3 .nightshift/audit_nfr.py --nfr-id <new-id> --specs-dir .nightshift/specs/
   ```
   Surface the report to the user. They review the listed non-done specs and decide which ones need `nfrs: [<new-id>]` added.

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

## `/nightshift doctor` — Diagnose Broken or Invisible Installs

Run `"$HOME/Dropbox/Developer/ManagedProjects/Nightshift/canonical/.board-venv/bin/python" "$HOME/Dropbox/Developer/ManagedProjects/Nightshift/doctor.py" <project>` for one install, or add `--fleet` to inspect every configured discovery root plus their shared parent (so sibling projects can be found). Add `--fix` only for mechanical repairs: missing discovery-list entries, absent kit files, and a bootstrap `_eval-project/`. It never overwrites a different existing managed file and never changes spec content, status, project config values, or the Git index. Exit codes are 0 clean, 1 warnings, and 2 CRITICAL findings.

Doctor extends validate: use validate for the install's own protocol/config/command integrity; use doctor for external reachability, kit freshness, bootstrap residue, board reachability, cross-directory spec hygiene, and the read-only managed-payload provenance audit. The audit reports `exact-current`, `retained-prior-release`, or `unresolved-divergence` using per-file hashes only. Preserve unresolved paths and route reusable work through a canonical Nightshift spec and whole-kit release; never infer ownership from timestamps, similarity, status text, or an aggregate fingerprint.

Finding `D7` (WARNING, SPEC-300-003) fires when the kit ships
`hooks/protect-write-scope.sh` but the target repository's common-dir
pre-commit hook does not carry the `# SPEC-300-003 protect-write-scope`
marker — the git write-scope guard is uninstalled there. `doctor --fix` runs
`hooks/install-write-scope-guard.sh` for that repository and records the
action; like every other `--fix` repair, it never edits a pre-commit hook it
does not recognise — the installer's own refusal message becomes the
finding's remedy text, and a human merges the guard into that hook by hand.

Finding `D8` (WARNING, SPEC-300-004) fires when the kit ships
`hooks/write-scope-hook.sh` but the target repository's
`.claude/settings.json` has no `nightshift-write-scope`-marked `PreToolUse`
entry — the Claude Code harness hook is uninstalled there. `doctor --fix`
runs `hooks/install-write-scope-hook.sh` for that repository. If the
repository has no `.claude/` directory at all, the finding still reports —
its remedy is a manual step, and `--fix` does not create `.claude/`
automatically.

**Harness coverage (SPEC-300-004 R8):** `hooks/write-scope-hook.sh` is a
Claude Code `PreToolUse` hook — Claude Code is the only harness in the
current matrix that exposes a pre-write tool hook. Codex and Hermes runs have
no equivalent interception point today; they rely entirely on the git
pre-commit write-scope guard (SPEC-300-003) and the evidence gate
(SPEC-300-002) to catch an out-of-scope write, always after the write has
already landed on disk rather than before. The terminal lifecycle commit's
`Nightshift-Scope-Check:` trailer (SPEC-300 R11 / SPEC-300-002) records the
outcome either way, so a reviewer can tell which layer actually caught (or
missed) a violation regardless of which harness ran the worker.

Even on Claude Code, where the hook does exist and is installed, its
spec-scoped rules are presently unreachable for a harness-launched
(`isolation: "worktree"`) worker — see "Known, accepted gap —
`NIGHTSHIFT_ACTIVE_SPEC` does not reach the `PreToolUse` hook for a
harness-launched worker (SPEC-300-004-001)" under Step 5 above for the
definitive answer and its evidence. Only the hook's two universal rules
fire in that case; the git guard and evidence gate remain the working
backstops.

## `/nightshift validate` — Check Kit Integrity

Verifies `.nightshift/` is well-formed and ready to run. Perform each check, report pass/fail, and provide specific fix suggestions for failures.

### Check 1: Required protocol files

Verify these exist: BOOTSTRAP.md, LOOP.md, ORCHESTRATOR.md, REVIEW.md, HUMAN-REVIEW.md, config.yaml. Optional but recommended: WATCHER.md, LOOP-DOMAIN-MAP.md, SPEC-GUIDE.md. Report each individually.

### Check 2: config.yaml structure

Parse as YAML. Verify required sections exist: `project` (name, language), `commands` (build, test, lint), `review` (enabled), `runner` (mode). Check that no required command is empty string or missing. Flag if `type_check` is empty for typed languages (TypeScript, Python with mypy, etc.).

### Check 3: Commands execution

Run each configured command and check exit codes. Install dependencies first if needed (npm install, pip install, etc.). Report each command's result. Distinguish between "command fails because code has issues" (warning) vs "command not found" (critical — tool not installed).

### Check 4: Spec integrity

For each spec in `specs/`:
- Parse frontmatter: required fields (id, priority, layer, type, status, created)
- Check ID uniqueness across all specs. Fleet-wide ID collisions are warning-only
  findings emitted by `validate_specs.py`; inspect that command's output for
  colliding project paths.
- Check status is valid enum (draft/ready/in_progress/done/blocked)
- For `status: ready` specs: verify all sections exist (Problem, Requirements, AC, Context, Out of Scope)
- Flag specs with requirements but no matching ACs

### Check 5: Dependency resolution

Build dependency graph from `after:` fields. Check for: circular dependencies, references to non-existent spec IDs, layer violations (spec in layer 2 depending on spec in layer 3).

### Check 5b: Duplicate specs

Run `python3 .nightshift/check_followup_spec.py --specs-dir .nightshift/specs --scan-all`. Exit 0 = clean; exit 1 = near-duplicate pairs found (title and/or requirement/AC body overlap above threshold). Report each pair so the user can retire or merge the duplicate. This is the disk-level backstop for duplicates that bypassed the per-suggestion follow-up gate.

### Check 6: Git integration

- Pre-commit hook: exists at `.git/hooks/pre-commit`, is executable, references config.yaml commands
- `.gitignore`: has entries for `_wip/`, `STOP`, `checkpoints/`
- Git repo exists (warn if no `.git/`)

### Check 7: Knowledge health

- Knowledge directory exists with expected subdirs (patterns/, attempts/, _review/)
- Review persona docs exist in `_review/` if personas are enabled in config
- Flag empty knowledge files (created but never populated)

**Output format:** Per-check pass/fail table, then detailed findings with specific fix commands the user can run.

---

## `/nightshift knowledge` — Manage Knowledge Base

### `add <topic>`
Guided creation of a new knowledge/ file. Ask what the topic covers, what patterns or lessons to capture, and which review persona (if any) owns it.

### `update <file>`
Read existing entry, ask what changed, update it.

### `review`
Check all entries for staleness — if specs have been completed since the knowledge file was last updated, flag it. Suggest updates based on recent reports.

### `import`
Read recent Nightshift reports and metrics. Extract lessons (what failed, what worked, what patterns emerged) and add them to knowledge/ entries or create new ones.

---

## `/nightshift release` — Publish and Roll Out One Exact Kit

Use this command only from the canonical Nightshift repository. The release unit
is the whole managed kit; never add or simulate a file-only release.

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

### Step 2: Fleet dry-run

Each project's `.nightshift/config.yaml` must declare:

```yaml
release_policy:
  committed_kit: allow  # or: opt_out
```

`allow` keeps the existing guarded local-commit path. `opt_out` is a known
project-local skip: the coordinator leaves that whole repository untouched and
continues independent repositories. Commit hooks that own a compatible explicit
policy may expose it with an executable commit-hook marker:

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

Review exact repository/install coverage. Divergence inside the exact manifest
payload is expected and never needs provenance reconstruction: release replaces
those files deterministically. An unrelated pre-staged path or dirty
project-owned migration path skips that whole repository. Do not clean, stash,
overwrite, or stage project-owned work to make a repository eligible.

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

If a prior apply stopped after copying or staging, rerun the same exact release.
Canonical payload replacement is idempotent, and the coordinator re-verifies
the marker, staged allowlist, and project-owned configuration boundary before it
commits. Never infer that an install is synchronized from a partial copy.

Write the final report and structured metrics with:

- planned, verified, skipped and untouched installs/repositories;
- old/new fingerprints and producer-session payload hashes;
- known versus unexpected failure classification;
- migration worker evidence and local commit IDs;
- canonical-suite/smoke counts, duration and observable post-commit rebuild time;
- the exact safe rerun command.

The operator decides separately when/if local commits are pushed.

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

The default command is **unblock**: one bounded repair whose only lifecycle
success is `blocked -> ready`. The opt-in `--to-done` mode is **drive to done**:
the parent advances a sequential evidence ladder toward the ordinary fresh-main
`done` gate without giving workers lifecycle or merge authority.

| Option | Meaning |
|---|---|
| `--to-done` | Opt into drive to done: bounded repair, work-to-done, per-AC coverage/runtime capture, gated AC review, then human authorization. |
| `--from-rung <2-4>` | Begin drive to done at an explicitly selected rung; no prior failure is fabricated. |
| `--dry-run` | Print the ladder plan and admission verdict without mutation, worker launch, or commit. |

Drive to done calls `unblock_ladder.py`, which in turn calls `unblock_spec.py`.
Rung 1 is the default unblock flow. A failed or skipped rung 1 enters rung 2;
rung 2 gives an evidence-only implementer the blocker packet, prior attempts,
and resilience ladder. Rung 3 records per-AC `covered-by` or
`runtime-captured` evidence without changing AC text. Rung 4 calls the SPEC-260
AC-review agent when available; until then it records `unavailable` and routes
to rung 5. Rung 5 stops and asks the user to authorize. Every entered rung emits
an `unblock_rung` event, and the terminal lifecycle commit records
`Nightshift-Unblock-Rung: <n>`.

Rung 4 dispatches the independent `nightshift-ac-reviewer` with the proposed
per-AC changes, blocker packet, attempt history, and rung-3 evidence—not the
implementer's narrative. It writes `reports/<SPEC>/ac-review.json`, which must
pass `ac_review.py validate`. A veto (or invalid verdict) followed by continued
failure routes to rung 5; the parent never loosens an AC past a veto.

`prepare` is the admission gate. A non-blocked, invalid, missing-evidence, stale,
or unchanged-fingerprint spec is reported as ineligible: no worker/worktree is launched.
An `eligibility: skipped` packet is recorded with `record_attempt` as a
controlled escalation; external input, credentials, product decisions,
security/safety, destructive work, scope changes, and ambiguous causality never
dispatch automatically.

Under drive to done only, skipped rung-1 eligibility carries `escalate: true`
and enters rung 2. Without `--to-done`, skipped eligibility ends unblock exactly
as before.

For an eligible packet, the parent may launch exactly one isolated, bounded worker.
Its brief contains the packet verbatim: exact blocker, evidence paths and hashes,
prior attempts, intervention boundary, guardrails, and verification command. The
worker must not change lifecycle state or merge; it returns only intervention and
verification evidence. The parent calls `record_attempt`, then `finalize`, remains
the sole lifecycle and merge owner, and only a verified success can transition
`blocked -> ready`. A new ordinary kickoff may begin only after that transition.

The operator result and run report list eligibility, attempt result, causal
confidence, evidence references, and whether human action is needed. Do not expose
raw logs, secrets, or private-local paths. Explain “why it worked” only from the
controller record: `demonstrated`/`supported` require before/after evidence;
otherwise say `not_established` rather than infer a cause.

For agent-local mandatory tooling, record the controlled recovery events in the
existing run event stream and use this single bounded ladder: capability probe,
smallest safe repair, post-repair probe, then one fresh-worker or transport
rebind probe if the original process is stale. The parent alone owns lifecycle
and integration; replacement workers return evidence only. Do not terminally
block on a single cached tool failure: `evidence_gap` requires recorded viable
alternatives that were unsafe, ineligible, externally authorized, or exhausted.
Inside an ordinary kickoff, the parent also exhausts the SPEC-266 in-loop
resilience ladder before terminal `blocked`: verifier failures require measured
failed-AC shrinkage before a second remediation; premise disputes scan coverage
and runtime gates before independent AC review; a done-claim evidence gap gets
one read-only collection pass; and a changed tool/fresh worker may use one more
transport rebind. Each rung is run-id keyed and recorded as `resilience_rung`.
When private Dropbox projection is configured, project only the hash-based run
manifest and approved relative references. `awaiting_sync` is observable but
does not alter the evidence gate or lifecycle result.

## `/nightshift kickoff [spec-id]` — Parent Kickoff Wrapper

The parent retains the successful installation admission's integrity receipt.
When the worker returns, it invokes
`managed_payload_provenance.verify_terminal_integrity` with that original
receipt before verifier-result acceptance, lifecycle terminalization, merge,
post-merge validation, or worktree cleanup. A fresh admission is not a valid
replacement. Deny or indeterminate preserves the worker branch/worktree and
routes the release-owned path to its canonical path/spec plus whole-kit release;
the parent never resets, checks out, bulk-copies, deletes, or auto-repairs it.

Use this command when a board-copied prompt or human explicitly wants a parent
agent to start and monitor a Nightshift run without doing implementation work.

`/nightshift kickoff <spec-id>` is a wrapper around `/nightshift run <spec-id>`
with `kickoff_parent: true`.

The parent kickoff agent:
- invokes the `/nightshift run` flow below,
- resolves the explicit state policy and records `in_progress` on main before launch
  (commit-backed lifecycle commit or private-local durable event),
- launches or coordinates the run/orchestrator agent,
- injects the **Kickoff Parent Context** section into the launched agent brief,
- monitors progress while the run is active,
- dispatches an independent `nightshift-verifier` when the run resolves and audits
  its structured verdict with the Step 5c validator, rather than re-deriving the
  evidence in its own context,
- autonomously resolves the run at completion: verifies evidence, merges and
  cleans up if sufficient, or invokes the controller-backed unblock protocol
  before a terminal blocked escalation.

The parent kickoff agent does **not** implement, research, validate, or code the
spec directly. The run/orchestrator agent owns Nightshift startup, instruction
packet generation, context loading, implementation, validation, metrics, reports,
and commits.

This wording is intentionally platform-neutral. In Claude, use the available
Agent/subagent mechanism. In Codex, use the available agent/delegation mechanism.
If no subagent mechanism is available, report that limitation before falling back
to inline execution.

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

### Step 1: Resolve spec

**If `spec-id` provided:**
- Find `specs/SPEC-{spec-id}-*.md` (or exact filename match)
- Validate `status: ready` — if not, error with current status and a suggestion (e.g. "status is draft — promote it with `/nightshift spec` first")

**If no `spec-id`:**
- Scan all specs for `status: ready`
- Sort by layer (ascending), then priority (ascending)
- Show user which spec was selected and ask to confirm before proceeding

If no ready specs exist, report the queue state and exit.

**NFR reconciliation check (MANDATORY before launch):** Read the canonical
`SPEC-GUIDE.md` transition gate. Reconcile the selected spec against every
active NFR: bind each mechanical match in `nfrs:` (the NFR or its parent), or
record `nfr_waivers: [{id, reason}]` with a non-empty reason. Run
`python3 audit_nfr.py --check-all --specs-dir specs/` where that helper is
installed. This applies equally to `/nightshift run` and its `/nightshift
kickoff` wrapper; do not duplicate or weaken the canonical rule here.

**Dependency drift check (MANDATORY, after resolving, before any other work):**

The frontmatter `after:` field can drift from what the spec body actually says. A spec body might describe "blocked on FART-DS-019" while `after:` is empty — the formal dependency check then says "ready" even though the work genuinely depends on something unfinished. Catch this here so the agent never launches with stale dependency info.

Scan the spec body (everything after the `---` frontmatter delimiter) for spec IDs that match the project's ID pattern (e.g. `FART-DS-\d+`, `SPEC-\d+`) inside any of these dependency-implying constructions:

- `blocked on <ID>` / `blocks on <ID>`
- `depends on <ID>` / `depend[s]? on <ID>`
- `after <ID>` (when used as a verb/preposition, not part of an unrelated sentence)
- `needs <ID>` / `requires <ID>` / `prerequisite[:]? <ID>`
- `embeds <ID>` / `built on <ID>` / `built atop <ID>`
- `wait[s]? for <ID>` / `waiting on <ID>`
- Any "Context" / "Background" / "Problem" section that lists another spec ID with a dependency-implying verb

For each ID found in the body but **NOT** present in the frontmatter `after:` array:

1. Show a clear warning:
   ```
   ⚠ Drift: spec body mentions {ID} as a dependency, but it is not in `after:`.
     Found in: "<10-word excerpt around the match>"
     Frontmatter `after:` currently: [<existing list>]
   ```

2. Ask the user (do **not** auto-fix — prose can be loose, e.g. "inspired by X" or "see also X"):
   ```
   How to proceed?
   (a) Add {ID} to `after:` on main, commit, and continue
   (b) Abort the run so I can review and decide whether the prose or the frontmatter is wrong
   (c) Skip this warning and proceed anyway (rare — only when the prose is informational, not a real dependency)
   ```

3. If (a): edit the spec frontmatter, `git commit -m "chore: declare {ID} as dependency of {spec-id}"`, then re-resolve from Step 1 (the new dep might itself need running first).
   If (b): exit with a one-line summary of the drift and how to fix.
   If (c): proceed but record the decision in the run's log so the post-run review can flag it.

This step exists because spec authors describe dependencies in prose first and forget to mirror them in the frontmatter. The agent that picks up the spec then either silently runs into the missing prerequisite, or — if it's clever — re-discovers the dependency by reading prose (which works but is fragile). A deterministic pre-flight check beats both.

### Step 2: Mark spec `in_progress` on main (EXECUTE NOW — before anything else)

#### Advisory spec-ownership claim (SPEC-178 — parent-owned)

Before the status/branch/agent mutation below, the **parent coordinator** obtains
an advisory claim for the selected spec's resolved absolute path. This is a
coordination guard, not a distributed lock: an unavailable coordinator records a
warning and the kickoff continues.

1. Retain one local coordinator session ID for this kickoff. A newly started
   session uses `local_session_start(harness, label="nightshift-{spec-id}",
   focus="Nightshift kickoff {spec-id}")`; a resumed parent reuses its existing
   session ID. The label is deliberately spec-specific, so `local_session_list`
   alone distinguishes concurrent Nightshift runs.
2. Call `local_session_list_claims()` and find a non-expired claim whose `path`
   exactly equals the resolved absolute spec path. If another session owns it,
   call `local_session_list()` to resolve the owner label, then halt **before**
   changing status, creating a branch/worktree, or launching an agent. State the
   owning session ID, its label, and the claim age. If this coordinator already
   owns the claim, continue with claim state `reused` (same-session re-entry is
   idempotent).
3. With no matching live claim, call
   `local_session_claim_path(session_id, absolute_spec_path,
   purpose="nightshift kickoff {spec-id} run {run-id}", ttl_minutes=30)` and
   record claim state `acquired`. The purpose must contain the spec ID.
4. If any coordinator operation is unreachable or errors, record claim state
   `skipped` plus the error in the heartbeat and eventual report, then continue;
   never turn this advisory outage into a failed or hung kickoff.

The selected spec path, coordinator session ID, TTL, and claim state belong to
the parent kickoff state (not the worker brief). At each Step 5b heartbeat beat,
the parent calls `local_session_renew_claim(session_id, absolute_spec_path,
ttl_minutes=30)`. A renewal failure is a warning and does not stop the run.

On every terminal path in Step 6 (`done` **or** `blocked`), the parent calls
`local_session_release_claim(session_id, absolute_spec_path)`. It records a
release failure as a warning but still completes the terminal lifecycle state.
The report must state `Claim: acquired`, `Claim: reused`, or `Claim: skipped`,
and include any claim/release warning.

**One-call ownership answer.** When asked who owns an `in_progress` spec, the
coordinator performs this bounded ownership query and returns one verdict: first
match `local_session_list_claims()` by the resolved absolute path; for a live
match, enrich it from `local_session_list()` with owner session ID, label, and
age. With no live claim, inspect only the matching branch and verified worktree.
If neither exists, return explicit **unowned** — never infer ownership from the
stored `in_progress` marker. Skip `_`-prefixed template files when scanning
specs. Coordinator outage returns **unknown (claim service unavailable)**, never
an unsafe `unowned` verdict.

> **This is the very first action after resolving the spec. Read only
> `nightshift_state.policy` first, using `private_state.py policy`; an invalid value
> stops before mutation or launch. Missing means `commit-backed`. Do not infer mode
> from `.gitignore` or remote visibility.**

#### Commit-backed (default)

Execute the existing three actions below. Each is a separate tool call.

**2a. Edit the spec file:**

```
Edit({
  file_path: "<absolute path to>/specs/<spec-id>-*.md",
  old_string: "status: ready",
  new_string: "status: in_progress",
})
```

(If the spec is already `in_progress` from a prior aborted run, skip 2a and go directly to 2a2. Do not regress the status.)

**2a2. Record the SPEC-291 transition artifact — before the commit.** This
edit is a mechanical `ready -> in_progress` transition, so its reason
synthesizes from the run ID with no prose required. Run this *before* 2b so
the artifact file exists on disk to be staged in the same commit — writing it
after would leave it untracked, which corpus validation would then flag as an
orphan/untracked finding on the very next run:
```bash
python3 .nightshift/spec_artifacts.py record-transition <spec-file> \
  --from ready --to in_progress --run-id <run-id>
```
A non-zero exit means the transition was classified as a judgment transition
(unexpected for `ready -> in_progress`) — pass `--reason "<why>"` and retry
rather than skipping this step; it is what R3 makes durable and what Step 6
below, and the board panel, both read back.

**2b. Commit on main with the spec file and its artifact directory staged.**
The artifact directory is a sibling of the specs directory's `reports/`, not
bare `reports/` from the project root — `.nightshift/reports/<spec-id>/artifacts/`
in a deployed project, `canonical/reports/<spec-id>/artifacts/` in this kit repo:

```
Bash({
  command: "cd <project-root> && git add <relative spec path> <specs-dir-sibling>/reports/<spec-id>/artifacts/ && git commit -m 'chore: mark <spec-id> in_progress'",
})
```

If `git status` shows other staged changes from earlier work, **stash them first** (`git stash push --staged`) so this commit is clean. Restore the stash after launch.

**2c. Verify the commit landed — HARD GATE:**

```
Bash({
  command: "cd <project-root> && git log --oneline -1",
})
```

The output must show `chore: mark <spec-id> in_progress` as the latest commit. If it does not, the commit failed silently — stop and investigate. **Do not proceed to Step 3 until you see this commit in `git log`.**

The board picks up the status change within ~10s of the commit.

#### Private-local (explicit opt-in)

The parent coordinator calls `transition_private_state(..., "in_progress",
owner="coordinator", assigned_spec=<spec-id>)` from the installed
`private_state.py`, using `StatusStore.for_specs_dir`. Record its returned
`run_id`; that durable local lifecycle event replaces the lifecycle commit proof.
Verify all of the following before Step 3:

- frontmatter and the status reader both show `in_progress` with the same run ID;
- `HEAD` and `git write-tree` are byte-for-byte unchanged;
- `private_state.py privacy-check` passes for every configured private path.

Never stage or force-add private Nightshift state. A worker cannot own this call.

Run 2a2 here too, exactly as above — the artifact is a spec-side record, not
private state. Unlike commit-backed, private-local makes no lifecycle commit
at all (`HEAD`/`git write-tree` stay byte-for-byte unchanged), so the artifact
file lands on disk untracked until a later ordinary commit (e.g. the run's own
implementation commit) picks it up; do not force a commit here solely to
track it, since that would break the byte-for-byte invariant above.

### Step 3: Read config

Read `.nightshift/config.yaml`:
- `runner.mode` — `inline` or `orchestrator`
- `commands.build`, `commands.test`, `commands.lint`, `commands.type_check`
- `project.language`, `project.name`
- `circuit_breaker` thresholds

If config.yaml is missing or unreadable → error: "Run `/nightshift validate` first."

### Step 3b: Bind the stable observational checkpoints

Both normal `$nightshift run` and `$nightshift kickoff` use the same mandatory
standalone launcher. This is the executable binding for SPEC-230; prose
mentioning an event is not publication. Invoke it as a new process exactly at
the five boundaries named below. Do not define a shell function or depend on
variables from an earlier fenced block: shell state does not persist across
agent tool calls.

For every command below, replace `{RUN_ID}` with the already-durable run ID from
Step 2, `{SPEC_ID}` with the resolved exact spec ID, and `{RUN_KIND}` with the
literal `run` for `$nightshift run` or `kickoff` for `$nightshift kickoff`.
Those three values remain identical for all five calls. Never execute a command
that still contains braces. The launcher discovers its private/configured
roots, chooses a PyYAML-capable runtime, records failures privately, and always
returns success on an extension-side failure; it never replaces the
authoritative run result.

Immediately after the durable `in_progress` state and run ID exist, execute:

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event run.started --outcome unknown
```

Each later block independently invokes the same launcher. It derives the next
contiguous sequence from the durable spool, so paths that do not reach a
checkpoint do not fabricate it. When approved artifact references exist, place
their closed JSON list in an ignored/private file, set the private
`NIGHTSHIFT_EXTENSION_ARTIFACT_ROOT`, and append
`--artifact-refs-file <private-file>` to that one invocation; raw artifacts stay
below the private artifact root.

### Step 4: Scaffold agent brief

Auto-generate the brief the agent will receive.

**a. Extract from spec frontmatter:**
- `id`, `layer`, `type`
- `after:` dependencies (mention as context, not blockers)
- `prior_attempts` — if any, include them: "Previous attempts: [list]. Do not repeat these approaches."

**b. Extract from spec body:**
- Problem section → brief Problem
- Requirements section → brief Requirements (verbatim)
- Acceptance Criteria → brief AC (verbatim)
- Context section → target files, test files, framework

**b1. Include the artifact-index summary when one exists (SPEC-291).** Read
`reports/<SPEC-ID>/artifacts/index.json`, if present, and add one line per
entry (`type` / `created` date / `summary`) to the brief under an "Artifact
history" heading — so the agent starts from why prior transitions happened
instead of re-deriving it. Absent or empty is silently skipped, never an
error (R7: most specs have no artifact history yet).

**c. Auto-map DevKB files** from spec `technologies` field using the DevKB Mapping Table in Implementation Notes. If the spec has no `technologies` field, detect from target file extensions (`.py` → python.md, `.swift` → swift.md + xcode.md, `.ts/.js` → shell.md, etc.).

**d. Populate Build & Verify** from `config.yaml` commands.

**e. Add standard boilerplate:**
```
- Read `.nightshift/BOOTSTRAP.md` first — it defines how to start a run
- Follow `.nightshift/LOOP.md` for the spec→implement→test→review→commit cycle
- Work only on spec {spec-id}. Do not touch other specs or unrelated files.
- Declared write scope: {scope.write, or "project root (no scope: declared)"}. An
  enforcement point that denies a write names the offending path and this scope;
  retry inside the declared scope first. If the write is genuinely needed outside
  it, do not perform it — record the path/reason under `## Scope Blockers` in the
  run report and return `worker-blocked` (SPEC-300 § Enforcement); scope only
  widens through a human-approved `## Scope Amendments` row on main. **This is a
  mechanical gate precondition, not just an audit trail (SPEC-302 R1):** if
  `scope.write` (or `deny`/`read`) on main is edited directly — widened with no
  covering `## Scope Amendments` row dated on or after that widening and carrying
  `Approved by: human` (or `human:<name>`) — `scope_guard.scope_from_main` does
  not honor the widened value for enforcement; it falls back to the narrower
  value that was in effect the last time the spec was `ready`. A pure narrowing
  (removing a `write` glob, adding a `deny` glob) never needs a row and always
  takes effect immediately (R2). Both the evidence-gate check 6 script below and
  the git pre-commit guard (SPEC-300-003) read scope exclusively through this one
  reconciling function (R3), so this precondition applies identically at both
  layers. A spec that has never had its scope widened, or whose `## Scope
  Amendments` table has always been empty, is unaffected (R5). SPEC-302-001
  closed two residual gaps in this same mechanism: a widening committed while
  `status:` stays `ready` (never passing through `in_progress`) can no longer
  become its own reconciliation baseline, and a commit that both narrows and
  widens the *same* field no longer un-drops the narrowed-out item as a side
  effect of blocking the uncovered widening.
- Commit your changes — the parent will review and merge the worktree branch.
- **Every `git commit` in this run MUST be prefixed with `NIGHTSHIFT_ACTIVE_SPEC={spec-id}`
  in the exact same shell invocation**, e.g.
  `NIGHTSHIFT_ACTIVE_SPEC={spec-id} git commit -m "..."` (SPEC-301). Your branch
  name is harness-assigned (`worktree-agent-<hex>` when launched with
  `isolation: "worktree"`) and does not encode the spec ID, so the git
  pre-commit write-scope guard (SPEC-300-003) cannot resolve the active spec
  from the branch name alone — without the inline env var it silently falls
  back to `no_active_spec` (allow, not a false deny, but also not enforcing
  your declared `scope.write`). A bare shell `export NIGHTSHIFT_ACTIVE_SPEC=...`
  does NOT help if your tool issues each command in a fresh shell — verify
  this for your own harness before relying on it, and prefix every commit
  inline regardless. This only reaches the git-guard layer; it does not
  retroactively affect any other enforcement point that resolves the active
  spec independently (e.g. a `PreToolUse` hook spawned by the harness itself
  reads its own environment, not this shell's).
- If you touch a file that is itself a member of `nightshift-sync.py`'s
  `CANONICAL_PROTOCOL_FILES` (i.e. your `scope.write` already legitimately
  includes a managed canonical-payload file), you do **not** need to add
  `release-manifest.json`/`CHANGELOG.md` to `scope.write` by hand —
  `scope_guard.py` implicit-allows both for you in that case
  (SPEC-300-001-001). Regenerate the manifest via
  `release.write_manifest(canonical_path, CANONICAL_PROTOCOL_FILES)` before
  your final commit regardless, and verify hashes with `shasum -a 256`
  against every file you edited — a stale manifest checksum breaks
  `release.apply_install()`'s verification everywhere it's exercised (SPEC-301).
- Circuit breaker limits: {max_same_errors} same errors, {max_review_cycles} review cycles, {timeout_minutes} min total
- Do NOT use Write tool for existing files — use Edit with precise replacements
- Do NOT guess API names — grep existing code first
- One fix at a time, one build at a time — do not stack changes
- MANDATORY: After completing the spec, write a human review report to
  `reports/YYYY-MM-DD-nightshift-report.md` (Step 14 of LOOP.md).
  This is NOT optional. A run without a report is an incomplete run.
  The report must include, verbatim as headings, matching LOOP.md Step 14's
  canonical template exactly (not a paraphrase): summary stats, per-spec
  changes, test results, AC checklist, a `## Blocked Specs` section, an
  `## Open Questions` section, and a `## Report Action Log` section — each
  states its content, or the literal word `None`/a `none_found` row when
  empty, never omitted. Also include any other blockers or discoveries.
```

**f. If `kickoff_parent: true`, add this section to the launched agent brief:**
```markdown
## Kickoff Parent Context

You were launched by a parent kickoff agent. The parent agent is monitoring this
run and will not implement the spec directly.

You are the run/orchestrator agent. You own Nightshift startup, instruction
packet generation, context loading, implementation, validation, metrics, reports,
and commits.

You run in an isolated git worktree, so the parent CANNOT see files inside your
worktree while you work. To stay observable, publish your heartbeat to the SHARED
progress file at the absolute path the parent gave you — it points into the MAIN
checkout (outside your worktree), under `_wip/` (gitignored, so no commit/merge
conflict):

`{progress_file_abs}`  (= `<main-repo>/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md`)

**Hard cadence rule — the parent enforces this:** the heartbeat file MUST advance
at least once every 20 minutes. If 20 minutes pass with no update, the parent
treats the run as stalled and may stop it. Update at each major phase or every
~10 minutes during long compute, whichever comes first — never let the file go
quiet for 20 minutes, even mid-step (write "still working on X, no new commit yet"
rather than nothing).

Each update OVERWRITES the file with: current phase, last completed action, next
action, latest commit SHA on your branch (so the parent can confirm forward motion
without seeing your worktree), an ISO-8601 UTC timestamp, blockers/stuck signals,
and latest evidence paths.

**Worktree-isolation write method — required:** `Write` and direct shell
redirection (`>`) to `{progress_file_abs}` are rejected because that path is
outside this worktree. Write the complete heartbeat to a worktree-local file,
then use `/bin/cp` to publish it to the shared path:

```bash
HEARTBEAT_LOCAL="$PWD/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md"
mkdir -p "$(dirname "$HEARTBEAT_LOCAL")"
# Produce the complete update locally. Its first line must be:
# heartbeat_state: worker-started
/bin/cp "$HEARTBEAT_LOCAL" "{progress_file_abs}"
```

The first successful `/bin/cp` replaces the parent seed's
`heartbeat_state: parent-seeded` marker. A seed that never gains
`heartbeat_state: worker-started` means **heartbeat never started**; a stale
file that does contain `worker-started` means **heartbeat stalled after start**.
Do not attempt another external write mechanism.

**`heartbeat_state` — controlled vocabulary.** The field is the file's **first
line** and takes exactly one of four values. Nothing else is a valid state:

| Value | Meaning | Written by |
|---|---|---|
| `parent-seeded` | file created at launch; the worker has not written yet | parent, Step 5 |
| `worker-started` | the run is live — **non-terminal**, the watchdog keeps measuring staleness | run agent |
| `worker-done` | the run finished its work — **terminal** | run agent |
| `worker-blocked` | the run stopped and cannot proceed — **terminal** | run agent |

`worker-done` and `worker-blocked` are the terminal set. **Before you return, your
final heartbeat MUST carry a terminal value on line 1.** A run that finishes while
still at `worker-started` is byte-for-byte indistinguishable from a hung one, and
the Step 5b watchdog will correctly report it as a stall — the false-alarm case
this vocabulary exists to remove. Write `worker-done` when you completed the work
(including a clean no-change outcome) and `worker-blocked` when you are handing
back a blocker.

Only line 1 is read. Naming a terminal value further down the file — in a "next
action" line, a quoted log, an evidence path — does **not** end the run and is not
read as terminal. Do not invent spellings (`worker-complete`, `done`, `finished`):
an unrecognised value is treated as non-terminal.

If you believe the spec is blocked or cannot proceed, report the exact blocker,
what you already tried, the latest evidence paths, and the smallest bounded
recovery task that should be attempted next. The parent kickoff agent may use
that to invoke the controller-backed unblock protocol before a terminal blocked
status is committed.
```

**g. Git-mutation-evidence preflight (SPEC-309, R1/R2/R4) — check before Step 5, not after
a failed dispatch.** Read this spec's Live Execution Checklist and Acceptance Criteria: do any
of them require a real git commit-class operation — `git add`, `git commit`, `git worktree add`,
or any mechanism that only fires at commit time (a pre-commit hook, a branch-naming convention
check)? If so, **a worktree-isolated worker cannot reliably execute it.** The sandbox's `rtk`
wrapper refuses bare `git status`/`git log`/`git commit` invocations, with byte-identical refusal
wording whether the target is the agent's own assigned worktree or a wholly disposable scratch
repository the agent built itself with no connection to the real project's git state (confirmed by
direct probe, 2026-09-06) — **this is a static command-shape parse check, not a target- or
mutation-aware boundary**: bare `git add .` (a real mutation) succeeds unrefused against an
external scratch repo in the same probe. A sanctioned `dangerouslyDisableSandbox: true` escalation
on the same command is refused identically; this is a platform boundary, not a bug to route around.
Three specific things must never be done in response to this refusal:
1. Do not suggest, and a worker should not attempt, an absolute-path invocation like `/usr/bin/git`
   in place of bare `git` as a workaround — that is a different, narrower fix for a *different*
   problem (BUG-019's compound/aliased commands), see the BUG-021 worked example under Step 5c.
2. Do not pipe (`| cat`, `| head`) or redirect (`>`) a git invocation to get around this refusal.
   That shape change bypasses the refusal outright — including for real `git commit` against a
   repository wholly external to the agent's own worktree — which means it evades an isolation
   guarantee, not merely an inconvenient control. See BUG-310 for the full finding; treat any
   dispatched agent that does this as having violated the sandbox boundary, not worked around an
   inconvenience.
3. Do not wrap the invocation in a subprocess call from another language (e.g. Python's
   `subprocess.run(["git", ...])`) to get around this refusal, even for a read-only command. This
   is a third observed bypass form (BUG-310, discovered during BUG-313), consistent with the same
   static command-shape parse mechanism rather than a new boundary — the wrapper's check keys off
   the literal `git ...` command-line shape it is asked to run directly, not any semantic property
   of the invocation, so any indirection that changes that literal shape bypasses it. Treat this
   identically to item 2: a dispatched agent that does this has violated the sandbox boundary, not
   found a sanctioned workaround, regardless of whether the wrapped command was itself read-only.

- **Sanctioned fallback (R2):** the coordinator (the top-level, non-isolated session) executes the
  live proof directly instead of a worktree-isolated worker. The completion report must name this
  explicitly — e.g. "executed by the coordinator, not a worktree-isolated worker, because
  `<spec-id>`'s evidence requires a real `git commit`" — rather than silently reading like ordinary
  worker output.
- This does not lift or route around the sandbox restriction itself (Out of Scope, SPEC-309 R5) —
  it only means the coordinator anticipates the constraint before dispatch instead of discovering
  it mid-run after burning a worker turn.
- See Step 5c's verifier-brief guidance (R3) below for the matching independent-verification-side
  handling — the same limitation applies to a dispatched `nightshift-verifier` trying to
  independently re-execute the same evidence.

**Runner mode variation:**
- `inline` — agent processes this spec only, returns when done
- `orchestrator` — after completing this spec, agent picks the next `ready` spec by layer+priority and continues until the queue is empty or circuit breaker trips

Print the scaffolded brief to the user (as FYI context), then proceed immediately to Step 5. Do NOT ask for confirmation — the user already stated intent by invoking `/nightshift run` or `/nightshift kickoff`. Only stop and ask if something is genuinely unclear or missing (e.g. ambiguous spec body, unresolved dependency drift from Step 1, missing required config values).

### Step 5: Launch agent

> **Precondition — verify before calling Agent():** for `commit-backed`, run
> `git log --oneline -1` and confirm the latest commit is `chore: mark {spec-id}
> in_progress`. For `private-local`, confirm the matching durable `in_progress`
> event/run ID and unchanged HEAD/index. If the selected proof is absent, return
> to Step 2. Do not proceed.

**Worktree path and project-ownership gate:** harness-managed `isolation: "worktree"`
is preferred. If the platform requires the parent to create a worktree manually, obtain
its path from the target project's installed resolver—never construct a sibling path
such as `<project>-nightshift-*` and never put it below the synchronized checkout:

```bash
WT=$(python3 <main-repo-abs>/.nightshift/worktree_paths.py plan \
  --repo <main-repo-abs> --spec {spec-id})
git -C <main-repo-abs> worktree add -b nightshift/{spec-id}-<run-id> "$WT"
python3 <main-repo-abs>/.nightshift/worktree_paths.py verify \
  --repo <main-repo-abs> --worktree "$WT"
```

The verify command is a hard gate before launch, merge, or cleanup: it proves the
worktree shares the intended project's Git common directory. A path/ownership failure
stops the run; do not fall back to a Dropbox sibling. After a successful merge, remove
the worktree and branch immediately as required by Step 6.

**Branch-name active-spec resolution (SPEC-301):** the `nightshift/{spec-id}-<run-id>`
branch shape above is only produced by the manual `git worktree add -b ...` path
just shown. A harness-managed `isolation: "worktree"` launch assigns its own
branch name independently of this convention (observed in this repository:
`worktree-agent-<hex>`) — `scope_guard.py`'s `active_spec()` cannot and does not
try to parse a spec ID out of that shape (no derivable relationship exists between
a harness-assigned hex ID and any spec ID). Every worker brief's Step 4e
boilerplate compensates by requiring `NIGHTSHIFT_ACTIVE_SPEC={spec-id}` inline on
every `git commit`; do not assume branch-name parsing alone enforces `scope.write`
for a harness-launched worker.

**Subagent coverage (SPEC-300-004 R7):** the write-scope `PreToolUse` hook is a
project-level Claude Code setting, not a per-worker one — when it is installed
in `<project>/.claude/settings.json`, it fires for every tool call a worker
launched with `isolation: "worktree"` makes from that project, including a
worker whose own worktree carries no `.claude/settings.json` of its own. A
worker whose settings happen to omit the hook (a harness that doesn't read
project settings, or a project that never ran the installer) still meets the
write-scope contract through the git pre-commit guard (SPEC-300-003) and the
evidence gate (SPEC-300-002) — the hook is the earliest layer, not the only
one.

**Known, accepted gap — `NIGHTSHIFT_ACTIVE_SPEC` does not reach the
`PreToolUse` hook for a harness-launched worker (SPEC-300-004-001):** the
parent's own Agent-launch tool (the `Agent({...})` call shown in Step 5) has
no parameter for setting an environment variable, or any other durable
per-session value, for the launched subagent's whole session — its schema
exposes only `description`, `isolation`, `mode`, `model`, `name`, `prompt`,
`subagent_type`, and `team_name`. This was checked directly against the
launch tool's own schema (not inferred), so it is a confirmed answer, not an
open question. A worker's own Bash tool calls cannot substitute for this
either: SPEC-301 confirmed empirically that a shell `export` in one Bash tool
call does not persist into the next — the harness issues each Bash call in a
fresh shell. Combined with the branch-name finding directly above (a
harness-assigned `worktree-agent-<hex>` branch carries no spec ID for
`scope_guard.py` to parse), this means **`scope_guard.py`'s `active_spec()`
has no working input for the `PreToolUse` hook on a harness-launched kickoff
today** — neither `NIGHTSHIFT_ACTIVE_SPEC` nor branch-name parsing resolves
the active spec at that layer, so it falls back to `no_active_spec` (allow)
for every real kickoff, which in turn means the hook's *spec-scoped* `write`/
`deny`/`read` rules never actually deny an out-of-scope write today. This is
not a false-deny risk (R4: a resolution failure always falls open, never a
false deny) — it is a coverage gap. The hook's two **universal** rules (the
spec-home guard and the malformed-target guard, which do not depend on
`active_spec()` resolving anything) still fire normally and are unaffected.
The two layers that remain fully working for spec-scoped enforcement on a
harness-launched kickoff are the git pre-commit guard (SPEC-300-003, via the
inline `NIGHTSHIFT_ACTIVE_SPEC={spec-id}` commit-prefix convention above,
which the guard reads directly from the `git commit` subprocess's own
environment) and the parent's evidence gate (SPEC-300-002). No fix is
available at the harness layer today (SPEC-300-004-001 R1/R3); this is
recorded as a known, accepted limitation, not a silent one.

In `private-local`, after this verification and before launch, invoke
`project_private_state` with an explicit allowlist containing only the selected
spec, installed runtime/protocol, project configuration, and required knowledge.
The destination must remain ignored. Before merge, call `return_private_evidence`
with only report, metrics, verification artifacts, and heartbeat paths declared by
the run contract, then run `privacy-check --base-ref <main-ref>` on the worker.
Any tracked/staged/diff private path refuses integration and preserves the worktree.

Before launching, compute the absolute heartbeat path and substitute it for
`{progress_file_abs}` in the brief: `<main-repo-abs>/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md`.
Create the `_wip/` dir if missing, then **seed the heartbeat file now with an
initial ISO-8601 timestamp and `heartbeat_state: parent-seeded` line** so the
staleness clock starts at launch — this catches a run that hangs before it ever
writes its first heartbeat (the watchdog needs the file to exist to measure
staleness). This marker also makes a never-started heartbeat distinguishable from
one that started and later stalled. This is the shared file the parent watches in
Step 5b — both parent and run agent use this exact absolute path.

Launch the run agent **in the background** (`run_in_background: true`). This is
required: a foreground launch blocks the parent until the subagent returns, which
makes the liveness monitoring in Step 5b structurally impossible (and is why hung
runs have gone undetected). Background launch keeps the parent in control.

```
Agent({
  description: "nightshift run {spec-id}",
  prompt: <scaffolded brief>,        // with {progress_file_abs} substituted
  isolation: "worktree",
  mode: "bypassPermissions",
  run_in_background: true,           // REQUIRED — see note above
})
```

**Capture the `agentId` from this launch result** — the parent needs it to
`TaskStop` the run if it hangs (Step 5b). Display: "Agent launched in background.
Monitoring `{spec-id}`..." Then proceed immediately to Step 5b. The harness
surfaces a completion notification to the parent when the background run finishes
— that is wake source 1 in Step 5b, and the run's `<branch>`/`<path>` arrive in
that notification's result payload.

**Immediate launch-failure branch (before the heartbeat watchdog):** A rejected
launch, or a completion carrying a harness/launch error before the shared
heartbeat contains `heartbeat_state: worker-started`, is a distinct
`launch_failure` outcome. Preserve the timestamp, sanitized harness error,
launch result, and heartbeat state in the parent progress artifact and run
report; do **not** wait 20 minutes for the stale-heartbeat watchdog.

The parent may make **exactly one** focused retry only when the error is
retryable and the retry needs neither human input nor unsafe action. Reuse the
same spec, run ID, parent claim, and isolated worktree policy, but narrow the
brief to the launch blocker, required context, and one deterministic verification
step. Record `launch_retry: 1` before dispatching it. The retry worker still
cannot change lifecycle state or merge.

If the first error is ineligible (credentials, policy approval, destructive or
unsafe action, ambiguity, or external input), or if that one retry is rejected
or completes before `worker-started` with another launch/harness error, stop
launching workers. Use the existing controller-backed blocked-resolution path,
with `blocker_class: launch_failure`, the preserved evidence, and the controller
produced next safe action. This is terminal `blocked`, not a stale heartbeat and
not an extra retry. If the focused retry starts successfully, continue through
the ordinary Step 5b liveness and Step 6 evidence gates, retaining the initial
launch failure in the final report.

### Step 5b: Enforced liveness loop (monitor the background run)

The run agent runs in the background, so the parent keeps control and **MUST**
actively confirm the run is still progressing — this step is not optional. Hung
runs that silently stop "looping" are the failure mode this guards against. The
parent does not take over implementation; it only watches and, on a confirmed
hang, stops and escalates.

Exactly two things wake the parent. Handle each:

**Wake source 1 — completion notification.** When the background run agent finishes,
the harness surfaces a background-task completion notification to the parent. If
it carries a launch/harness error and the heartbeat never reached
`worker-started`, handle the immediate launch-failure branch in Step 5 first;
otherwise → go to Step 6 (post-run resolution).

**Wake source 2 — liveness watchdog (the hang case).** A hung run never sends a
completion notification, so the parent detects it on a wall-clock timer. The run
works in an isolated worktree the parent cannot read, so the parent watches the
SHARED heartbeat file instead:

`<main-repo-abs>/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md`

Immediately after launching (Step 5), arm a liveness watchdog with the **`Monitor`**
tool — a poll loop that exits, and thereby notifies the parent, on exactly one of
two conditions: the heartbeat reached a **terminal `heartbeat_state`** (`worker-done`
or `worker-blocked` — the run ended, this is `TERMINAL`, not a stall), or it has not
been touched for the stall threshold (1200s = 20 min — this is `STALL`). Do **not**
use `ScheduleWakeup` (it is `/loop`-only), and do **not** chain `sleep` commands
(long leading sleeps are blocked):

```bash
# Monitor watchdog — wakes the parent on EITHER a terminal heartbeat_state (the run
# ended cleanly) OR a heartbeat stale > 1200s (20 min).
# Terminal is checked FIRST and this ordering is load-bearing: a finished run's
# heartbeat is ALSO stale, so a staleness-first loop reports a false STALL on every
# completed run. Only line 1 is read — a terminal word elsewhere in the file must not
# disarm the watchdog on a genuinely hung run.
HB="<main-repo-abs>/.nightshift/reports/_wip/orchestrator-progress-{spec-id}.md"
TERMINAL_RE='^heartbeat_state:[[:space:]]*(worker-done|worker-blocked)([[:space:]]|$)'
while :; do
  if [ -f "$HB" ] && sed -n '1p' "$HB" | grep -Eq "$TERMINAL_RE"; then
    echo "TERMINAL: heartbeat for {spec-id} reached $(sed -n '1p' "$HB")"
    break
  fi
  if [ -f "$HB" ] && [ $(( $(date +%s) - $(stat -f %m "$HB") )) -gt 1200 ]; then
    echo "STALL: heartbeat for {spec-id} not advanced in >1200s"
    break
  fi
  sleep 60
done
```

(macOS: `stat -f %m`; Linux: `stat -c %Y`. The 60s inner poll is the watch's own
loop, not a leading sleep — the parent is not blocked while it runs.) **Capture the
watchdog's task ID when you arm it** — immediately record it as
`watchdog_task_id: <id>` in the parent progress state beside the run ID, claim,
and heartbeat reference. The parent needs that exact ID to `TaskStop` the watchdog
after the run resolves; a description or a later task-name search is not a substitute.

**This is still wake source 2, not a third one.** The watchdog wakes the parent once
and the parent routes on the message it printed: `TERMINAL` → go to Step 6
(post-run resolution) exactly as a completion notification would, recording the
terminal state read from line 1; `STALL` → enter the escalation ladder below.
A `TERMINAL` wake never enters the ladder and is never recorded as a stall.

**Staleness escalation ladder** — when the watchdog fires `STALL`:

1. **First stall → classify, then grace.** Read the heartbeat's state marker.
   `heartbeat_state: parent-seeded` (or no `worker-started` marker) means
   **heartbeat never started**; `heartbeat_state: worker-started` means the
   heartbeat **stalled after start**. Record that exact classification, then
   re-arm the watchdog for ONE more interval. The run may be in one long step
   (large build, a slow model call), so do not escalate yet.
2. **Second consecutive stall (heartbeat still unchanged after the grace interval)
   → declare the run hung.** Do **not** try to "ping" the run agent — background
   subagents are not reliably pingable mid-run. Instead:
   - Stop the background run agent with `TaskStop`.
   - Mark the spec `blocked` on main via the failure-persistence helper (Step 6),
     reason e.g. `"kickoff run hung — heartbeat stale >40 min, no forward progress"`.
   - Append a `HANG` line to the heartbeat file for the post-mortem.
   - Cortex breadcrumb: `"Spec {spec-id} hung during kickoff run — stopped after stale heartbeat"`.
   - Leave the worktree in place for inspection. Tell the user what stalled (last
     recorded phase / action / commit SHA from the heartbeat) and the worktree path.

While neither wake source has fired, the parent is idle and waiting — it must not
poll the run agent directly or start doing the spec's work. The watchdog and the
completion notification are the only two channels.

### Watchdog cleanup assertion (SPEC-226)

Every terminal path — successful `done`, evidence-gate `blocked`, confirmed hung
run, and immediate launch failure (including its exhausted retry) — executes this
same parent-owned cleanup assertion before the parent becomes idle. The worker never
discharges it. The parent records the exact `watchdog_task_id`, asks the harness to
`TaskStop` that ID when it is armed, then enumerates the parent's running background
tasks and compares their IDs to the recorded ID.

Record one controlled result in both the parent progress artifact and final run
report:

| `watchdog_cleanup` | Meaning | Required action |
|---|---|---|
| `checked-clean` | The recorded watchdog ID is absent from the task listing after stop. | Continue terminal resolution. |
| `check-failed` | The recorded watchdog ID is still running, or `TaskStop` failed. | Report the failure; do not silently swallow it. Treat the terminal resolution as blocked/evidence-gap until it is resolved. |
| `check-not-run` | The harness has no task-listing capability, no watchdog was armed, or the parent could not perform the assertion. | Record the reason and whether human action is needed; this is graceful degradation, never a fabricated clean result. |

The terminal heartbeat and explicit stop are belt-and-braces, not alternatives — a
finished heartbeat does not prove task cleanup. A leaked watchdog is a protocol defect:
its task ID must appear in the `check-failed` report evidence. Before any `done` or
`blocked` lifecycle commit, include the cleanup result and the task ID (or the
documented `check-not-run` reason) in the terminal-resolution evidence. The run report
must use the exact three result names above so a missing check is distinguishable from
a clean result.

> **Platform note.** The above is the Claude path (`Agent run_in_background` + a
> `Monitor` watchdog). On Codex, use its background-execution plus a wall-clock
> watch equivalent. If a platform offers neither background launch nor a wall-clock
> watch, this flow degrades to instruction-only: launch foreground and accept that
> a hung run will block the parent — state that limitation to the user before
> proceeding rather than pretending the run is monitored.

### Durable pre-fix red proofs (SPEC-279)

When an acceptance criterion depends on a regression test having failed before
the fix, report prose is not sufficient evidence. The run that observes the red
result records the baseline revision, exact test-file bytes, and exact failing
pytest node IDs in a committed project-local artifact:

```bash
python3 .nightshift/red_proof.py record \
  --root "$PROJECT_ROOT" \
  --artifact "$PROJECT_ROOT/.nightshift/red-proofs/{SPEC_ID}.json" \
  --spec-id "{SPEC_ID}" --baseline-revision "{RED_BASELINE}" \
  --test-file "{REPOSITORY_RELATIVE_TEST_FILE}" \
  --failing-test "{EXACT_FAILING_NODE_ID}" [...]
```

The run agent must use the failures actually observed in that red execution,
inspect the emitted JSON, and commit the artifact before publishing `work.completed`.
The artifact belongs to project history; a same-spec report may summarize it but
does not replace it. Never place it under `reports/`, whose same-spec content is
intentionally withheld from the independent verifier.

When a later post-fix or integration run relies on that proof, the run agent
mechanically re-asserts it and commits the structured result before returning:

```bash
python3 .nightshift/red_proof.py reassert \
  --root "$PROJECT_ROOT" \
  --artifact "$PROJECT_ROOT/.nightshift/red-proofs/{SPEC_ID}.json" \
  --result "$PROJECT_ROOT/.nightshift/red-proofs/{SPEC_ID}-reassertion.json"
```

`reasserted` means only that the current test file is byte-identical to the file
bound into the committed observation. The result therefore says
`evidence_mode: inherited_committed_artifact` and
`red_execution_performed: false`; it never claims the post-fix run observed red.
This check must not revert or reconstruct pre-fix code. A missing or changed test
file is a successful evidence check with status `not_re_derivable` and an explicit
reason, not a stale pass and not a controller crash. The parent verifies that the
expected artifact/result is committed and verifier-readable before dispatch.

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
evidence paths (`reports/**`, `metrics/**`, and this spec's own file) are always
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
  [--spec-path <repo-relative-spec-file>] \
  [--suite-command <exact-configured-command> ...]) || {
    echo 'verifier_surface_unavailable: do not call Agent' >&2
    exit 2
  }
```

Repeat `--suite-command` once per exact configured suite command for the normal
brief and omit it entirely for the no-test-suite brief. When no `--suite-command`
is given, `prepare-dispatch` derives one default from the source project's own
`commands.test` (SPEC-243-001) and fails closed to the no-test-suite brief when
that value is absent, empty, or malformed rather than fabricating suite evidence
— explicit `--suite-command` still always wins and is never merged with the
config-derived default. Parse `DISPATCH_PLAN` as
JSON and require its exact schema before composing the brief. Use only its
`repository`, `arm_working_directories.baseline`/`.head`, `verifier-baseline`/
`verifier-head`, suite tuple, and synthetic commit IDs in the verifier
assignment. The source/report arguments above remain parent-private
preparation inputs and must not be copied into the brief.

**Declared external evidence (SPEC-288).** Some specs cannot be verified from the
subject repository alone: their durable evidence — a retained benchmark run, a
held-out reference output — lives in a *different* repository. `--spec-path` is
what lets such a spec's predeclared evidence reach its verifier, under
containment, and it is the only route. Without `--spec-path`, `prepare-dispatch`
behaves exactly as it did before SPEC-288, so no existing dispatch changes
behaviour by upgrading the kit.

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

**Closure packet: SPEC-ARGO-067 (parent-owned, SPEC-289 R6).** 067 is the first
consumer of this mechanism and was blocked twice — once by SPEC-288's absence, once
by SPEC-289's anchor defect. Execute these steps in order; none of them loads a
model, and none of them may be replaced by a parent self-check.

1. **Declaration.** One entry, quoted, in 067's `context.required_inputs`:

   ```yaml
   context:
     required_inputs:
     - "external-evidence:{{HOME}}/Dropbox/Developer/ManagedProjects/Tools/benchmarks#results/2026-08-23T202546Z_agentic-unified-ctx131072"
   ```

   `{{HOME}}` is the anchor that resolves — the benchmarks repository is *not*
   under Argo Home, so `{{ARGO_HOME}}` and `{{PROJECT_ROOT}}` cannot reach it and
   `..` is forbidden. The run directory is admissible as measured on 2026-08-30:
   57 tracked regular files, 2,504,722 bytes, clean at the source HEAD, no
   symlinks — inside the 256-member and 8 MiB bounds, with no headroom to spare
   if the declaration is widened to `results/`, which it must not be.
2. **New baseline.** Both arms must carry an identical declaration, so 067's
   historic baseline `14bdd483f5fb43dfd9bcd1d204645ca6da84934b` cannot be reused:
   it predates the declaration and the arms would differ. Commit the declaration
   edit *alone* on Argo `main` and use that commit as the new baseline.
3. **New candidate.** The preserved evidence candidate
   `nightshift/SPEC-ARGO-067-20260830` at `0672ea66` cannot be dispatched as-is
   either. Rebase or recreate it on the new baseline so it carries the same
   declaration, and change nothing else — the retained evidence, its report, and
   its metrics stay byte-identical. Verify with a diff against `0672ea66` that
   only the declaration line moved.
4. **Dedicated run ID.** Allocate a new run ID for this dispatch. Do not reuse the
   blocked runs' IDs; their durable records are evidence of the two refusals and
   are not to be overwritten.
5. **Rebuild the surface** with `prepare-dispatch` exactly as documented above,
   passing `--spec-path` for 067's spec file (without it the declaration is inert
   and the surface carries no evidence), a fresh empty destination, and a fresh
   `--evidence` path under the new run ID. Confirm before dispatching that the
   containment evidence records the input as `admitted` with `member_count` 57,
   and that both arm directories contain the projection.
6. **Dispatch the independent verifier** against the emitted plan, with the brief
   addition above. The verifier reads the projection from its assigned arm; it is
   never given the benchmarks path, and the parent never verifies 067 itself.
7. **Terminalize only from the verdict.** A pass terminalizes 067 as `done`; a
   fail returns it to the ladder with the verifier's findings. A refusal at step 5
   is a controlled `evidence_gap` (`verifier_surface_unavailable`) — fix the
   *declaration* and repeat from step 2. Never resolve 067 from the parent's own
   reading of the evidence.
8. **No rerun, ever.** This procedure loads no local model, starts no LM Studio
   server, and re-executes no benchmark. The 2026-08-23 run is the evidence; the
   projection is a copy of bytes already committed. If any step appears to require
   sampling a model, the step is wrong — stop and report it.

The versioned dispatch identity has two non-interchangeable values. `head_commit`
is the synthetic Git object ID used only inside the standalone repository.
`implementation_head_digest` is an opaque lowercase SHA-256 binding over the
parent-private candidate revision and containment projection. Copy both unchanged
into the verifier verdict. Never derive one from the other or expose the exact
candidate revision.

Collect `git_footprint.baseline` and `git_footprint.head`, each with its own
`tree_before`, `tree_after`, `porcelain_before`, and `porcelain_after`, from that
arm's assigned working directory only (R4) — never from `repository` or from the
other arm's directory. Both snapshots are required: the gate is a set comparison
of what you returned against what you were handed, so a working tree that was
already dirty when you received it is not your footprint, and the validator
recomputes that comparison from these two fields rather than trusting a
conclusion. Report the verbatim `status --porcelain=v1 --untracked-files=all`
text, including when it is empty. The source run worktree and parent checkout are outside the
verifier capability boundary after surface creation. The delimited, verbatim
Acceptance Criteria quote is the current spec's complete AC set for this
verdict — do not infer AC IDs elsewhere.
Populate declared suites only from exact configured commands, using neutral
generated labels (`suite-1`, `suite-2`, ...). Never add expected totals, pass/fail
claims, comments, or worker-derived prose to a suite header or label.

```markdown
<!-- NIGHTSHIFT-VERIFIER-BRIEF-BEGIN -->
You are the independent verifier for Nightshift spec {spec-id}. You did not write
this code and you are not told what its author concluded.

Inputs (the only five you get):
- Branch content under test: {branch}, materialized as `verifier-head` in the assigned standalone verifier surface
- Baseline content: {baseline_commit}, materialized as `verifier-baseline` in that surface
- Declared suites: {suite_commands}
- Declared write scope: {scope_summary}. A path in the branch/baseline diff outside
  this scope, and not covered by a `## Scope Amendments` row on main, is out of scope
  regardless of whether it looks related to this spec.
- Acceptance criteria, verbatim from the spec:
<!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN -->
{acceptance_criteria_verbatim}
<!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-END -->

Your job: decide, from evidence you gather yourself inside the assigned verifier
surface, whether each AC holds at `verifier-head` relative to `verifier-baseline`.

Verdict JSON contract: include `spec_id`, `branch`, `baseline_commit`,
`head_commit`, `identity_schema_version` (`"1.0.0"`),
`implementation_head_digest` (a lowercase SHA-256), `verdict` (`pass`, `fail`,
or `disputes_premise`), a non-empty `acs` array, `suites`, `git_footprint`,
`scope`, and `contamination`. `scope` (SPEC-300-002 R6) is
`{"checked": [...], "out_of_scope": [...], "amended": [...]}`, each a list of
repo-relative paths from the `verifier-baseline..verifier-head` diff:
`checked` is every changed path, `out_of_scope` the ones denied against the
brief's declared write scope with no covering `## Scope Amendments` row on
main, `amended` the denied ones a row does cover. Every `acs` entry uses
`status: pass | fail | unverifiable`
and `evidence` as a non-empty JSON string containing the command plus observed
result; arrays, objects, numbers, and null are rejected. `git_footprint` must
contain `baseline` and `head` arms, each with `tree_before`, `tree_after`,
`porcelain_before`, and `porcelain_after`; supplementary top-level footprint
keys are allowed. Suite entries use the declared command and carry named
baseline/head samples plus the five classification lists (`regressed`,
`newly_flaky`, `flaky_observed`, `fixed`, `flake_resolved` — BUG-024).
Set `contamination` to null when none was observed. A `disputes_premise`
verdict additionally includes `premise_dispute.claim`, `.evidence`, and
boolean `.spec_defect`. Whenever this contract or the JSON example below it
needs quoting into a sub-verification brief, copy the canonical block
verbatim — do not paraphrase field names, the status/verdict enums, or key
ordering from memory (BUG-024 R6): reconstructing it from memory has
independently drifted on `acs` vs `acceptance_criteria`, the `unverifiable`
status enum, per-sample count shape, and `git_footprint` key ordering.

Rules:
1. READ-ONLY. Run tests and read files. Never edit, create, delete, stage, commit,
   merge, rebase, stash, or change lifecycle state. Apply the Canonical
   verifier-gate boundary above; a non-empty verifier-surface footprint voids
   your verdict.
2. This run's report, its progress artifacts, and every other report that names this
   spec are structurally absent and unreachable from the assigned surface. That is
   the whole of the guarantee. Reports belonging to other specs may still be present
   as test fixtures, and any file may quote a conclusion in passing. Do not access
   any source checkout outside the assigned surface. If you nevertheless observe an
   author conclusion about this spec — in a retained fixture, a path name, a commit
   message, or anywhere else — record it in `contamination` and continue, including
   whether you saw it before or after deriving the same result yourself.
3. Sample, do not take single draws. For any suite marked flaky-suspected — and for
   any suite whose two arms disagree at all — run it at least 3 times per arm and
   report every sample. A difference seen in one draw per arm is not a regression.
4. Report failing test NAMES per sample, never totals alone. A totals-only verdict
   is rejected by the validator.
5. If the spec's or the parent's stated expectation is itself wrong, or if you
   disagree with something else about this run (an enforcement gate, a tool,
   a parent-level claim), return `verdict: disputes_premise` with the claim,
   the evidence, and an explicit `spec_defect: true | false` — state directly
   whether the dispute names a requirement or AC of *this spec* that is itself
   wrong or unmeetable, even when it does not (your dispute is against
   something else entirely). That is a first-class outcome, not a failure, and
   it is preferred over forcing a pass/fail.
6. If an AC requires you to independently re-execute a real git commit-class operation (`git add`,
   `git commit`, `git worktree add`) to confirm it, and your own worktree isolation refuses that
   operation, do not force a `pass` or `fail` for it: mark that AC `unverifiable` with the specific
   reason (e.g. "cannot independently re-execute commit-class git mutation under worktree
   isolation") — `fail` would misrepresent a sandbox limitation as a defect in the work.
7. Write your verdict JSON to {verdict_path} and print nothing else of substance.
<!-- NIGHTSHIFT-VERIFIER-BRIEF-END -->
```

**a-alt. No-test-suite verifier brief (docs/protocol-type specs, SPEC-ARGO-061 R2).**
Dispatch is unconditional (R1, SPEC-ARGO-061 Decision) even when a project's
`config.yaml`'s `commands.test` is absent, empty, or malformed — most `domain:
protocol` / `type: docs` specs have nothing a suite command can run, regardless
of whether the project otherwise declares one (SPEC-243-001; this project's own
`config.yaml` now declares a dependency-complete `commands.test`, so most of its
specs still route here on doc/protocol grounds, not on a missing command). Only
the brief's shape and the resulting `suites` field change; dispatch, the footprint
assertion, and the validator all stay the same. Use this template verbatim in place
of (a) whenever `{suite_commands}` would otherwise be empty/`null`:

```markdown
<!-- NIGHTSHIFT-VERIFIER-BRIEF-NOSUITE-BEGIN -->
You are the independent verifier for Nightshift spec {spec-id}. You did not write
this code and you are not told what its author concluded.

Inputs (the only five you get):
- Branch content under test: {branch}, materialized as `verifier-head` in the assigned standalone verifier surface
- Baseline content: {baseline_commit}, materialized as `verifier-baseline` in that surface
- Declared suites: none — no suite command applies to this spec's changes;
  verify each AC by direct inspection of the diff and the changed files'
  committed content.
- Declared write scope: {scope_summary}. A path in the branch/baseline diff outside
  this scope, and not covered by a `## Scope Amendments` row on main, is out of scope
  regardless of whether it looks related to this spec.
- Acceptance criteria, verbatim from the spec:
<!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN -->
{acceptance_criteria_verbatim}
<!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-END -->

Your job: decide, from evidence you gather yourself inside the assigned verifier
surface, whether each AC holds at `verifier-head` relative to `verifier-baseline`. There is nothing to run — the evidence is
whether the committed text, doc content, or config is actually correct, not
whether a test passes.

Verdict JSON contract: include `spec_id`, `branch`, `baseline_commit`,
`head_commit`, `identity_schema_version` (`"1.0.0"`),
`implementation_head_digest` (a lowercase SHA-256), `verdict` (`pass`, `fail`,
or `disputes_premise`), a non-empty `acs` array, `suites`, `git_footprint`,
`scope`, and `contamination`. `scope` (SPEC-300-002 R6) is
`{"checked": [...], "out_of_scope": [...], "amended": [...]}`, each a list of
repo-relative paths from the `verifier-baseline..verifier-head` diff:
`checked` is every changed path, `out_of_scope` the ones denied against the
brief's declared write scope with no covering `## Scope Amendments` row on
main, `amended` the denied ones a row does cover. Every `acs` entry uses
`status: pass | fail | unverifiable`
and `evidence` as a non-empty JSON string containing the command plus observed
result; arrays, objects, numbers, and null are rejected. `git_footprint` must
contain `baseline` and `head` arms, each with `tree_before`, `tree_after`,
`porcelain_before`, and `porcelain_after`; supplementary top-level footprint
keys are allowed. Report `suites: []` for this no-suite path and set
`contamination` to null when none was observed. A `disputes_premise` verdict
additionally includes `premise_dispute.claim`, `.evidence`, and boolean
`.spec_defect`. Whenever this contract needs quoting into a sub-verification
brief, copy the canonical block verbatim — do not paraphrase it from memory
(BUG-024 R6).

Rules:
1. READ-ONLY. Read files and run `git diff`/`git show`; never edit, create,
   delete, stage, commit, merge, rebase, stash, or change lifecycle state. Apply
   the Canonical verifier-gate boundary above; a non-empty verifier-surface
   footprint voids your verdict.
2. This run's report, its progress artifacts, and every other report that names this
   spec are structurally absent and unreachable from the assigned surface. That is
   the whole of the guarantee. Reports belonging to other specs may still be present
   as test fixtures, and any file may quote a conclusion in passing. Do not access
   any source checkout outside the assigned surface. If you nevertheless observe an
   author conclusion about this spec — in a retained fixture, a path name, a commit
   message, or anywhere else — record it in `contamination` and continue, including
   whether you saw it before or after deriving the same result yourself.
3. For each AC, gather evidence yourself: read `git diff verifier-baseline..verifier-head`
   for the files it names, open the changed file(s) at `verifier-head` and check the
   actual content/config/schema the AC describes — grep for the exact string,
   open the section, validate the config parses, confirm the file exists at the
   claimed path. Never take the worker's claim about what it did as evidence.
4. Evidence per AC is the command you ran plus what you *observed* — e.g.
   `grep -n "pattern" path/to/file` -> "found at line 42, exact match" or
   `python3 -c "import yaml; yaml.safe_load(open('x.yaml'))"` -> "parses clean".
   A bare "looks correct" or "confirmed" with no command+observation is
   rejected by the validator (same `evidence` non-empty check as the suite
   path) and should not be written.
5. Report `suites: []` in the verdict. There is nothing to sample — do not
   fabricate a suite entry, a fake command, or synthetic pass/fail samples to
   satisfy the schema. The validator accepts an empty `suites` array; per-AC
   evidence carries the weight the suite samples would otherwise carry.
6. If the spec's or the parent's stated expectation is itself wrong, or if you
   disagree with something else about this run, return `verdict:
   disputes_premise` with the claim, the evidence, and an explicit
   `spec_defect: true | false`, exactly as in the suite-based brief.
7. If an AC requires you to independently re-execute a real git commit-class operation (`git add`,
   `git commit`, `git worktree add`) to confirm it, and your own worktree isolation refuses that
   operation, do not force a `pass` or `fail` for it: mark that AC `unverifiable` with the specific
   reason (e.g. "cannot independently re-execute commit-class git mutation under worktree
   isolation") — `fail` would misrepresent a sandbox limitation as a defect in the work.
8. Write your verdict JSON to {verdict_path} and print nothing else of substance.
<!-- NIGHTSHIFT-VERIFIER-BRIEF-NOSUITE-END -->
```

**Worked example (illustrative, not tied to a live spec).** A docs spec's AC1
reads "the SKILL.md Step 5c intro paragraph states dispatch is unconditional."
The verifier's per-AC entry:

```json
{"id": "AC1", "status": "pass",
 "evidence": "grep -n 'dispatch a `nightshift-verifier` agent' Skills/nightshift/SKILL.md at verifier-head -> found at line 1201, matches the AC's quoted text exactly"}
```

— a command, and what was actually observed running it. `suites` in that
verdict is `[]`; nothing else about the verdict schema, the footprint check, or
the validator changes.

**Worked example — git-mutation-heavy spec (BUG-021, SPEC-309 AC3, real and
already-resolved).** BUG-021 (completing SPEC-300-003's own missing
live-execution evidence) needed a real `git commit` against a genuine
pre-commit hook — a mechanism that only fires at commit time. The dispatched
`nightshift-worker`, worktree-isolated, refused the task outright: every `git`
invocation it attempted — including bare `git status`/`git log --oneline -1`
with no arguments, run from its own worktree — was refused by the sandbox's
`rtk` wrapper citing worktree isolation, and its one sanctioned
`dangerouslyDisableSandbox: true` escalation on the simplest possible case was
refused identically. It correctly declined to proceed rather than fabricate
evidence, and correctly refused the coordinator's own mistaken follow-up
suggestion to retry via `/usr/bin/git` in place of bare `git` — a workaround
that applies to a different, narrower problem (BUG-019's compound/aliased
commands that the sandbox's static verifier could not parse) and was not
authorization to route around this boundary (Step 4g above). Per R2, the
coordinator then executed the live proof directly — the fallback pattern this
spec requires the completion report to name explicitly, in this shape:
"executed by the coordinator, not a worktree-isolated worker, because
SPEC-300-003's pre-commit hook can only be exercised at real commit time." The
independently-dispatched `nightshift-verifier` hit the same wall trying to
re-run the proof itself: it reproduced the read-only step (running the
installer script) but could not independently reproduce the real `git commit`
steps. Per R3/Rule 6-7 above, the correct classification for those AC(s) is
`unverifiable` with reason "cannot independently re-execute commit-class git
mutation under worktree isolation" — not `fail`, which would misrepresent a
sandbox limitation as a defect in SPEC-300-003's own work. (A later probe
found the refusal here is a static command-shape parse check rather than a
true target-aware boundary — see Step 4g's correction and BUG-310 — but the
`unverifiable` classification and the coordinator-executes-directly fallback
are unaffected: they hold regardless of *why* the refusal fires, only never
via a piped/redirected invocation, which bypasses it.)

**Forbidden-content check on the composed brief (R2/AC2), scoped to the
parent-authored text (R1/R2/AC1/AC5).** Run this against the brief you actually
composed, immediately before dispatch — not against the template. It is the one
check that catches a parent that helpfully pasted the worker's report in — while
leaving the brief's own `{acceptance_criteria_verbatim}` block out of scope, since
R2 requires that block to quote the spec's ACs verbatim and a spec's ACs can
legitimately contain phrasing the leak-detector matches (SPEC-ARGO-038's own AC2
text — *"contains no worker conclusions"* — is the case that exposed this).
Provenance is determined mechanically and in two layers, never by a
hand-maintained allowlist of "safe" phrasings (R2): (1) the
`NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN`/`-END` delimiters mark *where* a verbatim
quote is supposed to be, and (2) a hit inside that region is only exempted once
it is independently confirmed against `<spec-file>` — the delimiters alone are
not proof, since anyone can type the marker comments, and a parent who pasted a
leak *inside* them would otherwise get it exempted for free. Exemption is
evaluated **per occurrence, by line position, never by string identity**: a line
that duplicates spec-quoted text but was pasted a second time outside the
delimiters is still in scope and still flagged (SPEC-ARGO-048 AC5), and if
`<spec-file>` is omitted or unreadable the check **fails closed** — no in-block
hit is exempted, so it cannot be weakened by dropping the argument. If a brief
carries no delimited block at all, every match stays in scope regardless.

```bash
# NIGHTSHIFT-BRIEF-CHECK-BEGIN
# usage: brief_check <composed-brief-file> <spec-file>
#   ->  BRIEF: clean | BRIEF: contaminated (<hits>)
#
# Scope (R1/R2/AC1/AC5): text delimited by
# <!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN --> ... <!-- NIGHTSHIFT-BRIEF-SPEC-QUOTE-END -->
# is where the brief's verbatim-from-spec quote (the acceptance_criteria_verbatim
# block in the template) belongs. The delimiters alone are NOT proof of
# provenance -- anyone can type the marker comments -- so a hit inside the block
# is only excluded once it is independently verified: the exact line must also
# appear, verbatim, in <spec-file>. A hit inside the block that is NOT found in
# <spec-file> stays contamination (a parent could otherwise smuggle a leak past
# the scan just by wrapping it in the marker comments). If <spec-file> is
# omitted or unreadable, the check FAILS CLOSED: no in-block hit is exempted,
# so the check cannot be weakened by dropping the argument.
#
# Scoping is by LINE POSITION, never by string identity: a line that duplicates
# spec-quoted text but was pasted a second time outside the delimiters is still
# in scope and still flagged (AC5) -- provenance is per-occurrence, not
# per-string, and there is no hand-maintained allowlist of "safe" phrasings
# (R2). Uses only bash/zsh-portable constructs (paired begin/end line numbers
# via `paste`, no indexed-array subscripting, whose 0- vs 1-based semantics
# differ between bash and zsh).
brief_check() {
  file="$1"
  specfile="$2"
  pattern='worker (report|conclu|claim|said|state)|the worker (found|fixed|verified|believes)|nightshift-report|run report says|according to the (worker|run|implementer)|\{worker_[a-z_]*\}|\{report_[a-z_]*\}|all (tests|ACs) (pass|passed) per|implementer (notes|reports)'

  begins=$(grep -nF 'NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN' "$file" | cut -d: -f1)
  ends=$(grep -nF 'NIGHTSHIFT-BRIEF-SPEC-QUOTE-END' "$file" | cut -d: -f1)
  ranges=$(paste -d' ' <(printf '%s\n' "$begins") <(printf '%s\n' "$ends"))

  all_hits=$(grep -nEi "$pattern" "$file")
  if [ -z "$all_hits" ]; then echo "BRIEF: clean"; return 0; fi

  contaminated=""
  excluded=""
  is_contaminated=0
  while IFS= read -r hit; do
    [ -z "$hit" ] && continue
    n="${hit%%:*}"
    line_text="${hit#*:}"
    in_scope=0
    while IFS=' ' read -r b e; do
      [ -z "$b" ] || [ -z "$e" ] && continue
      if [ "$n" -ge "$b" ] && [ "$n" -le "$e" ]; then
        in_scope=1
      fi
    done <<RANGES
$ranges
RANGES
    if [ "$in_scope" -eq 1 ]; then
      verified=0
      if [ -n "$specfile" ] && [ -f "$specfile" ] && grep -Fxq -- "$line_text" "$specfile"; then
        verified=1
      fi
      if [ "$verified" -eq 1 ]; then
        excluded="${excluded}${hit} [spec-quoted, verified against spec file];"
      else
        contaminated="${contaminated}${hit} [inside quote block but NOT found in spec file];"
        is_contaminated=1
      fi
    else
      contaminated="${contaminated}${hit} [not spec-traceable];"
      is_contaminated=1
    fi
  done <<HITS
$all_hits
HITS

  if [ "$is_contaminated" -eq 1 ]; then
    echo "BRIEF: contaminated ($contaminated)"
    [ -n "$excluded" ] && echo "  spec-quoted matches excluded from scope: $excluded"
    return 1
  fi
  echo "BRIEF: clean"
  [ -n "$excluded" ] && echo "  spec-quoted matches excluded from scope: $excluded"
  return 0
}
# NIGHTSHIFT-BRIEF-CHECK-END
```

A `contaminated` brief is not dispatched — strip the flagged **parent-authored**
lines (marked `[not spec-traceable]` in the output) and re-check. A hit marked
`[inside quote block but NOT found in spec file]` means something was pasted (or
altered) inside the delimiters that is not actually in the spec — fix the quote,
don't widen the exemption. Genuinely spec-quoted lines inside the delimiters are
never flagged once `<spec-file>` is supplied, so satisfying this never requires
touching — or being tempted to touch — the verbatim AC block R2 requires.

> **Containment boundary.** The forbidden-content check still protects the
> parent-authored brief, while the standalone verifier surface protects the read
> capability itself. The source checkout is never assigned to the verifier and
> its report blobs are absent from the verifier object database. Treat a non-null
> `contamination` field in the verdict as real signal. The phrase scan is not a
> semantic leak detector: it matches
> the same fixed phrase-alternation as before scoping was added, so a leak worded
> entirely outside that alternation's coverage will not be caught — widening that
> coverage is Out of Scope for SPEC-ARGO-048, which changes how the gate is
> asserted, not what it checks.

**b. Dispatch, with the read-only footprint asserted by hash, over both assigned
arm surfaces (R4/R6/AC1/AC2).** Capture each arm's tree hash *and* its
working-tree entries before and after; assert that the tree hash is equal and
that the two sets of entries are equal. A worktree that was already dirty at
dispatch is not the verifier's footprint — only what the set comparison shows it
added or removed is. Mutation, or an entry gained or lost, in *either* arm voids
the verdict; a clean baseline arm never masks a dirty head arm or vice versa:

```bash
# NIGHTSHIFT-FOOTPRINT-BEGIN
# usage: FOOTPRINT_BASELINE_BEFORE=$(footprint_before <baseline-worktree>)
#        FOOTPRINT_HEAD_BEFORE=$(footprint_before <head-worktree>)   # export/keep both in scope
#        ... dispatch the verifier ...
#        footprint_after <baseline-worktree> "$FOOTPRINT_BASELINE_BEFORE" baseline
#        footprint_after <head-worktree> "$FOOTPRINT_HEAD_BEFORE" head
# The captured value is the arm's tree hash on line 1 and its working-tree
# entries below it, so `footprint_after` set-compares what the verifier returned
# against what it was handed (SPEC-284). It is never a test of whether the
# worktree happened to be clean at dispatch: an entry in both snapshots was
# already there and is nobody's write, while an entry only after (added) or only
# before (removed) is the verifier's, whatever the path is called.
footprint_before() {
  git -C "$1" rev-parse 'HEAD^{tree}'
  git -C "$1" status --porcelain=v1 --untracked-files=all | LC_ALL=C sort
}
footprint_after() {
  local worktree="$1" before="$2" label="$3"
  local before_tree after_tree before_dirt after_dirt added removed
  before_tree=$(printf '%s\n' "$before" | head -n 1)
  before_dirt=$(printf '%s\n' "$before" | tail -n +2 | grep -v '^[[:space:]]*$' | LC_ALL=C sort)
  after_tree=$(git -C "$worktree" rev-parse 'HEAD^{tree}')
  after_dirt=$(git -C "$worktree" status --porcelain=v1 --untracked-files=all | grep -v '^[[:space:]]*$' | LC_ALL=C sort)
  if [ "$after_tree" != "$before_tree" ]; then echo "FOOTPRINT[$label]: violated (tree $before_tree -> $after_tree)"; return 1; fi
  added=$(comm -13 <(printf '%s\n' "$before_dirt") <(printf '%s\n' "$after_dirt") | grep -v '^[[:space:]]*$')
  removed=$(comm -23 <(printf '%s\n' "$before_dirt") <(printf '%s\n' "$after_dirt") | grep -v '^[[:space:]]*$')
  if [ -n "$added" ]; then echo "FOOTPRINT[$label]: violated (verifier added: $(echo $added))"; return 1; fi
  if [ -n "$removed" ]; then echo "FOOTPRINT[$label]: violated (verifier removed: $(echo $removed))"; return 1; fi
  echo "FOOTPRINT[$label]: clean ($after_tree)"; return 0
}
# NIGHTSHIFT-FOOTPRINT-END
```

```
Agent({
  description: "nightshift verify {spec-id}",
  subagent_type: "nightshift-verifier",
  prompt: <composed verifier brief, naming DISPATCH_PLAN.arm_working_directories.baseline and .head as the two mandatory workdirs, one per arm, for every command>,
  mode: "bypassPermissions",
})
```

The verifier runs against the **standalone repository emitted in
`DISPATCH_PLAN`**, never the existing run worktree — and, since SPEC-282, that
standalone repository already contains both arms pre-materialized as their own
runnable, checked-out, read-only working directories at
`DISPATCH_PLAN.arm_working_directories.baseline` and `.head`. The verifier
never checks out a ref, creates a worktree, or materializes any file itself;
it only names whichever of the two already-assigned directories a command
targets (for example with the tool's `workdir` or `git -C`). Every command in
the brief must name the correct arm's directory explicitly. If the current
harness cannot make that assignment, do not launch the verifier; resolve the
controlled evidence gap instead. The parent retains the run worktree and both
arm surfaces until after the verdict is validated, then performs parent-owned
cleanup.

**c. Verdict schema.** The verifier writes one JSON object. Under the (a-alt)
no-test-suite brief, `suites` is legitimately `[]` — the validator (below) never
requires a non-empty `suites` array, only that `acs` is non-empty and every AC
carries evidence. `acs[*].evidence` is specifically a non-empty JSON string,
not a structured value. `git_footprint` must contain the required `baseline`
and `head` arms and may carry supplementary top-level evidence keys. An empty
suite array is not a schema gap to work around:

```json
{
  "spec_id": "SPEC-XXX",
  "branch": "nightshift/SPEC-XXX-<run-id>",
  "baseline_commit": "<sha>",
  "head_commit": "<sha>",
  "identity_schema_version": "1.0.0",
  "implementation_head_digest": "<lowercase-sha256>",
  "verdict": "pass | fail | disputes_premise",
  "acs": [
    {"id": "AC1", "status": "pass | fail | unverifiable", "evidence": "<command + observed result>"}
  ],
  "suites": [
    {
      "name": "<suite label>",
      "command": "<exact command>",
      "flaky_suspected": true,
      "samples": {
        "baseline": [{"executed": true, "failing": ["pkg/mod.py::test_a"], "failed": 1, "passed": 617}],
        "head":     [{"executed": true, "failing": [], "failed": 0, "passed": 618}]
      },
      "classification": {
        "regressed": [], "newly_flaky": [], "flaky_observed": ["pkg/mod.py::test_a"], "fixed": [],
        "flake_resolved": []
      }
    }
  ],
  "git_footprint": {
    "baseline": {"tree_before": "<sha>", "tree_after": "<sha>", "porcelain_before": "", "porcelain_after": ""},
    "head":     {"tree_before": "<sha>", "tree_after": "<sha>", "porcelain_before": "", "porcelain_after": ""}
  },
  "scope": {
    "checked": ["src/search/index.py", "reports/2026-09-04-nightshift-report.md"],
    "out_of_scope": [],
    "amended": []
  },
  "premise_dispute": null,
  "contamination": null
}
```

This is the canonical verdict-JSON template block. When briefing a
sub-verification or any nested verdict-composition step, copy it verbatim —
never reconstruct field names, enums, or key shape from memory (BUG-024 R6).
A session that paraphrased this block from memory has independently drifted
on `acs` vs `acceptance_criteria`, the `unverifiable` status enum, per-sample
count shape, and `git_footprint` key ordering, costing correction round-trips
each time.

Schema/brief representation sweep (SPEC-292 R5/R6):

- **Change — `acs[*].evidence`:** keep the non-empty-string contract, publish
  it in both briefs, and reject every other JSON type through `die()`.
- **Change — `git_footprint` top-level keys:** require `baseline` and `head` as
  a subset and allow supplementary evidence keys; exact equality discarded
  useful evidence without strengthening the two-arm check.
- **Keep — `acs[*].status`:** retain `pass | fail | unverifiable` and publish
  the enumeration in both briefs.
- **Keep — identity and verdict fields:** retain the required identity version,
  lowercase digest, verdict enumeration, contamination field, and conditional
  premise-dispute fields; both briefs now publish them.
- **Keep — footprint arm shape:** retain tree-before/tree-after and both
  porcelain snapshots; both briefs now publish the required arm fields.
- **Keep — suite sample/classification shape:** the suite brief already states
  named failures, real execution, two arms, sampling, and recomputation rules;
  its compact contract now names the sample and four-list representation. The
  no-suite brief explicitly requires `suites: []`.

A sample is evidence of an actual run, never a placeholder (R3, SPEC-282). The
validator (below) rejects a sample that declares `"executed": false`, an arm
with no samples at all, and a "zero-count placeholder" — a sample reporting
zero passed, zero failed, and no failing names, which is indistinguishable
from a suite that never ran. Each of the three is a controlled evidence-gap
reason, not an empty passing sample. Do not fabricate a nonzero count to dodge
this check; if an arm genuinely could not be run, that is exactly the
evidence gap the validator exists to surface.

When `verdict` is `disputes_premise`, `premise_dispute` is required and carries
three fields: `claim`, `evidence` (both R5), and `spec_defect: true | false`
(R2, SPEC-ARGO-049) — the verifier's own explicit statement of whether the
dispute names a requirement or AC of *this spec* that is itself wrong or
unmeetable. This is the field Step 5c(e) routes on; it is not inferred by the
parent from the claim text, and the validator rejects a `disputes_premise`
verdict that omits it.

Classification is defined over sample sets, not totals — `any` is the union across
an arm's samples, `all` the intersection:

| Bucket | Definition | Meaning |
|---|---|---|
| `regressed` | `head_all − baseline_any` | fails in **every** head sample, in **no** baseline sample |
| `newly_flaky` | `(head_any − head_all) − baseline_any` | new intermittent failure — not a pass, not a deterministic regression |
| `flaky_observed` | `(head_any − head_all) ∪ ((baseline_any − baseline_all) ∩ head_any)` | pre-existing flake, still reproducing in some head sample; never a regression |
| `fixed` | `baseline_all − head_any` | fails in **every** baseline sample, in **no** head sample — a deterministic failure that is now deterministically gone |
| `flake_resolved` | `(baseline_any − baseline_all) − head_any` | an **intermittent** (not all-fail) baseline failure that reproduces in **zero** head samples — a flake that stopped reproducing, distinct from `fixed`'s all-fail precondition (BUG-024) |

`newly_flaky` exists so the multi-sample rule is not a one-way ratchet. Requiring
"fails in all head samples" alone would silently absolve an introduced race — a
60%-failure race clears a 5-sample all-fail bar 92% of the time. Report it; do not
merge on it without a decision.

`flake_resolved` exists because `fixed`'s `baseline_all − head_any` definition
requires a 100%-baseline-failure precondition that a genuinely intermittent flake
almost never satisfies at any practical sample count (BUG-024: a 13%-flake-rate
test clears a 30-sample all-fail bar with probability ~1e-27). `fixed` and
`flake_resolved` partition the same underlying signal — "failed at least once in
baseline, never in head" (`baseline_any − head_any`) — by whether the baseline
failure was total (`fixed`) or partial (`flake_resolved`); a name can never be in
both. `flaky_observed`'s second term is correspondingly narrowed to
`(baseline_any − baseline_all) ∩ head_any` — a partial baseline flake only stays
`flaky_observed` if it is still reproducing in at least one head sample; once
head_any goes to zero, it moves to `flake_resolved` instead of being silently
absorbed with no distinguishing signal. `flake_resolved` does not weaken
`regressed` or the 3x-minimum sampling rule (Gap Protocol stop-immediately
clause): it still requires the standard per-arm sample count to fire, per the
`need` check below, and it only ever removes failures from view, never adds one.

**d. Validate the verdict — this is the audit (R3/R4/R5).** One command; it recomputes
every classification from the submitted names and never trusts the verifier's arithmetic:

```python
# NIGHTSHIFT-VERDICT-VALIDATOR-BEGIN
# usage: python3 validate_verdict.py <verdict.json> [spec-file] [surface-repo]
#   -> prints report, exit 0 = auditable
# [spec-file] also gates the AC-ID coverage check (below); [surface-repo] --
# the standalone verifier surface containing `verifier-baseline`/`verifier-head`
# -- additionally gates full scope.out_of_scope/.amended recomputation
# (SPEC-300-002 R6) and requires [spec-file] to be supplied too.
import json, re, subprocess, sys
from pathlib import Path

def die(msg): print("SCHEMA:     reject: " + msg); print("GATE:       reject"); sys.exit(1)

v = json.load(open(sys.argv[1]))
for k in ("spec_id","branch","baseline_commit","head_commit","identity_schema_version","implementation_head_digest","verdict","acs","suites","git_footprint","scope","contamination"):
    if k not in v: die("missing top-level key '%s'" % k)
if v["identity_schema_version"] != "1.0.0": die("unsupported verifier identity schema")
if not re.fullmatch(r"[0-9a-f]{64}", v["implementation_head_digest"]): die("invalid implementation_head_digest")
if v["verdict"] not in ("pass","fail","disputes_premise"): die("verdict not in enum: %r" % v["verdict"])

# R5 — disputes_premise must carry its evidence, or it is just an opinion.
# R2 (SPEC-ARGO-049) — and must state explicitly whether the dispute names a
# spec defect, since Step 5c(e) routes on that field, not on the claim text.
if v["verdict"] == "disputes_premise":
    d = v.get("premise_dispute") or {}
    if not d.get("claim") or not d.get("evidence"): die("disputes_premise without premise_dispute.claim + .evidence")
    if not isinstance(d.get("spec_defect"), bool): die("disputes_premise without premise_dispute.spec_defect (bool)")

# R4/R6 — read-only, asserted by hash, over BOTH assigned arm surfaces
# (SPEC-282). A clean baseline arm never masks a dirty head arm or vice versa.
# SPEC-284: the working-tree half is recomputed here as a set comparison of the
# verdict's own porcelain_before against its porcelain_after, never an emptiness
# test on porcelain_after. A worktree that was already dirty at dispatch is not
# the verifier's footprint; an entry only in after (added) or only in before
# (removed) is. That retires the single generated-artifact exclusion this block
# used to carry — pre-existing generated output now cancels in every project,
# with no project's tooling named here. Both fields are REQUIRED: a verdict
# carrying only the old flat `porcelain` key has no before-set to compare
# against, and is rejected rather than read as two empty sets, which would
# accept real dirt.
gf = v["git_footprint"]
if not isinstance(gf, dict) or not {"baseline","head"}.issubset(gf): die("git_footprint must report both baseline and head arms")
for arm_label in ("baseline","head"):
    g = gf.get(arm_label) or {}
    if g.get("tree_before") != g.get("tree_after"): die("%s: verifier mutated the repo (tree %s -> %s)" % (arm_label, g.get("tree_before"), g.get("tree_after")))
    if "porcelain_before" not in g or "porcelain_after" not in g: die("%s: footprint must record porcelain_before and porcelain_after" % arm_label)
    _before = {l for l in (g.get("porcelain_before") or "").splitlines() if l.strip()}
    _after = {l for l in (g.get("porcelain_after") or "").splitlines() if l.strip()}
    _added, _removed = sorted(_after - _before), sorted(_before - _after)
    if _added: die("%s: verifier added to the working tree: %s" % (arm_label, "; ".join(_added)))
    if _removed: die("%s: verifier removed pre-existing working-tree state: %s" % (arm_label, "; ".join(_removed)))

# SPEC-300-002 R6 -- scope schema is always required; full recomputation
# against the verifier-baseline..verifier-head diff runs only when the
# standalone surface repo is supplied as argv[3] (requires argv[2] too).
sc = v["scope"]
if not isinstance(sc, dict) or not {"checked","out_of_scope","amended"}.issubset(sc):
    die("scope must be a dict with checked/out_of_scope/amended")
for _sk in ("checked","out_of_scope","amended"):
    if not isinstance(sc.get(_sk), list) or not all(isinstance(p, str) for p in sc[_sk]):
        die("scope.%s must be a list of path strings" % _sk)
if len(sys.argv) > 3:
    if len(sys.argv) <= 2: die("scope recomputation requires the spec-file argument (argv[2])")
    surface_repo, spec_file_for_scope = sys.argv[3], sys.argv[2]
    kit_dir = Path(spec_file_for_scope).resolve().parent.parent
    sys.path.insert(0, str(kit_dir))
    import scope_guard  # noqa: E402
    spec_text = open(spec_file_for_scope).read()
    scope = scope_guard.resolve_scope(spec_text)
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACDMR", "verifier-baseline", "verifier-head", "--"],
        cwd=surface_repo, capture_output=True, text=True,
    )
    diff_paths = sorted(p for p in diff.stdout.splitlines() if p.strip())
    amend_globs = []
    heading = re.search(r"^## Scope Amendments\s*$([\s\S]*?)(?=^## |\Z)", spec_text, re.M)
    if heading:
        for line in heading.group(1).split("\n"):
            s = line.strip()
            if not s.startswith("|") or re.match(r"^\|[\s:|-]*\|?$", s):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not any(cells) or cells[0] == "Date" or len(cells) < 5 or not cells[1]:
                continue
            amend_globs.append(cells[1])
    project_root = Path(surface_repo)
    # BUG-336 R2: classify_write's spec_relpath must be comparable to the
    # diff paths above, which git reports relative to project_root
    # (surface_repo). spec_file_for_scope is the CLI-supplied spec path
    # (matching scope_gate.py's spec_relpath argument) but, per this
    # embedded validator's own established convention (see
    # test_verifier_gate.py's `_surface_repo_for_scope_recomputation`), is
    # given as a real filesystem path *inside* the standalone surface, not
    # already project-root-relative -- so it is re-expressed relative to
    # project_root here. A spec file that (unusually) lives outside the
    # surface falls back to the raw value, matching prior (non-matching,
    # but no-worse) behavior rather than raising.
    try:
        spec_relpath = str(Path(spec_file_for_scope).resolve().relative_to(project_root.resolve()))
    except ValueError:
        spec_relpath = spec_file_for_scope
    computed_out, computed_amended = [], []
    for p in diff_paths:
        d = scope_guard.classify_write(p, scope, project_root, kit_dir, spec_relpath)
        if d.allowed:
            continue
        if any(scope_guard._glob_match(g, p) for g in amend_globs):
            computed_amended.append(p)
        else:
            computed_out.append(p)
    if sorted(sc["checked"]) != diff_paths:
        die("scope.checked disagrees with the verifier-baseline..verifier-head diff")
    if sorted(sc["out_of_scope"]) != sorted(computed_out):
        die("scope.out_of_scope disagrees with recomputed classification")
    if sorted(sc["amended"]) != sorted(computed_amended):
        die("scope.amended disagrees with recomputed classification")

# R3 — per-AC status, and every AC in the spec covered.
if not v["acs"]: die("no per-AC statuses")
for a in v["acs"]:
    if a.get("status") not in ("pass","fail","unverifiable"): die("%s: bad status %r" % (a.get("id"), a.get("status")))
    if not isinstance(a.get("evidence"), str) or not a["evidence"].strip(): die("%s: evidence must be a non-empty string" % a.get("id"))
if len(sys.argv) > 2:
    # Scope the AC-ID scan to the "## Acceptance Criteria" section only. A
    # whole-file scan false-positives on prose that mentions another spec's
    # AC (e.g. a child spec discussing its parent's "AC6") as if it were an
    # uncovered AC of the spec under verification. Falls back to whole-file
    # if the heading isn't found, so specs without this exact heading still
    # get a check rather than none.
    spec_text = open(sys.argv[2]).read()
    ac_section = re.search(r"^##\s+Acceptance Criteria\s*$(.*?)(?=^##\s|\Z)", spec_text, re.M | re.S)
    want = set(re.findall(r"\bAC\d+\b", ac_section.group(1) if ac_section else spec_text))
    missing = sorted(want - {a.get("id") for a in v["acs"]})
    if missing: die("ACs not covered: %s" % ",".join(missing))

lines, match = [], True
for s in v["suites"]:
    arms = {}
    for arm in ("baseline","head"):
        smp = (s.get("samples") or {}).get(arm)
        if not smp: die("%s: no %s samples" % (s.get("name"), arm))
        for i, one in enumerate(smp):
            # R3 (SPEC-282) — a sample is evidence of an actual run, never a
            # placeholder. Reject an explicit non-execution marker...
            if one.get("executed") is False: die("%s/%s[%d]: declared executed:false — controlled evidence gap, not a passing sample" % (s.get("name"), arm, i))
            # R3 — names, not totals.
            if not isinstance(one.get("failing"), list): die("%s/%s[%d]: totals-only verdict, no failing-name list" % (s.get("name"), arm, i))
            if "failed" in one and one["failed"] != len(one["failing"]): die("%s/%s[%d]: failed=%s but %d names" % (s.get("name"), arm, i, one["failed"], len(one["failing"])))
            # ...and a synthetic zero-count placeholder: zero passed, zero
            # failed, no failing names is indistinguishable from a suite that
            # never ran.
            if one.get("passed", 0) == 0 and one.get("failed", 0) == 0 and not one["failing"]:
                die("%s/%s[%d]: zero-count placeholder — no evidence the suite actually ran" % (s.get("name"), arm, i))
        sets = [set(o["failing"]) for o in smp]
        arms[arm] = (set().union(*sets) if sets else set(), set.intersection(*sets) if sets else set(), len(sets))
    (b_any,b_all,b_n), (h_any,h_all,h_n) = arms["baseline"], arms["head"]
    # R4 — a single draw per arm may never be reported as a difference.
    need = 3 if (s.get("flaky_suspected") or b_any != h_any or b_any != b_all or h_any != h_all) else 1
    if min(b_n,h_n) < need: die("%s: %d/%d samples but %d per arm required (single-draw comparison is not a valid verdict)" % (s.get("name"), b_n, h_n, need))
    # BUG-024: `fixed` (baseline_all - head_any) requires a 100%-baseline-failure
    # precondition a genuinely intermittent flake almost never satisfies. `fixed`
    # and `flake_resolved` partition baseline_any - head_any ("failed at least
    # once in baseline, never in head") by whether the baseline failure was
    # total (`fixed`) or partial (`flake_resolved`) -- disjoint by construction,
    # since baseline_all and (baseline_any - baseline_all) already partition
    # baseline_any. flaky_observed's second term is narrowed to intersect with
    # head_any so a partial baseline flake that stops reproducing at head moves
    # to flake_resolved instead of staying silently absorbed in flaky_observed;
    # it stays disjoint from (head_any - head_all) since flake_resolved requires
    # head_any empty for that name while (head_any - head_all) requires it
    # present in head_any.
    rec = {"regressed": sorted(h_all - b_any), "newly_flaky": sorted((h_any - h_all) - b_any),
           "flaky_observed": sorted((h_any - h_all) | ((b_any - b_all) & h_any)),
           "fixed": sorted(b_all - h_any), "flake_resolved": sorted((b_any - b_all) - h_any)}
    dec = {k: sorted(s.get("classification", {}).get(k, [])) for k in rec}
    if dec != rec: match = False
    lines.append("  %-24s regressed=%s newly_flaky=%s flaky_observed=%s fixed=%s flake_resolved=%s" % (s.get("name"), rec["regressed"], rec["newly_flaky"], rec["flaky_observed"], rec["fixed"], rec["flake_resolved"]))

print("SCHEMA:     ok")
print("RECOMPUTED:")
for l in lines: print(l)
print("DECLARED_MATCH: " + ("yes" if match else "no"))
print("VERDICT:    " + v["verdict"])
print("GATE:       " + ("accept" if match else "reject"))
sys.exit(0 if match else 1)
# NIGHTSHIFT-VERDICT-VALIDATOR-END
```

`GATE: reject` means the verdict is **not auditable** — the verifier's own numbers
contradict its own samples. Treat it exactly like a missing verdict: do not merge,
and route to the controller-backed unblock path with
`Nightshift-Blocker-Class: evidence_gap`.

**e. Route on the validated verdict.**

Before routing a validated `fail` to terminal blocking, use the managed
`verifier_feedback.py` boundary. Only a current, uncontaminated, independently
produced failure with complete AC evidence and a clean footprint can create the
parent-signed packet. The parent selects exactly one remediation mode
(`resume_original` or `fresh_worker`), preserves the original authority, and
requires a newly independent verifier on the changed head before integration.
The verifier and remediation actor never communicate directly, mutate lifecycle,
merge, or self-accept.

Packet admission recomputes the containment binding from the parent-private exact
candidate revision, then requires the verdict's synthetic `head_commit` and opaque
`implementation_head_digest` to equal the dispatch plan and evidence. A legacy
failure verdict without the digest is rejected as `legacy_verdict_identity`.
After remediation, compare exact private Git revisions first, prepare a new
contained surface, validate its new identity pair, persist it, and only then
request the fresh verifier. Reducer events and replay keys use the digest, not the
Git object ID.

Invalid/contaminated verdicts create no packet and permit only one replacement
verifier on the unchanged head. Remediation or dispatch failure, unchanged head,
a second invalid verdict, or a fresh valid failure exhausts the bounded path and
resolves through controlled blocked policy. Record each actor attempt separately
from the parent delivery result via the configured SPEC-224 adapter. The typed
admission seam handles both sources without adding another lifecycle owner
(SPEC-235-001).
`implementer_blocked` is an attempt fact that opens a parent-owned assessment:
retain and hash-inventory the candidate, validate the closed diagnosis envelope,
classify mechanical evidence, use at most one read-only diagnostician for safe
uncertainty, and dispatch at most one bounded `resume_original` or
`fresh_specialist` repair. Reuse keyed effects after callback loss, polling, or
restart; never renew allowances on reconnect. A changed repair must pass a newly
independent verifier and the coordinator's serialized fresh-main integration
before delivery may close.

After the verdict validator has produced the auditable verdict, publish the
actual verification outcome exactly once. Map `pass` to `passed`, `fail` to
`failed`, and an unresolved or unauditable result to `unknown`; this optional
publication does not change the routing table below.

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event verification.completed --outcome "{VERIFICATION_OUTCOME}"
```

| `VERDICT` | Parent action |
|---|---|
| `pass` | continue to Step 6; check 5 of the evidence gate is satisfied |
| `fail` | do not merge; Step 6's controller-backed unblock path |
| `disputes_premise` with `premise_dispute.spec_defect: true` | **not a failure**, and never a merge on the verifier's authority. The verifier's own R2 field says a requirement or AC of *this spec* is wrong or unmeetable. Record the dispute verbatim in the run report and parent progress artifact, then submit any loosened AC to the independent `nightshift-ac-reviewer`, retain its valid `reports/<SPEC>/ac-review.json`, and add the approved old → new row to `## AC Amendments`; re-run the gate and continue to `done`. A veto leaves the expectation intact and routes to blocked/user authorization. The dispute is evidence for a parent decision, never the decision itself. |
| `disputes_premise` with `premise_dispute.spec_defect: false` | **not a failure, and not an unresolved spec expectation** (SPEC-ARGO-049 R1/R3). The verifier's own R2 field says no requirement or AC of this spec is in question — the dispute is against something else (an enforcement gate, a tool, a parent-level claim outside the spec). There is no spec expectation to amend, and `blocked`/`evidence_gap` stays reserved for a genuinely unresolved **spec** expectation (R3), so it does not apply here either. Record the dispute verbatim in the run report and the parent progress artifact, file it as follow-up work (a new spec or TODO item — cite the ID once created), and continue to the ordinary evidence gate: once the follow-up is filed, this verdict satisfies check 5 (Step 6). |
| missing / `GATE: reject` | treat as `evidence_gap`; do not merge |

Record the outcome in both the report and the lifecycle commit trailer
`Nightshift-Evidence-Verifier:` (Step 6). Canonical `record_metrics.py` reads a
fixed set of trailer keys and ignores unknown ones, so this trailer is durable and
greppable in git today but is **not** yet consumed into metrics.

### Step 6: Post-run resolution

When the agent completes, run **Step 5c first** — dispatch the verifier and validate its
verdict — then resolve the run autonomously using the evidence gate below. Do **not**
offer merge/discard choices to the user, and do **not** re-derive the verifier's evidence
yourself; make the decision from the validated verdict.

**Completion notification is a terminal-resolution trigger.** On receipt, the
parent immediately records `terminal_resolution: evidence_gate_running` and its
start timestamp in the parent progress artifact, stops the watchdog, and executes
this Step 6. `awaiting parent integration` is not a permitted steady state: it is
only the in-process label while the evidence gate is running. The same completion
event must produce one terminal result (`done` or `blocked`) and record elapsed
resolution time before the parent becomes idle; it must never wait for a human
status ping.

> Because the run was launched in the background (Step 5), read the worktree `<branch>` and `<path>` used in the commands below from the **completion notification's result payload** — there is no foreground return value. Also `TaskStop` the liveness watchdog now if it is still armed.

**Parent tool-call tally (mandatory — R1/R2, SPEC-ARGO-059).** Every completed kickoff resolution
records the parent coordinator's own tool-call count for this pass in a git-tracked artifact — not
optional, not left to discretion. **Counted:** every tool call the parent itself makes, starting
immediately after launching the run agent (Step 5) and ending at this pass's terminal resolution
(the `done` or `blocked` lifecycle commit below) — monitoring, the Step 5c verifier dispatch and
audit, the evidence gate, and the resolution commit itself all count. **Not counted:** anything the
launched run worker or the Step 5c verifier did inside their own agent invocations — the worker's
count is already captured separately (the Agent completion notification's `tool_uses` field).
There is no API-level ground truth to check this against: it is necessarily a self-tally the parent
keeps and reports as it goes, not an independently audited number — state it as counted, never
rounded or estimated. Record it in the terminal lifecycle commit (`done` or `blocked`, both below,
`commit-backed` policy only — see note there for `private-local`) as two trailers, never only in the
report or the gitignored progress artifact:

```
Nightshift-Parent-Tool-Calls: <N>
Nightshift-Resolution-Kind: <verifier-dispatched|self-verified|self-verified-experimental>
```

`Nightshift-Resolution-Kind` has three values, and a bare guess is never acceptable — record what
this pass actually did (SPEC-ARGO-061 R1/R3):

- **`verifier-dispatched`** — Step 5c's dispatch step was actually executed for this pass: an
  independent `nightshift-verifier` agent was launched. **The only normal path**, since Step 5c is
  mandatory for every spec, including docs/protocol-type specs with no test suite (SPEC-ARGO-061 R1
  decision; the (a-alt) brief in Step 5c is what makes that practical, not an excuse to skip
  dispatch). This value covers **every** outcome of a real dispatch attempt, not only a clean
  `pass` — a `fail` verdict, a `GATE: reject` (unauditable verdict), or an agent that launched but
  produced no usable verdict are still `verifier-dispatched`; the *quality* of what dispatch
  produced is recorded separately, via `Nightshift-Evidence-Verifier` and `Nightshift-Blocker-Class:
  evidence_gap` on the resulting `blocked` commit, never by reaching for a different
  `Resolution-Kind` value. `Resolution-Kind` answers one question only — did Step 5c's dispatch
  mechanism run for this pass, or was it deliberately bypassed — so a legitimate `blocked`
  resolution after a failed or unauditable verdict is `verifier-dispatched`, same as a `done` one.
  The one case dispatch never ran at all — the verifier agent's *launch itself* was rejected
  (SPEC-ARGO-037's `launch_failure` outcome, Step 5's launch-rejection branch) — is still recorded
  as `verifier-dispatched` here too: the parent attempted Step 5c's mandatory dispatch as required,
  the launch failure is what the controller-backed unblock/retry path and the SPEC-ARGO-037 outcome
  row exist to capture, and it is not evidence of a bypassed Step 5c the way a self-verified value
  would be.
- **`self-verified-experimental`** — dispatch was **deliberately** not performed for this pass,
  solely because this run was pre-designated, before it started, as a bounded comparison sample for
  a self-verified-arm measurement. This is the **only** sanctioned use of self-verification going
  forward — narrow, pre-declared, and never opportunistic ("this one looked easy to self-check" is
  not a qualifying reason). A pass using this value MUST also carry a
  `Nightshift-Experimental-Sample-For: <designating-spec-id>` trailer and a one-line reason in the
  commit body naming which comparison pair it fills. The originating designation was
  `SPEC-ARGO-038-001` (project-local, Argo Home); **`SPEC-ARGO-038-001` is superseded by canonical
  `SPEC-223`** (`canonical/specs/SPEC-223-measure-verified-versus-self-verified-context-spend.md`),
  which is itself currently blocked pending exactly this sample type. Before designating a new
  sample, read the currently-live designating spec's own file for the exact count/status required —
  do not assume `SPEC-ARGO-038-001` is still the live target, and do not assume `SPEC-223` will
  remain the only legitimate designator going forward; a later spec may supersede it in turn.
  `SPEC-ARGO-038-001` remains the historical discovery/partial-evidence record and is not deleted
  from this text.
- **`self-verified`** (without `-experimental`) — reserved for a pass where this convention did not
  exist yet or was not followed. **As of SPEC-ARGO-061, a bare `self-verified` on any new commit is
  itself a protocol violation, not a legitimate outcome** — R1's decision closed the "rare case
  dispatch could not happen" carve-out that used to justify it. If dispatch genuinely cannot happen
  (e.g. verifier agent launch failure), that is a `launch_failure` under the SPEC-ARGO-037 outcome
  recording and the controller-backed unblock/retry path — it does not fall back to the parent
  self-verifying and writing plain `self-verified`. A future reader must not confuse a bare
  `self-verified` commit with a deliberate `self-verified-experimental` one: the trailer value is
  the whole distinction, and the two are never interchangeable or backfillable into each other.

**Runs resolved before this instruction existed have no recoverable count.** A future reader
(including `SPEC-ARGO-038-001`) must report those as `unavailable` — never estimate, reconstruct, or
backfill a number for them, no matter how plausible an estimate would be. Likewise, a pre-SPEC-ARGO-061
`self-verified` commit is not retroactively relabeled `self-verified-experimental` — Out of Scope
for SPEC-ARGO-061 explicitly forbids reclassifying prior sessions' self-verified resolutions.

**Evidence gate (all six must pass to merge):**

1. **Report exists** — `reports/YYYY-MM-DD-nightshift-report.md` is present in the worktree.
2. **Tests passed** — report contains no `❌` on test-result lines.
3. **Code changed** — `git diff main..<branch>` has changes to files outside `reports/`.
4. **ACs covered** — report AC checklist has zero `❌` items (⚠️ with explanation is acceptable).
5. **Verifier verdict** — a Step 5c verdict exists, the validator printed
   `GATE: accept`, and either `VERDICT` is `pass`, or `VERDICT` is
   `disputes_premise` with `premise_dispute.spec_defect: false` and the
   dispute has been filed as follow-up work per Step 5c(e). Checks 1–4 read
   the run's *own* report; check 5 is the only one sourced independently of
   the author, which is why it is the one that must be dispatched, not
   re-derived by the parent. A `disputes_premise` verdict with
   `premise_dispute.spec_defect: true` does not satisfy check 5 and does not
   fail it — resolve the premise per Step 5c(e) first (it routes to
   `blocked`, per R3), then re-evaluate the gate. **The one sanctioned
   substitute for check 5** is a pass whose `Nightshift-Resolution-Kind` will be
   `self-verified-experimental` (SPEC-ARGO-061 R3): no Step 5c verdict exists
   because dispatch was deliberately skipped for a pre-designated sampling run
   (originally `SPEC-ARGO-038-001`, now superseded by canonical `SPEC-223` — see
   the Resolution-Kind section above for the currently-live designator), so the
   parent evaluates checks 1–4 and the ACs directly instead, and records
   that substitution via the trailer pair, never by leaving check 5 silently
   unaddressed. This is not available for a bare `self-verified` outcome — that
   value records a violation, not a passing gate.
6. **Scope** (SPEC-300-002 R1) — every path in `git diff --name-only
   <baseline>..<branch>` (added, modified, deleted, both sides of a rename)
   is classified by `scope_guard.py` against the spec's declared write scope,
   read from the spec file **on the configured main branch** — never the
   worker branch or the working tree (SPEC-300 R3). Runs after check 5, before
   the merge decision. Any `DENY` fails the gate. Skip this check, recording
   `Nightshift-Scope-Check: not_run` and a report warning naming the missing
   file, **only** when `scope_guard.py` is absent from the install — never
   because the spec has no `scope:` (R9): an absent `scope:` still resolves to
   the project-root default, which check 6 evaluates like any other scope.

   Run the embedded gate script against the candidate branch:

   ```python
   # NIGHTSHIFT-SCOPE-GATE-BEGIN
   # usage: python3 scope_gate.py <project-root> <spec-relpath> <main-branch> <baseline> <branch>
   #   -> one "ALLOW|AMENDED|DENY <reason> <path>" line per changed path, then:
   #        SCOPE-CHECK: clean | amended | violated | not_run
   #        REASON: <path> (<reason>), <path> (<reason>), ...   (omitted when clean)
   #      exit 0 unless violated; not_run also exits 0 (R9 — a missing resolver
   #      never blocks the run, it only forces the recorded trailer).
   import re
   import subprocess
   import sys
   from pathlib import Path

   project_root, spec_relpath, main_branch, baseline, branch = sys.argv[1:6]
   project_root = Path(project_root).resolve()
   kit_dir = (project_root / spec_relpath).resolve().parent.parent
   sys.path.insert(0, str(kit_dir))
   try:
       import scope_guard  # noqa: E402
   except ImportError:
       print("SCOPE-CHECK: not_run")
       print(f"WARNING: scope_guard.py not found under {kit_dir} — check 6 skipped")
       sys.exit(0)

   scope = scope_guard.scope_from_main(project_root, spec_relpath, main_branch)
   spec_text_main = subprocess.run(
       ["git", "show", f"{main_branch}:{spec_relpath}"],
       cwd=project_root, capture_output=True, text=True,
   ).stdout
   diff = subprocess.run(
       ["git", "diff", "--name-only", "--diff-filter=ACDMR", f"{baseline}..{branch}"],
       cwd=project_root, capture_output=True, text=True,
   )
   paths = [p for p in diff.stdout.splitlines() if p.strip()]

   amend_globs = []
   heading = re.search(r"^## Scope Amendments\s*$([\s\S]*?)(?=^## |\Z)", spec_text_main, re.MULTILINE)
   if heading:
       for line in heading.group(1).split("\n"):
           s = line.strip()
           if not s.startswith("|") or re.match(r"^\|[\s:|-]*\|?$", s):
               continue
           cells = [c.strip() for c in s.strip("|").split("|")]
           if not any(cells) or cells[0] == "Date" or len(cells) < 5 or not cells[1]:
               continue
           amend_globs.append(cells[1])

   # AC3 — a worker branch that edits its own spec's `scope:` on the branch is
   # classified against MAIN's scope regardless (the scope resolution above
   # already only ever reads main), but `scope_guard.classify_write`'s
   # `spec_self` rule would otherwise let the spec's own file diff itself pass
   # unconditionally (SPEC-300-001's carve-out for ordinary bookkeeping edits
   # -- checklists, block_reason, etc.). Check 6 narrows that carve-out: when
   # the branch's own copy of `scope:` differs from main's, the spec file
   # itself is reported as an out-of-scope write (never `spec_self`), because
   # that is exactly the self-widening SPEC-300 forbids. An ordinary edit that
   # leaves `scope:` unchanged keeps the normal `spec_self` allow.
   spec_text_branch = subprocess.run(
       ["git", "show", f"{branch}:{spec_relpath}"],
       cwd=project_root, capture_output=True, text=True,
   ).stdout
   # SPEC-302: compare against main's *raw* (unreconciled) scope, not the
   # `scope` variable above — `scope_from_main` may have rolled an uncovered
   # widening back to the last-`ready` value, and a worker branch that only
   # ticks a checklist box in its own spec (leaving `scope:` byte-identical
   # to main's raw frontmatter) must not be flagged for a widening it never
   # made and cannot fix.
   scope_self_edit = (
       spec_relpath in paths
       and scope_guard.resolve_scope(spec_text_branch) != scope_guard.resolve_scope(spec_text_main)
   )

   out_of_scope, amended = [], []
   for path in paths:
       if path == spec_relpath and scope_self_edit:
           decision_allowed, decision_reason = False, "scope_self_edit"
       else:
           decision = scope_guard.classify_write(path, scope, project_root, kit_dir, spec_relpath)
           decision_allowed, decision_reason = decision.allowed, decision.reason
       if decision_allowed:
           print(f"ALLOW {decision_reason} {path}")
           continue
       if any(scope_guard._glob_match(g, path) for g in amend_globs):
           print(f"AMENDED {decision_reason} {path}")
           amended.append((path, decision_reason))
       else:
           print(f"DENY {decision_reason} {path}")
           out_of_scope.append((path, decision_reason))

   status = "violated" if out_of_scope else ("amended" if amended else "clean")
   print(f"SCOPE-CHECK: {status}")
   if status != "clean":
       offenders = out_of_scope if status == "violated" else amended
       print("REASON: " + ", ".join(f"{p} ({r})" for p, r in offenders))
   sys.exit(1 if status == "violated" else 0)
   # NIGHTSHIFT-SCOPE-GATE-END
   ```

   `SCOPE-CHECK: clean` and `SCOPE-CHECK: amended` both satisfy check 6 (an
   amendment is a human-approved widening, not a violation) and set
   `Nightshift-Scope-Check` to that exact value on the terminal `done` commit.
   `SCOPE-CHECK: violated` fails check 6; its `REASON:` line — one
   `<repo-relative-path> (<reason-code>)` entry per offending path,
   comma-separated — becomes both the spec's `block_reason` (R2) and
   `unblock_spec.py`'s only parseable record of which paths still need an
   amendment (R8). `SCOPE-CHECK: not_run` satisfies check 6 mechanically (R9)
   but is still recorded verbatim, never silently folded into `clean`.

**If all six pass → merge and clean up:**

```bash
git merge --no-ff <branch>
git worktree remove <path>
git branch -d <branch>
```

In `commit-backed`, first record the SPEC-291 transition artifact for the
evidence-gated `in_progress -> done` transition about to be made — its reason
synthesizes from the run ID, no prose required — *before* flipping status and
committing, so the artifact file exists on disk to be staged in the same
commit (writing it after would leave it untracked):
```bash
python3 .nightshift/spec_artifacts.py record-transition <spec-file> \
  --from in_progress --to done --run-id <started-run-id>
```

Resolve terminal status on main. In `commit-backed`, flip to `done` and
commit, staging both the spec file and its `reports/<spec-id>/artifacts/`
directory (the sibling of the specs directory's `reports/` —
`.nightshift/reports/...` deployed, `canonical/reports/...` in this kit
repo — not bare `reports/` from the project root):
```
chore: mark <spec-id> done

Nightshift-Evidence-Report: pass
Nightshift-Evidence-Tests: pass
Nightshift-Evidence-Code: pass
Nightshift-Evidence-ACs: pass
Nightshift-Evidence-Verifier: <pass|disputes_premise>
Nightshift-Blocker-Class: none
Nightshift-Blocker-Scope: none
Nightshift-Scope-Check: <clean|amended|not_run>
Nightshift-Unblock-Attempts: 0
Nightshift-Unblock-Limit: 1
Nightshift-Unblock-Rung: <0|1|2|3|4|5>
Nightshift-Parent-Tool-Calls: <N>
Nightshift-Resolution-Kind: <verifier-dispatched|self-verified|self-verified-experimental>
Nightshift-Experimental-Sample-For: <currently-live designating spec (e.g. canonical SPEC-223, which supersedes the original SPEC-ARGO-038-001 designation — read that spec's own file for the live target before writing this trailer) | omit unless Resolution-Kind is self-verified-experimental>
```

**BUG-017 — one contiguous trailer paragraph, no exceptions.** If this session's
attribution convention also requires trailers such as `Co-Authored-By:` or
`Claude-Session:` on this commit, append them as additional lines **inside this
same block**, directly below `Nightshift-Experimental-Sample-For`/`Nightshift-Resolution-Kind`
— zero blank lines between any two trailer lines. Never put them in a second
paragraph after a blank line, and never glue this block directly onto free-form
prose with no blank line separating them either. Git's trailer parser
(`%(trailers:...)`, which `record_metrics.py` depends on) recognizes only the
single, last, blank-line-delimited paragraph of the commit message, and only
when every line in it is trailer-shaped — a second trailer-shaped paragraph
after this one silently hides this entire block from every `Nightshift-*`
reader, and prose glued onto this block with no preceding blank line hides
everything, including the attribution trailers. The required shape is exactly:
one blank line between the free-form body and the trailer block, then every
trailer — `Nightshift-*` and attribution alike — as one uninterrupted run of
`Key: value` lines.

`Nightshift-Evidence-Verifier` records the validated `VERDICT` value verbatim —
`disputes_premise` here only ever means `premise_dispute.spec_defect: false`
(SPEC-ARGO-049 R1), since `spec_defect: true` cannot satisfy check 5 (it routes
to `blocked`). When it is `disputes_premise`, cite the filed follow-up
spec/TODO ID in the commit body or the run report, not just in the trailer.

If a controller-backed recovery was required, set
`Nightshift-Unblock-Attempts: 1`; the other successful-gate trailers stay the
same. These trailers are consumed mechanically by `record_metrics.py
--mark-commit`. The matching `in_progress` commit becomes the stable `run_id`,
so a blocked transition and a later recovery remain one analyzable run.
Set `Nightshift-Unblock-Rung` to `0` when no drive-to-done rung was entered, or
to the final entered rung (`1` through `5`) when the ladder ran.

**Terminal-trailer correction on a shared branch (SPEC-275).** Never use `git
commit --amend` to repair a terminal trailer on a shared branch: a concurrent
writer may have advanced `HEAD`, and amend would rewrite that writer's commit.
Instead create a separate correction commit with the corrected trailers and a
subject that does **not** match `MARK_COMMIT_RE`, then explicitly run
`record_metrics.py --correct-commit <bad-terminal-sha> --repo <project-root>`.
The post-commit hook cannot invoke this path and the existing metrics row is
patched in place; no second `chore: mark ...` transition is created. If an amend
is otherwise permitted, first run `record_metrics.py --verify-amend-head
<captured-40-character-sha> --repo <project-root>` using the exact SHA captured
immediately after this session's own prior commit. A mismatch is a hard stop. If
you discover that another session's commit was already rewritten, stop writing
and hand the choice to that commit's owner; do not attempt a compensating rewrite.

In `private-local`, do not make a lifecycle commit. After the same evidence gate
and serialized application merge, call `transition_private_state(..., "done",
run_id=<started-run-id>, owner="coordinator", assigned_spec=<spec-id>)`. Derive
resolution metrics with `record_metrics.derive_local_resolution`; it must resolve
the same durable run without searching Git history. `Nightshift-Parent-Tool-Calls` /
`Nightshift-Resolution-Kind` are commit trailers and R2 requires the artifact to be
git-tracked, so this instrumentation does not apply under `private-local` today —
recording the tally there needs its own private-state field, out of scope for
SPEC-ARGO-059. Run the SPEC-291 `record-transition` command above regardless of
mode — the artifact lives under `reports/<spec-id>/artifacts/`, a spec-side,
git-tracked record independent of which lifecycle-checkpoint proof was used.

Tell the user: spec ID, what landed, test count, report path. One paragraph.

Record `terminal_resolution: done` and `terminal_resolution_elapsed_s` in the
parent progress artifact only after the merge, cleanup, and durable terminal
state have all succeeded.

After that durable `done` state exists, publish the terminal fact and do not
wait for its optional consumer:

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event run.completed --outcome passed
```

**If check 6 (scope) fails → block directly; do not enter the controller-backed
ladder automatically (SPEC-300-002 R2).** A scope violation is a
human-decided class, not a mechanical recovery: skip straight to "block and
escalate" below with `blocker_class: scope_violation`,
`blocker_scope: out_of_scope`, `block_reason` set to check 6's `REASON:` line
(one `<path> (<reason-code>)` entry per offending path), and
`unblock_condition: scope amendment approved on main, or offending paths
removed from the branch`. Do not call `unblock_spec.py prepare` as part of
this automatic terminal resolution — a human adds the `## Scope Amendments`
row on main first; only then may `unblock_spec.py prepare` be invoked (by a
human or a later pass) and return eligible for rung 1 (R8). A worker that
itself returned `worker-blocked` with a `## Scope Blockers` report section
(path, reason, proposed scope change) is resolved exactly this way too — copy
`block_reason` verbatim from that section, and never apply the worker's
proposed scope change on its behalf (R7); the parent is not a scope
authority.

**If any other check fails or the orchestrator reports blocked/stuck → invoke the controller-backed unblock protocol:**

Keep the spec `in_progress` while the parent creates the durable blocked evidence
required by the lifecycle contract, then use `unblock_spec.py prepare` with the
same stable run ID. The parent records every result with `record_attempt` and is
the sole caller of `finalize`; parent remains the sole lifecycle and merge owner.
It never asks the worker to mutate lifecycle state, merge, or finalize metrics.
An eligible packet permits exactly one isolated,
bounded recovery worker. A skipped or failed packet records the controller-produced
next safe action and causal confidence, leaves the spec blocked, and forbids an
automatic retry for the unchanged fingerprint. For a `scope_violation` packet
(SPEC-300-002 R8), `prepare` reports `eligibility: skipped` with next safe
action "human scope decision" unless a `## Scope Amendments` row now exists on
main covering every path named in `block_reason`, in which case it reports
`eligibility: eligible` and rung 1 may run ordinarily — this is the one
class where a later `prepare` call on the *same* blocked spec can flip from
skipped to eligible without a new blocker, because the human-approved
amendment is exactly the fact that changes.

Only a verified `record_attempt(... outcome="succeeded")` followed by `finalize`
may transition `blocked -> ready`. Rerun ordinary admission and the fresh-main
evidence gate from that ready state; do not jump from blocked to `in_progress` or
`done`. The recovery report must include the packet/attempt artifact references,
verification result, human-action flag, and a Causal confidence line. When the
mechanism is not proven by before/after evidence it says `not_established`, not a
speculative explanation of why it worked.

**If controller recovery fails or cannot run → block and escalate:**

1. Mark the spec blocked on main. For `commit-backed`, use the failure persistence helper (`failure_persistence.py` in the project's `.nightshift/` or `canonical/` directory):
   ```bash
   python3 -c "
   import sys; sys.path.insert(0, '.nightshift')
   from failure_persistence import mark_spec_blocked
   from pathlib import Path
   mark_spec_blocked(Path('specs/<spec-file>'), '<specific reason: which check(s) failed and why>')
   "
   ```

   For `private-local`, call `transition_private_state(..., "blocked",
   run_id=<started-run-id>, owner="coordinator", assigned_spec=<spec-id>,
   note=<specific reason>)` instead. It must leave one terminal checkpoint and no
   staged/committed private path. Run the SPEC-291 `record-transition` command
   below (with `--reason`) regardless of mode.

   `-> blocked` is a judgment transition (SPEC-291 R3): record the transition
   artifact *before* committing (below), so the artifact file exists on disk
   to be staged in the same commit — an empty reason is refused, not silently
   skipped:
   ```bash
   python3 .nightshift/spec_artifacts.py record-transition <spec-file> \
     --from in_progress --to blocked --run-id <started-run-id> \
     --reason "<specific reason: which check(s) failed and why>"
   ```

2. In `commit-backed`, commit on main: stage both the spec file and its
   `reports/<spec-id>/artifacts/` directory (the sibling of the specs
   directory's `reports/`, not bare `reports/` from the project root — see
   Step 2b).
   ```
   chore: mark <spec-id> blocked

   <one-line reason>

   Nightshift-Evidence-Report: <pass|fail|unknown>
   Nightshift-Evidence-Tests: <pass|fail|unknown>
   Nightshift-Evidence-Code: <pass|fail|unknown>
   Nightshift-Evidence-ACs: <pass|fail|unknown>
   Nightshift-Evidence-Verifier: <pass|fail|disputes_premise|unknown>
   Nightshift-Blocker-Class: <implementation|test_infrastructure|fixture_drift|baseline_regression|external_input|evidence_gap|scope_violation|unknown>
   Nightshift-Blocker-Scope: <in_scope|out_of_scope|mixed|unknown>
   Nightshift-Scope-Check: <violated|not_run|clean|amended>
   Nightshift-Unblock-Attempts: <0|1>
   Nightshift-Unblock-Limit: 1
   Nightshift-Unblock-Rung: <0|1|2|3|4|5>
   Nightshift-Parent-Tool-Calls: <N>
   Nightshift-Resolution-Kind: <verifier-dispatched|self-verified|self-verified-experimental>
   Nightshift-Experimental-Sample-For: <currently-live designating spec (e.g. canonical SPEC-223, which supersedes the original SPEC-ARGO-038-001 designation — read that spec's own file for the live target before writing this trailer) | omit unless Resolution-Kind is self-verified-experimental>
   ```

   **BUG-017 — same single-paragraph rule as the `done` commit above applies here.**
   If attribution trailers (`Co-Authored-By:`, `Claude-Session:`, or equivalent)
   are also required, append them as more lines inside this same trailer block —
   never as a separate blank-line-delimited paragraph, and never with no blank
   line at all between the one-line reason above and this block. Git's trailer
   parser only recognizes one contiguous, fully trailer-shaped final paragraph;
   splitting or omitting the blank line silently hides `Nightshift-*` trailers
   from every reader, including `record_metrics.py`.

   The subject line is exactly `chore: mark <spec-id> blocked` with no trailing suffix —
   this is what `record_metrics.MARK_COMMIT_RE` and `hooks/commit-msg` both enforce. The
   one-line reason goes as the first line of the commit body, above the trailer block; it
   is for human/git-log readability only — `derive_block_reason` reads the reason from the
   spec file's own `block_reason`, not from the commit.

   The tool-call tally and resolution-kind trailers are mandatory here too (R2's "terminal
   resolution" includes `blocked`, not only `done`) — same definitions as the done-path
   instruction above: count the parent's own tool calls from Step 5 launch to this commit,
   self-tallied and unaudited, and record which resolution kind actually occurred.

   Classify the blocker by observed cause, not by the worker's status. Use
   `fixture_drift` for stale/mutated expected artifacts, `test_infrastructure`
   for harness/port/environment failures, `evidence_gap` when implementation may
   be sound but a required gate cannot be demonstrated, `implementation`
   for a defect in the spec's delivered code, and `scope_violation` (SPEC-300-002
   R3) when evidence-gate check 6 denied a path — always with `blocker_scope:
   out_of_scope`, and see the "check 6 fails" carve-out above for the routing
   difference: this class never enters the controller-backed ladder
   automatically. Scope says whether the required fix belongs to the
   kicked-off spec.

3. Write a Cortex breadcrumb:
   `mcp__cortex__cortex_breadcrumb`: `"Spec <spec-id> blocked after kickoff run: <reason>"`

4. Leave the worktree in place for inspection. Tell the user:
   - Which evidence check(s) failed and what is specifically missing
   - Which controller recovery attempt was recorded, or why it was skipped
   - Worktree path for manual inspection of partial work
   - Suggested next step (fix the gap and re-run, or investigate the blocker)

**Record each dispatched agent's response state (SPEC-ARGO-037).** Terminal
resolution is not complete until one outcome row exists per agent this run
dispatched — the run worker, the Step 5c `nightshift-verifier`, and any bounded
recovery worker. This runs on **both** branches: a blocked run is exactly the case
the field exists to measure, and a run that never produced a worker still
dispatched one.

<!-- SPEC-ARGO-037-RESOLUTION-BEGIN -->
```bash
# One record per dispatched agent. agent_response is the PARENT's observation of
# whether that agent responded — never the agent's own account, because the agent
# this field exists to catch is the one that stopped answering.
#
#   completed              engaged and reached its own terminal state
#   refused_with_evidence  declined, and stated a reason  <- NOT a failure
#   no_response            launched, never acted (heartbeat stuck at parent-seeded,
#                          zero tool calls, zero commits)
#   stalled_mid_task       acted, then froze with work incomplete
#   partial_abandoned      landed partial work, then went unresponsive
#   launch_failure         launch was REJECTED; no worker ever ran (Step 5a branch)
#
# Everything except `completed` needs agent_response_evidence: the parent-observable
# facts. Heartbeat state, tool-call count, commit count, or the refusal's reason.
python3 "$ARGO_HOME/Skills/delegate/scripts/record_agent_outcome.py" --allowed-values
python3 "$ARGO_HOME/Skills/delegate/scripts/record_agent_outcome.py" --append /tmp/outcome-{spec-id}.json
```
<!-- SPEC-ARGO-037-RESOLUTION-END -->

The writer rejects a record with a missing or off-enum `agent_response` and names
the allowed values; the `pre-commit` guard it installs rejects a hand-edited row
that skipped it. Do not classify a `refused_with_evidence` as a stall because the
run did not land — a correct refusal is the system working, and folding the two
together is the one thing the vocabulary exists to prevent.

**Status discipline:** never leave a spec stuck at `in_progress` after the kickoff
resolves. One of `done` or `blocked` must be visible in both frontmatter and the
durable status reader. Commit it only in `commit-backed`; private-local uses the
matching local run event. The board uses the existing reconciliation path.

Before becoming idle on this path, record `terminal_resolution: blocked` and
`terminal_resolution_elapsed_s` in the parent progress artifact. A failed evidence
gate has one and only one controller-backed unblock pass; its skipped, failed, and
successful outcomes all continue to a terminal state rather than `awaiting parent
integration`.

After the durable `blocked` state exists, publish the terminal fact and do not
wait for its optional consumer:

```bash
PROJECT_ROOT=$(git rev-parse --show-toplevel) &&
"$PROJECT_ROOT/.nightshift/extension_checkpoint.sh" \
  --project-root "$PROJECT_ROOT" --run-id "{RUN_ID}" \
  --spec-id "{SPEC_ID}" --run-kind "{RUN_KIND}" \
  --event run.completed --outcome blocked
```

### Step 7: Process suggested follow-up specs

After the run resolves and a report exists, check the report for a `## Suggested Follow-up Specs` section. This applies after **every** run completion or unblock — not only for `done` specs (a blocked run can still surface valid follow-ups).

After processing that section, the coordinator executes the managed canonical
processor exactly once: `python3 .nightshift/followup_processor.py --root
.nightshift --specs-dir .nightshift/specs --source-spec <SPEC-ID> --run-id
<RUN-ID> --terminal-context <done|noop|partial|blocked|unblock|verifier_warning|material_scope|integration_failure|post_release>
--evidence-ref <project-relative-report>`. A suggestion also passes controlled
classification and source-aware child arguments. The processor runs the
source-aware conflict check, preserves distinct conflict/NFR/tool outcomes, and
seals `created` only after its child exists with the exact backlink. No
suggestion records the required zero observation. A report alone is not evidence.

For each suggestion entry, run the conflict check:

```bash
python3 .nightshift/check_followup_spec.py \
    --suggestion-title "<suggestion title>" \
    --specs-dir .nightshift/specs \
    [--artifact "<output_artifact path>"] \
    [--domain "<domain>"] [--layer <0-3>]
```

Act on the JSON result:

- **Exit 0 (`status: clean`)** — create the spec immediately in `.nightshift/specs/` using the `proposed_id` from the JSON and the `SPEC-GUIDE.md` format. Do **not** ask for confirmation. Commit the new spec file.
- **Exit 1 (`status: conflict`)** — do **not** create the spec. Record the conflict detail under the suggestion entry in the run report.
- **Exit 1 AND `nfr_texts` non-empty** — read each NFR text returned by the script and judge semantically whether the suggestion violates any NFR constraint. No violation → treat as clean and create the spec. Violation found → do not create; record the NFR constraint that blocks it.
- **Script missing** (`.nightshift/check_followup_spec.py` not found) — record the suggestion as pending in the report; skip creation.

Keep this policy here only — `board.py`'s run prompt points at this skill rather than duplicating it, so the two cannot drift.

---

## Important Implementation Notes

### Canonical kit — NEVER generate protocol files

The protocol files (LOOP.md, BOOTSTRAP.md, REVIEW.md, ORCHESTRATOR.md, etc.) are complex, battle-tested documents totaling ~4800 lines. They evolved through 9+ development phases and multiple production runs. **Never generate them from descriptions or summaries.** Always copy from `$HOME/Dropbox/Developer/ManagedProjects/Nightshift/canonical/`.

Only `config.yaml` values and project-specific files (hooks, prompts) are generated. Everything else is copied verbatim.

### Template files

`references/templates.md` contains the config.yaml template format, spec template, static analysis detection table, and pre-commit hook template. Use it for generating project-specific customizations — NOT for protocol files.

### Spec ID assignment

**Always use `check_followup_spec.py` to get a proposed ID — never compute one by scanning and incrementing manually.** Manual increment cannot detect: (a) IDs already in use under a different prefix, (b) follow-up streams from multiple parents colliding on the same global counter.

```bash
python3 .nightshift/check_followup_spec.py \
  --suggestion-title "Short title" \
  --specs-dir .nightshift/specs/ \
  [--parent-id PARENT-SPEC-ID]  # Required when the spec has a parent: field
```

Use the `proposed_id` from the JSON output. For baseline specs prefix the title with "Baseline —"; for gap specs prefix with "Gap —" — the inferred prefix will match existing project conventions automatically.

User can always override the proposed ID, but they must verify it doesn't already exist.

### Config detection heuristics

When detecting project commands, check these locations:
- `package.json` → `scripts` section
- `Makefile` / `Justfile` → targets
- `pyproject.toml` → `[tool.*]` sections, `[project.scripts]`
- `Cargo.toml` → cargo commands
- `Package.swift` → swift build/test

When in doubt, ask the user rather than guessing.

### Validation strictness

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

Scans all draft and blocked specs for embedded open questions, consolidates them into a single persistent **QUESTIONS spec**, and provides a structured discussion flow so questions are resolved one by one. All decisions are recorded in the QUESTIONS spec and applied back to the source specs with full traceability.

This command exists because specs written by subagents routinely contain deferred decisions ("open question — unresolved at draft time", "BLOCKED until…") that are easy to miss when reviewing individually. The QUESTIONS spec is the single source of truth for what is open, what was decided, and what changed as a result.

---

### The QUESTIONS spec

Every run of this command creates or updates a QUESTIONS spec in `specs/`. It is a permanent artifact — not a report. Format:

```markdown
---
id: {PROJECT}-QUESTIONS-NNN
type: questions
status: draft       # draft (questions open) | in_progress (mix) | done (all resolved)
created: YYYY-MM-DD
wave: <label describing what wave of specs these came from>
sources: [SPEC-ID-1, SPEC-ID-2, ...]
---

# Open Questions — <wave label>

## Q1 — <short title>

**Source:** [SPEC-ID § section name](spec://SPEC-ID)
**Severity:** blocker | advisory
**Status:** OPEN | RESOLVED YYYY-MM-DD | BLOCKED — waiting on <person>

**Question:** <exact question text, copied verbatim from the source spec>

**Options (from source spec):**
- A: ...
- B: ...

**Decision:** <recorded after discussion>

**Changes applied:**
- [SPEC-ID § section name](spec://SPEC-ID) — <what changed>
- [SPEC-ID § AC number](spec://SPEC-ID) — <what changed>

**New spec created:** [NEW-SPEC-ID](spec://NEW-SPEC-ID) (if applicable)

---

## Q2 — ...
```

**Key rules for the QUESTIONS spec:**
- Questions are **never deleted** from the QUESTIONS spec, even after resolution. They stay as a permanent record.
- Each question's **source text is copied verbatim** from the source spec — so the QUESTIONS spec is self-contained and readable without opening the source spec.
- When a question is resolved, the entry is updated in-place: Decision + Changes applied fields are filled in.
- If a question spawns a new spec, the new spec's ID is recorded under "New spec created".

---

### Step 1: Check for existing QUESTIONS spec

Before scanning, look for any existing `{PROJECT}-QUESTIONS-NNN.md` in `specs/`. If one exists:
- Load it and extract the list of already-resolved or blocked questions (by source spec + section)
- These will be **skipped** in the scan — do not surface questions that are already recorded in a QUESTIONS spec
- If an existing QUESTIONS spec has open (unresolved) questions, surface those first before scanning for new ones
- If no QUESTIONS spec exists, create a new one with the next available NNN

This is the mechanism that prevents the same questions from being asked twice.

---

### Step 2: Scan for new open questions

Read every spec whose `status` is `draft` or `blocked`. Skip specs whose questions are already recorded in the QUESTIONS spec. Scan for:

**Explicit markers:**
- "open question", "unresolved", "to be decided", "blocked on", "must be resolved before"
- "MISSING", "FIXME", "TODO" in Requirements or Context sections
- A requirement or AC containing "TBD" or "?"
- A `Gap Protocol` section with unanswered "Stop-immediately" gaps
- A `BLOCKED:` note added by a previous `address-issues` run

**Implicit signals:**
- A requirement referencing a component or method that provably does not exist
- An `after:` dependency pointing to a spec that is itself `draft` or `blocked`

For each question found:
- Copy the verbatim question text from the source spec
- Record source spec ID + section
- Classify severity: `blocker` (spec cannot be implemented without an answer) or `advisory`
- Deduplicate across specs: if two specs share the same question, merge into one entry listing both sources

---

### Step 3: Write / update the QUESTIONS spec

Append all newly found questions to the QUESTIONS spec (or create it if it doesn't exist yet). Set their status to `OPEN`.

**Stop here.** Do not ask questions yet. Write the QUESTIONS spec file first so the user has a single document to review. Print a brief summary:

```
Found N open questions across M specs.
Written to: specs/{PROJECT}-QUESTIONS-NNN.md

Blockers (K): Q1, Q3, Q7, ...
Advisory (J): Q2, Q4, Q5, ...

Previously resolved (skipped): Q-from-last-run-1, Q-from-last-run-2, ...

Ready to discuss? Start with blockers, or pick a question.
```

---

### Step 4: Discuss — one question at a time

#### Evidence-brief phase for material REVIEW cases

Before discussing a question, the `address-issues` coordinator decides whether it is a
**material REVIEW case**: an explicit open question or intrinsic-readiness `REVIEW`
whose answer could change requirements, ACs, architecture, execution authority, safety,
or meaningful cost. Dependency waiting, intentionally `planned` work, deterministic text
repair, and advisory/non-implementation questions stay on the lightweight flow below.
This is an `address-issues` phase, not a command, ledger, store, or autonomy model.

The coordinator is the sole owner of source-spec and QUESTIONS writes. It may dispatch
bounded, read-only evidence workers for independent questions (in parallel only within
the configured NFR-001 limit), then reconciles their findings and writes decisions
serially. Workers and the later run agent never mutate lifecycle state or source specs.
After each serial resolution, refresh any later brief whose assumptions, options, or
evidence were affected.

For every material case, add an immutable `## Decision Brief` section to its existing
QUESTIONS entry before an authority decision. The section must contain these labelled,
non-empty fields:

- `Question`, `Measured facts`, `Reproduction`, `Evidence`, `Options`, and `Consequences`
- `Recommendation`, `Assumptions`, `Neighbouring questions`, `Evidence timestamp`, and `Proposed authority`

`Reproduction` includes a command/query; `Evidence` links reproducible output or an
artifact. Options include those newly found by measurement, with cost, risk, and
reversibility. Keep rejected options and prior evidence in the QUESTIONS history.
Run `validate_specs.py` for the deterministic schema/reference/timestamp gate, then use
a distinct reviewer role to judge evidence relevance and sufficiency, option completeness,
and whether the recommendation follows. The reviewer cannot review its own brief or
mutate the source spec. A static failure, reviewer `REVIEW`, conflicting evidence, or a
policy exception remains `REVIEW`; it is not a confident recommendation or `blocked` by
default.

Route only through the existing autonomy rung: the coordinator can resolve a reversible,
in-scope full-auto choice after both gates pass; `authorize` pauses for authorization;
`interrupt`, irreversible, and outward-facing choices use the existing human path.
No brief widens authority. On resolution, record reviewer result, authority, decision,
rationale, and source backlinks in QUESTIONS; update the source spec's decided R/AC or
constraint with a backlink. Rerun intrinsic readiness validation: only a qualifying
`draft` becomes `ready`; retain exact `REVIEW` findings otherwise.

Whenever that intrinsic review examines R/ACs, record a `contract_review` on the
existing lifecycle-classification event. Include clean reviews so the denominator is
complete. Flag each revised R/AC once with every applicable controlled reason from
`SPEC-GUIDE.md`; write only counts, canonical IDs, kinds, and reason codes. The
coordinator performs the single serial event write after reconciling read-only findings.

Finally emit a compact run-agent decision packet containing only final decision, changed
R/ACs, implementation constraints, critical evidence, and invalidating assumptions.
Measure its size and keep it within the configured context budget; omit broad discovery
transcripts and rejected options unless requested. Record material questions, briefs,
static failures, reviewer revisions, option changes, authority/rung decisions,
escalations, time-to-decision, avoided repeats, readiness result, reversals, discovery
context size, and packet size. For rates, retain numerator and denominator; report `N/A`
instead of zero when there are no samples.

The user drives this phase. They may say "go through all blockers" or "let's talk about Q3." For each question being discussed:

- Read the question entry from the QUESTIONS spec
- Present it with full context (source spec + section, options if any)
- Use `AskUserQuestion` (max 4 per call) for questions with discrete options
- For free-form answers (e.g. "supply the 14 quotes"), accept typed input directly
- After each answer, move immediately to Step 5 for that question before continuing to the next

---

### Step 5: Apply one resolved question

When a question gets an answer:

**a. Update the QUESTIONS spec entry:**
- Set `Status: RESOLVED YYYY-MM-DD` (or `BLOCKED — waiting on <person>` if deferred)
- Fill in `Decision:` with the answer
- Fill in `Changes applied:` with every spec + section that was modified

**b. Apply to the source spec — only if the spec is `draft` or `blocked`:**
- If `status: draft` or `blocked`: edit the spec to reflect the decision. Remove the open-question text and replace with the decided approach + `(decided YYYY-MM-DD)`. Update Requirements, ACs, Navigation sections as needed. Update `status` if the blocker is now cleared.
- If `status: done`: **do not touch the source spec**. The answer lives only in the QUESTIONS spec. Add a note in the QUESTIONS entry: `Source spec is done — answer recorded here only.`

**c. Create follow-up specs if needed:**
- If the decision is "do this as a separate spec", create it with `parent:` pointing to the originating spec and `after:` pointing to it
- Record the new spec ID in the QUESTIONS entry under `New spec created:`
- The new spec must also have a reference back: add a line in its Context section: `This spec was created to resolve Q{N} in {PROJECT}-QUESTIONS-NNN.md`

**d. Update LOOP reports that referenced the question (optional, best-effort):**
- If a LOOP run report in `reports/` mentioned this spec's open question, add a reference line to that report pointing to the QUESTIONS spec. This is best-effort — don't block on it.

---

### Step 6: Final summary

After all discussed questions are resolved (or deferred), print the full traceability report:

```
QUESTIONS spec: specs/{PROJECT}-QUESTIONS-NNN.md

RESOLVED (N):
  ✓ Q1 — SCR-002/003: Onboarding routing → Option A (OnboardingHostView)
      Source: specs/FART-SCR-002-wel-1.md § Navigation in/out
      Changes: FART-SCR-002 § Navigation in/out, FART-SCR-003 § Navigation in/out

  ✓ Q3 — SCR-010: Payout estimate → removed entirely
      Source: specs/FART-SCR-010-hitcel.md § Requirements
      Changes: FART-SCR-010 § Requirements (req removed), § AC-5, § AC-6

  ✓ Q5 — SCR-017: per-slot charts → follow-up spec
      Source: specs/FART-SCR-017-stats.md § Out of Scope
      New spec: specs/FART-SCR-017b-stats-distributions.md

BLOCKED / DEFERRED (M):
  ✗ Q2 — SCR-001: badge icon (golden clover asset needed)
      Source: specs/FART-SCR-001-disc.md § Visual note on the badge icon
      Waiting on: Łukasz to supply asset

  ✗ Q4 — SCR-016: 14 pull-quotes missing
      Source: specs/FART-SCR-016-about.md § Quote inventory status
      Waiting on: Łukasz to supply quotes

STILL OPEN (P):
  ○ Q6, Q8 — not discussed this session

Specs now promotable to ready: SCR-002, SCR-003, SCR-005, SCR-010, SCR-015
```

---

### How LOOP reports connect to this

When the Nightshift LOOP runs a spec and encounters an open question it cannot resolve, it should:
1. Record the question in its run report under a `## Open Questions` section
2. Note: `See {PROJECT}-QUESTIONS-NNN.md for the consolidated questions tracker`

If no QUESTIONS spec exists yet when the report is written, the LOOP notes the question in the report and the next `address-issues` run will pick it up and create the QUESTIONS spec.

**Report-level scan vs. this command's spec-level scan (SPEC-299).** This
command's Step 2 scan is scoped to `draft`/`blocked` *specs* — it is
complementary to, not a replacement for, the report-level half of the flow.
Every report the LOOP writes must carry its own `## Report Action Log`
section (LOOP.md Step 14): a closed-vocabulary record of what happened to
that report's own `## Open Questions`/`## Blocked Specs` content
(`none_found` | `consolidated_into <QUESTIONS-spec-id>` | `resolved_in_report`
| `deferred: <reason>`). The board's **COPY PROMPT** button (`board.py`'s
`copyQuestionsPrompt()`) is the operator-facing entrypoint for that
report-level scan: it walks unread reports, extracts `## Open Questions`/
`## Blocked Specs`, and instructs the reader to append one `## Report Action
Log` row per scanned report — including a `none_found` row, never a silent
skip — to the consolidated QUESTIONS spec, so a later reader can answer "was
this report addressed?" from the QUESTIONS spec (or the report itself)
without re-opening every report.

---

### Guidelines

**Never re-ask resolved questions.** The QUESTIONS spec is the guard. Check it at the start of every run.

**Questions in done specs stay in QUESTIONS spec only.** If a source spec is `done`, editing it to record the decision is noise — nobody reads past decisions in done specs. The QUESTIONS spec is where decisions live permanently.

**One question per discussion turn.** Don't batch 8 decisions in one AskUserQuestion call if the user wants to discuss each carefully. The AskUserQuestion 4-at-a-time limit is a ceiling, not a target.

**Commit after every apply pass.** Suggested message: `chore: address-issues — resolve QN-QM in {PROJECT}-QUESTIONS-NNN.md`
