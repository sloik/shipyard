# Bootstrap Entry Point

**Purpose:** The first file any agent reads when starting a nightshift run. This document guides you through interactive discovery of your project's stack, auto-detection of build/test commands, configuration of the nightshift system, tooling audit, and entry into the LOOP.

**Overview:** Bootstrap has five phases:
1. **Auto-Discovery** — scan project for stack indicators and existing tools
2. **Interactive Configuration** — present findings, ask human to confirm/correct
3. **Write Config** — generate `config.yaml` based on conversation
4. **Tooling Audit** — verify static tools exist, create SPEC-000-tooling if needed
5. **Knowledge & Entry** — read project docs, check specs queue, enter LOOP

---

## Phase A: Auto-Discovery (Silent Agent Work)

**What to do:** Scan the project root to understand its stack and existing configuration. Present your findings to the human in Phase B.

### Re-entry Check

Before scanning the project:

1. **Check if both of these exist:**
   - `.nightshift/config.yaml` — already written in a previous run
   - `.git/` directory — git repository already initialized

2. **If BOTH exist:**
   - This is a re-entry after a session restart (you were here before)
   - Print: "Bootstrap re-entry detected. Skipping Phases A-C (already complete)."
   - Jump directly to **Phase D** (tooling audit)
   - Phase D should re-audit tools (swiftlint config may have been created in the first run, or other tools updated)

3. **If only `config.yaml` exists but no `.git/`:**
   - Something went wrong; proceed with Phase A normally (git init will create the repo)

4. **If neither exists:**
   - Fresh bootstrap; proceed with Phase A normally

### Workspace Directory Setup

Ensure the Nightshift workspace directories exist before proceeding:

```bash
mkdir -p .nightshift/knowledge/patterns
mkdir -p .nightshift/metrics
mkdir -p .nightshift/specs
mkdir -p .nightshift/reports
```

These directories are required by the loop protocol:
- `knowledge/patterns/` — success patterns written by agents (LOOP Step 12)
- `metrics/` — per-spec metrics YAML files (LOOP Step 13)
- `specs/` — spec files for task selection (LOOP Step 2)
- `reports/` — nightshift reports and discovered TODOs (LOOP Step 14)

Using `mkdir -p` is safe for re-entry — it won't fail if directories already exist.

### Stack Indicators to Check

Scan the project root and subdirectories for these files:

| Stack | Indicator File | Alternate Indicators |
|-------|----------------|----------------------|
| **Swift/iOS/macOS** | `Package.swift` | `*.xcodeproj`, `*.xcworkspace` |
| **Rust** | `Cargo.toml` | `Cargo.lock` |
| **Node/TypeScript/JavaScript** | `package.json` | `npm-shrinkwrap.json`, `pnpm-lock.yaml`, `yarn.lock` |
| **Python** | `pyproject.toml`, `setup.py`, `requirements.txt` | `Pipfile`, `Pipfile.lock`, `Poetry.lock` |
| **Go** | `go.mod` | `go.sum` |
| **Java/Kotlin/Android** | `build.gradle`, `build.gradle.kts` | `pom.xml`, `settings.gradle` |
| **C/C++** | `CMakeLists.txt` | `Makefile`, `*.sln` |
| **Other** | `Dockerfile`, `Makefile` | Look for language-specific patterns in file extensions |

### Existing Configuration to Check

For each detected language, look for these configuration files:

| Language | Configuration Files to Check |
|----------|------------------------------|
| **TypeScript/JS** | `tsconfig.json`, `eslint.config.*`, `.eslintrc.*`, `.prettierrc*`, `prettier.config.*` |
| **Python** | `pyproject.toml` (for `[tool.ruff]`, `[tool.mypy]`), `mypy.ini`, `pyrightconfig.json`, `setup.cfg` |
| **Swift** | `.swiftlint.yml`, `Package.swift` (build settings) |
| **Rust** | `Cargo.toml`, `clippy.toml`, `rustfmt.toml` |
| **Go** | `.golangci.yml`, `go.mod` |
| **Kotlin/Java** | `build.gradle`, `build.gradle.kts`, `lint.xml` |

### Project Documentation to Skim

Read these files if they exist — they reveal project conventions and patterns:

- `README.md` — project purpose, setup instructions, build steps
- `CONTRIBUTING.md` — contributor guidelines, code style, testing expectations
- `docs/` folder (if present) — architecture, patterns, known gotchas
- `.git/config` or run `git branch -a` — to detect main branch name (`main`, `develop`, `master`)
- Examine the most recent commits to detect commit message style (conventional, semantic, simple)

### Document Your Findings

Prepare to present to the human:
- **Which stack(s) did you detect?** (e.g., "TypeScript + Python")
- **Evidence** for each (e.g., "`package.json` found; `pyproject.toml` found")
- **What build/test tooling exists?** (scripts in package.json, pytest in requirements, etc.)
- **What static analysis is configured?** (ESLint, Ruff, SwiftLint, etc.)
- **Project conventions** based on README/CONTRIBUTING/code patterns
- **Main branch name** and **commit message style** from git

### Git Init Restart Gate

**MANDATORY CHECK after git operations in Phase A:**

Did you run `git init` during this Phase A session? (Check: was there a `.git/` directory BEFORE you started Phase A?)

- If `.git/` **already existed** before Phase A → continue to Phase B
- If you **created** `.git/` via `git init` during Phase A → **YOU MUST STOP NOW**

#### ⚠️ STOP — SESSION RESTART REQUIRED ⚠️

**DO NOT CONTINUE TO PHASE B. DO NOT PROCEED. STOP HERE.**

The harness session was started before this git repository existed. Worktree isolation
(required for orchestrator mode) WILL NOT WORK because the harness caches git state at
startup. Continuing will cause all sub-agents to fail worktree creation.

**Tell the human:**
```
BOOTSTRAP PAUSED — Session restart required.

I created a new git repository (git init) during this bootstrap.
Worktree isolation won't work until you restart the session.

Please:
1. Exit this session (Ctrl+C or /exit)
2. Re-run: claude --dangerously-skip-permissions ".nightshift/BOOTSTRAP.md"
3. I'll detect the existing config and skip to Phase D automatically.
```

**Then stop. Do not execute any further steps. Wait for the session to end.**

**⚠️ STOP — do not continue to Phase B.**

The bootstrap will auto-detect the re-entry on the second run and resume from Phase D.

---

## Phase B: Interactive Configuration

**What to do:** Present your auto-discovery findings to the human in a structured conversation. Ask for confirmation, correction, or additional context for each major decision.

### B1: Greet and Introduce Discovery Results

Present something like:

> I've scanned the project. Here's what I found:
>
> **Detected Stack:** TypeScript (package.json), Python (pyproject.toml)
> **Build indicators:** npm scripts in package.json, Makefile present
> **Static tools:** ESLint configured, TypeScript compiler available, Ruff configured
> **Main branch:** main (from git config)
>
> Let me ask a few questions to confirm this is all correct and get the details needed for config.yaml.

### B2: Project Basics

Ask the human to confirm or correct:

> **I detected TypeScript and Python as your main languages based on package.json and pyproject.toml. Is that right?**
>
> If not, what are the actual primary languages? (List all languages the agent will write code in.)

Then:

> **What's the project name?** (short, no spaces — used in config.yaml; e.g., "my-app", "tram-tracker")
>
> **One-line description:** What does this project do?

### B3: Build & Test Commands

For each detected language, ask:

> **For [TypeScript/Python/etc.], I found [build indicator]. What are the exact commands?**
>
> - **Build command:** What command compiles/builds your project? (e.g., `npm run build`, `swift build`, `cargo build`)
> - **Test command:** What command runs your full test suite? (e.g., `npm test`, `pytest`, `cargo test`)
> - **Lint command:** What command runs static analysis? Must exit 0 on success, non-zero on failure. Fail on warnings.
> - **Type check:** (if applicable) What command type-checks? (e.g., `tsc --noEmit`, `mypy .`, `pyright`)
> - **Format check:** (optional) Does your project check code formatting? Command?
> - **Format fix:** (optional) Command to auto-fix formatting?

**Important:** Test each command they give you locally to confirm it works. If it fails, ask them to debug or provide the correct command.

### B4: Project Conventions

Ask:

> **What are the key coding conventions or patterns your project follows?**
>
> Examples:
> - "All network calls go through src/api/client.ts"
> - "Tests live next to source files as *.test.ts"
> - "Use async/await, never callbacks"
> - "All database queries must use parameterized statements"
> - "ViewModels use @Observable @MainActor pattern"
>
> Please list 3-5 conventions that an autonomous agent should know about.

### B5: Review Configuration

Ask:

> **Which review personas matter most for this project?**
>
> We have 6 available: `architect`, `security`, `performance`, `domain`, `quality`, `user`.
>
> All are enabled by default. Should I remove any? (E.g., if there's no UI, remove `user`. If there's no network code, maybe skip `security`.)
>
> **Any extra project-specific review criteria?** (Beyond the 6 personas.)
> Examples:
> - "All public functions must have doc comments"
> - "No debug/print statements in production code"

### B6: Git Configuration

Ask:

> **Git configuration:**
> - **Main branch:** I detected `[branch]`. Is it `main`, `develop`, or `master`?
> - **Commit style:** Does this project use conventional commits (feat/fix/test/docs) or simple messages?
> - **Merge strategy:** Do you prefer `no-ff` (always merge commit), `squash`, or `rebase`?

### B7: Circuit Breaker (Optional Tuning)

Ask:

> **Stall detection thresholds:** The defaults work for most projects. Do you want to adjust them?
>
> - **Max consecutive identical errors:** (default 3) — If the build fails the same way 3 times in a row, assume it's stuck
> - **Max review cycles:** (default 5) — If reviewers request changes 5 times for one spec, assume the spec is too ambiguous
> - **Max spec duration:** (default 120 minutes) — Hard ceiling. Useful if your project builds slowly. Increase for slow languages (Swift, Rust, Kotlin).
> - **Phase duration multiplier:** (default 3) — Assume stall if any phase takes 3x longer than average
>
> (If they don't have opinions, use defaults.)

### B8: DevKB — External Knowledge Base (Optional)

Ask:

> **DevKB (Development Knowledge Base):** Do you have a cross-project knowledge base with lessons per technology?
>
> If yes:
> - **Path:** What's the absolute path to the DevKB directory? (e.g., `/Users/ed/Dropbox/Argo/DevKB`)
> - **Writeback:** Should agents stage new cross-project discoveries back to DevKB? (default: yes)
> - **Always-include files:** Any DevKB files to always load regardless of language? (e.g., `git.md`, `architecture.md`)
>
> I'll auto-map your project languages to DevKB files based on naming convention (`<language>.md`).
> You can override the mappings in config.yaml after bootstrap.
>
> If no DevKB → leave blank, skip this section.

**Auto-mapping logic (for Phase C):**
For each language in `project.language`, check if `<devkb.path>/<language>.md` exists.
If it does, add it to `devkb.mappings.<language>`. For Swift projects, also check for `xcode.md` and `macos.md`.

### B9: Watcher (Optional)

Ask:

> **Parallel review agent:** Would you like to enable the watcher? (Separate agent runs alongside, reviews your code independently.)
>
> Default: disabled. Leave off for first runs. Once the main loop is stable, enable watcher for extra review coverage.

---

## Phase C: Write Configuration

**What to do:** Write `.nightshift/config.yaml` with all values confirmed in Phase B.

**Template sections to fill:**

```yaml
# project
project:
  name: <name from B2>
  description: <description from B2>
  language: <list from B2>

# commands
commands:
  build: <from B3>
  test: <from B3>
  lint: <from B3>
  type_check: <from B3, or "" if not applicable>
  format: <from B3, or "" if not applicable>
  format_fix: <from B3, or "" if not applicable>

# conventions
conventions:
  <from B4 — each as a bullet>

# review
review:
  enabled: <from B5 — list of personas, minus any removed>
  extra_criteria: <from B5 — list or empty>

# git
git:
  main_branch: <from B6>
  branch_prefix: "nightshift"
  commit_style: <from B6>
  worktrees: "auto"
  merge_strategy: <from B6>

# circuit_breaker
circuit_breaker:
  max_same_error: <from B7, default 3>
  max_review_cycles: <from B7, default 5>
  max_spec_duration_min: <from B7, default 120>
  phase_duration_multiplier: <from B7, default 3>

# metrics
metrics:
  enabled: true
  track: [duration, test_results, review_cycles, build_errors, files_changed]

# watcher
watcher:
  enabled: <from B8, default false>
  poll_interval_min: 5
  idle_timeout_min: 30
  review_file: "WATCHER-REVIEW.md"
  lens: "general"
```

### Config Key Naming (IMPORTANT)

The LOOP.md protocol references commands using the `commands.*` namespace exclusively:
- `commands.build` — build/compile command
- `commands.test` — test suite command
- `commands.lint` — linter command
- `commands.type_check` — type checker command
- `commands.format` — formatter command
- `commands.test_timeout_s` — test timeout in seconds

**You MUST use these exact key paths in config.yaml.** Alternative structures
(e.g., `build.test_command`, `testing.command`) will NOT be recognized by the
loop protocol. The Null Command Policy, timeout wrapping, and metrics logging
all reference `commands.*` keys by name.

After writing, commit:

```
git add .nightshift/config.yaml
git commit -m "config: initial nightshift setup for $(date +%Y-%m-%d)"
```

---

## Phase D: Static Analysis & Test Framework Audit

**Critical:** Static tools and test frameworks are the cheapest quality gates. Ensure they exist before any feature work.

### D1: Static Analysis Tools

For each language in `config.yaml` → `project.language`, verify static tools are configured:

| Language | Required Tools | Config File | Verify Command |
|----------|---|---|---|
| **TypeScript/JS** | ESLint, Prettier, TypeScript | `eslint.config.*`, `.eslintrc.*`, `.prettierrc*`, `tsconfig.json` | `npx eslint --version`, `npx prettier --version`, `npx tsc --version` |
| **Python** | ruff (lint+format), mypy or pyright | `pyproject.toml [tool.ruff]`, `mypy.ini` or `pyrightconfig.json` | `ruff --version`, `mypy --version` |
| **Swift** | SwiftLint, swift build | `.swiftlint.yml`, `Package.swift` | `swiftlint --version`, `swift build --help` |
| **Rust** | clippy, rustfmt | `clippy.toml`, `rustfmt.toml` | `cargo clippy --help`, `rustfmt --version` |
| **Go** | golangci-lint | `.golangci.yml` | `golangci-lint --version` |
| **Java/Kotlin** | gradle lint plugin | `build.gradle` or `build.gradle.kts` | `./gradlew lint --help` |

### D2: Test Framework Audit

**Equally critical.** A project without tests cannot safely evolve. Check if `config.yaml` → `commands.test` is null or missing. If so, propose a test framework:

| Language / Project Type | Recommended Framework | Verify Command | Config File |
|---|---|---|---|
| **HTML/CSS/JS (static)** | Playwright | `npx playwright --version` | `playwright.config.js` |
| **TypeScript/JS (Node)** | vitest or jest | `npx vitest --version` | `vitest.config.ts` |
| **Python** | pytest | `python -m pytest --version` | `pyproject.toml [tool.pytest]` |
| **Swift** | XCTest | `swift test --help` | `Package.swift` (test targets) |
| **Rust** | cargo test | `cargo test --help` | `Cargo.toml` (test targets) |
| **Go** | go test | `go test --help` | `*_test.go` files |

**If test framework is missing:**
1. Check if the framework binary is available (run verify command)
2. If available: create SPEC-000-testing (Layer 0, priority 0) to set up test infrastructure
3. If not available: note in bootstrap report, suggest installation, create SPEC-000-testing anyway
4. Update `config.yaml` → `commands.test` with the recommended command AFTER the spec completes

**Why this matters:** The LOOP's TDD cycle (Steps 4-5) is disabled when `commands.test` is null. Without a test framework, every spec ships untested code. Test infrastructure is as foundational as linting — it should be audited here, not discovered later.

### Procedure

1. For each language in `config.yaml`:
   - Check: do the config files exist?
   - Run the verify command: does the tool work?
2. Record findings below in the bootstrap report (Phase E)

### If Tools Are Missing

If a language is configured but static tools are absent:

1. **Create a SPEC-000-tooling spec** (Layer 0, priority 1):

```markdown
# specs/SPEC-000-tooling.md

---
id: SPEC-000-tooling
priority: 1
layer: 0
type: refactor
status: ready
created: 2026-03-16
---

# Set Up Static Analysis Tools

## Problem

Static analysis tools are missing or not configured. The loop requires these before feature work.

## Requirements

- [ ] Install and configure all required static analysis tools for [language list]
- [ ] Lint command: runs without errors on clean baseline
- [ ] Type check command: runs without errors on clean baseline (if applicable)
- [ ] Format check command: passes on clean baseline (if applicable)

## Acceptance Criteria

- [ ] All commands from `config.yaml` succeed locally
- [ ] Tooling is strict enough to catch real issues (not overly lenient)
- [ ] Agent can run `lint`, `type_check`, `format` between every code change

## Context

For autonomous agents, static tools are the cheapest quality gate. Every lint error caught by a tool is one fewer review cycle burned. The loop expects these to be maximal-strictness (unlike human development, where linters can be annoying).

Strict tools save tokens.
```

2. This spec must run first (Layer 0, priority 1). The static safety net must exist before feature work.
3. Save to `specs/SPEC-000-tooling.md`
4. Continue to Phase E

### If Tools Exist but Are Lenient

If tools are configured but with lenient settings (e.g., many ESLint rules disabled, low mypy strictness):

1. **Note this in the bootstrap report** (Phase E)
2. **Optionally create a SPEC-001-tighten-tools** to strengthen rules (lower priority than SPEC-000-tooling)
3. Proceed with current tools — working lenient tools are better than no tools

### Strictness Philosophy

For autonomous agents, **maximum strictness is better than for humans.**

- Humans find strict linters annoying (they interrupt flow)
- Agents don't have flow — they have loops
- Every lint error caught by a static tool is one fewer LLM review cycle

Configure tools as strictly as the project can tolerate. It saves tokens.

### Install Pre-Commit Hook

After the tooling audit, install the Nightshift pre-commit hook to prevent commits that fail lint or type-check:

```bash
cp .nightshift/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

This hook reads `lint` and `type_check` commands from `config.yaml` and runs them before every `git commit`. If either fails, the commit is rejected.

**Why:** This is agent-agnostic — it works regardless of which agent/harness runs the loop. The agent runs `git commit` → git runs the hook → commit is rejected if lint fails. This catches the case where the agent skips step 9 (Full Validation) and tries to commit directly.

---

## Phase E: Write Bootstrap Report

**What to do:** Summarize your findings and tooling audit in a structured report.

**Save to:** `reports/YYYY-MM-DD-bootstrap-report.md` (use today's date)

**Template:**

```markdown
# Bootstrap Report

**Date:** YYYY-MM-DD
**Project:** <name>
**Language(s):** <comma-separated>
**Bootstrap phase:** Complete

## Configuration Summary

- **Project name:** <name>
- **Languages:** <list>
- **Build command:** <command>
- **Test command:** <command>
- **Lint command:** <command>
- **Main branch:** <branch>
- **Commit style:** <style>

## Tooling Audit

### Configured & Passing ✅

List static tools that exist and work:
- ESLint: configured, passes
- Prettier: configured, passes
- TypeScript: configured, passes

### Missing Tools ⚠️

If any, list here. (If none, write "None.")

### Lenient Tools ⚠️

If any tools are configured but lenient, note them. (If none, write "None.")

## Specs in Queue

- **Ready:** N spec(s)
- **Draft:** M spec(s)
- **Total:** N+M spec(s)

First spec to start: SPEC-XXX

## Conventions

List 3-5 key conventions from config.yaml that the agent will follow.

## Next Steps

1. All tools are in place ✅
2. Proceed to LOOP.md step 1: pre-flight check
3. First spec: SPEC-XXX

---

Generated during bootstrap on YYYY-MM-DD.
```

After writing, commit:

```
git add reports/YYYY-MM-DD-bootstrap-report.md
git commit -m "docs: bootstrap report for $(date +%Y-%m-%d) run"
```

---

## Phase E: Knowledge & Loop Entry

**What to do:** Read project documentation, survey the specs queue, then enter the main loop.

### E1: Read Knowledge Files

List all files in `knowledge/`:

```bash
ls -la .nightshift/knowledge/
```

For each file present (excluding `.gitkeep`), read it:
- General project docs (style, patterns, architecture)
- Domain-specific knowledge relevant to the first spec you'll work on
- Known gotchas, performance constraints, security concerns

These files are the project's accumulated wisdom. They prevent you from rediscovering lessons.

*Note:* The `knowledge/` directory may be empty if this is the first bootstrap. That's fine — you'll populate it over time as you discover patterns.

### E1a: Load DevKB (External Development Knowledge Base)

**What to do:** Load cross-project development lessons from DevKB if configured.

1. **Check configuration:**
   - Read `config.yaml` → `devkb.path`
   - If empty or missing → skip this step (DevKB not configured)
   - If set → verify the directory exists: `ls -la <devkb.path>`

2. **Resolve files to load:**
   - For each language in `config.yaml` → `project.language`:
     - Look up `devkb.mappings.<language>` → list of filenames
     - For each filename, construct full path: `<devkb.path>/<filename>`
   - Also load all files listed in `devkb.always_include` (e.g., `git.md`, `architecture.md`)
   - Deduplicate (a file may appear in multiple language mappings)

3. **Read each resolved file:**
   - Read the full contents of each DevKB file
   - These contain cross-project patterns: Problem → Root Cause → Fix → Prevention
   - They are the distilled lessons from past sessions across ALL projects

4. **Log to working notes:**
   ```
   DevKB Injection Summary:
   Loaded N DevKB files from <devkb.path>:
   - swift.md (for: swift)
   - xcode.md (for: swift)
   - git.md (always_include)

   These are now in context for the LOOP.
   ```

5. **Create writeback directory** (if `devkb.writeback: true`):
   ```bash
   mkdir -p .nightshift/knowledge/devkb-updates
   ```

**Why:** DevKB prevents agents from rediscovering cross-project lessons. The 3-iteration pause rule exists because agents waste cycles on problems DevKB already solved. Loading DevKB at bootstrap means every spec in this run benefits from prior knowledge.

**If DevKB path doesn't exist:** Log a warning: `"DevKB path configured but not found: <path>. Skipping."` — do not fail bootstrap over this.

### E2: Survey Specs Queue

List all files in `specs/`:

```bash
ls -la .nightshift/specs/
```

For each spec, check:
- **Status:** Is it `ready`, `draft`, `in_progress`, `done`, or `blocked`?
- **Layer:** What layer is it in? (0=foundation, 1=infra, 2=feature, 3=polish)
- **Type:** Is it a `feature`, `bugfix`, `refactor`, or `eval`?
- **Priority:** Bugfixes always take priority over features

Note:
- How many are `ready`?
- Are there any `bugfix` type specs? (These take absolute priority.)
- What's the first spec you'll work on? (Layer 0 first, then by priority within layer.)

**Need help writing specs?** Read `.nightshift/SPEC-GUIDE.md` — it walks you (or your agent) through spec creation interactively. You can hand this guide to any LLM and it will walk you through the 9-phase process to create a complete, well-formed spec.

### E3: Check for STOP Signal

Look for `.nightshift/STOP` file:

```bash
ls -la .nightshift/STOP 2>/dev/null
```

If it exists:
- Read it — understand why the loop was stopped
- If the issue is resolved, delete the file and proceed
- If the issue persists, exit and report to a human

### E6. Check for Interrupted Work (Checkpoints)

Before entering the loop, check for any incomplete specs from previous runs:

1. **Scan for checkpoints:**
   ```bash
   ls -la .nightshift/checkpoints/*/latest.json 2>/dev/null
   ```

2. **For each checkpoint found:**
   - A previous run crashed or was interrupted mid-spec
   - Read the `latest.json` file to identify which spec and step
   - Print the checkpoint data (spec ID, step number, last saved time)

3. **Resume interrupted specs FIRST:**
   - Do not pick a new spec via Task Selection (step 2)
   - Instead, resume the interrupted spec immediately
   - Load the checkpoint using `checkpoint.load_latest_checkpoint(spec_id)`
   - Print resumption instructions using `checkpoint.get_resume_instructions(cp)`
   - Start the loop from the step AFTER the checkpoint's step number

4. **Example:**
   ```python
   import checkpoint
   from pathlib import Path

   checkpoints_dir = Path(".nightshift/checkpoints")
   if checkpoints_dir.exists():
       for spec_dir in checkpoints_dir.glob("*"):
           latest = spec_dir / "latest.json"
           if latest.exists():
               cp = checkpoint.load_latest_checkpoint(spec_dir.name)
               if cp:
                   print(f"Found interrupted spec: {cp['spec_id']}")
                   print(f"Last checkpoint: step {cp['step']} ({cp['step_name']})")
                   print(checkpoint.get_resume_instructions(cp))
                   # Resume from step (cp['step'] + 1)
   ```

**Why:** Interruptions happen (context window exhaustion, network failure, agent timeout). Checkpoints allow the loop to resume without losing progress or repeating completed work.

### E3a: Knowledge Injection

**What to do:** Make knowledge patterns discoverable for the loop.

1. **Scan the patterns directory:**
   ```bash
   ls -la .nightshift/knowledge/patterns/
   ```
   List all `.md` files (excluding `_TEMPLATE.md`)

2. **For each pattern file found:**
   - Read the file's header section
   - Extract: `Problem area:`, `Tags:` (if present), `When to Reuse:`
   - Log the findings to working notes

3. **Log to working notes:**
   ```
   Knowledge Injection Summary:
   Found N knowledge patterns in knowledge/patterns/:
   - Pattern-Name-1: [Problem area summary]
   - Pattern-Name-2: [Problem area summary]
   - ...

   These patterns are now loaded and available for LOOP step 3.
   ```

4. **Note:** The patterns are injected into the LOOP's context loading phase (step 3). During implementation, the loop will automatically match patterns by domain, tags, and relevance. No further action needed here — this sub-step simply makes the agent aware that patterns exist.

**Why:** Explicit knowledge injection at bootstrap time ensures the agent knows patterns are available. The LOOP handles the actual matching and injection.

---

### E4: Check Domain & Enter the Loop

**Check `config.yaml` → `runner.domain`:**

**If `runner.domain` is NOT `code`** (research or analysis):
- **STOP and read:** `.nightshift/LOOP-DOMAIN-MAP.md`
- This file explains how the 16-step loop adapts to non-code work (research, analysis, etc.)
- Learn the domain-specific step mappings before entering the loop
- Note which review personas apply to your domain (methodology, accuracy, completeness, bias)
- Refer back to LOOP-DOMAIN-MAP.md during implementation for step-specific guidance

**Then, check `config.yaml` → `runner.mode`:**

**If `runner.mode: orchestrator`** (or unset and multiple specs are ready):
- **Read:** `.nightshift/ORCHESTRATOR.md`
- Follow the orchestrator protocol — delegate each spec to a fresh sub-agent
- Each sub-agent reads LOOP.md and executes one spec with a clean context window
- The orchestrator stays thin: it manages the queue, not the code

**If `runner.mode: inline`** (default, or single spec):
- **Read:** `.nightshift/LOOP.md`
- Follow the 16-step cycle directly in this session
- If domain is not code: reference LOOP-DOMAIN-MAP.md for domain-specific guidance on each step

Either way, run until:
- All ready specs are completed
- You hit a stall and create a BLOCKED report
- You encounter the STOP file

---

## Configuration Checklist

Before entering the loop, verify:

- [ ] `config.yaml` exists and has all required fields filled
- [ ] All commands in `config.yaml` work locally:
  - [ ] `commands.build` succeeds (exit 0)
  - [ ] `commands.test` succeeds (exit 0)
  - [ ] `commands.lint` succeeds (exit 0)
  - [ ] `commands.type_check` succeeds, if applicable (exit 0)
- [ ] Git working tree is clean OR you've committed/stashed changes
- [ ] At least one spec exists in `specs/` with `status: ready`
- [ ] `knowledge/` directory exists (may be empty)
- [ ] `reports/` directory exists and is writable
- [ ] Static analysis tools are verified to work
- [ ] Pre-commit hook is installed (`.git/hooks/pre-commit` exists and is executable)
- [ ] Bootstrap report is written and committed

---

## Troubleshooting Bootstrap

### "I can't detect what stack this project uses"

If no standard indicators are found (no Package.swift, package.json, go.mod, etc.):

1. **Examine file extensions** — What language files are present? (*.swift, *.py, *.go, *.ts, *.rs?)
2. **Read README** — Usually states the language and build steps
3. **Check Makefile or CI config** — .github/workflows, .gitlab-ci.yml, etc. often reveal how to build
4. **Ask the human** directly — "I couldn't auto-detect your stack from standard indicators. What language does this project use? What's the build command?"

### "Build/test/lint command fails during tooling audit"

- **Verify dependencies are installed:** `npm install`, `pip install`, `cargo build` to fetch deps
- **Check command correctness:** Ask the human to run the exact command from the terminal and verify it works
- **Check paths:** Are they relative to the project root? The loop assumes project-root-relative paths.
- **Check environment:** Missing tools? Missing API keys? Missing config files that the build depends on?

### "No specs in ready state"

All specs are `draft`, `in_progress`, `done`, or `blocked`. Ask the human: "Please create a spec or mark an existing one as `status: ready` so the loop has something to work on."

### "Knowledge files are empty or missing"

The `knowledge/` directory can be empty. The loop works without it — reviews use general best practices. Over time, as you discover patterns, populate this directory with entries.

### "Git doesn't have a main branch called 'main'"

Check what your main branch is called:

```bash
git branch -a | grep -E "main|master|develop"
```

Update `config.yaml` → `git.main_branch` to match your repo. Common values: `main`, `master`, `develop`.

### "I can't determine commit style"

Ask the human: "Does this project use conventional commits (feat: ..., fix: ..., test: ...) or simple messages (Fixed bug, Added feature)?"

---

## Bootstrap Completion

Once all phases are done:

1. ✅ Config is written and committed
2. ✅ Tooling audit is complete
3. ✅ Bootstrap report is written and committed
4. ✅ Knowledge files are read (or noted as empty)
5. ✅ Specs queue is surveyed
6. ✅ No STOP file is blocking

**You are ready to enter the loop.**

Proceed to `.nightshift/LOOP.md`, **Step 1: Pre-flight Check**.

> The loop is self-contained. Once bootstrap is done, an agent can run unattended overnight.
>
> Each loop iteration will produce metrics, reports, and commits. Review them in the morning.
