.PHONY: build test snapshot release

build:
	go build ./cmd/shipyard/

test:
	go test ./...

snapshot:
	goreleaser release --snapshot --clean

release:
	goreleaser release --clean
