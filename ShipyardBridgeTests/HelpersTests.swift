import Testing
import Foundation
@testable import ShipyardBridgeLib

@Suite("parseJSONLine Tests")
struct ParseJSONLineTests {
    @Test("Parse valid request with all fields")
    func parseValidRequestWithAllFields() {
        let json = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"test.method\",\"params\":{\"key\":\"value\"}}"
        let request = parseJSONLine(json)

        #expect(request != nil)
        #expect(request?.jsonrpc == "2.0")
        #expect(request?.id == 1)
        #expect(request?.method == "test.method")
        #expect(request?.params != nil)
    }

    @Test("Parse request with only required fields")
    func parseMinimalRequest() {
        let json = "{\"method\":\"test.method\"}"
        let request = parseJSONLine(json)

        #expect(request != nil)
        #expect(request?.method == "test.method")
        #expect(request?.id == nil)
        #expect(request?.params == nil)
    }

    @Test("Parse request without id but with params")
    func parseRequestWithoutIdButWithParams() {
        let json = "{\"method\":\"test.method\",\"params\":{\"key\":\"value\"}}"
        let request = parseJSONLine(json)

        #expect(request != nil)
        #expect(request?.id == nil)
        #expect(request?.params != nil)
    }

    @Test("Parse notification (method starts with notifications/)")
    func parseNotification() {
        let json = "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/status\"}"
        let request = parseJSONLine(json)

        #expect(request != nil)
        #expect(request?.method == "notifications/status")
        #expect(request?.id == nil)
    }

    @Test("Parse notification with params")
    func parseNotificationWithParams() {
        let json = "{\"jsonrpc\":\"2.0\",\"method\":\"notifications/update\",\"params\":{\"status\":\"ready\"}}"
        let request = parseJSONLine(json)

        #expect(request != nil)
        #expect(request?.method == "notifications/update")
        #expect(request?.params != nil)
    }

    @Test("Parse request with numeric id")
    func parseRequestWithNumericId() {
        let json = "{\"jsonrpc\":\"2.0\",\"id\":42,\"method\":\"test\"}"
        let request = parseJSONLine(json)

        #expect(request?.id == 42)
    }

    @Test("Parse request with zero id")
    func parseRequestWithZeroId() {
        let json = "{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"test\"}"
        let request = parseJSONLine(json)

        #expect(request?.id == 0)
    }

    @Test("Parse request with negative id")
    func parseRequestWithNegativeId() {
        let json = "{\"jsonrpc\":\"2.0\",\"id\":-1,\"method\":\"test\"}"
        let request = parseJSONLine(json)

        #expect(request?.id == -1)
    }

    @Test("Invalid JSON returns nil")
    func invalidJSONReturnsNil() {
        let json = "not valid json{"
        let request = parseJSONLine(json)
        #expect(request == nil)
    }

    @Test("Empty string returns nil")
    func emptyStringReturnsNil() {
        let request = parseJSONLine("")
        #expect(request == nil)
    }

    @Test("Whitespace only returns nil")
    func whitespaceOnlyReturnsNil() {
        let request = parseJSONLine("   \n  \t  ")
        #expect(request == nil)
    }

    @Test("Valid JSON without method returns nil")
    func validJSONWithoutMethodReturnsNil() {
        let json = "{\"jsonrpc\":\"2.0\",\"id\":1}"
        let request = parseJSONLine(json)
        #expect(request == nil)
    }

    @Test("Valid JSON with extra fields parses successfully")
    func validJSONWithExtraFields() {
        let json = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"test\",\"extra\":\"ignored\"}"
        let request = parseJSONLine(json)

        #expect(request != nil)
        #expect(request?.method == "test")
    }

    @Test("Parse request with complex params")
    func parseRequestWithComplexParams() {
        let json = """
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "test",
            "params": {
                "string": "value",
                "number": 42,
                "bool": true,
                "nested": {"key": "val"}
            }
        }
        """
        let request = parseJSONLine(json)

        #expect(request != nil)
        #expect(request?.params != nil)
    }

    @Test("Parse request with empty params object")
    func parseRequestWithEmptyParams() {
        let json = "{\"method\":\"test\",\"params\":{}}"
        let request = parseJSONLine(json)

        #expect(request != nil)
        #expect(request?.params?.isEmpty == true)
    }

    @Test("Parse request with array params returns nil")
    func parseRequestWithArrayParams() {
        let json = "{\"method\":\"test\",\"params\":[]}"
        let request = parseJSONLine(json)
        // params should be an object, not array, so this should fail
        #expect(request == nil)
    }
}

@Suite("extractParams Tests")
struct ExtractParamsTests {
    @Test("Extract from nil params returns empty dict")
    func extractFromNilReturnsEmpty() {
        let result = extractParams(nil)
        #expect(result.isEmpty)
        #expect(result.count == 0)
    }

    @Test("Extract from empty params returns empty dict")
    func extractFromEmptyParamsReturnsEmpty() {
        let params: [String: AnyCodable] = [:]
        let result = extractParams(params)
        #expect(result.isEmpty)
    }

    @Test("Extract string values")
    func extractStringValues() {
        let params: [String: AnyCodable] = [
            "name": .string("Alice"),
            "city": .string("NYC")
        ]
        let result = extractParams(params)

        #expect(result["name"] is String)
        #expect(result["name"] as? String == "Alice")
        #expect(result["city"] as? String == "NYC")
    }

    @Test("Extract int values")
    func extractIntValues() {
        let params: [String: AnyCodable] = [
            "count": .int(42),
            "id": .int(100)
        ]
        let result = extractParams(params)

        #expect(result["count"] is Int)
        #expect(result["count"] as? Int == 42)
        #expect(result["id"] as? Int == 100)
    }

    @Test("Extract bool values")
    func extractBoolValues() {
        let params: [String: AnyCodable] = [
            "active": .bool(true),
            "deleted": .bool(false)
        ]
        let result = extractParams(params)

        #expect(result["active"] is Bool)
        #expect(result["active"] as? Bool == true)
        #expect(result["deleted"] as? Bool == false)
    }

    @Test("Extract double values")
    func extractDoubleValues() {
        let params: [String: AnyCodable] = [
            "price": .double(19.99),
            "rating": .double(4.5)
        ]
        let result = extractParams(params)

        #expect(result["price"] is Double)
        #expect((result["price"] as? Double) ?? 0 == 19.99)
    }

    @Test("Extract null values")
    func extractNullValues() {
        let params: [String: AnyCodable] = [
            "nothing": .null
        ]
        let result = extractParams(params)

        #expect(result["nothing"] is NSNull)
    }

    @Test("Extract array values")
    func extractArrayValues() {
        let params: [String: AnyCodable] = [
            "items": .array([.int(1), .int(2), .int(3)])
        ]
        let result = extractParams(params)

        #expect(result["items"] is [Any])
        let arr = result["items"] as? [Any]
        #expect(arr?.count == 3)
    }

    @Test("Extract nested array values")
    func extractNestedArrayValues() {
        let params: [String: AnyCodable] = [
            "users": .array([
                .object(["name": .string("Alice"), "id": .int(1)]),
                .object(["name": .string("Bob"), "id": .int(2)])
            ])
        ]
        let result = extractParams(params)

        let users = result["users"] as? [Any]
        #expect(users?.count == 2)
    }

    @Test("Extract object values")
    func extractObjectValues() {
        let params: [String: AnyCodable] = [
            "user": .object(["name": .string("Alice"), "age": .int(30)])
        ]
        let result = extractParams(params)

        #expect(result["user"] is [String: Any])
        let user = result["user"] as? [String: Any]
        #expect(user?["name"] is String)
        #expect(user?["age"] is Int)
    }

    @Test("Extract nested object values")
    func extractNestedObjectValues() {
        let params: [String: AnyCodable] = [
            "address": .object([
                "street": .string("Main St"),
                "city": .string("NYC"),
                "zip": .string("10001")
            ])
        ]
        let result = extractParams(params)

        let address = result["address"] as? [String: Any]
        #expect(address?["street"] as? String == "Main St")
        #expect(address?["city"] as? String == "NYC")
    }

    @Test("Extract mixed type values")
    func extractMixedTypes() {
        let params: [String: AnyCodable] = [
            "id": .int(1),
            "name": .string("Test"),
            "active": .bool(true),
            "score": .double(95.5),
            "tags": .array([.string("a"), .string("b")])
        ]
        let result = extractParams(params)

        #expect(result["id"] is Int)
        #expect(result["name"] is String)
        #expect(result["active"] is Bool)
        #expect(result["score"] is Double)
        #expect(result["tags"] is [Any])
    }

    @Test("Extract preserves all keys")
    func extractPreservesAllKeys() {
        let params: [String: AnyCodable] = [
            "key1": .string("val1"),
            "key2": .string("val2"),
            "key3": .string("val3")
        ]
        let result = extractParams(params)

        #expect(result.count == 3)
        #expect(result["key1"] != nil)
        #expect(result["key2"] != nil)
        #expect(result["key3"] != nil)
    }

    @Test("Extract handles special characters in keys")
    func extractSpecialCharacterKeys() {
        let params: [String: AnyCodable] = [
            "user-name": .string("Alice"),
            "age_in_years": .int(30),
            "has.dot": .bool(true)
        ]
        let result = extractParams(params)

        #expect(result["user-name"] as? String == "Alice")
        #expect(result["age_in_years"] as? Int == 30)
        #expect(result["has.dot"] as? Bool == true)
    }

    @Test("Extract handles empty string values")
    func extractEmptyStringValues() {
        let params: [String: AnyCodable] = [
            "empty": .string("")
        ]
        let result = extractParams(params)

        #expect(result["empty"] as? String == "")
    }

    @Test("Extract handles empty array values")
    func extractEmptyArrayValues() {
        let params: [String: AnyCodable] = [
            "items": .array([])
        ]
        let result = extractParams(params)

        let arr = result["items"] as? [Any]
        #expect(arr?.isEmpty == true)
    }

    @Test("Extract handles empty object values")
    func extractEmptyObjectValues() {
        let params: [String: AnyCodable] = [
            "data": .object([:])
        ]
        let result = extractParams(params)

        let obj = result["data"] as? [String: Any]
        #expect(obj?.isEmpty == true)
    }

    @Test("Extract deeply nested structures")
    func extractDeeplyNested() {
        let params: [String: AnyCodable] = [
            "level1": .object([
                "level2": .object([
                    "level3": .string("deep")
                ])
            ])
        ]
        let result = extractParams(params)

        let l1 = result["level1"] as? [String: Any]
        let l2 = l1?["level2"] as? [String: Any]
        let l3 = l2?["level3"] as? String

        #expect(l3 == "deep")
    }

    @Test("Extract handles zero values")
    func extractZeroValues() {
        let params: [String: AnyCodable] = [
            "zero_int": .int(0),
            "zero_double": .double(0.0)
        ]
        let result = extractParams(params)

        #expect(result["zero_int"] as? Int == 0)
        #expect((result["zero_double"] as? Double) ?? 0 == 0.0)
    }

    @Test("Extract handles negative values")
    func extractNegativeValues() {
        let params: [String: AnyCodable] = [
            "neg_int": .int(-42),
            "neg_double": .double(-3.14)
        ]
        let result = extractParams(params)

        #expect(result["neg_int"] as? Int == -42)
        #expect((result["neg_double"] as? Double) ?? 0 == -3.14)
    }
}

@Suite("parseJSONLine and extractParams Integration Tests")
struct HelpersIntegrationTests {
    @Test("Parse request and extract params together")
    func parseAndExtractTogether() {
        let json = """
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "test.method",
            "params": {
                "name": "Alice",
                "age": 30,
                "active": true
            }
        }
        """
        let request = parseJSONLine(json)
        #require(request != nil)

        let params = extractParams(request?.params)

        #expect(params.count == 3)
        #expect(params["name"] as? String == "Alice")
        #expect(params["age"] as? Int == 30)
        #expect(params["active"] as? Bool == true)
    }

    @Test("Parse request without params and extract returns empty")
    func parseWithoutParamsExtractEmpty() {
        let json = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"test\"}"
        let request = parseJSONLine(json)
        #require(request != nil)

        let params = extractParams(request?.params)

        #expect(params.isEmpty)
    }

    @Test("Parse complex nested request and extract params")
    func parseComplexAndExtract() {
        let json = """
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "complex.call",
            "params": {
                "user": {
                    "name": "Bob",
                    "id": 42
                },
                "tags": ["tag1", "tag2"],
                "metadata": {
                    "created": "2024-03-12",
                    "active": true
                }
            }
        }
        """
        let request = parseJSONLine(json)
        #require(request != nil)

        let params = extractParams(request?.params)

        let user = params["user"] as? [String: Any]
        #expect(user?["name"] as? String == "Bob")

        let tags = params["tags"] as? [Any]
        #expect(tags?.count == 2)

        let metadata = params["metadata"] as? [String: Any]
        #expect(metadata?["active"] as? Bool == true)
    }
}
