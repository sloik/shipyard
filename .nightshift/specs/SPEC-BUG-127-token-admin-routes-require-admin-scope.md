---
id: SPEC-BUG-127
template_version: 3
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-010]
violates: [SPEC-010]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-29
completed: 2026-05-29
---

# Token Admin Routes Require Admin Scope

## Problem

Shipyard's token-admin HTTP endpoints authenticate a bearer token, but do not
check whether that token is actually administrative. Any stored token can list,
delete, inspect, or update token scopes through `/api/tokens...` as long as it
is otherwise valid.

This violates SPEC-010's scoped-token model. SPEC-010 distinguishes an admin
token with `*:*` from scoped tokens such as `filesystem:*`; scoped tokens should
authorize MCP tool access only within their scopes, not token administration.

**Violated spec:** SPEC-010 (Bearer Token Authentication for MCP Proxy)

**Violated criteria:** R8 adds token CRUD as an admin API; R2/R5/R6 define
per-token scopes as the authorization boundary; AC-3/AC-4 distinguish scoped
tokens from `*:*` tokens; AC-11/AC-12/AC-18/AC-19 cover token-admin operations.

## Reproduction

Initial state:

- Auth is enabled on the server.
- A scoped non-admin token exists, for example with scopes `["filesystem:*"]`.

Steps:

1. Send `GET /api/tokens` with `Authorization: Bearer <scoped-token>`.
2. Send `DELETE /api/tokens/{id}` with `Authorization: Bearer <scoped-token>`.
3. Send `PUT /api/tokens/{id}/scopes` with `Authorization: Bearer <scoped-token>`.
4. **Actual:** the request is accepted if the token is valid.
5. **Expected:** the request is rejected with `401 Unauthorized` unless the
   bearer is the bootstrap token or a stored admin token with unrestricted scope.

## Root Cause

`requireAdminAuth` authenticated the bootstrap token first, then accepted any
stored token returned by `authStore.Authenticate`. It did not check the stored
token's scopes before allowing token-admin operations, so scoped MCP tokens were
implicitly treated as admin tokens.

## Requirements

- [x] R1: Token-admin routes must continue to accept the bootstrap token.
- [x] R2: Token-admin routes must accept stored tokens with unrestricted admin
  scope (`*:*`).
- [x] R3: Token-admin routes must reject valid stored tokens that do not have
  unrestricted admin scope.
- [x] R4: Existing token create, list, delete, update-scopes, and stats behavior
  must remain unchanged for admin callers.
- [x] R5: MCP bearer-token authorization and scoped tool access must remain
  unchanged.

## Acceptance Criteria

- [x] AC 1: A token with scope `filesystem:*` receives `401 Unauthorized` when
  calling `GET /api/tokens`.
- [x] AC 2: A token with scope `*:*` can call `GET /api/tokens` successfully.
- [x] AC 3: `DELETE /api/tokens/{id}` still revokes a target token when called
  by an admin token.
- [x] AC 4: `PUT /api/tokens/{id}/scopes` still updates a target token when
  called by an admin token.
- [x] AC 5: The violated SPEC-010 scoped-token/admin-token distinction now
  passes for token-admin routes.
- [x] AC 6: Regression coverage exists in Go unit tests.
- [x] AC 7: `go test ./...`, `go vet ./...`, and `go build ./...` pass.

## Context

- Parent spec: `.nightshift/specs/SPEC-010-token-based-auth.md`
- NFR: `.nightshift/specs/SPEC-NFR-001-zero-data-races.md`
- Existing auth store: `internal/auth/store.go`
- Existing scope matching: `internal/auth/scope.go`
- Token admin handlers: `internal/web/server.go`
- Existing tests: `internal/web/server_test.go`

## Out of Scope

- Adding roles beyond the existing `*:*` unrestricted admin token convention
- Changing token generation, hashing, storage, or rate limiting
- Adding dashboard authentication
- Changing MCP scoped-tool authorization behavior

## Code Pointers

- `internal/web/server.go` - `requireAdminAuth` and token-admin handlers
- `internal/auth/scope.go` - scope matching semantics
- `internal/web/server_test.go` - token-admin endpoint tests
- `.nightshift/specs/SPEC-010-token-based-auth.md` - parent auth behavior

## Gap Protocol

- Research-acceptable gaps:
  - Whether an existing helper already encapsulates unrestricted token checks
  - Whether admin status should accept only `*:*` or the existing wildcard
    matcher's equivalent unrestricted pattern
- Stop-immediately gaps:
  - Any fix that requires weakening MCP tool-scope enforcement
  - Any fix that changes token storage format or invalidates existing tokens
- Max research subagents before stopping: 0
