import SwiftUI
import AppKit

/// Editable JSON editor with syntax highlighting, validation, and error display
struct JSONEditorView: View {
    @Binding var jsonText: String
    let inputSchema: Data
    @AppStorage("jsonViewer.fontSize") private var fontSize: Double = 11
    @State private var jsonErrors: [JSONSchemaValidator.Issue] = []
    @State private var validationTask: Task<Void, any Error>?

    var body: some View {
        VStack(spacing: 0) {
            // Editor — NSTextView without updateNSView attribute updates
            SimpleJSONTextEditor(text: $jsonText, fontSize: fontSize)
                .onChange(of: jsonText) { _, newText in
                    debounceValidation(newText)
                }
                .frame(maxHeight: .infinity)

            // Error/Warning display area — fixed reserved space to prevent bouncing
            VStack(alignment: .leading, spacing: 6) {
                if !jsonErrors.isEmpty {
                    ForEach(jsonErrors.indices, id: \.self) { index in
                        let issue = jsonErrors[index]
                        HStack(spacing: 8) {
                            Image(systemName: issue.level == .error ? "xmark.circle.fill" : "exclamationmark.circle.fill")
                                .foregroundStyle(issue.level == .error ? .red : .orange)
                                .font(.caption)

                            Text(issue.message)
                                .font(.caption)
                                .foregroundStyle(issue.level == .error ? .red : .orange)

                            Spacer()
                        }
                    }
                }
            }
            .frame(height: 24)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color(nsColor: .controlBackgroundColor))
            .overlay(Divider(), alignment: .top)
        }
        .onDisappear {
            validationTask?.cancel()
        }
    }
    
    private func debounceValidation(_ text: String) {
        validationTask?.cancel()
        
        let task = Task {
            do {
                try await Task.sleep(nanoseconds: 300_000_000)
                
                var issues: [JSONSchemaValidator.Issue] = []
                
                // Check if JSON is valid
                let (isValid, errorMsg) = JSONSchemaValidator.isValidJSON(text)
                if !isValid {
                    if let msg = errorMsg {
                        issues.append(JSONSchemaValidator.Issue(level: .error, message: "Invalid JSON: \(msg)"))
                    }
                } else {
                    // Validate against schema if available
                    if let jsonData = text.data(using: .utf8),
                       let payload = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
                       let schema = try? JSONSerialization.jsonObject(with: inputSchema) as? [String: Any] {
                        issues = JSONSchemaValidator.validate(payload: payload, against: schema)
                    }
                }
                
                // Update on main thread
                await MainActor.run {
                    self.jsonErrors = issues
                }
            } catch is CancellationError {
                // Validation was cancelled, ignore
            }
        }
        
        validationTask = task
    }
}

/// NSTextView wrapper using NSTextStorageDelegate for cursor-safe syntax highlighting.
///
/// The key insight: highlighting happens inside `textStorage(_:didProcessEditing:range:changeInLength:)`
/// which is called DURING the text storage's editing transaction. Attribute changes made here
/// are part of the same edit operation as the text change, so the cursor is never disrupted.
///
/// Previous attempts that FAILED:
/// - Attempt 1: setAttributes in updateNSView (SwiftUI re-entrancy disrupts cursor)
/// - Attempt 2: setAttributes in textDidChange (still disrupts cursor — not inside editing transaction)
struct SimpleJSONTextEditor: NSViewRepresentable {
    @Binding var text: String
    let fontSize: Double
    var scrollToText: String? = nil

    func makeNSView(context: Context) -> NSScrollView {
        let textView = NSTextView()
        textView.isEditable = true
        textView.isSelectable = true
        textView.backgroundColor = NSColor.textBackgroundColor
        textView.textContainerInset = NSSize(width: 12, height: 8)
        textView.textContainer?.lineFragmentPadding = 0
        textView.font = NSFont.monospacedSystemFont(ofSize: fontSize, weight: .regular)
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.isAutomaticTextReplacementEnabled = false
        textView.delegate = context.coordinator

        // Set the coordinator as the textStorage delegate — this is where highlighting happens
        textView.textStorage?.delegate = context.coordinator
        context.coordinator.fontSize = fontSize
        context.coordinator.textView = textView
        context.coordinator.scrollToText = scrollToText

        // Set initial text
        textView.string = text
        // Initial highlighting will be triggered by the textStorage delegate

        // Wrap in scroll view for proper layout
        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.documentView = textView
        textView.autoresizingMask = [.width]
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.textContainer?.widthTracksTextView = true

        // Scroll to target text after layout is complete
        if scrollToText != nil {
            DispatchQueue.main.async {
                context.coordinator.performScroll(in: scrollView)
            }
        }

        return scrollView
    }

    func updateNSView(_ nsView: NSScrollView, context: Context) {
        guard let textView = nsView.documentView as? NSTextView else { return }

        // Update font size for future highlighting
        context.coordinator.fontSize = fontSize

        // Sync text from binding (e.g., pre-fill from history, reset button)
        // Only when text actually differs — avoids fighting with user typing
        if textView.string != text {
            context.coordinator.isSyncingFromBinding = true
            textView.string = text
            context.coordinator.isSyncingFromBinding = false
            // Force re-highlight after external text change
            if let textStorage = textView.textStorage {
                let fullRange = NSRange(location: 0, length: textStorage.length)
                textStorage.edited(.editedAttributes, range: fullRange, changeInLength: 0)
            }
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(text: $text)
    }

    @MainActor
    class Coordinator: NSObject, NSTextViewDelegate, @preconcurrency NSTextStorageDelegate {
        @Binding var text: String
        var fontSize: Double = 11
        var isSyncingFromBinding = false
        weak var textView: NSTextView?
        var scrollToText: String?

        init(text: Binding<String>) {
            self._text = text
        }

        /// Perform scroll-to-text after layout is complete
        func performScroll(in scrollView: NSScrollView) {
            guard let scrollToText = scrollToText,
                  let textView = textView,
                  let range = textView.string.range(of: scrollToText) else { return }

            let nsRange = NSRange(range, in: textView.string)
            textView.setSelectedRange(nsRange)
            textView.scrollRangeToVisible(nsRange)

            // Scroll up a bit so the match is ~3 lines from top, not at the very top
            if let layoutManager = textView.layoutManager,
               let textContainer = textView.textContainer {
                let glyphRange = layoutManager.glyphRange(forCharacterRange: nsRange, actualCharacterRange: nil)
                let rect = layoutManager.boundingRect(forGlyphRange: glyphRange, in: textContainer)
                let lineHeight = textView.font?.pointSize ?? 11
                let targetY = max(0, rect.origin.y + textView.textContainerInset.height - lineHeight * 3)
                scrollView.contentView.scroll(to: NSPoint(x: 0, y: targetY))
            }
        }

        // MARK: - NSTextViewDelegate

        func textDidChange(_ notification: Notification) {
            guard !isSyncingFromBinding,
                  let textView = notification.object as? NSTextView else { return }
            // Only update the binding — NO highlighting here
            text = textView.string
        }

        // MARK: - NSTextStorageDelegate

        /// Called during the text storage's editing transaction.
        /// Attribute changes here are part of the same edit — cursor is not disrupted.
        func textStorage(
            _ textStorage: NSTextStorage,
            didProcessEditing editedMask: NSTextStorageEditActions,
            range editedRange: NSRange,
            changeInLength delta: Int
        ) {
            // Only re-highlight when text actually changed (not just attributes)
            // This prevents infinite recursion: text edit → highlight → attribute edit → (stop)
            guard editedMask.contains(.editedCharacters) else { return }

            let fullText = textStorage.string
            let highlighted = JSONHighlighter.highlight(fullText, fontSize: fontSize)
            let fullRange = NSRange(location: 0, length: textStorage.length)

            // Apply attributes from highlighted string onto existing storage
            // This is safe inside didProcessEditing — it only triggers another
            // didProcessEditing with .editedAttributes (which we skip above)
            highlighted.enumerateAttributes(in: NSRange(location: 0, length: highlighted.length)) { attrs, range, _ in
                if range.location + range.length <= fullRange.length {
                    textStorage.setAttributes(attrs, range: range)
                }
            }
        }
    }
}

#Preview {
    @Previewable @State var jsonText = """
    {
      "name": "example",
      "value": 42
    }
    """

    let schema = try! JSONSerialization.data(withJSONObject: [
        "type": "object",
        "properties": [
            "name": ["type": "string"],
            "value": ["type": "integer"]
        ],
        "required": ["name"]
    ])

    JSONEditorView(jsonText: $jsonText, inputSchema: schema)
}
