// swift-tools-version: 6.2
import PackageDescription

// NOTE: Only ShipyardBridgeLib, ShipyardBridge, and ShipyardBridgeTests live here.
// The Shipyard app and ShipyardTests are built by Shipyard.xcodeproj.
// This package is added as a local dependency in the Xcode project so that
// ShipyardBridgeTests can be run from Xcode's Test Navigator (Cmd+U).

let package = Package(
    name: "ShipyardBridgePackage",
    platforms: [
        .macOS(.v26)
    ],
    products: [
        .library(
            name: "ShipyardBridgeLib",
            targets: ["ShipyardBridgeLib"]
        ),
    ],
    targets: [
        .target(
            name: "ShipyardBridgeLib",
            path: "ShipyardBridgeLib"
        ),
        .executableTarget(
            name: "ShipyardBridge",
            dependencies: ["ShipyardBridgeLib"],
            path: "ShipyardBridge"
        ),
        .testTarget(
            name: "ShipyardBridgeTests",
            dependencies: ["ShipyardBridgeLib"],
            path: "ShipyardBridgeTests"
        ),
    ]
)
