/// Regression guard for the Commands-environment crash.
///
/// Previously, `ShipyardCommands` used `@Environment` to access Observable objects
/// (`MCPRegistry`, `ProcessManager`, `LogStore`). Since `Commands` live at the Scene level
/// outside the view hierarchy, the environment is empty, causing a fatal crash at launch.
///
/// The fix was to replace `@Environment` declarations with `let` stored properties
/// passed via the initializer. These tests verify that the fix is in place:
///
/// 1. **Compile-time guard**: Test 1 instantiates `ShipyardCommands` with explicit parameters.
///    If anyone adds `@Environment` back, the memberwise initializer signature changes and
///    this test will NOT compile, catching the regression immediately.
///
/// 2. **Reference identity**: Test 2 verifies that the stored properties hold references
///    to the exact objects passed in (not Environment-wrapped copies).
///
/// 3. **Mirror inspection**: Test 3 uses Mirror to ensure the stored properties are
///    Observable objects directly, not wrapped in an Environment type.

import Testing
import Foundation
@testable import Shipyard

@Suite("ShipyardCommands")
@MainActor
struct ShipyardCommandsTests {
    /// Test 1: ShipyardCommands accepts explicit dependencies.
    ///
    /// If someone changes the initializer back to `@Environment`, this test will not compile,
    /// catching the regression immediately.
    @Test
    @available(macOS 14.0, *)
    func commandsAcceptsExplicitDependencies() {
        let registry = MCPRegistry()
        let processManager = ProcessManager()
        let logStore = LogStore()

        // This line will not compile if someone adds `@Environment` back to the struct
        let commands = ShipyardCommands(
            registry: registry,
            processManager: processManager,
            logStore: logStore
        )

        #expect(true)
    }

    /// Test 2: ShipyardCommands stores references correctly.
    ///
    /// Verifies that the stored properties hold references to the exact objects passed in.
    @Test
    @available(macOS 14.0, *)
    func commandsStoresReferencesCorrectly() {
        let registry = MCPRegistry()
        let processManager = ProcessManager()
        let logStore = LogStore()

        let commands = ShipyardCommands(
            registry: registry,
            processManager: processManager,
            logStore: logStore
        )

        // Verify reference identity — these are class types, so === checks object identity
        #expect(commands.registry === registry)
        #expect(commands.processManager === processManager)
        #expect(commands.logStore === logStore)
    }

    /// Test 3: ShipyardCommands does not use @Environment for core dependencies.
    ///
    /// Uses Mirror to inspect stored properties and verify they are Observable objects
    /// directly, not wrapped in an Environment type.
    @Test
    @available(macOS 14.0, *)
    func commandsDoesNotUseEnvironmentForDependencies() {
        let registry = MCPRegistry()
        let processManager = ProcessManager()
        let logStore = LogStore()

        let commands = ShipyardCommands(
            registry: registry,
            processManager: processManager,
            logStore: logStore
        )

        let mirror = Mirror(reflecting: commands)

        // Collect property names and their types
        var propertyTypes: [String: String] = [:]
        for child in mirror.children {
            if let label = child.label {
                let valueType = String(describing: type(of: child.value))
                propertyTypes[label] = valueType
            }
        }

        // Verify that the three key properties exist and are the correct types
        #expect(propertyTypes["registry"] == "MCPRegistry")
        #expect(propertyTypes["processManager"] == "ProcessManager")
        #expect(propertyTypes["logStore"] == "LogStore")

        // Verify that none of them contain "Environment" in the type name
        for (label, typeString) in propertyTypes {
            if ["registry", "processManager", "logStore"].contains(label) {
                #expect(
                    !typeString.contains("Environment"),
                    "Property '\(label)' should not be wrapped in Environment, but type is: \(typeString)"
                )
            }
        }
    }
}
