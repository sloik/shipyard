# Interactive Spec Creation Guide

**Purpose:** Use this document to walk a user (or agent) through creating a Nightshift spec step by step. Any LLM that can read files and have a conversation can follow this guide to help the user write a complete, well-formed spec.

**How to use:** An agent reads this guide, then asks the user a series of questions—one section at a time. After each answer, the agent fills in that section of the spec. At the end, the agent presents the complete spec for review and saves it to `specs/SPEC-XXX-short-title.md`.

**Works with:** Any LLM (Claude, GPT, Gemini, Llama, etc.) that can read markdown and conduct a conversation.

**Reference:** For the complete spec template and all sections, see `_TEMPLATE.md`. This guide references the template but does not duplicate its content.

---

## Phase 0: Auto-Discovery (Agent Work)

Before asking the user any questions, the agent should:

1. **Read the project's `config.yaml`** to understand:
   - Project name
   - Primary languages
   - Domain (code, research, or analysis)
   - Build/test/lint conventions
   - Review personas that apply

2. **List existing specs** in `specs/` to determine:
   - What's the next available SPEC-XXX number?
   - What domains/layers are already covered?
   - What patterns exist in existing specs?

3. **Summarize findings** to present to the user:
   ```
   "This is the Nightshift Kit for [project name].
   Domain: [code/research/analysis]
   Next available spec ID: SPEC-XXX

   Let me walk you through creating a new spec. We'll cover 9 phases, taking about 20-30 minutes total."
   ```

---

## Phase 1: Problem & Motivation

**Agent's Task:** Ask the user to articulate the problem and why it matters.

**Questions to ask:**

1. **"What problem are you trying to solve?"**
   - Expected answer: A concrete pain point, user frustration, or missing capability
   - Example: "Users can't search the document library. Currently they have to scroll through 500+ entries to find one document."

2. **"Why does this matter now? What's the trigger?"**
   - Expected answer: Business context, user feedback, deadline, blocker, or opportunity
   - Example: "We have 50 new users onboarding next week. Search is critical for them to be productive."

3. **"Who is affected? Who benefits from solving this?"**
   - Expected answer: User personas, teams, or stakeholders
   - Example: "Daily users and new onboarders. The support team also gets fewer 'How do I find X?' questions."

**Guardrails (Agent must enforce):**

- **If the answer is vague** ("make things better", "improve performance"):
  - Pushback: "That's too abstract. Can you give me a specific, concrete pain point? For example: 'Users spend 10+ minutes per day scrolling' or 'We lose customers because of slow load times.'"

- **If the answer describes a solution instead of a problem** ("add caching", "implement Redis"):
  - Pushback: "That sounds like a solution. Let's focus on the underlying problem. Why do you need a cache? What pain does it solve?"

- **If the answer has no time pressure or business justification**:
  - Pushback: "This sounds useful, but why now? Is there a deadline, user request, or blocker driving this?"

**After Phase 1:** Agent should be able to fill in the `## Problem` section of the spec template.

---

## Phase 2: Scope & Type

**Agent's Task:** Help the user define the scope and determine what kind of work this is.

**Questions to ask:**

1. **"Is this a new feature, a bug fix, a refactoring, or an evaluation task?"**
   - Expected answer: One of `feature`, `bugfix`, `refactor`, `eval`
   - Guide the user:
     - **Feature:** Something new the system doesn't do yet
     - **Bugfix:** Fixing broken behavior
     - **Refactor:** Improving existing code without changing behavior (performance, maintainability, tech debt)
     - **Eval:** Research or evaluation task (for research/analysis domains)

2. **"What layer does this belong in?"** (Explain layers first)
   ```
   Layers enforce a natural build order. All Layer 0 must be done before Layer 1, etc.
   - Layer 0: Foundation (project setup, core models, CI, static tools)
   - Layer 1: Infrastructure (logging, auth, API client, database layer, caching)
   - Layer 2: Features (user-facing features, search, profiles, notifications)
   - Layer 3: Polish (performance optimization, accessibility, analytics)
   ```
   - Expected answer: A number 0-3
   - Guide: "This helps us build in the right order. Dependencies before dependents."

3. **"Does this depend on any other specs being done first?"**
   - Expected answer: List of spec IDs (e.g., `[SPEC-001, SPEC-005]`) or "no"
   - Guide: "If this spec builds on top of another feature, list it here. The loop will respect the dependency."

**Guardrails (Agent must enforce):**

- **If the user describes something that sounds like 2-3 separate features** ("add search, add filters, and add sorting"):
  - Pushback: "This sounds like 3 features. Let's focus on the core — what's the minimum viable version? We can make filters and sorting separate specs later."

- **If the layer choice seems off** (e.g., a feature in Layer 0):
  - Suggest: "Layer 0 is for foundation only. Does this really belong there? Should this be Layer 2 (features)?"

- **If the type is unclear** ("kind of a bugfix, kind of a refactor"):
  - Clarify: "Let me ask differently. Is the system currently broken (bugfix) or does it work but just needs to be cleaner (refactor)?"

**After Phase 2:** Agent should have values for `type`, `layer`, and `after` in the frontmatter.

---

## Phase 3: Requirements

**Agent's Task:** Extract the specific, testable requirements that the agent needs to implement.

**Question to ask:**

1. **"What are the specific things the agent needs to build/produce?"**
   - Expected answer: A list of discrete, independently verifiable items
   - Say: "I'll ask you this differently based on your domain:"

**Domain-specific prompts:**

- **Code domain:**
  ```
  "What functions, endpoints, components, or modules need to exist?
  List each one as a clear statement:
  - Add a `/api/search` endpoint
  - Implement fuzzy-match algorithm
  - Add SearchBox component to UI
  etc."
  ```

- **Research domain:**
  ```
  "What output sections or deliverables are expected?
  For example:
  - Synthesize findings from 5+ sources
  - Write a summary of key trends
  - Create a recommendation section
  etc."
  ```

- **Analysis domain:**
  ```
  "What calculations or reports need to be produced?
  For example:
  - Calculate monthly transaction totals by category
  - Generate a CSV export with reconciliation checks
  - Cross-reference summary vs. detail totals
  etc."
  ```

**Guardrails (Agent must enforce):**

- **If requirements are vague** ("make search work", "improve the report"):
  - Pushback: "That's the goal, not a requirement. Be more specific. 'Make search work' — what does working mean? What features?"

- **If there are 5+ requirements covering unrelated areas**:
  - Suggestion: "This is a lot. Should we split this into 2-3 specs? Each spec should be focused on one area."

- **If a requirement is implementation-specific** ("use a B-tree index", "call the AWS API"):
  - Redirect: "That's an implementation detail. State the requirement instead: 'Search must work with 100K documents.' We'll let the agent decide how."

**After Phase 3:** Agent should be able to fill in the `## Requirements` section with a checked list of 2-5 items.

---

## Phase 4: Acceptance Criteria

**Agent's Task:** Extract concrete, testable criteria that prove the requirements work. This is the most critical phase.

**Say to the user:**

```
"For each requirement, what's the concrete test that proves it works?
These become the test cases. They must be specific and testable —
not vague like 'works well' or 'is fast', but measurable:
'returns results within 500ms', 'handles 100K items', etc."
```

**Then ask:**

1. **"For each requirement, what's the concrete test?"**
   - Expected answer: One or more acceptance criteria per requirement
   - Example for "add search box":
     - "User types in search box, results filter in real-time"
     - "Empty search returns all documents"
     - "Special characters don't crash the UI"

2. **"What edge cases should be handled?"**
   - Expected answer: Boundary conditions, error states, unusual inputs
   - Domain-specific prompts:
     - **Code:** "What happens with null input? Empty list? No authentication? Very large input? Special characters?"
     - **Research:** "What if a source is unavailable? What if claims contradict? What if there's insufficient data?"
     - **Analysis:** "What if data is missing? What if totals don't reconcile? What if there are duplicates?"

3. **"Are there any boundary values we should test?"**
   - Expected answer: Limits, thresholds, edge values
   - Examples: "0 items", "1 item", "1M items", "negative numbers", "future dates"

**Guardrails (Agent must STRICTLY enforce this phase):**

- **Reject vague acceptance criteria:**
  - ❌ "Search works well"
  - ❌ "Performance is good"
  - ✅ "Search returns results within 500ms for 100K documents"
  - ✅ "UI remains responsive (no > 1s freezes) during search"

- **Reject non-testable acceptance criteria:**
  - ❌ "Code is clean"
  - ❌ "User experience is smooth"
  - ✅ "All functions have docstrings"
  - ✅ "Lint passes with zero warnings"

- **Reject acceptance criteria without context:**
  - ❌ "Search works" (works how? How fast? With what data size?)
  - ✅ "Search returns results within 500ms for queries up to 100 chars on a 100K-document corpus"

- **Ensure edge cases are covered:**
  - If user only mentions happy path ("user types 'budget', sees results"):
    - Pushback: "Good. Now the unhappy paths: What if they type nothing? What if they type special characters? What if the query is 1000 characters long?"

- **Ensure each AC maps to at least one requirement:**
  - "We've listed 7 acceptance criteria. Which requirement does AC-6 belong to? I don't see a match."

**Checklist for Phase 4 (Agent must verify):**

- [ ] Each requirement has at least one AC
- [ ] Each AC is specific and measurable (not vague adjectives)
- [ ] Each AC is independently testable
- [ ] Edge cases are covered (null, empty, invalid, boundary, large)
- [ ] Domain-specific edge cases are included (auth, concurrency, duplicates, etc.)
- [ ] No AC is an implementation detail
- [ ] AC count is reasonable (2-3 per requirement, total 5-15)

**After Phase 4:** Agent should have a complete list of acceptance criteria that can be turned into test cases or validation checklists.

---

## Phase 5: Context & Constraints

**Agent's Task:** Gather background information, existing code/docs, and any limitations.

**Questions to ask:**

1. **"What existing code, files, or documentation should the agent look at?"**
   - Expected answer: File paths, module names, API docs, architecture guides
   - Examples:
     - "See `src/repositories/DocumentRepository.ts` for existing fetch patterns"
     - "API contract: GET `/api/documents/search?q=query`"
     - "See `knowledge/search-patterns.md` for project conventions"

2. **"Are there any constraints?" (performance, compatibility, dependencies, etc.)**
   - Expected answer: Hard limits or requirements
   - Examples:
     - "Search must be <500ms for 100K documents"
     - "Must work with PostgreSQL and MySQL"
     - "Cannot add external dependencies (no npm packages)"

3. **"Any known gotchas or pitfalls?"**
   - Expected answer: Things the agent should watch out for
   - Examples:
     - "Watch out for N+1 queries when fetching metadata"
     - "Previous attempts at search failed due to memory overhead with large datasets"
     - "This repository has strict lint rules — make sure to check early"

**Guardrails (Agent must enforce):**

- **If context is too vague** ("look at the codebase"):
  - Pushback: "Be more specific. What files? What patterns should they follow? What conventions?"

- **If constraints are missing for non-trivial specs** (e.g., no performance requirement for a search feature):
  - Pushback: "You haven't mentioned performance. How fast should search be? Is there a timeout?"

- **If the user provides implementation details as context** ("use Redis for caching"):
  - Redirect: "That's implementation. The context should describe what the agent will find, not how to solve it."

**After Phase 5:** Agent should have values for `Context` section and understand what knowledge the agent will need.

---

## Phase 6: Scenarios (End-to-End)

**Agent's Task:** Extract end-to-end user journeys that describe complete workflows.

**Say to the user:**

```
"Scenarios are different from acceptance criteria. Instead of testing
individual conditions, scenarios test complete user journeys.
Walk me through what a real user does, step by step."
```

**Then ask:**

1. **"Describe a complete, happy-path user journey:"**
   - Expected answer: "User does X → sees Y → does Z → sees result"
   - Example: "User opens document list → types 'budget' in search → sees 3 matching docs → clicks first → document opens"

2. **"Now describe an edge-case or error scenario:"**
   - Expected answer: "User encounters [unusual state] → system responds with [graceful behavior]"
   - Example: "User searches while offline → sees cached results with 'last updated 2h ago' banner → reconnects → results refresh"

3. **"Any other scenarios?"**
   - Expected answer: Key user flows that validate the feature works end-to-end
   - Aim for 2-4 scenarios total

**Guardrails (Agent must enforce):**

- **If scenarios are too granular** (testing single conditions like "button is visible"):
  - Redirect: "That's too micro. I need user journeys — start to finish. What does the user do, and what do they see?"

- **If scenarios are missing error cases:**
  - Pushback: "Good happy path. Now what if something goes wrong? Network failure? Invalid input? Rate limit?"

- **If scenarios duplicate acceptance criteria exactly:**
  - Note: "Scenarios validate the whole flow. They can reference ACs but should test integration, not individual conditions."

**After Phase 6:** Agent should have 2-4 end-to-end scenarios that describe complete user workflows.

---

## Phase 7: Out of Scope

**Agent's Task:** Clarify what's explicitly NOT being done in this spec.

**Question to ask:**

1. **"What are you explicitly NOT including in this spec?"**
   - Expected answer: Related features or enhancements that are deliberate exclusions
   - Examples:
     - "Advanced filters (by date, author, tag) — future spec"
     - "Autocomplete/suggestions — not in MVP"
     - "Search history — out of scope"

2. **"Any related features that should be separate specs later?"**
   - Expected answer: Follow-on work that could be specs in a future layer
   - Example: "We'll do basic search in this spec, then fuzzy-match in SPEC-XXX, then advanced filters in SPEC-YYY"

**Guardrails (Agent must enforce):**

- **If "out of scope" is vague** ("we won't do everything"):
  - Pushback: "Be specific. What features or requirements are we leaving out?"

- **If scope creep is visible** ("and also filters, and also sorting, and also saved searches"):
  - Redirect: "Those are all good ideas. Let's list them as 'out of scope for this spec' and create separate specs for them. This keeps scope tight."

**After Phase 7:** Agent should have a clear list of what's NOT being done, which prevents scope creep during implementation.

---

## Phase 8: Optional Sections

**Agent's Task:** Check for optional but high-value sections.

**Ask:**

1. **"Have there been previous attempts at solving this problem?"**
   - If yes: "What happened? Why did they fail? What should the agent learn?"
   - Use this to fill `prior_attempts` in frontmatter and `Alternatives Considered` section

2. **"Is there an exemplar (working implementation of something similar) the agent should study?"**
   - If yes: "What's the source? What patterns should they learn? What should they NOT copy?"
   - Use this to fill `Exemplar` section

3. **"Any final notes or clarifications for the agent?"**
   - Use this to fill `Notes for the Agent` section

**After Phase 8:** Agent has gathered all remaining context.

---

## Phase 9: Review & Output

**Agent's Task:** Present the complete spec, validate it against a checklist, and save it.

**Steps:**

1. **Present the complete spec to the user:**
   ```
   "Here's the complete spec. Please review it for clarity and accuracy.
   I'll also run it against a quality checklist."
   ```

2. **Run the checklist from `_TEMPLATE.md` → "Checklist Before Marking as Ready":**
   - [ ] Problem and context are clear
   - [ ] Requirements map to acceptance criteria
   - [ ] Acceptance criteria are specific and testable
   - [ ] Layer and priority are reasonable
   - [ ] Out of scope is clear
   - [ ] Soft dependencies are noted
   - [ ] Prior attempts are listed
   - [ ] Alternatives considered are filled
   - [ ] Scenarios describe end-to-end journeys
   - [ ] Exemplar is linked (if available)
   - [ ] Someone reviewed the spec (the agent did; human should too)

3. **Flag any weaknesses:**
   - If AC-3 is vague, flag it: "AC-3 is a bit vague — should we tighten it to: 'search returns results within 500ms'?"
   - If layer seems wrong: "This feels like Layer 2 (feature), not Layer 1 (infra). Should we move it?"
   - If requirements don't match acceptance criteria: "We have 5 requirements but only 3 ACs. Each requirement should have at least one AC."

4. **Ask for approval:**
   ```
   "Ready to save? I'll write this to:
   specs/SPEC-XXX-short-title.md
   with status: ready

   Should I proceed, or make any changes first?"
   ```

5. **After approval, save the spec:**
   - Write the complete spec to `specs/SPEC-XXX-short-title.md`
   - Set frontmatter fields:
     - `id: SPEC-XXX`
     - `priority: [1-10, default 5]` ← Ask user if not specified
     - `layer: [0-3]` ← Should be filled from Phase 2
     - `type: [feature/bugfix/refactor/eval/nfr]` ← From Phase 2 (nfr = standing constraint, not a task)
     - `status: ready` ← Ready to enter the loop
     - `after: [list of spec IDs]` ← From Phase 2
     - `prior_attempts: []` ← From Phase 8
     - `created: [YYYY-MM-DD]` ← Today's date

6. **Confirm successful save:**
   ```
   "✅ Spec saved to specs/SPEC-XXX-short-title.md

   This spec is ready for the Nightshift loop. An agent can now pick it up
   and begin implementation. The loop will follow LOOP.md and use your
   acceptance criteria as the definition of done."
   ```

---

## Anti-Patterns Reference

Use this table to catch common spec mistakes and redirect:

| Anti-Pattern | Example | How Agent Should Fix |
|---|---|---|
| **Solution disguised as problem** | "We need to add Redis" | "What latency problem are you solving? Let's focus on the problem, not the solution." |
| **Vague acceptance criteria** | "Search works well" | "Too vague. How fast? How many results? What data size? Be specific and measurable." |
| **Scope creep baked in** | 10+ requirements covering 3 different features | "This is really 2-3 specs. Let's split: foundation spec, then feature spec, then polish spec." |
| **Implementation details in spec** | "Use a B-tree index on the name column" | "That's how you'd solve it. State the requirement instead: 'Search by name must be fast (<200ms).'" |
| **Missing edge cases** | Only happy path tested | "Good happy path. Now: what happens with null input? Empty data? Huge input? Errors?" |
| **Untestable requirements** | "Code should be clean" | "That's not testable. How do you measure it? 'All functions have docstrings'? 'Lint passes'? Be concrete." |
| **No priority or layer** | Spec written but layer/priority blank | "Which layer (0-3)? What priority (1-10)? These help the loop build in order." |
| **Dependencies not declared** | Spec depends on SPEC-002 but doesn't say so | "Does this depend on another spec? If so, list it in `after:` so the loop knows the order." |
| **No way to verify completion** | "Implement user authentication" with vague ACs | "How will the agent know when auth is done? What tests pass? Write concrete ACs." |
| **Too large for one spec** | 50+ lines, 8+ requirements, 3 different layers | "This is too big. Split it. Nightshift specs should be 1-2 days of work max per spec." |

---

## Domain-Specific Guidance

### For Code Domain:

- **Phase 3 (Requirements):** Focus on components, endpoints, functions that need to exist
- **Phase 4 (AC):** Emphasize unit tests, integration tests, edge cases with type errors, null handling, concurrency
- **Phase 5 (Context):** Point agent to relevant modules, existing patterns, performance budgets
- **Phase 6 (Scenarios):** Describe user-facing workflows and API interactions
- **Out of Scope:** Often includes "performance optimization", "refactoring", "documentation" — separate concerns

### For Research Domain:

- **Phase 3 (Requirements):** Focus on research questions, deliverable sections (summary, findings, recommendations)
- **Phase 4 (AC):** Emphasize source verification, fact-checking, citation completeness, bias detection
- **Phase 5 (Context):** Point agent to available sources (APIs, databases, articles), citation format requirements
- **Phase 6 (Scenarios):** Describe how the output answers the research question
- **Out of Scope:** Often includes "peer review", "publication", "further analysis" — separate concerns

### For Analysis Domain:

- **Phase 3 (Requirements):** Focus on calculations, reports, data transformations, aggregations
- **Phase 4 (AC):** Emphasize calculation correctness, cross-reference reconciliation, boundary conditions (zero, negative, missing data)
- **Phase 5 (Context):** Point agent to data sources, data dictionary, calculation formulas
- **Phase 6 (Scenarios):** Describe how output is used and what it proves
- **Out of Scope:** Often includes "visualization", "predictive modeling", "data cleaning" — separate concerns

---

## Using This Guide

### For Agents:

1. **Read this guide in full** before starting any conversation with a user
2. **Follow the 9 phases in order** — don't skip ahead
3. **Use guardrails strictly** — catch vague specs before they cause wasted work during implementation
4. **Enforce the Anti-Patterns table** — these are real mistakes that slow down the loop
5. **At Phase 9, validate against the checklist** — a strong spec saves tokens

### For Humans (Users):

1. **Find an agent** that can read markdown and conduct a conversation
2. **Give the agent this guide:** "Read this and walk me through creating a spec"
3. **Be ready to answer 9 questions** — budget 20-30 minutes
4. **Expect pushback** if your answers are vague — that's the guardrails working
5. **Review the final spec carefully** — this is the contract between you and the agent that will build it

---

## Notes on Implementation

- **Flexibility:** Agents may ask questions in different order or combine phases — that's fine as long as all 9 phases are covered
- **Iteration:** Users may change their minds. Let them revise answers. Specs evolve during the conversation
- **Blocking:** If a user can't answer a phase clearly, don't proceed. Ask for clarification or suggest they come back when ready
- **Timing:** A well-conducted spec conversation takes 20-30 minutes. If it's taking 2+ hours, the problem may be too large (scope creep) or too vague (needs more research)

---

> **A well-written spec is the difference between smooth execution and frustrating back-and-forth.**
>
> This guide exists to prevent the latter.
