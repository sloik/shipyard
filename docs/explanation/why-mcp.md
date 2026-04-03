# Why MCP Matters: Context, Challenges, and the Shipyard Solution

## The Problem: Connecting AI Agents to the Outside World

Before MCP, integrating external tools into AI systems was ad-hoc and fragmented. Every AI application that needed to call external APIs, access databases, or invoke custom services had to build its own integration layer. This meant duplicating effort, inventing custom protocols, and managing multiple connection mechanisms—all outside the agent's control.

The real constraint wasn't technical capability: Claude and other large language models can already call functions if you build an integration for them. The constraint was standardization. Without a shared protocol, each tool provider had to support N different integration patterns, and each AI application had to reinvent the wheel for every new tool.

MCP (Model Context Protocol) exists to solve this fundamental problem: it provides a single, standard way for AI agents to discover and invoke external tools and data sources.

## How MCP Works: A Lightweight Protocol for Tool Integration

MCP is built on JSON-RPC 2.0 over stdio. That simplicity is intentional. Rather than requiring complex WebSocket servers or custom authentication schemes, an MCP server is any process that speaks JSON-RPC—typically launched by the application that needs its tools. Messages flow between the agent and the server as newline-delimited JSON.

The protocol handshake is minimal. When an agent connects to an MCP server, it sends an `initialize` request, the server responds with its capabilities, and that's it. After initialization, the agent can ask the server to list its available tools using the `tools/list` request. Each tool has a schema—name, description, and input parameters—that tells the agent how to invoke it.

When the agent wants to call a tool, it sends a `tools/call` request with the tool name and parameters. The server processes the request and returns a result (or an error). This happens synchronously, making it easy to reason about. No pub-sub machinery, no event queues, no complex state management—just request-response, over and over.

The protocol also includes notifications: the server can push updates to the agent without waiting for a request. This is useful for status changes or long-running operations, but it's optional. The core of MCP is stateless request-response.

This minimalism is key to MCP's viability. It can run in any language, on any platform, with minimal dependencies. A tool provider can implement an MCP server in a weekend. An application developer can integrate it just as quickly.

## The Ecosystem Problem: Too Many Servers, Not Enough Observability

As MCP adoption grows, the practical challenges become clear. A single agent might need access to dozens of MCP servers—one for GitHub operations, one for AWS APIs, one for database access, one for internal services, and so on. Each server is a separate process that needs to be launched, monitored, and kept alive.

Managing N independent MCP servers creates operational friction:

**Lifecycle management** becomes tedious. You have to start servers in the right order, handle startup failures, restart them when they crash, and gracefully shut them down. If a server isn't running, the agent can't access its tools, but figuring out why requires checking logs scattered across the filesystem.

**Visibility suffers** because each server logs to its own sink. Debugging a tool integration means hunting through multiple log files, piecing together requests and responses across processes. There's no unified view of which tools are healthy, which servers are slow, or what failed recently.

**Security and secrets** become scattered. Each server might need API keys, database credentials, or OAuth tokens. These need to be injected at startup, rotated securely, and never exposed to the agent directly. Without a coordinated system, managing credentials at scale is error-prone.

**Connection complexity** means the agent needs N separate connections, one to each MCP server. This multiplies resource usage and makes it harder to implement features like request rate limiting, caching, or priority handling across tools.

## Shipyard's Solution: Unified Lifecycle and Gateway Aggregation

Shipyard addresses these challenges by sitting between the agent and the MCP ecosystem. It's both a lifecycle manager for MCP servers and an MCP server itself—specifically, an MCP gateway.

As a **lifecycle manager**, Shipyard handles process orchestration. When you tell Shipyard to manage an MCP server, it owns starting, stopping, restarting, and monitoring that process. If a server crashes, Shipyard knows to restart it. If startup fails, Shipyard logs the failure and can retry with backoff. This shifts MCP server management from manual scripting to declarative configuration.

As an **MCP gateway**, Shipyard runs its own MCP server called ShipyardBridge. This bridge is itself an MCP server that aggregates tools from all the child servers Shipyard manages. Instead of the agent opening N connections to N servers, it opens one connection to ShipyardBridge. When the agent asks for tools, ShipyardBridge lists all tools from all children. When the agent calls a tool, ShipyardBridge routes the request to the appropriate child server and returns the result.

This gateway pattern delivers three immediate benefits:

**Unified observability** emerges naturally. Shipyard logs all server events (start, stop, crash, health checks) and can aggregate health status across the fleet. You get one dashboard, one log stream, one source of truth about what's running and why.

**Simplified security** becomes possible because Shipyard can be the single point where secrets are injected. Rather than distributing credentials to each server at launch, Shipyard can manage secrets in macOS Keychain and pass them to servers only when needed. The agent never sees credentials directly.

**Efficient resource usage** because the agent has one connection, not N. Shipyard can implement cross-tool features like request deduplication, caching, and rate limiting at the gateway level, benefiting all tools without duplicating that logic in each server.

## MCP's Broader Significance: Becoming the AI Tool Standard

Beyond Shipyard's specific role, MCP represents a larger inflection point in AI infrastructure. For years, each AI application built its own tool-calling interface. Claude Desktop has its own, Claude Code has its own, different LLM providers have different conventions. This fragmentation raises barriers: tool providers have to support multiple standards, and applications can't easily swap components.

MCP is becoming the shared language. Anthropic has backed it as an open standard, major AI platforms are adopting it, and the ecosystem of MCP server implementations is growing rapidly. This creates a virtuous cycle: as more tools expose MCP servers, it becomes more attractive for applications to adopt MCP support, which justifies more tool implementations.

The longer-term value of MCP isn't any single feature—JSON-RPC over stdio is not revolutionary on its own. The value is network effects: a standard protocol means tool developers and application developers can work independently, creating an ecosystem rather than point-to-point integrations.

## Where Shipyard Fits in This Evolution

Shipyard is an early-stage component in this emerging ecosystem. Its job is to make MCP practical at scale—to handle the operational complexity that arises when you have many servers and want to maintain observability and security.

As the ecosystem matures, Shipyard's specific responsibilities might evolve. Some features might move into MCP itself, some might move into application frameworks, and some might become platform conventions. But the underlying need—managing many tool sources and presenting them to an agent in a unified, observable, secure way—will remain core to any serious AI agent platform.

For now, Shipyard is the bridge between the ideal of "one protocol for all tools" and the reality of "managing many tool servers reliably." It's the missing piece that makes MCP practical.
