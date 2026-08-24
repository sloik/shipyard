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

Payloads contain controlled enums, semantic versions, SHA-256 digests,
timestamps, stable IDs, and `{name, sha256, size}` relative artifact references.
Raw prompts, output, logs, commands, environment, credentials, URLs, absolute
paths, endpoints, and application data remain in the ignored/private namespace.

The skill maintainer keeps both official paths mechanically bound to these five
calls. The canonical `Skills/nightshift/SKILL.md` source is manifest-hashed with
the kit, and the serialized release coordinator alone verifies and delivers its
exact bytes to the external active path. A repository worker or parent never
patches that delivery outside the whole-kit handoff.
