import SwiftUI
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ExecutionQueuePanelView")

/// Bottom panel showing active and completed tool executions
struct ExecutionQueuePanelView: View {
    @Environment(ExecutionQueueManager.self) private var queueManager

    @State private var isCollapsed = false
    @AppStorage("execution.queue.panel.height") private var panelHeight: Double = 120

    var onViewExecution: ((ToolExecution) -> Void)?
    var onRetryExecution: ((ToolExecution) -> Void)?
    
    private let minPanelHeight: Double = 60
    private let maxPanelHeight: Double = 300
    private let dividerHeight: Double = 4
    
    var body: some View {
        VStack(spacing: 0) {
            // Draggable divider
            Rectangle()
                .fill(Color.gray.opacity(0.3))
                .frame(height: dividerHeight)
                .contentShape(Rectangle())
                .gesture(
                    DragGesture()
                        .onChanged { value in
                            let newHeight = panelHeight - value.translation.height
                            panelHeight = min(maxPanelHeight, max(minPanelHeight, newHeight))
                        }
                )
            
            // Panel header
            HStack(spacing: 12) {
                // Collapse/expand button
                Button(action: { withAnimation { isCollapsed.toggle() } }) {
                    Image(systemName: isCollapsed ? "chevron.right" : "chevron.down")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .help(L10n.string(isCollapsed ? "execution.panel.expandHelp" : "execution.panel.collapseHelp"))
                
                // Title with counts
                let activeCount = queueManager.activeExecutions.count
                let completedCount = queueManager.history.count
                Text(L10n.format("execution.panel.title", activeCount, completedCount))
                    .font(.callout)
                    .fontWeight(.semibold)
                
                Spacer()
                
                // Clear history button
                Button(action: clearHistory) {
                    Label(L10n.string("execution.panel.clearHistoryButton"), systemImage: "trash")
                        .font(.caption)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(queueManager.history.isEmpty)
                .help(L10n.string("execution.panel.clearHistoryHelp"))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color(nsColor: .controlBackgroundColor))
            .overlay(Divider(), alignment: .bottom)
            
            // Collapsed state: just show the header
            if isCollapsed {
                Spacer()
            } else {
                // Expanded state: show entries
                ScrollView {
                    VStack(spacing: 0) {
                        if queueManager.activeExecutions.isEmpty && queueManager.history.isEmpty {
                            // Empty state
                            VStack(spacing: 8) {
                                Image(systemName: "hourglass")
                                    .font(.system(size: 24))
                                    .foregroundStyle(.secondary)
                                Text(L10n.string("execution.panel.emptyMessage"))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .multilineTextAlignment(.center)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 16)
                        } else {
                            // Active executions section
                            if !queueManager.activeExecutions.isEmpty {
                                VStack(alignment: .leading, spacing: 0) {
                                    Text(L10n.string("execution.panel.activeSectionTitle"))
                                        .font(.caption)
                                        .fontWeight(.semibold)
                                        .foregroundStyle(.secondary)
                                        .padding(.horizontal, 12)
                                        .padding(.vertical, 8)
                                    
                                    ForEach(queueManager.activeExecutions, id: \.id) { execution in
                                        ExecutionQueueRowView(execution: execution, onView: { onViewExecution?(execution) }, onRetry: { onRetryExecution?($0) })

                                        if execution.id != queueManager.activeExecutions.last?.id {
                                            Divider()
                                                .padding(.vertical, 0)
                                        }
                                    }
                                }
                            }
                            
                            // Separator between active and history
                            if !queueManager.activeExecutions.isEmpty && !queueManager.history.isEmpty {
                                Divider()
                                    .padding(.vertical, 4)
                            }
                            
                            // History section
                            if !queueManager.history.isEmpty {
                                VStack(alignment: .leading, spacing: 0) {
                                    Text(L10n.string("execution.panel.historySectionTitle"))
                                        .font(.caption)
                                        .fontWeight(.semibold)
                                        .foregroundStyle(.secondary)
                                        .padding(.horizontal, 12)
                                        .padding(.vertical, 8)
                                    
                                    ForEach(queueManager.history, id: \.id) { execution in
                                        ExecutionQueueRowView(execution: execution, onView: { onViewExecution?(execution) }, onRetry: { onRetryExecution?($0) })

                                        if execution.id != queueManager.history.last?.id {
                                            Divider()
                                                .padding(.vertical, 0)
                                        }
                                    }
                                }
                            }
                        }
                    }
                    .padding(.horizontal, 0)
                    .padding(.vertical, 8)
                }
            }
        }
        .frame(height: isCollapsed ? 44 : panelHeight)
        .background(Color(nsColor: .controlBackgroundColor))
    }
    
    private func clearHistory() {
        queueManager.history.removeAll()
    }
}

#Preview {
    @Previewable @State var queueManager = ExecutionQueueManager()
    
    ExecutionQueuePanelView()
        .environment(queueManager)
        .frame(height: 200)
}
