Load when: following board-and-api.md for shared board and control prompt library.
Covers: the complete continuation section relocated from board-and-api.md.
Not here: parent workflow and gates (see board-and-api.md).
Requires: read board-and-api.md first; all its gates remain in force.

## Shared prompt library

Board **PROMPT LIBRARY** and the selected registered Control card use the same
`prompt_snippets.py` service and the same UI fragment. The legacy **SNIPPETS**
entry remains available against that authority. Control uses the selected
registered name and port, resolves its existing board layout without launching
or importing that project's Python, and rejects unsupported/unreadable contexts.
Project selection never changes a dirty editor's original write destination.

| Method | Board path | Contract |
| --- | --- | --- |
| GET | `/api/prompt-library` | `{items, stores}`; resolved identities, per-store revisions and folders; no write/migration |
| POST | `/api/prompt-library/{scope}/mutate` | JSON `action`, `revision` plus payload; returns `{item, snapshot}` |
| POST | `/api/prompt-library/{scope}/{id}/copy` | JSON `mode: plain/codex/claude`; exact `{text}` |
| POST | `/api/prompt-library/{scope}/{id}/render` | Explicit `harness`, `variables`; legacy `{text,warnings}` |

Control exposes the same paths under `/api/projects/{name}/prompt-library`,
with the selected registered `?port=` retained for every request. Only local,
same-origin callers may access the library routes. Scope is `prebuilt`, `repo`
or `project`; the former is immutable, including folders. Repo resolves to the
selected Git worktree root, project to the sibling of its existing `specs/`.
There is no personal/global writable scope and no secondary Control database.

Mutation actions are `create`, `update`, `delete`, `duplicate`, `folder_create`,
`folder_rename`, `folder_delete` and `move`. Existing targets use `id`; folders
use trimmed names unique ignoring case in that scope; moves use `folder_id`
(or null for Ungrouped). Duplicate uses `source_scope` and `source_id` and a new
identity, preserving overrides and variables. Nonempty folder deletion returns
409 `folder_not_empty` with `count`; explicitly move members out first.

Every mutation requires a store revision. Legacy POST/PUT accepts `If-Match`
or a JSON `revision`; legacy DELETE requires `If-Match`. Missing preconditions
return non-mutating 428 `precondition_required` with reload/upgrade guidance.
A stale edit/delete/move returns 409 `conflict`: retain input, reload the latest
revision, review and explicitly reapply. Independent creates can merge under
the same cross-process lock; existing ID collisions always refuse. Errors for
load, malformed store, write, conflict and unavailable context are visible;
malformed/unreadable content is never replaced as an empty successful library.
Legacy GET list/single and explicit render retain their response shapes, with
additional identity/revision/folder/kind metadata on snippet rows.

**Schema and rollback boundary.** Reads preserve legacy list bytes and create
nothing. First successful mutation writes schema version 2, an object containing
`schema_version`, `snippets`, `folders`, after retaining exact original bytes in
`<store>.v1.<sha256>.bak`. Unknown snippet fields, IDs, bodies, tags, variables,
overrides and timestamps survive migration; explicit edits change only their
intended fields. No automatic legacy command inference occurs. All writers to a
store must use the upgraded service before that first write: old list-only
writers are unsupported after migration and must not run concurrently. For
rollback, stop **all** writers, export any later edits, restore the exact digest
named v1 backup, then start compatible old writers. Restoring the backup alone
loses later edits; never restore over active writers. No live store migration
is part of testing or installation verification.

Plain copy returns the stored body without rendering. Explicit command kind
stores one unprefixed token at offset zero plus its untouched suffix, e.g.
`nightshift run "a/$b"` followed by a newline remains exact after prepending one
`$` or `/`. Explicit create/convert removes at most one optional leading prefix;
leading whitespace, embedded token prefix or an empty token refuse. Dollars,
slashes, URLs, fences and newlines in the suffix remain untouched. Rendered copy
is separate, with harness overrides, variable inputs and service-bound board URL.
Clipboard success is announced only after the clipboard API resolves; failure
retains exact selectable preview and a distinct explanation. No action executes
or pastes a snippet.
