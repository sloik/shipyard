import Testing
import Foundation
@testable import ShipyardBridgeLib

@Suite("ToolDefinitions")
struct ToolDefinitionsTests {

    @Test("buildManagementTools returns 7 tools")
    func returnsSevenTools() {
        let tools = buildManagementTools()
        #expect(tools.count == 7)
    }

    @Test("all management tools have shipyard_ prefix")
    func allToolsHavePrefix() {
        let tools = buildManagementTools()
        for tool in tools {
            #expect(tool.name.hasPrefix("shipyard_"), "Tool '\(tool.name)' should start with shipyard_")
        }
    }

    @Test("all expected tool names are present")
    func expectedToolNamesPresent() {
        let tools = buildManagementTools()
        let names = Set(tools.map { $0.name })
        let expected: Set<String> = [
            "shipyard_status", "shipyard_health", "shipyard_logs",
            "shipyard_restart", "shipyard_gateway_discover",
            "shipyard_gateway_call", "shipyard_gateway_set_enabled"
        ]
        #expect(names == expected)
    }

    @Test("all tools have non-empty descriptions")
    func allToolsHaveDescriptions() {
        let tools = buildManagementTools()
        for tool in tools {
            #expect(!tool.description.isEmpty, "Tool '\(tool.name)' should have a description")
        }
    }

    @Test("all tool schemas have type object")
    func allSchemasAreObjects() {
        let tools = buildManagementTools()
        for tool in tools {
            #expect(tool.inputSchema.type == "object", "Tool '\(tool.name)' schema type should be object")
        }
    }

    @Test("shipyard_logs requires mcp_name")
    func logsRequiresMcpName() {
        let tools = buildManagementTools()
        let logsTool = tools.first { $0.name == "shipyard_logs" }!
        #expect(logsTool.inputSchema.required.contains("mcp_name"))
    }

    @Test("shipyard_logs lines property has default 50")
    func logsLinesDefault() {
        let tools = buildManagementTools()
        let logsTool = tools.first { $0.name == "shipyard_logs" }!
        let linesProp = logsTool.inputSchema.properties["lines"]
        #expect(linesProp != nil)
        if case .int(50) = linesProp?.default {
            // correct
        } else {
            Issue.record("lines default should be .int(50)")
        }
    }

    @Test("shipyard_restart requires mcp_name")
    func restartRequiresMcpName() {
        let tools = buildManagementTools()
        let tool = tools.first { $0.name == "shipyard_restart" }!
        #expect(tool.inputSchema.required.contains("mcp_name"))
    }

    @Test("shipyard_gateway_call requires tool parameter")
    func gatewayCallRequiresTool() {
        let tools = buildManagementTools()
        let tool = tools.first { $0.name == "shipyard_gateway_call" }!
        #expect(tool.inputSchema.required.contains("tool"))
    }

    @Test("shipyard_status has empty schema")
    func statusHasEmptySchema() {
        let tools = buildManagementTools()
        let tool = tools.first { $0.name == "shipyard_status" }!
        #expect(tool.inputSchema.properties.isEmpty)
        #expect(tool.inputSchema.required.isEmpty)
    }

    @Test("shipyard_gateway_set_enabled has enabled default true")
    func setEnabledHasDefaultTrue() {
        let tools = buildManagementTools()
        let tool = tools.first { $0.name == "shipyard_gateway_set_enabled" }!
        let enabledProp = tool.inputSchema.properties["enabled"]
        #expect(enabledProp != nil)
        if case .bool(true) = enabledProp?.default {
            // correct
        } else {
            Issue.record("enabled default should be .bool(true)")
        }
    }

    @Test("ToolDef can be encoded to JSON")
    func toolDefIsEncodable() throws {
        let tool = buildManagementTools()[0]
        let data = try JSONEncoder().encode(tool)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        #expect(json?["name"] as? String == tool.name)
        #expect(json?["description"] as? String == tool.description)
        #expect(json?["inputSchema"] != nil)
    }
}
