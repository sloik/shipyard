import Foundation

// MARK: - ToolExecutionRequest

/// Captures a tool call request: tool name + JSON arguments payload
struct ToolExecutionRequest: Codable, Equatable {
    let toolName: String
    let arguments: [String: Any]
    
    init(toolName: String, arguments: [String: Any]) {
        self.toolName = toolName
        self.arguments = arguments
    }
    
    // MARK: - Codable Conformance
    
    enum CodingKeys: String, CodingKey {
        case toolName
        case arguments
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.toolName = try container.decode(String.self, forKey: .toolName)
        
        // Decode arguments as JSON data, then convert to [String: Any]
        let data = try container.decode(Data.self, forKey: .arguments)
        if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
            self.arguments = json
        } else {
            self.arguments = [:]
        }
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(toolName, forKey: .toolName)
        
        // Encode arguments as JSON data
        let data = try JSONSerialization.data(withJSONObject: arguments)
        try container.encode(data, forKey: .arguments)
    }
    
    // MARK: - Equatable Conformance
    
    static func == (lhs: ToolExecutionRequest, rhs: ToolExecutionRequest) -> Bool {
        lhs.toolName == rhs.toolName &&
        NSDictionary(dictionary: lhs.arguments).isEqual(to: rhs.arguments)
    }
}
