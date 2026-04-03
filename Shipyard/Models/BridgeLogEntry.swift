import Foundation

// MARK: - BridgeLogLevel Enum

enum BridgeLogLevel: String, Comparable, CaseIterable, Codable, Sendable {
    case debug
    case info
    case warn
    case error

    static func < (lhs: BridgeLogLevel, rhs: BridgeLogLevel) -> Bool {
        let order: [BridgeLogLevel] = [.debug, .info, .warn, .error]
        return order.firstIndex(of: lhs)! < order.firstIndex(of: rhs)!
    }
}

// MARK: - AnyCodableValue Enum

enum AnyCodableValue: Codable, Sendable, Equatable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot decode AnyCodableValue")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .int(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        }
    }
}

// MARK: - BridgeLogEntry Struct

struct BridgeLogEntry: Identifiable, Sendable {
    let id: UUID
    let ts: String
    let level: String
    let cat: String
    let src: String
    let msg: String
    let meta: [String: AnyCodableValue]?

    /// Parsed once at init — avoids allocating a new ISO8601DateFormatter on every access
    let timestamp: Date

    /// Shared formatter for all parsing (allocated once, only used from @MainActor context)
    private nonisolated(unsafe) static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    /// Computed: Convert level string to BridgeLogLevel
    var logLevel: BridgeLogLevel {
        BridgeLogLevel(rawValue: level) ?? .info
    }

    init(id: UUID = UUID(), ts: String, level: String, cat: String, src: String, msg: String, meta: [String: AnyCodableValue]? = nil) {
        self.id = id
        self.ts = ts
        self.level = level
        self.cat = cat
        self.src = src
        self.msg = msg
        self.meta = meta
        self.timestamp = Self.isoFormatter.date(from: ts) ?? Date()
    }

    /// Parse from raw JSON dictionary (for manual JSONSerialization parsing)
    static func fromJSON(_ dict: [String: Any]) -> BridgeLogEntry? {
        guard
            let ts = dict["ts"] as? String,
            let level = dict["level"] as? String,
            let cat = dict["cat"] as? String,
            let src = dict["src"] as? String,
            let msg = dict["msg"] as? String
        else {
            return nil
        }

        var metaDict: [String: AnyCodableValue]? = nil
        if let metaRaw = dict["meta"] as? [String: Any] {
            var meta: [String: AnyCodableValue] = [:]
            for (key, value) in metaRaw {
                if let stringVal = value as? String {
                    meta[key] = .string(stringVal)
                } else if let intVal = value as? Int {
                    meta[key] = .int(intVal)
                } else if let doubleVal = value as? Double {
                    meta[key] = .double(doubleVal)
                } else if let boolVal = value as? Bool {
                    meta[key] = .bool(boolVal)
                }
            }
            metaDict = meta.isEmpty ? nil : meta
        }

        return BridgeLogEntry(id: UUID(), ts: ts, level: level, cat: cat, src: src, msg: msg, meta: metaDict)
    }
}
