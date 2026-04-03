import SwiftUI
import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ExecutionQueueRowView")

/// A single row in the execution queue panel
struct ExecutionQueueRowView: View {
    @Environment(ExecutionQueueManager.self) private var queueManager

    let execution: ToolExecution
    var onView: (() -> Void)?
    var onRetry: ((ToolExecution) -> Void)?
    
    var body: some View {
        HStack(spacing: 12) {
            // Status icon
            statusIcon
            
            // Tool name and timestamp
            VStack(alignment: .leading, spacing: 2) {
                Text(execution.toolName)
                    .font(.callout)
                    .fontWeight(.medium)
                    .lineLimit(1)
                    .truncationMode(.tail)
                
                Text(formatTimestamp(execution.startedAt ?? Date()))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            
            Spacer()
            
            // Elapsed time
            elapsedTimeView
            
            // Action buttons (for completed/failed entries only)
            if execution.status != .pending && execution.status != .executing {
                HStack(spacing: 6) {
                    Button(action: { onView?() }) {
                        Text(L10n.string("common.action.view"))
                            .font(.caption)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    
                    Button(action: { onRetry?(execution) }) {
                        Text(L10n.string("common.action.retry"))
                            .font(.caption)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    
                    Button(action: { fastRetry() }) {
                        Image(systemName: "bolt.fill")
                            .font(.caption)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .help(L10n.string("execution.row.fastRetryHelp"))
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }
    
    @ViewBuilder
    private var statusIcon: some View {
        switch execution.status {
        case .pending, .executing:
            Image(systemName: "hourglass")
                .font(.caption)
                .foregroundStyle(.orange)
        case .success:
            Image(systemName: "checkmark.circle.fill")
                .font(.caption)
                .foregroundStyle(.green)
        case .failure:
            Image(systemName: "xmark.circle.fill")
                .font(.caption)
                .foregroundStyle(.red)
        case .cancelled:
            Image(systemName: "xmark.circle.fill")
                .font(.caption)
                .foregroundStyle(.gray)
        }
    }
    
    @ViewBuilder
    private var elapsedTimeView: some View {
        if execution.status == .pending || execution.status == .executing {
            // Live elapsed time using TimelineView
            TimelineView(.periodic(from: Date(), by: 1.0)) { context in
                Text(formatElapsedTime(execution.elapsedSeconds))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .monospaced()
            }
        } else {
            // Fixed elapsed time for completed entries
            Text(formatElapsedTime(execution.elapsedSeconds))
                .font(.caption)
                .foregroundStyle(.secondary)
                .monospaced()
        }
    }
    
    private func formatElapsedTime(_ seconds: Double) -> String {
        let totalSeconds = Int(seconds)
        let hours = totalSeconds / 3600
        let minutes = (totalSeconds % 3600) / 60
        let secs = totalSeconds % 60
        
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, secs)
        } else {
            return String(format: "%d:%02d", minutes, secs)
        }
    }
    
    private func fastRetry() {
        let newExecution = queueManager.retryExecution(execution)
        log.debug("Fast retry execution: \(execution.toolName) -> new id: \(newExecution.id.uuidString)")
    }
    
    private func formatTimestamp(_ date: Date) -> String {
        let timeFormatter = DateFormatter()
        timeFormatter.timeStyle = .medium
        timeFormatter.dateStyle = .none
        return timeFormatter.string(from: date)
    }
}

#Preview {
    @Previewable @State var queueManager = ExecutionQueueManager()
    @Previewable @State var activeExecution = ToolExecution(
        toolName: "shipyard__shipyard_status",
        request: ToolExecutionRequest(toolName: "shipyard__shipyard_status", arguments: [:])
    )
    @Previewable @State var completedExecution = ToolExecution(
        toolName: "shipyard__shipyard_health",
        request: ToolExecutionRequest(toolName: "shipyard__shipyard_health", arguments: [:])
    )
    
    VStack(spacing: 0) {
        ExecutionQueueRowView(execution: activeExecution)
        Divider()
        ExecutionQueueRowView(execution: completedExecution)
    }
    .environment(queueManager)
    .onAppear {
        activeExecution.markExecuting()
        completedExecution.markExecuting()
        completedExecution.markSuccess(response: ToolExecutionResponse(responseJSON: "{}"))
    }
}
