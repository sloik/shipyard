import Foundation

struct StartupPhaseTiming: Codable, Sendable {
    let label: String
    let startMs: Double
    let endMs: Double
    let durationMs: Double

    var stableID: String {
        "\(label)-\(startMs)-\(endMs)"
    }

    enum CodingKeys: String, CodingKey {
        case label
        case startMs = "start_ms"
        case endMs = "end_ms"
        case durationMs = "duration_ms"
    }

    init(label: String, startMs: Double, endMs: Double, durationMs: Double) {
        self.label = label
        self.startMs = startMs
        self.endMs = endMs
        self.durationMs = durationMs
    }
}

struct StartupServerTiming: Codable, Sendable {
    let name: String
    let spawnMs: Double
    let handshakeMs: Double
    let toolsDiscovered: Int
    let toolsDiscoveryMs: Double
    let totalMs: Double

    enum CodingKeys: String, CodingKey {
        case name
        case spawnMs = "spawn_ms"
        case handshakeMs = "handshake_ms"
        case toolsDiscovered = "tools_discovered"
        case toolsDiscoveryMs = "tools_discovery_ms"
        case totalMs = "total_ms"
    }

    init(
        name: String,
        spawnMs: Double,
        handshakeMs: Double,
        toolsDiscovered: Int,
        toolsDiscoveryMs: Double,
        totalMs: Double
    ) {
        self.name = name
        self.spawnMs = spawnMs
        self.handshakeMs = handshakeMs
        self.toolsDiscovered = toolsDiscovered
        self.toolsDiscoveryMs = toolsDiscoveryMs
        self.totalMs = totalMs
    }
}

struct StartupProfileReport: Codable, Sendable {
    let generatedAt: String
    let totalMs: Double
    let phases: [StartupPhaseTiming]
    let servers: [StartupServerTiming]

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case totalMs = "total_ms"
        case phases
        case servers
    }
}

@MainActor
final class StartupProfiler {
    static let shared = StartupProfiler()

    private struct MutableServerTiming {
        let name: String
        var spawnMs: Double = 0
        var handshakeMs: Double = 0
        var toolsDiscovered: Int = 0
        var toolsDiscoveryMs: Double = 0
        var totalMs: Double = 0
    }

    private let dateFormatter: ISO8601DateFormatter
    private let profilePath = PathManager.shared.startupProfileFile.path

    private var startupStart: CFAbsoluteTime
    private var phaseStarts: [String: [CFAbsoluteTime]] = [:]
    private var phaseTimings: [StartupPhaseTiming] = []
    private var serverTimings: [String: MutableServerTiming] = [:]
    private var firstSceneRenderRecorded = false

    private(set) var lastReport: StartupProfileReport?

    private init() {
        self.startupStart = CFAbsoluteTimeGetCurrent()
        self.dateFormatter = ISO8601DateFormatter()
        self.dateFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    }

    func reset() {
        startupStart = CFAbsoluteTimeGetCurrent()
        phaseStarts.removeAll(keepingCapacity: true)
        phaseTimings.removeAll(keepingCapacity: true)
        serverTimings.removeAll(keepingCapacity: true)
        firstSceneRenderRecorded = false
        lastReport = nil
    }

    func begin(_ label: String) {
        var starts = phaseStarts[label, default: []]
        starts.append(CFAbsoluteTimeGetCurrent())
        phaseStarts[label] = starts
    }

    func end(_ label: String) {
        guard var starts = phaseStarts[label], let start = starts.popLast() else {
            return
        }

        if starts.isEmpty {
            phaseStarts.removeValue(forKey: label)
        } else {
            phaseStarts[label] = starts
        }

        let end = CFAbsoluteTimeGetCurrent()
        appendPhase(label: label, start: start, end: end)
    }

    func markInstant(_ label: String) {
        let now = CFAbsoluteTimeGetCurrent()
        appendPhase(label: label, start: now, end: now)
    }

    func recordFirstSceneRenderIfNeeded() {
        guard !firstSceneRenderRecorded else { return }
        firstSceneRenderRecorded = true
        markInstant("firstSceneRender")
    }

    func recordServerStartup(name: String, spawnMs: Double, handshakeMs: Double, totalMs: Double) {
        var timing = serverTimings[name] ?? MutableServerTiming(name: name)
        timing.spawnMs = max(0, spawnMs)
        timing.handshakeMs = max(0, handshakeMs)
        timing.totalMs = max(0, totalMs)
        serverTimings[name] = timing
    }

    func recordToolDiscovery(name: String, toolCount: Int, durationMs: Double) {
        var timing = serverTimings[name] ?? MutableServerTiming(name: name)
        timing.toolsDiscovered = max(0, toolCount)
        timing.toolsDiscoveryMs = max(0, durationMs)
        serverTimings[name] = timing
    }

    @discardableResult
    func completeStartup() -> StartupProfileReport {
        endOpenPhases()

        let now = CFAbsoluteTimeGetCurrent()
        let totalMs = max(0, (now - startupStart) * 1000)

        let phases = phaseTimings.sorted { lhs, rhs in
            if lhs.startMs == rhs.startMs {
                return lhs.label < rhs.label
            }
            return lhs.startMs < rhs.startMs
        }

        let servers = serverTimings.values
            .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
            .map { timing in
                StartupServerTiming(
                    name: timing.name,
                    spawnMs: timing.spawnMs,
                    handshakeMs: timing.handshakeMs,
                    toolsDiscovered: timing.toolsDiscovered,
                    toolsDiscoveryMs: timing.toolsDiscoveryMs,
                    totalMs: timing.totalMs
                )
            }

        let report = StartupProfileReport(
            generatedAt: dateFormatter.string(from: Date()),
            totalMs: totalMs,
            phases: phases,
            servers: servers
        )

        lastReport = report
        writeReport(report)
        return report
    }

    func loadReportFromDisk() -> StartupProfileReport? {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: profilePath)) else {
            return nil
        }
        let decoder = JSONDecoder()
        let report = try? decoder.decode(StartupProfileReport.self, from: data)
        if let report {
            lastReport = report
        }
        return report
    }

    func reportJSONString(prettyPrinted: Bool = false) -> String {
        let report = lastReport ?? completeStartup()
        let encoder = JSONEncoder()
        if prettyPrinted {
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        } else {
            encoder.outputFormatting = [.sortedKeys]
        }
        if let data = try? encoder.encode(report), let json = String(data: data, encoding: .utf8) {
            return json
        }
        return "{}"
    }

    func topSlowPhases(limit: Int) -> [StartupPhaseTiming] {
        let report = lastReport
        let phases = (report?.phases ?? phaseTimings)
        return phases
            .sorted { lhs, rhs in
                if lhs.durationMs == rhs.durationMs {
                    return lhs.label < rhs.label
                }
                return lhs.durationMs > rhs.durationMs
            }
            .prefix(max(0, limit))
            .map { $0 }
    }

    private func appendPhase(label: String, start: CFAbsoluteTime, end: CFAbsoluteTime) {
        let startMs = max(0, (start - startupStart) * 1000)
        let endMs = max(startMs, (end - startupStart) * 1000)
        let durationMs = max(0, (end - start) * 1000)
        phaseTimings.append(
            StartupPhaseTiming(label: label, startMs: startMs, endMs: endMs, durationMs: durationMs)
        )
    }

    private func endOpenPhases() {
        let now = CFAbsoluteTimeGetCurrent()
        for (label, starts) in phaseStarts {
            for start in starts {
                appendPhase(label: label, start: start, end: now)
            }
        }
        phaseStarts.removeAll(keepingCapacity: true)
    }

    private func writeReport(_ report: StartupProfileReport) {
        guard let data = try? JSONEncoder().encode(report) else { return }

        let url = URL(fileURLWithPath: profilePath)
        let directory = url.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
    }
}
