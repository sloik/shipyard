import Foundation
import Testing
@testable import Shipyard

@Suite("SPEC-021: Startup Profiling", .timeLimit(.minutes(1)))
@MainActor
struct SPEC021Tests {

    @Test("Startup report contains required phase and server timing fields")
    func startupReportContainsRequiredFields() {
        let profiler = StartupProfiler.shared
        profiler.reset()

        profiler.begin("registry.init")
        profiler.end("registry.init")

        profiler.recordServerStartup(name: "alpha", spawnMs: 120, handshakeMs: 340, totalMs: 900)
        profiler.recordToolDiscovery(name: "alpha", toolCount: 4, durationMs: 210)

        let report = profiler.completeStartup()

        #expect(report.totalMs >= 0)
        #expect(!report.phases.isEmpty)
        #expect(report.phases.contains(where: { $0.label == "registry.init" }))

        let alpha = report.servers.first(where: { $0.name == "alpha" })
        #expect(alpha != nil)
        #expect(alpha?.spawnMs == 120)
        #expect(alpha?.handshakeMs == 340)
        #expect(alpha?.toolsDiscovered == 4)
        #expect(alpha?.totalMs == 900)
    }

    @Test("topSlowPhases returns descending durations")
    func topSlowPhasesSortsByDuration() {
        let profiler = StartupProfiler.shared
        profiler.reset()

        profiler.begin("fast")
        profiler.end("fast")

        profiler.begin("medium")
        Thread.sleep(forTimeInterval: 0.01)
        profiler.end("medium")

        profiler.begin("slow")
        Thread.sleep(forTimeInterval: 0.02)
        profiler.end("slow")

        _ = profiler.completeStartup()
        let top = profiler.topSlowPhases(limit: 2)

        #expect(top.count == 2)
        #expect(top[0].durationMs >= top[1].durationMs)
    }

    @Test("Profiler persists and reloads startup report from disk")
    func profilerPersistsAndLoadsReport() {
        let profiler = StartupProfiler.shared
        profiler.reset()
        profiler.begin("startup")
        profiler.end("startup")
        _ = profiler.completeStartup()

        let loaded = profiler.loadReportFromDisk()
        #expect(loaded != nil)
        #expect((loaded?.totalMs ?? -1) >= 0)
    }
}
