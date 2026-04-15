.PHONY: build test snapshot release wails-dev wails-build build-mcp install-mcp

build:
	go build ./cmd/shipyard/

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

# Desktop app targets (requires: go install github.com/wailsapp/wails/v2/cmd/wails@latest)
wails-dev:
	cd cmd/shipyard && wails dev -skipbindings

wails-build:
	cd cmd/shipyard && wails build -skipbindings
