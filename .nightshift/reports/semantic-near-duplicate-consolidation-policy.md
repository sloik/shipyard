# Semantic Near-Duplicate Consolidation Policy

## Purpose and boundary

`check_followup_spec.py --scan-all` compares titles and Requirements / Acceptance
Criteria text. Its similarity findings are candidates for human review, not proof
that two specifications have the same historical identity or should be changed.

This policy is separate from the exact control-plane integrity checks restored by
SPEC-BUG-157. A duplicate non-template `id`, or an unresolved or ambiguous
structured `after`, `parent`, `children`, or `implementation_order` reference,
is an exact validation defect and must continue to fail its existing validation
gate. A semantic finding must never suppress, downgrade, or "resolve" such an
exact defect.

## Signal classification

Classify every scanner finding before acting on it.

| Classification | When it applies | Required action |
| --- | --- | --- |
| `informational` | Similarity is explained by shared vocabulary, a parent/child relationship, a common template, adjacent work, or one weak signal with no evidence of duplicate intent. | Record the rationale; make no historical metadata change. |
| `review-needed` | Title or Requirements/AC similarity is material enough that independent work, shared implementation intent, or a prior migration may be plausible; or the scanner produces both a strong title and body signal. | Preserve both records and open a review record. Collect the evidence below before proposing any consolidation. |
| `approved-consolidation` | A named reviewer has approved a specific, bounded disposition after the minimum evidence is recorded. | Apply only the approved disposition and record the resulting links, commits, and validation evidence. |

Scores are triage signals, not automatic classification. In particular, the
scanner threshold alone cannot make a finding `approved-consolidation`; it can
at most make it `review-needed`.

## Evidence and approval gate

Before merging, retiring, relinking, renaming, or changing the status or
dependencies of a historical spec, a review record must contain all of the
following:

1. The two immutable source paths and canonical IDs, plus the scanner output
   (title and body scores) that initiated review.
2. A comparison of problem, requirements, acceptance criteria, scope, dates,
   parent/dependency edges, and completion/implementation evidence. It must say
   whether the records describe the same intended work, overlapping work, or
   merely similar language.
3. Historic-identity evidence: original commit/history or a documented absence
   of it, any prior ID-migration entry, and the reason the selected canonical
   record—not just its wording—is authoritative.
4. Status evidence before any status change: the existing status/checkboxes and
   the supporting implementation, report, validation, or decision record. Do
   not infer completion or retirement from similarity.
5. Dependency evidence before any edge change: every inbound and outbound
   structured reference, the target IDs after the change, and a successful exact
   reference/graph validation after the proposed edit.
6. An explicit human maintainer approval naming the chosen disposition,
   affected IDs, and rationale. Automation may prepare evidence but cannot grant
   approval.

Permitted dispositions are: retain both with an informational rationale; retain
both and cross-link related work; create a new successor/canonical record while
preserving both historical records; or retire/relink a record only when the
approval specifically authorizes it. Destructive consolidation is never the
default.

## Auditable review outcome

Each reviewed finding must have one durable entry (in the run report, a linked
decision record, or the affected spec history) with this minimum schema:

```text
finding_id: stable pair of canonical IDs
scanner_evidence: command, threshold, title_score, body_score, scan date
classification: informational | review-needed | approved-consolidation
rationale: why the records are or are not the same historical work
evidence: identity, status, dependency, and implementation/report references
approval: reviewer and decision reference (required for approved-consolidation)
disposition: retain | cross-link | successor | retire | relink
changes: file paths, canonical IDs, and commit(s), or "none"
exact_validation: result of ID and structured-reference validation
```

`review-needed` remains an auditable pending outcome: it does not authorize a
change and must say what evidence or approval is still missing. `informational`
also closes the review only with its rationale. `approved-consolidation` is
complete only after its declared exact-validation result is recorded.

## Non-regression rule

Do not modify `.nightshift/check_followup_spec.py`, exact-ID uniqueness rules,
or structured-reference validation merely to reduce semantic findings. The
semantic scanner may remain noisy by design; cleanup is a separately approved,
evidence-backed historical decision.
