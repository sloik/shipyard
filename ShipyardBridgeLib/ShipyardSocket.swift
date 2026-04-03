import Foundation
import Darwin

// MARK: - Shipyard Socket Protocol

public protocol ShipyardSocketProtocol: Sendable {
    func send(method: String, params: [String: Any]?, timeout: TimeInterval) -> [String: Any]?
}

// MARK: - Shipyard Socket Client

public final class ShipyardSocket: ShipyardSocketProtocol, @unchecked Sendable {
    public static let shared = ShipyardSocket()

    private init() {}

    public func send(method: String, params: [String: Any]? = nil, timeout: TimeInterval = DEFAULT_TIMEOUT) -> [String: Any]? {
        let startTime = CFAbsoluteTimeGetCurrent()

        let socketFD = socket(AF_UNIX, SOCK_STREAM, 0)
        guard socketFD >= 0 else {
            return nil
        }

        defer { close(socketFD) }

        // SOCKET_PATH already uses NSHomeDirectory(), no tilde expansion needed
        let expandedPath = SOCKET_PATH

        // Connect
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = expandedPath.utf8CString
        guard pathBytes.count <= MemoryLayout.size(ofValue: addr.sun_path) else {
            return nil
        }

        pathBytes.withUnsafeBufferPointer { srcBuffer in
            withUnsafeMutableBytes(of: &addr.sun_path) { dstBuffer in
                dstBuffer.copyMemory(from: UnsafeRawBufferPointer(srcBuffer))
            }
        }

        var addrCopy = addr
        let addrLen = MemoryLayout<sockaddr_un>.size

        let connectResult = withUnsafePointer(to: &addrCopy) { ptr in
            connect(
                socketFD,
                UnsafeRawPointer(ptr).assumingMemoryBound(to: sockaddr.self),
                socklen_t(addrLen)
            )
        }

        guard connectResult == 0 else {
            return nil
        }

        // Set timeout
        var tv = timeval()
        tv.tv_sec = Int(timeout)
        tv.tv_usec = __darwin_suseconds_t((timeout.truncatingRemainder(dividingBy: 1)) * 1_000_000)
        setsockopt(socketFD, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))

        // Prepare request
        var requestDict: [String: Any] = ["method": method]
        if let params = params {
            requestDict["params"] = params
        }

        guard let requestData = try? JSONSerialization.data(withJSONObject: requestDict),
              var requestStr = String(data: requestData, encoding: .utf8) else {
            return nil
        }
        requestStr += "\n"

        // Send request
        guard let sendData = requestStr.data(using: .utf8) else {
            return nil
        }

        let written = sendData.withUnsafeBytes { buffer in
            Darwin.write(socketFD, buffer.baseAddress!, buffer.count)
        }

        guard written > 0 else {
            bridgeLog.log(.error, cat: "socket", msg: "write failed for \(method)")
            return nil
        }

        bridgeLog.log(.info, cat: "socket", msg: "sent \(written)B for \(method)", meta: ["method": method, "bytes": written])

        // Read response (loop to handle large/chunked responses)
        var responseData = Data()
        let bufferSize = 65536
        var buffer = [UInt8](repeating: 0, count: bufferSize)

        while true {
            let bytesRead = Darwin.read(socketFD, &buffer, bufferSize)
            let totalSoFar = responseData.count + max(0, bytesRead)
            bridgeLog.log(.debug, cat: "socket", msg: "read=\(bytesRead) total=\(totalSoFar)", meta: ["method": method, "bytes_read": bytesRead, "total": totalSoFar])
            if bytesRead <= 0 { break }
            responseData.append(contentsOf: buffer.prefix(bytesRead))
            if responseData.last == UInt8(ascii: "\n") {
                break
            }
        }

        guard !responseData.isEmpty else {
            bridgeLog.log(.error, cat: "socket", msg: "empty response for \(method)")
            return nil
        }

        let durationMs = Int((CFAbsoluteTimeGetCurrent() - startTime) * 1000)
        bridgeLog.log(.info, cat: "socket", msg: "total \(responseData.count)B for \(method)", meta: ["method": method, "bytes": responseData.count, "duration_ms": durationMs])

        guard let json = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any] else {
            let trimmedStr = String(data: responseData, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let preview = trimmedStr?.prefix(200) ?? ""
            bridgeLog.log(.error, cat: "socket", msg: "JSON parse failed for \(method)", meta: ["method": method, "response_preview": String(preview)])
            guard let trimmedStr = trimmedStr,
                  let trimmedData = trimmedStr.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: trimmedData) as? [String: Any] else {
                return nil
            }
            return json
        }

        return json
    }
}

// MARK: - Injectable Socket Variable

/// The active socket client. Defaults to ShipyardSocket.shared.
/// Override in tests with a mock.
public nonisolated(unsafe) var shipyardSocket: any ShipyardSocketProtocol = ShipyardSocket.shared

// MARK: - Protocol Extension for Default Parameters

public extension ShipyardSocketProtocol {
    func send(method: String, params: [String: Any]? = nil) -> [String: Any]? {
        send(method: method, params: params, timeout: DEFAULT_TIMEOUT)
    }
}
