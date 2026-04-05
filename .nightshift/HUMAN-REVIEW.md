# Human Review Checklist

**Purpose:** The morning-after protocol. A human (or AI architect like Argo) inspects the loop's overnight output and decides what comes next.

---

## Quick Scan (2 minutes)

**What to do:**

1. Read `.nightshift/reports/YYYY-MM-DD-nightshift-report.md`
2. Look at:
   - Which specs completed? ✅
   - Which are blocked? ⏸
   - Any discovered TODOs?
3. Decide: is anything obviously broken or wrong?

If everything looks good, proceed to detailed review. If something is obviously wrong, jump to section "When Something Is Wrong" below.

---

## Commit Review (10-20 minutes)

**What to do:**

1. Walk the git log for the nightshift run:
   ```bash
   git log --oneline <main-branch>..<nightshift-branch>
   # or for local work:
   git log --oneline -N
   ```
2. Read each commit message
3. For key commits, check the diff:
   ```bash
   git show <commit-hash>
   ```
4. Ask yourself:
   - Does the approach make sense?
   - Are there obvious design issues?
   - Any surprises or unexpected changes?

**Commit format to expect:**

```
feat(SPEC-001): add search feature with fuzzy matching

Added a new SearchService that indexes documents and provides fuzzy search.
Chose Levenshtein distance algorithm for tolerance to typos. Considered BK-trees
for performance but opted for simplicity given small corpus. Tests cover happy
path, empty input, and Unicode handling.

Nightshift-Loop: 2026-03-16
Spec: SPEC-001
Phase: implementation
```

Look for:
- Clear messages with reasoning
- Appropriate granularity (per-phase, not squashed into one giant commit)
- Conventional format (feat/fix/test/docs)

---

## Changelog Review (2 minutes)

**What to do:**

1. Read the CHANGELOG entries in the report or in the repo
2. Verify they summarize the changes in human language
3. Check: does a non-technical stakeholder understand what changed?

**Good changelog:**
> Added search feature with fuzzy matching. Users can now search documents by title or content. Empty searches are handled gracefully.

**Bad changelog:**
> feat: add fuzzy search

---

## Test Review (5 minutes)

**What to do:**

1. Look at the test files that were added/modified
2. Questions to ask:
   - Do tests cover the acceptance criteria from the spec?
   - Are edge cases tested?
   - Do tests test behavior, or just implementation details?
   - Is the test setup clear and maintainable?

**Good tests:**

```typescript
describe("SearchService", () => {
  it("returns matching documents", () => {
    const results = searchService.search("lorem");
    expect(results).toHaveLength(2);
    expect(results[0].title).toContain("lorem");
  });

  it("handles empty query gracefully", () => {
    const results = searchService.search("");
    expect(results).toHaveLength(0); // empty query = no results
  });

  it("handles Unicode correctly", () => {
    const results = searchService.search("łódź");
    expect(results[0].title).toBe("Łódź Guide");
  });
});
```

**Weak tests:**

```typescript
it("search works", () => {
  const results = searchService.search("x");
  expect(results.length).toBeGreaterThan(0); // too vague
});
```

---

## Functional Testing (5-10 minutes)

**For human reviewers:**
- Run the app locally
- Click through the new features
- Try to break them (empty inputs, edge cases, strange data)
- Verify it works as described in the spec and changelog

**For AI reviewers (e.g., Argo):**
- Run the test suite again (local run may have used a different environment)
- Check build artifacts (does it compile? any warnings?)
- Examine integration points (does it integrate cleanly with existing code?)
- Spot-check edge cases (does the implementation handle what the spec required?)

---

## Blocked Specs (5 minutes)

**What to do:**

1. Read `.nightshift/reports/BLOCKED-*.md` files (if any)
2. For each blocked spec:
   - Understand the agent's hypothesis for the root cause
   - Decide: can you unblock this?
   - Options:
     - **Clarify the spec** — the spec was ambiguous, write a clearer version
     - **Provide infrastructure** — missing tool, API docs, permission, dependency
     - **Config change** — update `config.yaml` to help the agent
     - **Accept the limitation** — it's genuinely blocked and can't be fixed without bigger work
3. If you can unblock it: do so and re-queue the spec as `status: ready`
4. If not: leave it blocked and note why for future context

**Example BLOCKED report:**

```
# Blocked: SPEC-010 — Integrate Payment Gateway

**When:** 2026-03-17T23:45:00Z
**Phase:** Implementation
**Signal:** Max spec duration exceeded (>2 hours)

## What Was Attempted

- Attempt 1: Read Stripe docs, wrote integration
  Error: Authentication fails, returns 401
- Attempt 2: Checked API key in config, seemed valid
  Error: Still 401, no docs on sandbox vs. live mode
- Attempt 3: Tried switching between sandbox and live keys
  Error: Can't tell which mode works without testing against real Stripe

## Root Cause Hypothesis

Agent doesn't have the Stripe API documentation for this project. The docs
might be behind a paywall or in a private wiki. Without them, agent can't
understand the correct authentication flow.

## What a Human Needs to Do

Provide:
1. Stripe API documentation for this project
2. Valid sandbox API key (current key returns 401)
3. Clarification: are we integrating Stripe test or live mode?
4. Link to project's payment architecture doc (if exists)
```

---

## Discovered TODOs (5 minutes)

**What to do:**

1. Read `.nightshift/reports/TODOs-discovered.md` (if exists)
2. For each TODO:
   - Is it real? Is it worth doing?
3. If yes: write a spec for it and add to `specs/`
4. If no: discard it or note in `knowledge/` as "known, accepted"

**Example:**

```
### [Tech Debt] - Refactor UserRepository to use async/await

**Location:** src/repositories/UserRepository.ts
**Why:** Current Promise chaining is hard to read. Async/await is clearer.
**Suggested action:** Small refactor. Could be a SPEC-NNN task.
```

Decision:
- "Yes, this is real" → Create SPEC-015: "Migrate UserRepository to async/await" (Layer 3, refactor, priority 2)
- "Not urgent" → Note in knowledge/ as "UserRepository uses Promises by choice (compatibility), refactor deferred"

---

## Metrics Review (5 minutes)

**What to do:**

1. Read `.nightshift/metrics/YYYY-MM-DD_NNN_SPEC-*.yaml` files
2. Look for patterns:
   - How long did each spec take?
   - How many review cycles?
   - How many tests?
   - Any build/test failures?

**Questions to ask:**

- Are there bottlenecks? (e.g., "plan review always takes 30 mins")
- Are any phases consistently slow? (e.g., "implementation always takes 2+ hours")
- Are review cycles high? (e.g., ">3 cycles per spec") — suggests review criteria are unclear
- Are test pass rates good? (e.g., >95% pass rate on first run)

**Example insights:**

```
Low review cycles (avg 1.2) → review criteria are clear, agent and reviewers aligned
High plan review duration (avg 45 min) → consider simplifying review process
Low test coverage (avg 3 tests per spec) → testing standards need clarification
```

---

## When Something Is Wrong

**The critical rule: Don't tell the agent to fix the code. Fix the system that produced the wrong code.**

When the agent produces incorrect or suboptimal output, the root cause is almost never "the agent is dumb." It's one of:

### Root Cause: Missing Documentation

**Symptom:** The review persona that should have caught this didn't have the right docs.

**Example:** Security reviewer didn't catch SQL injection because there was no security.md doc.

**Fix:** Write the missing doc in `knowledge/_review/`:
```markdown
# knowledge/_review/security.md

## SQL Injection Prevention
All database queries MUST use parameterized queries or prepared statements.
Never use string interpolation or concatenation for queries.

Examples:
- ❌ `SELECT * FROM users WHERE id = ${userId}`
- ✅ `SELECT * FROM users WHERE id = ?` (with parameterized binding)
```

Commit: `docs: add security.md to knowledge`

Next time, the security reviewer will have this doc and catch the issue in the plan phase.

### Root Cause: Spec Ambiguity

**Symptom:** Agent implemented something reasonable, but it wasn't what the spec wanted.

**Example:** Spec says "handle errors gracefully" but doesn't define what that means. Agent logs them, you wanted a user-friendly message.

**Fix:** Rewrite the spec section to be clearer:
```markdown
## Acceptance Criteria
- [ ] AC 1: When an error occurs, display a user-friendly message (not a stack trace)
- [ ] AC 2: Log the full error server-side for debugging
```

Update the spec in `specs/` and add a note for next time.

Commit: `docs(SPEC-XXX): clarify error handling requirements`

### Root Cause: Weak Test Plan

**Symptom:** Tests pass but behavior is wrong in edge cases.

**Example:** Tests cover happy path but miss the "empty input" case mentioned in the spec.

**Fix:** Strengthen testing standards in `knowledge/` or add a note to the spec template:
```markdown
# knowledge/_review/testing-standards.md

## Coverage Requirements
- Happy path (normal input)
- Empty/null input
- Boundary values
- Error conditions
- Integration with related features
```

Commit: `docs: add testing standards to knowledge`

### Root Cause: Missing Static Tool

**Symptom:** Code has a obvious bug (missing null check, unused variable) that a linter would catch.

**Example:** No linter configured, so unused imports creep in.

**Fix:** Enable or tighten the static tool in `config.yaml`:
```yaml
commands:
  lint: "your-linter --strict"  # configure to fail on warnings, not just errors
```

Or create a SPEC to set up missing tools.

Commit: `config: enable stricter linting`

Next run, the agent runs lint after every file and catches these issues immediately.

### Root Cause: Loop Gap

**Symptom:** The loop protocol itself is missing a step or check.

**Example:** Agent doesn't validate that the implementation actually matches the spec before moving on.

**Fix:** Update LOOP.md and bump the version date:
```
**Version:** 2026-03-18  (was 2026-03-16)
```

Add a new check, or expand an existing step.

Commit: `docs: update LOOP.md with spec-to-implementation validation`

The next agent gets the improved loop.

---

## The Feedback Cycle

Each review round should produce **at least one systemic improvement:**

- Missing doc? Write it.
- Unclear spec? Clarify it.
- Weak tests? Strengthen standards.
- Missing linter rule? Enable it.
- Loop gap? Update LOOP.md.

Over time, the same mistakes stop happening. This is the compounding effect — each cycle the loop gets slightly better.

---

## For AI Reviewers (Orchestrator / Architect Role)

When reviewing sub-agent output:

1. **Read the report** — 2 minutes
2. **Walk the commits** — 10 minutes
3. **Write the systemic fix** directly:
   - Missing doc → write `knowledge/` entry
   - Linter gap → update `config.yaml`
   - Spec lesson → add a knowledge entry if it applies beyond this spec
4. **Only escalate to the human when:**
   - A design/product decision is needed
   - Manual testing is required (agent can't do it)
   - Something is blocked by infrastructure outside the loop's control

The reviewer does not tell the agent to "fix the code again." Fix the system, commit it, and the next run gets better.

---

## End-of-Review Checklist

- [ ] Read the report (2 min)
- [ ] Walk the commits (10-20 min)
- [ ] Review tests (5 min)
- [ ] Functional test (5-10 min)
- [ ] Handle blocked specs (5 min)
- [ ] Triage discovered TODOs (5 min)
- [ ] Check metrics for patterns (5 min)
- [ ] Write systemic improvements (10 min)
- [ ] Commit all changes: `docs: post-review updates`
- [ ] Update specs with new work (if new specs created)
- [ ] Commit: `docs: add new specs from review`

**Total time:** 30-60 minutes for a typical overnight run.

---

> The goal is not to catch every bug — it's to improve the system so bugs are less likely next time.
