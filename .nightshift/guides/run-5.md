Load when: you run `/nightshift run` or `/nightshift kickoff` and have reached the steps listed under Covers.
Covers: part 5 of 8 of the run procedure: continues with: Declared preflight proof (SPEC-390-002); Declared evidence projection (SPEC-391); Closure packet: SPEC-ARGO-067 (parent-owned, SPEC-289 R6); a-alt; Worked example (illustrative, not tied to a live spec).
Not here: spec authoring (`/nightshift spec`), recovery of a blocked spec (`unblock.md`); the run's pinned executable blocks are in `pinned-briefs.md`, `pinned-checks.md` and `pinned-validator.md`.
Requires: a ready spec in an installed project; read the parts in order: `run.md`, `run-2.md`, `run-3.md`, `run-4.md`, `run-5.md`, `run-6.md`, `run-7.md`, `run-8.md`.

# Run guide, part 5 of 8

**Declared preflight proof (SPEC-390-002).** A spec whose AC rests on an ordinary
preflight run (for example "a preflight passes with admission `allow`") cannot let
the verifier read that run: the retained result is ignored, untracked, and holds
local paths and test output. The verifier instead receives a *sanitized, parsed
projection* of it, bound to the candidate, and checks that projection itself
rather than the author's compact summary. Like external evidence, it needs
`--spec-path`; without a declaration `prepare-dispatch` behaves exactly as before.

*Declaration.* One entry of `context.required_inputs`, a **project-relative** path
to the retained result (never absolute, never containing `..`, never through a
symlink), identical at both verifier arms:

```yaml
context:
  required_inputs:
  - "preflight-proof:reports/_wip/<run>/<SPEC-ID>.preflight.json"
```

*Coordinator step.* Run the ordinary preflight **at the exact candidate commit**
(clean tree; the result records `repository_head`) and keep the retained file out of
Git. The digest is the out-of-band reference for "this is the file that run
produced"; it is never read from the spec, the report, or a compact summary, and a
declaration cannot carry it (a digest of a result that names the commit cannot be
committed in that commit). A result recorded before this change has no
`repository_head` and is therefore `unbound`. Two ways to supply the digest:

- *Automatic (default).* Preflight writes the result and also records its SHA-256 in
  `<metrics_dir>/_wip/preflight-digests/<SPEC-ID>.json` (`spec_id`,
  `repository_head`, `result_sha256`; untracked, parent-private, overwritten by the
  next preflight for that spec, not written when `repository_head` is null). Run
  `prepare-dispatch` **without** `--preflight-proof-sha256`: it reads that record,
  resolves `--head` to a full commit, and uses the digest when the recorded
  `repository_head` equals it. A record for a different head, or an unreadable one,
  refuses the dispatch (exit 2, `controller_reason` `preflight_digest_head_mismatch`
  or `preflight_digest_record_invalid`). No record keeps `no_reference_digest`. The
  record is consulted only when the spec declares a proof.
- *Manual.* Compute the retained file's SHA-256 yourself and pass it as
  `--preflight-proof-sha256`; an explicit flag always wins over the record.

*What the verifier sees.* `.nightshift-verifier-proof/preflight-proof.json` in
both arms, read-only, in a namespace separate from `.nightshift-verifier-inputs/`.
Its fields are an allowlist, each re-validated to a closed shape (digest, enum,
boolean, count, identifier): `retrieval`, `result_sha256`,
`bound_candidate_revision_digest` (a digest, never the raw commit), and a
`projection` of `spec_id`, `timestamp`, `ok`, `blocking_failure_count`,
`git_clean`, `install_admission` (`ok`, `admission`, `invocation_id`,
`artifact_sha256`, `integrity_receipt_sha256`, `coverage`), and `declared_test`
(`configured`, `exit`, `skipped`). No raw output, command line, host path, or
free text crosses. The three same-spec report withholding classes and their
containment audit are unchanged. Containment evidence gains
`declared_preflight_proof` and the public plan gains `preflight_proof`
(`projected_path`, `projected_sha256`, `candidate_revision_digest`,
`checker_provenance`, `candidate_changed_checker`) **only** when a proof was declared.

*Verifier check (trusted copy, SPEC-390-002-001).* Run `verify-preflight-proof` from
the **trusted** copy of `verification_report.py` named by
`plan.preflight_proof.checker_provenance`, pointing `--surface` at the **head arm**:
`baseline_arm` means the baseline arm's copy
(`<baseline arm>/canonical/verification_report.py`, or
`<baseline arm>/.nightshift/verification_report.py` in an installed project);
`installed` means the parent's installed copy
(`.nightshift/verification_report.py`). Never run the head (candidate) arm's own
copy: the candidate can edit `verification_report.py`, and a checker the candidate
controls could report its own proof as `verified`.

```bash
python3 <trusted copy>/verification_report.py verify-preflight-proof \
  --surface <head arm directory> \
  --candidate-revision-digest <plan.preflight_proof.candidate_revision_digest>
```

State which copy you ran (`baseline_arm` or `installed`) in the AC note.
`plan.preflight_proof.candidate_changed_checker` is `true` when
`verification_report.py` differs between the baseline and head arms. A result
produced by running the checker from the head arm alone is then **rejected** as
evidence, and so is any result that does not state its trusted copy; rerun from the
trusted copy or report the AC `unverifiable`.

It prints `{"result": ..., "reasons": [...]}` and exits 0 only for `verified`,
which requires: the document is closed and self-consistent, it is bound to the
plan's candidate digest, `ok` is true with no blocking failures, installation
admission is `allow` with every applicable check passed, the declared test ran
and exited 0, and the invocation is identified. Anything else is `unverifiable`
with every applicable reason; a proof that cannot be established is *reported*,
not a failed dispatch.

| Reason | Condition |
| --- | --- |
| `missing` | no retained file at the declared path, or no projected proof in the arm |
| `path_not_contained` | the declared path is absolute, traverses, or is reached through a symlink; nothing is read |
| `no_reference_digest` | the coordinator supplied no `--preflight-proof-sha256` |
| `digest_mismatch` | the retained bytes differ from the coordinator's digest (altered) |
| `malformed` | unparseable result, oversize (over 1 MiB), or a projection that is not the closed document |
| `declaration_invalid` | more than one `preflight-proof:` entry |
| `unbound` | the result recorded no `repository_head` |
| `wrong_candidate` | the result ran against a different commit than the dispatch head |
| `not_ok`, `admission_not_allowed`, `test_not_passed`, `invocation_unidentified` | the projected outcome itself fails |

If the two arms' declarations differ the dispatch is refused
(`declaration_not_identical`), as for external evidence. Report `unverifiable`
as the AC outcome when the check does; never re-derive the proof from the
author's summary.

*Brief addition.* "`.nightshift-verifier-proof/preflight-proof.json` is a
sanitized projection of a retained preflight result. Judge the AC from the output
of `verify-preflight-proof`, run from the trusted copy named by
`plan.preflight_proof.checker_provenance` (never the head arm's own copy) with
`--surface` at the head arm, and state that copy in the AC note; if it is
`unverifiable`, report the AC as unverifiable and say which reason."

**Declared evidence projection (SPEC-391).** A spec whose AC rests on a same-spec JSON
report artifact the verifier may not read (a report-only acceptance) declares
`verifier_evidence_projection:` in its frontmatter. Like the other declarations it needs
`--spec-path`; without a declaration `prepare-dispatch` behaves exactly as before.

*Declaration.* A list of entries, each a `path:` (a project-relative `.json` artifact, at
most 8 entries) and a `fields:` list of selectors (at most 32 per entry, for example
`rows[*].sha256`):

```yaml
verifier_evidence_projection:
  - path: reports/<SPEC-ID>/artifacts/<artifact>.json
    fields:
      - rows[*].sha256
```

*What the verifier gets.* `prepare-dispatch` writes a sanitized document to
`.nightshift-verifier-evidence/evidence-projection.json` in both arms (never the blob),
bound to the candidate and baseline revision digests and to the head and baseline blob
SHA-256s; the public plan gains `evidence_projection`. Judge it with
`python3 .nightshift/verification_report.py verify-evidence-projection --surface <arm>
--candidate-revision-digest <digest>`.

*Refusals.* Selectors that name conclusions, logs or secrets, undeclared paths, non-JSON
files, dict leaves, host paths, oversize values and declarations that differ between arms
are refused or marked unverifiable. Fix the *declaration* and re-dispatch; never hand the
verifier the path directly.

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

[Pinned in `.nightshift/guides/pinned-briefs.md`: NIGHTSHIFT-VERIFIER-BRIEF - byte-exact, not repeated here.]

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

[Pinned in `.nightshift/guides/pinned-briefs.md`: NIGHTSHIFT-VERIFIER-BRIEF-NOSUITE - byte-exact, not repeated here.]

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

**Worked example — git-mutation-heavy spec (BUG-021, SPEC-309 AC3, resolved).**
BUG-021 needed a real `git commit` against a genuine pre-commit hook. The
worktree-isolated `nightshift-worker` refused: every `git` invocation, even a bare
`git status`, was refused under worktree isolation (Step 4g; `/usr/bin/git` is not a
workaround for this boundary). Per R2 the coordinator executed the live proof directly
and the report said so: "executed by the coordinator, not a worktree-isolated worker,
because SPEC-300-003's pre-commit hook can only be exercised at real commit time." The
independent verifier could re-run the read-only steps but not the commits; per R3/Rule
6-7 those AC(s) are `unverifiable` with reason "cannot independently re-execute
commit-class git mutation under worktree isolation", not `fail`. The classification and
the coordinator-executes-directly fallback hold whatever the refusal's cause (BUG-310).

**Forbidden-content check on the composed brief (R2/AC2), scoped to the
parent-authored text (R1/R2/AC1/AC5).** Run it against the brief you composed,
immediately before dispatch, not the template. It catches a parent that pasted the
worker's report in, while leaving the delimited `{acceptance_criteria_verbatim}` block
out of scope (a spec's ACs can legitimately match the leak pattern). A hit inside the
`NIGHTSHIFT-BRIEF-SPEC-QUOTE-BEGIN`/`-END` delimiters is exempt only once confirmed
against `<spec-file>`; exemption is per occurrence by line position, never by string
identity, and an omitted or unreadable `<spec-file>` fails closed (SPEC-ARGO-048 AC5).

[Pinned in `.nightshift/guides/pinned-checks.md`: NIGHTSHIFT-BRIEF-CHECK - byte-exact, not repeated here.]

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


### Required authored deliverables: ordered intake (BUG-NS-KIT-166)

Generated handoff and manually copied suite/no-suite pinned briefs use the same
`NIGHTSHIFT-ORDERED-DELIVERABLE-INTAKE` block in `pinned-briefs.md`. Preserve it
verbatim. Before accessing substantive required-deliverable conclusions, the
verifier independently derives the relevant source behavior, test assertions
and actual command results from the exact assigned arms, preserving observations
outside the arms. Metadata/path existence and unrelated AC work do not establish
that derivation; target reads rather than searching outcome-bearing documents.
Then inspect the real contractual deliverable and its committed digest. This
instruction order adds no staged-access capability or content-free substitution.

Classify actual exposure honestly. Unavoidable/accidental early exposure remains
`before_derivation` with any capability/evidence gap; it cannot become a final
pass by relabelling. Supported late exposure is `required_deliverable /
after_derivation`. Keep original rejected evidence, exact identity and both-arm
read-only checks. Exposed failures still need independent native reproduction
and lead-only remediation. Assembly and strict final admission remain unchanged.

### Final canonical packaging before configured suites (SPEC-NS-KIT-162)

At canonical hand-back, after all final managed edits including CHANGELOG, run
`python3 canonical/release.py check-final-manifest --canonical canonical` before
launching an expensive configured suite. A nonzero result stops that launch and
names affected paths. The read-only result binds manifest bytes, complete declared
managed bytes and executable modes, and applicable pending handoff membership.
The supported canonical preflight performs this same check before commands.

Finish edits, explicitly regenerate using the existing authoring release helper,
then check again. Every launch needs current identity; a later managed edit, mode
change, manifest edit or handoff change invalidates retained packaging evidence.
This command never regenerates, bumps versions, reseals historical releases or
patches installed copies. Installed-profile preflight retains its own admission
contract and does not require a canonical-only manifest.
