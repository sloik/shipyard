Load when: you must find, list, show or search specs, move a spec's status, or say why a board card did not move.
Covers: launching the board and finding its port, the status authority model, every board HTTP route with curl recipes, which CLI answers which question.
Not here: writing a spec (`/nightshift spec`), the kickoff procedure, validator rules (`/nightshift validate`).
Requires: an installed `.nightshift/` with `board.py`, `status_store.py`, `lifecycle.py`; a running board for the curl recipes.

# Board and API guide

Source of truth is the code: `board.py` (routes, write gate `SpecCache._update_status_locked`),
`status_store.py` (`StatusStore.transition_commit_backed`), `lifecycle.py`, and, in the
kit repository, `nightshift-master.py` (Control). Paths below are install-relative
(`.nightshift/...`); in the kit repository the same files sit under `canonical/`.

## 1. Launch, port, runtime

- **Control** (`nightshift-master.py`, port 7799) lists projects from every
  `projects-registry.json` it finds. `POST /api/projects/{name}/start` runs
  `board.py --port <registry port>` detached (log: `board.restart.log` next to
  `board.py`) and returns `{"status": "starting", ...}`. It writes **no `board.pid`**.
  `POST /api/projects/{name}/stop` finds the listener on the port and signals it.
- **`board.sh`** (`.nightshift/board.sh [--no-open] [--port N] [extra board.py args]`): starts
  `board.py --open` in the background, probes `GET /api/health`, then writes `board.pid`
  (next to `board.sh`; `--no-open` skips the browser). Log: `board.restart.log`. `board.sh stop` stops the PID in
  `board.pid`, refusing a PID that is not this board.
  Python runtime: `$NIGHTSHIFT_BOARD_PYTHON`, else `.nightshift/.board-venv/bin/python`,
  else `python3`; it must import `fastapi`, `uvicorn`, `yaml` or the script exits 1.
- **Port.** Explicit `--port` always wins. Otherwise `board.py` uses
  `7800 + sum(ord(c) for c in NAME) % 200` where `NAME` is the project-root directory
  name, upper-cased, leading dots stripped. `python3 .nightshift/board.py --print-port`
  prints it without starting. `board.sh` asks `board.py --print-port` for its probe
  (BUG-342 fixed the old mismatch where it hashed its own directory name). Control
  does **not** use the hash: it passes the registry's `port`, which can differ
  (a board started by `board.sh` without `--port` may sit on another port than the
  registry lists). Trust whatever answers `GET /api/health`.
- **Find the port:**
  `python3 -c "import json;[print(p['name'],p['port']) for p in json.load(open('.nightshift/projects-registry.json'))['projects']]"`
- The board binds `127.0.0.1` only. Every recipe below uses `B=http://127.0.0.1:$PORT`.
- `board.py --summary` prints reconciled frontmatter as JSON and exits (no server);
  `--export PATH.html` writes a static snapshot.

## 2. Status authority model

A spec's status lives in two places that can disagree: the `status:` frontmatter line
and the **durable status store** (SQLite, `StatusStore`; one file per git repository in
the git common directory, `nightshift-status.db`, shared by all worktrees; a project
that is a strict subdirectory of the checkout gets a namespaced path).

- **The board shows the effective status**, not the frontmatter. For each spec it reads
  the newest store checkpoint. If that checkpoint is **`done` or `blocked` (terminal),
  it is authoritative and immutable via frontmatter**: editing `status:` by hand does not
  move the card. For any other checkpoint, a frontmatter status whose file mtime is at or
  after the checkpoint's time overwrites the store (a `frontmatter-reconcile`
  checkpoint) and the card follows the file.
- **Why a hand edit "did not work":** the store says `blocked` or `done`, so the file is
  behind it. Check with `GET /api/status-sync` (section 4): `mismatches` lists
  `{id, frontmatter, durable, effective, reason, ...}` with reason
  `durable-terminal-ahead-of-file` (store is terminal; file lags) or
  `durable-stale-behind-file` (non-terminal store row the repair refused, for example
  a different spec path or an older file). `GET /api/health` carries the count as
  `status_sync_mismatches`. The fix is a real transition (below), not another edit.
- **Write paths** (all of them write the store checkpoint, then a `status-transition`
  artifact, then the frontmatter; **none of them commits to git**, so commit the spec and its
  `reports/<ID>/artifacts/` files yourself, with explicit paths; the store DB is not in git):

| Path | Use it for | Notes |
| --- | --- | --- |
| `PUT /api/spec/{id}/status` (board) | any move while a board is running; the only path that holds the board's cache lock | runs the full gate below; source `board`; body `{status, reason?, reconsider_when?, state_evidence?}` |
| `StatusStore.transition_commit_backed(path, status, run_id=..., reason=...)` | scripts and coordinators with no board, in Python | judgment transition without reason raises `TransitionReasonRequired`; does **not** run the board's NFR-family or release-handoff gates; an unresolved promotion gap is refused only at the frontmatter write, after the checkpoint (`LifecyclePersistenceError`) |
| `python3 .nightshift/spec_promotion.py <spec> --run-id R --reason T` | `draft`/`planned` to `ready` (or `--target-status planned`), resolving a promotion gap | wraps `transition_commit_backed`, runs the promotion gate, records decision/context artifacts |
| `python3 .nightshift/spec_artifacts.py record-transition <spec> --from A --to B --run-id R --reason T [--reconsider-when W]` | record the artifact and rationale for a transition already applied to the frontmatter | does not move the store; `author-decision` records a rationale without a transition |

  A write that bypasses the store (an uncommitted frontmatter edit) is only honoured
  while the store row is non-terminal.
- **The board's write gate** (`PUT`, in this order; first failure refuses and records a
  *transfer refusal*, see below): the spec must exist (404); `status` must be one of
  `planned draft ready in_progress blocked active done superseded retired` (NFR-family
  specs, id `NFR-*` or type `nfr`, may only use `active`/`retired`); a `draft` to
  `ready` move must pass the promotion-gap check (`promotion_transition_error`); a move
  to `done` must pass the **release-handoff gate**; a **judgment transition** must carry
  a non-empty `reason`. Refusals are 400 with the message in `detail`.
- **Lifecycle edges.** `lifecycle.LIFECYCLE_TRANSITIONS` is the intended map:
  `draft` to planned, ready, blocked, superseded; `planned` to ready, blocked,
  superseded; `ready` to planned, in_progress, blocked, superseded; `in_progress` to
  ready, done, blocked; `blocked` to draft, planned, ready, superseded; `done` and
  `superseded` have no outgoing edge. It is consulted by `unblock_spec.py` and
  `release_handoff.py`; **neither the board `PUT` nor `transition_commit_backed`
  enforces it**, so the gate above is what actually stops a move.
- **Judgment-transition reason rule.** Among the seven lifecycle statuses (`draft planned
  ready in_progress blocked done superseded`), every pair needs a non-empty prose
  `reason` except the mechanical `ready` to `in_progress`, `in_progress` to `done`,
  `blocked` to `ready` (`lifecycle.is_judgment_transition`); those get a synthesized
  reason. Statuses outside the seven (`active`, `retired`) never need one.
- **`reconsider_when` and `## State rationale`.** Every transition upserts the spec's
  `## State rationale` section (YAML block: status, reason, `reconsider_when`,
  evidence, `record` pointing at the new artifact). `reconsider_when` (the concrete
  condition or date to revisit) is required for targets `draft`, `planned`, `blocked`.
  If the `PUT` omits it for those targets, the artifact is still written but the section
  is left untouched and reads as stale. `state_evidence` is a list of typed locators
  such as `{"kind": "file", "path": "..."}`. Also fills `GET /api/spec/{id}` field
  `run_state_explanation`.
- **`done` gate.** A move to `done` validates the spec's `release_handoff:` declaration
  against `release-manifest.json` **only when that manifest sits next to `board.py`**,
  which is true in the kit repository and false on fleet installs (BUG-337: the manifest
  is never distributed). With no manifest the check is skipped, not failed.
- **Transfer-refusal record.** Each gate refusal is written into the spec's frontmatter
  as `transfer_refusal: <message>` (sanitized, best effort) so the card shows why a drag
  failed; the next successful `PUT` clears it. `POST` and `DELETE`
  `/api/spec/{id}/transfer-refusal` set and dismiss it from the UI. It is a frontmatter
  edit, so it appears in `git status`.
- **Single writer.** While a board runs, send status writes through its `PUT`. The board
  caches the corpus (a `PUT` updates its cache; `POST /api/refresh` rebuilds it after
  out-of-band edits).

## 3. Endpoint table

Legend: R = read-only, W = writes spec/project files or the store, S = side effect
outside the corpus (opens apps, writes UI state). `{id}` is exact, case-sensitive.
Rows marked **UI-only** exist for the board page; agents should not call them.

| Method | Path | Purpose | Kind |
| --- | --- | --- | --- |
| GET | `/` | the board HTML page | R |
| GET | `/api/specs` | every spec's frontmatter plus `_title`, `_problem`, `_mtime`, `run_state_summary`; `status` is the effective status | R |
| GET | `/api/spec/{spec_id}` | one spec: `frontmatter`, `body_md`, `title`, `artifacts`, `artifact_index_state`, `run_state_explanation` | R |
| GET | `/api/spec/{spec_id}/artifact` | preview one indexed artifact (`?path=` exact index key); errors are `{error:{code,message}}` | R |
| PUT | `/api/spec/{spec_id}/status` | move a spec (body above); `{"ok": true}` | W |
| GET | `/api/spec/{spec_id}/status/history` | store checkpoints, newest first: `{spec_id, history[]}` | R |
| POST | `/api/spec/{spec_id}/transfer-refusal` | record a refusal text (`{reason}`); UI-only | W |
| DELETE | `/api/spec/{spec_id}/transfer-refusal` | dismiss a refusal; UI-only | W |
| POST | `/api/spec/{spec_id}/deployment-authorization` | owner approve/reject for a held deployment candidate (`{action, actor, sha, environment}`); writes a decision artifact | W |
| GET | `/api/search` | `?q=` case-insensitive substring over id, title and body; `[{id,title,status,excerpt}]` | R |
| GET | `/api/graph` | dependency graph `{nodes, edges, parent_edges}` | R |
| POST | `/api/refresh` | drop the cache and re-read all specs; `{count}` | S |
| GET | `/api/status-sync` | spec files vs durable store: `{checked, mismatches[]}` | R |
| GET | `/api/health` | `{status, db_reachable, spec_count, status_sync_mismatches, open_fds, ...}`; never 5xx | R |
| GET | `/api/statuses` | the status columns and their meaning | R |
| GET | `/api/spec-metadata` | the project's `spec_metadata` policy `{fields: {version: {required, allowed_values}}, errors[]}` (SPEC-419); feeds the VERSION filter | R |
| GET | `/api/vocabulary` | the versioned concept registry | R |
| GET | `/api/projects-registry` | `projects-registry.json` next to the specs dir, or `{projects: []}` | R |
| GET | `/api/external-spec/{port}/{spec_id}` | proxy: another local board's status for a spec (ports 7800-7999) | R |
| GET | `/api/worktree-status` | specs whose status differs in another git worktree | R |
| GET | `/api/reports` | every Markdown report in the project, newest first | R |
| GET | `/api/report/{filename}` | one report's text by project-relative path | R |
| GET | `/api/loop-observability` | loop-health metrics from run history | R |
| GET | `/api/experiments` | sanitized experiment projection | R |
| GET | `/api/performance` | aggregate timings of this board process | R |
| POST | `/api/performance/client` | browser timing sink; UI-only | S |
| POST | `/api/reports/read` | mark a report read (`board-reads.json`); UI-only | S |
| POST | `/api/reports/read-all` | mark every report read; UI-only | S |
| POST | `/api/open/spec/{spec_id}` | opens the spec in an editor on the host; UI-only | S |
| POST | `/api/open/spec/{spec_id}/finder` | opens Finder; UI-only | S |
| POST | `/api/open/spec/{spec_id}/terminal` | opens Terminal; UI-only | S |
| POST | `/api/open/report/{filename}` | opens a report in an editor; UI-only | S |
| GET | `/api/prompts` | prompt-snippet list; UI-only | R |
| GET | `/api/prompts/{scope}/{id}` | one snippet; UI-only | R |
| POST | `/api/prompts/{scope}` | create a snippet; UI-only | W |
| PUT | `/api/prompts/{scope}/{id}` | edit a snippet; UI-only | W |
| DELETE | `/api/prompts/{scope}/{id}` | delete a snippet; UI-only | W |
| POST | `/api/prompts/{scope}/{id}/render` | render a snippet with variables; UI-only | R |

### Graph view: reduced and full dependency arrows

The live and exported graph draw a **reduced** projection by default: a declared prerequisite arrow is hidden only when another directed path between the same two specs remains among the arrows currently displayed (gate -> planning -> child hides gate -> child). Reachability is unchanged. The legend's **Show all dependencies** switch (also in the inspector's "not drawn" row) draws every declared arrow; the note under it counts the hidden ones, and the spec inspector lists each omitted arrow with its alternate path. The reduction is recomputed whenever a status/type filter or the data changes, so hiding the middle spec brings the gate -> child arrow back; dashed parent/grouping lines never count as a path. Self-loops, arrows to missing specs and anything touching a cycle are never hidden; external prerequisites are keyed `project::id`. It is view-only: spec files, `after:`, `/api/graph`, `board_ctl.py deps`, exports, validation and scheduling still carry every declared edge, and redundant `after:` entries are not an error. Reference implementation: `dependency_graph_view.py` (`reduce_dependency_edges`); `board.py` mirrors it in `reduceDependencyEdges`, and a test runs both on the same graphs.

### Recipes

Set the base once: `B=http://127.0.0.1:$PORT` (port from section 1).

```sh
# health and divergence check
curl -s $B/api/health
curl -s $B/api/status-sync

# list: all specs, or filter by effective status (blocked, ready, in_progress, ...)
curl -s $B/api/specs
curl -s $B/api/specs | python3 -c "import json,sys;[print(s['id'],s['status'],s.get('_title','')) for s in json.load(sys.stdin) if s['status']=='blocked']"

# show one spec (frontmatter, body_md, artifacts, run_state_explanation)
curl -s $B/api/spec/SPEC-393

# search id, title and body (URL-encode the query)
curl -s "$B/api/search?q=status%20transition"

# status history, newest checkpoint first
curl -s $B/api/spec/SPEC-393/status/history

# dependency graph
curl -s $B/api/graph

# one artifact: take an exact `path` from the spec's `artifacts` list
curl -s "$B/api/spec/SPEC-393/artifact?path=artifacts/<file-from-index>.json"
```

Write recipes (never aim these at a board whose store you do not own):

```sh
# re-read every spec file after out-of-band edits
curl -s -X POST $B/api/refresh

# mechanical move (no reason needed)
curl -s -X PUT $B/api/spec/SPEC-1/status -H 'Content-Type: application/json' \
  -d '{"status":"in_progress"}'

# judgment move: reason required; reconsider_when required for draft/planned/blocked
curl -s -X PUT $B/api/spec/SPEC-1/status -H 'Content-Type: application/json' \
  -d '{"status":"blocked","reason":"waiting on owner decision","reconsider_when":"owner answers Q1"}'
```

Errors: 400 `{"detail": "<refusal>"}` (invalid status, gate, missing reason), 404
`spec not found`, 500 other. The change is on disk, uncommitted: the frontmatter, the
`## State rationale` block and a new `reports/<ID>/artifacts/*-status-transition-*.json`.

## 4. Tool map

| Question | Command |
| --- | --- |
| Which specs exist, their status? | `GET /api/specs`, or `python3 .nightshift/board.py --summary` with no server |
| Find specs mentioning X | `GET /api/search?q=X` |
| What can run next / the graph in text? | `python3 .nightshift/nightshift-dag.py next` and `graph` (`--json`, `--specs-dir`) |
| Is one spec file valid and ready? | `python3 .nightshift/validate_specs.py <file-or-dir> [--format json]`; `nightshift-dag.py validate-spec <file>`; every rule at once: `board_ctl.py rules check <id>` (`guides/rules.md`) |
| Is the board right vs the spec files? | `GET /api/status-sync` |
| Is a status change allowed and why was it refused? | the `PUT` response `detail`, or `transfer_refusal:` in the spec |
| Which files may this spec write? | `python3 .nightshift/scope_guard.py check --spec ID --root <repo> <paths...>` |
| Promote draft to ready with a record | `python3 .nightshift/spec_promotion.py` |
| Record a transition already applied | `python3 .nightshift/spec_artifacts.py record-transition` |
| Is the install itself sound? | `python3 .nightshift/validate_install.py --profile installed --root .`; `/nightshift validate` |
| Why is an install invisible or stale? | `doctor.py` in the kit repository, `/nightshift doctor` |
| Project overview | `/nightshift status` (spec queue, layers, last run) |

Relation to the slash commands: `/nightshift status` is the human dashboard and reads the
spec files; the board API answers the same questions from the durable store and is the
one to trust for status. `/nightshift validate` checks install and spec structure and
does not look at the store. `/nightshift doctor` diagnoses install provenance and
reachability, not individual specs. None of them replaces the other.

## 5. `board_ctl.py` (read side)

`python3 .nightshift/board_ctl.py <command>` wraps sections 1 to 4 for reads. It imports no
FastAPI, so it runs on system `python3` with the board stopped. `describe --json` lists every
command, its arguments, whether it writes (section 6 only) and this guide's path.

| Command | Answers | Needs board |
| --- | --- | --- |
| `list [--status S]... [--layer N] [--type T] [--parent ID] [--text Q]` | which specs match, by effective status | no |
| `show <id> [--body]` | frontmatter, run-state explanation, artifact index | no |
| `search <q>` | substring over id, title and body | no |
| `deps <id>` | what the spec waits on and what waits on it | no |
| `history <id>`, `artifacts <id> [--path P]` | status checkpoints; artifact index or one artifact | yes |
| `who` | `in_progress` specs joined with other-worktree status | yes |
| `health`, `refresh` | `/api/health`; re-read spec files (writes nothing) | yes |
| `next`, `brief <id>` | delegate to `nightshift-dag.py next`, `nightshift-instructions.py apply` | no |
| `port` | the port and how it was resolved | no |

- **Output.** Text by default, `--json` on every command with stable keys. Reads carry
  `"source": "board"` or `"offline"`. Exit codes: 0 ok, 1 not found, 2 usage, 3 board
  unreachable for a board-only command (the message names the next command to try).
- **Port order.** `--port`, then this project's `projects-registry.json` entry, then the
  `board.py` formula (shared code: `board.py` imports it from `board_ctl.py`).
  `--project NAME` aims every command at another registered project's board and specs.
  `--specs-dir DIR` overrides the specs directory.
- **Offline.** `list`, `show`, `search` and `deps` fall back to the spec files plus a
  read-only read of the status store (never a write, so the `frontmatter-reconcile`
  repair the board performs is not applied). A terminal store row therefore still wins
  over the frontmatter, as on the board. Ids are matched exactly, never parsed.
- **Relation to existing commands.** `board_ctl.py next` is `nightshift-dag.py next`;
  `board_ctl.py list` is the filtered `/api/specs` of section 3, not `/nightshift status`.

## 6. `board_ctl.py` management

Writes in this section are the only ones `board_ctl.py` makes; each delegates to the existing
durable path and never re-implements a store write. Exit codes add 4 (refused by the policy or a
gate) and 5 (operation failed, or `board-doctor` found a problem). `--control-port N`
(default `$NIGHTSHIFT_CONTROL_PORT`, else 7799) aims lifecycle commands at a Control instance.

- **Lifecycle.** `start | stop | restart | status`. With Control reachable and this project
  registered (same name and port) it uses `POST /api/projects/{name}/start|stop`; otherwise
  `board.sh --no-open --port N`. It never opens a browser and never signals a process
  itself. `status` reports up/down, the port and its source, and the launcher: `control`, or
  `board.sh` with its PID (a Control-launched board has no `board.pid`).
- **`board-doctor`** (the board only; `/nightshift doctor` / `doctor.py` stays the install
  diagnostic). Read-only; each finding names its fix: stale or invalid `board.pid`
  (`pid_file_*`, `pid_not_board`), the port held by a non-board process, the runtime missing
  fastapi/uvicorn/yaml (`NIGHTSHIFT_BOARD_PYTHON` or `.board-venv`), `/api/health` failing, a
  Control-launched board with no PID file, and store-versus-frontmatter disagreement
  (`/api/status-sync` when up, `status_store.classify_status_sync` offline).
- **`transition <id> <status> --reason R [--reconsider-when W] [--no-commit]`.** The edge is
  checked against `lifecycle.LIFECYCLE_TRANSITIONS` and this table before anything is written:

| From -> to | Result | Path |
| --- | --- | --- |
| draft/ready -> planned; draft/planned/ready -> blocked | allowed; `--reason` and `--reconsider-when` required | board write path |
| draft/planned/ready/blocked -> superseded | allowed; `--reason` required | board write path |
| draft/planned -> ready | allowed; `--reason`, plus `--gap-resolved` or `--gap-waived-reason`, `--resolution-rationale`, `--finding`, `--evidence` | `spec_promotion.py` (always, board up or down) |
| blocked -> draft/planned/ready | refused (exit 4) | `/nightshift unblock <id>` |
| any -> in_progress, in_progress -> any | refused | `/nightshift run` (kickoff, verifier) |
| any -> done | refused | the verifier and merge flow |
| any other edge | refused, listing the edges allowed from the current status | none |

  Board write path: with the board up (`/api/health` answers and it knows the spec) the helper
  sends `PUT /api/spec/{id}/status` and then `POST /api/refresh`; down, it runs the same gate
  sequence (`status_transition.gate_status_write`, also called by `board.py`) and
  `transition_commit_backed`. A refusal and its `transfer_refusal:` record are the same either way.
  A board answering without the spec is an error, never a reason to fall back offline.
- **Commit.** Neither path commits, so the helper does: only the spec and the artifacts this
  transition created, as `git commit -- <paths>` (`[<ID>] chore: status A -> B (board_ctl)`).
  If the spec or its `reports/<ID>/` was dirty or staged before, or with `--no-commit`, it
  commits nothing and prints the exact command. Other staged files stay staged.
- **`validate [<id>... | --staged | --all] [--install]`.** Runs `validate_specs.py` and, with
  `--install`, `validate_install.py --profile installed|canonical` (by layout); one summary,
  exit 0 only if all pass. `/nightshift validate` Check 4 can use it.

Recipes: park a draft: `board_ctl.py transition SPEC-X planned --reason "waiting for design"
--reconsider-when "design lands"`; retire a spec: `... superseded --reason "replaced by SPEC-Y"`;
why a card did not move: `board_ctl.py board-doctor`, then `show <id>`.
