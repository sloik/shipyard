.PHONY: build test race coverage coverage-check coverage-check-probe format-check lint type-check script-check quality quality-self-test tools smoke smoke-build smoke-full deploy-runtime snapshot release wails-dev wails-build wails-build-server package-macos sign-macos notarize-macos build-mcp install-mcp

TOOLS_BIN := $(CURDIR)/.tools/bin
STATICCHECK := $(TOOLS_BIN)/staticcheck
ACTIONLINT := $(TOOLS_BIN)/actionlint

# The tool versions are pinned in tools/go.mod and tools/go.sum. Keeping the
# bootstrap in-repo makes local and CI analyzer behavior identical.
tools: $(STATICCHECK) $(ACTIONLINT)

$(STATICCHECK): tools/go.mod tools/go.sum
	@mkdir -p "$(TOOLS_BIN)"
	cd tools && go build -mod=readonly -o "$@" honnef.co/go/tools/cmd/staticcheck

$(ACTIONLINT): tools/go.mod tools/go.sum
	@mkdir -p "$(TOOLS_BIN)"
	cd tools && go build -mod=readonly -o "$@" github.com/rhysd/actionlint/cmd/actionlint

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
SMOKE_BIN_DIR := $(CURDIR)/build/smoke

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

# Builds, smoke-tests, and then atomically promotes the sole launchd runtime.
# The script refuses to archive legacy binaries until launchd proves the
# canonical runtime is live.
deploy-runtime:
	scripts/deploy-canonical-runtime.sh

# Build and install the MCP bridge (used by Claude Code CLI / Desktop)
# Requires ad-hoc signing so macOS will allow Claude Code to spawn it.
build-mcp:
	go build -o .shipyard-dev/bin/ShipyardBridge ./cmd/shipyard-mcp/
	codesign -s - --force .shipyard-dev/bin/ShipyardBridge

install-mcp: build-mcp

test:
	go test -count=1 ./...

race:
	go test -race -count=1 -timeout 5m ./...

# The checked-in baseline is a floor, never an automatically rewritten target.
# `coverage` emits a fresh, deterministic report; `coverage-check` makes that
# report blocking for both CI and Nightshift.
coverage:
	python3 scripts/coverage_ratchet.py collect

coverage-check: coverage
	python3 scripts/coverage_ratchet.py check

# A controlled regression fixture proves the ratchet rejects both a lower total
# and a lower package floor. It succeeds only when the check rejects it.
coverage-check-probe:
	@! python3 scripts/coverage_ratchet.py check --report .nightshift/coverage-fixtures/regressed.json

format-check:
	@unformatted="$$(git ls-files '*.go' | xargs gofmt -l)"; test -z "$$unformatted" || { echo "Go files require gofmt:"; printf '%s\n' "$$unformatted"; exit 1; }

lint: tools
	"$(STATICCHECK)" ./...

type-check:
	go vet ./...

script-check: tools
	"$(ACTIONLINT)" .github/workflows/*.yml
	node scripts/check-js-syntax.mjs internal/web/ui/ds.js internal/web/ui/index.html
	zsh -n scripts/*.sh

# The canonical blocking quality contract. CI and local development must call
# this target rather than duplicating a subset of its checks.
quality: format-check lint type-check script-check build test race

# Negative probes prove that each static gate is capable of rejecting malformed
# input. They are intentionally separate from the normal quality target.
quality-self-test: tools
	scripts/quality-negative-tests.sh "$(STATICCHECK)" "$(ACTIONLINT)"

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
