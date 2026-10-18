Load when: finding specs, authoring placement or moving status.
Covers: board discovery, status authority, routes and CLI.
Not here: spec interview, kickoff or validation rules; use their command guides.
Requires: installed board.py, status_store.py and lifecycle.py; a board for HTTP recipes.

# Board and API guide

Authority: board.py routes/SpecCache._update_status_locked, status_store.py's
StatusStore.transition_commit_backed, lifecycle.py and Control (nightshift-master.py).
Paths are install-relative (.nightshift/); source files live in canonical/.

## 1. Launch, port, runtime

- **Control** (`nightshift-master.py`, port 7799) loads discovered project registries.
  `POST /api/projects/{name}/start` detaches `board.py --port <registry port>`;
  returns `{"status":"starting",...}`, logs beside `board.py` in `board.restart.log`,
  writes no `board.pid`. `/stop` finds and signals the port's listener.
- **`board.sh`** (`.nightshift/board.sh [--no-open] [--port N] [board.py args]`)
  backgrounds `board.py --open`, probes `/api/health`, then writes adjacent `board.pid`.
  `--no-open` skips the browser; `stop` refuses a PID that is not this board.
  Log: `board.restart.log`. Runtime: `$NIGHTSHIFT_BOARD_PYTHON`, then
  `.nightshift/.board-venv/bin/python`, then `python3`; missing fastapi/uvicorn/yaml exits 1.
- **Port:** explicit `--port` wins; otherwise `board.py` hashes the project-root name
  (upper-case, leading dots stripped): `7800 + sum(ord(c) for c in NAME) % 200`.
  `python3 .nightshift/board.py --print-port` prints without starting. `board.sh` uses
  that probe (BUG-342), while Control passes the registry port; these may differ.
  Find registered name/port in `projects-registry.json`; confirm `/api/health` answers.
- Binds `127.0.0.1` only; recipes use `B=http://127.0.0.1:$PORT`.
  `board.py --summary` prints reconciled JSON without serving; `--export PATH.html`
  writes a static snapshot.

### Authoring identity, placement and retention

Read the live registry's name, path, code and port; resolve the intended watched
spec directory, not the shell cwd. Observed canonical kit identity is
`NIGHTSHIFT-CANONICAL`/`NS-KIT`, flat `canonical/specs`; Control uses `NS-CTL`;
installed applications use their own registered code and `.nightshift/specs`.
Recheck these observations on the current installation.

Run `check_followup_spec.py --specs-dir <registered-specs> --suggestion-title <title>
--suggestion-body <requirements-and-ACs> --kind <kind>`; retain the actual result.
Conflicts stop authoring. An unexpected generic proposal from an unregistered
worktree is refused even if the gate returns clean. Prefer the registered-root gate;
if needed, supported Python `check(..., registry_path=...)` takes a caller-only
registry copy mapping existing entries to the isolated roots while preserving codes.
Retain the mapping/result; never mutate the global registry or invent an ID.

A durable branch commit does not place files in a running board's watched tree;
board-visible working-tree files do not establish MAIN integration. Retain the
spec, indexed author decision (`spec_artifacts.py author-decision`), evidence and
required handoff as one set. Placement into MAIN follows GIT.md's sole serialized
integration authority and current freeze. Disclose incomplete integration and any
uncommitted placement. Never dirty frozen MAIN, commit directly to MAIN, remap the
board root or promote solely for visibility.

At the registered port, bound discovery to `GET /api/health`, `POST /api/refresh`,
`GET /api/specs`, then `GET /api/spec/<ID>` for each new ID. Require one list entry,
intended effective status and `artifact_index_state: available` with the indexed
decision. HTTP 404 means unresolved placement/discovery. Intrinsic readiness PASS
with lifecycle `draft` is still non-dispatchable; later promotion uses the supported
entrypoint. Authoring placement alone adds no native/full-kit suite gate; existing
implementation, ownership, integration and release gates remain required.

Before temporary cleanup, retain bounded unique findings in persistent
`reports/<ID>/` and commit on the durable branch: readable summary, source paths,
SHA-256 hashes, and archive member/source mapping plus integrity when archiving.
Temporary paths are provenance, not required live inputs. Exclude credentials,
copied app trees and derived builds; board-visible untracked files alone are not
retention. Do not claim implementation or release from these checks.

## 2. Status authority model

Status combines frontmatter and a durable SQLite checkpoint (`StatusStore`):
`nightshift-status.db` in the Git common directory, shared across worktrees;
strict checkout subdirectories get namespaced stores.

- **Effective status:** newest `done`/`blocked` checkpoint wins immutably over
  frontmatter. Otherwise frontmatter at least as new as the checkpoint creates
  a `frontmatter-reconcile` checkpoint and moves the card.
- **Mismatch:** `GET /api/status-sync` lists `{id, frontmatter, durable, effective,
  reason,...}`. `durable-terminal-ahead-of-file` means terminal store/file lag;
  `durable-stale-behind-file` means refused non-terminal repair (e.g. different
  path or older file). `/api/health` counts `status_sync_mismatches`.
  Use a supported transition, not another hand edit.
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
- **Lifecycle map** (`lifecycle.LIFECYCLE_TRANSITIONS`): draft → planned/ready/blocked/
  superseded; planned → ready/blocked/superseded; ready → planned/in_progress/blocked/
  superseded; in_progress → ready/done/blocked; blocked → draft/planned/ready/superseded;
  done/superseded → none. `unblock_spec.py` and `release_handoff.py` consult it;
  board PUT and `transition_commit_backed` do not, so their actual gate governs writes.
- **Reasons:** every pair among draft/planned/ready/in_progress/blocked/done/superseded
  requires non-empty prose except mechanical ready → in_progress, in_progress → done,
  blocked → ready (synthesized reason). `active`/`retired` never require one;
  source: `lifecycle.is_judgment_transition`.
- **Rationale:** transitions upsert `## State rationale` YAML (status, reason,
  `reconsider_when`, evidence, `record` artifact pointer), also exposed in detail's
  `run_state_explanation`. Targets draft/planned/blocked require a concrete revisit
  condition/date; omitted PUT values still write an artifact but leave stale rationale.
  `state_evidence` holds typed locators, e.g. `{"kind":"file","path":"..."}`.
- **Done:** validates `release_handoff:` against a manifest next to `board.py`.
  Kit has it; fleet installs do not (BUG-337), so without it the gate is skipped.
- **Transfer refusals:** best-effort sanitized `transfer_refusal:` frontmatter
  records gate failures; successful PUT clears it. UI POST/DELETE
  `/api/spec/{id}/transfer-refusal` sets/dismisses it. This edit appears in Git status.
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
| GET | `/api/search` | `?q=` ranked exact/abbreviated/numeric ID or literal title/body phrase; default `[{id,title,status,excerpt}]` | R |
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

Live/exported graphs default to a reduced view: hide a prerequisite arrow only
while an alternate directed path remains among displayed arrows. Reachability is
unchanged. **Show all dependencies** (legend/inspector) restores declared arrows;
the note counts hidden ones and the inspector names their alternate paths.
Filters/data changes recompute reduction: hiding a middle spec restores its direct
arrow. Dashed parent/grouping lines never count; self-loops, missing specs and
cycle-touching edges stay visible. External keys are `project::id`. This is view-only:
files, `after:`, `/api/graph`, `board_ctl.py deps`, exports, validation and scheduling
retain every edge; redundant `after:` is valid. `dependency_graph_view.py`
(`reduce_dependency_edges`) and board JS `reduceDependencyEdges` share tested graphs.

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

`/nightshift status` reads spec files for a human overview; trust the board's
effective status. `/nightshift validate` checks install/spec structure, not the
store; `/nightshift doctor` checks install provenance/reachability, not specs.

## 5. `board_ctl.py` (read side)

`python3 .nightshift/board_ctl.py <command>` wraps sections 1 to 4 for reads. It imports no
FastAPI, so it runs on system `python3` with the board stopped. `describe --json` lists every
command, its arguments, whether it writes (section 6 only) and this guide's path.

| Command | Answers | Needs board |
| --- | --- | --- |
| `list [--status S]... [--layer N] [--type T] [--parent ID] [--text Q]` | which specs match, by effective status | no |
| `show <id> [--body]` | frontmatter, run-state explanation, artifact index | no |
| `search <q>` | ranked ID or title/body search; explicit facets/paging, optional offline snapshot | no |
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

### Completion warnings and release delivery

Only `WARNING: ` is advisory. Valid pending re-pin permits Done, not delivery.
API warnings reach drag/dropdown; 400: detail/errors/warnings.
Invalid manifest/handoff blocks checkpoint. Whole-kit release
re-pins/delivers; BUG-337 exempts installs without bookkeeping. Board/CLI share
gate; `board_ctl transition` refuses Done/in_progress (parent/verifier).
Persistence failure: reconcile recovery artifact/file, retry supported writer;
never edit state manually.

Live/export cards: ≤2 title lines, ≤1 activity line; wait/incomplete flags.
Unknown duration; no activity: no row. Hover/focus: full title;
click/Enter/Space: full activity.

Replacement: see `../SPEC-GUIDE.md` (SPEC-NS-KIT-184).


Search/snapshot details and load diagnostic boundaries: [search and benchmarks](board-search-benchmarks.md).

## Shared prompt library routes

Read [prompt-library details](board-prompt-library.md) before using these routes.

| Method | Board path | Contract |
| --- | --- | --- |
| GET | `/api/prompt-library` | Read snapshot |
| POST | `/api/prompt-library/{scope}/mutate` | Revision-bound mutation |
| POST | `/api/prompt-library/{scope}/{id}/copy` | Copy |
| POST | `/api/prompt-library/{scope}/{id}/render` | Render |
