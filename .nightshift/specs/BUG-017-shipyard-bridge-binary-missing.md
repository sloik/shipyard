---
id: BUG-017
priority: 1
layer: 1
type: bugfix
status: done
after: []
violates: [SPEC-019]
prior_attempts: []
created: 2026-03-31
---

# ShipyardBridge Symlink Stale — DerivedData Binary Gone

## Symptom

Shipyard shows as **failed** in Claude Desktop / Cowork MCP panel with error `Server disconnected`. The logs show:

```
Failed to spawn process: No such file or directory
Command: ~/.shipyard/bin/ShipyardBridge
```

## Root Cause (Confirmed)

The install mechanism is a **symlink to DerivedData**, created by the Xcode "Symlink to stable path" build phase in the ShipyardBridge target:

```bash
STABLE_DIR="${HOME}/.shipyard/bin"
mkdir -p "${STABLE_DIR}"
ln -sf "${BUILT_PRODUCTS_DIR}/${EXECUTABLE_PATH}" "${STABLE_DIR}/ShipyardBridge"
```

The symlink exists and was created correctly:
```
~/.shipyard/bin/ShipyardBridge
  → ~/Library/Developer/Xcode/DerivedData/Shipyard-.../Build/Products/Debug/ShipyardBridge
```

But **the DerivedData binary is gone** — the target of the symlink doesn't exist. This happens whenever DerivedData is cleaned (Xcode → Product → Clean Build Folder, or `xcodebuild clean`). The symlink stays, the binary is deleted, and Claude gets `No such file or directory`.

## Immediate Fix (Manual)

Rebuild the ShipyardBridge target in Xcode (⌘B). The build phase recreates the symlink and the DerivedData binary comes back. No other action needed — the symlink already points to the right place.

Verify:
```bash
ls -la ~/.shipyard/bin/ShipyardBridge   # should show the symlink and resolve
file ~/.shipyard/bin/ShipyardBridge     # should say "Mach-O 64-bit executable"
```

## Permanent Fix — Replace Symlink with Copy

The symlink approach is fragile: any `Clean Build Folder` breaks Claude connectivity until the next rebuild. The fix is to **copy** the binary to `~/.shipyard/bin/` instead of symlinking it, so it survives DerivedData cleans.

Change the Xcode build phase script from:
```bash
ln -sf "${BUILT_PRODUCTS_DIR}/${EXECUTABLE_PATH}" "${STABLE_DIR}/ShipyardBridge"
```
to:
```bash
cp -f "${BUILT_PRODUCTS_DIR}/${EXECUTABLE_PATH}" "${STABLE_DIR}/ShipyardBridge"
```

**Trade-off:** `cp` means `~/.shipyard/bin/ShipyardBridge` can be stale after a rebuild until the build phase runs again (i.e., always after a build). With `ln -sf`, the symlink always reflects the freshest DerivedData binary — but only while DerivedData exists. Given that Clean Build Folder is a common troubleshooting action, copy is more resilient.

## Acceptance Criteria

- [x] Xcode build phase in ShipyardBridge target uses `cp -f` instead of `ln -sf`
- [x] After a clean build (`Product → Clean Build Folder` → `⌘B`), `~/.shipyard/bin/ShipyardBridge` is a real binary (not a symlink or dangling symlink)
- [x] `file ~/.shipyard/bin/ShipyardBridge` reports `Mach-O 64-bit executable arm64`
- [ ] Shipyard MCP shows as **connected** in Claude Desktop / Cowork after the fix
- [x] No more `Failed to spawn process: No such file or directory` after a clean build cycle
- [x] Build succeeds with zero errors; all existing tests pass

## References

- SPEC-019: Standard MCP Registration — introduced ShipyardBridge as the Claude-facing stdio bridge
- Xcode build phase location: ShipyardBridge target → Build Phases → "Symlink to stable path"
