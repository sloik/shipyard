import Foundation
import Security
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "KeychainManager")

/// Manages secret storage in macOS Keychain for MCP server environment variables.
///
/// Secrets are stored with service = "com.inwestomat.shipyard" and account = "<mcp-name>/<key-name>".
/// Example: service="com.inwestomat.shipyard", account="lmstudio/LM_STUDIO_TOKEN"
@MainActor final class KeychainManager {

    static let serviceName = "com.inwestomat.shipyard"

    // MARK: - Public API

    /// Saves a secret to Keychain. Updates if already exists.
    /// - Parameters:
    ///   - value: The secret string value
    ///   - serverName: MCP server name (e.g., "lmstudio")
    ///   - key: Environment variable name (e.g., "LM_STUDIO_TOKEN")
    func save(value: String, serverName: String, key: String) throws {
        let account = "\(serverName)/\(key)"
        guard let data = value.data(using: .utf8) else {
            throw KeychainError.encodingFailed
        }

        // Try to update first
        let updateQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.serviceName,
            kSecAttrAccount as String: account,
        ]
        let updateAttributes: [String: Any] = [
            kSecValueData as String: data,
        ]

        var status = SecItemUpdate(updateQuery as CFDictionary, updateAttributes as CFDictionary)

        if status == errSecItemNotFound {
            // Item doesn't exist yet, add it
            var addQuery = updateQuery
            addQuery[kSecValueData as String] = data
            status = SecItemAdd(addQuery as CFDictionary, nil)
        }

        guard status == errSecSuccess else {
            let message = SecCopyErrorMessageString(status, nil) as String? ?? "Unknown error"
            log.error("Keychain save failed for \(account): \(message)")
            throw KeychainError.saveFailed(status, message)
        }

        log.info("Saved secret: \(account)")
    }

    /// Retrieves a secret from Keychain.
    /// - Returns: The secret string, or nil if not found.
    func load(serverName: String, key: String) -> String? {
        let account = "\(serverName)/\(key)"

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.serviceName,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8) else {
            if status != errSecItemNotFound {
                log.warning("Keychain load failed for \(account): status \(status)")
            }
            return nil
        }

        return value
    }

    /// Deletes a secret from Keychain.
    func delete(serverName: String, key: String) throws {
        let account = "\(serverName)/\(key)"

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.serviceName,
            kSecAttrAccount as String: account,
        ]

        let status = SecItemDelete(query as CFDictionary)

        guard status == errSecSuccess || status == errSecItemNotFound else {
            let message = SecCopyErrorMessageString(status, nil) as String? ?? "Unknown error"
            throw KeychainError.deleteFailed(status, message)
        }

        log.info("Deleted secret: \(account)")
    }

    /// Lists all stored secrets for a given MCP server (returns key names, not values).
    func listKeys(serverName: String) -> [String] {
        let prefix = "\(serverName)/"

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.serviceName,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitAll,
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let items = result as? [[String: Any]] else {
            return []
        }

        return items.compactMap { item in
            guard let account = item[kSecAttrAccount as String] as? String,
                  account.hasPrefix(prefix) else { return nil }
            return String(account.dropFirst(prefix.count))
        }
    }

    /// Resolves all secret keys from manifest into a dictionary of key → value.
    /// Keys not found in Keychain are omitted (with a warning).
    func resolveSecrets(for manifest: MCPManifest) -> [String: String] {
        guard let secretKeys = manifest.env_secret_keys, !secretKeys.isEmpty else {
            return [:]
        }

        var resolved: [String: String] = [:]
        for key in secretKeys {
            if let value = load(serverName: manifest.name, key: key) {
                resolved[key] = value
            } else {
                log.warning("Secret '\(key)' not found in Keychain for '\(manifest.name)'")
            }
        }
        return resolved
    }

    /// Checks if all required secrets for a manifest are present in Keychain.
    func hasAllSecrets(for manifest: MCPManifest) -> Bool {
        guard let secretKeys = manifest.env_secret_keys, !secretKeys.isEmpty else {
            return true  // no secrets needed
        }
        return secretKeys.allSatisfy { load(serverName: manifest.name, key: $0) != nil }
    }
}

// MARK: - Error Types

enum KeychainError: LocalizedError, Sendable {
    case encodingFailed
    case saveFailed(OSStatus, String)
    case deleteFailed(OSStatus, String)

    var errorDescription: String? {
        switch self {
        case .encodingFailed:
            return L10n.string("error.keychain.encodingFailed")
        case .saveFailed(let status, let message):
            return L10n.format("error.keychain.saveFailed", Int64(status), message)
        case .deleteFailed(let status, let message):
            return L10n.format("error.keychain.deleteFailed", Int64(status), message)
        }
    }
}
