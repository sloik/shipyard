import Foundation

// MARK: - Tool Definitions

public struct ToolInputSchema: Encodable {
    public let type: String
    public let properties: [String: PropertyDef]
    public let required: [String]

    public struct PropertyDef: Encodable {
        public let type: String
        public let description: String?
        public let `default`: AnyCodable?

        public enum CodingKeys: String, CodingKey {
            case type
            case description
            case `default`
        }

        public init(type: String, description: String?, default: AnyCodable?) {
            self.type = type
            self.description = description
            self.`default` = `default`
        }

        public func encode(to encoder: Encoder) throws {
            var container = encoder.container(keyedBy: CodingKeys.self)
            try container.encode(type, forKey: .type)
            if let desc = description {
                try container.encode(desc, forKey: .description)
            }
            if let def = `default` {
                try container.encode(def, forKey: .default)
            }
        }
    }

    public init(type: String, properties: [String: PropertyDef], required: [String]) {
        self.type = type
        self.properties = properties
        self.required = required
    }
}

public struct ToolDef: Encodable {
    public let name: String
    public let description: String
    public let inputSchema: ToolInputSchema

    public init(name: String, description: String, inputSchema: ToolInputSchema) {
        self.name = name
        self.description = description
        self.inputSchema = inputSchema
    }
}

// MARK: - Management Tool Definitions

public func buildManagementTools() -> [ToolDef] {
    return [
        ToolDef(
            name: "shipyard_status",
            description: "Get status of all managed MCP servers",
            inputSchema: ToolInputSchema(
                type: "object",
                properties: [:],
                required: []
            )
        ),
        ToolDef(
            name: "shipyard_health",
            description: "Run health checks on all MCP servers",
            inputSchema: ToolInputSchema(
                type: "object",
                properties: [:],
                required: []
            )
        ),
        ToolDef(
            name: "shipyard_logs",
            description: "Retrieve logs from an MCP server",
            inputSchema: ToolInputSchema(
                type: "object",
                properties: [
                    "mcp_name": ToolInputSchema.PropertyDef(
                        type: "string",
                        description: "Name of the MCP server",
                        default: nil
                    ),
                    "lines": ToolInputSchema.PropertyDef(
                        type: "number",
                        description: "Number of log lines to retrieve",
                        default: .int(50)
                    ),
                    "level": ToolInputSchema.PropertyDef(
                        type: "string",
                        description: "Filter by log level (debug, info, warning, error)",
                        default: nil
                    )
                ],
                required: ["mcp_name"]
            )
        ),
        ToolDef(
            name: "shipyard_restart",
            description: "Restart an MCP server",
            inputSchema: ToolInputSchema(
                type: "object",
                properties: [
                    "mcp_name": ToolInputSchema.PropertyDef(
                        type: "string",
                        description: "Name of the MCP server to restart",
                        default: nil
                    )
                ],
                required: ["mcp_name"]
            )
        ),
        ToolDef(
            name: "shipyard_gateway_discover",
            description: "Discover all available tools from child MCPs",
            inputSchema: ToolInputSchema(
                type: "object",
                properties: [:],
                required: []
            )
        ),
        ToolDef(
            name: "shipyard_gateway_call",
            description: "Call a tool exposed by a child MCP",
            inputSchema: ToolInputSchema(
                type: "object",
                properties: [
                    "tool": ToolInputSchema.PropertyDef(
                        type: "string",
                        description: "Name of the tool to call (e.g., 'mcpname__toolname')",
                        default: nil
                    ),
                    "arguments": ToolInputSchema.PropertyDef(
                        type: "object",
                        description: "Tool arguments",
                        default: nil
                    )
                ],
                required: ["tool"]
            )
        ),
        ToolDef(
            name: "shipyard_gateway_set_enabled",
            description: "Enable or disable an MCP or specific tool",
            inputSchema: ToolInputSchema(
                type: "object",
                properties: [
                    "mcp_name": ToolInputSchema.PropertyDef(
                        type: "string",
                        description: "Name of the MCP to enable/disable",
                        default: nil
                    ),
                    "tool_name": ToolInputSchema.PropertyDef(
                        type: "string",
                        description: "Name of the tool to enable/disable",
                        default: nil
                    ),
                    "enabled": ToolInputSchema.PropertyDef(
                        type: "boolean",
                        description: "Whether to enable or disable",
                        default: .bool(true)
                    )
                ],
                required: []
            )
        )
    ]
}
