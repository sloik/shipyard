import Foundation

/// Lightweight JSON Schema validator for basic schema validation
final class JSONSchemaValidator {
    /// A validation issue (error or warning)
    struct Issue: Equatable {
        let level: Level
        let message: String
        
        enum Level: String, Equatable {
            case error
            case warning
        }
    }
    
    /// Validate a JSON payload against a schema
    /// - Parameters:
    ///   - payload: The parsed JSON object to validate
    ///   - schema: The JSON schema (as [String: Any])
    /// - Returns: Array of validation issues (empty if valid)
    static func validate(payload: [String: Any], against schema: [String: Any]) -> [Issue] {
        var issues: [Issue] = []
        
        // Check required fields
        if let required = schema["required"] as? [String] {
            for fieldName in required {
                if payload[fieldName] == nil {
                    issues.append(Issue(level: .error, message: "Missing required field: \(fieldName)"))
                }
            }
        }
        
        // Check field types and properties
        if let properties = schema["properties"] as? [String: Any] {
            for (key, value) in payload {
                guard let propSchema = properties[key] as? [String: Any] else {
                    continue
                }
                
                // Validate type
                if let expectedType = propSchema["type"] as? String {
                    let actualType = typeOf(value)
                    if actualType != expectedType {
                        issues.append(Issue(
                            level: .error,
                            message: "Field \(key): expected \(expectedType), got \(actualType)"
                        ))
                    }
                }
                
                // Validate enum
                if let enumValues = propSchema["enum"] as? [Any] {
                    let stringValue = String(describing: value)
                    let validStrings = enumValues.map { String(describing: $0) }
                    if !validStrings.contains(stringValue) {
                        issues.append(Issue(
                            level: .warning,
                            message: "Field \(key): value not in allowed options"
                        ))
                    }
                }
            }
        }
        
        return issues
    }
    
    /// Check if a JSON string is valid
    static func isValidJSON(_ jsonString: String) -> (isValid: Bool, error: String?) {
        guard let data = jsonString.data(using: .utf8) else {
            return (false, "Invalid encoding")
        }
        
        do {
            _ = try JSONSerialization.jsonObject(with: data)
            return (true, nil)
        } catch let error as NSError {
            // Extract user-friendly error message
            var message = "Invalid JSON"
            if let desc = error.userInfo["NSDebugDescription"] as? String {
                message = desc
            }
            return (false, message)
        }
    }
    
    /// Get the JSON type name of a value
    private static func typeOf(_ value: Any) -> String {
        switch value {
        case is String:
            return "string"
        case is NSNumber:
            let num = value as! NSNumber
            if CFNumberGetType(num as CFNumber) == .charType {
                return "boolean"
            }
            return "number"
        case is [String: Any]:
            return "object"
        case is [Any]:
            return "array"
        case is NSNull:
            return "null"
        default:
            return "unknown"
        }
    }
}
