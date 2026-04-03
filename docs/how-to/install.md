# Install Shipyard

This guide covers both supported install paths:

- manual install for public releases
- build from source for contributors

## Prerequisites

- macOS
- Claude Desktop or Claude Code
- For source builds: Xcode 26 or newer

## Manual Install

### 1. Download and move the app

Download the latest `Shipyard.app` release and move it to `/Applications` or another stable app location.

### 2. Launch Shipyard once

Open `Shipyard.app`. On first launch, Shipyard prepares the runtime layout under `~/.shipyard/`:

- `~/.shipyard/bin/ShipyardBridge`
- `~/.shipyard/config/mcps.json`
- `~/.shipyard/data/shipyard.sock`
- `~/.shipyard/logs/`

### 3. Register Shipyard with Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` and add:

```json
{
  "mcpServers": {
    "shipyard": {
      "command": "$HOME/.shipyard/bin/ShipyardBridge"
    }
  }
}
```

Use the absolute path to `ShipyardBridge` in your home directory.

### 4. Register Shipyard with Claude Code

Edit `~/.claude/settings.json` and add the same entry:

```json
{
  "mcpServers": {
    "shipyard": {
      "command": "$HOME/.shipyard/bin/ShipyardBridge"
    }
  }
}
```

### 5. Restart your Claude client

Quit and reopen Claude Desktop or restart your Claude Code session so the MCP entry is reloaded.

## Build From Source

### 1. Clone the repository

```bash
git clone https://github.com/<your-org>/shipyard.git
cd shipyard
```

### 2. Build in Xcode

Open `Shipyard.xcodeproj` in Xcode 26 or newer, select the `Shipyard` scheme, and build or run the app.

CLI build example:

```bash
xcodebuild build \
  -project Shipyard.xcodeproj \
  -scheme Shipyard \
  -destination 'platform=macOS'
```

### 3. Run Shipyard once

Launch the built app from Xcode or from the build products folder. In development builds, Shipyard uses the repo-local `.shipyard-dev/` directory instead of `~/.shipyard/`.

### 4. Point Claude at the development bridge

For source builds, use the bridge binary prepared by the running development app. The development root is:

```text
<repo>/.shipyard-dev/
```

That directory contains:

- `bin/ShipyardBridge`
- `config/mcps.json`
- `data/shipyard.sock`
- `logs/`

## Swift Package Dependencies

Shipyard does not require external Swift Package Manager dependencies for the bridge package. `Package.swift` defines only local targets:

- `ShipyardBridgeLib`
- `ShipyardBridge`
- `ShipyardBridgeTests`

The app itself is built from `Shipyard.xcodeproj`.

## Verify The Install

After either install path:

1. Confirm `Shipyard.app` is running.
2. Confirm the bridge binary exists at the expected path.
3. Confirm the socket exists at `~/.shipyard/data/shipyard.sock` for installed builds.
4. Add one child MCP and verify its tools appear in Claude.

Next: [getting-started.md](../tutorial/getting-started.md)
