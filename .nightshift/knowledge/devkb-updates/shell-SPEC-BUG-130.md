# DevKB Update Proposal — shell.md

## Wails v3 macOS release tasks should fail before signing when credentials are absent

**Problem:** A Wails v3 project can have a working raw desktop build while
`wails3 package` / `wails3 sign` do nothing useful or fail obscurely if the
project has not defined the platform tasks and credential checks.

**Root Cause:** Wails v3 delegates packaging/signing to Taskfile tasks such as
`darwin:package`, `darwin:sign`, and `darwin:sign:notarize`. If the repository
does not define those tasks, the wrapper fails with a generic missing-task error.
If signing tasks do not validate environment upfront, maintainers only discover
missing Apple credentials after a partial build or codesign invocation.

**Fix:** Add explicit platform tasks and keep raw `wails3 task build` separate
from release signing. For macOS signing, check `SHIPYARD_MACOS_SIGN_IDENTITY`
or `SIGN_IDENTITY` before running `codesign`; for notarization, check
`SHIPYARD_MACOS_NOTARY_PROFILE` or `KEYCHAIN_PROFILE` before `notarytool`.

**Prevention:** For Wails v3 packaging specs, validate all three surfaces:
`wails3 task build` for raw local builds, `wails3 package GOOS=darwin` for an
unsigned `.app`, and a missing-credentials signing invocation that exits with a
clear maintainer-facing message.
