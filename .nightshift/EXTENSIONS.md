# Observational extension checkpoints

Extensions consume five already-authoritative facts and never participate in
lifecycle, selection, prompting, verification, recovery, merge, cleanup,
integration queues, or core-event publication. The official `$nightshift run`
and `$nightshift kickoff` routes call the standalone `extension_checkpoint.sh`
at the real checkpoint, passing the stable run ID, spec ID, run kind, event,
and outcome on every invocation. The launcher self-resolves the installed
project/private/user roots and a PyYAML-capable interpreter; its shell state
never needs to survive between tool calls. `nightshift-dag.py dispatch-spec`
does not synthesize these facts.

The order is `run.started`, then each applicable `work.completed`,
`verification.requested`, and `verification.completed` fact, then
`run.completed`. Sequences are contiguous across the facts actually published;
`--sequence auto` derives the next value from the fsynced spool so an early
blocked path does not fabricate checkpoints merely to fill sequence numbers. The
installed helper receives the project root, ignored/private extension root,
privately configured user-manifest root, stable run ID, sequence, event,
controlled payload JSON, parsed extensions config, and (only when references
exist) an ignored private artifact root. It verifies and atomically materializes
content-addressed references into the private run namespace before it publishes
the stable event. It appends and fsyncs the
stable event before creating a job. A separate supervisor drains jobs. An
append/fsync failure launches nothing; optional extension failures cannot change
the ordinary run result.

The low-level CLI receives payload/config through ignored private files
(`--payload-file` and `--config-file`). Official run and kickoff routes instead
use `--official-config config.yaml` plus controlled `--run-kind`, `--spec-id`,
`--outcome`, event, and sequence fields. The helper loads only `extensions` from
the multi-document public config and derives the closed payload itself, so raw
JSON never appears in a process command line.

The project-private default spool is `.nightshift/.extension-private/`, which is
ignored by the managed `.nightshift/.gitignore`. A privately supplied
`NIGHTSHIFT_USER_EXTENSION_ROOT` enables user-global discovery; when absent the
official route uses a disabled empty subdirectory below that private spool.
Approved artifact references use an optional private
`NIGHTSHIFT_EXTENSION_ARTIFACT_ROOT`; the helper verifies and materializes them
before publishing the stable event.

The standalone launcher always exits zero because this channel is
observational. Missing arguments, an unavailable interpreter, or an unexpected
helper exit produce only a controlled private
`.extension-private/checkpoint-diagnostics.jsonl` record.

## Reusable package lifecycle

`extension_package.py` defines the portable `.nsext` archive. Its canonical ZIP
bytes are deterministic and contain the SPEC-230 manifest, payload, input/output
schemas, documentation, tests, license, provenance, and a complete per-file
SHA-256 inventory. Inspection is data-only: it neither extracts nor imports the
entry point, and rejects missing, extra, changed, traversing, symlinked, or
executable archive members.

`ExtensionPackageManager` owns explicit `project` and `user` installation scopes.
Every install, verify, update, rollback, and remove starts as a sealed dry-run plan.
Apply rechecks both package bytes and ledger state, stages a complete verified tree,
then atomically changes the installation ledger. The ledger is activation authority,
so an interruption cannot expose mixed package bytes. Duplicate IDs and omitted or
ambiguous scope never resolve through search order.

Updates require a compatible protocol range, strictly increasing version, integrity
match, and a declared migration from the active version. Added events or capabilities
disable existing project approvals until each consumer explicitly re-approves the new
exact version. Deterministic list, inspect, and status views expose only portable IDs,
versions, scopes, compatibility, declared authority, consumers, and controlled health.

Catalogue documents are informational data. Their optional fields must be declared by
the catalogue schema; reading or removing an entry has no installation, enablement,
grant, trust, or runtime effect. Production extension packages remain outside the
Nightshift kit and require their own specs, provenance, tests, dependencies, and
release cadence.

When a project explicitly enrolls private observability and supplies a validated
experiment observer, package administration emits closed private observations at
inspection, plan, apply/rejection/interruption, verification, approval, rollback,
removal, and preservation boundaries. Installed-package admission/refusal and
terminal job state are correlated through package, plan, approval, admission, run,
and job digests. These observations belong to the SPEC-238 private experiment
protocol; they do not add a sixth event to SPEC-230, grant execution authority, or
make package success depend on telemetry. A missing capture is an explicit
instrumentation gap. The controlled `interrupt_after_stage` seam is accepted only
by the direct administrative API against an operator-selected isolated root; it is
not configurable through ordinary project YAML.

Payloads contain controlled enums, semantic versions, SHA-256 digests,
timestamps, stable IDs, and `{name, sha256, size}` relative artifact references.
Raw prompts, output, logs, commands, environment, credentials, URLs, absolute
paths, endpoints, and application data remain in the ignored/private namespace.

The skill maintainer keeps both official paths mechanically bound to these five
calls. The canonical `Skills/nightshift/SKILL.md` source is manifest-hashed with
the kit, and the serialized release coordinator alone verifies and delivers its
exact bytes to the external active path. A repository worker or parent never
patches that delivery outside the whole-kit handoff.

## Harness write-scope hook matrix (SPEC-300-004)

Separately from the extension checkpoints above: SPEC-300's write-scope lock
has a harness-specific earliest layer, `hooks/write-scope-hook.sh`, a Claude
Code `PreToolUse` hook that classifies a write's destination against the
active spec's declared `scope.write` (via `scope_guard.py`, SPEC-300-001)
before the tool call runs, and denies it with the correct location named.

| Harness | Pre-write interception | Fallback enforcement |
| --- | --- | --- |
| Claude Code | `hooks/write-scope-hook.sh` (`PreToolUse`), installed per-project via `hooks/install-write-scope-hook.sh` — but see the note below: its spec-scoped rules are presently unreachable for a harness-launched worker | git pre-commit guard (SPEC-300-003), evidence gate (SPEC-300-002) |
| Codex | none today | git pre-commit guard (SPEC-300-003), evidence gate (SPEC-300-002) |
| Hermes | none today | git pre-commit guard (SPEC-300-003), evidence gate (SPEC-300-002) |

The hook is strictly an earliest-detection optimization, never the only
enforcement layer: a Codex or Hermes run still has its scope enforced by the
git guard at commit time and the evidence gate at verification time, and the
terminal lifecycle commit's `Nightshift-Scope-Check:` trailer (SPEC-300 R11)
records which layer actually resolved a violation, independent of which
harness ran the worker.

**Claude Code's own hook is not fully reachable for a harness-launched
worker either (SPEC-300-004-001).** The row above is more precise than "no
hook at all" (Codex/Hermes) but less capable than it looks: the hook's
*spec-scoped* `write`/`deny`/`read` rules depend on `scope_guard.py`'s
`active_spec()` resolving the active spec from either
`NIGHTSHIFT_ACTIVE_SPEC` or the branch name, and for a harness-launched
(`isolation: "worktree"`) kickoff worker, **neither input is available at
the `PreToolUse` layer**: the parent's Agent-launch tool has no parameter to
set an environment variable for the launched subagent's session (checked
directly against the launch tool's own schema — `description`, `isolation`,
`mode`, `model`, `name`, `prompt`, `subagent_type`, `team_name`; no `env`
field), a worker's own Bash-tool `export` does not persist across separate
Bash calls (confirmed empirically by SPEC-301), and the harness assigns its
own `worktree-agent-<hex>` branch name that carries no spec ID for
`scope_guard.py` to parse. So `active_spec()` falls back to
`no_active_spec` (allow) at this layer for every real harness-launched
kickoff, and only the hook's two **universal** rules (spec-home guard,
malformed-target guard — neither depends on `active_spec()`) actually fire.
The git pre-commit guard (via the inline `NIGHTSHIFT_ACTIVE_SPEC={spec-id}`
commit-prefix convention, which the guard reads from the `git commit`
subprocess's own environment) and the evidence gate remain the two working
backstops for spec-scoped enforcement in this case — the same fallback
Codex/Hermes rely on for everything. This is a known, accepted gap (no fix
available at the harness-launch layer today), not a silent one; see
`canonical/Skills/nightshift/SKILL.md` Step 5 for the full evidence trail.
