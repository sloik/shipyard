import Testing
import Foundation
@testable import ShipyardBridgeLib

@Suite("formatErrorText Tests")
struct FormatErrorTextTests {
    @Test("Returns Error: prefix with message")
    func returnsErrorPrefixWithMessage() {
        let result = formatErrorText("Connection failed")
        #expect(result == "Error: Connection failed")
    }

    @Test("Handles empty message")
    func handlesEmptyMessage() {
        let result = formatErrorText("")
        #expect(result == "Error: ")
    }

    @Test("Handles special characters in message")
    func handlesSpecialCharacters() {
        let result = formatErrorText("Socket error: connection reset")
        #expect(result == "Error: Socket error: connection reset")
    }

    @Test("Handles message with newlines")
    func handlesMessageWithNewlines() {
        let result = formatErrorText("Error line 1\nError line 2")
        #expect(result == "Error: Error line 1\nError line 2")
    }

    @Test("Handles very long message")
    func handlesVeryLongMessage() {
        let longMessage = String(repeating: "x", count: 1000)
        let result = formatErrorText(longMessage)
        #expect(result.hasPrefix("Error: "))
        #expect(result.count == 7 + 1000)
    }
}

@Suite("formatGatewayDiscoverResult Tests")
struct FormatGatewayDiscoverResultTests {
    @Test("Returns default message for nil data")
    func returnsDefaultMessageForNilData() {
        let result = formatGatewayDiscoverResult(nil)
        #expect(result == "No gateway tools available.")
    }

    @Test("Returns default message for missing tools key")
    func returnsDefaultMessageForMissingToolsKey() {
        let data: [String: Any] = [:]
        let result = formatGatewayDiscoverResult(data)
        #expect(result == "No gateway tools available.")
    }

    @Test("Returns default message for nil tools value")
    func returnsDefaultMessageForNilToolsValue() {
        let data: [String: Any] = ["tools": NSNull()]
        let result = formatGatewayDiscoverResult(data)
        #expect(result == "No gateway tools available.")
    }

    @Test("Returns default message for empty tools array")
    func returnsDefaultMessageForEmptyToolsArray() {
        let data: [String: Any] = ["tools": []]
        let result = formatGatewayDiscoverResult(data)
        #expect(result == "No gateway tools available.")
    }

    @Test("Formats single MCP with single tool correctly")
    func formatsSingleMcpWithSingleTool() {
        let data: [String: Any] = [
            "tools": [
                [
                    "mcp": "test_mcp",
                    "name": "test_tool",
                    "description": "A test tool",
                    "enabled": true
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        #expect(result.contains("Gateway Tools Catalog:"))
        #expect(result.contains("[test_mcp]"))
        #expect(result.contains("• test_tool"))
        #expect(result.contains("A test tool"))
        #expect(result.contains("[enabled]"))
    }

    @Test("Shows disabled status correctly")
    func showsDisabledStatusCorrectly() {
        let data: [String: Any] = [
            "tools": [
                [
                    "mcp": "test_mcp",
                    "name": "disabled_tool",
                    "description": "A disabled tool",
                    "enabled": false
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        #expect(result.contains("[disabled]"))
        #expect(!result.contains("[enabled]"))
    }

    @Test("Groups multiple tools by MCP")
    func groupsMultipleToolsByMcp() {
        let data: [String: Any] = [
            "tools": [
                [
                    "mcp": "mcp_alpha",
                    "name": "tool_a",
                    "description": "Tool A",
                    "enabled": true
                ],
                [
                    "mcp": "mcp_alpha",
                    "name": "tool_b",
                    "description": "Tool B",
                    "enabled": false
                ],
                [
                    "mcp": "mcp_beta",
                    "name": "tool_c",
                    "description": "Tool C",
                    "enabled": true
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        #expect(result.contains("[mcp_alpha]"))
        #expect(result.contains("[mcp_beta]"))
        #expect(result.contains("• tool_a"))
        #expect(result.contains("• tool_b"))
        #expect(result.contains("• tool_c"))
    }

    @Test("Sorts MCPs alphabetically")
    func sortsMcpsAlphabetically() {
        let data: [String: Any] = [
            "tools": [
                [
                    "mcp": "zebra_mcp",
                    "name": "tool_z",
                    "description": "Tool Z",
                    "enabled": true
                ],
                [
                    "mcp": "alpha_mcp",
                    "name": "tool_a",
                    "description": "Tool A",
                    "enabled": true
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        let alphaIndex = result.range(of: "[alpha_mcp]")?.lowerBound ?? result.endIndex
        let zebraIndex = result.range(of: "[zebra_mcp]")?.lowerBound ?? result.endIndex
        #expect(alphaIndex < zebraIndex)
    }

    @Test("Handles tool with missing description")
    func handlesMissingDescription() {
        let data: [String: Any] = [
            "tools": [
                [
                    "mcp": "test_mcp",
                    "name": "tool_no_desc",
                    "enabled": true
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        #expect(result.contains("no description"))
    }

    @Test("Handles tool with missing enabled status")
    func handlesMissingEnabledStatus() {
        let data: [String: Any] = [
            "tools": [
                [
                    "mcp": "test_mcp",
                    "name": "tool_no_enabled",
                    "description": "No enabled field"
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        #expect(result.contains("[disabled]"))
    }

    @Test("Handles tool with missing MCP name")
    func handlesMissingMcpName() {
        let data: [String: Any] = [
            "tools": [
                [
                    "name": "tool_no_mcp",
                    "description": "No MCP field",
                    "enabled": true
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        #expect(result.contains("[unknown]"))
    }

    @Test("Handles tool with missing name")
    func handlesMissingName() {
        let data: [String: Any] = [
            "tools": [
                [
                    "mcp": "test_mcp",
                    "description": "No name field",
                    "enabled": true
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        #expect(result.contains("• unknown"))
    }

    @Test("Formats multiple MCPs with multiple tools")
    func formatsMultipleMcpsWithMultipleTools() {
        let data: [String: Any] = [
            "tools": [
                [
                    "mcp": "mcp_one",
                    "name": "tool_1a",
                    "description": "First tool in MCP 1",
                    "enabled": true
                ],
                [
                    "mcp": "mcp_one",
                    "name": "tool_1b",
                    "description": "Second tool in MCP 1",
                    "enabled": false
                ],
                [
                    "mcp": "mcp_two",
                    "name": "tool_2a",
                    "description": "First tool in MCP 2",
                    "enabled": true
                ],
                [
                    "mcp": "mcp_two",
                    "name": "tool_2b",
                    "description": "Second tool in MCP 2",
                    "enabled": true
                ],
                [
                    "mcp": "mcp_three",
                    "name": "tool_3a",
                    "description": "Only tool in MCP 3",
                    "enabled": false
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        #expect(result.contains("Gateway Tools Catalog:"))
        #expect(result.contains("[mcp_one]"))
        #expect(result.contains("[mcp_three]"))
        #expect(result.contains("[mcp_two]"))
        #expect(result.contains("• tool_1a"))
        #expect(result.contains("• tool_1b"))
        #expect(result.contains("• tool_2a"))
        #expect(result.contains("• tool_2b"))
        #expect(result.contains("• tool_3a"))
    }

    @Test("Handles tools with special characters in descriptions")
    func handlesSpecialCharactersInDescriptions() {
        let data: [String: Any] = [
            "tools": [
                [
                    "mcp": "test_mcp",
                    "name": "special_tool",
                    "description": "Description with 'quotes' and \"double quotes\" & symbols",
                    "enabled": true
                ]
            ]
        ]
        let result = formatGatewayDiscoverResult(data)

        #expect(result.contains("Description with 'quotes' and \"double quotes\" & symbols"))
    }
}
