import Foundation

// MARK: - Helper Functions

public func formatErrorText(_ message: String) -> String {
    return "Error: \(message)"
}

public func extractParams(_ params: [String: AnyCodable]?) -> [String: Any] {
    guard let params = params else { return [:] }
    var result: [String: Any] = [:]
    for (key, value) in params {
        result[key] = value.toAny()
    }
    return result
}

public func encodeJSONResponse(_ value: Encodable) -> String? {
    let encoder = JSONEncoder()
    if let data = try? encoder.encode(value),
       let json = String(data: data, encoding: .utf8) {
        return json
    }
    return nil
}

public func parseJSONLine(_ line: String) -> MCPRequest? {
    guard let data = line.data(using: .utf8) else {
        return nil
    }
    let decoder = JSONDecoder()
    return try? decoder.decode(MCPRequest.self, from: data)
}
