.PHONY: build test snapshot release wails-dev wails-build

build:
	go build ./cmd/shipyard/

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
