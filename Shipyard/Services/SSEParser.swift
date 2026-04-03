import Foundation

/// Server-Sent Events (SSE) parser for `text/event-stream` responses.
/// Parses SSE format and extracts JSON-RPC responses from data events.
///
/// SSE format:
/// ```
/// event: message
/// data: {"jsonrpc": "2.0", "id": 1, "result": {...}}
///
/// event: message
/// data: {"jsonrpc": "2.0", "id": 2, "result": {...}}
/// ```
///
/// Multi-line data is supported: consecutive `data:` lines are joined with newlines.
struct SSEParser {
    /// Represents a parsed SSE event
    struct Event {
        let eventType: String?
        let data: String?
        let id: String?
    }
    
    /// Parse SSE stream and extract events
    /// - Parameter stream: The raw `text/event-stream` data as a string
    /// - Returns: Array of parsed events
    static func parseEvents(from stream: String) -> [Event] {
        var events: [Event] = []
        var currentEvent = EventBuilder()
        
        let lines = stream.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        
        for line in lines {
            // Empty line marks end of event
            if line.isEmpty {
                if currentEvent.hasContent {
                    events.append(currentEvent.build())
                    currentEvent = EventBuilder()
                }
                continue
            }
            
            // Comments (lines starting with :)
            if line.starts(with: ":") {
                continue
            }
            
            // Parse field: value
            if let colonIndex = line.firstIndex(of: ":") {
                let field = String(line[..<colonIndex])
                var value = String(line[line.index(after: colonIndex)...])
                
                // Remove leading space from value (per SSE spec)
                if value.starts(with: " ") {
                    value.removeFirst()
                }
                
                switch field {
                case "event":
                    currentEvent.eventType = value
                case "data":
                    currentEvent.appendData(value)
                case "id":
                    currentEvent.id = value
                default:
                    // Unknown field — ignore
                    break
                }
            }
        }
        
        // Handle final event if stream doesn't end with empty line
        if currentEvent.hasContent {
            events.append(currentEvent.build())
        }
        
        return events
    }
    
    /// Parse SSE stream and extract JSON-RPC responses
    /// Collects all `data:` fields from each event, joins them, and parses as JSON.
    /// - Parameter stream: The raw `text/event-stream` data as a string
    /// - Returns: Array of JSON-RPC response dictionaries
    /// - Throws: BridgeError if JSON parsing fails
    static func extractJSONResponses(from stream: String) throws -> [[String: Any]] {
        let events = parseEvents(from: stream)
        var responses: [[String: Any]] = []
        
        for event in events {
            // Only process events with data
            guard let dataString = event.data, !dataString.isEmpty else {
                continue
            }
            
            // Parse JSON from data field
            guard let jsonData = dataString.data(using: .utf8) else {
                throw BridgeError.serializationFailed("Failed to encode SSE data as UTF-8")
            }
            
            guard let jsonObject = try JSONSerialization.jsonObject(with: jsonData) as? [String: Any] else {
                throw BridgeError.serializationFailed("SSE data field is not valid JSON")
            }
            
            responses.append(jsonObject)
        }
        
        return responses
    }
    
    /// Helper builder for accumulating event data across multiple lines
    private struct EventBuilder {
        var eventType: String?
        var dataLines: [String] = []
        var id: String?
        
        var hasContent: Bool {
            eventType != nil || !dataLines.isEmpty || id != nil
        }
        
        mutating func appendData(_ line: String) {
            dataLines.append(line)
        }
        
        var data: String? {
            guard !dataLines.isEmpty else { return nil }
            // Join multiple data lines with newlines (per SSE spec)
            return dataLines.joined(separator: "\n")
        }
        
        func build() -> Event {
            Event(eventType: eventType, data: data, id: id)
        }
    }
}
