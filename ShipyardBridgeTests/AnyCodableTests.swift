import Testing
import Foundation
@testable import ShipyardBridgeLib

@Suite("AnyCodable Encoding Tests")
struct AnyCodableEncodingTests {
    private let encoder = JSONEncoder()

    @Test("Encode null")
    func encodeNull() throws {
        let value = AnyCodable.null
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? NSNull
        #expect(json != nil)
    }

    @Test("Encode bool true")
    func encodeBoolTrue() throws {
        let value = AnyCodable.bool(true)
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? Bool
        #expect(json == true)
    }

    @Test("Encode bool false")
    func encodeBoolFalse() throws {
        let value = AnyCodable.bool(false)
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? Bool
        #expect(json == false)
    }

    @Test("Encode int")
    func encodeInt() throws {
        let value = AnyCodable.int(42)
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? Int
        #expect(json == 42)
    }

    @Test("Encode negative int")
    func encodeNegativeInt() throws {
        let value = AnyCodable.int(-100)
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? Int
        #expect(json == -100)
    }

    @Test("Encode double")
    func encodeDouble() throws {
        let value = AnyCodable.double(3.14)
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? Double
        #expect(json == 3.14)
    }

    @Test("Encode string")
    func encodeString() throws {
        let value = AnyCodable.string("hello")
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? String
        #expect(json == "hello")
    }

    @Test("Encode empty string")
    func encodeEmptyString() throws {
        let value = AnyCodable.string("")
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? String
        #expect(json == "")
    }

    @Test("Encode array of ints")
    func encodeArrayOfInts() throws {
        let value = AnyCodable.array([.int(1), .int(2), .int(3)])
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? [Int]
        #expect(json == [1, 2, 3])
    }

    @Test("Encode empty array")
    func encodeEmptyArray() throws {
        let value = AnyCodable.array([])
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? [Any]
        #expect(json?.count == 0)
    }

    @Test("Encode object with string values")
    func encodeObjectWithStrings() throws {
        let value = AnyCodable.object(["name": .string("Alice"), "city": .string("NYC")])
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: String]
        #expect(json?["name"] == "Alice")
        #expect(json?["city"] == "NYC")
    }

    @Test("Encode empty object")
    func encodeEmptyObject() throws {
        let value = AnyCodable.object([:])
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        #expect(json?.count == 0)
    }
}

@Suite("AnyCodable Decoding Tests")
struct AnyCodableDecodingTests {
    private let decoder = JSONDecoder()

    @Test("Decode null")
    func decodeNull() throws {
        let data = "null".data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)
        if case .null = value {
            #expect(true)
        } else {
            #expect(false, "Should decode to null case")
        }
    }

    @Test("Decode bool true")
    func decodeBoolTrue() throws {
        let data = "true".data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)
        if case .bool(let b) = value {
            #expect(b == true)
        } else {
            #expect(false, "Should decode to bool case")
        }
    }

    @Test("Decode bool false")
    func decodeBoolFalse() throws {
        let data = "false".data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)
        if case .bool(let b) = value {
            #expect(b == false)
        } else {
            #expect(false, "Should decode to bool case")
        }
    }

    @Test("Decode int")
    func decodeInt() throws {
        let data = "42".data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)
        if case .int(let i) = value {
            #expect(i == 42)
        } else {
            #expect(false, "Should decode to int case")
        }
    }

    @Test("Decode double")
    func decodeDouble() throws {
        let data = "3.14".data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)
        if case .double(let d) = value {
            #expect(d == 3.14)
        } else {
            #expect(false, "Should decode to double case")
        }
    }

    @Test("Decode string")
    func decodeString() throws {
        let data = "\"hello\"".data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)
        if case .string(let s) = value {
            #expect(s == "hello")
        } else {
            #expect(false, "Should decode to string case")
        }
    }

    @Test("Decode array")
    func decodeArray() throws {
        let data = "[1,2,3]".data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)
        if case .array(let a) = value {
            #expect(a.count == 3)
        } else {
            #expect(false, "Should decode to array case")
        }
    }

    @Test("Decode object")
    func decodeObject() throws {
        let data = "{\"key\":\"value\"}".data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)
        if case .object(let o) = value {
            #expect(o["key"] != nil)
        } else {
            #expect(false, "Should decode to object case")
        }
    }
}

@Suite("AnyCodable Round-trip Tests")
struct AnyCodableRoundTripTests {
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    @Test("Round-trip null")
    func roundTripNull() throws {
        let original = AnyCodable.null
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(AnyCodable.self, from: encoded)
        let reencoded = try encoder.encode(decoded)

        let originalJSON = try JSONSerialization.jsonObject(with: encoded)
        let roundtripJSON = try JSONSerialization.jsonObject(with: reencoded)

        // Both should be NSNull
        #expect(type(of: originalJSON) == type(of: roundtripJSON))
    }

    @Test("Round-trip bool")
    func roundTripBool() throws {
        let original = AnyCodable.bool(true)
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(AnyCodable.self, from: encoded)
        let reencoded = try encoder.encode(decoded)

        let originalJSON = try JSONSerialization.jsonObject(with: encoded) as? Bool
        let roundtripJSON = try JSONSerialization.jsonObject(with: reencoded) as? Bool

        #expect(originalJSON == roundtripJSON)
    }

    @Test("Round-trip int")
    func roundTripInt() throws {
        let original = AnyCodable.int(42)
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(AnyCodable.self, from: encoded)
        let reencoded = try encoder.encode(decoded)

        let originalJSON = try JSONSerialization.jsonObject(with: encoded) as? Int
        let roundtripJSON = try JSONSerialization.jsonObject(with: reencoded) as? Int

        #expect(originalJSON == roundtripJSON)
    }

    @Test("Round-trip double")
    func roundTripDouble() throws {
        let original = AnyCodable.double(3.14159)
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(AnyCodable.self, from: encoded)
        let reencoded = try encoder.encode(decoded)

        let originalJSON = try JSONSerialization.jsonObject(with: encoded) as? Double
        let roundtripJSON = try JSONSerialization.jsonObject(with: reencoded) as? Double

        #expect(originalJSON ?? 0 == roundtripJSON ?? 0)
    }

    @Test("Round-trip string")
    func roundTripString() throws {
        let original = AnyCodable.string("test string")
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(AnyCodable.self, from: encoded)
        let reencoded = try encoder.encode(decoded)

        let originalJSON = try JSONSerialization.jsonObject(with: encoded) as? String
        let roundtripJSON = try JSONSerialization.jsonObject(with: reencoded) as? String

        #expect(originalJSON == roundtripJSON)
    }

    @Test("Round-trip array")
    func roundTripArray() throws {
        let original = AnyCodable.array([.int(1), .string("two"), .double(3.0)])
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(AnyCodable.self, from: encoded)
        let reencoded = try encoder.encode(decoded)

        let originalArray = try JSONSerialization.jsonObject(with: encoded) as? [Any]
        let roundtripArray = try JSONSerialization.jsonObject(with: reencoded) as? [Any]

        #expect(originalArray?.count == roundtripArray?.count)
    }

    @Test("Round-trip object")
    func roundTripObject() throws {
        let original = AnyCodable.object(["a": .int(1), "b": .string("two")])
        let encoded = try encoder.encode(original)
        let decoded = try decoder.decode(AnyCodable.self, from: encoded)
        let reencoded = try encoder.encode(decoded)

        let originalObj = try JSONSerialization.jsonObject(with: encoded) as? [String: Any]
        let roundtripObj = try JSONSerialization.jsonObject(with: reencoded) as? [String: Any]

        #expect(originalObj?.count == roundtripObj?.count)
    }
}

@Suite("AnyCodable Nested Structure Tests")
struct AnyCodableNestedTests {
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    @Test("Encode object containing array")
    func encodeObjectWithArray() throws {
        let value = AnyCodable.object([
            "items": .array([.int(1), .int(2), .int(3)]),
            "name": .string("list")
        ])
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        let items = json?["items"] as? [Int]
        #expect(items == [1, 2, 3])
    }

    @Test("Encode array of objects")
    func encodeArrayOfObjects() throws {
        let value = AnyCodable.array([
            .object(["id": .int(1), "name": .string("Alice")]),
            .object(["id": .int(2), "name": .string("Bob")])
        ])
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? [[String: Any]]

        #expect(json?.count == 2)
        #expect(json?[0]["name"] as? String == "Alice")
    }

    @Test("Encode deeply nested structure")
    func encodeDeeplyNested() throws {
        let value = AnyCodable.object([
            "level1": .object([
                "level2": .object([
                    "level3": .string("deep value")
                ])
            ])
        ])
        let data = try encoder.encode(value)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        let l1 = json?["level1"] as? [String: Any]
        let l2 = l1?["level2"] as? [String: Any]
        let l3 = l2?["level3"] as? String

        #expect(l3 == "deep value")
    }

    @Test("Decode object containing array")
    func decodeObjectWithArray() throws {
        let jsonStr = "{\"items\":[1,2,3],\"name\":\"list\"}"
        let data = jsonStr.data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)

        if case .object(let obj) = value {
            if case .array(let arr) = obj["items"] {
                #expect(arr.count == 3)
            } else {
                #expect(false, "Should contain array")
            }
        } else {
            #expect(false, "Should decode to object")
        }
    }

    @Test("Decode array of objects")
    func decodeArrayOfObjects() throws {
        let jsonStr = "[{\"id\":1,\"name\":\"Alice\"},{\"id\":2,\"name\":\"Bob\"}]"
        let data = jsonStr.data(using: .utf8)!
        let value = try decoder.decode(AnyCodable.self, from: data)

        if case .array(let arr) = value {
            #expect(arr.count == 2)
        } else {
            #expect(false, "Should decode to array")
        }
    }
}

@Suite("AnyCodable toAny() Tests")
struct AnyCodableToAnyTests {
    @Test("toAny() null returns NSNull")
    func toAnyNull() {
        let value = AnyCodable.null
        let result = value.toAny()
        #expect(result is NSNull)
    }

    @Test("toAny() bool returns Bool")
    func toAnyBool() {
        let value = AnyCodable.bool(true)
        let result = value.toAny()
        #expect(result is Bool)
        #expect(result as? Bool == true)
    }

    @Test("toAny() int returns Int")
    func toAnyInt() {
        let value = AnyCodable.int(42)
        let result = value.toAny()
        #expect(result is Int)
        #expect(result as? Int == 42)
    }

    @Test("toAny() double returns Double")
    func toAnyDouble() {
        let value = AnyCodable.double(3.14)
        let result = value.toAny()
        #expect(result is Double)
        #expect((result as? Double) ?? 0 == 3.14)
    }

    @Test("toAny() string returns String")
    func toAnyString() {
        let value = AnyCodable.string("hello")
        let result = value.toAny()
        #expect(result is String)
        #expect(result as? String == "hello")
    }

    @Test("toAny() array returns Array")
    func toAnyArray() {
        let value = AnyCodable.array([.int(1), .int(2), .int(3)])
        let result = value.toAny()
        #expect(result is [Any])

        let arr = result as? [Any]
        #expect(arr?.count == 3)
    }

    @Test("toAny() array converts nested values")
    func toAnyArrayNested() {
        let value = AnyCodable.array([
            .int(1),
            .string("two"),
            .bool(true)
        ])
        let result = value.toAny() as? [Any]

        #expect(result?[0] is Int)
        #expect(result?[1] is String)
        #expect(result?[2] is Bool)
    }

    @Test("toAny() object returns Dictionary")
    func toAnyObject() {
        let value = AnyCodable.object(["key": .string("value")])
        let result = value.toAny()
        #expect(result is [String: Any])

        let dict = result as? [String: Any]
        #expect(dict?["key"] is String)
    }

    @Test("toAny() object converts nested values")
    func toAnyObjectNested() {
        let value = AnyCodable.object([
            "name": .string("Alice"),
            "age": .int(30),
            "active": .bool(true)
        ])
        let result = value.toAny() as? [String: Any]

        #expect(result?["name"] is String)
        #expect(result?["age"] is Int)
        #expect(result?["active"] is Bool)
    }

    @Test("toAny() complex nested structure")
    func toAnyComplex() {
        let value = AnyCodable.object([
            "users": .array([
                .object(["name": .string("Alice"), "id": .int(1)]),
                .object(["name": .string("Bob"), "id": .int(2)])
            ])
        ])
        let result = value.toAny() as? [String: Any]
        let users = result?["users"] as? [Any]

        #expect(users?.count == 2)
    }
}

@Suite("AnyCodable Error Handling Tests")
struct AnyCodableErrorTests {
    private let decoder = JSONDecoder()

    @Test("Decode invalid JSON throws error", throws: NSError.self)
    func decodeInvalidJSON() throws {
        let data = "not valid json{".data(using: .utf8)!
        let _ = try decoder.decode(AnyCodable.self, from: data)
    }

    @Test("Decode empty data throws error", throws: NSError.self)
    func decodeEmptyData() throws {
        let data = "".data(using: .utf8)!
        let _ = try decoder.decode(AnyCodable.self, from: data)
    }
}
