import Foundation
import Testing
@testable import Shipyard

/// Test suite for HTTPBridge
@Suite("HTTPBridge Tests")
struct HTTPBridgeTests {
    
    /// Mock URLProtocol for testing HTTP requests
    final class MockHTTPProtocol: URLProtocol, Sendable {
        static var mockResponses: [String: (statusCode: Int, body: [String: Any])] = [:]
        static var lastRequest: URLRequest?
        static var requestCount: Int = 0
        
        override class func canInit(with request: URLRequest) -> Bool {
            return true
        }
        
        override class func canonicalRequest(for request: URLRequest) -> URLRequest {
            return request
        }
        
        override func startLoading() {
            Self.lastRequest = request
            Self.requestCount += 1
            
            let url = request.url?.absoluteString ?? "unknown"
            let mock = Self.mockResponses[url] ?? (statusCode: 200, body: [:])
            
            guard let jsonData = try? JSONSerialization.data(withJSONObject: mock.body) else {
                let error = NSError(domain: "MockHTTPProtocol", code: -1, userInfo: nil)
                client?.urlProtocol(self, didFailWithError: error)
                return
            }
            
            if let response = HTTPURLResponse(
                url: request.url ?? URL(fileURLWithPath: "/"),
                statusCode: mock.statusCode,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            ) {
                client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
                client?.urlProtocol(self, didLoad: jsonData)
                client?.urlProtocolDidFinishLoading(self)
            }
        }
        
        override func stopLoading() {}
    }
    
    @Test("HTTPBridge initialization creates instance")
    func testInitialization() {
        let url = URL(string: "http://localhost:8000/mcp")!
        let bridge = HTTPBridge(
            mcpName: "testMCP",
            endpointURL: url,
            customHeaders: ["Authorization": "Bearer token123"]
        )
        
        #expect(bridge.mcpName == "testMCP")
        #expect(bridge.endpointURL == url)
        #expect(bridge.customHeaders["Authorization"] == "Bearer token123")
    }
    
    @Test("HTTPBridge timeout property set correctly")
    func testTimeoutConfiguration() {
        let url = URL(string: "http://localhost:8000/mcp")!
        let bridge = HTTPBridge(
            mcpName: "testMCP",
            endpointURL: url,
            timeout: 45
        )
        
        #expect(bridge.timeout == 45)
    }
    
    @Test("BridgeError classification for transient HTTP errors")
    func testTransientHTTPErrorRetry() {
        // 503 Service Unavailable is transient
        let error = BridgeError.httpError("testMCP", 503, "Service Unavailable")
        #expect(error.isTransient == true)
    }
    
    @Test("BridgeError classification for permanent HTTP errors")
    func testPermanentHTTPError() {
        // 401 Unauthorized is permanent
        let error = BridgeError.httpError("testMCP", 401, "Unauthorized")
        #expect(error.isTransient == false)
    }
    
    @Test("BridgeError for session expired")
    func testSessionExpiredError() {
        let error = BridgeError.sessionExpired("testMCP")
        #expect(error.isTransient == true)
        #expect(error.errorDescription?.contains("re-initialization") == true)
    }
    
    @Test("BridgeError for connection failed")
    func testConnectionFailedError() {
        let error = BridgeError.connectionFailed("testMCP", "Network unreachable")
        #expect(error.isTransient == true)
        #expect(error.errorDescription?.contains("testMCP") == true)
        #expect(error.errorDescription?.contains("Network unreachable") == true)
    }
}
