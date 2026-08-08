# SPEC-BUG-165-001 — Runtime configuration report

## Outcome

Blocked at runtime. The requested per-tool setting is present in the active
untracked runtime configuration, but the launchd-managed Shipyard binary still
applies the former 30-second default to `mole_clean`.

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
