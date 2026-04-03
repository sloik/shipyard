import Testing
import Foundation
@testable import Shipyard

@Suite("SocketServer — Response formatting", .timeLimit(.minutes(1)))
struct SocketServerResponseTests {

    @Test("errorResponse produces valid JSON")
    @available(macOS 14.0, *)
    @MainActor
    func errorResponseValid() throws {
        let server = SocketServer()
        let response = server.errorResponse("test error")
        let data = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        #expect(json["error"] as? String == "test error")
    }

    @Test("successResponse with dict produces valid JSON")
    @available(macOS 14.0, *)
    @MainActor
    func successResponseDict() throws {
        let server = SocketServer()
        let response = server.successResponse(["ok": true])
        let data = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let result = try #require(json["result"] as? [String: Any])
        #expect(result["ok"] as? Bool == true)
    }

    @Test("successResponse with empty array produces valid JSON")
    @available(macOS 14.0, *)
    @MainActor
    func successResponseEmptyArray() throws {
        let server = SocketServer()
        let response = server.successResponse([String]())
        let data = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        let result = try #require(json["result"] as? [Any])
        #expect(result.isEmpty)
    }

    @Test("levelValue returns correct ordering")
    @available(macOS 14.0, *)
    @MainActor
    func levelValues() {
        let server = SocketServer()
        #expect(server.levelValue(.debug) == 0)
        #expect(server.levelValue(.info) == 1)
        #expect(server.levelValue(.warning) == 2)
        #expect(server.levelValue(.error) == 3)
    }
}

// MARK: - log_event Dispatch Tests

@Suite("SocketServer — log_event handler", .timeLimit(.minutes(1)))
struct SocketServerLogEventTests {

    @Test("log_event returns success for valid entry")
    @available(macOS 14.0, *)
    @MainActor
    func logEventValidEntry() async throws {
        let server = SocketServer()
        let request: [String: Any] = [
            "method": "log_event",
            "params": [
                "ts": "2026-03-12T14:30:05.123Z",
                "level": "info",
                "cat": "socket",
                "src": "bridge",
                "msg": "test log forwarding"
            ] as [String: Any]
        ]
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let requestStr = try #require(String(data: requestData, encoding: .utf8))

        let response = await server.dispatchRequest(requestStr)
        let responseData = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: responseData) as? [String: Any])
        let result = try #require(json["result"] as? [String: Any])
        #expect(result["ok"] as? Bool == true)
    }

    @Test("log_event returns error for missing fields")
    @available(macOS 14.0, *)
    @MainActor
    func logEventMissingFields() async throws {
        let server = SocketServer()
        let request: [String: Any] = [
            "method": "log_event",
            "params": [
                "ts": "2026-03-12T14:30:05.123Z",
                "level": "info"
                // missing cat, src, msg
            ] as [String: Any]
        ]
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let requestStr = try #require(String(data: requestData, encoding: .utf8))

        let response = await server.dispatchRequest(requestStr)
        let responseData = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: responseData) as? [String: Any])
        #expect(json["error"] != nil, "Should return error for missing fields")
    }

    @Test("log_event handles meta dictionary")
    @available(macOS 14.0, *)
    @MainActor
    func logEventWithMeta() async throws {
        let server = SocketServer()
        let request: [String: Any] = [
            "method": "log_event",
            "params": [
                "ts": "2026-03-12T14:30:05.123Z",
                "level": "info",
                "cat": "gateway",
                "src": "bridge",
                "msg": "gateway call",
                "meta": ["method": "gateway_call", "bytes": 245, "duration_ms": 12] as [String: Any]
            ] as [String: Any]
        ]
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let requestStr = try #require(String(data: requestData, encoding: .utf8))

        let response = await server.dispatchRequest(requestStr)
        let responseData = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: responseData) as? [String: Any])
        let result = try #require(json["result"] as? [String: Any])
        #expect(result["ok"] as? Bool == true)
    }
}

@Suite("SocketServer — Shipyard self exposure", .timeLimit(.minutes(1)))
struct SocketServerShipyardExposureTests {

    @Test("shipyard_tools returns expected tool catalog")
    @available(macOS 14.0, *)
    @MainActor
    func shipyardToolsCatalog() async throws {
        let server = SocketServer()
        let request: [String: Any] = ["method": "shipyard_tools"]
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let requestStr = try #require(String(data: requestData, encoding: .utf8))

        let response = await server.dispatchRequest(requestStr)
        let responseData = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: responseData) as? [String: Any])
        let result = try #require(json["result"] as? [String: Any])
        let tools = try #require(result["tools"] as? [[String: Any]])
        let names = Set(tools.compactMap { $0["name"] as? String })
        #expect(tools.allSatisfy { $0["inputSchema"] != nil })

        #expect(names.contains("shipyard_status"))
        #expect(names.contains("shipyard_health"))
        #expect(names.contains("shipyard_logs"))
        #expect(names.contains("shipyard_restart"))
        #expect(names.contains("shipyard_gateway_discover"))
        #expect(names.contains("shipyard_gateway_call"))
        #expect(names.contains("shipyard_gateway_set_enabled"))
    }

    @Test("gateway_set_enabled rejects shipyard MCP-level disable")
    @available(macOS 14.0, *)
    @MainActor
    func rejectsShipyardMCPDisable() async throws {
        let server = SocketServer()
        let registry = MCPRegistry()
        let processManager = ProcessManager()
        let gatewayRegistry = GatewayRegistry()

        await server.start(registry: registry, processManager: processManager, gatewayRegistry: gatewayRegistry)

        let request: [String: Any] = [
            "method": "gateway_set_enabled",
            "params": ["mcp": "shipyard", "enabled": false]
        ]
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let requestStr = try #require(String(data: requestData, encoding: .utf8))
        let response = await server.dispatchRequest(requestStr)
        let responseData = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: responseData) as? [String: Any])
        let error = try #require(json["error"] as? String)
        #expect(error.contains("cannot be disabled"))
        await server.stop()
    }

    @Test("gateway_call returns tool_unavailable for disabled shipyard tool")
    @available(macOS 14.0, *)
    @MainActor
    func disabledShipyardToolReturnsUnavailable() async throws {
        let server = SocketServer()
        let registry = MCPRegistry()
        let processManager = ProcessManager()
        let gatewayRegistry = GatewayRegistry()

        await server.start(registry: registry, processManager: processManager, gatewayRegistry: gatewayRegistry)
        gatewayRegistry.updateTools(
            mcpName: GatewayRegistry.shipyardMCPName,
            rawTools: [["name": "shipyard_status", "description": "status", "input_schema": [:]]]
        )
        gatewayRegistry.setToolEnabled("shipyard__shipyard_status", enabled: false)

        let request: [String: Any] = [
            "method": "gateway_call",
            "params": ["tool": "shipyard__shipyard_status", "arguments": [:]]
        ]
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let requestStr = try #require(String(data: requestData, encoding: .utf8))
        let response = await server.dispatchRequest(requestStr)
        let responseData = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: responseData) as? [String: Any])
        let error = try #require(json["error"] as? String)
        #expect(error.contains("tool_unavailable"))
        await server.stop()
    }

    @Test("status reports builtin shipyard as healthy with dependencies_ok true")
    @available(macOS 14.0, *)
    @MainActor
    func statusForBuiltinShipyardIsHealthy() async throws {
        let server = SocketServer()
        let registry = MCPRegistry()
        registry.ensureSyntheticShipyardServerRegistered()
        let processManager = ProcessManager()
        let gatewayRegistry = GatewayRegistry()

        await server.start(registry: registry, processManager: processManager, gatewayRegistry: gatewayRegistry)

        let request: [String: Any] = ["method": "status"]
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let requestStr = try #require(String(data: requestData, encoding: .utf8))
        let response = await server.dispatchRequest(requestStr)
        let responseData = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: responseData) as? [String: Any])
        let result = try #require(json["result"] as? [[String: Any]])
        let shipyard = try #require(result.first { ($0["name"] as? String) == GatewayRegistry.shipyardMCPName })

        #expect(shipyard["version"] as? String == "builtin")
        #expect(shipyard["state"] as? String == "running")
        #expect(shipyard["health"] as? String == "healthy")
        #expect(shipyard["dependencies_ok"] as? Bool == true)

        await server.stop()
    }

    @Test("health endpoint reports builtin shipyard as healthy without subprocess")
    @available(macOS 14.0, *)
    @MainActor
    func healthForBuiltinShipyardIsHealthy() async throws {
        let server = SocketServer()
        let registry = MCPRegistry()
        registry.ensureSyntheticShipyardServerRegistered()
        let processManager = ProcessManager()
        let gatewayRegistry = GatewayRegistry()

        await server.start(registry: registry, processManager: processManager, gatewayRegistry: gatewayRegistry)

        let request: [String: Any] = ["method": "health"]
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let requestStr = try #require(String(data: requestData, encoding: .utf8))
        let response = await server.dispatchRequest(requestStr)
        let responseData = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: responseData) as? [String: Any])
        let result = try #require(json["result"] as? [[String: Any]])
        let shipyard = try #require(result.first { ($0["name"] as? String) == GatewayRegistry.shipyardMCPName })

        #expect(shipyard["healthy"] as? Bool == true)
        #expect(shipyard["message"] == nil)

        await server.stop()
    }

    @Test("restart method handles builtin Shipyard by restarting socket listener")
    @available(macOS 14.0, *)
    @MainActor
    func restartBuiltinShipyardViaRPC() async throws {
        let server = SocketServer()
        let registry = MCPRegistry()
        registry.ensureSyntheticShipyardServerRegistered()
        let processManager = ProcessManager()
        let gatewayRegistry = GatewayRegistry()

        await server.start(registry: registry, processManager: processManager, gatewayRegistry: gatewayRegistry)

        let request: [String: Any] = [
            "method": "restart",
            "params": ["name": GatewayRegistry.shipyardMCPName]
        ]
        let requestData = try JSONSerialization.data(withJSONObject: request)
        let requestStr = try #require(String(data: requestData, encoding: .utf8))
        let response = await server.dispatchRequest(requestStr)
        let responseData = try #require(response.data(using: .utf8))
        let json = try #require(try JSONSerialization.jsonObject(with: responseData) as? [String: Any])
        let result = try #require(json["result"] as? [String: Any])
        #expect(result["ok"] as? Bool == true)

        await server.stop()
    }
}

@Suite("SocketServer — listener restart", .serialized, .timeLimit(.minutes(1)))
struct SocketServerListenerRestartTests {
    @Test("restartSocketListener rebinds socket and accepts new connections")
    @available(macOS 14.0, *)
    @MainActor
    func restartRebindsAndAcceptsConnections() async throws {
        let server = SocketServer()
        let registry = MCPRegistry()
        registry.ensureSyntheticShipyardServerRegistered()
        let processManager = ProcessManager()
        let gatewayRegistry = GatewayRegistry()

        await server.start(registry: registry, processManager: processManager, gatewayRegistry: gatewayRegistry)
        defer { Task { await server.stop() } }

        #expect(FileManager.default.fileExists(atPath: shipyardSocketPath()))

        let beforeRequest: [String: Any] = ["method": "status"]
        let beforeRequestData = try JSONSerialization.data(withJSONObject: beforeRequest)
        let beforeRequestStr = try #require(String(data: beforeRequestData, encoding: .utf8))
        let beforeResponse = await server.dispatchRequest(beforeRequestStr)
        let beforeData = try #require(beforeResponse.data(using: .utf8))
        let beforeJSON = try #require(try JSONSerialization.jsonObject(with: beforeData) as? [String: Any])
        #expect(beforeJSON["result"] != nil)

        try await server.restartSocketListener()

        #expect(FileManager.default.fileExists(atPath: shipyardSocketPath()))

        let afterRequest: [String: Any] = ["method": "status"]
        let afterRequestData = try JSONSerialization.data(withJSONObject: afterRequest)
        let afterRequestStr = try #require(String(data: afterRequestData, encoding: .utf8))
        let afterResponse = await server.dispatchRequest(afterRequestStr)
        let afterData = try #require(afterResponse.data(using: .utf8))
        let afterJSON = try #require(try JSONSerialization.jsonObject(with: afterData) as? [String: Any])
        #expect(afterJSON["result"] != nil)
    }

    @Test("connections open during restart are closed")
    @available(macOS 14.0, *)
    @MainActor
    func inFlightConnectionsClosedOnRestart() async throws {
        let server = SocketServer()
        let registry = MCPRegistry()
        registry.ensureSyntheticShipyardServerRegistered()
        let processManager = ProcessManager()
        let gatewayRegistry = GatewayRegistry()

        await server.start(registry: registry, processManager: processManager, gatewayRegistry: gatewayRegistry)
        defer { Task { await server.stop() } }

        let fd = try openClientSocket()
        defer { Darwin.close(fd) }

        try await server.restartSocketListener()

        var timeout = timeval(tv_sec: 0, tv_usec: 250_000)
        _ = withUnsafePointer(to: &timeout) { ptr in
            setsockopt(
                fd,
                SOL_SOCKET,
                SO_RCVTIMEO,
                UnsafeRawPointer(ptr),
                socklen_t(MemoryLayout<timeval>.size)
            )
        }

        let requestLine = #"{"method":"status"}\n"#
        let bytes = [UInt8](requestLine.utf8)
        let writeResult = bytes.withUnsafeBufferPointer {
            Darwin.write(fd, $0.baseAddress!, $0.count)
        }

        var buffer = [UInt8](repeating: 0, count: 1024)
        let readResult = Darwin.read(fd, &buffer, buffer.count)

        #expect(writeResult < 0 || readResult <= 0)
    }
}

private func shipyardSocketPath() -> String {
    PathManager.shared.socketFile.path
}

private func openClientSocket() throws -> Int32 {
    let socketPath = shipyardSocketPath()
    for _ in 0..<20 {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else {
            throw NSError(domain: "SocketServerTests", code: Int(errno))
        }

        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = socketPath.utf8CString
        pathBytes.withUnsafeBufferPointer { srcBuffer in
            withUnsafeMutableBytes(of: &addr.sun_path) { dstBuffer in
                dstBuffer.copyMemory(from: UnsafeRawBufferPointer(srcBuffer))
            }
        }

        var addrCopy = addr
        let connectResult = withUnsafePointer(to: &addrCopy) { ptr in
            connect(fd, UnsafeRawPointer(ptr).assumingMemoryBound(to: sockaddr.self), socklen_t(MemoryLayout<sockaddr_un>.size))
        }
        if connectResult == 0 {
            return fd
        }

        let err = errno
        Darwin.close(fd)
        if err != ENOENT && err != ECONNREFUSED && err != EAGAIN {
            throw NSError(domain: "SocketServerTests", code: Int(err))
        }
        usleep(50_000)
    }

    throw NSError(domain: "SocketServerTests", code: Int(errno))
}

private func sendSocketRequest(method: String, params: [String: Any]) throws -> [String: Any] {
    let fd = try openClientSocket()
    defer { Darwin.close(fd) }

    var timeout = timeval(tv_sec: 0, tv_usec: 300_000)
    _ = withUnsafePointer(to: &timeout) { ptr in
        setsockopt(
            fd,
            SOL_SOCKET,
            SO_RCVTIMEO,
            UnsafeRawPointer(ptr),
            socklen_t(MemoryLayout<timeval>.size)
        )
    }

    let request: [String: Any] = ["method": method, "params": params]
    let requestData = try JSONSerialization.data(withJSONObject: request)
    var requestLine = requestData
    requestLine.append(0x0A)

    _ = requestLine.withUnsafeBytes { bytes in
        Darwin.write(fd, bytes.baseAddress!, bytes.count)
    }

    var buffer = [UInt8](repeating: 0, count: 4096)
    let bytesRead = Darwin.read(fd, &buffer, buffer.count)
    guard bytesRead > 0 else {
        throw NSError(domain: "SocketServerTests", code: Int(errno))
    }
    let payload = Data(buffer.prefix(bytesRead))
    let trimmed = String(data: payload, encoding: .utf8)?
        .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    guard let responseData = trimmed.data(using: .utf8) else {
        throw NSError(domain: "SocketServerTests", code: -2)
    }
    guard let json = try JSONSerialization.jsonObject(with: responseData) as? [String: Any] else {
        throw NSError(domain: "SocketServerTests", code: -3)
    }
    return json
}
