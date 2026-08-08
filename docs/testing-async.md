# Deterministic asynchronous test policy

Tests must wait for an observable condition, never use `time.Sleep` as a
completion signal. A bounded wait must state the condition it is observing and
report the last observed state when its deadline expires.

The only polling exception is a real child-process or browser E2E boundary
whose protocol cannot expose readiness. Such polling must use a bounded
deadline, a short interval, and diagnostic context naming the external target.
`internal/proxy/proxy_run_test.go:waitForFile` and
`cmd/shipyard/e2e_smoke_test.go:waitForHTTP` are the approved exceptions.

Worker-lifecycle tests should use component completion channels or context
cancellation and assert that the owned worker exits. Do not assert a global
goroutine total.

The current lifecycle gates are `TestHub_RunClosesClientsOnCancel`,
`TestRun_RealSubprocessContextCancellationStopsBlockedChild`, and the access-log
drain assertions in `internal/auth/middleware_test.go`. Together they prove
subscription cleanup, child-process cancellation, and queued access-log work
completion without relying on a global goroutine count.
