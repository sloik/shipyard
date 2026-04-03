import Foundation

enum JSONFormatter {
    /// Standard serialization options for all JSON display in Shipyard
    static let displayOptions: JSONSerialization.WritingOptions = [
        .prettyPrinted, .sortedKeys, .withoutEscapingSlashes
    ]

    /// Format any value as clean, human-readable JSON
    static func format(_ data: Any) -> String {
        // If data is a String, try to parse it as JSON first
        if let jsonString = data as? String,
           let jsonData = jsonString.data(using: .utf8),
           let jsonObject = try? JSONSerialization.jsonObject(with: jsonData) {
            return format(jsonObject)  // Recurse with parsed object
        }

        // Try to serialize to pretty JSON
        if let dict = data as? [String: Any],
           let jsonData = try? JSONSerialization.data(withJSONObject: dict, options: displayOptions),
           let jsonString = String(data: jsonData, encoding: .utf8) {
            return decodeUnicodeEscapes(jsonString)
        } else if let array = data as? [Any],
                  let jsonData = try? JSONSerialization.data(withJSONObject: array, options: displayOptions),
                  let jsonString = String(data: jsonData, encoding: .utf8) {
            return decodeUnicodeEscapes(jsonString)
        }

        // Fallback: convert to string
        return "\(data)"
    }

    /// Format a response JSON string (unwraps {"result": ...} wrapper)
    static func formatResponse(_ responseJSON: String) -> String {
        // Try to unwrap {"result": ...} wrapper from SocketServer.successResponse()
        if let jsonData = responseJSON.data(using: .utf8),
           let parsed = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
           let result = parsed["result"] {
            return format(result)
        }
        return format(responseJSON)
    }

    /// Decode unicode escape sequences (\uXXXX) in a string to actual characters
    /// Handles surrogate pairs (\uD800-\uDBFF followed by \uDC00-\uDFFF)
    static func decodeUnicodeEscapes(_ string: String) -> String {
        var result = String()
        var i = string.startIndex

        while i < string.endIndex {
            // Look for \uXXXX pattern
            if i < string.index(string.endIndex, offsetBy: -5),
               string[i] == "\\",
               string[string.index(after: i)] == "u" {
                let hexStart = string.index(i, offsetBy: 2)
                let hexEnd = string.index(hexStart, offsetBy: 4)

                if hexEnd <= string.endIndex,
                   let codeValue = UInt32(string[hexStart..<hexEnd], radix: 16) {
                    // Check for surrogate pair (high surrogate followed by low surrogate)
                    var finalCodeValue = codeValue
                    var nextIndex = hexEnd

                    if codeValue >= 0xD800 && codeValue <= 0xDBFF,
                       nextIndex < string.index(string.endIndex, offsetBy: -5),
                       string[nextIndex] == "\\",
                       string[string.index(after: nextIndex)] == "u" {
                        let lowHexStart = string.index(nextIndex, offsetBy: 2)
                        let lowHexEnd = string.index(lowHexStart, offsetBy: 4)

                        if lowHexEnd <= string.endIndex,
                           let lowCodeValue = UInt32(string[lowHexStart..<lowHexEnd], radix: 16),
                           lowCodeValue >= 0xDC00 && lowCodeValue <= 0xDFFF {
                            // Valid surrogate pair — combine them
                            let highSurrogate = codeValue - 0xD800
                            let lowSurrogate = lowCodeValue - 0xDC00
                            finalCodeValue = 0x10000 + ((highSurrogate << 10) | lowSurrogate)
                            nextIndex = lowHexEnd
                        }
                    }

                    // Convert to Unicode scalar and append
                    if let scalar = UnicodeScalar(finalCodeValue) {
                        result.append(Character(scalar))
                    }
                    i = nextIndex
                } else {
                    result.append(string[i])
                    i = string.index(after: i)
                }
            } else {
                result.append(string[i])
                i = string.index(after: i)
            }
        }

        return result
    }
}
