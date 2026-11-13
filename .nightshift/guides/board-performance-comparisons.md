Load when: explicitly commissioning finite graph observations or comparing retained arms.
Covers: capture bounds, portable artifacts, matching, advisory arithmetic and limitations.
Not here: optimizing graph loads, scheduling, full suites, release or fleet rollout.
Requires: Python; capture also requires Playwright/Chromium and a selected local board/export.

# Qualified graph performance comparisons

`board_performance_snapshot.py` is opt-in. Nothing invokes it at board startup,
spec closure or release. One command implementation accepts parameters; do not
regenerate scripts or run until green. Commission each additional arm explicitly.

```sh
python3 .nightshift/board_performance_snapshot.py capture --url http://127.0.0.1:7853 \
  --source-root .nightshift --scenario requested --output baseline.json
python3 .nightshift/board_performance_snapshot.py capture --export snapshot.html \
  --source-root .nightshift --scenario no-request --output exported.json
python3 .nightshift/board_performance_snapshot.py compare \
  --baseline baseline.json --candidate candidate.json --output comparison.json
```

In canonical use the script directly and `--source-root .`. Source root must be
the board's actual checkout/install with Git ancestry available. The command hashes
`board.py`, `dependency_graph_view.py`, and itself in that fixed order, records Git
HEAD and hashes the served inline scripts. Revision identifies ancestry; the byte
digests identify current bytes, including uncommitted work. Operators must bind the
selected running board to its source root; the tool cannot authenticate a process's
checkout remotely. Do not call an old server a new source revision.

`--controlled-fixture` labels controlled inputs separately from genuine live data.
`--all-dependencies` selects all arrows instead of the reduced view. A fresh browser
context fixes initial filters/grouping and viewport (1200×900). Requested scenarios
request fresh graph/spec data on every opening; no-request scenarios reuse data
on warm openings. The first opening still fetches missing live data. Exports have
their own target kind and always use the static fetch shim, with no telemetry POST.
A controlled export remains labelled controlled within the export target kind.

Each capture attempts one first opening and five warm openings, once each. Each
attempt has at most 30 seconds, including navigation and waiting for the existing
first-draw/next-frame boundary. An async timeout bounds the whole attempt,
including evaluator calls without their own timeout. Invocation is bounded by 240 seconds including
browser shutdown; an external watchdog reserves three seconds for termination and
kills only its owned worker process group. Errors/timeouts remain attempts; no
replacement samples or retries. A fresh invocation requires commissioning.
Atomic checkpoints retain completed attempts if interrupted. An invocation-limit
termination adds an explicit timeout for the interrupted attempt when space remains.
Exit 0 means six visible successful observations; 1 means incomplete/unqualified
observations; 2 means refused/invalid command or unavailable durable evidence.
Capture failure never changes ordinary board rendering or lifecycle.

Artifacts use schema/boundary version 1. They contain target kind; source revision,
source-input/served-code digests; corpus/dependency digests and counts; numeric
browser/Playwright/Python versions; coarse OS/architecture and viewport; controlled
scenario flags; first/warm sequence; actual requested mode; visibility; phase/total
milliseconds; visible nodes/edges; and controlled outcome/partial reason codes.
Only allowlisted fields, finite nonnegative timings and valid digests are accepted.
The full artifact digest binds every identity and sample. Source input digests are
also bound together. Digests detect modifications, not malicious re-authoring.
No spec IDs/prose, raw source, URL/path/command, username, host, environment value
or error payload is retained in portable artifacts. Sources stay at origin; no
raw-source snapshot is copied. Keep output on storage you control.

Comparison is offline and imports/launches no browser, capture, model or formal
runner. Select immutable baseline/candidate files explicitly; output is exclusive
and cannot replace either input. Repeating comparison never captures or rebaselines.
Invalid/tampered or missing identities produce controlled incomparable reasons.
Target kind, corpus/dependencies, runtime/platform/viewport, scenario and boundary
must match exactly. Changed source identity is expected and displayed separately.
Fixture/live/export and requested/no-request strata never pool. Corpus drift within
a capture remains a failed attempt. Failed/hidden attempts cannot fill success slots.

First-opening values are separate from warm values. Five visible warm successes
per arm qualify count, median, nearest-rank p95 (`ceil(.95*n)`), min/max and median
deltas. Fewer yield insufficient evidence, with explicit outcome/hidden/unattempted
denominators. A suspected-degradation advisory requires both **more than 100ms**
and **more than 20%** median increase; equality does not warn. Baseline zero makes
percentage unavailable. Thus 800→1500ms warns (+700ms/+87.5%) below the separate
2,000ms budget. Individual first/warm values and qualified p95 above 2,000ms are
reported separately. Errors/cancellations/timeouts never enter successful percentiles.

These are finite, variable observations: neither statistical nor causal proof of a
regression and never a flaky wall-clock CI gate. Existing deterministic instrumentation
and request-work gates remain unchanged. SPEC-NS-KIT-200's retained slow fetch is a
slow observation of unknown cause, not a retrospectively manufactured baseline.
