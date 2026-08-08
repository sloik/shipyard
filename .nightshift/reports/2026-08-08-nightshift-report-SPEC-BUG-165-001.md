# SPEC-BUG-165-001 — Runtime configuration report

## Outcome

Completed after a parent takeover recovery. The requested per-tool setting is
present in the active untracked runtime configuration, and the launchd-managed
Shipyard process now applies the 81-second override to `mole_clean` while the
unconfigured-tool boundary retains the 30-second default.

## Change

The external runtime artifact `/Users/ed/servers.json` was backed up before the
edit at:

`/Users/ed/.argo-runtime-config-backups/servers.json.SPEC-BUG-165-001.20260808T085914Z.bak`

Its only change is:

```diff
+      "tools": {
+        "mole_clean": {
+          "response_timeout_seconds": 81
+        }
+      }
```

The artifact is intentionally untracked; it is not included in this commit.
`jq empty` validated the edited JSON, and a structural comparison found exactly
one added path: `servers.lmac-run.tools`.

## Runtime evidence

- `launchctl print gui/$(id -u)/com.argo.shipyard.app.canonical` reports a
  running service with `--config /Users/ed/servers.json` after `kickstart -k`.
- `/api/servers` reported `lmac-run` online after the restart.
- `/api/gateway/tools` listed `lmac-run__mole_clean`.
- The live dry-run request
  `POST /api/tools/call` with
  `{"server":"lmac-run","tool":"mole_clean","arguments":{"mode":"dry_run"}}`
  returned HTTP 502 after 30.003 seconds:

  ```text
  timeout waiting for response from "lmac-run" after 30s
  ```

  Therefore AC-2 is not met, and the same result confirms the live process is
  retaining the default 30-second behavior rather than using the configured
  81-second override.

- In the isolated worktree, the per-tool boundary introduced by
  SPEC-BUG-164-001 is present and validated:

  ```text
  go test ./internal/proxy -run 'Test.*(Timeout|timeout)' -count=1 -v
  PASS
  ```

  This includes `TestManagedProxyResponseTimeout_OnlyConfiguredToolCallUsesOverride`,
  whose unconfigured-tool subtest preserves the 30-second default (AC-3 at the
  implementation boundary).

## Smallest next unblock

Deploy the current Shipyard binary containing SPEC-BUG-164-001's per-tool
response-timeout support, then restart the canonical launchd service and rerun
the `mole_clean` dry-run. No Shipyard source change or Mole policy change is
needed for this spec.

## Parent takeover recovery

- `make deploy-runtime` passed both browser smoke suites and built/replaced
  `bin/shipyard`, but its unconditional `launchctl bootstrap` failed with error
  5 because `com.argo.shipyard.app.canonical` was already loaded.
- The existing canonical label was restarted with `launchctl kickstart -k`; its
  PID changed from `73869` to `81012`, proving a new process loaded the binary.
- The exact live `mole_clean` dry-run returned HTTP 200 in 77.363 seconds with
  return code 0. This exceeds the former 30-second ceiling and is inside the
  configured 81-second timeout, satisfying AC-1 and AC-2.
- `TestManagedProxyResponseTimeout_OnlyConfiguredToolCallUsesOverride` passed
  and includes the unconfigured-tool 30-second control, satisfying AC-3.
- Runtime config backup remains at
  `/Users/ed/.argo-runtime-config-backups/servers.json.SPEC-BUG-165-001.20260808T085914Z.bak`.

## Suggested Follow-up Specs

- Make canonical runtime deployment idempotent when the canonical launchd
  label is already loaded, while preserving rollback behavior.
