Load when: you run `/nightshift address-issues`: consolidating open questions embedded in draft or blocked specs.
Covers: the QUESTIONS spec format, the scan, the one-question-at-a-time discussion flow, applying decisions back to source specs and the guidelines.
Not here: executing a ready spec (`/nightshift run`), recovery of a blocked spec (`unblock.md`), the invalid old-run recovery paragraph (kept in SKILL.md).
Requires: draft or blocked specs in the project's `specs/`.

# Address-issues guide

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
