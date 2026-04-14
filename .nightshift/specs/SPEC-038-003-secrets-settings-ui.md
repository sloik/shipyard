---
id: SPEC-038-003
template_version: 2
priority: 1
layer: 2
type: feature
status: done
parent: SPEC-038
after: [SPEC-038-002]
prior_attempts: []
created: 2026-04-13
---

# Secure Secrets — Settings UI + Plain-Text Warning Banner

## Problem

After SPEC-038-001 and SPEC-038-002, Shipyard can resolve secrets — but users have no
UI to configure which backend to use, and no indication that their current config has
plain-text secrets that should be migrated.

Two UX gaps:
1. The only way to set `secrets.backend` is by editing the YAML config file manually.
2. Users with existing `LMS_API_KEY: "sk-..."` entries have no hint that something is
   wrong or how to fix it.

## Requirements

- [ ] R1: Settings tab (`#view-settings`) gets a new "Secret Manager" section showing
  the current backend and radio buttons to switch between: macOS Keychain, 1Password
  (op CLI), Environment Variables, None (plain text).
- [ ] R2: Selecting a radio button calls the settings API to persist the `secrets.backend`
  value to the config file.
- [ ] R3: On page load, the correct radio button is pre-selected based on the current
  `secrets.backend` config value returned by the settings API.
- [ ] R4: Servers view (`#view-servers`) shows an amber warning banner when the API
  indicates any server has plain-text secret candidates in its env config. A "plain-text
  secret candidate" is an env key whose name contains `KEY`, `TOKEN`, `SECRET`,
  `PASSWORD`, or `API` (case-insensitive) and whose value does NOT start with
  `@keychain:`, `op://`, or `${`.
- [ ] R5: Warning banner has a "Go to Settings" link that navigates to the Settings tab.
- [ ] R6: Warning banner is dismissable per page session (clicking ✕ hides it until
  the page is reloaded).
- [ ] R7: Plain-text detection is done server-side (`GET /api/servers` response includes
  a `has_plain_text_secrets bool` field per server). The UI reads this field — no secret
  scanning in JavaScript.

## Acceptance Criteria

- [ ] AC 1: Settings tab HTML (`#view-settings`) contains `id="secrets-backend-section"`.
- [ ] AC 2: `#secrets-backend-section` has four radio inputs with values `"keychain"`,
  `"1password"`, `"env"`, `""`.
- [ ] AC 3: `loadSettings()` JS function populates the correct radio as checked based on
  `config.secrets.backend` from the settings API.
- [ ] AC 4: Changing a radio calls `saveSecretBackend(value)` which POSTs/PATCHes the
  new backend value to the settings API endpoint.
- [ ] AC 5: `#servers-plain-text-warning` element exists in `index.html` (hidden by
  default via `style="display:none"`).
- [ ] AC 6: `loadServers()` shows `#servers-plain-text-warning` when any server in the
  response has `has_plain_text_secrets: true`.
- [ ] AC 7: Warning banner contains a button/link that calls `showView('settings')` (or
  equivalent).
- [ ] AC 8: `serverInfoResponse` in `internal/web/server.go` has `HasPlainTextSecrets bool \`json:"has_plain_text_secrets"\``.
- [ ] AC 9: `hasPlainTextSecrets(env map[string]string) bool` helper exists in
  `internal/web/` and is called when constructing `serverInfoResponse`.
- [ ] AC 10: `TestHasPlainTextSecrets` covers: plain-text API key detected, keychain ref
  not flagged, op ref not flagged, env ref not flagged, non-secret key not flagged.
- [ ] AC 11: Settings API (`GET /api/settings` or equivalent) returns `secrets.backend`
  in its response, and accepts updates to it.
- [ ] AC 12: `go test ./...` passes.
- [ ] AC 13: `go build ./...` passes.
- [ ] AC 14: `.shipyard-dev/verify-spec-038-003.sh` exits 0.

## Verification Script

Create `.shipyard-dev/verify-spec-038-003.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  if [ "$2" = "0" ]; then echo "  PASS: $1"; PASS=$((PASS+1))
  else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-038-003 Verification ==="

grep -q 'secrets-backend-section' internal/web/ui/index.html
check "secrets-backend-section exists in HTML" $?

grep -q 'servers-plain-text-warning' internal/web/ui/index.html
check "servers-plain-text-warning banner exists in HTML" $?

grep -q 'has_plain_text_secrets' internal/web/server.go
check "serverInfoResponse has has_plain_text_secrets field" $?

grep -q 'hasPlainTextSecrets' internal/web/server.go
check "hasPlainTextSecrets helper exists" $?

grep -q 'TestHasPlainTextSecrets' internal/web/server_test.go
check "TestHasPlainTextSecrets test exists" $?

go test ./...
check "go test ./..." $?

go build ./...
check "go build ./..." $?

echo ""; echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
```

## Context

### Target files

- `internal/web/ui/index.html`:
  - Settings tab: find the Settings section block (search for `#view-settings`). Add
    "Secret Manager" section after the existing Auth Token section.
  - Servers view: add `#servers-plain-text-warning` banner near the top of
    `#view-servers`, below the action bar. Hidden by default.
  - `loadSettings()` function: add code to read and set the secrets backend radio.
  - `loadServers()` function: after processing server list, check if any
    `has_plain_text_secrets` is true and show/hide the warning banner.

- `internal/web/server.go`:
  - `serverInfoResponse` struct: add `HasPlainTextSecrets bool \`json:"has_plain_text_secrets"\``
  - In `handleServers`: populate `HasPlainTextSecrets` by calling `hasPlainTextSecrets(srv.Env)`
  - New helper: `hasPlainTextSecrets(env map[string]string) bool`

- Settings API: Check if `/api/settings` endpoint exists. If not, add it. It must support
  `GET` (return full config including `secrets.backend`) and `PUT` or `PATCH` to update
  `secrets.backend`. Read existing settings handler patterns first.

### Secret Manager section HTML (target)

```html
<div class="settings-section">
  <div class="settings-section-title">Secret Manager</div>
  <div class="settings-section-body" id="secrets-backend-section">
    <label class="settings-radio-row">
      <input type="radio" name="secrets-backend" value="keychain">
      <span>macOS Keychain <span class="text-muted">(recommended on macOS)</span></span>
    </label>
    <label class="settings-radio-row">
      <input type="radio" name="secrets-backend" value="1password">
      <span>1Password <span class="text-muted">(requires op CLI)</span></span>
    </label>
    <label class="settings-radio-row">
      <input type="radio" name="secrets-backend" value="env">
      <span>Environment Variables <span class="text-muted">(${VAR} expansion only)</span></span>
    </label>
    <label class="settings-radio-row">
      <input type="radio" name="secrets-backend" value="">
      <span>None <span class="text-muted">(plain text, not recommended)</span></span>
    </label>
  </div>
</div>
```

Adapt to the existing settings section HTML structure — check how the Auth Token section
is structured and match the pattern.

### Warning banner HTML (target)

```html
<div id="servers-plain-text-warning" style="display:none; align-items:center; gap:12px; background:var(--warning-subtle); border:1px solid var(--warning-muted); border-radius:var(--radius-s); padding:10px 16px; margin:0 24px 12px 24px; font-size:var(--font-size-sm);">
  <span style="color:var(--warning-fg);">&#9888;</span>
  <span style="flex:1; color:var(--text-secondary);">One or more servers have plain-text secrets in their config. Consider using a secret manager.</span>
  <button class="btn btn-default btn-sm" onclick="showView('settings'); document.getElementById('servers-plain-text-warning').style.display='none';">Go to Settings</button>
  <button class="btn btn-ghost btn-sm" onclick="document.getElementById('servers-plain-text-warning').style.display='none';">&#10005;</button>
</div>
```

Check existing `--warning-*` CSS variables in `ds.css`. If they don't exist, use
`--warning-subtle: var(--bg-raised)` fallback or add the variables.

### hasPlainTextSecrets logic

```go
var secretKeyPattern = regexp.MustCompile(`(?i)(KEY|TOKEN|SECRET|PASSWORD|API)`)

func hasPlainTextSecrets(env map[string]string) bool {
    for k, v := range env {
        if !secretKeyPattern.MatchString(k) {
            continue
        }
        if strings.HasPrefix(v, "@keychain:") ||
            strings.HasPrefix(v, "op://") ||
            strings.HasPrefix(v, "${") {
            continue
        }
        return true
    }
    return false
}
```

Note: `hasPlainTextSecrets` operates on the ORIGINAL (unresolved) `ServerConfig.Env` —
not the resolved values. This is correct: we want to warn when the config file itself
has plain text. The `serverInfoResponse` struct should receive the unresolved env for
this check.

### Settings API

Check `internal/web/server.go` for existing `/api/settings` handler or `/api/config`
handler. If neither exists, add:
- `GET /api/settings` — returns `{"secrets": {"backend": "keychain"}}` (and any other
  settings fields already being returned)
- `POST /api/settings` — accepts `{"secrets": {"backend": "..."}}`, validates the
  `backend` field against the allowed enum, writes to config, returns 200

Keep the handler minimal. If a settings handler already exists, add `secrets` to its
response/request structs.

### JS conventions (from project config)

- Use `var`, not `let`/`const`
- Use `.then()` callbacks, not `async/await`
- Vanilla JS only — no framework

Example JS for backend selection:
```javascript
function loadSecretsBackend() {
  fetch('/api/settings').then(function(r) { return r.json(); }).then(function(d) {
    var backend = (d.secrets && d.secrets.backend) ? d.secrets.backend : '';
    var radios = document.querySelectorAll('input[name="secrets-backend"]');
    for (var i = 0; i < radios.length; i++) {
      radios[i].checked = (radios[i].value === backend);
    }
  });
}

function saveSecretBackend(value) {
  fetch('/api/settings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({secrets: {backend: value}})
  });
}
```

## Alternatives Considered

- **Client-side secret scanning** (scan env values in JS): Rejected. The API already
  omits env values (SPEC-038-002). The server must compute `has_plain_text_secrets` from
  the unresolved config before suppressing env values.
- **Persistent dismiss** (store dismiss in localStorage): Deferred. Session-only dismiss
  is simpler and ensures the warning reappears when the user returns, which is appropriate
  for a security warning.

## Out of Scope

- Reveal button (ephemeral 30s modal to see resolved value) — future spec
- Migration wizard (UI to move plain-text values to Keychain) — future spec
- Per-server backend override (all servers use the same configured backend) — future
- Warning for `${VAR}` refs when the env var is not set — future

## Gap Protocol

- Research-acceptable gaps: existing settings section HTML structure, existing
  `--warning-*` CSS variable names — read `index.html` and `ds.css` before implementing
- Stop-immediately gaps: `go test` failures; settings API writes resolved values to config
- Max research subagents before stopping: 0
