# How to Use the Gateway in Shipyard

The Gateway tab aggregates tools from all your managed MCP servers into a single, unified interface. Instead of configuring each MCP separately in Claude Desktop, you enable/disable servers and tools in the Gateway, then a single Shipyard entry in your Claude config gives agents access to all of them.

## Why Use the Gateway?

- **One config entry**: Claude Desktop only needs the Shipyard connection; all child MCPs are managed through Shipyard
- **Unified tool management**: Enable/disable entire servers or individual tools without restarting Claude
- **Fine-grained control**: Hide write-only tools, expose only safe read operations, or disable tools per agent needs
- **Live updates**: Changes take effect immediately on the next agent call — no Claude restart needed

## Prerequisites

- Shipyard.app is running
- At least one MCP server is running and registered (see: [How to Add a New MCP Server to Shipyard](./add-mcp-server.md))
- Claude Desktop is configured with ShipyardBridge (see: Step 5 below)

---

## Task 1: View All Available Gateway Tools

### Steps

1. **Open the Gateway tab**
   - Press **⌘2** or click the Gateway tab in Shipyard.app

2. **Review the tool list**
   - Tools are grouped by MCP server name (e.g., `anthropic`, `obsidian`, `jcodemunch`)
   - Under each server, you see all available tools with their namespaced names (e.g., `mcp__anthropic__get_profile`)

3. **Read tool details**
   - Click or hover over a tool to see its description
   - Inspect the input schema to understand required/optional parameters
   - Note the enabled state (green toggle = enabled, gray = disabled)

### Example

```
Gateway Tools
├─ anthropic (MCP Server)
│  ├─ mcp__anthropic__get_profile
│  │  Description: Retrieve user profile information
│  │  Input: { user_id: string (required) }
│  │  Enabled: ✓
│  └─ mcp__anthropic__list_models
│     Description: List available models
│     Enabled: ✓
├─ jcodemunch (MCP Server)
│  └─ mcp__jcodemunch__search_symbols
│     Description: Search for symbols in indexed repositories
│     Enabled: ✓
```

---

## Task 2: Enable/Disable an Entire MCP Server's Tools

Use this when you want to quickly toggle all tools from a server on or off (e.g., temporarily disable an unstable server).

### Steps

1. **Open the Gateway tab** (⌘2)

2. **Locate the MCP server section header**
   - Find the server name (e.g., "anthropic", "obsidian")

3. **Toggle the MCP-level switch**
   - Click the toggle next to the server name
   - A green toggle = all tools from that server are enabled
   - A gray toggle = all tools are disabled

4. **Verify the change**
   - All tools under that server should reflect the new state (green or gray)
   - The change takes effect immediately

### Example

To disable all Obsidian tools:
1. Press ⌘2 (Gateway tab)
2. Find "obsidian" in the list
3. Click the toggle next to "obsidian" → it turns gray
4. All Obsidian tools are now disabled
5. Agents will not see these tools on their next call

---

## Task 3: Enable/Disable Individual Tools

Use this for fine-grained control — e.g., expose only read tools and hide write operations, or disable a specific problematic tool.

### Steps

1. **Open the Gateway tab** (⌘2)

2. **Find the tool in the list**
   - Locate it under its MCP server section

3. **Toggle the tool-level switch**
   - Click the toggle next to the tool name
   - Green = enabled, gray = disabled

4. **Note precedence**
   - Tool-level toggles override server-level toggles
   - If a server is disabled but a specific tool is enabled, the tool stays enabled
   - This allows exceptions: e.g., "disable all anthropic tools except get_profile"

### Example

To expose only read operations from Obsidian:
1. Press ⌘2 (Gateway tab)
2. Under "obsidian", disable these tools:
   - `mcp__obsidian__obsidian_append_content` → gray
   - `mcp__obsidian__obsidian_delete_file` → gray
   - `mcp__obsidian__obsidian_patch_content` → gray
3. Keep these enabled:
   - `mcp__obsidian__obsidian_get_file_contents` → green
   - `mcp__obsidian__obsidian_simple_search` → green
4. Agents can now read and search but cannot modify files

---

## Task 4: Refresh the Tool Catalog

Use this after adding/removing servers, or if you suspect a server's tool list is out of sync.

### Steps

1. **Press ⌘R** (Refresh)
   - Or go to menu: **Server** → **Refresh**

2. **Wait for discovery to complete**
   - Shipyard re-connects to all running MCPs and queries their available tools
   - The Gateway tab updates with any new or removed tools

3. **Check the Servers tab (⌘1) for errors**
   - If a server isn't responding, it may not be running
   - See Troubleshooting (Task 6) for next steps

### When to refresh

- After starting a new MCP server
- After stopping/removing an MCP server
- After an MCP server is updated with new tools
- If tools mysteriously disappear or appear out of sync

---

## Task 5: Connect Claude Desktop to the Gateway

Once tools are configured in the Gateway, connect Claude Desktop to receive them.

### Steps

1. **Go to the Config tab**
   - Press **⌘4** or click the Config tab in Shipyard.app

2. **Generate the configuration**
   - Click **"Copy Config"** or **"Copy with Secrets"**
   - The config includes the ShipyardBridge, which automatically connects Claude to the Gateway

3. **Open Claude Desktop config**
   - On macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - On Windows: `%APPDATA%\Claude\claude_desktop_config.json`

4. **Paste the Shipyard entry**
   - Replace or add the Shipyard block from step 2
   - Example:
     ```json
     {
       "mcps": {
         "shipyard": {
           "command": "...",
           "args": ["..."],
           "env": { "..." }
         }
       }
     }
     ```

5. **Restart Claude Desktop**
   - Quit Claude Desktop completely
   - Reopen it
   - All enabled Gateway tools should now appear in the tools list

6. **Verify in Claude**
   - Open Claude Desktop
   - Go to Tools (bottom left) or click the tool icon
   - You should see tools grouped by server name

---

## Task 6: Troubleshoot Missing Tools

If tools don't appear in the Gateway or aren't available in Claude, work through these steps.

### Step 1: Verify the MCP server is running

1. **Open the Servers tab** (⌘1)
2. **Find the MCP server** in the list
3. **Check the status**
   - Green circle = running
   - Red circle = stopped or error
   - If red, click **Start** to launch the server
4. **Check System Logs** (⌘3) for startup errors

### Step 2: Verify the MCP is enabled in the Gateway

1. **Open the Gateway tab** (⌘2)
2. **Find the MCP server** section
3. **Check the server-level toggle**
   - If gray, click it to enable the entire server
4. **Check individual tool toggles**
   - Make sure the specific tool you need isn't disabled (gray)

### Step 3: Refresh the tool catalog

1. **Press ⌘R** or go to **Server** → **Refresh**
2. **Wait for discovery to complete**
3. **Check the Gateway tab again**
   - If tools still don't appear, the server may not be responding

### Step 4: Check System Logs for errors

1. **Open System Logs** (⌘3)
2. **Search for the server name**
3. **Look for error messages**
   - "Connection refused" = server isn't listening
   - "Tool discovery failed" = server is running but not responding to tool queries
   - "Unknown tool" = server tool isn't registered properly

### Step 5: Restart the server

1. **Go to Servers tab** (⌘1)
2. **Stop the server** (click Stop or press ⌘⇧S)
3. **Wait 2 seconds**
4. **Start the server** (click Start)
5. **Refresh the Gateway** (⌘R)

### Step 6: Verify Claude Desktop config

1. **Go to Config tab** in Shipyard
2. **Click "Copy Config"** to get the latest configuration
3. **Open Claude Desktop config** file (path from Task 5, Step 3)
4. **Paste the new Shipyard block**
5. **Restart Claude Desktop**
6. **Check Tools in Claude** — tools should now appear

### If tools still don't appear

- Check that Shipyard.app is still running
- Ensure the MCP server process is healthy (no memory leaks, crashes)
- Try restarting Shipyard.app completely
- Check the macOS Console.app for system-level errors from Shipyard

---

## Quick Reference

| Action | Keyboard | Menu |
|--------|----------|------|
| Open Gateway | ⌘2 | — |
| Refresh tools | ⌘R | Server → Refresh |
| View Servers | ⌘1 | — |
| View System Logs | ⌘3 | — |
| View Config | ⌘4 | — |
| View Secrets | ⌘5 | — |
| Start all servers | ⌘⇧S | Server → Start All |
| Stop all servers | ⌘⇧X | Server → Stop All |

---

## Next Steps

- [How to Add a New MCP Server to Shipyard](./add-mcp-server.md)
- [How to Configure Secrets for MCP Servers](./configure-secrets.md)
- [How to Debug a Stuck MCP Server](./debug-stuck-server.md)
