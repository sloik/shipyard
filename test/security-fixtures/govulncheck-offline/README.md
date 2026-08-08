# Locked Offline govulncheck Fixture

This self-contained module has a vendored `example.com/locked-vulnerable`
dependency at `v0.0.1`. Its `main` package calls `Reachable`, which is listed
in the checked-in `vulndb/ID/GO-SHIPYARD-0001.json` advisory.

`make security-self-test` runs the pinned `govulncheck` with this fixture's
`file://` database and with `GOPROXY=off`, `GOSUMDB=off`, and `GOVCS=*:off`.
The command must fail and name `GO-SHIPYARD-0001`; a pass or a missing locked
advisory is a self-test failure. The production `security-govulncheck` target
remains unchanged and continues to use its normal advisory database.
