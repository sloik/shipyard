import Foundation
import AppKit

/// JSONHighlighter converts JSON strings to NSAttributedString with syntax highlighting
final class JSONHighlighter {
    /// Syntax highlighting colors
    private static let keyColor = NSColor.labelColor
    private static let stringColor = NSColor.systemGreen
    private static let numberColor = NSColor.systemBlue
    private static let booleanColor = NSColor.systemOrange
    private static let nullColor = NSColor.secondaryLabelColor
    private static let punctuationColor = NSColor.secondaryLabelColor
    
    private static let baseFont = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
    private static let keyFont = NSFont.monospacedSystemFont(ofSize: 11, weight: .semibold)
    
    /// Highlight a JSON string and return an NSAttributedString
    static func highlight(_ jsonString: String) -> NSAttributedString {
        let attributed = NSMutableAttributedString(
            string: jsonString,
            attributes: [
                .font: baseFont,
                .foregroundColor: keyColor
            ]
        )
        
        var index = jsonString.startIndex
        while index < jsonString.endIndex {
            let char = jsonString[index]
            
            // Skip whitespace
            if char.isWhitespace {
                index = jsonString.index(after: index)
                continue
            }
            
            // Parse strings
            if char == "\"" {
                if let (stringRange, isKey) = parseString(jsonString, startingAt: index) {
                    let nsRange = NSRange(stringRange, in: jsonString)
                    let color = isKey ? keyColor : stringColor
                    let font = isKey ? keyFont : baseFont
                    attributed.setAttributes([
                        .font: font,
                        .foregroundColor: color
                    ], range: nsRange)
                    index = stringRange.upperBound
                    continue
                }
            }
            
            // Parse numbers
            if char.isNumber || (char == "-" && peekAhead(jsonString, from: index)?.isNumber ?? false) {
                if let numberRange = parseNumber(jsonString, startingAt: index) {
                    let nsRange = NSRange(numberRange, in: jsonString)
                    attributed.setAttributes([
                        .font: baseFont,
                        .foregroundColor: numberColor
                    ], range: nsRange)
                    index = numberRange.upperBound
                    continue
                }
            }
            
            // Parse keywords (true, false, null)
            if char.isLetter {
                if let keywordRange = parseKeyword(jsonString, startingAt: index) {
                    let keyword = String(jsonString[keywordRange])
                    var color = nullColor
                    if keyword == "true" || keyword == "false" {
                        color = booleanColor
                    }
                    let nsRange = NSRange(keywordRange, in: jsonString)
                    attributed.setAttributes([
                        .font: baseFont,
                        .foregroundColor: color
                    ], range: nsRange)
                    index = keywordRange.upperBound
                    continue
                }
            }
            
            // Color punctuation
            if "{[]},:" ~= char {
                let nsRange = NSRange(index..<jsonString.index(after: index), in: jsonString)
                attributed.setAttributes([
                    .font: baseFont,
                    .foregroundColor: punctuationColor
                ], range: nsRange)
            }
            
            index = jsonString.index(after: index)
        }
        
        return attributed
    }
    
    // MARK: - Parsing Helpers
    
    /// Parse a JSON string, detecting if it's a key (followed by ':')
    /// Returns: (stringRange, isKey)
    private static func parseString(_ json: String, startingAt start: String.Index) -> (Range<String.Index>, Bool)? {
        guard json[start] == "\"" else { return nil }
        
        var index = json.index(after: start)
        while index < json.endIndex {
            let char = json[index]
            if char == "\"" {
                let stringRange = start...index
                
                // Check if followed by ':' (making this a key)
                var nextNonWS = json.index(after: index)
                while nextNonWS < json.endIndex && json[nextNonWS].isWhitespace {
                    nextNonWS = json.index(after: nextNonWS)
                }
                let isKey = nextNonWS < json.endIndex && json[nextNonWS] == ":"
                
                return (stringRange, isKey)
            }
            if char == "\\" && json.index(after: index) < json.endIndex {
                index = json.index(after: index)
            }
            index = json.index(after: index)
        }
        
        return nil
    }
    
    /// Parse a JSON number
    private static func parseNumber(_ json: String, startingAt start: String.Index) -> Range<String.Index>? {
        var index = start
        
        // Optional minus
        if json[index] == "-" {
            index = json.index(after: index)
        }
        
        // Integer part
        guard index < json.endIndex && json[index].isNumber else { return nil }
        while index < json.endIndex && json[index].isNumber {
            index = json.index(after: index)
        }
        
        // Optional decimal part
        if index < json.endIndex && json[index] == "." {
            index = json.index(after: index)
            while index < json.endIndex && json[index].isNumber {
                index = json.index(after: index)
            }
        }
        
        // Optional exponent
        if index < json.endIndex && (json[index] == "e" || json[index] == "E") {
            index = json.index(after: index)
            if index < json.endIndex && (json[index] == "+" || json[index] == "-") {
                index = json.index(after: index)
            }
            while index < json.endIndex && json[index].isNumber {
                index = json.index(after: index)
            }
        }
        
        return start..<index
    }
    
    /// Parse a keyword (true, false, null)
    private static func parseKeyword(_ json: String, startingAt start: String.Index) -> Range<String.Index>? {
        var index = start
        while index < json.endIndex && json[index].isLetter {
            index = json.index(after: index)
        }
        let word = String(json[start..<index])
        return ["true", "false", "null"].contains(word) ? (start..<index) : nil
    }
    
    /// Peek at the next character without advancing
    private static func peekAhead(_ json: String, from index: String.Index) -> Character? {
        let next = json.index(after: index)
        return next < json.endIndex ? json[next] : nil
    }
}

// MARK: - Character Range Matching

private func ~= (pattern: String, value: Character) -> Bool {
    pattern.contains(String(value))
}
