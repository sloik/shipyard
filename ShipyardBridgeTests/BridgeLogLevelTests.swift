import Testing
import Foundation
@testable import ShipyardBridgeLib

@Suite("BridgeLogLevel Raw Value Tests")
struct BridgeLogLevelRawValueTests {
    @Test("debug has raw value 'debug'")
    func debugRawValue() {
        #expect(BridgeLogLevel.debug.rawValue == "debug")
    }

    @Test("info has raw value 'info'")
    func infoRawValue() {
        #expect(BridgeLogLevel.info.rawValue == "info")
    }

    @Test("warn has raw value 'warn'")
    func warnRawValue() {
        #expect(BridgeLogLevel.warn.rawValue == "warn")
    }

    @Test("error has raw value 'error'")
    func errorRawValue() {
        #expect(BridgeLogLevel.error.rawValue == "error")
    }
}

@Suite("BridgeLogLevel Comparable Tests")
struct BridgeLogLevelComparableTests {
    @Test("debug < info")
    func debugLessThanInfo() {
        #expect(BridgeLogLevel.debug < BridgeLogLevel.info)
    }

    @Test("debug < warn")
    func debugLessThanWarn() {
        #expect(BridgeLogLevel.debug < BridgeLogLevel.warn)
    }

    @Test("debug < error")
    func debugLessThanError() {
        #expect(BridgeLogLevel.debug < BridgeLogLevel.error)
    }

    @Test("info < warn")
    func infoLessThanWarn() {
        #expect(BridgeLogLevel.info < BridgeLogLevel.warn)
    }

    @Test("info < error")
    func infoLessThanError() {
        #expect(BridgeLogLevel.info < BridgeLogLevel.error)
    }

    @Test("warn < error")
    func warnLessThanError() {
        #expect(BridgeLogLevel.warn < BridgeLogLevel.error)
    }

    @Test("Level not less than itself")
    func notLessThanSelf() {
        #expect(!(BridgeLogLevel.debug < BridgeLogLevel.debug))
        #expect(!(BridgeLogLevel.info < BridgeLogLevel.info))
        #expect(!(BridgeLogLevel.warn < BridgeLogLevel.warn))
        #expect(!(BridgeLogLevel.error < BridgeLogLevel.error))
    }

    @Test("Transitive property: debug < info < warn < error")
    func transitiveOrdering() {
        #expect(BridgeLogLevel.debug < BridgeLogLevel.info)
        #expect(BridgeLogLevel.info < BridgeLogLevel.warn)
        #expect(BridgeLogLevel.warn < BridgeLogLevel.error)
        #expect(BridgeLogLevel.debug < BridgeLogLevel.error)
    }

    @Test("Reverse comparisons work correctly")
    func reverseComparisons() {
        #expect(!(BridgeLogLevel.info < BridgeLogLevel.debug))
        #expect(!(BridgeLogLevel.warn < BridgeLogLevel.info))
        #expect(!(BridgeLogLevel.error < BridgeLogLevel.warn))
    }
}

@Suite("BridgeLogLevel Equality Tests")
struct BridgeLogLevelEqualityTests {
    @Test("debug equals itself")
    func debugEqualsItself() {
        #expect(BridgeLogLevel.debug == BridgeLogLevel.debug)
    }

    @Test("info equals itself")
    func infoEqualsItself() {
        #expect(BridgeLogLevel.info == BridgeLogLevel.info)
    }

    @Test("warn equals itself")
    func warnEqualsItself() {
        #expect(BridgeLogLevel.warn == BridgeLogLevel.warn)
    }

    @Test("error equals itself")
    func errorEqualsItself() {
        #expect(BridgeLogLevel.error == BridgeLogLevel.error)
    }

    @Test("Different levels are not equal")
    func differentLevelsNotEqual() {
        #expect(BridgeLogLevel.debug != BridgeLogLevel.info)
        #expect(BridgeLogLevel.info != BridgeLogLevel.warn)
        #expect(BridgeLogLevel.warn != BridgeLogLevel.error)
        #expect(BridgeLogLevel.debug != BridgeLogLevel.error)
    }
}

@Suite("BridgeLogLevel Codable Tests")
struct BridgeLogLevelCodableTests {
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    @Test("Encode debug level")
    func encodeDebugLevel() throws {
        let level = BridgeLogLevel.debug
        let data = try encoder.encode(level)
        let json = String(data: data, encoding: .utf8)
        #expect(json == "\"debug\"")
    }

    @Test("Encode info level")
    func encodeInfoLevel() throws {
        let level = BridgeLogLevel.info
        let data = try encoder.encode(level)
        let json = String(data: data, encoding: .utf8)
        #expect(json == "\"info\"")
    }

    @Test("Encode warn level")
    func encodeWarnLevel() throws {
        let level = BridgeLogLevel.warn
        let data = try encoder.encode(level)
        let json = String(data: data, encoding: .utf8)
        #expect(json == "\"warn\"")
    }

    @Test("Encode error level")
    func encodeErrorLevel() throws {
        let level = BridgeLogLevel.error
        let data = try encoder.encode(level)
        let json = String(data: data, encoding: .utf8)
        #expect(json == "\"error\"")
    }

    @Test("Decode debug level")
    func decodeDebugLevel() throws {
        let data = "\"debug\"".data(using: .utf8)!
        let level = try decoder.decode(BridgeLogLevel.self, from: data)
        #expect(level == .debug)
    }

    @Test("Decode info level")
    func decodeInfoLevel() throws {
        let data = "\"info\"".data(using: .utf8)!
        let level = try decoder.decode(BridgeLogLevel.self, from: data)
        #expect(level == .info)
    }

    @Test("Decode warn level")
    func decodeWarnLevel() throws {
        let data = "\"warn\"".data(using: .utf8)!
        let level = try decoder.decode(BridgeLogLevel.self, from: data)
        #expect(level == .warn)
    }

    @Test("Decode error level")
    func decodeErrorLevel() throws {
        let data = "\"error\"".data(using: .utf8)!
        let level = try decoder.decode(BridgeLogLevel.self, from: data)
        #expect(level == .error)
    }

    @Test("Round-trip debug level")
    func roundTripDebugLevel() throws {
        let original = BridgeLogLevel.debug
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(BridgeLogLevel.self, from: encoded)
        #expect(decoded == original)
    }

    @Test("Round-trip info level")
    func roundTripInfoLevel() throws {
        let original = BridgeLogLevel.info
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(BridgeLogLevel.self, from: encoded)
        #expect(decoded == original)
    }

    @Test("Round-trip warn level")
    func roundTripWarnLevel() throws {
        let original = BridgeLogLevel.warn
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(BridgeLogLevel.self, from: encoded)
        #expect(decoded == original)
    }

    @Test("Round-trip error level")
    func roundTripErrorLevel() throws {
        let original = BridgeLogLevel.error
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(BridgeLogLevel.self, from: encoded)
        #expect(decoded == original)
    }

    @Test("Decode invalid level throws error", throws: NSError.self)
    func decodeInvalidLevel() throws {
        let data = "\"invalid\"".data(using: .utf8)!
        let _ = try decoder.decode(BridgeLogLevel.self, from: data)
    }
}

@Suite("BridgeLogLevel Array Ordering Tests")
struct BridgeLogLevelArrayOrderingTests {
    @Test("Array of levels can be sorted")
    func sortArrayOfLevels() {
        let levels = [BridgeLogLevel.error, BridgeLogLevel.debug, BridgeLogLevel.warn, BridgeLogLevel.info]
        let sorted = levels.sorted()
        #expect(sorted[0] == .debug)
        #expect(sorted[1] == .info)
        #expect(sorted[2] == .warn)
        #expect(sorted[3] == .error)
    }

    @Test("Can use min() on levels")
    func minLevel() {
        let levels = [BridgeLogLevel.error, BridgeLogLevel.debug, BridgeLogLevel.warn]
        let min = levels.min()
        #expect(min == .debug)
    }

    @Test("Can use max() on levels")
    func maxLevel() {
        let levels = [BridgeLogLevel.error, BridgeLogLevel.debug, BridgeLogLevel.warn]
        let max = levels.max()
        #expect(max == .error)
    }
}
