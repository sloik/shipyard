import SwiftUI
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ExecutionDetailView")

/// Detailed view of a single execution showing request and response
struct ExecutionDetailView: View {
    @Environment(ExecutionQueueManager.self) private var queueManager

    let execution: ToolExecution
    let onBack: () -> Void
    var onRetry: ((ToolExecution) -> Void)? = nil
    var onFastRetry: ((ToolExecution) -> Void)? = nil

    @AppStorage("execution.detail.dividerPosition") private var dividerFraction: Double = 0.35
    @State private var isRequestCollapsed = false

    private let minSectionHeight: Double = 60
    private let dividerHeight: Double = 12

    /// Returns true if execution is in a completed state (success, failure, or cancelled)
    private var isCompletedStatus: Bool {
        switch execution.status {
        case .success, .failure, .cancelled:
            return true
        case .pending, .executing:
            return false
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack(spacing: 12) {
                Button(action: onBack) {
                    Label(L10n.string("execution.detail.backButton"), systemImage: "chevron.left")
                        .font(.callout)
                }
                .buttonStyle(.bordered)

                VStack(alignment: .leading, spacing: 2) {
                    Text(execution.toolName)
                        .font(.headline)

                    HStack(spacing: 8) {
                        statusBadge

                        if let startedAt = execution.startedAt {
                            Text(formatHeaderTimestamp(startedAt))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                Spacer()

                // Retry buttons for completed executions
                if isCompletedStatus {
                    Button(action: { onRetry?(execution) }) {
                        Label(L10n.string("common.action.retry"), systemImage: "play.fill")
                            .font(.callout)
                    }
                    .buttonStyle(.bordered)

                    Button(action: { onFastRetry?(execution) }) {
                        Image(systemName: "bolt.fill")
                            .font(.callout)
                    }
                    .buttonStyle(.bordered)
                    .help(L10n.string("execution.row.fastRetryHelp"))
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(Color(nsColor: .controlBackgroundColor))
            .overlay(Divider(), alignment: .bottom)

            // Content with draggable divider
            GeometryReader { geometry in
                let totalHeight = geometry.size.height
                let requestHeight = isRequestCollapsed ? 0 : totalHeight * dividerFraction
                let minRequestHeight = isRequestCollapsed ? 0 : minSectionHeight
                let maxRequestHeight = totalHeight - minSectionHeight - dividerHeight

                VStack(spacing: 0) {
                    // Request section
                    if !isRequestCollapsed {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 16) {
                                VStack(alignment: .leading, spacing: 8) {
                                    Text(L10n.string("execution.detail.requestTitle"))
                                        .font(.callout)
                                        .fontWeight(.semibold)

                                    requestPayloadView
                                }
                            }
                            .padding(.horizontal, 16)
                            .padding(.vertical, 12)
                        }
                        .frame(height: requestHeight)
                    }

                    // Draggable divider
                    HStack(spacing: 8) {
                        Spacer()
                        Image(systemName: "line.3.horizontal")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                    }
                    .frame(height: dividerHeight)
                    .background(Color.gray.opacity(0.2))
                    .contentShape(Rectangle())
                    .gesture(
                        DragGesture()
                            .onChanged { value in
                                let newFraction = (requestHeight + value.translation.height) / totalHeight
                                let clampedFraction = min(
                                    max(newFraction, minSectionHeight / totalHeight),
                                    (totalHeight - minSectionHeight) / totalHeight
                                )
                                dividerFraction = clampedFraction
                            }
                    )
                    .onTapGesture(count: 2) {
                        withAnimation {
                            isRequestCollapsed.toggle()
                        }
                    }

                    // Response section
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(L10n.string("execution.detail.responseTitle"))
                                    .font(.callout)
                                    .fontWeight(.semibold)

                                responsePayloadView
                            }

                            if let error = execution.error, !error.isEmpty {
                                Divider()

                                VStack(alignment: .leading, spacing: 8) {
                                    Text(L10n.string("execution.detail.errorTitle"))
                                        .font(.callout)
                                        .fontWeight(.semibold)
                                        .foregroundStyle(.red)

                                    Text(error)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .padding(.horizontal, 12)
                                        .padding(.vertical, 8)
                                        .background(Color.red.opacity(0.05))
                                        .cornerRadius(4)
                                }
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                    }
                    .frame(maxHeight: .infinity)
                }
            }
        }
    }
    
    @ViewBuilder
    private var statusBadge: some View {
        HStack(spacing: 6) {
            switch execution.status {
            case .pending:
                Image(systemName: "hourglass")
                    .foregroundStyle(.orange)
                Text(L10n.string("common.state.pending"))
                    .font(.caption)
                    .fontWeight(.medium)
                    .foregroundStyle(.orange)
                
            case .executing:
                Image(systemName: "hourglass")
                    .foregroundStyle(.orange)
                Text(L10n.string("common.state.running"))
                    .font(.caption)
                    .fontWeight(.medium)
                    .foregroundStyle(.orange)
                
            case .success:
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                Text(L10n.string("common.state.success"))
                    .font(.caption)
                    .fontWeight(.medium)
                    .foregroundStyle(.green)
                
            case .failure:
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.red)
                Text(L10n.string("common.state.failed"))
                    .font(.caption)
                    .fontWeight(.medium)
                    .foregroundStyle(.red)
                
            case .cancelled:
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.gray)
                Text(L10n.string("common.state.cancelled"))
                    .font(.caption)
                    .fontWeight(.medium)
                    .foregroundStyle(.gray)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(Color.gray.opacity(0.1))
        .cornerRadius(4)
    }
    
    @ViewBuilder
    private var requestPayloadView: some View {
        let requestJSON = JSONFormatter.format(execution.request.arguments)

        VStack(alignment: .leading, spacing: 0) {
            Text(L10n.string("execution.detail.argumentsLabel"))
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)

            CodeBlockView(jsonString: requestJSON)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color.gray.opacity(0.05))
        .cornerRadius(4)
    }
    
    @ViewBuilder
    private var responsePayloadView: some View {
        if let response = execution.response {
            let responseJSON = JSONFormatter.formatResponse(response.responseJSON)
            
            VStack(alignment: .leading, spacing: 0) {
                Text(L10n.string("execution.detail.resultLabel"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                
                CodeBlockView(jsonString: responseJSON)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color.gray.opacity(0.05))
            .cornerRadius(4)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                Text(L10n.string("execution.detail.waitingForResponse"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color.gray.opacity(0.05))
            .cornerRadius(4)
        }
    }
    
    private func formatHeaderTimestamp(_ date: Date) -> String {
        let timeFormatter = DateFormatter()
        timeFormatter.timeStyle = .medium
        timeFormatter.dateStyle = .short
        return timeFormatter.string(from: date)
    }
}

#Preview {
    @Previewable @State var queueManager = ExecutionQueueManager()
    @Previewable @State var execution = ToolExecution(
        toolName: "shipyard__shipyard_gateway_call",
        request: ToolExecutionRequest(
            toolName: "shipyard__shipyard_gateway_call",
            arguments: ["tool": "shipyard__shipyard_status", "arguments": [:]]
        )
    )
    
    ExecutionDetailView(execution: execution, onBack: {}, onRetry: nil)
        .environment(queueManager)
        .onAppear {
            execution.markExecuting()
            execution.markSuccess(response: ToolExecutionResponse(responseJSON: #"{"servers":[{"name":"lmstudio","state":"running"}]}"#))
        }
}
