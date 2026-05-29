# Nightshift Report — 2026-05-29 — SPEC-BUG-126

## Summary Stats

- Specs run: 1
- Completed: 1
- Blocked: 0
- Files changed in this run:
  - `internal/web/server_test.go`
  - `.nightshift/specs/SPEC-BUG-126-api-tools-shipyard-returns-502.md`
- Required validation commands passed: 3/3
- Live API checks passed: 6/6

## Per-Spec Changes

### SPEC-BUG-126 — `GET /api/tools?server=shipyard` Returns 502 Instead of Shipyard Tool List

Status: done

The current branch/base already contained the implementation for the self-server path:

- `fetchToolsResult` returns `selfToolsResult()` for `serverName == "shipyard"` instead of forwarding to child proxies.
- `selfToolsResult()` returns the built-in Shipyard tools with bare names.
- `handleTools` applies gateway policy fields (`enabled`, `server_enabled`) to the direct per-server response.

This run added missing regression coverage for AC5:

- `TestHandleTools_ShipyardSelfServerMatchesGatewayCatalogNaming`
- Verifies `/api/gateway/tools?include_disabled=1` uses namespaced `shipyard__*` names.
- Verifies `/api/tools?server=shipyard` uses bare names.
- Verifies both views agree on `enabled` and `server_enabled`, including disabled `shipyard/status`.

The spec file was marked `done` and its requirement/acceptance checkboxes were checked after validation passed.

## Test Results

All required commands from `.nightshift/config.yaml` passed:

```text
go test ./internal/web
ok  	github.com/sloik/shipyard/internal/web	3.026s

go test ./...
ok  	github.com/sloik/shipyard/cmd/shipyard	(cached)
ok  	github.com/sloik/shipyard/cmd/shipyard-mcp	(cached)
ok  	github.com/sloik/shipyard/internal/auth	(cached)
ok  	github.com/sloik/shipyard/internal/capture	(cached)
ok  	github.com/sloik/shipyard/internal/gateway	(cached)
ok  	github.com/sloik/shipyard/internal/proxy	(cached)
ok  	github.com/sloik/shipyard/internal/secrets	(cached)
ok  	github.com/sloik/shipyard/internal/secrets/env	(cached)
ok  	github.com/sloik/shipyard/internal/secrets/keychain	(cached)
ok  	github.com/sloik/shipyard/internal/secrets/op	(cached)
?   	github.com/sloik/shipyard/internal/teststubchild	[no test files]
ok  	github.com/sloik/shipyard/internal/web	(cached)

go vet ./...
passed

go build ./...
passed
```

## Live API Evidence

The running local Shipyard instance was already listening on `127.0.0.1:9417`, so it was not stopped or replaced.

- `GET /api/servers` returned `shipyard` plus real child servers including `lmac-run`, `lmstudio`, `markitdown`, and `xcode`.
- `curl -i 'http://127.0.0.1:9417/api/tools?server=shipyard'` returned `HTTP/1.1 200 OK`.
- Direct self-server body contained bare tools: `status`, `list_servers`, `restart`, `stop`.
- Each direct self-server tool included `enabled` and `server_enabled`.
- `PUT /api/tools/shipyard/status/enabled {"enabled":false}` returned 200, and the direct self-server response returned bare `status` with `enabled:false` and `server_enabled:true`.
- `GET /api/gateway/tools?include_disabled=1` returned namespaced `shipyard__status` with `tool_enabled:false`, `enabled:false`, and `server_enabled:true` during the disabled check.
- The toggle was restored with `PUT /api/tools/shipyard/status/enabled {"enabled":true}` and verified restored through `/api/tools?server=shipyard`.
- `curl -i 'http://127.0.0.1:9417/api/tools?server=lmac-run'` returned `HTTP/1.1 200 OK` with the real child server's bare tools.

## Acceptance Checklist

- [x] AC 1: `GET /api/tools?server=shipyard` returns 200 OK.
- [x] AC 2: Response includes a `tools` array with at least `status`, `list_servers`, `restart`, and `stop`.
- [x] AC 3: Each returned Shipyard tool includes `enabled` and `server_enabled`.
- [x] AC 4: Disabling `shipyard__status` makes direct `/api/tools?server=shipyard` return bare `status` with `enabled:false`.
- [x] AC 5: Gateway view and direct per-server view stay consistent; gateway uses namespaced names, direct view uses bare names.
- [x] AC 6: `GET /api/tools?server=<real-child>` still works unchanged; verified with `lmac-run`.
- [x] AC 7: Go regression coverage exists for the self-server `/api/tools` path, including the newly added AC5 consistency test.
- [x] AC 8: `go test ./...`, `go vet ./...`, and `go build ./...` pass.

## Blockers / Discoveries

- No blockers remain.
- Discovery: the implementation and two self-server tests were already present in the current branch/base before this run; the remaining useful work was closing the AC5 regression gap and completing the Nightshift evidence/reporting path.
- Discovery: the manual isolated worktree contains tracked spec/config files but does not contain local-only Nightshift protocol files or `.argo/README.md`; those were read from the main checkout as a read-only fallback. Main checkout edits were limited to the shared heartbeat file.

## Suggested Follow-up Specs

None.
