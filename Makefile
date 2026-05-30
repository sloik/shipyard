.PHONY: build test snapshot release wails-dev wails-build wails-build-server package-macos sign-macos notarize-macos build-mcp install-mcp

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

# Desktop app targets (requires: go install github.com/wailsapp/wails/v3/cmd/wails3@latest)
wails-dev:
	wails3 dev

wails-build:
	wails3 task build

wails-build-server:
	wails3 task build:server

package-macos:
	wails3 package GOOS=darwin

sign-macos:
	wails3 sign GOOS=darwin

notarize-macos:
	wails3 task darwin:sign:notarize
