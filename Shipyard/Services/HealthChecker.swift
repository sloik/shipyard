import Foundation
import os
import UserNotifications

private let log = Logger(subsystem: "com.shipyard.app", category: "HealthChecker")

/// Monitors server health by checking if processes are still running
@Observable @MainActor final class HealthChecker {
    private var healthCheckTasks: [UUID: Task<Void, Never>] = [:]
    private let checkInterval: TimeInterval
    
    init(checkInterval: TimeInterval = 60) {
        self.checkInterval = checkInterval
        log.info("HealthChecker initialized with interval \(checkInterval)s")
        
        // Request notification permissions
        Task {
            do {
                _ = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
            } catch {
                log.warning("Failed to request notification permissions: \(error.localizedDescription)")
            }
        }
    }
    
    // MARK: - Health Checking
    
    /// Starts health checks for a server
    func startHealthChecks(for server: MCPServer, processManager: ProcessManager) {
        guard healthCheckTasks[server.id] == nil else {
            log.warning("Health checks already running for \(server.manifest.name)")
            return
        }
        
        log.info("Starting health checks for '\(server.manifest.name)'")
        
        let task = Task {
            while !Task.isCancelled {
                // Sleep first to allow process to stabilize
                do {
                    try await Task.sleep(for: .seconds(checkInterval))
                } catch {
                    break
                }
                
                if Task.isCancelled {
                    break
                }
                
                // Perform health check
                await checkHealth(for: server, processManager: processManager)
            }
        }
        
        healthCheckTasks[server.id] = task
    }
    
    /// Stops health checks for a server
    func stopHealthChecks(for server: MCPServer) {
        guard let task = healthCheckTasks.removeValue(forKey: server.id) else {
            return
        }
        
        log.info("Stopping health checks for '\(server.manifest.name)'")
        task.cancel()
    }
    
    /// Performs a single health check
    private func checkHealth(for server: MCPServer, processManager: ProcessManager) async {
        if server.isBuiltin {
            server.healthStatus = .healthy
            server.lastHealthCheck = Date()
            server.restartCount = 0
            return
        }

        // Get the process for this server from the processManager
        let isProcessRunning = processManager.isProcessRunning(server.id)
        
        let newStatus: HealthStatus
        
        if isProcessRunning && server.state == .running {
            newStatus = .healthy
            // Reset restart count on successful health check
            server.restartCount = 0
        } else if server.state == .running {
            // Process died unexpectedly
            newStatus = .unhealthy("Process is not running")
            
            log.warning("Health check failed for '\(server.manifest.name)': process not running")
            
            // Handle auto-restart
            if server.autoRestartEnabled {
                await handleAutoRestart(for: server, processManager: processManager)
            }
            
            // Send notification
            sendNotification(
                title: "Server Crashed",
                body: "'\(server.manifest.name)' process stopped unexpectedly"
            )
        } else {
            newStatus = .unknown
        }
        
        server.healthStatus = newStatus
        server.lastHealthCheck = Date()
    }
    
    /// Handles auto-restart logic
    private func handleAutoRestart(for server: MCPServer, processManager: ProcessManager) async {
        log.info("Auto-restart triggered for '\(server.manifest.name)'")
        
        let lastAttempt = server.lastRestartAttempt ?? Date(timeIntervalSince1970: 0)
        let timeSinceLastAttempt = Date().timeIntervalSince(lastAttempt)
        
        // Crash loop detection: if crashed within last 30 seconds, don't restart
        if timeSinceLastAttempt < 30 {
            log.warning("Crash loop detected for '\(server.manifest.name)' - skipping restart")
            server.healthStatus = .unhealthy("Crash loop detected - auto-restart disabled")
            
            sendNotification(
                title: "Crash Loop Detected",
                body: "'\(server.manifest.name)' is crashing repeatedly. Auto-restart disabled."
            )
            return
        }
        
        // Restart once
        server.lastRestartAttempt = Date()
        server.restartCount += 1
        
        log.info("Attempting restart #\(server.restartCount) for '\(server.manifest.name)'")
        
        do {
            try await processManager.restart(server)
            log.info("Auto-restart succeeded for '\(server.manifest.name)'")
            
            sendNotification(
                title: "Server Restarted",
                body: "'\(server.manifest.name)' was restarted automatically"
            )
        } catch {
            log.error("Auto-restart failed for '\(server.manifest.name)': \(error.localizedDescription)")
            server.healthStatus = .unhealthy("Auto-restart failed: \(error.localizedDescription)")
            
            sendNotification(
                title: "Restart Failed",
                body: "Failed to restart '\(server.manifest.name)'"
            )
        }
    }
    
    /// Sends a macOS notification
    private func sendNotification(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        
        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        )
        
        Task {
            do {
                try await UNUserNotificationCenter.current().add(request)
            } catch {
                log.warning("Failed to send notification: \(error.localizedDescription)")
            }
        }
    }
}
