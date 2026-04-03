import Foundation

// MARK: - ToolExecutionResponse

/// Captures a tool call response: raw JSON response string + content length
struct ToolExecutionResponse: Codable, Sendable {
    let responseJSON: String
    let contentLength: Int
    
    init(responseJSON: String) {
        self.responseJSON = responseJSON
        self.contentLength = responseJSON.count
    }
    
    // MARK: - Codable Conformance
    
    enum CodingKeys: String, CodingKey {
        case responseJSON
        case contentLength
    }
    
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.responseJSON = try container.decode(String.self, forKey: .responseJSON)
        self.contentLength = try container.decode(Int.self, forKey: .contentLength)
    }
    
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(responseJSON, forKey: .responseJSON)
        try container.encode(contentLength, forKey: .contentLength)
    }
}
