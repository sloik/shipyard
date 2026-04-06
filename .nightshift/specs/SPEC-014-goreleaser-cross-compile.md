---
id: SPEC-014
priority: 14
type: nfr
status: draft
after: [SPEC-006]
created: 2026-04-06
---

# GoReleaser — Cross-Platform Build & Release

## Problem

Shipyard only builds for the host platform (macOS arm64). The product is positioned as cross-platform ("Browser DevTools for MCP"), but there is no build system to produce binaries for Linux or Windows. ADR-002 commits to "runs on macOS, Linux, and Windows from day one."

## Goal

Set up GoReleaser for automated cross-platform builds, checksums, and GitHub Releases. Produce 6 binaries on every tagged release.

## Target Platforms

| OS | Arch | Binary Name |
|----|------|-------------|
| macOS | arm64 | shipyard_darwin_arm64 |
| macOS | amd64 | shipyard_darwin_amd64 |
| Linux | arm64 | shipyard_linux_arm64 |
| Linux | amd64 | shipyard_linux_amd64 |
| Windows | amd64 | shipyard_windows_amd64.exe |
| Windows | arm64 | shipyard_windows_arm64.exe |

## Key Changes

### 1. `.goreleaser.yml`

```yaml
version: 2
project_name: shipyard

builds:
  - main: ./cmd/shipyard
    binary: shipyard
    env:
      - CGO_ENABLED=0
    goos:
      - darwin
      - linux
      - windows
    goarch:
      - amd64
      - arm64
    ldflags:
      - -s -w
      - -X main.version={{.Version}}
      - -X main.commit={{.Commit}}

archives:
  - format: tar.gz
    name_template: "{{ .ProjectName }}_{{ .Version }}_{{ .Os }}_{{ .Arch }}"
    format_overrides:
      - goos: windows
        format: zip

checksum:
  name_template: "checksums.txt"

changelog:
  sort: asc
  filters:
    exclude:
      - "^docs:"
      - "^chore:"
      - "^nightshift:"

release:
  github:
    owner: sloik
    name: shipyard
```

### 2. Version Injection (cmd/shipyard/main.go)

Add version variables:
```go
var (
  version = "dev"
  commit  = "none"
)
```

Add `--version` flag that prints `shipyard v0.2.0 (abc1234)`.

### 3. CGO_ENABLED=0

The project uses `github.com/ncruces/go-sqlite3` which is CGO-free. Verify all builds work with `CGO_ENABLED=0`. This is critical for cross-compilation without C toolchains.

### 4. Makefile (optional convenience)

```makefile
.PHONY: build test release snapshot

build:
	go build ./cmd/shipyard/

test:
	go test ./...

snapshot:
	goreleaser release --snapshot --clean

release:
	goreleaser release --clean
```

## Acceptance Criteria

- [ ] AC-1: `.goreleaser.yml` exists and is valid (`goreleaser check`)
- [ ] AC-2: `goreleaser release --snapshot --clean` produces 6 binaries
- [ ] AC-3: All binaries are statically linked (CGO_ENABLED=0)
- [ ] AC-4: `shipyard --version` prints version and commit hash
- [ ] AC-5: Archives use tar.gz for Unix, zip for Windows
- [ ] AC-6: Checksums file is generated

## Out of Scope

- Homebrew tap formula (deferred to post-release)
- Docker image builds
- Signing binaries
- Snap/Flatpak/AUR packaging

## Notes for Implementation

- Install goreleaser: `brew install goreleaser` or `go install github.com/goreleaser/goreleaser@latest`
- Test with `--snapshot` first (doesn't push to GitHub)
- The `ncruces/go-sqlite3` package uses Wasm-based SQLite — no CGO needed. Verify with `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build ./cmd/shipyard/`
- ldflags `-s -w` strips debug info, reducing binary size by ~30%

## Target Files

- `.goreleaser.yml` (new)
- `Makefile` (new)
- `cmd/shipyard/main.go` (add version vars + --version flag)
