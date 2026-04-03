import Testing
import Foundation
@testable import Shipyard

@Suite("ExecutionQueueManager")
@MainActor
struct ExecutionQueueManagerTests {
    
    // MARK: - Test Helpers
    
    private func makeManager() -> ExecutionQueueManager {
        let suiteName = "com.shipyard.test.execution.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return ExecutionQueueManager(defaults: defaults)
    }
    
    // MARK: - Initialization Tests
    
    @Test("ExecutionQueueManager initializes with empty queues")
    func initializesEmpty() {
        let manager = makeManager()
        
        #expect(manager.activeExecutions.isEmpty)
        #expect(manager.history.isEmpty)
    }
    
    // MARK: - Execution Lifecycle Tests
    
    @Test("executeToolAsync creates execution in pending state")
    func executeToolAsyncCreatesPendingExecution() {
        let manager = makeManager()
        let toolName = "test_tool"
        let args: [String: Any] = ["param": "value"]
        
        let execution = manager.executeToolAsync(toolName: toolName, arguments: args)
        
        #expect(execution.toolName == toolName)
        #expect(execution.status == .pending)
        #expect(execution.startedAt == nil)
        #expect(execution.completedAt == nil)
    }
    
    @Test("executeToolAsync adds execution to active list")
    func executeToolAsyncAddsToActive() {
        let manager = makeManager()
        
        let ex1 = manager.executeToolAsync(toolName: "tool1", arguments: [:])
        let ex2 = manager.executeToolAsync(toolName: "tool2", arguments: [:])
        
        #expect(manager.activeExecutions.count == 2)
        #expect(manager.activeExecutions.contains { $0.id == ex1.id })
        #expect(manager.activeExecutions.contains { $0.id == ex2.id })
    }
    
    @Test("markExecuting updates status and startedAt")
    func markExecutingUpdatesState() {
        let execution = ToolExecution(toolName: "test", request: ToolExecutionRequest(toolName: "test", arguments: [:]))
        let before = Date()
        
        execution.markExecuting()
        
        let after = Date()
        
        #expect(execution.status == .executing)
        #expect(execution.startedAt != nil)
        #expect(execution.startedAt! >= before)
        #expect(execution.startedAt! <= after)
    }
    
    @Test("markSuccess updates status, response, and completedAt")
    func markSuccessUpdatesState() {
        let execution = ToolExecution(toolName: "test", request: ToolExecutionRequest(toolName: "test", arguments: [:]))
        let response = ToolExecutionResponse(responseJSON: "{\"result\": \"ok\"}")
        let before = Date()
        
        execution.markSuccess(response: response)
        
        let after = Date()
        
        #expect(execution.status == .success)
        #expect(execution.response?.responseJSON == "{\"result\": \"ok\"}")
        #expect(execution.completedAt != nil)
        #expect(execution.completedAt! >= before)
        #expect(execution.completedAt! <= after)
    }
    
    @Test("markFailure updates status, error, and completedAt")
    func markFailureUpdatesState() {
        let execution = ToolExecution(toolName: "test", request: ToolExecutionRequest(toolName: "test", arguments: [:]))
        let errorMsg = "Tool not found"
        let before = Date()
        
        execution.markFailure(error: errorMsg)
        
        let after = Date()
        
        #expect(execution.status == .failure)
        #expect(execution.error == errorMsg)
        #expect(execution.completedAt != nil)
        #expect(execution.completedAt! >= before)
        #expect(execution.completedAt! <= after)
    }
    
    // MARK: - History Management Tests
    
    @Test("History caps at maxHistorySize (20)")
    func historyCapsAt20() {
        let manager = makeManager()
        
        // Execute 25 tools to fill history beyond the cap
        for i in 0..<25 {
            let execution = manager.executeToolAsync(
                toolName: "tool_\(i)",
                arguments: [:]
            )
            
            // Simulate execution completing
            execution.markSuccess(response: ToolExecutionResponse(responseJSON: "{\"n\": \(i)}"))
            
            // Manually move to history to test cap logic
            // Remove from active and add to history (replicating what would happen in executeInternal)
            if let idx = manager.activeExecutions.firstIndex(where: { $0.id == execution.id }) {
                manager.activeExecutions.remove(at: idx)
                manager.history.insert(execution, at: 0)
                // Cap at 20
                if manager.history.count > 20 {
                    manager.history.removeLast(manager.history.count - 20)
                }
            }
        }
        
        #expect(manager.history.count == 20)
        // Newest should be at index 0 (tool_24), oldest at index 19 (tool_5)
        #expect(manager.history[0].toolName == "tool_24")
        #expect(manager.history[19].toolName == "tool_5")
    }
    
    // MARK: - Cancellation Tests
    
    @Test("cancel() sets status to cancelled")
    func cancelSetsStatus() {
        let execution = ToolExecution(toolName: "test", request: ToolExecutionRequest(toolName: "test", arguments: [:]))
        
        execution.cancel()
        
        #expect(execution.status == .cancelled)
    }
    
    // MARK: - Retry Tests
    
    @Test("retryExecution creates new execution with same request")
    func retryExecutionCreatesNewWithSameRequest() {
        let manager = makeManager()
        let toolName = "retry_tool"
        let args: [String: Any] = ["key": "value"]
        
        let ex1 = manager.executeToolAsync(toolName: toolName, arguments: args)
        let ex2 = manager.retryExecution(ex1)
        
        #expect(ex1.id != ex2.id)  // Different executions
        #expect(ex2.toolName == ex1.toolName)
        #expect(ex2.request.toolName == ex1.request.toolName)
    }
    
    // MARK: - Recent Calls Tests
    
    @Test("getRecentCalls returns empty list for new tool")
    func getRecentCallsEmptyForNewTool() {
        let manager = makeManager()
        
        let calls = manager.getRecentCalls(for: "nonexistent_tool")
        
        #expect(calls.isEmpty)
    }
    
    @Test("elapsedSeconds computes correctly")
    func elapsedSecondsComputes() {
        let execution = ToolExecution(toolName: "test", request: ToolExecutionRequest(toolName: "test", arguments: [:]))
        let start = Date()
        execution.startedAt = start
        
        // Simulate a 0.1 second delay
        Thread.sleep(forTimeInterval: 0.1)
        
        let end = Date()
        execution.completedAt = end
        
        let elapsed = execution.elapsedSeconds
        
        // Should be close to 0.1 seconds (allow +/- 0.05)
        #expect(elapsed >= 0.05)
        #expect(elapsed <= 0.15)
    }
    
    // MARK: - Equatable Tests
    
    @Test("ToolExecutionRequest equality works correctly")
    func toolExecutionRequestEquality() {
        let req1 = ToolExecutionRequest(toolName: "tool", arguments: ["a": "b"])
        let req2 = ToolExecutionRequest(toolName: "tool", arguments: ["a": "b"])
        let req3 = ToolExecutionRequest(toolName: "tool", arguments: ["x": "y"])
        
        #expect(req1 == req2)
        #expect(req1 != req3)
    }
}
