Load when: you run `/nightshift unblock <spec-id>` (default unblock, `--to-done`, `--from-rung`, `--dry-run`) on a spec that is currently `blocked`.
Covers: the controller-backed unblock protocol, the drive-to-done rung ladder and the resilience ladder, with every command the parent runs.
Not here: running a ready spec (`/nightshift run`), moving a status by hand (`/nightshift board`).
Requires: `unblock_spec.py`, `unblock_ladder.py`, `ac_review.py` in the install and retained evidence for the blocked spec.

# Unblock guide

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
`blocked -> ready`. A new ordinary kickoff (or `unblock_spec.py resume`) may begin only after that transition.

`--root` may be the project root or the install directory (`.nightshift`). A project root is resolved to `<root>/.nightshift`; a directory that has `specs/` itself (this repository's `canonical/` next to `.nightshift/`) is used as is. Events, attempts and locks are kept under the install directory; a directory with neither layout is refused with `NS-UNBLOCK-ROOT-NOT-INSTALL` before anything is written.

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
