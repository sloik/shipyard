---
id: SPEC-011
template_version: 2
priority: 3
layer: 2
type: feature
status: done
after: [SPEC-010]
prior_attempts: []
parent:
nfrs: []
created: 2026-04-05
---

# Token Management UI

## Problem

SPEC-010 introduces bearer token authentication for Shipyard's proxy endpoints, but there is no way to manage tokens through the web dashboard. Administrators must use raw API calls or CLI tools to create, scope, and revoke tokens. This creates friction for day-to-day operations and makes it easy to lose track of which tokens exist, what they can access, and whether any are stale.

A dashboard page for token management makes the feature self-service and visible --- operators can create scoped tokens, audit usage, and revoke compromised tokens without leaving the browser.

## Requirements

- [ ] R1: Add a "Tokens" tab/route to the dashboard navigation
- [ ] R2: Display a table listing all tokens with columns: name, created date, last used, rate limit, scope count, status (active/revoked)
- [ ] R3: Provide a "Create Token" flow that collects name, rate limit, and initial scopes, then displays the plaintext token exactly once
- [ ] R4: Implement a scope editor that lets users view, add, and remove scopes for an existing token
- [ ] R5: Scope editor shows a live preview of which tools match the current scope patterns
- [ ] R6: Provide a "Revoke" action with confirmation dialog that soft-deletes the token
- [ ] R7: Display per-token usage statistics (total calls, calls today/this week, top tools, error rate, last used)
- [ ] R8: All UI uses existing design system components from ds.css / ds.js --- no inline styles, no new CSS classes outside the design system
- [ ] R9: All API interactions use XMLHttpRequest with callbacks (no fetch, no async/await)

## Acceptance Criteria

- [ ] AC 1: Navigating to `#/tokens` displays the token list table; the table loads data from `GET /api/tokens`
- [ ] AC 2: The token list table shows columns: Name, Created, Last Used, Rate Limit, Scopes, Status --- with correct data types (dates formatted, scope count as integer, status as badge)
- [ ] AC 3: Revoked tokens appear in the table with a "revoked" badge and greyed-out styling; they are not removed from the list
- [ ] AC 4: Clicking "Create Token" opens a form with fields: name (required, text input), rate limit per minute (number input, default 60), initial scopes (textarea, one scope per line)
- [ ] AC 5: Submitting the create form with an empty name shows a validation error and does not call the API
- [ ] AC 6: On successful creation (`POST /api/tokens`), a show-once dialog displays the plaintext token value with a "Copy" button and a warning that the token will not be shown again
- [ ] AC 7: The "Copy" button copies the token to the clipboard and shows visual feedback (e.g., button text changes to "Copied")
- [ ] AC 8: After dismissing the show-once dialog, the new token appears in the list table
- [ ] AC 9: Clicking "Edit Scopes" on a token row opens the scope editor showing current scopes as an editable list
- [ ] AC 10: Each scope row displays the `{server}:{tool_pattern}` format; users can add new rows and remove existing ones
- [ ] AC 11: As the user types a scope pattern, a live preview section shows which tools from `GET /api/tools` match the pattern (client-side filtering)
- [ ] AC 12: Saving scopes calls `PUT /api/tokens/{id}/scopes` with the updated scope list; the token list refreshes on success
- [ ] AC 13: Clicking "Revoke" shows a confirmation dialog stating the token name; confirming calls `DELETE /api/tokens/{id}`; the token row updates to revoked status without a page reload
- [ ] AC 14: Expanding or opening stats for a token calls `GET /api/tokens/{id}/stats` and displays: total calls, calls today, calls this week, top 5 tools by call count, error rate (percentage), last used timestamp
- [ ] AC 15: The Tokens page uses only ds.css classes and ds.js components --- zero inline styles, zero framework dependencies
- [ ] AC 16: All HTTP calls use XMLHttpRequest with callbacks; no `fetch()`, no `async/await`, no Promises

## Context

- **Dashboard file:** `internal/web/ui/index.html` (single-file SPA, ~78.5KB)
- **Design system:** `internal/web/ui/ds.css` (36.4KB) + `internal/web/ui/ds.js` (16.4KB)
- **Web server:** `internal/web/server.go` --- stdlib `net/http`, route pattern `GET /api/...`, `POST /api/...`
- **Design source of truth:** `UX-002-dashboard-design.pen` --- check via Pencil MCP `get_guidelines` for component specs
- **Existing navigation:** Hash routing with `#/timeline`, `#/tools`, `#/history`, `#/servers` (see SPEC-006)
- **Token API endpoints (from SPEC-010):**
  - `POST /api/tokens` --- create token (body: `{name, rate_limit_per_minute, scopes: []}`) --- returns plaintext token
  - `GET /api/tokens` --- list all tokens
  - `DELETE /api/tokens/{id}` --- revoke token
  - `PUT /api/tokens/{id}/scopes` --- update scopes (body: `{scopes: []}`)
  - `GET /api/tokens/{id}/stats` --- usage statistics
- **Tools endpoint:** `GET /api/tools` already exists (used by Tool Browser); scope preview reuses this
- **Config constraints from `.nightshift/config.yaml`:** single HTML file, vanilla JS only, no async/await

## Alternatives Considered

- **Separate HTML page for tokens:** Rejected --- breaks the single-file SPA convention established by SPEC-006. Adding a route is consistent with the existing architecture.
- **Modal-based workflow (no dedicated page):** Rejected --- token list + stats + scope editor have enough surface area to warrant a full page section. Modals work for create and revoke confirmation but not for the main list.
- **Server-side rendered token list:** Rejected --- the dashboard is fully client-side. Adding server-rendered HTML would introduce a second rendering paradigm.

## Scenarios

1. **First token creation:** Admin navigates to `#/tokens` -> sees empty table with "No tokens yet" message -> clicks "Create Token" -> fills in name "CI Pipeline", leaves rate limit at 60, adds scopes `cortex:*` and `filesystem:read_file` -> submits -> sees show-once dialog with the token value -> copies it -> dismisses dialog -> token "CI Pipeline" appears in table with status "active" and scope count 2.

2. **Scope refinement:** Admin sees token "CI Pipeline" in the list -> clicks "Edit Scopes" -> sees current scopes `cortex:*` and `filesystem:read_file` -> adds `filesystem:list_directory` -> types `filesystem:` and sees live preview showing all filesystem tools that match -> saves -> scope count in the table updates to 3.

3. **Token compromise response:** Admin suspects token "CI Pipeline" is compromised -> clicks "Revoke" -> confirmation dialog says "Revoke token CI Pipeline? This cannot be undone." -> confirms -> token row turns grey with "revoked" badge -> token remains visible in the list for audit purposes.

4. **Usage audit:** Admin clicks stats expand/panel on token "CI Pipeline" -> sees total calls: 1,247, today: 89, this week: 412, top tools: `cortex:cortex_search` (890 calls), `cortex:cortex_add` (312 calls), `filesystem:read_file` (45 calls), error rate: 0.4%, last used: 2 minutes ago.

5. **Empty scope warning:** Admin creates a token with no scopes -> token appears in list with scope count 0 -> any API call with this token is rejected (server-side, per SPEC-010) -> admin clicks "Edit Scopes" to add scopes after the fact.

## Out of Scope

- Token rotation (create a new token that replaces an old one) --- future spec
- Token expiration dates / TTL --- future spec
- Bulk operations (revoke multiple tokens at once) --- future spec
- Token usage graphs / charts over time --- future spec (current stats are numeric only)
- Role-based access to the token management page itself --- Shipyard v2 has no user auth for the dashboard
- Export/import of token configurations --- future spec
- Scope autocompletion dropdown (live preview is sufficient for v1)

## Research Hints

- **Files to study:**
  - `internal/web/ui/index.html` --- existing route structure, hash router implementation, XHR patterns
  - `internal/web/ui/ds.css` --- available table, form, button, dialog, badge classes
  - `internal/web/ui/ds.js` --- available JS components (dialogs, forms, toasts)
  - `internal/web/server.go` --- existing endpoint registration pattern for adding token API routes
  - `UX-002-dashboard-design.pen` --- design system component inventory (use Pencil MCP `get_guidelines`)
- **Patterns to look for:**
  - How existing pages (Timeline, Tool Browser) make XHR calls and render responses
  - How the hash router shows/hides view sections
  - How the Tool Browser fetches and displays tool lists (reuse for scope preview)
  - Dialog patterns in ds.js (create, show, dismiss)
  - Table rendering patterns (static vs dynamic rows)
- **Cortex tags:** shipyard, dashboard, tokens, ui
- **DevKB:** `DevKB/go.md` (for server-side endpoint registration)

## Gap Protocol

- **Research-acceptable gaps:** design system component names, existing XHR helper patterns, hash router API
- **Stop-immediately gaps:** SPEC-010 API contract changes (endpoint URLs, request/response shapes), missing ds.css components needed for the UI (tables, dialogs, forms, badges)
- **Max research subagents before stopping:** 3
- **Design system gate:** If a required UI component (table, dialog, form, badge) does not exist in ds.css/ds.js, stop and file a design system gap --- do not create ad-hoc CSS. Check `UX-002-dashboard-design.pen` via Pencil MCP first.

---

## Notes for the Agent

- **SPEC-010 must be complete first.** This spec only builds the UI; the API endpoints and token storage are SPEC-010's responsibility. If SPEC-010 is not done, this spec is blocked.
- **Single file constraint:** All HTML, CSS references, and JS go into `internal/web/ui/index.html`. Do not create separate `.js` files.
- **No async/await, no fetch, no Promises.** Use `XMLHttpRequest` with `onload`/`onerror` callbacks. Check existing XHR patterns in index.html before writing new ones.
- **Clipboard API:** `navigator.clipboard.writeText()` returns a Promise. Wrap it or use the older `document.execCommand('copy')` with a hidden textarea to stay within the no-Promise constraint. Check which pattern ds.js already provides.
- **Show-once token dialog:** The plaintext token value must never be stored client-side after the dialog is dismissed. Clear the variable holding it when the dialog closes.
- **Scope pattern matching for live preview:** The format is `{server}:{tool_pattern}` where `tool_pattern` supports `*` as a glob. Implement simple client-side glob matching (replace `*` with `.*`, use RegExp). The tool list from `GET /api/tools` includes server names and tool names.
- **Revoked tokens stay in the list.** Do not filter them out. Use a badge or visual indicator (greyed row, "revoked" label) to distinguish them.
- **Check the .pen file** via Pencil MCP `get_guidelines` before implementing any component. The design file is the source of truth for visual appearance.
- **Add the `#/tokens` route** to the existing hash router in index.html. Follow the same pattern as `#/timeline`, `#/tools`, etc. Add a "Tokens" tab to the navigation bar.
