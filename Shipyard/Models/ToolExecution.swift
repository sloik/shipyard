import Foundation

// MARK: - ExecutionStatus Enum

enum ExecutionStatus: String, Sendable {
    case pending
    case executing
    case success
    case failure
    case cancelled
}

// MARK: - ToolExecution Model

/// Represents a single tool execution with full lifecycle tracking
@Observable @MainActor final class ToolExecution: Identifiable {
    nonisolated let id: UUID
    nonisolated let toolName: String
    let request: ToolExecutionRequest
    
    var status: ExecutionStatus = .pending
    var startedAt: Date?
    var completedAt: Date?
    var response: ToolExecutionResponse?
    var error: String?
    
    /// The underlying Task for this execution (stored for cancellation)
    private var task: Task<Void, Never>?
    
    init(
        id: UUID = UUID(),
        toolName: String,
        request: ToolExecutionRequest
    ) {
        self.id = id
        self.toolName = toolName
        self.request = request
    }
    
    /// Computed: elapsed time in seconds since start (or duration if completed)
    var elapsedSeconds: Double {
        let start = startedAt ?? Date()
        let end = completedAt ?? Date()
        return end.timeIntervalSince(start)
    }
    
    /// Set the task reference for cancellation
    func setTask(_ newTask: Task<Void, Never>) {
        self.task = newTask
    }
    
    /// Cancel the execution
    func cancel() {
        task?.cancel()
        self.status = .cancelled
    }
    
    /// Mark as executing
    func markExecuting() {
        self.status = .executing
        self.startedAt = Date()
    }
    
    /// Mark as success with response
    func markSuccess(response: ToolExecutionResponse) {
        self.status = .success
        self.response = response
        self.completedAt = Date()
    }
    
    /// Mark as failure with error
    func markFailure(error: String) {
        self.status = .failure
        self.error = error
        self.completedAt = Date()
    }
}
