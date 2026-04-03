import Foundation

// MARK: - JSON-RPC Types

public struct MCPRequest: Codable {
    public var jsonrpc: String = "2.0"
    public let id: Int?
    public let method: String
    public let params: [String: AnyCodable]?

    public init(jsonrpc: String = "2.0", id: Int?, method: String, params: [String: AnyCodable]?) {
        self.jsonrpc = jsonrpc
        self.id = id
        self.method = method
        self.params = params
    }
}

public struct MCPResponse: Encodable {
    public let jsonrpc: String
    public let id: Int?
    public let result: AnyCodable?
    public let error: MCPError?

    public enum CodingKeys: String, CodingKey {
        case jsonrpc
        case id
        case result
        case error
    }

    public init(jsonrpc: String = "2.0", id: Int?, result: AnyCodable?, error: MCPError?) {
        self.jsonrpc = jsonrpc
        self.id = id
        self.result = result
        self.error = error
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(jsonrpc, forKey: .jsonrpc)
        try container.encode(id, forKey: .id)
        if let result = result {
            try container.encode(result, forKey: .result)
        }
        if let error = error {
            try container.encode(error, forKey: .error)
        }
    }
}

public struct MCPError: Encodable {
    public let code: Int
    public let message: String

    public init(code: Int, message: String) {
        self.code = code
        self.message = message
    }
}

public struct MCPContentBlock: Encodable {
    public let type: String
    public let text: String

    public init(type: String, text: String) {
        self.type = type
        self.text = text
    }
}

public struct MCPToolContent: Encodable {
    public let content: [MCPContentBlock]

    public init(content: [MCPContentBlock]) {
        self.content = content
    }
}

public struct MCPToolResult: Encodable {
    public let content: [MCPContentBlock]

    public init(content: [MCPContentBlock]) {
        self.content = content
    }
}

// MARK: - AnyCodable (for flexible JSON encoding)

public enum AnyCodable: Codable {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([AnyCodable])
    case object([String: AnyCodable])

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()

        if container.decodeNil() {
            self = .null
        } else if let bool = try? container.decode(Bool.self) {
            self = .bool(bool)
        } else if let int = try? container.decode(Int.self) {
            self = .int(int)
        } else if let double = try? container.decode(Double.self) {
            self = .double(double)
        } else if let string = try? container.decode(String.self) {
            self = .string(string)
        } else if let array = try? container.decode([AnyCodable].self) {
            self = .array(array)
        } else if let object = try? container.decode([String: AnyCodable].self) {
            self = .object(object)
        } else {
            throw DecodingError.dataCorrupted(
                DecodingError.Context(
                    codingPath: decoder.codingPath,
                    debugDescription: "Cannot decode AnyCodable"
                )
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null:
            try container.encodeNil()
        case .bool(let bool):
            try container.encode(bool)
        case .int(let int):
            try container.encode(int)
        case .double(let double):
            try container.encode(double)
        case .string(let string):
            try container.encode(string)
        case .array(let array):
            try container.encode(array)
        case .object(let object):
            try container.encode(object)
        }
    }

    public func toAny() -> Any {
        switch self {
        case .null:
            return NSNull()
        case .bool(let b):
            return b
        case .int(let i):
            return i
        case .double(let d):
            return d
        case .string(let s):
            return s
        case .array(let a):
            return a.map { $0.toAny() }
        case .object(let o):
            return o.mapValues { $0.toAny() }
        }
    }
}
