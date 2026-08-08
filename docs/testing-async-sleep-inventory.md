# SPEC-BUG-162 sleep inventory

This inventory records all 24 `time.Sleep` calls present before the change.
All entries were replaced with timer receives so no `time.Sleep` remains in
test code. The wait loops retain their explicit bounded condition and their
existing timeout diagnostic.

| Owner | Original locations | Classification | Replacement / maximum bound |
| --- | --- | --- | --- |
| `internal/proxy` | `proxy_additional_test.go` (2), `proxy_more_test.go` (2), `schema_watcher_test.go` (1), `manager_test.go` (3) | unit async state observation | timer-driven recheck of the named writer/store/request/watcher condition; 2–10 s enclosing deadlines |
| `internal/proxy` | `proxy_run_test.go` (1) | child-process polling exception | `waitForFile`; 10 ms interval, 2 s deadline, path diagnostic |
| `internal/web` | `web_extra_test.go` (9) | hub/server state observation | timer-driven recheck of named client registration/unregistration condition; 2–3 s enclosing deadlines |
| `cmd/shipyard` | `desktop_test.go` (1) | local listener readiness exercise | bounded `waitForServer`; 2 s deadline |
| `cmd/shipyard` | `e2e_smoke_test.go` (1) | real process polling exception | `waitForHTTP`; 50 ms interval, 20 s deadline, URL and last-error diagnostic |
| `cmd/shipyard-mcp` | `main_test.go` (4) | HTTP timeout/policy-watch behavior | test-server timeout simulation or timer-driven state observation; 2–6 s enclosing deadlines |
