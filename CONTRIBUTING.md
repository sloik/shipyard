# Contributing to Shipyard

## Philosophy: AI-Authored Code

Shipyard is built entirely by AI agents directed by human intent. We believe the future of software development is humans deciding *what* to build and *why*, while AI handles the *how*. Every line of code in this repo was written by an AI assistant, and we intend to keep it that way.

**We accept pull requests authored by AI tools only.** This includes code written with Claude Code, GitHub Copilot, Cursor, Aider, or any other AI coding assistant. The human's role is to define the problem, review the output, and decide whether to merge — not to write the implementation by hand.

This isn't a limitation — it's a design choice. AI-authored code is reproducible, spec-driven, and testable by default. It also means anyone can contribute regardless of their programming experience, as long as they can clearly describe what needs to change.

## Workflow

Shipyard changes should be scoped to a spec or bugfix request. For non-trivial work, start from a Nightshift spec in `.nightshift/specs/` and keep implementation aligned with its acceptance criteria.

## Pull Requests

1. Keep each pull request focused on one spec or bugfix.
2. Describe the problem, the files changed, and how you validated the result.
3. State which AI tool was used to author the code.
4. Include screenshots for UI changes when relevant.
5. Call out any follow-up work explicitly instead of silently expanding scope.

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
