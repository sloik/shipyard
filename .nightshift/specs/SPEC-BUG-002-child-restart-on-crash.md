---
id: SPEC-BUG-002
priority: 2
type: bugfix
status: done
after: [SPEC-001]
created: 2026-04-04
---

# SPEC-BUG-002: Child Process Not Auto-Restarted After Crash

## Problem

When a child MCP server crashes, the proxy logs "child crashed, proxy remains running" and waits for SIGTERM. It should attempt to restart the child process so the proxy remains functional without manual intervention.

## Current Behavior

`proxy.go:108-112` — after child exits, if context is still active, the proxy blocks on `<-ctx.Done()`. No restart attempt.

## Expected Behavior

After child crash:
1. Log the crash with exit code
2. Wait a short backoff (1s, then 2s, then 4s, capped at 30s)
3. Respawn the child process
4. Resume proxying
5. After 5 consecutive crashes within 60 seconds, give up and log a fatal message

## Target Files

- `internal/proxy/proxy.go` — add restart loop with exponential backoff

## Acceptance Criteria

- [ ] AC-1: Child process is restarted automatically after crash
- [ ] AC-2: Exponential backoff between restarts (1s, 2s, 4s, ..., 30s cap)
- [ ] AC-3: After 5 crashes in 60 seconds, proxy logs error and stops restarting
- [ ] AC-4: Restart events are logged at INFO level
- [ ] AC-5: Traffic capture resumes after restart without data loss
