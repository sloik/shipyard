import Testing
import Foundation
@testable import Shipyard

@Suite("JSONFormatter")
struct JSONFormatterTests {

    @Test("testFormatSlashEscaping: paths contain unescaped forward slashes")
    func testFormatSlashEscaping() throws {
        let input: [String: Any] = [
            "path": "/opt/homebrew/bin/python3",
            "url": "https://example.com/api/v1/endpoint"
        ]

        let result = JSONFormatter.format(input)
        
        #expect(result.contains("/opt/homebrew/bin/python3"))
        #expect(result.contains("https://example.com/api/v1/endpoint"))
        #expect(!result.contains("\\/opt\\/homebrew\\/bin\\/python3"))
        #expect(!result.contains("https:\\/\\/example.com\\/api\\/v1\\/endpoint"))
    }

    @Test("testFormatUnicodeDecoding: unicode escapes decoded to actual characters")
    func testFormatUnicodeDecoding() throws {
        // Create a dictionary with embedded unicode escapes in a string value
        let input: [String: Any] = [
            "hebrew": "\\u05e9",  // Hebrew letter shin
            "smartquote": "\\u2019",  // Right single quotation mark
            "normal": "hello"
        ]

        let result = JSONFormatter.format(input)
        
        // The output should contain the actual characters
        #expect(result.contains("ש"))  // Decoded Hebrew letter
        #expect(result.contains("'"))  // Decoded smart quote
        #expect(result.contains("hello"))
    }

    @Test("testFormatSurrogatePairs: surrogate pairs decoded to emoji")
    func testFormatSurrogatePairs() throws {
        // \uD83D\uDE00 is the surrogate pair for 😀 (grinning face)
        let input: [String: Any] = [
            "emoji": "\\uD83D\\uDE00",
            "text": "Grinning face"
        ]

        let result = JSONFormatter.format(input)
        
        #expect(result.contains("😀"))
        #expect(result.contains("Grinning face"))
    }

    @Test("testFormatPreservesValidJSON: roundtrip produces valid JSON")
    func testFormatPreservesValidJSON() throws {
        let input: [String: Any] = [
            "name": "test",
            "value": 42,
            "nested": [
                "key": "value",
                "array": [1, 2, 3]
            ] as [String: Any]
        ]

        let formatted = JSONFormatter.format(input)
        
        // Should be valid JSON that can be re-parsed
        let jsonData = formatted.data(using: .utf8)!
        let reparsed = try JSONSerialization.jsonObject(with: jsonData)
        #expect(reparsed is [String: Any])
    }

    @Test("testFormatStringContainingJSON: embedded JSON string is properly formatted")
    func testFormatStringContainingJSON() throws {
        let embeddedJSON = #"{"inner":"value"}"#
        let input: [String: Any] = [
            "payload": embeddedJSON,
            "type": "response"
        ]

        let result = JSONFormatter.format(input)
        
        // The embedded JSON should be parsed and formatted
        #expect(result.contains("inner"))
        #expect(result.contains("value"))
    }

    @Test("testFormatResponseUnwrapsResult: unwraps result wrapper from response format")
    func testFormatResponseUnwrapsResult() throws {
        let responseJSON = #"{"result":{"status":"ok","data":{"id":123}}}"#

        let result = JSONFormatter.formatResponse(responseJSON)
        
        // Should unwrap to the inner content
        #expect(result.contains("status"))
        #expect(result.contains("ok"))
        #expect(result.contains("data"))
        #expect(!result.contains("\"result\""))
    }

    @Test("testFormatArray: array input formatted correctly")
    func testFormatArray() throws {
        let input: [Any] = [
            "item1",
            42,
            ["nested": "object"]
        ]

        let result = JSONFormatter.format(input)
        
        #expect(result.contains("item1"))
        #expect(result.contains("42"))
        #expect(result.contains("nested"))
        #expect(result.contains("object"))
    }

    @Test("testFormatFallback: non-JSON input returns string representation")
    func testFormatFallback() throws {
        let input = 12345

        let result = JSONFormatter.format(input)
        
        #expect(result.contains("12345"))
    }
}
