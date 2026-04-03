# Contributing to Shipyard

## Workflow

Shipyard changes should be scoped to a spec or bugfix request. For non-trivial work, start from a Nightshift spec in `.nightshift/specs/` and keep implementation aligned with its acceptance criteria.

## Pull Requests

1. Keep each pull request focused on one spec or bugfix.
2. Describe the problem, the files changed, and how you validated the result.
3. Include screenshots for UI changes when relevant.
4. Call out any follow-up work explicitly instead of silently expanding scope.

## Code Style

- SwiftUI app code lives under `Shipyard/`; shared bridge code lives under `ShipyardBridgeLib/`.
- Follow the existing Swift 6 patterns: `@MainActor`, `@Observable`, and structured concurrency instead of Combine.
- Prefer small, targeted edits over broad refactors.
- Do not hardcode machine-specific paths or plaintext credentials. Use runtime resolution or configuration overrides instead.

## Testing

- Build with `xcodebuild build -project Shipyard.xcodeproj -scheme Shipyard -destination 'platform=macOS' -quiet`.
- Run relevant test coverage with `xcodebuild test -project Shipyard.xcodeproj -scheme Shipyard -destination 'platform=macOS' -quiet`.
- Use synthetic fixture values only. Do not commit real tokens, API keys, personal directories, or local machine secrets.

## Spec Discipline

- Do not edit unrelated specs to make a change fit.
- If implementation reveals a spec gap, update the active spec or document the follow-up separately.
- Keep Nightshift protocol files (`LOOP.md`, `BOOTSTRAP.md`, `ORCHESTRATOR.md`, and related kit files) unchanged unless a spec explicitly targets them.

## Public Release Hygiene

- Keep `.env`, key files, exported credentials, and Xcode user state out of the repo.
- Before a public release, audit tracked files and git history for personal paths and secrets.
- If repository history has not been scrubbed, prefer a squashed initial public import over exposing unsanitized history.
