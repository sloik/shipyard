Load when: you ask "may I do X?", "is this spec ready?" or "which rule blocked me?", or you need to find where a Nightshift rule is written.
Covers: one row per rule family (digest, authoritative file and anchor, checking tool) and `board_ctl.py rules check <id>`, the read-only pre-flight over every machine-checkable rule.
Not here: the rule text itself (open the source), writing a spec (`/nightshift spec`), moving a status (`/nightshift board`), install soundness (`/nightshift validate`).
Requires: `.nightshift/board_ctl.py` and the kit's `validate_specs.py`, `scope_guard.py`, `spec_frontmatter.py`; python3 with PyYAML.

# Rules guide

Each digest below is a pointer, never a replacement: **when a digest and its source differ, the
source wins**, and the source is the file at the anchor in column 3. Paths are install-relative
(`.nightshift/...`); in the kit repository the same files sit under `canonical/`. This guide adds
no rule and changes none.

## 1. Where each rule lives

`Validator families` lists the `validate_specs.py` finding families (fnmatch globs over
`classify_finding_family`) that `rules check` reports under that row; `-` means none.

| Rule family | Digest | Authoritative source | Checked by | Validator families |
| --- | --- | --- | --- | --- |
| `spec-format` | Frontmatter parses, required fields and the current `template_version` are present, and `type:` is one value of the Spec Types registry (SPEC-GUIDE tables; `vocabulary-registry.yaml` carries the same set, a test pins it); an unregistered type is an error, except an audit warning on `done`, `superseded`, `retired` and `blocked` specs. | `SPEC-GUIDE.md#spec-types` | `validate_specs.py`; `rules check` (`spec-format/type`, the same registry loader; the validator's `unregistered-type` finding is shown there, not twice) | `missing-*`, `invalid-status-value`, `legacy-planning-status`, `attachments-*`, `followup-shape`, `*template-token`, `path-traversal-token`, `absolute-path-leak`, `block-reason-as-title`, `transfer-refusal-shape`, `done-spec-unchecked-checkbox`, `unregistered-type`, `unclassified-finding`, `spec-id-*`, `registry-code-invalid`, `staged-configuration-invalid`, `deploy-environment`, `board-column-defaults`, `resolved-blocker-field-residual`, `artifact-*`, `untracked-*` |
| `state-rationale` | A new spec carries a `## State rationale` fenced YAML block whose status, reason, `reconsider_when` and record agree with its stored status. | `SPEC-GUIDE.md#state-rationale-why-a-spec-has-its-current-status-spec-357` | `validate_specs.py` | `state_rationale_*` |
| `lifecycle` | Status moves only along `lifecycle.LIFECYCLE_TRANSITIONS`; a judgment transition needs a reason; draft/planned to ready is refused while a `promotion_gap` is unresolved; `after:` and `requires_specs` must name real specs (the validator reports an unknown id: error on planned/ready/in_progress, WARNING on draft or a closed spec); promotion also needs `lifecycle.intrinsic_readiness` PASS, or REVIEW with `--readiness-reviewed <rationale>`. A project `spec_metadata` policy (SPEC-419) is part of that readiness: a missing, malformed or disallowed `version:` is an error on planned/ready/in_progress and a WARNING on a draft or closed spec. | `SPEC-GUIDE.md#draft-promotion-gaps-spec-210` | `rules check` (`lifecycle/promotion` via `promotion_transition_error` and `spec_promotion.readiness_refusal`, `lifecycle/dependencies`); `board_ctl.py transition` | `promotion-gap-*`, `status-sync-mismatch`, `unknown-dependency`, `spec-metadata-*` |
| `scope` | `scope.write` globs bound where the run may write; kit evidence paths are implicit; scope is read from `main`; `deny` wins. | `SPEC-GUIDE.md#write-scope` | `scope_guard.py check` through `rules check --diff` (`scope/diff`); the write-scope hooks at write time; `validate_specs.py` for the declaration's shape | - |
| `release-handoff` | A spec declares `release_handoff` as `required` or `exempt` with a reason; `required` needs a valid artifact in `release-handoffs/`. | `ORCHESTRATOR.md#versioned-release-handoff-spec-189` | `validate_specs.py`, only where `release-manifest.json` sits next to it (kit repository); `skip` in an install | `release-handoff-*`, `*release*handoff*` |
| `nfr` | Every active NFR that matches the spec is bound in `nfrs:` or waived in `nfr_waivers:`. | `SPEC-GUIDE.md#creating-an-nfr-spec` | `validate_specs.py`; `audit_nfr.py --check-all` | `nfr-*`, `scope-tags-shape` |
| `real-use-evidence` | A feature declares `real_use_evidence`; a `required_before_done` spec needs every ticked Live Execution item to cite exactly one evidence file (paragraph "Real-use evidence (SPEC-238)" at the top of the guide). | `SPEC-GUIDE.md#interactive-spec-creation-guide` | `validate_specs.py` | `real-use-evidence`, `real-use-evidence-*`, `live-item-evidence-*` |
| `amendments` | A changed acceptance criterion needs an `## AC Amendments` row; widened scope needs a `## Scope Amendments` row; approvers and dates follow the tables. | `SPEC-GUIDE.md#ac-amendments` | `validate_specs.py` (`ac_amendment_undocumented`, scope amendment rows); `scope_guard.py` | `ac-amendment-*` |
| `commit-hooks` | A commit subject is `[SPEC-ID] type: subject` (merges and reverts exempt); the secret/PII scan and the write-scope guard run at commit. | `GIT.md#commit-format` | `hooks/commit-msg` and `hooks/pre-commit` when you commit; not machine-checked by `rules check` | - |
| `merge` | The coordinator alone merges, one candidate at a time; `main` is re-validated after each merge and must stay green. | `GIT.md#merge-and-post-merge-validation` | not machine-checked | - |
| `no-test-loosening` | A test is never disabled, skipped or narrowed to go green; a criterion changes only through an AC Amendments row with an independent review. | `SPEC-GUIDE.md#ac-amendments` | not machine-checked (only the amendment row is, under `amendments`) | - |
| `worktree-isolation` | Concurrent workers each own one worktree and branch, never edit the shared checkout and never merge. | `GIT.md#branches-and-worktrees` | `hooks/protect-primary-branch.sh` and the write-scope hooks at write time; not machine-checked by `rules check` | - |

## 2. `board_ctl.py rules check <id> [--diff <rev-range>] [--main BRANCH] [--json]`

`python3 .nightshift/board_ctl.py rules check SPEC-ID` runs every machine-checkable rule above
against one spec and prints one line per check: `rule | pass/fail/skip | reason | source`.
`--specs-dir` and `--project` aim it at another spec set. Exit 0 when nothing failed, 5 when
any line is `fail`, 1 when the spec id is unknown.

| Line | What runs | `skip` when |
| --- | --- | --- |
| `spec-format`, `state-rationale`, `scope`, `release-handoff`, `nfr`, `real-use-evidence`, `amendments` | `validate_specs.py` on that file; each finding goes to the row its family or text names. A `WARNING:` makes the line `pass` with a count. | `release-handoff` only: no `release-manifest.json` next to the kit |
| `spec-format/type` | the `type:` value against the Spec Types tables of `SPEC-GUIDE.md` | `SPEC-GUIDE.md` is not installed |
| `lifecycle/dependencies` | `after:` and `requires_specs` resolved exactly, with each target's status in the reason | never |
| `lifecycle/promotion` | `spec_frontmatter.promotion_transition_error(spec, "ready")` and `spec_promotion.readiness_refusal` called directly | the effective status is not draft or planned |
| `scope/diff` | `git diff --name-only <rev-range>` classified by `scope_guard.py check --spec ID`, scope read from `--main` (default `main`) | no `--diff` |

- **Read-only.** It never constructs `StatusStore`; the effective status comes from the same
  read-only store reader as `list` and `show`. It writes nothing to the working tree, the index,
  bytecode or the store file; subprocesses run with `-B` and `GIT_OPTIONAL_LOCKS=0`. The one
  trace is SQLite's: a read-only open of the WAL store may create empty `-wal` and `-shm`
  files beside it (no store content, the store's bytes are unchanged).
- **Scope comes from `main`.** `--diff` judges paths against the `scope:` committed on the
  `--main` branch, never the working copy; a spec not yet committed there gets the project-root
  default, which allows every path.
- **It is a pre-flight, not the gate.** `lifecycle/promotion` mirrors what `spec_promotion.py`
  checks first; the real promotion can still be refused by a later gate. `skip` is not `pass`:
  read the reason.
- **Known gaps.** `rules check`'s dependency line resolves an unqualified `after:` id through the
  registry as well as locally, where the validator looks only in the specs directory.
  The kit that runs the command decides the handoff check: `--specs-dir` or `--project` aimed at
  another project's specs is checked against the running kit's `release-handoffs/`. A new `validate_specs.py` finding family must
  get a row here (`tests/test_board_ctl_rules.py` fails until it has one).
