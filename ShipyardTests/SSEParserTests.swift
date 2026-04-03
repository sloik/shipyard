import Foundation
import Testing
@testable import Shipyard

/// Test suite for SSEParser
@Suite("SSEParser Tests")
struct SSEParserTests {
    
    // MARK: - Basic Parsing
    
    @Test("Parse single SSE event with JSON data")
    func testParseSingleEvent() {
        let sse = """
        event: message
        data: {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "hello"}]}}
        
        """
        
        let events = SSEParser.parseEvents(from: sse)
        #expect(events.count == 1)
        #expect(events[0].eventType == "message")
        #expect(events[0].data?.contains("hello") == true)
    }
    
    @Test("Parse multiple SSE events")
    func testParseMultipleEvents() {
        let sse = """
        event: message
        data: {"jsonrpc": "2.0", "id": 1, "result": "first"}
        
        event: message
        data: {"jsonrpc": "2.0", "id": 2, "result": "second"}
        
        """
        
        let events = SSEParser.parseEvents(from: sse)
        #expect(events.count == 2)
        #expect(events[0].eventType == "message")
        #expect(events[1].eventType == "message")
    }
    
    // MARK: - Multi-line Data Fields
    
    @Test("Parse SSE event with multi-line data field")
    func testParseMultilineData() {
        let sse = """
        event: message
        data: {"jsonrpc": "2.0",
        data: "id": 1,
        data: "result": {"text": "multi-line"}}
        
        """
        
        let events = SSEParser.parseEvents(from: sse)
        #expect(events.count == 1)
        
        let dataString = events[0].data
        #expect(dataString?.contains("jsonrpc") == true)
        #expect(dataString?.contains("multi-line") == true)
        // Data lines should be joined with newlines
        #expect(dataString?.contains("\n") == true)
    }
    
    // MARK: - Comments and Edge Cases
    
    @Test("Ignore SSE comments (lines starting with colon)")
    func testIgnoreComments() {
        let sse = """
        : this is a comment
        event: message
        data: {"jsonrpc": "2.0", "id": 1, "result": "test"}
        
        """
        
        let events = SSEParser.parseEvents(from: sse)
        #expect(events.count == 1)
        #expect(events[0].eventType == "message")
    }
    
    @Test("Handle event with id field")
    func testParseEventWithId() {
        let sse = """
        event: message
        id: 123
        data: {"jsonrpc": "2.0", "id": 1}
        
        """
        
        let events = SSEParser.parseEvents(from: sse)
        #expect(events.count == 1)
        #expect(events[0].id == "123")
    }
    
    @Test("Handle data field with leading space")
    func testDataWithLeadingSpace() {
        let sse = """
        event: message
        data: {"result": "value with space"}
        
        """
        
        let events = SSEParser.parseEvents(from: sse)
        #expect(events.count == 1)
        // Leading space after : should be removed per SSE spec
        #expect(events[0].data == "{\"result\": \"value with space\"}")
    }
    
    @Test("Handle empty stream")
    func testEmptyStream() {
        let sse = ""
        let events = SSEParser.parseEvents(from: sse)
        #expect(events.count == 0)
    }
    
    @Test("Handle stream with only comments")
    func testOnlyComments() {
        let sse = """
        : comment 1
        : comment 2
        : comment 3
        """
        
        let events = SSEParser.parseEvents(from: sse)
        #expect(events.count == 0)
    }
    
    // MARK: - JSON Extraction
    
    @Test("Extract JSON-RPC response from SSE stream")
    func testExtractJSONResponse() throws {
        let sse = """
        event: message
        data: {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "hello"}]}}
        
        """
        
        let responses = try SSEParser.extractJSONResponses(from: sse)
        #expect(responses.count == 1)
        #expect(responses[0]["id"] as? Int == 1)
        #expect(responses[0]["jsonrpc"] as? String == "2.0")
    }
    
    @Test("Extract multiple JSON responses from SSE stream")
    func testExtractMultipleJSONResponses() throws {
        let sse = """
        event: message
        data: {"jsonrpc": "2.0", "id": 1, "result": "first"}
        
        event: message
        data: {"jsonrpc": "2.0", "id": 2, "result": "second"}
        
        """
        
        let responses = try SSEParser.extractJSONResponses(from: sse)
        #expect(responses.count == 2)
        #expect(responses[0]["id"] as? Int == 1)
        #expect(responses[1]["id"] as? Int == 2)
    }
    
    @Test("Return last response when multiple events")
    func testLastResponseUsedForMultipleEvents() throws {
        let sse = """
        event: message
        data: {"jsonrpc": "2.0", "id": 1, "result": "first"}
        
        event: message
        data: {"jsonrpc": "2.0", "id": 2, "result": "second"}
        
        event: message
        data: {"jsonrpc": "2.0", "id": 3, "result": "third"}
        
        """
        
        let responses = try SSEParser.extractJSONResponses(from: sse)
        #expect(responses.count == 3)
        // Verify they're in order
        #expect(responses[0]["id"] as? Int == 1)
        #expect(responses[2]["id"] as? Int == 3)
    }
    
    // MARK: - Error Handling
    
    @Test("Throw error on invalid JSON in data field")
    func testInvalidJSONData() {
        let sse = """
        event: message
        data: {this is not json}
        
        """
        
        #expect(throws: BridgeError.self) {
            try SSEParser.extractJSONResponses(from: sse)
        }
    }
    
    @Test("Handle data field with non-JSON content (empty after filtering)")
    func testEmptyDataFields() throws {
        let sse = """
        event: message
        id: 123
        
        """
        
        let responses = try SSEParser.extractJSONResponses(from: sse)
        #expect(responses.count == 0)
    }
    
    @Test("Skip events without data field")
    func testSkipEventsWithoutData() throws {
        let sse = """
        event: message
        id: 1
        
        event: message
        data: {"jsonrpc": "2.0", "id": 2}
        
        event: message
        id: 3
        
        """
        
        let responses = try SSEParser.extractJSONResponses(from: sse)
        #expect(responses.count == 1)
        #expect(responses[0]["id"] as? Int == 2)
    }
    
    // MARK: - Real MCP Response Examples
    
    @Test("Parse real MCP tools/list SSE response")
    func testRealMCPToolsListResponse() throws {
        let sse = """
        event: message
        data: {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "get_weather", "description": "Get weather for a location", "inputSchema": {"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}}]}}
        
        """
        
        let responses = try SSEParser.extractJSONResponses(from: sse)
        #expect(responses.count == 1)
        
        let result = responses[0]["result"] as? [String: Any]
        let tools = result?["tools"] as? [[String: Any]]
        #expect(tools?.count == 1)
        #expect((tools?[0]["name"] as? String) == "get_weather")
    }
    
    @Test("Parse real MCP tools/call SSE response")
    func testRealMCPToolsCallResponse() throws {
        let sse = """
        event: message
        data: {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "The weather in San Francisco is 72F and sunny"}]}}
        
        """
        
        let responses = try SSEParser.extractJSONResponses(from: sse)
        #expect(responses.count == 1)
        
        let result = responses[0]["result"] as? [String: Any]
        let content = result?["content"] as? [[String: Any]]
        #expect(content?.count == 1)
        #expect((content?[0]["text"] as? String) == "The weather in San Francisco is 72F and sunny")
    }
    
    // MARK: - Edge Cases with Real SSE Format
    
    @Test("Handle SSE stream with trailing newlines")
    func testTrailingNewlines() throws {
        let sse = """
        event: message
        data: {"jsonrpc": "2.0", "id": 1, "result": "test"}
        
        
        
        """
        
        let responses = try SSEParser.extractJSONResponses(from: sse)
        #expect(responses.count == 1)
    }
    
    @Test("Parse event without explicit newlines between fields")
    func testEventWithoutNewlines() {
        let sse = "event: msg\ndata: {\"id\": 1}\n\n"
        
        let events = SSEParser.parseEvents(from: sse)
        #expect(events.count == 1)
        #expect(events[0].eventType == "msg")
    }
    
    @Test("Handle multi-line JSON in single data field")
    func testMultilineJSONInDataField() throws {
        let sse = """
        event: message
        data: {
        data:   "jsonrpc": "2.0",
        data:   "id": 1,
        data:   "result": "test"
        data: }
        
        """
        
        let responses = try SSEParser.extractJSONResponses(from: sse)
        #expect(responses.count == 1)
        #expect(responses[0]["id"] as? Int == 1)
    }
}
