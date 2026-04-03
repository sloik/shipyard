# The Gateway Pattern: Aggregating Tools from Many MCP Servers

## The N×M Problem Without a Gateway

When Shipyard first managed multiple MCP servers, a fundamental scaling problem emerged. Imagine you have three MCP servers running: `mac-runner`, `lmstudio`, and `database-query`. Each server exports its own set of tools.

In a world without a gateway, every AI agent (Claude Desktop, Claude Code, etc.) must be configured with **separate MCP entries** for each server. The Claude Desktop `mcp.json` might look like this:

```json
{
  "mcpServers": {
    "mac-runner": {"command": "shipyard-bridge", "args": ["--server", "mac-runner"]},
    "lmstudio": {"command": "shipyard-bridge", "args": ["--server", "lmstudio"]},
    "database-query": {"command": "shipyard-bridge", "args": ["--server", "database-query"]}
  }
}
```

This creates the N×M problem: **N servers × M agents = N×M configuration changes every time you add or remove a server**. Add a fourth server, and you must edit three agent configs. Remove a server, same story. Every agent maintainer becomes responsible for knowing what servers exist and keeping their config in sync.

At scale—imagine ten MCP servers and a dozen applications using them—this becomes operationally untenable. Servers become stale in configurations. Agents try to use tools from servers that no longer exist. There's no single source of truth about which tools are available.

## Gateway Aggregation: One Connection, One Catalog

The gateway pattern solves this by introducing a **single aggregation point**: Shipyard itself becomes an MCP server (via ShipyardBridge) that discovers tools from all child servers and re-exposes them under a unified namespace.

Now, every agent connects to **one MCP entry**: ShipyardBridge. Behind the scenes, Shipyard's GatewayRegistry discovers tools from all running child MCPs using the standard MCP `tools/list` request. These tools are then namespaced and re-exposed to the agent.

The agent sees a single, unified tool catalog:
- `mac-runner__run_command`
- `mac-runner__check_process`
- `lmstudio__load_model`
- `lmstudio__inference`
- `database-query__select`
- `database-query__insert`

When Shipyard adds a fourth server, the agent automatically sees its tools in the next discovery cycle—no config changes needed. When a server is removed, those tools disappear from the catalog. The agent's configuration never changes; Shipyard handles all the plumbing.

This flips the scaling problem from O(N×M) to O(N): **N servers, M agents, one MCP config entry per agent**. The complexity moves entirely into Shipyard, where it belongs.

## Tool Namespacing: The Double-Underscore Convention

The gateway aggregates tools from many servers, but all tools must have unique names visible to the agent. Shipyard uses a simple, consistent convention: **`{mcp_name}__{tool_name}`** (double underscore).

Why double underscore? Several reasons:

**Collision avoidance**: two servers could both export a tool named `status`. Without namespacing, the second one would overwrite the first in the agent's catalog. With namespacing (`mac-runner__status` vs. `lmstudio__status`), both coexist.

**Pattern matching**: Claude Code and other Claude applications use this same double-underscore convention internally for namespaced tools. This consistency makes the gateway pattern feel native to the Claude ecosystem rather than a special case.

**Parseability**: tools are often inspected and invoked programmatically. The double underscore is unambiguous and easy to split (`"mac-runner__run_command".split("__")`). It's not a common character in tool names, so false positives are unlikely.

The namespacing is transparent to the user: they see `mac-runner__run_command` in the tool list, understand that it's the `run_command` tool from `mac-runner`, and invoke it like any other tool. The gateway handles extracting the MCP name and delegating the request correctly.

## Enable/Disable Controls: Fine-Grained Access

Raw aggregation isn't enough. Users need control over **which tools are available**. Shipyard provides a two-level toggle system, persisted in macOS UserDefaults:

**MCP-level toggle**: disable all tools from one server at once. This is useful when you want to temporarily prevent an agent from accessing a specific server without removing the server itself. For example, disable `lmstudio` while updating its model weights.

**Tool-level toggle**: disable individual tools while keeping the server running. This is useful for security or operational reasons. You might disable `database-query__delete` in untrusted contexts while keeping `database-query__select` available for read-only access.

Both toggles are applied at the gateway. When an agent requests the tool catalog, GatewayRegistry filters out disabled tools before returning the list. When an agent calls a tool, the gateway checks both the MCP-level and tool-level enable flags before forwarding the request. If either flag is disabled, the gateway returns an error: "Tool not available."

This control is **persistent** across app restarts because it's backed by UserDefaults. It's also **observable** in the Shipyard UI (Gateway tab), where users can see which tools are enabled and toggle them without restarting anything.

The enable/disable system is simpler than configuration generation: you don't need to edit config files, restart agents, or deploy anything. Changing a toggle in the GUI immediately affects tool availability for all connected agents.

## Request Forwarding: The Path a Tool Call Takes

When an agent calls a tool through the gateway, a multi-hop request path is triggered. Understanding this path clarifies why the gateway adds latency but remains practical.

**Step 1: Agent to ShipyardBridge**. Claude sends an MCP JSON-RPC 2.0 `tools/call` request to ShipyardBridge's stdin with the tool name (e.g., `mac-runner__run_command`) and arguments.

**Step 2: ShipyardBridge to SocketServer**. ShipyardBridge parses the request, extracts the MCP name and tool name, and sends a `gateway_call` request over the Unix domain socket to Shipyard.app's SocketServer. The request includes the MCP name, tool name, and arguments.

**Step 3: SocketServer to GatewayRegistry**. SocketServer's `handleGatewayCall()` handler passes the request to GatewayRegistry, which validates that the MCP is running, the tool exists, and both MCP-level and tool-level enables are true. If validation fails, it returns an error immediately.

**Step 4: GatewayRegistry to MCPBridge**. If validation passes, GatewayRegistry looks up the MCPBridge for that specific MCP server and forwards the request.

**Step 5: MCPBridge to Child MCP**. MCPBridge sends a standard MCP JSON-RPC 2.0 `tools/call` request to the child MCP's stdin, preserving the original tool name (without the namespace prefix). It includes a unique request `id` so it can correlate the response.

**Step 6: Child MCP responds**. The child MCP processes the tool call and writes its result to stdout as a JSON-RPC response with the matching `id`.

**Step 7: MCPBridge to SocketServer**. MCPBridge reads the child's response, correlates it by `id`, and sends the result back to SocketServer.

**Step 8: SocketServer to ShipyardBridge**. SocketServer writes the result to the socket.

**Step 9: ShipyardBridge to Agent**. ShipyardBridge reads the result from the socket and writes it to stdout as an MCP JSON-RPC response to the agent.

Each hop introduces a small amount of latency (socket I/O, JSON serialization/deserialization, validation logic). In practice, this is negligible for most tools—a few milliseconds per request. The trade-off is worth it for the operational benefits: unified observability, enable/disable control, and simplified agent configuration.

## Hot-Reload: The Catalog Stays Current

Tools are discovered dynamically. When an MCP starts, stops, or restarts, Shipyard can detect this and update its tool catalog without requiring an app restart or agent reconnection.

**Discovery on lifecycle events**: ProcessManager detects when a child MCP process exits or is restarted. When this happens, it signals GatewayRegistry to re-run `tools/list` on the child, updating the catalog entry for that MCP.

**Manual refresh**: Users can also request an immediate refresh from the Gateway tab UI, which re-discovers tools from all running MCPs.

**Agent-visible updates**: Agents can call `tools/list` at any time. Because GatewayRegistry applies the current state of the catalog and enable/disable flags on every `tools/list` call, agents always see the current set of available tools. If an MCP crashed and restarted, tools reappear automatically (assuming they're enabled).

This hot-reload behavior means the tool catalog is **always fresh**. Agents don't get stuck with stale references to tools that no longer exist, and new tools become immediately available when their MCP starts.

## Trade-Offs: Why the Gateway Pattern Imposes Costs

The gateway pattern is operationally powerful, but it introduces costs that must be acknowledged.

**Single point of failure**: if Shipyard crashes or the SocketServer becomes unresponsive, all tool access fails. Every agent loses all tools at once. This is a harder failure mode than having independent MCP connections (where one server's crash wouldn't affect the others). Mitigating this requires robust health checking, automatic app restarts, and possibly redundancy—all costs.

**Additional latency**: every tool call hops through an extra process (ShipyardBridge) and socket. For latency-sensitive tools or high-throughput scenarios, this can matter. The gateway isn't a bottleneck for typical use (tool calls are typically on the order of seconds), but it's not invisible either.

**State synchronization complexity**: GatewayRegistry must stay in sync with running MCPs. If a child MCP crashes unexpectedly, GatewayRegistry might not know immediately. If a tool changes or disappears, the cached schema could become stale. These are solvable (periodic re-discovery, aggressive timeout handling), but they add implementation complexity that wouldn't exist with direct connections.

**Protocol overhead**: the gateway introduces two additional MCP protocols: `gateway_discover` (to list tools) and `gateway_set_enabled` (to toggle availability). The bridge must handle these in addition to standard `tools/list` and `tools/call` requests. This adds code and testing burden.

These costs are acceptable because they're front-loaded: Shipyard pays them once, on behalf of all agents. Without the gateway, every agent would have to pay the cost of managing N server connections and tracking enable/disable state independently.

## Comparison to Alternatives

Three approaches were considered for managing multiple MCPs.

**No gateway** — each agent configures child MCPs directly. Pros: minimal latency, no central failure point. Cons: O(N×M) configuration burden, no centralized observability, agents duplicate effort for enable/disable logic. This doesn't scale beyond a handful of servers and agents.

**Configuration generation** — Shipyard scans for running MCPs and generates agent config files (e.g., `claude_desktop_config.json`), but agents connect directly to child MCPs. Pros: simpler than a gateway, agents still have direct connections. Cons: agents still need to reconfigure when servers change, no centralized enable/disable, benefits of unified observability are lost.

**Gateway aggregation** (chosen) — Shipyard re-exposes all tools under one namespace. Pros: O(N) config burden, centralized observability, fine-grained access control, hot-reload. Cons: additional latency, single point of failure, more complex.

The gateway pattern was chosen because it delivers the most operational value as Shipyard scaled beyond a handful of MCPs. The alternatives become impractical when you're managing more than a few servers or want to maintain security policies across many tools.

## Implementation Details: See ADR 0003

The architectural decision to adopt the gateway pattern is formally documented in **ADR 0003: Gateway Pattern — Single MCP Entry Point**. That document records the decision context, alternatives considered, rationale, design, and consequences.

This explanation document provides the conceptual background and reasoning: why the N×M problem matters, how the gateway solves it, what design choices (namespacing, enable/disable, hot-reload) make the pattern practical, and why the trade-offs are worth it.

---

*Last updated: 2026-03-16*
