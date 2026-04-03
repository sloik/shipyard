import Foundation

// MARK: - Management Tool Handlers

public func handleShipyardStatus() -> String {
    guard let response = shipyardSocket.send(method: "status") else {
        return formatErrorText("Failed to connect to Shipyard")
    }

    if let error = response["error"] as? String {
        return formatErrorText(error)
    }

    guard let result = response["result"] as? [[String: Any]] else {
        return formatErrorText("Invalid response format")
    }

    var output = ""
    for server in result {
        let name = server["name"] as? String ?? "unknown"
        let version = server["version"] as? String ?? "unknown"
        let state = server["state"] as? String ?? "unknown"
        let health = server["health"] as? String ?? "unknown"
        let pid = server["pid"] as? Int
        let cpu = server["cpu_percent"] as? Double
        let mem = server["memory_mb"] as? Double
        let lastCheck = server["last_health_check"] as? String
        let autoRestart = server["auto_restart"] as? Bool ?? false
        let depsOk = server["dependencies_ok"] as? Bool ?? false

        output += "=== \(name) (v\(version)) ===\n"
        output += "State: \(state)"
        if let pid = pid {
            output += " (PID \(pid))"
        }
        output += "\n"

        if let cpu = cpu, let mem = mem {
            output += "CPU: \(String(format: "%.1f", cpu))% | Memory: \(String(format: "%.0f", mem)) MB\n"
        }

        output += "Health: \(health)"
        if let lastCheck = lastCheck {
            output += " (last check: \(lastCheck))"
        }
        output += "\n"

        output += "Auto-restart: \(autoRestart ? "on" : "off")\n"
        output += "Dependencies: \(depsOk ? "ok" : "issues detected")\n\n"

    }

    return output.trimmingCharacters(in: .whitespacesAndNewlines)
}

public func handleShipyardHealth() -> String {
    guard let response = shipyardSocket.send(method: "health") else {
        return formatErrorText("Failed to connect to Shipyard")
    }

    if let error = response["error"] as? String {
        return formatErrorText(error)
    }

    guard let result = response["result"] as? [[String: Any]] else {
        return formatErrorText("Invalid response format")
    }

    var output = "Health Status:\n\n"
    for server in result {
        let name = server["name"] as? String ?? "unknown"
        let healthy = server["healthy"] as? Bool ?? false
        let message = server["message"] as? String ?? "ok"

        output += "• \(name): \(healthy ? "✓ healthy" : "✗ unhealthy")"
        if !healthy {
            output += " - \(message)"
        }
        output += "\n"
    }

    return output.trimmingCharacters(in: .whitespacesAndNewlines)
}

public func handleShipyardLogs(mcpName: String, lines: Int = 50, level: String? = nil) -> String {
    var params: [String: Any] = [
        "name": mcpName,
        "lines": lines
    ]
    if let level = level {
        params["level"] = level
    }

    guard let response = shipyardSocket.send(method: "logs", params: params) else {
        return formatErrorText("Failed to connect to Shipyard")
    }

    if let error = response["error"] as? String {
        return formatErrorText(error)
    }

    guard let result = response["result"] as? [[String: Any]] else {
        return formatErrorText("Invalid response format")
    }

    var output = "Logs for \(mcpName):\n\n"
    for entry in result {
        let timestamp = entry["timestamp"] as? String ?? ""
        let level = entry["level"] as? String ?? "INFO"
        let message = entry["message"] as? String ?? ""

        output += "[\(timestamp)] \(level): \(message)\n"
    }

    return output.trimmingCharacters(in: .whitespacesAndNewlines)
}

public func handleShipyardRestart(mcpName: String) -> String {
    guard let response = shipyardSocket.send(method: "restart", params: ["name": mcpName]) else {
        return formatErrorText("Failed to connect to Shipyard")
    }

    if let error = response["error"] as? String {
        return formatErrorText(error)
    }

    return "Restart request sent for \(mcpName)"
}

public func handleShipyardGatewayDiscover(timeout: TimeInterval = DEFAULT_TIMEOUT) -> ([String: Any]?, String?) {
    guard let response = shipyardSocket.send(method: "gateway_discover", params: nil, timeout: timeout) else {
        return (nil, "Failed to connect to Shipyard")
    }

    if let error = response["error"] as? String {
        return (nil, error)
    }

    guard let result = response["result"] as? [String: Any] else {
        return (nil, "Invalid response format")
    }

    return (result, nil)
}

public func handleShipyardGatewayCatalog(timeout: TimeInterval = DEFAULT_TIMEOUT) -> ([String: Any]?, String?) {
    guard let response = shipyardSocket.send(method: "gateway_catalog", params: nil, timeout: timeout) else {
        return (nil, "Failed to connect to Shipyard")
    }

    if let error = response["error"] as? String {
        return (nil, error)
    }

    guard let result = response["result"] as? [String: Any] else {
        return (nil, "Invalid response format")
    }

    return (result, nil)
}

public func handleShipyardGatewayCall(toolName: String, arguments: [String: Any]) -> (String?, String?) {
    let params: [String: Any] = ["tool": toolName, "arguments": arguments]

    guard let response = shipyardSocket.send(method: "gateway_call", params: params, timeout: EXTENDED_TIMEOUT) else {
        return (nil, "Failed to connect to Shipyard")
    }

    // Handle both string and dict error formats
    if let errorStr = response["error"] as? String {
        return (nil, errorStr)
    } else if let errorDict = response["error"] as? [String: Any],
              let errorMsg = errorDict["message"] as? String {
        return (nil, errorMsg)
    }

    guard let result = response["result"] else {
        return (nil, "Invalid response format")
    }

    // Serialize result back to JSON for returning to Claude
    // Handle dict, array, string, number, bool, or null
    if let jsonData = try? JSONSerialization.data(withJSONObject: result, options: .fragmentsAllowed),
       let jsonStr = String(data: jsonData, encoding: .utf8) {
        return (jsonStr, nil)
    }

    return (nil, "Failed to serialize result")
}

public func formatGatewayDiscoverResult(_ data: [String: Any]?) -> String {
    guard let data = data,
          let tools = data["tools"] as? [[String: Any]] else {
        return "No gateway tools available."
    }

    // Group by MCP
    var grouped: [String: [[String: Any]]] = [:]
    for tool in tools {
        let mcp = tool["mcp"] as? String ?? "unknown"
        grouped[mcp, default: []].append(tool)
    }

    var lines: [String] = ["Gateway Tools Catalog:", ""]
    for (mcpName, mcpTools) in grouped.sorted(by: { $0.key < $1.key }) {
        lines.append("[\(mcpName)]")
        for tool in mcpTools {
            let name = tool["name"] as? String ?? "unknown"
            let desc = tool["description"] as? String ?? "no description"
            let enabled = tool["enabled"] as? Bool ?? false
            lines.append("  • \(name)")
            lines.append("    \(desc)")
            lines.append("    [\(enabled ? "enabled" : "disabled")]")
        }
        lines.append("")
    }
    return lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
}

public func handleShipyardGatewaySetEnabled(mcpName: String? = nil, toolName: String? = nil, enabled: Bool = true) -> String {
    var params: [String: Any] = ["enabled": enabled]
    if let mcpName = mcpName {
        params["mcp"] = mcpName
    }
    if let toolName = toolName {
        params["tool"] = toolName
    }

    guard let response = shipyardSocket.send(method: "gateway_set_enabled", params: params) else {
        return formatErrorText("Failed to connect to Shipyard")
    }

    if let error = response["error"] as? String {
        return formatErrorText(error)
    }

    let target = mcpName ?? toolName ?? "unknown"
    return "\(target) is now \(enabled ? "enabled" : "disabled")"
}
