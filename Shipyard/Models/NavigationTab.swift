import SwiftUI

/// Navigation tabs for the main window
enum NavigationTab: String, CaseIterable, Identifiable {
    case servers
    case gateway
    case logs
    case config
    case secrets
    case instructions
    case about

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .servers: return "servers.tab.title"
        case .gateway: return "gateway.tab.title"
        case .logs: return "logs.tab.title"
        case .config: return "config.tab.title"
        case .secrets: return "secrets.tab.title"
        case .instructions: return "instructions.tab.title"
        case .about: return "about.tab.title"
        }
    }

    var icon: String {
        switch self {
        case .servers: return "server.rack"
        case .gateway: return "link.circle"
        case .logs: return "list.bullet.rectangle"
        case .config: return "doc.text"
        case .secrets: return "key"
        case .instructions: return "questionmark.circle"
        case .about: return "info.circle"
        }
    }

    var shortcutKey: KeyEquivalent {
        switch self {
        case .servers: return "1"
        case .gateway: return "2"
        case .logs: return "3"
        case .config: return "4"
        case .secrets: return "5"
        case .instructions: return "6"
        case .about: return "7"
        }
    }
}
