.PHONY: build test smoke smoke-build smoke-full snapshot release wails-dev wails-build wails-build-server package-macos sign-macos notarize-macos build-mcp install-mcp

build:
	go build ./cmd/shipyard/

# SPEC-BUG-149/150: headless-browser smoke harness.
# Launches an ephemeral Shipyard instance and drives real clicks against the
# UI via playwright-core + the system Chrome. Intentionally OUTSIDE `make test`
# (the Go suite) so a missing browser/node never blocks unrelated work.
#
# `make smoke`      - fast path: Tool Browser only (the common case).
# `make smoke-full` - opt-in: Tool Browser + Servers view (SPEC-BUG-150).
#
# Skips gracefully (exit 0): node missing -> guarded here; Chrome or
# playwright-core missing -> guarded inside lib/harness.mjs.
# First run: `npm install` (pulls playwright-core; no browser download).
SMOKE_BIN_DIR := $(CURDIR)/bin

# Shared: build the binaries the harness drives. Used by both smoke targets.
smoke-build:
	@mkdir -p "$(SMOKE_BIN_DIR)"
	go build -o "$(SMOKE_BIN_DIR)/shipyard-smoke" ./cmd/shipyard/
	go build -o "$(SMOKE_BIN_DIR)/stubchild-smoke" ./internal/teststubchild/

smoke:
	@command -v node >/dev/null 2>&1 || { echo "SKIP: node unavailable (install Node.js to run the smoke harness)"; exit 0; }
	@$(MAKE) smoke-build
	SHIPYARD_BIN="$(SMOKE_BIN_DIR)/shipyard-smoke" \
	STUBCHILD_BIN="$(SMOKE_BIN_DIR)/stubchild-smoke" \
	node test/smoke/tool_browser_smoke.mjs

# smoke-full: the fast Tool Browser checks PLUS the Servers view checks.
# Each harness launches/tears down its own ephemeral instance, so they run
# sequentially and independently.
smoke-full:
	@command -v node >/dev/null 2>&1 || { echo "SKIP: node unavailable (install Node.js to run the smoke harness)"; exit 0; }
	@$(MAKE) smoke-build
	SHIPYARD_BIN="$(SMOKE_BIN_DIR)/shipyard-smoke" \
	STUBCHILD_BIN="$(SMOKE_BIN_DIR)/stubchild-smoke" \
	node test/smoke/tool_browser_smoke.mjs
	SHIPYARD_BIN="$(SMOKE_BIN_DIR)/shipyard-smoke" \
	STUBCHILD_BIN="$(SMOKE_BIN_DIR)/stubchild-smoke" \
	node test/smoke/servers_smoke.mjs

# Build and install the MCP bridge (used by Claude Code CLI / Desktop)
# Requires ad-hoc signing so macOS will allow Claude Code to spawn it.
build-mcp:
	go build -o .shipyard-dev/bin/ShipyardBridge ./cmd/shipyard-mcp/
	codesign -s - --force .shipyard-dev/bin/ShipyardBridge

install-mcp: build-mcp

test:
	go test ./...

snapshot:
	goreleaser release --snapshot --clean

release:
	goreleaser release --clean

# Desktop app targets (requires: go install github.com/wailsapp/wails/v3/cmd/wails3@latest)
wails-dev:
	wails3 dev

wails-build:
	wails3 task build

wails-build-server:
	wails3 task build:server

package-macos:
	wails3 task darwin:package

sign-macos:
	wails3 sign GOOS=darwin

notarize-macos:
	wails3 task darwin:sign:notarize
