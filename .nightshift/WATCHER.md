# Parallel Watcher Agent Protocol

**Purpose:** An optional second agent that runs in parallel with the main loop, providing independent review while the main loop codes. The watcher reviews commits, provides feedback, and never writes code.

---

## Overview

While the main loop agent works through specs (steps 1-16 of LOOP.md), a watcher agent runs in the background:

```
┌─────────────────────┐     ┌─────────────────────┐
│   MAIN LOOP AGENT   │     │    WATCHER AGENT     │
│                     │     │                      │
│  Picks spec         │     │  Sleeps N minutes    │
│  Writes tests       │     │  Checks git log      │
│  Implements         │     │  Reviews new commits │
│  Commits per-phase ─┼──→──┤  Writes feedback to  │
│                     │     │  WATCHER-REVIEW.md   │
│  Checks feedback  ←─┼──←──┤                      │
│  Incorporates       │     │  Sleeps again        │
│  Continues...       │     │  Repeats...          │
└─────────────────────┘     └─────────────────────┘
         │                           │
         └─── shared git repo ───────┘
```

**Why:** The main agent reviewing its own work (even through personas) has inherent blind spots. A watcher agent brings genuinely independent review: different context window, potentially different model, fresh perspective.

---

## Watcher Loop

### The Poll-Review-Feedback Cycle

1. **Sleep** — Wait N minutes (default: 5) before checking
2. **Check** — Run `git log` for new commits since last check
3. **No new commits?** → Sleep again
4. **New commits found?** → Proceed to step 5
5. **Review each commit:**
   - Read the commit diff and message
   - Find the associated spec (from commit trailer `Spec: SPEC-XXX`)
   - Review the diff against the spec's requirements and acceptance criteria
   - Check: do tests actually test what the spec requires?
   - Check: does implementation match the spec, or did the agent drift?
6. **Write feedback** to `.nightshift/WATCHER-REVIEW.md`
7. **Loop until stop condition** (see below)

### Stop Conditions

The watcher stops when:

- All specs in queue are `done` or `blocked`
- No new commits for 30 minutes (main agent may have quit or stalled)
- `.nightshift/STOP` file exists
- Timeout exceeded (optional, e.g., 8 hours for overnight run)

### Configuration

In `config.yaml`:

```yaml
watcher:
  enabled: false                   # opt-in, not default
  poll_interval_min: 5             # how often to check for new commits
  idle_timeout_min: 30             # stop if no commits for this long
  review_file: "WATCHER-REVIEW.md" # where to write feedback
  lens: "general"                  # general | code | security | ux | legal | performance
```

---

## Review Lenses

The watcher is not limited to code review. It reviews through a configurable **lens** — a focus area that determines what it looks for and what documentation it reads.

| Lens | What the watcher checks | Reads | Best for |
|------|------------------------|-------|----------|
| `code` | Correctness, logic errors, spec drift, test coverage gaps | Spec, diff, test files | General quality |
| `security` | Auth boundaries, input validation, secrets in code, injection vectors | Spec, diff, `knowledge/_review/security.md`, threat model | Sensitive features |
| `ux` | Does the UI match spec? Accessibility issues? Error states? Consistency? | Spec, diff, `knowledge/_review/ux-guidelines.md`, design docs | User-facing features |
| `legal` | Data handling compliance (GDPR, CCPA), disclaimers, T&S implications | Spec, diff, `knowledge/_review/legal-requirements.md` | Data-heavy features |
| `performance` | N+1 queries, allocations, bundle size, API call patterns | Spec, diff, `knowledge/_review/performance.md` | Infra/backend work |
| `general` | All of the above at a lighter depth (default) | Spec, diff, all available review docs | Most work |

**Choosing a lens:**

- Use `general` for most specs (default, covers everything lightly)
- Use `security` for auth, payment, data-sensitive features
- Use `ux` for user-facing UI/UX work
- Use `performance` for database queries, caching, optimization work
- Use `legal` for data handling, privacy features
- Run multiple watchers with different lenses for critical overnight runs

---

## WATCHER-REVIEW.md Format

The watcher writes feedback in a structured file. The main loop reads this file and incorporates feedback.

### File Structure

```markdown
# Watcher Review

Date: 2026-03-17 (when the watcher started)
Lens: general
Total commits reviewed: 3

---

## SPEC-001 — commit abc123f (test phase)

**Reviewed:** 2026-03-17T22:15:00Z
**Status:** ⚠️ Has feedback

### Findings

- **[BLOCKING]** Test `test_search_returns_results` only tests happy path. Spec AC 2 requires handling empty queries gracefully — no test for that.
- **[WARNING]** Fixture uses hardcoded dates (2026-01-01). Consider using relative dates (3 days ago) for test stability.
- **[NOTE]** Consider renaming test to be more specific: `test_search_returns_results_for_valid_query`.

---

## SPEC-001 — commit def456g (implementation phase)

**Reviewed:** 2026-03-17T22:45:00Z
**Status:** ✅ Approved

No issues found. Implementation matches spec, tests are sufficient, code is clean.

---

## SPEC-002 — commit ghi789j (implementation phase)

**Reviewed:** 2026-03-17T23:15:00Z
**Status:** ⚠️ Has feedback

### Findings

- **[BLOCKING]** Implementation uses string interpolation in SQL: `SELECT * FROM users WHERE id = \(id)`. This is a SQL injection vulnerability. Spec doesn't explicitly forbid it, but architecture docs (section 3.2) require parameterized queries.
  **Fix:** Use prepared statements or parameterized queries from the database client.

- **[WARNING]** Performance: the search function loads all users into memory before filtering. With 10K users, this could be slow. Consider database-level filtering or pagination.

### Acknowledged

<!-- Main agent writes here when it reads the feedback -->
```

---

## Main Agent Integration

The main agent incorporates watcher feedback in **LOOP.md step 15: Check Watcher Feedback**.

### For Blocking Issues

If the watcher found blocking issues:

1. Stop
2. Fix the code (go back to LOOP step 8)
3. Re-run full validation (LOOP step 9)
4. Re-review if needed (LOOP step 10)
5. Append acknowledgment to the feedback
6. Continue to next spec

### For Warnings / Notes

If only warnings or notes:

1. Log them in metrics for context
2. Optionally create a TODO for future work
3. Append acknowledgment to the feedback
4. Continue to next spec

### Acknowledgment Format

After reading watcher feedback, the main agent appends:

```markdown
### Acknowledged

Processed by main loop at 2026-03-17T23:30:00Z.
- Blocking issue fixed and re-validated ✅
- Warnings logged for future consideration
- See metrics/2026-03-17_001_SPEC-001.yaml for details
```

This tells the watcher the feedback was seen and acted on.

---

## Design Principles

### Agent-Agnostic

The watcher protocol is a markdown document, just like LOOP.md. Any agent/model can run it. The main agent and watcher don't need to be the same model or provider — in fact, using a different model for the watcher gives more diverse review.

**Benefit:** Model diversity catches model-specific blind spots. If Claude's main loop misses X, GPT's watcher might catch it.

### Communication Is File-Based

No IPC, no sockets, no APIs. The watcher writes a file, the main agent reads it. Git is the shared state. This works with any harness.

### The Watcher Never Writes Code

It only reviews and writes feedback. It has no authority to change files, create branches, or commit. It's read-only + one feedback file. This prevents conflicts.

**Why:** Code conflicts would require merging worktrees or resolving race conditions. File-based feedback avoids this complexity entirely.

### The Watcher Is Optional

The main loop works fine without it — the built-in review personas (from REVIEW.md) are the baseline. The watcher is a quality amplifier for when you want to maximize review coverage.

**When to use:**
- Critical overnight runs
- Complex features where an extra pair of eyes helps
- Evaluating the loop itself
- Different model comparison (e.g., main loop = Opus, watcher = Sonnet)

---

## Launching the Watcher

### Prerequisites

- Main loop is running and committing code to the same repo
- Watcher has read access to the repo and write access to `.nightshift/WATCHER-REVIEW.md`
- `config.yaml` has `watcher.enabled: true`

### Command

If you have a harness (e.g., Claude Code), launch the watcher separately:

```bash
# Terminal 1: Main loop
claude code run .nightshift/BOOTSTRAP.md

# Terminal 2: Watcher (separate session)
claude code run .nightshift/WATCHER.md
```

Or, if your harness supports it, run both in background processes.

### Watcher Configuration

The watcher reads its own config from `config.yaml`:

```yaml
watcher:
  enabled: true
  poll_interval_min: 5             # check every 5 minutes
  idle_timeout_min: 30             # stop if no commits for 30 min
  review_file: ".nightshift/WATCHER-REVIEW.md"
  lens: "general"                  # or specific: security, ux, performance
```

---

## Watcher Implementation Notes

### Step 1: Check for Updates

```bash
# Get timestamp of last review
last_reviewed=$(grep -m1 "^Reviewed:" WATCHER-REVIEW.md | cut -d' ' -f2-)

# Get last commit timestamp
last_commit=$(git log -1 --format=%ci)

# If last_commit > last_reviewed, new work exists
```

### Step 2: Get New Commits

```bash
# List commits since last review
git log --oneline --since="<last_reviewed>" --until=now
```

### Step 3: Review Each Commit

For each new commit:

```bash
# Get commit hash, message, diff
hash=$(git rev-parse HEAD)
message=$(git log -1 --format=%B)

# Extract Spec ID from trailer
spec_id=$(git log -1 --format=%b | grep "^Spec:" | cut -d' ' -f2)

# Get the diff
diff=$(git show --stat)
```

### Step 4: Read the Spec

```bash
# Find the spec file
spec_file=$(find specs/ -name "*${spec_id}*" -type f)

# Extract requirements and AC from frontmatter and content
```

### Step 5: Analyze the Diff

For the chosen lens (code, security, ux, etc.), examine:

- Test coverage: do tests cover AC from the spec?
- Implementation drift: does code match spec?
- Edge cases: are all mentioned cases handled?
- Patterns: does code follow project conventions?
- Lens-specific issues:
  - `security` lens: auth boundaries, input validation, secrets
  - `ux` lens: accessibility, error messages, consistency
  - `performance` lens: queries, allocations, caching

### Step 6: Write Feedback

Append to WATCHER-REVIEW.md in the format above. Structure:

```markdown
## SPEC-XXX — commit <hash> (<phase>)

**Reviewed:** <ISO timestamp>
**Status:** ✅ Approved | ⚠️ Has feedback

### Findings

- **[BLOCKING|WARNING|NOTE]** <issue> ... **Fix:** <recommendation>
- ...

### Acknowledged

<!-- Will be filled by main agent -->
```

---

## Multiple Watchers

For critical runs, launch multiple watchers with different lenses:

```bash
# Terminal 1: Main loop
claude code run .nightshift/BOOTSTRAP.md

# Terminal 2: Code quality watcher
# (config.yaml has watcher.lens: code, review_file: WATCHER-REVIEW-code.md)
claude code run .nightshift/WATCHER.md

# Terminal 3: Security watcher
# (config.yaml has watcher.lens: security, review_file: WATCHER-REVIEW-security.md)
claude code run .nightshift/WATCHER.md

# Terminal 4: Performance watcher
# (config.yaml has watcher.lens: performance, review_file: WATCHER-REVIEW-perf.md)
claude code run .nightshift/WATCHER.md
```

Each watcher writes to its own file. The main loop checks all of them at LOOP step 15.

---

## Metrics & Learning

Track watcher effectiveness:

- Did watcher feedback lead to actual fixes?
- Did watcher catch issues the personas missed?
- Are there patterns in watcher feedback? (e.g., "always catches N+1 queries")
- Different lenses: which are most valuable?

Over time, tune:

- Which lenses to run
- Which models to use for main vs. watcher
- Poll interval (faster feedback vs. less noise)
- Strictness (how much should a note escalate to blocking?)

---

## Future Refinements

- **Cheaper watcher:** Main loop on Opus, watcher on Haiku. Even a less capable model catches oversights.
- **Different provider:** Main on Claude, watcher on GPT. Diversity.
- **Watcher metrics correlation:** Track whether watcher-flagged items actually become bugs. Adjust lens/strictness based on data.
- **Watcher-initiated amendments:** If the watcher consistently flags a missing dimension in specs (e.g., every spec forgets accessibility), it could propose an addition to the spec template.

---

> The watcher is optional but recommended for critical work. It's like having a second pair of eyes while you code — you can ignore it, but it catches things you miss.
