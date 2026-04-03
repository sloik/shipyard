import SwiftUI
import AppKit

/// Read-only JSON viewer with syntax highlighting, line numbers, and search
struct CodeBlockView: View {
    let jsonString: String
    @AppStorage("jsonViewer.fontSize") private var fontSize: Double = 11
    @State private var searchText = ""
    @State private var currentMatchIndex = 0
    @State private var matchRanges: [NSRange] = []
    
    var body: some View {
        VStack(spacing: 0) {
            // Search bar
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                
                TextField(L10n.string("common.search.placeholder"), text: $searchText)
                    .textFieldStyle(.plain)
                    .font(.caption)
                
                if !searchText.isEmpty {
                    HStack(spacing: 4) {
                        Text(L10n.format("common.search.matchCount", matchRanges.isEmpty ? 0 : currentMatchIndex + 1, matchRanges.count))
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        
                        Button(action: previousMatch) {
                            Image(systemName: "chevron.up")
                                .font(.caption)
                        }
                        .buttonStyle(.plain)
                        .disabled(matchRanges.isEmpty)
                        
                        Button(action: nextMatch) {
                            Image(systemName: "chevron.down")
                                .font(.caption)
                        }
                        .buttonStyle(.plain)
                        .disabled(matchRanges.isEmpty)
                    }
                }
                
                Spacer()
                
                Button(action: copyJSON) {
                    Image(systemName: "doc.on.doc")
                        .font(.caption)
                }
                .buttonStyle(.plain)
                .help(L10n.string("common.action.copyJsonHelp"))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color(nsColor: .controlBackgroundColor))
            .overlay(Divider(), alignment: .bottom)
            
            // Code viewer
            ScrollView(.vertical) {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(highlightedLines.enumerated()), id: \.offset) { index, lineAttrString in
                        HStack(alignment: .top, spacing: 0) {
                            // Line number
                            Text("\(index + 1)")
                                .font(.system(size: fontSize, design: .monospaced))
                                .foregroundStyle(.secondary)
                                .frame(width: gutterWidth, alignment: .trailing)
                                .padding(.trailing, 12)

                            // Content wraps to available width and grows vertically when needed.
                            lineTextView(lineAttrString)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(.leading, 8)
                    }
                }
                .padding(.vertical, 8)
                .padding(.leading, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(Color(nsColor: .textBackgroundColor))
        }
        .onChange(of: searchText) { _, newText in
            updateSearchMatches(newText)
        }
    }
    
    private var lineCount: Int {
        jsonString.components(separatedBy: .newlines).count
    }

    private var gutterWidth: CGFloat {
        let digitCount = max(1, String(lineCount).count)
        return CGFloat(digitCount * 7 + 4)  // ~7 pts per digit + padding
    }
    
    private var highlightedJSON: NSAttributedString {
        let highlighted = NSMutableAttributedString(attributedString: JSONHighlighter.highlight(jsonString, fontSize: fontSize))

        // Apply search highlighting
        for (index, range) in matchRanges.enumerated() {
            let bgColor = index == currentMatchIndex
                ? NSColor.systemOrange.withAlphaComponent(0.3)
                : NSColor.systemYellow.withAlphaComponent(0.2)
            highlighted.addAttribute(.backgroundColor, value: bgColor, range: range)
        }

        return highlighted
    }

    private var highlightedLines: [NSAttributedString] {
        Self.splitLines(from: highlightedJSON)
    }

    static func splitLines(from attributedString: NSAttributedString) -> [NSAttributedString] {
        let string = attributedString.string
        let lines = string.components(separatedBy: "\n")
        var result: [NSAttributedString] = []
        var location = 0

        for line in lines {
            let utf16Length = (line as NSString).length
            let range = NSRange(location: location, length: utf16Length)
            let lineAttr = attributedString.attributedSubstring(from: range)
            result.append(lineAttr)
            location += utf16Length + 1  // +1 for newline
        }

        return result
    }
    
    private func updateSearchMatches(_ text: String) {
        matchRanges = []
        currentMatchIndex = 0
        
        guard !text.isEmpty else { return }
        
        let searchRange = NSRange(jsonString.startIndex..., in: jsonString)
        var foundRange = NSRange(location: 0, length: 0)
        
        while foundRange.location != NSNotFound {
            foundRange = (jsonString as NSString).range(
                of: text,
                options: .caseInsensitive,
                range: NSRange(location: foundRange.location + foundRange.length, length: searchRange.length - (foundRange.location + foundRange.length))
            )
            
            if foundRange.location != NSNotFound {
                matchRanges.append(foundRange)
            }
        }
    }
    
    private func nextMatch() {
        if !matchRanges.isEmpty {
            currentMatchIndex = (currentMatchIndex + 1) % matchRanges.count
        }
    }
    
    private func previousMatch() {
        if !matchRanges.isEmpty {
            currentMatchIndex = currentMatchIndex == 0 ? matchRanges.count - 1 : currentMatchIndex - 1
        }
    }
    
    private func copyJSON() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(jsonString, forType: .string)
    }

    @ViewBuilder
    private func lineTextView(_ lineAttrString: NSAttributedString) -> some View {
        if lineAttrString.length == 0 {
            Text(" ")
                .font(.system(size: fontSize, design: .monospaced))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .multilineTextAlignment(.leading)
        } else if let swiftAttr = try? AttributedString(lineAttrString, including: \.appKit) {
            Text(swiftAttr)
                .font(.system(size: fontSize, design: .monospaced))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .multilineTextAlignment(.leading)
        } else {
            Text(lineAttrString.string)
                .font(.system(size: fontSize, design: .monospaced))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .multilineTextAlignment(.leading)
        }
    }
}


#Preview {
    let sampleJSON = """
    {
      "name": "cortex_query",
      "description": "Query the knowledge base",
      "parameters": {
        "query": "user research",
        "limit": 10
      },
      "enabled": true
    }
    """
    
    CodeBlockView(jsonString: sampleJSON)
}
